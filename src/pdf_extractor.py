"""Document extraction module for CiteVerify.
Supports PDF (PyMuPDF / pypdf), DOCX (python-docx), and TXT files.
Detects reference sections and separates body text from bibliographies.
"""
from __future__ import annotations

import io
import re
from typing import Any, Dict, List, Optional, Tuple

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB limit

# Regex for common academic bibliography section headings
REF_HEADER_REGEX = re.compile(
    r"\n\s*(?:[0-9]+\.?\s*)?(?:references|bibliography|works\s+cited|literature\s+cited|sources)\b",
    re.IGNORECASE
)


def extract_from_pdf(file_bytes: bytes) -> Tuple[str, int]:
    """Extract full text and page count from PDF using PyMuPDF or pypdf."""
    text_parts: List[str] = []
    page_count = 1

    # Attempt PyMuPDF (fitz)
    try:
        import pymupdf
        doc = pymupdf.open(stream=file_bytes, filetype="pdf")
        page_count = len(doc)
        for page in doc:
            t = page.get_text("text")
            if t:
                text_parts.append(t)
        doc.close()
        if text_parts:
            return "\n\n".join(text_parts), page_count
    except Exception:
        pass

    # Fallback to pypdf
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        page_count = len(reader.pages)
        for page in reader.pages:
            t = page.extract_text()
            if t:
                text_parts.append(t)
        if text_parts:
            return "\n\n".join(text_parts), page_count
    except Exception as e:
        raise ValueError(f"Failed to extract text from PDF: {e}")

    return "\n\n".join(text_parts), page_count


def extract_from_docx(file_bytes: bytes) -> Tuple[str, int]:
    """Extract text from DOCX file using python-docx."""
    try:
        import docx
        doc = docx.Document(io.BytesIO(file_bytes))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        full_text = "\n\n".join(paragraphs)
        # Approximate page count based on word/character count
        approx_pages = max(1, len(full_text.split()) // 450)
        return full_text, approx_pages
    except Exception as e:
        raise ValueError(f"Failed to extract text from DOCX: {e}")


def extract_from_txt(file_bytes: bytes) -> Tuple[str, int]:
    """Extract text from TXT file with utf-8 / latin-1 decoding."""
    try:
        text = file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = file_bytes.decode("latin-1", errors="replace")
    approx_pages = max(1, len(text.split()) // 450)
    return text, approx_pages


def split_body_and_references(full_text: str) -> Tuple[str, str]:
    """Locate the References section and split text into body and reference blocks."""
    if not full_text:
        return "", ""

    matches = list(REF_HEADER_REGEX.finditer(full_text))
    if not matches:
        # If no explicit header, check if numbered reference bracket blocks [1] dominate towards the end
        last_bracket = full_text.rfind("[1]")
        if last_bracket != -1 and last_bracket > len(full_text) * 0.5:
            return full_text[:last_bracket].strip(), full_text[last_bracket:].strip()
        return full_text.strip(), ""

    # Choose the last match if multiple occur (e.g. references mentioned in introduction vs at the end)
    best_match = matches[-1]
    body = full_text[:best_match.start()].strip()
    references = full_text[best_match.end():].strip()
    return body, references


def process_uploaded_document(file_bytes: bytes, filename: str) -> Dict[str, Any]:
    """Validate uploaded document and return structured extracted text and metadata."""
    if not file_bytes:
        raise ValueError("Uploaded file is empty (0 bytes).")

    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise ValueError(f"File size exceeds 50MB limit ({len(file_bytes) / (1024*1024):.1f} MB).")

    ext = filename.lower().split(".")[-1]
    if ext == "pdf":
        raw_text, page_count = extract_from_pdf(file_bytes)
        file_type = "PDF"
    elif ext in ("docx", "doc"):
        raw_text, page_count = extract_from_docx(file_bytes)
        file_type = "DOCX"
    elif ext in ("txt", "md"):
        raw_text, page_count = extract_from_txt(file_bytes)
        file_type = "TXT"
    else:
        raise ValueError(f"Unsupported file format: .{ext}. Please upload PDF, DOCX, or TXT.")

    if not raw_text.strip():
        raise ValueError("Could not extract any readable text. Scanned or image-only documents without an OCR text layer are not supported.")

    body_text, references_text = split_body_and_references(raw_text)

    return {
        "filename": filename,
        "file_type": file_type,
        "raw_text": raw_text,
        "body_text": body_text,
        "references_text": references_text,
        "page_count": page_count,
        "char_count": len(raw_text),
        "word_count": len(raw_text.split())
    }
