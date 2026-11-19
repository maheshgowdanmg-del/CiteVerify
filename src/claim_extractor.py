"""Scientific Claim Extraction Engine for CiteVerify.
Uses Google Gemini API to extract substantive scientific and empirical claims with
associated citations, topics, and numerical metrics from document body text.
Includes a robust offline rule-based extractor when API is unavailable.
"""
from __future__ import annotations

import re
import json
import logging
from typing import Any, Dict, List, Optional

from . import config
from .gemini_engine import get_gemini_client
from .utils import repair_json, extract_numbers_from_text

logger = logging.getLogger(__name__)


def extract_claims_with_gemini(body_text: str, max_claims: int = 25) -> List[Dict[str, Any]]:
    """Use Gemini API to extract scientific claims, citations, and numerical metrics from text."""
    client_tuple = get_gemini_client()
    if not client_tuple:
        return extract_claims_heuristic(body_text, max_claims=max_claims)

    sdk_type, client = client_tuple

    # Limit text length to avoid excessive prompt token usage while capturing all relevant sections
    truncated_text = body_text[:18000]

    prompt = f"""
Analyze the following academic document body text and extract up to {max_claims} explicit empirical scientific claims.
Every claim must represent a substantive research finding, clinical trial result, numerical measurement, or technical benchmark.

CRITICAL INSTRUCTIONS:
1. ONLY extract claims actually present in the text below. DO NOT INVENT CLAIMS.
2. For each claim, extract its associated in-text citation marker (e.g. "[1]", "[2-3]", "(Author, Year)").
3. Identify numerical values (percentages, AUC, sample sizes, p-values, accuracy metrics).
4. Specify the scientific topic or subdomain.
5. Provide brief surrounding research context.

Return a JSON object with this exact structure:
{{
  "claims": [
    {{
      "claim_id": "C1",
      "claim": "AI improves cancer detection accuracy by 35%.",
      "topic": "Medical AI",
      "numerical_values": ["35%"],
      "citation": "[1]",
      "context": "In clinical trials on screening mammography..."
    }}
  ]
}}

DOCUMENT TEXT:
\"\"\"{truncated_text}\"\"\"
"""

    try:
        response_text = ""
        model_name = config.GEMINI_MODEL

        if sdk_type == "genai":
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config={
                    "temperature": 0.1,
                    "response_mime_type": "application/json"
                }
            )
            response_text = response.text
        else:
            model = client.GenerativeModel(
                model_name=model_name,
                generation_config={"temperature": 0.1, "response_mime_type": "application/json"}
            )
            response = model.generate_content(prompt)
            response_text = response.text

        parsed = repair_json(response_text)
        if parsed:
            raw_claims = parsed.get("claims") if isinstance(parsed, dict) else parsed
            if isinstance(raw_claims, list) and len(raw_claims) > 0:
                validated = []
                for idx, c in enumerate(raw_claims[:max_claims], 1):
                    if isinstance(c, dict) and c.get("claim"):
                        nums = c.get("numerical_values") or []
                        if not nums:
                            # Auto-extract numbers if model omitted them
                            detected = extract_numbers_from_text(c["claim"])
                            nums = [d["raw"] for d in detected]

                        validated.append({
                            "claim_id": c.get("claim_id") or f"C{idx}",
                            "claim": c["claim"].strip(),
                            "topic": c.get("topic") or "General Science",
                            "numerical_values": nums,
                            "citation": c.get("citation", ""),
                            "context": c.get("context", "")
                        })
                if validated:
                    return validated
    except Exception as e:
        logger.warning(f"Gemini claim extraction failed: {e}. Using heuristic fallback.")

    return extract_claims_heuristic(body_text, max_claims=max_claims)


def extract_claims_heuristic(body_text: str, max_claims: int = 25) -> List[Dict[str, Any]]:
    """Rule-based extractor that scans for sentences with citations and scientific claim cues."""
    if not body_text:
        return []

    # Regex for sentences with bracket citations e.g. [1] or (Author, Year)
    citation_pattern = re.compile(r"(\[\d+(?:\s*[-–,;\s]\s*\d+)*\]|\([A-Z][a-zA-Z\s]+(?:et\s+al\.?)?,\s*(?:19|20)\d{2}\))")
    
    # Scientific claim cues
    cues = re.compile(
        r"\b(achieve|achieved|improved|demonstrate|demonstrated|reported|reduction|increase|"
        r"sensitivity|specificity|accuracy|auc|outperform|significant|associated|yielded|evaluated)\b",
        re.IGNORECASE
    )

    sentences = re.split(r"(?<=[.!?])\s+", body_text)
    claims: List[Dict[str, Any]] = []

    for s in sentences:
        s_clean = s.strip()
        if len(s_clean) < 30 or len(s_clean) > 400:
            continue

        cit_match = citation_pattern.search(s_clean)
        if cit_match:
            cit_marker = cit_match.group(0)
            # Remove citation from claim text for cleaner presentation
            claim_text = citation_pattern.sub("", s_clean).strip()
            # Clean punctuation
            claim_text = re.sub(r"\s+", " ", claim_text)

            nums = extract_numbers_from_text(s_clean)
            num_strings = [n["raw"] for n in nums]

            # Assign topic
            topic = "Clinical / AI Benchmark" if any(w in s_clean.lower() for w in ("ai", "cancer", "accuracy", "clinical", "tumor")) else "Empirical Finding"

            claims.append({
                "claim_id": f"C{len(claims)+1}",
                "claim": claim_text,
                "topic": topic,
                "numerical_values": num_strings,
                "citation": cit_marker,
                "context": s_clean
            })

            if len(claims) >= max_claims:
                break

    # If no sentences with citations found, extract sentences with strong empirical cues
    if not claims:
        for s in sentences:
            s_clean = s.strip()
            if len(s_clean) > 40 and cues.search(s_clean):
                nums = extract_numbers_from_text(s_clean)
                claims.append({
                    "claim_id": f"C{len(claims)+1}",
                    "claim": s_clean,
                    "topic": "General Claim",
                    "numerical_values": [n["raw"] for n in nums],
                    "citation": "[Uncited]",
                    "context": s_clean
                })
                if len(claims) >= max_claims:
                    break

    return claims
