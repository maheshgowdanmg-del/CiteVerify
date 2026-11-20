"""Utility functions for text processing, fuzzy matching, numerical extraction,
JSON cleanup, and UI badge rendering.
"""
from __future__ import annotations

import re
import html
import json
import hashlib
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from . import config


def calculate_hash(content: bytes) -> str:
    """Calculate SHA256 hash of file content."""
    return hashlib.sha256(content).hexdigest()[:16]


def clean_doi(raw: str) -> str:
    """Extract and normalize a standard clean DOI string."""
    if not raw:
        return ""
    raw = raw.strip()
    # Match standard DOI prefix 10.xxxx/...
    match = re.search(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", raw)
    if match:
        clean = match.group(0).rstrip(".,;)>]")
        return clean
    # If the input was an explicit short DOI or test string (like 'invalid_string' or '10.xxxx')
    if len(raw) < 80 and not any(sep in raw for sep in ("\n", ". (", ", &", "et al", "References")):
        return raw.replace("https://doi.org/", "").replace("http://dx.doi.org/", "").strip()
    return ""


def fuzzy_similarity(a: str, b: str) -> float:
    """Calculate normalized similarity ratio between two strings (0.0 to 1.0)."""
    if not a or not b:
        return 0.0
    s_a = re.sub(r"[^\w\s]", "", a.lower()).strip()
    s_b = re.sub(r"[^\w\s]", "", b.lower()).strip()
    return round(SequenceMatcher(None, s_a, s_b).ratio(), 3)


def extract_numbers_from_text(text: str) -> List[Dict[str, Any]]:
    """Extract numerical quantities, percentages, sample sizes, and statistics from text."""
    if not text:
        return []
    
    found: List[Dict[str, Any]] = []
    seen_spans = set()
    
    # 1. Percentages (e.g. 45%, 32.5 percent, 95.0%)
    for m in re.finditer(r"(\b\d+(?:\.\d+)?)\s*(%|percent\b)", text, flags=re.I):
        val = float(m.group(1))
        seen_spans.add((m.start(), m.end()))
        found.append({"raw": m.group(0), "value": val, "unit": "%", "type": "percentage"})
    
    # 2. AUC / ROC / P-values (e.g. AUC of 0.945, p < 0.05, p=0.001)
    for m in re.finditer(r"\b(auc|p|r2)\s*(?:of|=|<|>|<=|>=)\s*(\d+(?:\.\d+)?)\b", text, flags=re.I):
        val = float(m.group(2))
        seen_spans.add((m.start(), m.end()))
        found.append({"raw": m.group(0), "value": val, "unit": m.group(1).upper(), "type": "statistical"})
        
    # 3. Sample sizes (e.g. n = 1,420, 500 patients, 120 subjects)
    for m in re.finditer(r"\b(?:n\s*=\s*|sample\s*of\s*)(\d[\d,]*)\b", text, flags=re.I):
        num_str = m.group(1).replace(",", "")
        seen_spans.add((m.start(), m.end()))
        found.append({"raw": m.group(0), "value": float(num_str), "unit": "sample_size", "type": "cohort"})

    # 4. Standalone decimal or integer measurements with scientific context
    for m in re.finditer(r"\b(\d+(?:\.\d+)?)\s*(fold|times|x|hours|days|years|mg|ml|bleu|glue|f1|accuracy|points?|billion|million|k|parameters?)\b", text, flags=re.I):
        val = float(m.group(1))
        seen_spans.add((m.start(), m.end()))
        found.append({"raw": m.group(0), "value": val, "unit": m.group(2).lower(), "type": "measurement"})

    # 5. Standalone decimal scores (e.g. 28.4, 35.0, 80.5, 90.5) not captured yet
    for m in re.finditer(r"\b(\d+\.\d+)\b", text):
        if not any(s <= m.start() and m.end() <= e for (s, e) in seen_spans):
            val = float(m.group(1))
            found.append({"raw": m.group(0), "value": val, "unit": "score", "type": "decimal_metric"})

    return found


def repair_json(raw: str) -> Optional[Any]:
    """Extract and parse valid JSON from LLM markdown code blocks or messy responses."""
    if not raw:
        return None
    raw = raw.strip()
    
    # Check for direct markdown fence ```json ... ```
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
    candidate = match.group(1).strip() if match else raw
    
    # Try parsing directly
    try:
        return json.loads(candidate)
    except Exception:
        pass
        
    # Attempt to locate outer brackets [ ... ] or { ... }
    b_start = candidate.find("[")
    b_end = candidate.rfind("]")
    c_start = candidate.find("{")
    c_end = candidate.rfind("}")
    
    if c_start != -1 and c_end != -1 and (b_start == -1 or c_start < b_start):
        try:
            return json.loads(candidate[c_start:c_end + 1])
        except Exception:
            pass
            
    if b_start != -1 and b_end != -1:
        try:
            return json.loads(candidate[b_start:b_end + 1])
        except Exception:
            pass
            
    return None


def highlight_passage(passage: str, quote: Optional[str] = None) -> str:
    """Highlight matched quote within an evidence passage with clean HTML."""
    if not passage:
        return ""
    safe_passage = html.escape(passage)
    if not quote or len(quote.strip()) < 4:
        return safe_passage
        
    words = [re.escape(html.escape(w)) for w in quote.split() if len(w) > 1]
    if not words:
        return safe_passage
        
    pattern = r"\s+".join(words[:15])  # search up to 15 contiguous words
    try:
        highlighted = re.sub(
            f"({pattern})",
            r"<mark style='background:#FEF08A;color:#854D0E;padding:2px 4px;border-radius:4px;font-weight:600;'>\1</mark>",
            safe_passage,
            count=1,
            flags=re.IGNORECASE
        )
        return highlighted
    except Exception:
        return safe_passage


def render_verdict_badge(verdict_key: str) -> str:
    """Generate professional HTML pill badge for a claim verdict."""
    v = config.VERDICTS.get(verdict_key, config.VERDICTS["NOT_ENOUGH_EVIDENCE"])
    return (
        f"<span style='display:inline-flex;align-items:center;gap:6px;background:{v['bg']};"
        f"color:{v['color']};border:1px solid {v['color']}40;border-radius:999px;"
        f"padding:3px 12px;font-size:0.82rem;font-weight:700;letter-spacing:0.02em;'>"
        f"{v['icon']} {v['label']}</span>"
    )


def render_citation_badge(status_key: str) -> str:
    """Generate professional HTML badge for citation fraud engine status."""
    c = config.CITATION_STATUSES.get(status_key, config.CITATION_STATUSES["UNVERIFIED"])
    return (
        f"<span style='display:inline-flex;align-items:center;gap:6px;background:{c['color']}15;"
        f"color:{c['color']};border:1px solid {c['color']}50;border-radius:8px;"
        f"padding:3px 10px;font-size:0.8rem;font-weight:600;'>"
        f"{c['icon']} {c['label']}</span>"
    )
