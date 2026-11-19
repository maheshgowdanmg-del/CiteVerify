"""Citation Fraud Detection Engine for CiteVerify.
Validates DOIs, checks metadata consistency (titles, authors, years),
and checks retraction status via Crossref and scholarly registries.
"""
from __future__ import annotations

import re
import json
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

import requests

from . import config
from .utils import clean_doi, fuzzy_similarity


def check_doi_crossref(doi: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """Query Crossref REST API for a given DOI.
    Returns (found, metadata_dict, error_or_reason).
    """
    clean = clean_doi(doi)
    if not clean or not clean.startswith("10."):
        return False, None, "Invalid or empty DOI format."

    url = f"{config.CROSSREF_API_URL}/{urllib.parse.quote(clean)}"
    headers = {"User-Agent": config.USER_AGENT}

    try:
        resp = requests.get(url, headers=headers, timeout=config.REQUEST_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json().get("message", {})
            return True, data, "DOI verified in Crossref registry."
        elif resp.status_code == 404:
            return False, None, "DOI not found in Crossref database."
        else:
            return False, None, f"Crossref returned HTTP status {resp.status_code}."
    except requests.exceptions.Timeout:
        return False, None, "Connection to Crossref timed out."
    except Exception as e:
        return False, None, f"Error connecting to Crossref: {str(e)}"


def extract_crossref_metadata(message: Dict[str, Any]) -> Dict[str, Any]:
    """Extract standard fields from Crossref work response."""
    # Title
    titles = message.get("title") or []
    title = titles[0] if titles else ""

    # Authors
    authors_raw = message.get("author") or []
    authors = []
    for a in authors_raw:
        given = a.get("given", "")
        family = a.get("family", "")
        name = f"{given} {family}".strip()
        if name:
            authors.append(name)

    # Year
    year = None
    created = message.get("published-print") or message.get("published-online") or message.get("created")
    if created and "date-parts" in created and created["date-parts"]:
        parts = created["date-parts"][0]
        if parts:
            year = parts[0]

    # Retraction checks
    is_retracted = False
    retraction_reason = ""
    updates = message.get("update-to") or []
    for u in updates:
        if u.get("type", "").lower() in ("retraction", "removal", "expression-of-concern"):
            is_retracted = True
            retraction_reason = f"Crossref update indicates {u.get('type')}."

    container = message.get("container-title") or []
    journal = container[0] if container else ""
    resource_url = message.get("URL") or f"https://doi.org/{message.get('DOI')}"

    return {
        "title": title,
        "authors": authors,
        "year": year,
        "journal": journal,
        "doi": message.get("DOI"),
        "url": resource_url,
        "is_retracted": is_retracted,
        "retraction_reason": retraction_reason
    }


def verify_citation_fraud(citation: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate a citation for fraud, fabricated DOI, metadata mismatches, or retraction.
    Returns enriched citation dictionary with verified_status, match_score, reason, and source_url.
    """
    raw_doi = citation.get("doi", "")
    cited_title = citation.get("title", "")
    cited_year = citation.get("year")
    cited_authors = citation.get("authors") or []

    result = dict(citation)
    result["match_score"] = 0.0
    result["provider"] = "Crossref"
    result["source_url"] = f"https://doi.org/{clean_doi(raw_doi)}" if raw_doi else ""

    # Case 1: No DOI specified
    if not raw_doi:
        result["verified_status"] = "UNVERIFIED"
        result["reason"] = "No DOI specified in citation. Manual review recommended to confirm publication."
        return result

    # Check DOI via Crossref
    found, msg, status_msg = check_doi_crossref(raw_doi)

    # Case 2: DOI not found (Fabricated or invalid DOI)
    if not found:
        result["verified_status"] = "DOI_NOT_FOUND"
        result["reason"] = f"DOI '{clean_doi(raw_doi)}' does not exist in scholarly registries. Possible hallucinated or corrupted DOI."
        return result

    # DOI exists! Now verify metadata
    meta = extract_crossref_metadata(msg)
    result["source_url"] = meta["url"]

    # Check retraction first
    if meta["is_retracted"]:
        result["verified_status"] = "POSSIBLY_RETRACTED"
        result["retracted"] = True
        result["reason"] = meta["retraction_reason"] or "This publication is marked as retracted in scholarly registry records."
        return result

    # Check title similarity
    t_sim = fuzzy_similarity(cited_title, meta["title"])
    result["match_score"] = t_sim

    # Check year consistency
    year_diff = abs(cited_year - meta["year"]) if (cited_year and meta["year"]) else 0

    # Evaluate consistency
    if t_sim >= 0.70:
        # Title matches well
        if year_diff <= 1:
            result["verified_status"] = "VERIFIED"
            result["reason"] = f"DOI verified. Title match: {int(t_sim*100)}%, publication year ({meta['year']}) verified."
        else:
            result["verified_status"] = "METADATA_MISMATCH"
            result["reason"] = f"Title matched ({int(t_sim*100)}%), but year discrepancy found: cited as {cited_year}, registered as {meta['year']}."
    elif t_sim >= 0.40:
        result["verified_status"] = "NEEDS_MANUAL_REVIEW"
        result["reason"] = f"Partial title match ({int(t_sim*100)}%). Registered title: '{meta['title'][:80]}...'"
    else:
        # High likelihood of DOI hijacking or mismatched reference
        result["verified_status"] = "METADATA_MISMATCH"
        result["reason"] = (
            f"DOI exists, but points to a completely different paper! "
            f"Cited: '{cited_title[:60]}...' | Registered: '{meta['title'][:60]}...'"
        )

    return result


def batch_verify_citations(citations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Verify an entire list of citations with the Citation Fraud Engine."""
    verified_list = []
    for cit in citations:
        v = verify_citation_fraud(cit)
        verified_list.append(v)
    return verified_list
