"""Automated tests for document extraction (PDF, DOCX, TXT) and reference section splitting."""
import os
import sys
from pathlib import Path
import pytest

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import pdf_extractor


def test_txt_extraction():
    sample_text = "This is a scientific paper.\n\nReferences\n[1] Nature 2020."
    data, pages = pdf_extractor.extract_from_txt(sample_text.encode("utf-8"))
    assert "This is a scientific paper." in data
    assert pages >= 1


def test_reference_section_splitting():
    text = (
        "1. Introduction\n"
        "Deep learning achieves 95% sensitivity [1].\n\n"
        "References\n"
        "[1] Esteva et al. (2017). Dermatologist-level classification. Nature."
    )
    body, refs = pdf_extractor.split_body_and_references(text)
    assert "Deep learning achieves 95% sensitivity" in body
    assert "[1] Esteva et al." in refs
    assert "References" not in refs.strip()


def test_process_uploaded_document_sample_file():
    sample_path = Path(__file__).resolve().parent.parent / "data" / "sample" / "sample_paper.txt"
    assert sample_path.exists(), "Sample paper must exist"
    
    with open(sample_path, "rb") as f:
        content = f.read()
        
    doc_meta = pdf_extractor.process_uploaded_document(content, "sample_paper.txt")
    assert doc_meta["file_type"] == "TXT"
    assert doc_meta["char_count"] > 500
    assert len(doc_meta["body_text"]) > 100
    assert len(doc_meta["references_text"]) > 100
    assert "McKinney" in doc_meta["references_text"]


def test_empty_file_validation():
    with pytest.raises(ValueError, match="empty"):
        pdf_extractor.process_uploaded_document(b"", "empty.txt")


def test_unsupported_file_extension():
    with pytest.raises(ValueError, match="Unsupported file format"):
        pdf_extractor.process_uploaded_document(b"hello world", "test.xyz")
