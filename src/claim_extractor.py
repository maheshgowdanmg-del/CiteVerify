"""Scientific Claim Extraction Engine for CiteVerify.
Extracts empirical scientific claims from document body text using multi-provider AI
(Gemini / Groq) with intelligent heuristic fallback.

Classifies claims into 7 categories:
- Statistical: Claims presenting statistical distributions, confidence intervals, p-values.
- Numerical: Claims asserting percentages, sample sizes, benchmark scores.
- Experimental: Direct outcomes of laboratory or clinical experiments.
- Causal: Claims proposing cause-and-effect mechanisms.
- Comparative: Claims contrasting two treatments, architectures, or cohorts.
- Scientific conclusion: Theoretical interpretations or synthesis of experimental findings.
- General factual: Background scientific context requiring literature citation.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from . import ai_provider, config
from .citation_parser import IN_TEXT_CITATION_REGEX
from .utils import extract_numbers_from_text, repair_json

logger = logging.getLogger(__name__)

CLAIM_TYPES = [
    "Statistical",
    "Numerical",
    "Experimental",
    "Causal",
    "Comparative",
    "Scientific conclusion",
    "General factual"
]


def classify_claim_type(text: str) -> str:
    """Classify a scientific claim into one of the 7 empirical categories."""
    t_l = text.lower()
    nums = extract_numbers_from_text(text)

    # 1. Statistical
    if re.search(r"\b(p\s*<|p\s*=|auc|roc|hazard ratio|confidence interval|std|variance|chi-square)\b", t_l):
        return "Statistical"

    # 2. Numerical
    if nums or re.search(r"\b(\d+%\s*|\bpercent\b|\bn\s*=\s*\d+|\d+\s*patients|\d+\s*samples)\b", t_l):
        return "Numerical"

    # 3. Comparative
    if re.search(r"\b(outperformed|higher than|superior to|compared to|versus|vs\.?|greater reduction|faster than)\b", t_l):
        return "Comparative"

    # 4. Causal
    if re.search(r"\b(caused by|leads to|induces|triggers|responsible for|resulting in|mediates)\b", t_l):
        return "Causal"

    # 5. Experimental
    if re.search(r"\b(trial|experiment|in vitro|in vivo|observed|measured|administered|protocol|randomized)\b", t_l):
        return "Experimental"

    # 6. Scientific conclusion
    if re.search(r"\b(conclude|demonstrates that|proves that|establishes that|indicates that|suggests that)\b", t_l):
        return "Scientific conclusion"

    return "General factual"


def extract_claims_with_gemini(body_text: str, max_claims: int = 25) -> List[Dict[str, Any]]:
    """Extract substantive scientific claims from document text using AI (Gemini / Groq) or heuristic fallback."""
    provider = config.get_active_provider()
    if provider == "offline" or not config.is_ai_configured():
        return extract_claims_heuristic(body_text, max_claims=max_claims)

    truncated_text = body_text[:18000]

    system_instruction = (
        "You are an academic integrity specialist identifying substantive empirical claims in research papers.\n"
        "Rules:\n"
        "1. Extract ONLY statements actually asserting scientific conclusions, empirical metrics, or findings.\n"
        "2. Associate each claim with its exact in-text citation marker (e.g. '[1]', '[2-3]', '(Author, 2020)').\n"
        "3. Categorize each claim into one of: 'Statistical', 'Numerical', 'Experimental', 'Causal', 'Comparative', 'Scientific conclusion', 'General factual'.\n"
        "4. DO NOT INVENT CLAIMS."
    )

    prompt = f"""Analyze this document body text and extract up to {max_claims} explicit empirical scientific claims.

DOCUMENT TEXT:
\"\"\"{truncated_text}\"\"\"

Return a valid JSON object matching this schema:
{{
  "claims": [
    {{
      "claim_id": "C1",
      "claim": "AI improves cancer detection accuracy by 35%.",
      "claim_type": "Numerical" | "Statistical" | "Experimental" | "Causal" | "Comparative" | "Scientific conclusion" | "General factual",
      "topic": "Medical AI Diagnostics",
      "numerical_values": ["35%"],
      "citation": "[1]",
      "context": "Brief surrounding context from the paragraph"
    }}
  ]
}}
"""

    parsed, provider_used, status = ai_provider.generate_structured_ai_response(
        prompt=prompt,
        system_instruction=system_instruction,
        json_mode=True,
        temperature=0.1
    )

    if parsed and isinstance(parsed, dict) and "claims" in parsed and isinstance(parsed["claims"], list):
        valid_claims = []
        for i, c in enumerate(parsed["claims"][:max_claims], 1):
            if not isinstance(c, dict) or not c.get("claim"):
                continue
            claim_str = c["claim"].strip()
            c_type = c.get("claim_type")
            if not c_type or c_type not in CLAIM_TYPES:
                c_type = classify_claim_type(claim_str)

            valid_claims.append({
                "claim_id": c.get("claim_id") or f"C{i}",
                "claim": claim_str,
                "claim_type": c_type,
                "topic": c.get("topic", "General Science"),
                "numerical_values": c.get("numerical_values") or [n["raw"] for n in extract_numbers_from_text(claim_str)],
                "citation": c.get("citation", ""),
                "citation_marker": c.get("citation", ""),
                "context": c.get("context", "")
            })
        if valid_claims:
            return valid_claims

    # Fallback to heuristic extraction
    logger.info(f"AI claim extraction returned {status}. Falling back to heuristic extractor.")
    return extract_claims_heuristic(body_text, max_claims=max_claims)


def extract_claims_heuristic(body_text: str, max_claims: int = 25) -> List[Dict[str, Any]]:
    """Deterministic regex and cue-based scientific claim extractor."""
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\[\(\"])", body_text)
    claims: List[Dict[str, Any]] = []

    claim_cues = [
        "demonstrate", "show", "found", "improved", "increased", "reduced",
        "decreased", "reported", "concluded", "revealed", "outperformed",
        "achieved", "accuracy", "sensitivity", "specificity", "survival",
        "significant", "associated with", "correlated", "degradation"
    ]

    for sent in sentences:
        s_clean = sent.strip()
        if len(s_clean) < 35 or len(s_clean) > 400:
            continue

        cites = IN_TEXT_CITATION_REGEX.findall(s_clean)
        has_cue = any(cue in s_clean.lower() for cue in claim_cues)
        has_number = bool(re.search(r"\d+(?:\.\d+)?%|\b\d+\b", s_clean))

        if cites or (has_cue and has_number):
            cid = f"C{len(claims) + 1}"
            cite_str = cites[0] if cites else ""
            c_type = classify_claim_type(s_clean)
            nums = [n["raw"] for n in extract_numbers_from_text(s_clean)]

            topic = "Empirical Research"
            if "cancer" in s_clean.lower() or "medical" in s_clean.lower() or "clinical" in s_clean.lower():
                topic = "Biomedical & Clinical"
            elif "battery" in s_clean.lower() or "energy" in s_clean.lower() or "solar" in s_clean.lower():
                topic = "Energy & Materials"
            elif "neural" in s_clean.lower() or "model" in s_clean.lower() or "ai" in s_clean.lower():
                topic = "Computer Science & AI"

            claims.append({
                "claim_id": cid,
                "claim": s_clean,
                "claim_type": c_type,
                "topic": topic,
                "numerical_values": nums,
                "citation": cite_str,
                "citation_marker": cite_str,
                "context": ""
            })

            if len(claims) >= max_claims:
                break

    return claims
