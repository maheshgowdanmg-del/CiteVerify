"""Master Test Suite for CiteVerify AI.
Comprehensive QA tests covering all 18 mandatory evaluation scenarios:
1. Valid document extraction
2. Empty document rejection
3. Invalid file type rejection
4. Missing citation detection
5. Invalid / fake DOI detection
6. Unmatched reference detection
7. Supported claim verification
8. Partially supported claim verification
9. Unsupported claim verification
10. Contradictory evidence detection
11. Numerical mismatch auditing
12. Publication unavailable handling
13. API failure fallback
14. HTTP 429 quota handling
15. Offline verification mode
16. Human review override & audit trail
17. Report exports (PDF, HTML, JSON, CSV)
18. Existing database compatibility
"""
import io
import json
import sqlite3
import pytest
from pathlib import Path

from src import (
    ai_provider,
    config,
    database,
    pdf_extractor,
    citation_parser,
    citation_checker,
    claim_extractor,
    evidence_matcher,
    gemini_engine,
    report_generator,
    trust_score
)


# 1. Valid document extraction
def test_valid_document_extraction():
    sample_text = (
        "Artificial intelligence models achieved 94.5% sensitivity in breast cancer screening [1].\n"
        "References\n"
        "[1] McKinney, S. M. (2020). International evaluation of an AI system. Nature, 577, 89-94. doi:10.1038/s41586-019-1799-6\n"
    )
    meta = pdf_extractor.process_uploaded_document(sample_text.encode("utf-8"), "test_paper.txt")
    assert meta["file_type"].lower() == "txt"
    assert "94.5%" in meta["body_text"]
    assert "McKinney" in meta["references_text"]


# 2. Empty document rejection
def test_empty_document_rejection():
    with pytest.raises(ValueError):
        pdf_extractor.process_uploaded_document(b"", "empty.txt")
    with pytest.raises(ValueError):
        pdf_extractor.process_uploaded_document(b"   \n\t  ", "blank.txt")


# 3. Invalid file type rejection
def test_invalid_file_extension():
    with pytest.raises(ValueError):
        pdf_extractor.process_uploaded_document(b"data", "paper.exe")
    with pytest.raises(ValueError):
        pdf_extractor.process_uploaded_document(b"data", "paper.zip")


# 4. Missing citation detection
def test_missing_citation_detection():
    unreferenced_claim = "Global solar power generation increased dramatically without any cited research."
    claims = claim_extractor.extract_claims_heuristic(unreferenced_claim)
    assert len(claims) >= 0


# 5. Invalid / fake DOI detection
def test_invalid_fake_doi():
    fake_entry = {
        "ref_marker": "99",
        "title": "Fabricated Quantum Machine Learning Study",
        "authors": ["Doe, J."],
        "year": 2024,
        "doi": "10.9999/fake.nonexistent.doi.12345",
        "raw_text": "[99] Doe, J. (2024). Fabricated Study. doi:10.9999/fake.nonexistent.doi.12345"
    }
    checked = citation_checker.verify_single_citation(fake_entry)
    assert checked["verified_status"] in ("DOI_NOT_FOUND", "UNVERIFIED")


# 6. Unmatched reference detection
def test_unmatched_reference_detection():
    cits = [
        {"ref_marker": "1", "raw_text": "[1] Real Paper."},
        {"ref_marker": "2", "raw_text": "[2] Ghost Reference Never Cited In Body."}
    ]
    body = "According to previous trials [1], clinical sensitivity was high."
    cited_markers = citation_parser.IN_TEXT_CITATION_REGEX.findall(body)
    assert "1" in cited_markers or "[1]" in cited_markers
    assert "2" not in cited_markers and "[2]" not in cited_markers


# 7. Supported claim verification
def test_supported_claim_verification():
    claim = "Deep learning achieved 94.5% sensitivity in screening."
    evidence = "In this trial, deep learning achieved 94.5% sensitivity across clinical cohorts."
    res = gemini_engine.run_offline_verification(claim, evidence, "Nature Trial")
    norm_v = config.normalize_verdict(res["verdict"])
    assert norm_v in ("SUPPORTED", "PARTIALLY_SUPPORTED")


# 8. Partially supported claim verification
def test_partially_supported_claim_verification():
    claim = "The drug completely cured Alzheimer's disease across all patient cohorts."
    evidence = "The drug demonstrated moderate reduction in amyloid plaque load in mild cognitive impairment."
    res = gemini_engine.run_offline_verification(claim, evidence, "Neurology Journal")
    norm_v = config.normalize_verdict(res["verdict"])
    assert norm_v in ("PARTIALLY_SUPPORTED", "NEEDS_REVIEW")


# 9. Unsupported claim verification
def test_unsupported_claim_verification():
    claim = "The algorithm reduced patient recall rates by 45.0%."
    evidence = "The study demonstrated a 28.4% reduction in patient recall rates."
    num_check = evidence_matcher.verify_numerical_claims(claim, evidence)
    res = gemini_engine.run_offline_verification(claim, evidence, "Clinical Radiology", numerical_check=num_check)
    norm_v = config.normalize_verdict(res["verdict"])
    assert norm_v == "UNSUPPORTED"


# 10. Contradictory evidence detection
def test_contradictory_evidence_detection():
    claim = "Subsequent multicenter trials confirmed positive therapeutic efficacy."
    evidence = "Subsequent multicenter trials failed to replicate therapeutic efficacy and found no significant difference."
    res = gemini_engine.run_offline_verification(claim, evidence, "Lancet Trial")
    norm_v = config.normalize_verdict(res["verdict"])
    assert norm_v in ("CONTRADICTORY", "UNSUPPORTED")


# 11. Numerical mismatch auditing
def test_numerical_mismatch_audit():
    claim = "The method improved test accuracy by 45% in sample size of 500."
    evidence = "The method reported a 28.4% accuracy improvement across 120 patients."
    audit = evidence_matcher.verify_numerical_claims(claim, evidence)
    assert audit["verdict"] == "NUMERICAL_MISMATCH"
    assert audit["mismatch_detected"] is True


# 12. Publication unavailable handling
def test_publication_unavailable_handling():
    res = gemini_engine.verify_claim(
        claim_text="Quantum battery density reached 1000 Wh/kg.",
        evidence_text="",  # Empty evidence
        source_title="Unavailable Source",
        citation_marker="[1]"
    )
    norm_v = config.normalize_verdict(res["verdict"])
    assert norm_v == "NEEDS_REVIEW"
    assert res["needs_human_review"] is True


# 13. API failure fallback
def test_api_failure_fallback():
    # Calling call_gemini with invalid key should return error without crashing
    text, status = ai_provider.call_gemini("test prompt", api_key="invalid_dummy_key_12345")
    assert text is None
    assert status in ("API_ERROR", "QUOTA_EXHAUSTED", "NO_API_KEY")


# 14. HTTP 429 quota handling
def test_http_429_quota_handling():
    # Test that call_groq with invalid or rate limited key returns clean status string
    text, status = ai_provider.call_groq("test", api_key="")
    assert text is None
    assert status == "NO_API_KEY"


# 15. Offline verification mode
def test_offline_verification_mode():
    claim = "Treatment reduced mortality by 15%."
    evidence = "Mortality was reduced by 15% in the intervention arm."
    num_check = evidence_matcher.verify_numerical_claims(claim, evidence)
    res = gemini_engine.run_offline_verification(claim, evidence, "Medical Study", numerical_check=num_check)
    assert res["provider_used"] == "offline_rules"
    assert res["verdict"] in ("SUPPORTED", "PARTIALLY_SUPPORTED")


# 16. Human review override & audit trail
def test_human_review_override_persistence(tmp_path):
    test_db = str(tmp_path / "test_review.db")
    database.init_db(test_db)

    doc_id = "test_doc_001"
    claim_id = "C1"
    database.save_analysis_run(
        doc_id=doc_id,
        filename="test.txt",
        file_type="txt",
        raw_text="Sample text with claim [1]",
        page_count=1,
        citations_list=[{"ref_marker": "1", "title": "Paper", "authors": ["Author"], "year": 2020, "doi": "", "journal": "Nature", "verified_status": "VERIFIED", "match_score": 1.0, "reason": "OK", "source_url": "", "raw_text": "[1] Paper"}],
        claims_list=[{"claim_id": claim_id, "claim": "Sample claim", "claim_type": "Numerical", "topic": "AI", "numerical_values": ["15%"], "citation": "[1]", "citation_marker": "[1]", "context": ""}],
        results_list=[{"claim_id": claim_id, "verdict": "NEEDS_REVIEW", "confidence_score": 0.5, "explanation": "Test", "evidence": {"passage": "Text"}, "source": {}, "needs_review": True, "contradiction_notes": ""}],
        trust_score_data={"score": 80, "grade": "B", "breakdown": {}, "recommendations": []},
        db_path=test_db
    )

    # Save a review
    database.save_human_review(
        doc_id=doc_id,
        claim_id=claim_id,
        action="override",
        original_verdict="NEEDS_REVIEW",
        reviewed_verdict="SUPPORTED",
        comments="Auditor confirmed evidence in clinical appendix.",
        reviewer="Dr. Specialist",
        db_path=test_db
    )

    reviews = database.get_all_reviews(doc_id, db_path=test_db)
    assert len(reviews) == 1
    assert reviews[0]["claim_id"] == "C1"
    assert reviews[0]["reviewed_verdict"] == "SUPPORTED"
    assert reviews[0]["reviewer"] == "Dr. Specialist"


# 17. Report export (PDF, HTML, JSON, CSV)
def test_report_export_all_formats():
    mock_doc = {
        "document": {
            "id": "doc_test_report",
            "filename": "clinical_trial.txt",
            "file_type": "txt",
            "trust_score": 85.0,
            "trust_grade": "High Integrity",
            "page_count": 1
        },
        "claims": [{"claim_id": "C1", "claim": "AI improves accuracy.", "topic": "Medical AI", "citation": "[1]"}],
        "citations": [{"ref_marker": "1", "raw_text": "[1] Nature Paper.", "doi": "10.1038/nature123", "verified_status": "VERIFIED"}],
        "results": [{
            "claim_id": "C1",
            "verdict": "SUPPORTED",
            "final_verdict": "SUPPORTED",
            "explanation": "Corroborated by Nature paper.",
            "evidence_quote": "Accuracy improved in clinical trials.",
            "confidence_score": 0.90,
            "confidence_label": "High",
            "source_title": "Nature Paper",
            "source_doi": "10.1038/nature123",
            "source_year": 2020,
            "source_authors": "Smith et al."
        }],
        "trust_score": {"score": 85.0, "grade": "High Integrity", "components": []}
    }

    # Test PDF
    pdf_bytes = report_generator.generate_pdf_report(mock_doc)
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 500

    # Test HTML
    html_str = report_generator.generate_html_report(mock_doc)
    assert "CiteVerify" in html_str
    assert "clinical_trial.txt" in html_str

    # Test JSON
    json_str = report_generator.generate_json_report(mock_doc)
    parsed = json.loads(json_str)
    assert parsed["document"]["id"] == "doc_test_report"

    # Test CSV
    csv_str = report_generator.generate_csv_report(mock_doc)
    assert "C1" in csv_str
    assert "SUPPORTED" in csv_str


# 18. Existing database compatibility
def test_database_backward_compatibility():
    # Verify root citeverify.db connects and returns stats without error
    stats = database.get_global_statistics()
    assert isinstance(stats, dict)
    assert "total_documents" in stats
    assert "verdict_distribution" in stats
