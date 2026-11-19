"""Original research retrieval engine for CiteVerify.
Retrieves academic papers, abstracts, and open-access metadata from
Crossref, OpenAlex, Semantic Scholar, and PubMed.
"""
from __future__ import annotations

import re
import json
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

import requests

from . import config
from .utils import clean_doi, fuzzy_similarity

# In-memory search cache to respect API rate limits
_RETRIEVAL_CACHE: Dict[str, Dict[str, Any]] = {}


def retrieve_paper_by_doi(doi: str) -> Optional[Dict[str, Any]]:
    """Retrieve full metadata and abstract for a known DOI via OpenAlex and Crossref."""
    clean = clean_doi(doi)
    if not clean:
        return None

    if clean in _RETRIEVAL_CACHE:
        return _RETRIEVAL_CACHE[clean]

    # Try OpenAlex works endpoint first (OpenAlex has inverted abstracts easily reconstitutable)
    openalex_url = f"{config.OPENALEX_API_URL}/https://doi.org/{urllib.parse.quote(clean)}"
    headers = {"User-Agent": config.USER_AGENT}

    try:
        resp = requests.get(openalex_url, headers=headers, timeout=config.REQUEST_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            # Reconstruct inverted abstract
            abstract = ""
            inv = data.get("abstract_inverted_index")
            if inv:
                words = {}
                for word, positions in inv.items():
                    for pos in positions:
                        words[pos] = word
                abstract = " ".join(words[p] for p in sorted(words))

            authors = [a.get("author", {}).get("display_name", "") for a in data.get("authorships", []) if a.get("author")]
            
            result = {
                "title": data.get("display_name") or data.get("title", ""),
                "authors": [a for a in authors if a][:6],
                "year": data.get("publication_year"),
                "journal": (data.get("primary_location") or {}).get("source", {}).get("display_name", ""),
                "doi": clean,
                "url": (data.get("primary_location") or {}).get("landing_page_url") or f"https://doi.org/{clean}",
                "abstract": abstract or "Abstract not openly indexed in registry.",
                "is_oa": (data.get("open_access") or {}).get("is_oa", False),
                "oa_url": (data.get("open_access") or {}).get("oa_url", ""),
                "is_retracted": data.get("is_retracted", False),
                "provider": "OpenAlex"
            }
            _RETRIEVAL_CACHE[clean] = result
            return result
    except Exception:
        pass

    # Fallback to Crossref
    try:
        crossref_url = f"{config.CROSSREF_API_URL}/{urllib.parse.quote(clean)}"
        resp = requests.get(crossref_url, headers=headers, timeout=config.REQUEST_TIMEOUT)
        if resp.status_code == 200:
            msg = resp.json().get("message", {})
            titles = msg.get("title") or []
            title = titles[0] if titles else ""
            abstract = msg.get("abstract", "")
            # Remove JATS XML tags if present in abstract
            abstract = re.sub(r"<[^>]+>", " ", abstract).strip()

            authors = []
            for a in msg.get("author") or []:
                name = f"{a.get('given', '')} {a.get('family', '')}".strip()
                if name:
                    authors.append(name)

            year = None
            date_parts = (msg.get("published-print") or msg.get("published-online") or msg.get("created", {})).get("date-parts", [])
            if date_parts and date_parts[0]:
                year = date_parts[0][0]

            container = msg.get("container-title") or []
            journal = container[0] if container else ""

            result = {
                "title": title,
                "authors": authors[:6],
                "year": year,
                "journal": journal,
                "doi": clean,
                "url": msg.get("URL") or f"https://doi.org/{clean}",
                "abstract": abstract or "Abstract not provided in Crossref record.",
                "is_oa": False,
                "oa_url": "",
                "is_retracted": False,
                "provider": "Crossref"
            }
            _RETRIEVAL_CACHE[clean] = result
            return result
    except Exception:
        pass

    return None


def search_openalex(query: str, limit: int = 3) -> List[Dict[str, Any]]:
    """Search OpenAlex for academic papers matching a text query."""
    if not query or len(query.strip()) < 4:
        return []

    cache_key = f"oa_{query[:60]}"
    if cache_key in _RETRIEVAL_CACHE:
        return _RETRIEVAL_CACHE[cache_key]

    url = f"{config.OPENALEX_API_URL}?search={urllib.parse.quote(query)}&per_page={limit}"
    headers = {"User-Agent": config.USER_AGENT}
    results = []

    try:
        resp = requests.get(url, headers=headers, timeout=config.REQUEST_TIMEOUT)
        if resp.status_code == 200:
            works = resp.json().get("results", [])
            for w in works:
                # Reconstruct abstract
                abstract = ""
                inv = w.get("abstract_inverted_index")
                if inv:
                    words = {}
                    for word, positions in inv.items():
                        for pos in positions:
                            words[pos] = word
                    abstract = " ".join(words[p] for p in sorted(words))

                authors = [a.get("author", {}).get("display_name", "") for a in w.get("authorships", []) if a.get("author")]
                doi_str = clean_doi(w.get("doi") or "")
                
                results.append({
                    "title": w.get("display_name") or w.get("title", ""),
                    "authors": [a for a in authors if a][:5],
                    "year": w.get("publication_year"),
                    "journal": (w.get("primary_location") or {}).get("source", {}).get("display_name", ""),
                    "doi": doi_str,
                    "url": (w.get("primary_location") or {}).get("landing_page_url") or (f"https://doi.org/{doi_str}" if doi_str else ""),
                    "abstract": abstract,
                    "is_oa": (w.get("open_access") or {}).get("is_oa", False),
                    "oa_url": (w.get("open_access") or {}).get("oa_url", ""),
                    "is_retracted": w.get("is_retracted", False),
                    "provider": "OpenAlex"
                })
    except Exception:
        pass

    _RETRIEVAL_CACHE[cache_key] = results
    return results


def search_pubmed(query: str, limit: int = 2) -> List[Dict[str, Any]]:
    """Search PubMed via NCBI E-utilities for biomedical claims."""
    if not query:
        return []

    cache_key = f"pm_{query[:60]}"
    if cache_key in _RETRIEVAL_CACHE:
        return _RETRIEVAL_CACHE[cache_key]

    results = []
    try:
        search_url = f"{config.PUBMED_ESEARCH_URL}?db=pubmed&term={urllib.parse.quote(query)}&retmode=json&retmax={limit}"
        resp = requests.get(search_url, timeout=config.REQUEST_TIMEOUT)
        if resp.status_code == 200:
            id_list = resp.json().get("esearchresult", {}).get("idlist", [])
            if id_list:
                ids_str = ",".join(id_list)
                summary_url = f"{config.PUBMED_ESUMMARY_URL}?db=pubmed&id={ids_str}&retmode=json"
                sum_resp = requests.get(summary_url, timeout=config.REQUEST_TIMEOUT)
                if sum_resp.status_code == 200:
                    sum_data = sum_resp.json().get("result", {})
                    for p_id in id_list:
                        item = sum_data.get(p_id)
                        if item:
                            title = item.get("title", "")
                            authors = [a.get("name") for a in item.get("authors", []) if a.get("name")]
                            doi = ""
                            for article_id in item.get("articleids", []):
                                if article_id.get("idtype") == "doi":
                                    doi = article_id.get("value")
                            pub_date = item.get("pubdate", "")
                            year_match = re.search(r"\b(19|20)\d{2}\b", pub_date)
                            year = int(year_match.group(0)) if year_match else None

                            results.append({
                                "title": title,
                                "authors": authors[:5],
                                "year": year,
                                "journal": item.get("source", ""),
                                "doi": clean_doi(doi),
                                "url": f"https://pubmed.ncbi.nlm.nih.gov/{p_id}/",
                                "abstract": "",
                                "is_oa": False,
                                "oa_url": "",
                                "is_retracted": False,
                                "provider": "PubMed"
                            })
    except Exception:
        pass

    _RETRIEVAL_CACHE[cache_key] = results
    return results


def retrieve_research_for_claim(
    claim: Dict[str, Any], 
    resolved_ref: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Retrieve the most relevant academic research paper and candidate evidence for a claim."""
    target_doi = ""
    query = ""

    if resolved_ref:
        target_doi = resolved_ref.get("doi", "")
        query = resolved_ref.get("title", "")

    if not query:
        query = claim.get("claim", "")[:120]

    paper_record = None

    # 1. Direct DOI retrieval if available
    if target_doi:
        paper_record = retrieve_paper_by_doi(target_doi)

    # 2. OpenAlex search if DOI was missing or abstract was empty
    if not paper_record or not paper_record.get("abstract") or len(paper_record.get("abstract", "")) < 30:
        candidates = search_openalex(query, limit=3)
        if candidates:
            # Pick best candidate by title similarity
            best = max(candidates, key=lambda c: fuzzy_similarity(c.get("title", ""), query))
            if not paper_record or (best.get("abstract") and len(best.get("abstract", "")) > len(paper_record.get("abstract", ""))):
                paper_record = best

    # 3. If biomedical and still lacking abstract, try PubMed
    if not paper_record and any(kw in query.lower() for kw in ("cancer", "patient", "clinical", "disease", "treatment")):
        pm_candidates = search_pubmed(query, limit=2)
        if pm_candidates:
            paper_record = pm_candidates[0]

    # Return structured record or empty fallback
    if paper_record:
        return paper_record

    # Fallback placeholder if entirely unindexed
    return {
        "title": resolved_ref.get("title", "Unknown Publication") if resolved_ref else "Unindexed Paper",
        "authors": resolved_ref.get("authors", []) if resolved_ref else [],
        "year": resolved_ref.get("year") if resolved_ref else None,
        "journal": resolved_ref.get("journal", "") if resolved_ref else "",
        "doi": target_doi,
        "url": f"https://doi.org/{target_doi}" if target_doi else "",
        "abstract": "The source paper could not be automatically retrieved from scholarly APIs. Full text required for offline audit.",
        "is_oa": False,
        "oa_url": "",
        "is_retracted": False,
        "provider": "None"
    }
