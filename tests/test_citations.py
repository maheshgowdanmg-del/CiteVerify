"""Automated tests for citation parsing, DOI validation, metadata matching, and fraud detection."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import citation_parser, citation_checker, utils


def test_in_text_citation_extraction():
    text = "Recent studies show high accuracy [1] and multi-center validation [2, 3] or (Esteva et al., 2017)."
    in_text = citation_parser.extract_in_text_citations(text)
    
    assert len(in_text) == 3
    assert in_text[0]["raw"] == "[1]"
    assert in_text[1]["raw"] == "[2, 3]"
    assert "Esteva" in in_text[2]["raw"]


def test_parse_reference_entry_with_doi():
    entry = "[1] McKinney, S. M., et al. (2020). International evaluation of an AI system. Nature, 577, 89–94. DOI: 10.1038/s41586-019-1799-6"
    parsed = citation_parser.parse_reference_entry(entry, fallback_marker="1")
    
    assert parsed["ref_marker"] == "1"
    assert "McKinney" in parsed["authors"][0]
    assert parsed["year"] == 2020
    assert parsed["doi"] == "10.1038/s41586-019-1799-6"
    assert "International evaluation" in parsed["title"]


def test_clean_doi():
    assert utils.clean_doi("https://doi.org/10.1038/nature21056") == "10.1038/nature21056"
    assert utils.clean_doi("DOI: 10.1016/S2589-7500(19)30123-2.") == "10.1016/S2589-7500(19)30123-2"
    assert utils.clean_doi("invalid_string") == "invalid_string"


def test_citation_fraud_detection_offline_mock(monkeypatch):
    """Test citation fraud logic with mocked Crossref responses."""
    # 1. Test genuine verified paper
    def mock_check_crossref_success(doi):
        return True, {
            "title": ["International evaluation of an AI system for breast cancer screening"],
            "author": [{"family": "McKinney", "given": "Scott"}],
            "published-print": {"date-parts": [[2020]]},
            "DOI": "10.1038/s41586-019-1799-6",
            "URL": "https://doi.org/10.1038/s41586-019-1799-6"
        }, "Found"

    monkeypatch.setattr(citation_checker, "check_doi_crossref", mock_check_crossref_success)

    citation_valid = {
        "title": "International evaluation of an AI system for breast cancer screening",
        "doi": "10.1038/s41586-019-1799-6",
        "year": 2020,
        "authors": ["McKinney et al."]
    }
    res_valid = citation_checker.verify_citation_fraud(citation_valid)
    assert res_valid["verified_status"] == "VERIFIED"
    assert res_valid["match_score"] >= 0.70

    # 2. Test metadata mismatch (DOI hijacked for completely different paper)
    def mock_check_crossref_mismatch(doi):
        return True, {
            "title": ["Quantum Cryptography in Satellite Networks"],
            "author": [{"family": "Quantum", "given": "Jane"}],
            "published-print": {"date-parts": [[2012]]},
            "DOI": "10.1038/quantum123",
            "URL": "https://doi.org/10.1038/quantum123"
        }, "Found"

    monkeypatch.setattr(citation_checker, "check_doi_crossref", mock_check_crossref_mismatch)

    citation_mismatch = {
        "title": "Deep learning in oncology and cancer diagnosis",
        "doi": "10.1038/quantum123",
        "year": 2022,
        "authors": ["Smith et al."]
    }
    res_mismatch = citation_checker.verify_citation_fraud(citation_mismatch)
    assert res_mismatch["verified_status"] == "METADATA_MISMATCH"
    assert "different paper" in res_mismatch["reason"].lower()

    # 3. Test fabricated / not found DOI
    def mock_check_crossref_notfound(doi):
        return False, None, "DOI not found in Crossref"

    monkeypatch.setattr(citation_checker, "check_doi_crossref", mock_check_crossref_notfound)

    citation_fake = {
        "title": "Fabricated Neural Paradigms",
        "doi": "10.9999/fake.doi.2024.00192",
        "year": 2024,
        "authors": ["Imaginary et al."]
    }
    res_fake = citation_checker.verify_citation_fraud(citation_fake)
    assert res_fake["verified_status"] == "DOI_NOT_FOUND"
    assert "does not exist" in res_fake["reason"]
