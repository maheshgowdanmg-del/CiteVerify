"""Academic Trust Score Engine for CiteVerify.
Calculates a transparent, mathematically sound 0-100 score reflecting
citation integrity, evidence coverage, claim verification results, and penalty deductions.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


# Scoring weights
WEIGHT_CLAIM_SUPPORT = 0.40
WEIGHT_CITATION_INTEGRITY = 0.25
WEIGHT_EVIDENCE_COVERAGE = 0.20
WEIGHT_PENALTIES = 0.15

CLAIM_CREDITS = {
    "SUPPORTED": 1.0,
    "PARTIALLY_SUPPORTED": 0.6,
    "CONTRADICTORY": 0.25,
    "UNSUPPORTED": 0.0,
    "REFUTED": 0.0,
    "NEEDS_REVIEW": 0.35,
    "NOT_ENOUGH_EVIDENCE": 0.35
}


def calculate_academic_trust_score(
    claims: List[Dict[str, Any]],
    citations: List[Dict[str, Any]],
    results: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Calculate the comprehensive CiteVerify Academic Trust Score with full component transparency."""
    n_claims = len(claims)
    n_citations = len(citations)
    n_results = len(results)

    if n_claims == 0:
        return {
            "score": 0.0,
            "grade": "No Claims Extracted",
            "grade_color": "#6B7280",
            "components": [],
            "penalties_applied": [],
            "explanation": "No scientific claims were identified in the document."
        }

    # 1. Claim Verification Factor (40%)
    claim_credits = [CLAIM_CREDITS.get(r.get("verdict", "NOT_ENOUGH_EVIDENCE"), 0.35) for r in results]
    avg_claim_support = sum(claim_credits) / max(1, len(claim_credits))
    claim_support_score = round(avg_claim_support * 100, 1)

    # 2. Citation Integrity Factor (25%)
    if n_citations > 0:
        verified_count = sum(1 for c in citations if c.get("verified_status") == "VERIFIED")
        partial_count = sum(1 for c in citations if c.get("verified_status") in ("UNVERIFIED", "NEEDS_MANUAL_REVIEW"))
        cit_ratio = (verified_count + 0.5 * partial_count) / n_citations
        cit_score = round(cit_ratio * 100, 1)
    else:
        cit_score = 50.0  # neutral if unreferenced document

    # 3. Evidence Coverage Factor (20%)
    with_evidence = sum(1 for r in results if r.get("evidence_quote") and len(r.get("evidence_quote", "").strip()) > 10)
    cov_ratio = with_evidence / max(1, n_results)
    coverage_score = round(cov_ratio * 100, 1)

    # 4. Penalties & Integrity Deductions (15% base weight + specific deductions)
    penalties = []
    penalty_deduction = 0.0

    # Retracted papers penalty
    retracted_count = sum(1 for c in citations if c.get("retracted") or c.get("verified_status") == "POSSIBLY_RETRACTED")
    if retracted_count > 0:
        ded = retracted_count * 25.0
        penalty_deduction += ded
        penalties.append(f"{retracted_count} potentially retracted publication(s) cited (-{ded:.0f} pts).")

    # Fabricated / Missing DOI penalty
    fake_doi_count = sum(1 for c in citations if c.get("verified_status") == "DOI_NOT_FOUND")
    if fake_doi_count > 0:
        ded = fake_doi_count * 15.0
        penalty_deduction += ded
        penalties.append(f"{fake_doi_count} citation(s) with nonexistent / invalid DOIs (-{ded:.0f} pts).")

    # Metadata mismatch penalty
    mismatch_count = sum(1 for c in citations if c.get("verified_status") == "METADATA_MISMATCH")
    if mismatch_count > 0:
        ded = mismatch_count * 10.0
        penalty_deduction += ded
        penalties.append(f"{mismatch_count} citation metadata mismatch(es) detected (-{ded:.0f} pts).")

    # Numerical mismatch penalty
    num_mismatch_count = sum(1 for r in results if (r.get("numeric_details") or {}).get("mismatch_detected"))
    if num_mismatch_count > 0:
        ded = num_mismatch_count * 12.0
        penalty_deduction += ded
        penalties.append(f"{num_mismatch_count} quantitative / numerical mismatch(es) between claim and source (-{ded:.0f} pts).")

    penalty_score = max(0.0, 100.0 - penalty_deduction)

    # Weighted calculation
    composite_raw = (
        claim_support_score * WEIGHT_CLAIM_SUPPORT +
        cit_score * WEIGHT_CITATION_INTEGRITY +
        coverage_score * WEIGHT_EVIDENCE_COVERAGE +
        penalty_score * WEIGHT_PENALTIES
    )
    final_score = max(0.0, min(100.0, round(composite_raw, 1)))

    # Determine grade
    if final_score >= 80.0:
        grade = "High Academic Integrity"
        grade_color = "#10B981"
    elif final_score >= 60.0:
        grade = "Moderate Integrity (Some Discrepancies)"
        grade_color = "#F59E0B"
    elif final_score >= 40.0:
        grade = "Low Integrity (Needs Significant Review)"
        grade_color = "#F97316"
    else:
        grade = "Critical Integrity Risk"
        grade_color = "#EF4444"

    components = [
        {
            "name": "Claim Verification Quality",
            "weight": f"{int(WEIGHT_CLAIM_SUPPORT*100)}%",
            "score": claim_support_score,
            "details": f"Average support rating across {n_results} scientific claims."
        },
        {
            "name": "Citation & DOI Validity",
            "weight": f"{int(WEIGHT_CITATION_INTEGRITY*100)}%",
            "score": cit_score,
            "details": f"Percentage of bibliographic entries resolving to verified registry records."
        },
        {
            "name": "Evidence Coverage",
            "weight": f"{int(WEIGHT_EVIDENCE_COVERAGE*100)}%",
            "score": coverage_score,
            "details": f"{with_evidence} of {n_results} claims backed by verbatim retrieved evidence."
        },
        {
            "name": "Integrity & Absence of Fraud",
            "weight": f"{int(WEIGHT_PENALTIES*100)}%",
            "score": round(penalty_score, 1),
            "details": f"{len(penalties)} penalty deduction(s) applied." if penalties else "Clean audit: No retractions or fabricated DOIs detected."
        }
    ]

    return {
        "score": final_score,
        "grade": grade,
        "grade_color": grade_color,
        "components": components,
        "penalties_applied": penalties,
        "explanation": (
            "The CiteVerify Academic Trust Score is an algorithmic integrity assessment calculated across "
            "empirical corroboration, citation resolution, quantitative consistency, and registry records. "
            "It serves as academic decision support and is not an official publisher evaluation."
        )
    }
