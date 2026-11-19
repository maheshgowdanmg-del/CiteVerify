"""Step 1 - read PDF / DOCX / TXT and split body from reference list."""
import io
import re


def extract_text(data: bytes, filename: str) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        return _pdf_text(data)
    if name.endswith(".docx"):
        return _docx_text(data)
    return data.decode("utf-8", errors="ignore")


def _pdf_text(data: bytes) -> str:
    import fitz  # PyMuPDF

    with fitz.open(stream=data, filetype="pdf") as doc:
        return "\n".join(page.get_text() for page in doc)


def pdf_pages(data: bytes, max_pages: int = 60):
    """Return [(page_number, text), ...] so evidence can cite a page."""
    import fitz

    out = []
    with fitz.open(stream=data, filetype="pdf") as doc:
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            out.append((i + 1, page.get_text()))
    return out


def _docx_text(data: bytes) -> str:
    import docx

    document = docx.Document(io.BytesIO(data))
    return "\n".join(p.text for p in document.paragraphs)


_REF_HEADING = re.compile(
    r"^\s*(?:\d+\.?\s*)?(references|bibliography|works cited|literature cited)\s*:?\s*$", re.I | re.M
)


def split_references(text: str):
    """Return (body, reference_list_text). Uses the LAST 'References' heading."""
    matches = list(_REF_HEADING.finditer(text))
    if not matches:
        return text, ""
    m = matches[-1]
    return text[: m.start()], text[m.end():]
