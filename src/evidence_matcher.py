"""Evidence matcher and Numerical Verification module for CiteVerify.
Pinpoints relevant evidence passages in retrieved paper text and performs
exact quantitative verification of percentages, statistics, sample sizes, and measurements.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .utils import extract_numbers_from_text


def find_best_evidence_passage(
    claim_text: str, 
    source_text: str, 
    min_length: int = 50
) -> Dict[str, Any]:
    """Find the most relevant sentence or paragraph within the source text that addresses the claim."""
    if not source_text or len(source_text.strip()) < 20:
        return {
            "passage": "No abstract or full-text evidence available in scholarly index.",
            "section": "Unavailable",
            "verified": False,
            "relevance_score": 0.0
        }

    # Split into candidate sentences
    sentences = re.split(r"(?<=[.!?])\s+", source_text.strip())
    if not sentences:
        return {
            "passage": source_text[:400],
            "section": "Abstract",
            "verified": False,
            "relevance_score": 0.3
        }

    # Extract keywords from claim (ignoring stop words)
    stop_words = {"the", "a", "an", "in", "on", "of", "to", "for", "and", "or", "is", "was", "were", "by", "that", "this", "with", "as"}
    claim_words = {w.lower() for w in re.findall(r"\b[a-zA-Z]{3,}\b", claim_text) if w.lower() not in stop_words}

    best_sentence = ""
    best_score = 0.0

    for s in sentences:
        s_words = {w.lower() for w in re.findall(r"\b[a-zA-Z]{3,}\b", s) if w.lower() not in stop_words}
        if not s_words:
            continue
        overlap = len(claim_words.intersection(s_words))
        score = overlap / max(1, len(claim_words))
        if score > best_score:
            best_score = score
            best_sentence = s

    # If best score is low, return first two sentences of abstract
    if best_score < 0.15 or not best_sentence:
        fallback_passage = " ".join(sentences[:2])
        return {
            "passage": fallback_passage,
            "section": "Abstract",
            "verified": False,
            "relevance_score": 0.2
        }

    # Context window: include adjacent sentence if available for rich context
    idx = sentences.index(best_sentence)
    start_idx = max(0, idx - 1)
    end_idx = min(len(sentences), idx + 2)
    rich_passage = " ".join(sentences[start_idx:end_idx])

    return {
        "passage": rich_passage,
        "section": "Results / Abstract",
        "verified": True,
        "relevance_score": round(best_score, 2)
    }


def verify_numerical_claims(claim_text: str, evidence_text: str) -> Dict[str, Any]:
    """Perform rigorous numerical verification comparing quantitative statements in claim vs evidence.
    Identifies percentages, metrics, accuracy values, sample sizes, and flags discrepancies.
    """
    claim_nums = extract_numbers_from_text(claim_text)
    ev_nums = extract_numbers_from_text(evidence_text)

    if not claim_nums:
        return {
            "verdict": "NOT_SPECIFIED",
            "explanation": "Claim does not contain specific numerical metrics, percentages, or sample sizes.",
            "claim_numbers": [],
            "evidence_numbers": [n["raw"] for n in ev_nums],
            "mismatch_detected": False,
            "difference_summary": ""
        }

    matched_values = []
    mismatched_values = []

    for c_num in claim_nums:
        c_val = c_num["value"]
        c_type = c_num["type"]

        # Look for identical or close number in evidence with same type
        found_exact = False
        potential_conflict = None

        for e_num in ev_nums:
            e_val = e_num["value"]
            e_type = e_num["type"]

            # Exact match (within 0.1% tolerance)
            if abs(c_val - e_val) < 0.05:
                found_exact = True
                matched_values.append({
                    "claim": c_num["raw"],
                    "evidence": e_num["raw"],
                    "value": c_val
                })
                break
            elif (c_num.get("unit") and c_num.get("unit") == e_num.get("unit")) or (c_type == e_type and c_type in ("percentage", "statistical", "measurement", "decimal_metric")) or (c_type in ("measurement", "decimal_metric") and e_type in ("measurement", "decimal_metric")):
                potential_conflict = e_num

        if not found_exact:
            if potential_conflict:
                mismatched_values.append({
                    "claim": c_num["raw"],
                    "evidence": potential_conflict["raw"],
                    "claim_val": c_val,
                    "evidence_val": potential_conflict["value"],
                    "type": c_type
                })
            else:
                mismatched_values.append({
                    "claim": c_num["raw"],
                    "evidence": "Not found in retrieved text",
                    "claim_val": c_val,
                    "evidence_val": None,
                    "type": c_type
                })

    # Determine final numerical status
    if mismatched_values and any(m["evidence_val"] is not None for m in mismatched_values):
        # Definite quantitative contradiction
        conflict_desc = ", ".join(
            f"Claim stated {m['claim']} but evidence reported {m['evidence']}"
            for m in mismatched_values if m["evidence_val"] is not None
        )
        return {
            "verdict": "NUMERICAL_MISMATCH",
            "explanation": f"Numerical discrepancy detected: {conflict_desc}.",
            "claim_numbers": [n["raw"] for n in claim_nums],
            "evidence_numbers": [n["raw"] for n in ev_nums],
            "mismatch_detected": True,
            "difference_summary": conflict_desc
        }
    elif matched_values and not mismatched_values:
        return {
            "verdict": "NUMERICAL_MATCH",
            "explanation": f"Quantitative values verified: {', '.join(m['claim'] for m in matched_values)} matches source evidence.",
            "claim_numbers": [n["raw"] for n in claim_nums],
            "evidence_numbers": [n["raw"] for n in ev_nums],
            "mismatch_detected": False,
            "difference_summary": ""
        }
    elif matched_values and mismatched_values:
        return {
            "verdict": "NUMERICAL_PARTIAL",
            "explanation": "Some numerical values match, but others are unconfirmed or contradictory in the evidence.",
            "claim_numbers": [n["raw"] for n in claim_nums],
            "evidence_numbers": [n["raw"] for n in ev_nums],
            "mismatch_detected": True,
            "difference_summary": "Partial numerical alignment."
        }
    else:
        # Numbers in claim were not found anywhere in retrieved evidence
        c_list = ", ".join(n["raw"] for n in claim_nums)
        return {
            "verdict": "NUMERICAL_UNCONFIRMED",
            "explanation": f"The claim's numerical metrics ({c_list}) were not found in the retrieved evidence passage.",
            "claim_numbers": [n["raw"] for n in claim_nums],
            "evidence_numbers": [n["raw"] for n in ev_nums],
            "mismatch_detected": False,
            "difference_summary": f"Metrics {c_list} missing from source abstract."
        }
