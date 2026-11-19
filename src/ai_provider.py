"""Modular AI Provider Architecture for CiteVerify.
Supports:
1. Google Gemini (via google.genai / google.generativeai)
2. Groq (via groq SDK / OpenAI-compatible REST API)
3. Offline / Rule-Based Mode

Features:
- Safe SQLite caching by sha256(prompt + model + version)
- Exponential backoff for transient failures
- Quota / HTTP 429 rate limit detection (avoids hammering exhausted quotas)
- Clean JSON schema extraction and repair
- Connection testing and provider diagnostics
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import requests

from . import config
from .utils import repair_json

logger = logging.getLogger(__name__)

CACHE_VERSION = "v2_master"


def _get_cache_db():
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_cache (
            cache_key TEXT PRIMARY KEY,
            response_text TEXT,
            provider TEXT,
            model TEXT,
            created_at TEXT
        );
    """)
    conn.commit()
    return conn


def get_cached_response(cache_key: str) -> Optional[str]:
    """Retrieve cached LLM response if available."""
    try:
        conn = _get_cache_db()
        cur = conn.cursor()
        cur.execute("SELECT response_text FROM ai_cache WHERE cache_key = ?;", (cache_key,))
        row = cur.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        logger.debug(f"Cache read error: {e}")
        return None


def set_cached_response(cache_key: str, response_text: str, provider: str, model: str) -> None:
    """Store LLM response in persistent SQLite cache."""
    try:
        conn = _get_cache_db()
        cur = conn.cursor()
        now_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cur.execute("""
            INSERT OR REPLACE INTO ai_cache (cache_key, response_text, provider, model, created_at)
            VALUES (?, ?, ?, ?, ?);
        """, (cache_key, response_text, provider, model, now_ts))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.debug(f"Cache write error: {e}")


def compute_cache_key(prompt: str, model: str, provider: str) -> str:
    """Generate deterministic SHA256 cache key."""
    content = f"{CACHE_VERSION}:{provider}:{model}:{prompt.strip()}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------------
# Provider Invocation Engine
# ------------------------------------------------------------------------------

def call_gemini(
    prompt: str,
    system_instruction: str = "",
    model: str = "gemini-2.5-flash",
    api_key: str = "",
    temperature: float = 0.2,
    json_mode: bool = True
) -> Tuple[Optional[str], str]:
    """Call Google Gemini API using official SDKs with backoff and 429 quota handling."""
    if not api_key:
        return None, "NO_API_KEY"

    # Priority 1: Official google.genai SDK
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key, http_options={"api_version": "v1beta"})
        config_kwargs: Dict[str, Any] = {"temperature": temperature}
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction
        if json_mode:
            config_kwargs["response_mime_type"] = "application/json"

        cfg = types.GenerateContentConfig(**config_kwargs)

        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=cfg
                )
                if response and response.text:
                    return response.text.strip(), "SUCCESS"
            except Exception as err:
                err_str = str(err).lower()
                if "429" in err_str or "quota" in err_str or "exhausted" in err_str:
                    logger.warning("Gemini quota exceeded (HTTP 429). Will not retry.")
                    return None, "QUOTA_EXHAUSTED"
                if attempt == 0:
                    time.sleep(1.0)
                else:
                    logger.warning(f"Gemini SDK call failed: {err}")
    except ImportError:
        pass
    except Exception as e:
        err_msg = str(e).lower()
        if "429" in err_msg or "quota" in err_msg:
            return None, "QUOTA_EXHAUSTED"
        logger.debug(f"google.genai execution error: {e}")

    # Priority 2: google.generativeai legacy SDK
    try:
        import google.generativeai as gai
        gai.configure(api_key=api_key)
        gen_kwargs: Dict[str, Any] = {"temperature": temperature}
        if json_mode:
            gen_kwargs["response_mime_type"] = "application/json"
        
        m = gai.GenerativeModel(
            model_name=model,
            system_instruction=system_instruction if system_instruction else None,
            generation_config=gen_kwargs
        )
        res = m.generate_content(prompt)
        if res and res.text:
            return res.text.strip(), "SUCCESS"
    except Exception as e:
        err_str = str(e).lower()
        if "429" in err_str or "quota" in err_str:
            return None, "QUOTA_EXHAUSTED"
        logger.warning(f"google.generativeai failed: {e}")

    return None, "API_ERROR"


def call_groq(
    prompt: str,
    system_instruction: str = "",
    model: str = "llama-3.3-70b-versatile",
    api_key: str = "",
    temperature: float = 0.2,
    json_mode: bool = True
) -> Tuple[Optional[str], str]:
    """Call Groq API via SDK or OpenAI-compatible endpoint with backoff and rate-limit detection."""
    if not api_key:
        return None, "NO_API_KEY"

    # Try official Groq SDK first
    try:
        from groq import Groq
        client = Groq(api_key=api_key)
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        call_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            call_kwargs["response_format"] = {"type": "json_object"}

        for attempt in range(2):
            try:
                resp = client.chat.completions.create(**call_kwargs)
                if resp.choices and resp.choices[0].message.content:
                    return resp.choices[0].message.content.strip(), "SUCCESS"
            except Exception as err:
                err_s = str(err).lower()
                if "429" in err_s or "rate" in err_s or "quota" in err_s:
                    logger.warning("Groq rate limit exceeded (HTTP 429).")
                    return None, "QUOTA_EXHAUSTED"
                if attempt == 0:
                    time.sleep(1.0)
                else:
                    logger.warning(f"Groq SDK call failed: {err}")
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"Groq SDK initialization error: {e}")

    # Fallback to direct REST API
    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        r = requests.post(url, headers=headers, json=payload, timeout=20)
        if r.status_code == 200:
            data = r.json()
            return data["choices"][0]["message"]["content"].strip(), "SUCCESS"
        elif r.status_code == 429:
            return None, "QUOTA_EXHAUSTED"
        else:
            return None, f"HTTP_{r.status_code}"
    except Exception as ex:
        return None, f"REST_ERROR_{str(ex)[:30]}"


def generate_structured_ai_response(
    prompt: str,
    system_instruction: str = "",
    json_mode: bool = True,
    temperature: float = 0.2
) -> Tuple[Optional[Dict[str, Any]], str, str]:
    """Unified entry point for AI inference with caching and multi-provider support.
    Returns: (parsed_json_dict, provider_used, status_message)
    """
    provider = config.get_active_provider()
    api_key = config.get_active_api_key()
    model = config.get_active_model()

    if provider == "offline" or not api_key:
        return None, "offline", "OFFLINE_MODE"

    cache_k = compute_cache_key(prompt, model, provider)
    cached = get_cached_response(cache_k)
    if cached:
        parsed = repair_json(cached) if json_mode else {"text": cached}
        return parsed, provider, "CACHE_HIT"

    raw_text: Optional[str] = None
    status = "UNKNOWN"

    if provider == "gemini":
        raw_text, status = call_gemini(
            prompt, system_instruction=system_instruction,
            model=model, api_key=api_key, temperature=temperature, json_mode=json_mode
        )
    elif provider == "groq":
        raw_text, status = call_groq(
            prompt, system_instruction=system_instruction,
            model=model, api_key=api_key, temperature=temperature, json_mode=json_mode
        )
    else:
        status = "UNSUPPORTED_PROVIDER"

    if raw_text:
        set_cached_response(cache_k, raw_text, provider, model)
        parsed = repair_json(raw_text) if json_mode else {"text": raw_text}
        return parsed, provider, "SUCCESS"

    return None, provider, status


def test_ai_connection(
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None
) -> Tuple[bool, str]:
    """Test live connectivity to the specified or active AI provider."""
    target_provider = (provider or config.get_active_provider()).lower().strip()
    target_key = (api_key or config.get_active_api_key()).strip()
    target_model = (model or config.get_active_model()).strip()

    if target_provider == "offline":
        return True, "Offline mode is active. Rule-based heuristic verification will be used."

    if not target_key:
        return False, f"No API key provided for {target_provider.upper()}."

    test_prompt = 'Respond with JSON: {"status": "connected", "provider": "ok"}'

    try:
        if target_provider == "gemini":
            text, status = call_gemini(test_prompt, model=target_model or "gemini-2.5-flash", api_key=target_key)
            if status == "SUCCESS" and text:
                return True, f"Successfully connected to Google Gemini ({target_model or 'gemini-2.5-flash'})!"
            return False, f"Gemini connection failed: {status}"

        elif target_provider == "groq":
            text, status = call_groq(test_prompt, model=target_model or "llama-3.3-70b-versatile", api_key=target_key)
            if status == "SUCCESS" and text:
                return True, f"Successfully connected to Groq Cloud ({target_model or 'llama-3.3-70b-versatile'})!"
            return False, f"Groq connection failed: {status}"

        return False, f"Unsupported provider: {target_provider}"
    except Exception as e:
        return False, f"Connection test error: {str(e)}"
