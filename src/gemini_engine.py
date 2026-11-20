"""Claim Verification Engine for CiteVerify.
Coordinates multi-provider AI inference (Google Gemini, Groq) and deterministic
rule-based offline fallback to verify academic claims against retrieved evidence.

Supports the 5 canonical verdicts:
- SUPPORTED
- PARTIALLY_SUPPORTED
- UNSUPPORTED
- CONTRADICTORY
- NEEDS_REVIEW

Includes explainable verification breakdowns:
- what_was_claimed
- what_source_reported
- what_matched
- what_did_not_match
- why_assigned
- what_remains_uncertain
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from . import ai_provider, config
from .utils import extract_numbers_from_text, fuzzy_similarity, repair_json

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


def verify_claim(
    claim_text: str,
    evidence_text: str,
    source_title: str,
    citation_marker: str,
    numerical_check: Optional[Dict[str, Any]] = None,
    claim_type: str = "Empirical"
) -> Dict[str, Any]:
    """Verify a scientific claim against retrieved source evidence.
    Routes through active AI provider (Gemini / Groq) with intelligent offline fallback.
    """
    evidence_clean = (evidence_text or "").strip()
    if not evidence_clean or len(evidence_clean) < 25:
        return {
            "verdict": "NEEDS_REVIEW",
            "explanation": "Insufficient or empty evidence passage retrieved from open academic repositories.",
            "evidence_quote": "",
            "limitations": "Full paper text was not openly accessible; only abstract or registry metadata available.",
            "confidence_score": 0.25,
            "confidence_label": "Low",
            "needs_human_review": True,
            "contradiction_notes": "",
            "provider_used": "system",
            "explainability": {
                "what_was_claimed": claim_text,
                "what_source_reported": "No conclusive evidence excerpt retrieved.",
                "what_matched": "None",
                "what_did_not_match": "Missing evidentiary context in open abstract.",
                "why_assigned": "Evidence retrieval returned fewer than 25 characters of scientific context.",
                "what_remains_uncertain": "Full methodology and findings cannot be audited without full-text access."
            }
        }

    num_info = ""
    if numerical_check:
        num_info = f"\nPre-computed Numerical Audit: Verdict={numerical_check.get('verdict')} | Details={numerical_check.get('explanation')}"

    system_instruction = (
        "You are CiteVerify AI, a senior academic integrity auditor evaluating whether cited scholarly "
        "evidence genuinely corroborates a scientific claim.\n"
        "Rules:\n"
        "1. DO NOT INVENT EVIDENCE. Base all judgments exclusively on the provided retrieved text.\n"
        "2. Assign exactly one of these five primary verdicts:\n"
        "   - 'SUPPORTED': The evidence directly corroborates the claim and its measurements within research context.\n"
        "   - 'PARTIALLY_SUPPORTED': Evidence supports general findings, but sample limits, conditions, or scope differ.\n"
        "   - 'UNSUPPORTED': Evidence does not justify the claim, or quantitatively contradicts it.\n"
        "   - 'CONTRADICTORY': Evidence actively demonstrates conflicting or opposing trial results.\n"
        "   - 'NEEDS_REVIEW': Retrieved text is too brief or ambiguous to confirm or refute.\n"
        "3. Provide explainable breakdown and quote verbatim text."
    )

    prompt = f"""Evaluate this scientific claim against the retrieved research paper evidence.

Claim: "{claim_text}"
Claim Type: {claim_type}
Citation Marker: {citation_marker}
Cited Source Title: "{source_title}"
Retrieved Source Evidence Excerpt:
\"\"\"{evidence_clean}\"\"\"
{num_info}

Respond strictly in valid JSON with this schema:
{{
  "verdict": "SUPPORTED" | "PARTIALLY_SUPPORTED" | "UNSUPPORTED" | "CONTRADICTORY" | "NEEDS_REVIEW",
  "explanation": "Clear, precise explanation of whether and how the evidence supports or contradicts the claim.",
  "evidence_quote": "Exact verbatim excerpt from the evidence text that best justifies the verdict.",
  "limitations": "Specific study constraints, sample sizes, or bounds noted in the evidence.",
  "confidence_score": 0.85,
  "confidence_label": "High" | "Medium" | "Low",
  "needs_human_review": false,
  "contradiction_notes": "",
  "explainability": {{
    "what_was_claimed": "Summary of the author's claim",
    "what_source_reported": "Summary of what the retrieved paper reported",
    "what_matched": "Specific agreements between claim and source",
    "what_did_not_match": "Specific discrepancies or unconfirmed elements",
    "why_assigned": "Core scientific rationale for this verdict",
    "what_remains_uncertain": "Remaining unknowns or limitations"
  }}
}}
"""

    parsed, provider_used, status = ai_provider.generate_structured_ai_response(
        prompt=prompt,
        system_instruction=system_instruction,
        json_mode=True,
        temperature=config.DEFAULT_TEMPERATURE
    )

    if parsed and isinstance(parsed, dict) and "verdict" in parsed:
        raw_v = parsed.get("verdict", "NEEDS_REVIEW")
        norm_v = config.normalize_verdict(raw_v)
        parsed["verdict"] = norm_v
        parsed["provider_used"] = provider_used
        if "explainability" not in parsed or not isinstance(parsed["explainability"], dict):
            parsed["explainability"] = {
                "what_was_claimed": claim_text,
                "what_source_reported": parsed.get("explanation", ""),
                "what_matched": "General topical alignment",
                "what_did_not_match": "None noted",
                "why_assigned": parsed.get("explanation", ""),
                "what_remains_uncertain": parsed.get("limitations", "No bounds noted")
            }
        return parsed

    # Graceful fallback to deterministic rule-based offline verification
    logger.info(f"AI provider '{provider_used}' unavailable or returned {status}. Running offline rule engine.")
    return run_offline_verification(claim_text, evidence_clean, source_title, numerical_check)


def verify_claim_with_gemini(
    claim_text: str,
    evidence_text: str,
    source_title: str,
    citation_marker: str,
    numerical_check: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Legacy alias preserved for backward compatibility."""
    return verify_claim(
        claim_text=claim_text,
        evidence_text=evidence_text,
        source_title=source_title,
        citation_marker=citation_marker,
        numerical_check=numerical_check
    )


def run_offline_verification(
    claim_text: str,
    evidence_text: str,
    source_title: str,
    numerical_check: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Robust heuristic verification engine that operates when AI services are offline."""
    claim_l = claim_text.lower()
    evidence_l = evidence_text.lower()

    # Find the best matching verbatim quote from evidence
    best_quote = ""
    evidence_sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", evidence_text) if len(s.strip()) > 15]
    if evidence_sentences:
        best_quote = max(evidence_sentences, key=lambda s: fuzzy_similarity(claim_text, s))

    # Priority 1: Check numerical consistency
    if numerical_check:
        num_v = numerical_check.get("verdict")
        if num_v == "NUMERICAL_MISMATCH":
            diff_text = numerical_check.get("explanation", "Numerical distortion detected.")
            return {
                "verdict": "UNSUPPORTED",
                "explanation": f"Quantitative discrepancy detected: {diff_text}",
                "evidence_quote": best_quote,
                "limitations": "Quantitative values in manuscript conflict with source findings.",
                "confidence_score": 0.90,
                "confidence_label": "High",
                "needs_human_review": True,
                "contradiction_notes": diff_text,
                "provider_used": "offline_rules",
                "explainability": {
                    "what_was_claimed": claim_text,
                    "what_source_reported": best_quote,
                    "what_matched": "Scientific subject topic",
                    "what_did_not_match": diff_text,
                    "why_assigned": "Claim asserts quantitative metrics conflicting with the cited source evidence.",
                    "what_remains_uncertain": "Verify whether alternative cohorts or endpoints were measured."
                }
            }
        elif num_v == "NUMERICAL_MATCH":
            diff_text = numerical_check.get("explanation", "Quantitative metrics verified.")
            return {
                "verdict": "SUPPORTED",
                "explanation": f"Source evidence directly substantiates the claim: {diff_text}",
                "evidence_quote": best_quote,
                "limitations": "Open literature excerpt directly corroborates claim assertions.",
                "confidence_score": 0.92,
                "confidence_label": "High",
                "needs_human_review": False,
                "contradiction_notes": "",
                "provider_used": "offline_rules",
                "explainability": {
                    "what_was_claimed": claim_text,
                    "what_source_reported": best_quote,
                    "what_matched": "Exact quantitative figures and empirical findings match.",
                    "what_did_not_match": "None",
                    "why_assigned": "Retrieved primary evidence directly verifies stated numerical findings and conclusions.",
                    "what_remains_uncertain": "None in the reported scope."
                }
            }

    # Priority 2: Check explicit contradiction / negation cues
    # Polar opposites: increase vs prevent/reduce/decrease
    if re.search(r"\bincrease(s|d)?\b", claim_l) and re.search(r"\b(prevent(s|ed)?|reduce(s|d)?|decrease(s|d)?|avoid(s|ed)?)\b", evidence_l + " " + source_title.lower()):
        return {
            "verdict": "CONTRADICTORY",
            "explanation": "Claim asserts an increase, but cited source evidence explicitly demonstrates prevention or reduction.",
            "evidence_quote": best_quote or source_title,
            "limitations": "Opposing empirical outcome reported in cited literature.",
            "confidence_score": 0.90,
            "confidence_label": "High",
            "needs_human_review": True,
            "contradiction_notes": "Claim and cited evidence assert opposite directional findings.",
            "provider_used": "offline_rules",
            "explainability": {
                "what_was_claimed": claim_text,
                "what_source_reported": best_quote or source_title,
                "what_matched": "Evaluated method/subject",
                "what_did_not_match": "Directional effect (increase asserted vs prevention reported)",
                "why_assigned": "Cited literature reports prevention/reduction rather than the asserted increase.",
                "what_remains_uncertain": "None in the primary scope."
            }
        }

    negation_cues = [
        "failed to replicate", "no significant difference", "failed to show",
        "did not improve", "contradicts", "inconclusive", "refutes", "no evidence that"
    ]
    for cue in negation_cues:
        if cue in evidence_l and not (cue in claim_l):
            return {
                "verdict": "CONTRADICTORY",
                "explanation": f"Evidence contains explicit negation cue ('{cue}') conflicting with the claim.",
                "evidence_quote": best_quote,
                "limitations": "Opposing scientific outcome reported in cited literature.",
                "confidence_score": 0.82,
                "confidence_label": "High",
                "needs_human_review": True,
                "contradiction_notes": f"Cited study reports '{cue}' in trial findings.",
                "provider_used": "offline_rules",
                "explainability": {
                    "what_was_claimed": claim_text,
                    "what_source_reported": best_quote,
                    "what_matched": "Experimental trial domain",
                    "what_did_not_match": f"Source documents {cue}",
                    "why_assigned": f"Negation finding ('{cue}') in source actively opposes claim direction.",
                    "what_remains_uncertain": "Potential differences in dosage, timeline, or study cohorts."
                }
            }

    # Priority 3: Semantic similarity & keyword overlap with best quote
    stop_words = {"the", "a", "an", "in", "on", "of", "to", "for", "and", "or", "is", "was", "were", "by", "that", "this", "with", "as"}
    claim_words = {w for w in re.findall(r"\b[a-zA-Z0-9\.\-]{3,}\b", claim_l) if w not in stop_words}
    ev_words = {w for w in re.findall(r"\b[a-zA-Z0-9\.\-]{3,}\b", (best_quote or evidence_text).lower()) if w not in stop_words}
    overlap_ratio = len(claim_words.intersection(ev_words)) / max(1, len(claim_words))
    sim_quote = fuzzy_similarity(claim_text, best_quote) if best_quote else 0.0

    claim_nums = extract_numbers_from_text(claim_text)
    ev_nums = extract_numbers_from_text(evidence_text)
    num_vals_match = bool(claim_nums and any(n["value"] in [en["value"] for en in ev_nums] for n in claim_nums))

    if num_vals_match or overlap_ratio >= 0.45 or sim_quote >= 0.45:
        verdict = "SUPPORTED" if (num_vals_match or overlap_ratio >= 0.50 or sim_quote >= 0.55) else "PARTIALLY_SUPPORTED"
        confidence = 0.88 if verdict == "SUPPORTED" else 0.72
        return {
            "verdict": verdict,
            "explanation": f"Retrieved source evidence substantiates the claim (keyword alignment: {int(overlap_ratio*100)}%).",
            "evidence_quote": best_quote,
            "limitations": "Evaluated against primary publication summary.",
            "confidence_score": confidence,
            "confidence_label": "High" if verdict == "SUPPORTED" else "Medium",
            "needs_human_review": False,
            "contradiction_notes": "",
            "provider_used": "offline_rules",
            "explainability": {
                "what_was_claimed": claim_text,
                "what_source_reported": best_quote,
                "what_matched": "Key thematic and quantitative terms corroborated",
                "what_did_not_match": "None flagged in retrieved passage",
                "why_assigned": f"Substantial empirical overlap ({int(overlap_ratio*100)}%) observed in primary source.",
                "what_remains_uncertain": "Secondary clinical endpoints."
            }
        }

    # Priority 4: Citation mismatch or unindexed claim
    if "could not be automatically retrieved" in evidence_text.lower():
        return {
            "verdict": "NEEDS_REVIEW",
            "explanation": "The source paper could not be automatically retrieved from scholarly registries for verification.",
            "evidence_quote": "",
            "limitations": "Manual review required: publication abstract or full text not openly indexed.",
            "confidence_score": 0.30,
            "confidence_label": "Low",
            "needs_human_review": True,
            "contradiction_notes": "Unindexed source paper.",
            "provider_used": "offline_rules",
            "explainability": {
                "what_was_claimed": claim_text,
                "what_source_reported": "No open indexed record found.",
                "what_matched": "None",
                "what_did_not_match": "Source document missing from index",
                "why_assigned": "Scholarly registries returned no matching work record.",
                "what_remains_uncertain": "Full document verification required."
            }
        }

    # Default: Needs Review
    return {
        "verdict": "NEEDS_REVIEW",
        "explanation": "Retrieved abstract evidence does not provide enough specific details to confirm or refute the claim.",
        "evidence_quote": best_quote,
        "limitations": "Abstract lacked specific experimental endpoint data.",
        "confidence_score": 0.40,
        "confidence_label": "Low",
        "needs_human_review": True,
        "contradiction_notes": "",
        "provider_used": "offline_rules",
        "explainability": {
            "what_was_claimed": claim_text,
            "what_source_reported": best_quote if best_quote else "No direct matches found",
            "what_matched": "General academic field",
            "what_did_not_match": "Specific benchmarks or methodologies",
            "why_assigned": "Insufficient evidentiary certainty from abstract text alone.",
            "what_remains_uncertain": "Full-text access required for rigorous audit."
        }
    }
