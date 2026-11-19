"""Automated tests for claim verification, numerical auditing, trust scoring,
database persistence, and report generation.
"""
import os
import sys
import tempfile
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import (
    database,
    evidence_matcher,
    gemini_engine,
    report_generator,
    trust_score,
    utils,
)


def test_numerical_claim_verification_match():
    claim = "The AI model achieved 95.0% diagnostic sensitivity."
    evidence = "In the primary cohort, our convolutional ensemble achieved a 95.0% sensitivity across verified lesions."
    
    num_res = evidence_matcher.verify_numerical_claims(claim, evidence)
    assert num_res["verdict"] == "NUMERICAL_MATCH"
    assert not num_res["mismatch_detected"]


def test_numerical_claim_verification_mismatch():
    claim = "Automated slide segmentation systems demonstrated a 45% reduction in turnaround times."
    evidence = "The retrospective analysis reported an 18.2% reduction in turnaround times across laboratories."
    
    num_res = evidence_matcher.verify_numerical_claims(claim, evidence)
    assert num_res["verdict"] == "NUMERICAL_MISMATCH"
    assert num_res["mismatch_detected"]
    assert "45%" in num_res["difference_summary"]
    assert "18.2%" in num_res["difference_summary"]


def test_gemini_json_repair():
    raw_markdown = '```json\n{"verdict": "SUPPORTED", "confidence_score": 0.9, "explanation": "Corroborated"}\n```'
    parsed = utils.repair_json(raw_markdown)
    assert parsed is not None
    assert parsed["verdict"] == "SUPPORTED"
    assert parsed["confidence_score"] == 0.9

    messy_text = 'Here is the response: {"verdict": "REFUTED", "explanation": "Mismatched"} thank you'
    parsed2 = utils.repair_json(messy_text)
    assert parsed2 is not None
    assert parsed2["verdict"] == "REFUTED"


def test_academic_trust_score_calculation():
    claims = [{"claim_id": "C1"}, {"claim_id": "C2"}]
    citations = [{"verified_status": "VERIFIED"}, {"verified_status": "VERIFIED"}]
    results = [
        {"claim_id": "C1", "verdict": "SUPPORTED", "evidence_quote": "Verbatim evidence text from Nature."},
        {"claim_id": "C2", "verdict": "PARTIALLY_SUPPORTED", "evidence_quote": "Partial evidence passage."}
    ]

    t_res = trust_score.calculate_academic_trust_score(claims, citations, results)
    assert t_res["score"] >= 75.0
    assert "High" in t_res["grade"] or "Moderate" in t_res["grade"]
    assert len(t_res["components"]) == 4


def test_academic_trust_score_penalties():
    claims = [{"claim_id": "C1"}]
    citations = [
        {"verified_status": "POSSIBLY_RETRACTED", "retracted": True},
        {"verified_status": "DOI_NOT_FOUND"}
    ]
    results = [
        {
            "claim_id": "C1",
            "verdict": "REFUTED",
            "numeric_details": {"mismatch_detected": True}
        }
    ]

    t_res = trust_score.calculate_academic_trust_score(claims, citations, results)
    assert t_res["score"] < 50.0
    assert len(t_res["penalties_applied"]) >= 2


def test_database_persistence_and_retrieval():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_db = tmp.name

    try:
        database.init_db(tmp_db)

        # Save analysis run
        doc_id = "test_doc_001"
        cits = [{
            "id": "1",
            "ref_marker": "1",
            "raw_text": "Nature 2020",
            "title": "Breast Cancer Screening",
            "authors": ["McKinney et al."],
            "year": 2020,
            "doi": "10.1038/s41586-019-1799-6",
            "verified_status": "VERIFIED"
        }]
        claims = [{
            "claim_id": "C1",
            "claim": "AI improves breast cancer screening.",
            "topic": "Medical AI",
            "numerical_values": ["0.945"],
            "citation": "[1]"
        }]
        results = [{
            "claim_id": "C1",
            "verdict": "SUPPORTED",
            "explanation": "Nature study corroborated AUC of 0.945.",
            "evidence": {"passage": "AUC 0.945", "verified": True},
            "source": {"title": "Breast Cancer Screening", "doi": "10.1038/s41586-019-1799-6", "year": 2020}
        }]

        database.save_analysis_run(
            doc_id=doc_id,
            filename="paper.pdf",
            file_type="PDF",
            raw_text="Sample text content for testing.",
            page_count=2,
            citations_list=cits,
            claims_list=claims,
            results_list=results,
            trust_score_data={"score": 88.5, "grade": "High Integrity"},
            db_path=tmp_db
        )

        # Retrieve document run
        loaded = database.get_document_run(doc_id, db_path=tmp_db)
        assert loaded is not None
        assert loaded["document"]["filename"] == "paper.pdf"
        assert len(loaded["claims"]) == 1
        assert loaded["claims"][0]["claim_id"] == "C1"
        assert len(loaded["results"]) == 1
        assert loaded["results"][0]["verdict"] == "SUPPORTED"

        # Test human review persistence
        database.add_human_review(
            doc_id=doc_id,
            claim_id="C1",
            action="override",
            original_verdict="SUPPORTED",
            reviewed_verdict="PARTIALLY_SUPPORTED",
            comments="Needs larger clinical trial.",
            reviewer="Dr. Auditor",
            db_path=tmp_db
        )

        reviews = database.get_all_reviews(doc_id, db_path=tmp_db)
        assert len(reviews) == 1
        assert reviews[0]["reviewed_verdict"] == "PARTIALLY_SUPPORTED"

        # Check global stats
        stats = database.get_global_statistics(db_path=tmp_db)
        assert stats["total_documents"] == 1
        assert stats["total_claims"] == 1
        assert stats["supported_claims"] == 1
    finally:
        if os.path.exists(tmp_db):
            os.remove(tmp_db)


def test_report_generation():
    doc_data = {
        "document": {
            "id": "doc_test",
            "filename": "clinical_paper.pdf",
            "trust_score": 85.0,
            "trust_grade": "High Academic Integrity",
            "page_count": 3
        },
        "claims": [{
            "claim_id": "C1",
            "claim_text": "Vision transformers reduce false positive detections by 58%.",
            "citation_marker": "[1]",
            "topic": "Neuro-oncology"
        }],
        "citations": [{
            "ref_marker": "1",
            "title": "U-Net in Cellular Pathology",
            "doi": "10.1038/s41592-018-0261-2",
            "verified_status": "VERIFIED"
        }],
        "results": [{
            "claim_id": "C1",
            "verdict": "SUPPORTED",
            "final_verdict": "SUPPORTED",
            "explanation": "Empirical evidence substantiated the 58% relative reduction.",
            "evidence_quote": "We observed a 58% reduction in false-positive detections.",
            "source_title": "U-Net in Cellular Pathology",
            "source_doi": "10.1038/s41592-018-0261-2",
            "source_year": 2019,
            "source_authors": "Falk et al.",
            "confidence_score": 0.88,
            "confidence_label": "High",
            "review_action": "accept"
        }]
    }

    # Test PDF generation
    pdf_bytes = report_generator.generate_pdf_report(doc_data)
    assert len(pdf_bytes) > 1000
    assert pdf_bytes.startswith(b"%PDF-")

    # Test JSON generation
    json_str = report_generator.generate_json_report(doc_data)
    assert "clinical_paper.pdf" in json_str

    # Test CSV generation
    csv_str = report_generator.generate_csv_report(doc_data)
    assert "Claim_ID" in csv_str
    assert "C1" in csv_str
    assert "SUPPORTED" in csv_str
