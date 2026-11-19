"""Citation and reference list parsing module for CiteVerify.
Parses in-text citation markers and extracts structured bibliographies.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .utils import clean_doi


# Regex patterns for in-text citations
IN_TEXT_NUMERIC_REGEX = re.compile(r"\[(\d+(?:\s*[-–,;\s]\s*\d+)*)\]")
IN_TEXT_AUTHOR_YEAR_REGEX = re.compile(r"\(([A-Z][a-zA-Z\s]+(?:et\s+al\.?)?,\s*(?:19|20)\d{2}(?:[a-z])?(?:;\s*[A-Z][a-zA-Z\s]+(?:et\s+al\.?)?,\s*(?:19|20)\d{2}(?:[a-z])?)*)\)")
IN_TEXT_CITATION_REGEX = re.compile(r"\[\d+(?:\s*[-–,;\s]\s*\d+)*\]|\([A-Z][a-zA-Z\s]+(?:et\s+al\.?)?,\s*(?:19|20)\d{2}[a-z]?(?:;\s*[A-Z][a-zA-Z\s]+(?:et\s+al\.?)?,\s*(?:19|20)\d{2}[a-z]?)*\)")



def extract_in_text_citations(text: str) -> List[Dict[str, Any]]:
    """Find all in-text citation markers and their spans in the document."""
    citations = []

    # Numbered brackets: [1], [1, 2], [1-3]
    for m in IN_TEXT_NUMERIC_REGEX.finditer(text):
        citations.append({
            "raw": m.group(0),
            "content": m.group(1),
            "start": m.start(),
            "end": m.end(),
            "type": "numeric"
        })

    # Author-Year: (Smith et al., 2020)
    for m in IN_TEXT_AUTHOR_YEAR_REGEX.finditer(text):
        citations.append({
            "raw": m.group(0),
            "content": m.group(1),
            "start": m.start(),
            "end": m.end(),
            "type": "author_year"
        })

    return sorted(citations, key=lambda x: x["start"])


def parse_reference_entry(raw_ref: str, fallback_marker: str = "") -> Dict[str, Any]:
    """Parse a single reference string into title, authors, year, journal, and DOI."""
    clean_ref = re.sub(r"\s+", " ", raw_ref).strip()
    
    # 1. Extract marker if present (e.g. [1] or 1.)
    marker_match = re.match(r"^(?:\[(\d+)\]|(\d+)\.|\(([A-Za-z0-9_-]+)\))\s*", clean_ref)
    ref_marker = fallback_marker
    if marker_match:
        ref_marker = marker_match.group(1) or marker_match.group(2) or marker_match.group(3)
        content = clean_ref[marker_match.end():].strip()
    else:
        content = clean_ref

    # 2. Extract DOI
    doi = clean_doi(content)

    # 3. Extract Year
    year = None
    year_match = re.search(r"\b((?:19|20)\d{2})\b", content)
    if year_match:
        year = int(year_match.group(1))

    # 4. Extract Authors and Title
    # Strategy A: Check for parenthesized year like Authors (2020). Title. Journal...
    year_paren_match = re.search(r"^(.*?)\s*\(((?:19|20)\d{2}[a-z]?)\)\.?\s+(.*)$", content)
    if year_paren_match:
        author_part = year_paren_match.group(1).strip()
        year = int(year_paren_match.group(2)[:4])
        rest = year_paren_match.group(3).strip()
        
        # Split rest by period to get title and journal
        rest_parts = [p.strip() for p in re.split(r"(?<=[a-zA-Z0-9\)])\.\s+", rest) if p.strip()]
        title = rest_parts[0] if rest_parts else rest[:120]
        journal = rest_parts[1] if len(rest_parts) > 1 else ""
        journal = re.sub(r"DOI:.*", "", journal, flags=re.I).strip()

        authors = [a.strip() for a in re.split(r",\s*(?:and\s+)?|&", author_part) if len(a.strip()) > 1][:6]
    else:
        # Strategy B: Standard period-separated parts
        parts = [p.strip() for p in re.split(r"(?<=[a-z0-9\)])\.\s+", content) if p.strip()]
        if len(parts) >= 2:
            first = parts[0]
            author_cand = re.sub(r"\((?:19|20)\d{2}\)", "", first).strip()
            authors = [a.strip() for a in re.split(r",\s*(?:and\s+)?|&", author_cand) if len(a.strip()) > 1][:6]
            title = parts[1].strip().strip('"').strip("'")
            journal = parts[2].strip() if len(parts) >= 3 else ""
            journal = re.sub(r"DOI:.*", "", journal, flags=re.I).strip()
        else:
            title = content[:120]
            authors = [content[:30]]
            journal = ""

    # Clean title
    title = re.sub(r"^[\"']|[\"']$", "", title).strip()
    if title.lower().startswith("doi:") or len(title) < 5:
        title = content[:150]

    return {
        "ref_marker": str(ref_marker or fallback_marker),
        "raw_text": clean_ref,
        "title": title,
        "authors": authors,
        "year": year,
        "doi": doi,
        "journal": journal,
        "verified_status": "UNVERIFIED"
    }


def parse_references_section(references_text: str) -> List[Dict[str, Any]]:
    """Parse complete reference block into structured reference items."""
    if not references_text:
        return []

    lines = references_text.splitlines()
    entries: List[str] = []
    current_entry: List[str] = []

    # Detect lines starting with [1], 1., or Author (Year)
    item_start_pattern = re.compile(r"^(?:\[\d+\]|\d+\.|\([A-Za-z0-9_-]+\))\s+")

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if item_start_pattern.match(stripped):
            if current_entry:
                entries.append(" ".join(current_entry))
                current_entry = []
            current_entry.append(stripped)
        elif current_entry:
            current_entry.append(stripped)
        else:
            current_entry.append(stripped)

    if current_entry:
        entries.append(" ".join(current_entry))

    # Parse each entry
    parsed_list: List[Dict[str, Any]] = []
    for idx, entry in enumerate(entries, 1):
        parsed = parse_reference_entry(entry, fallback_marker=str(idx))
        parsed_list.append(parsed)

    return parsed_list


def resolve_citation_to_reference(
    citation_marker: str, 
    references_list: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Resolve an in-text citation marker (e.g. '[1]', '1', 'Esteva et al., 2017') to its reference."""
    if not citation_marker or not references_list:
        return None

    # Clean marker
    clean_num = re.sub(r"[^\d]", "", citation_marker)
    if clean_num:
        for ref in references_list:
            if ref.get("ref_marker") == clean_num:
                return ref

    # Try matching by author name or year
    marker_lower = citation_marker.lower()
    for ref in references_list:
        # Check author matching
        for a in ref.get("authors") or []:
            last_name = a.split()[-1].lower() if a.split() else ""
            if last_name and last_name in marker_lower:
                if str(ref.get("year", "")) in marker_lower:
                    return ref

    return None
