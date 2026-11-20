"""Original research retrieval engine for CiteVerify.
Retrieves academic papers, abstracts, and open-access metadata from
Crossref, OpenAlex, Semantic Scholar, and PubMed.
"""
from __future__ import annotations

import re
import json
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

import requests

from . import config
from .utils import clean_doi, fuzzy_similarity

# In-memory search cache to respect API rate limits
_RETRIEVAL_CACHE: Dict[str, Dict[str, Any]] = {}


def retrieve_paper_from_arxiv(arxiv_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve full metadata and abstract for an arXiv paper via the open arXiv export API."""
    clean_id = re.sub(r"^arxiv:\s*", "", arxiv_id.strip(), flags=re.I).strip()
    if not clean_id:
        return None

    cache_key = f"arxiv_{clean_id}"
    if cache_key in _RETRIEVAL_CACHE:
        return _RETRIEVAL_CACHE[cache_key]

    url = f"http://export.arxiv.org/api/query?id_list={urllib.parse.quote(clean_id)}"
    try:
        resp = requests.get(url, timeout=config.REQUEST_TIMEOUT)
        if resp.status_code == 200:
            root = ET.fromstring(resp.text)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            entry = root.find("atom:entry", ns)
            if entry is not None:
                title_elem = entry.find("atom:title", ns)
                summary_elem = entry.find("atom:summary", ns)
                title = title_elem.text.strip().replace("\n", " ") if title_elem is not None and title_elem.text else ""
                abstract = summary_elem.text.strip().replace("\n", " ") if summary_elem is not None and summary_elem.text else ""
                authors = [
                    a.find("atom:name", ns).text.strip()
                    for a in entry.findall("atom:author", ns)
                    if a.find("atom:name", ns) is not None and a.find("atom:name", ns).text
                ]
                published_elem = entry.find("atom:published", ns)
                year = int(published_elem.text[:4]) if published_elem is not None and published_elem.text and len(published_elem.text) >= 4 else None

                result = {
                    "title": title,
                    "authors": authors[:6],
                    "year": year,
                    "journal": f"arXiv:{clean_id}",
                    "doi": f"10.48550/arXiv.{clean_id}",
                    "url": f"https://arxiv.org/abs/{clean_id}",
                    "abstract": abstract,
                    "is_oa": True,
                    "oa_url": f"https://arxiv.org/pdf/{clean_id}.pdf",
                    "is_retracted": False,
                    "provider": "arXiv"
                }
                _RETRIEVAL_CACHE[cache_key] = result
                return result
    except Exception:
        pass

    return None


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


def search_crossref_title(query: str, limit: int = 3) -> List[Dict[str, Any]]:
    """Search Crossref REST API by title query as a reliable fallback."""
    if not query or len(query.strip()) < 5:
        return []

    cache_key = f"cr_q_{query[:60]}"
    if cache_key in _RETRIEVAL_CACHE:
        return _RETRIEVAL_CACHE[cache_key]

    url = f"{config.CROSSREF_API_URL}?query.title={urllib.parse.quote(query)}&rows={limit}"
    headers = {"User-Agent": config.USER_AGENT}
    results = []
    try:
        resp = requests.get(url, headers=headers, timeout=config.REQUEST_TIMEOUT)
        if resp.status_code == 200:
            items = resp.json().get("message", {}).get("items", [])
            for msg in items:
                titles = msg.get("title") or []
                t = titles[0] if titles else ""
                clean = msg.get("DOI", "")
                authors = []
                for a in msg.get("author") or []:
                    name = f"{a.get('given', '')} {a.get('family', '')}".strip()
                    if name:
                        authors.append(name)
                year = None
                date_parts = (msg.get("published-print") or msg.get("published-online") or msg.get("created", {})).get("date-parts", [])
                if date_parts and date_parts[0]:
                    year = date_parts[0][0]
                is_retracted = bool(msg.get("update-to") or "retraction" in t.lower())
                abstract = msg.get("abstract", "")
                abstract = re.sub(r"<[^>]+>", " ", abstract).strip()
                if is_retracted and not abstract:
                    abstract = f"RETRACTED PUBLICATION: This paper '{t}' was formally retracted in scholarly registry records."
                results.append({
                    "title": t,
                    "authors": authors[:6],
                    "year": year,
                    "journal": (msg.get("container-title") or [""])[0],
                    "doi": clean,
                    "url": msg.get("URL") or (f"https://doi.org/{clean}" if clean else ""),
                    "abstract": abstract or f"Publication registered in Crossref: '{t}'.",
                    "is_oa": False,
                    "oa_url": "",
                    "is_retracted": is_retracted,
                    "provider": "Crossref"
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
    target_arxiv = ""
    query = ""

    if resolved_ref:
        target_doi = resolved_ref.get("doi", "")
        target_arxiv = resolved_ref.get("arxiv", "")
        query = resolved_ref.get("title", "")
        if not target_arxiv:
            raw_text = resolved_ref.get("raw_text", "")
            ax_m = re.search(r"arXiv:\s*(\d{4}\.\d{4,5}(?:v\d+)?)", raw_text, re.I)
            if ax_m:
                target_arxiv = ax_m.group(1)

    if not query:
        query = claim.get("claim", "")[:120]

    paper_record = None

    # 1. Direct arXiv retrieval if arXiv ID is specified
    if target_arxiv:
        paper_record = retrieve_paper_from_arxiv(target_arxiv)

    # 2. Direct DOI retrieval if available
    if not paper_record and target_doi and target_doi.startswith("10."):
        paper_record = retrieve_paper_by_doi(target_doi)

    # 3. OpenAlex search if DOI was missing or abstract was empty
    if not paper_record or not paper_record.get("abstract") or len(paper_record.get("abstract", "")) < 30:
        candidates = search_openalex(query, limit=3)
        if candidates:
            # Pick best candidate by title similarity
            best = max(candidates, key=lambda c: fuzzy_similarity(c.get("title", ""), query))
            if not paper_record or (best.get("abstract") and len(best.get("abstract", "")) > len(paper_record.get("abstract", ""))):
                paper_record = best

    # 4. Crossref title search if OpenAlex was empty or ratelimited
    if not paper_record or not paper_record.get("abstract") or len(paper_record.get("abstract", "")) < 30:
        cr_candidates = search_crossref_title(query, limit=3)
        if cr_candidates:
            best_cr = max(cr_candidates, key=lambda c: fuzzy_similarity(c.get("title", ""), query))
            if fuzzy_similarity(best_cr.get("title", ""), query) >= 0.40:
                paper_record = best_cr

    # 5. If biomedical and still lacking abstract, try PubMed
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
