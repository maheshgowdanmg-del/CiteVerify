"""End-to-End Orchestration Pipeline for CiteVerify.
Coordinates document extraction, citation fraud checking, Gemini claim extraction,
scholarly research retrieval, numerical verification, evidence comparison,
trust scoring, and database persistence.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from . import (
    citation_checker,
    citation_parser,
    claim_extractor,
    contradiction_detector,
    database,
    evidence_matcher,
    gemini_engine,
    pdf_extractor,
    research_retriever,
    trust_score,
    utils,
)


def run_full_verification_pipeline(
    file_bytes: bytes,
    filename: str,
    max_claims: int = 25,
    progress_callback: Optional[Callable[[float, str], None]] = None
) -> Dict[str, Any]:
    """Execute complete 6-stage scientific claim and citation verification pipeline."""
    def update_progress(ratio: float, msg: str):
        if progress_callback:
            progress_callback(min(1.0, max(0.0, ratio)), msg)

    doc_id = f"doc_{int(time.time())}_{uuid.uuid4().hex[:6]}"

    # ---------------- STAGE 1: Document Extraction ----------------
    update_progress(0.05, "Extracting text and locating reference sections...")
    doc_meta = pdf_extractor.process_uploaded_document(file_bytes, filename)
    raw_text = doc_meta["raw_text"]
    body_text = doc_meta["body_text"]
    references_text = doc_meta["references_text"]
    page_count = doc_meta["page_count"]

    # ---------------- STAGE 2: Parse Citations & Reference Section ----------------
    update_progress(0.15, "Parsing reference bibliography and in-text citation markers...")
    citations_list = citation_parser.parse_references_section(references_text)

    # ---------------- STAGE 3: Citation Fraud Detection Engine ----------------
    update_progress(0.25, "Running Citation Fraud Detection via Crossref & scholarly registries...")
    verified_citations = citation_checker.batch_verify_citations(citations_list)

    # ---------------- STAGE 4: Gemini Scientific Claim Extraction ----------------
    update_progress(0.40, "Extracting scientific claims and numerical metrics with Gemini AI...")
    claims_list = claim_extractor.extract_claims_with_gemini(body_text, max_claims=max_claims)

    # Map in-text citations to resolved reference entries
    for cl in claims_list:
        cit_marker = cl.get("citation", "")
        resolved = citation_parser.resolve_citation_to_reference(cit_marker, verified_citations)
        cl["resolved_reference"] = resolved
        if resolved:
            cl["ref_id"] = resolved.get("ref_marker", "")

    # ---------------- STAGE 5: Research Retrieval & Evidence Verification ----------------
    results_list: List[Dict[str, Any]] = []
    total_claims = len(claims_list)

    for idx, claim in enumerate(claims_list, 1):
        step_ratio = 0.50 + 0.35 * (idx / max(1, total_claims))
        update_progress(step_ratio, f"Retrieving research evidence and verifying claim {idx} of {total_claims}...")

        resolved_ref = claim.get("resolved_reference")

        # 1. Retrieve original research
        retrieved_paper = research_retriever.retrieve_research_for_claim(claim, resolved_ref)

        # 2. Extract best evidence passage
        evidence = evidence_matcher.find_best_evidence_passage(
            claim["claim"],
            retrieved_paper.get("abstract", "")
        )

        # 3. Rigorous numerical claim verification
        num_check = evidence_matcher.verify_numerical_claims(
            claim["claim"],
            evidence.get("passage", "")
        )

        # 4. Gemini Claim Verification Engine
        verdict_data = gemini_engine.verify_claim_with_gemini(
            claim_text=claim["claim"],
            evidence_text=evidence.get("passage", ""),
            source_title=retrieved_paper.get("title", ""),
            citation_marker=claim.get("citation", ""),
            numerical_check=num_check
        )

        # 5. Contradiction Detection check
        contradiction_data = contradiction_detector.analyze_contradictions_across_studies(
            topic=claim.get("topic", "General Science"),
            claim_text=claim["claim"],
            papers=[retrieved_paper]
        )

        # Assemble finding result
        norm_verdict = config.normalize_verdict(verdict_data.get("verdict", "NEEDS_REVIEW"))
        result_entry = {
            "claim_id": claim.get("claim_id", f"C{idx}"),
            "verdict": norm_verdict,
            "final_verdict": norm_verdict,
            "explanation": verdict_data.get("explanation", ""),
            "confidence_score": verdict_data.get("confidence_score", 0.75),
            "confidence_label": verdict_data.get("confidence_label", "Medium"),
            "limitations": verdict_data.get("limitations", ""),
            "needs_review": norm_verdict == "NEEDS_REVIEW",
            "provider_used": verdict_data.get("provider_used", "ai"),
            "explainability": verdict_data.get("explainability") or {
                "what_was_claimed": claim.get("claim", ""),
                "what_source_reported": verdict_data.get("explanation", ""),
                "what_matched": "Empirical subject matter",
                "what_did_not_match": "None",
                "why_assigned": verdict_data.get("explanation", ""),
                "what_remains_uncertain": verdict_data.get("limitations", "No bounds noted")
            },
            "evidence": {
                "passage": evidence.get("passage", ""),
                "quote": verdict_data.get("evidence_quote") or evidence.get("passage", "")[:250],
                "section": evidence.get("section", "Abstract"),
                "verified": evidence.get("verified", False)
            },
            "evidence_quote": verdict_data.get("evidence_quote") or evidence.get("passage", "")[:250],
            "numeric_check": num_check,
            "numeric_verdict": num_check.get("verdict", "NONE"),
            "source": retrieved_paper,
            "source_title": retrieved_paper.get("title", ""),
            "source_authors": ", ".join(retrieved_paper.get("authors") or []),
            "source_year": retrieved_paper.get("year"),
            "source_doi": retrieved_paper.get("doi", ""),
            "source_url": retrieved_paper.get("url", ""),
            "source_access": "open_access" if retrieved_paper.get("is_oa") else "abstract",
            "contradiction_notes": contradiction_data.get("summary", ""),
            "review_action": "AI Verified",
            "review_comment": "Automated verification complete."
        }
        results_list.append(result_entry)

    # ---------------- STAGE 6: Academic Trust Score & Database Persistence ----------------
    update_progress(0.92, "Calculating transparent Academic Trust Score...")
    t_score_data = trust_score.calculate_academic_trust_score(
        claims=claims_list,
        citations=verified_citations,
        results=results_list
    )

    update_progress(0.97, "Saving analysis to SQLite database...")
    database.save_analysis_run(
        doc_id=doc_id,
        filename=filename,
        file_type=doc_meta["file_type"],
        raw_text=raw_text,
        page_count=page_count,
        citations_list=verified_citations,
        claims_list=claims_list,
        results_list=results_list,
        trust_score_data=t_score_data
    )

    update_progress(1.0, "Verification complete!")

    return {
        "document": {
            "id": doc_id,
            "filename": filename,
            "file_type": doc_meta["file_type"],
            "raw_text": raw_text,
            "page_count": page_count,
            "char_count": doc_meta["char_count"],
            "word_count": doc_meta["word_count"],
            "trust_score": t_score_data.get("score"),
            "trust_grade": t_score_data.get("grade")
        },
        "citations": verified_citations,
        "claims": claims_list,
        "results": results_list,
        "trust_score": t_score_data,
        "reviews": {}
    }
