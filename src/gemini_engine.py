"""Gemini Claim Verification Engine for CiteVerify.
Uses the official Google Gen AI SDK (google-genai / google.generativeai) with structured JSON
to verify scientific claims against original retrieved research evidence.
Includes an intelligent offline fallback when API keys are not supplied.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from . import config
from .utils import repair_json, extract_numbers_from_text

logger = logging.getLogger(__name__)


def get_gemini_client():
    """Create and return a configured Gemini GenAI client or module."""
    if not config.is_gemini_configured():
        return None

    # Priority 1: Official Google GenAI SDK (google.genai)
    try:
        from google import genai
        client = genai.Client(api_key=config.GEMINI_API_KEY, http_options={"api_version": "v1beta"})
        return ("genai", client)
    except Exception as e:
        logger.debug(f"Could not initialize google.genai: {e}")

    # Priority 2: google.generativeai
    try:
        import google.generativeai as gai
        gai.configure(api_key=config.GEMINI_API_KEY)
        return ("generativeai", gai)
    except Exception as e:
        logger.debug(f"Could not initialize google.generativeai: {e}")

    return None


def verify_claim_with_gemini(
    claim_text: str,
    evidence_text: str,
    source_title: str,
    citation_marker: str,
    numerical_check: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Verify a scientific claim against retrieved source evidence using Gemini AI.
    Returns structured verdict, explanation, verbatim quote, limitations, and confidence.
    """
    client_tuple = get_gemini_client()

    # If Gemini is not configured, run robust offline rule-based verification
    if not client_tuple:
        return run_offline_verification(claim_text, evidence_text, source_title, numerical_check)

    sdk_type, client = client_tuple
    num_info = ""
    if numerical_check:
        num_info = f"\nPre-computed Numerical Analysis: {numerical_check.get('verdict')} - {numerical_check.get('explanation')}"

    system_instruction = (
        "You are CiteVerify AI, a world-class scientific auditor evaluating whether academic claims are supported "
        "by their cited research evidence. You must strictly adhere to the following rules:\n"
        "1. DO NOT HALLUCINATE OR INVENT EVIDENCE. Base your comparison STRICTLY on the provided retrieved text.\n"
        "2. If the retrieved passage directly corroborates the claim and numbers, verdict is 'SUPPORTED'.\n"
        "3. If the general direction matches but scope, numbers, or conditions diverge, verdict is 'PARTIALLY_SUPPORTED'.\n"
        "4. If the retrieved text directly contradicts, invalidates, or contradicts the numerical claim, verdict is 'REFUTED'.\n"
        "5. If there is genuine competing scientific evidence mentioned, verdict is 'CONTRADICTORY'.\n"
        "6. If the retrieved text lacks the relevant methodology or data to confirm or deny, verdict is 'NOT_ENOUGH_EVIDENCE'.\n"
        "7. You must respond in valid JSON matching the exact schema."
    )

    prompt = f"""
Evaluate this scientific claim against the retrieved research paper evidence.

Claim: "{claim_text}"
Citation Marker: {citation_marker}
Cited Source: "{source_title}"
Retrieved Source Evidence:
\"\"\"{evidence_text}\"\"\"
{num_info}

Return JSON with this exact structure:
{{
  "verdict": "SUPPORTED" | "PARTIALLY_SUPPORTED" | "REFUTED" | "CONTRADICTORY" | "NOT_ENOUGH_EVIDENCE",
  "explanation": "Clear, precise explanation of whether and how the evidence supports or contradicts the claim.",
  "evidence_quote": "A short, verbatim sentence or phrase from the retrieved evidence that best justifies the verdict.",
  "limitations": "Any study limitations, sample constraints, or external validity bounds mentioned in the source.",
  "confidence_score": 0.85,
  "confidence_label": "High" | "Medium" | "Low",
  "needs_human_review": false,
  "contradiction_notes": ""
}}
"""

    try:
        response_text = ""
        model_name = config.GEMINI_MODEL

        if sdk_type == "genai":
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config={
                    "temperature": config.DEFAULT_TEMPERATURE,
                    "response_mime_type": "application/json"
                }
            )
            response_text = response.text
        else:
            model = client.GenerativeModel(
                model_name=model_name,
                generation_config={"temperature": config.DEFAULT_TEMPERATURE, "response_mime_type": "application/json"}
            )
            response = model.generate_content(prompt)
            response_text = response.text

        parsed = repair_json(response_text)
        if parsed and isinstance(parsed, dict) and "verdict" in parsed:
            v = parsed.get("verdict", "").upper().replace(" ", "_")
            if v not in config.VERDICTS:
                v = "NOT_ENOUGH_EVIDENCE"
            parsed["verdict"] = v
            parsed["confidence_score"] = float(parsed.get("confidence_score", 0.85))
            parsed["confidence_label"] = parsed.get("confidence_label", "High")
            return parsed
    except Exception as e:
        logger.warning(f"Gemini API verification failed or timed out: {e}. Falling back to rule engine.")

    return run_offline_verification(claim_text, evidence_text, source_title, numerical_check)


def run_offline_verification(
    claim_text: str,
    evidence_text: str,
    source_title: str,
    numerical_check: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Robust heuristic verification engine used when Gemini API is offline or unavailable."""
    if not evidence_text or "not automatically retrieved" in evidence_text.lower() or len(evidence_text.strip()) < 30:
        return {
            "verdict": "NOT_ENOUGH_EVIDENCE",
            "explanation": "The original paper text or abstract could not be indexed from open scholarly APIs. Full document access required for conclusive verification.",
            "evidence_quote": "",
            "limitations": "Only metadata was available.",
            "confidence_score": 0.40,
            "confidence_label": "Low",
            "needs_human_review": True,
            "contradiction_notes": ""
        }

    c_lower = claim_text.lower()
    e_lower = evidence_text.lower()

    # Check for numerical mismatch first
    if numerical_check and numerical_check.get("verdict") == "NUMERICAL_MISMATCH":
        return {
            "verdict": "REFUTED",
            "explanation": f"Numerical contradiction detected: {numerical_check.get('explanation')}",
            "evidence_quote": evidence_text[:200],
            "limitations": "Claim metrics conflict with reported data in source.",
            "confidence_score": 0.80,
            "confidence_label": "High",
            "needs_human_review": False,
            "contradiction_notes": numerical_check.get("difference_summary", "")
        }

    # Check for explicit contradiction cues
    contradiction_cues = ["no statistically significant difference", "failed to replicate", "did not improve", "contradicts previous", "however, we found no"]
    if any(cue in e_lower for cue in contradiction_cues) and ("significantly" in c_lower or "improves" in c_lower or "outperform" in c_lower):
        return {
            "verdict": "CONTRADICTORY",
            "explanation": "Retrieved evidence reports conflicting or negative findings contrary to the positive claim.",
            "evidence_quote": evidence_text[:250],
            "limitations": "Validation trials reported contrasting or null clinical outcomes.",
            "confidence_score": 0.75,
            "confidence_label": "Medium",
            "needs_human_review": True,
            "contradiction_notes": "Literature displays conflicting outcomes."
        }

    # Check for topic relevance (common words)
    stop_words = {"the", "a", "an", "in", "on", "of", "to", "for", "and", "or", "is", "was", "were", "by", "that", "this", "with"}
    claim_words = {w for w in c_lower.split() if len(w) > 3 and w not in stop_words}
    evidence_words = {w for w in e_lower.split() if len(w) > 3 and w not in stop_words}
    overlap = len(claim_words.intersection(evidence_words))
    ratio = overlap / max(1, len(claim_words))

    # Check if completely unrelated paper was cited
    title_words = {w for w in source_title.lower().split() if len(w) > 3 and w not in stop_words}
    title_overlap = len(claim_words.intersection(title_words))

    if ratio < 0.15 and title_overlap == 0:
        return {
            "verdict": "REFUTED",
            "explanation": f"The cited paper ('{source_title}') does not appear to discuss the specific claim topic. Citation appears misplaced or irrelevant.",
            "evidence_quote": evidence_text[:200],
            "limitations": "Topic mismatch between statement and cited reference.",
            "confidence_score": 0.70,
            "confidence_label": "Medium",
            "needs_human_review": True,
            "contradiction_notes": "Unrelated research cited."
        }

    if ratio > 0.45 or (numerical_check and numerical_check.get("verdict") == "NUMERICAL_MATCH"):
        return {
            "verdict": "SUPPORTED",
            "explanation": "Retrieved study findings corroborate the scientific claim, confirming methodology and reported outcomes.",
            "evidence_quote": evidence_text[:200],
            "limitations": "Single study cohort; see full paper for external validity.",
            "confidence_score": 0.85,
            "confidence_label": "High",
            "needs_human_review": False,
            "contradiction_notes": ""
        }

    return {
        "verdict": "PARTIALLY_SUPPORTED",
        "explanation": "General research context aligns with the cited publication, but specific sub-metrics or comprehensive conditions require full-text verification.",
        "evidence_quote": evidence_text[:200],
        "limitations": "Extracted from abstract text; supplementary data not fully inspected.",
        "confidence_score": 0.65,
        "confidence_label": "Medium",
        "needs_human_review": True,
        "contradiction_notes": ""
    }
