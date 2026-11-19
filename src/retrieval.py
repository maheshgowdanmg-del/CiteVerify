"""Step 3 - locate the original paper using free scholarly APIs.

APIs used: Crossref, OpenAlex, Semantic Scholar, arXiv, Unpaywall.
Every HTTP response is cached in SQLite so repeated runs are fast, cheap and reproducible.
"""
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from difflib import SequenceMatcher
from urllib.parse import quote

import requests

from . import config, storage


# ---------------- HTTP helper with cache ----------------
def _get(url, params=None, headers=None, as_json=True):
    key = "http:" + hashlib.sha256(json.dumps([url, params], sort_keys=True).encode()).hexdigest()
    hit = storage.cache_get(key)
    if hit is not None:
        return hit
    try:
        r = requests.get(
            url,
            params=params,
            headers={"User-Agent": config.USER_AGENT, **(headers or {})},
            timeout=config.HTTP_TIMEOUT,
        )
        if r.status_code != 200:
            return None
        out = r.json() if as_json else r.text
    except Exception:
        return None
    storage.cache_set(key, out)
    return out


def _norm(s):
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()


def title_score(query, cand_title, query_is_raw=False):
    a, b = _norm(query), _norm(cand_title)
    if not a or not b:
        return 0.0
    seq = SequenceMatcher(None, a, b).ratio()
    if query_is_raw:  # query is the full reference string -> measure containment
        bt = set(b.split())
        return max(seq, len(bt & set(a.split())) / len(bt))
    return seq


# ---------------- Crossref ----------------
def _crossref_norm(item):
    year = None
    try:
        year = item["issued"]["date-parts"][0][0]
    except Exception:
        pass
    updated_by = item.get("updated-by", []) or []
    retracted = any((u.get("type") or "").lower() in ("retraction", "withdrawal") for u in updated_by)
    title = (item.get("title") or [""])[0]
    if title.lower().startswith("retracted"):
        retracted = True
    abstract = re.sub(r"<[^>]+>", " ", item.get("abstract", "") or "")
    return {
        "provider": "crossref",
        "title": title,
        "year": year,
        "doi": item.get("DOI"),
        "authors": [a.get("family", "") for a in item.get("author", [])][:6],
        "abstract": re.sub(r"\s+", " ", abstract).strip(),
        "url": item.get("URL"),
        "retracted": retracted,
    }


def crossref_by_doi(doi):
    data = _get(f"https://api.crossref.org/works/{quote(doi, safe='/')}", {"mailto": config.CONTACT_EMAIL})
    return _crossref_norm(data["message"]) if data and "message" in data else None


def crossref_search(query):
    data = _get(
        "https://api.crossref.org/works",
        {"query.bibliographic": query[:300], "rows": 3, "mailto": config.CONTACT_EMAIL},
    )
    try:
        return [_crossref_norm(i) for i in data["message"]["items"]]
    except Exception:
        return []


# ---------------- OpenAlex ----------------
def _abstract_from_inverted(idx):
    if not idx:
        return ""
    words = {}
    for w, positions in idx.items():
        for p in positions:
            words[p] = w
    return " ".join(words[i] for i in sorted(words))


def _openalex_norm(w):
    loc = w.get("best_oa_location") or {}
    return {
        "provider": "openalex",
        "title": w.get("title") or "",
        "year": w.get("publication_year"),
        "doi": (w.get("doi") or "").replace("https://doi.org/", "") or None,
        "authors": [(a.get("author") or {}).get("display_name", "") for a in w.get("authorships", [])][:6],
        "abstract": _abstract_from_inverted(w.get("abstract_inverted_index")),
        "url": (w.get("primary_location") or {}).get("landing_page_url") or w.get("id"),
        "retracted": bool(w.get("is_retracted")),
        "cited_by": w.get("cited_by_count"),
        "pdf_url": loc.get("pdf_url"),
    }


def openalex_by_doi(doi):
    w = _get(f"https://api.openalex.org/works/https://doi.org/{quote(doi, safe='/')}", {"mailto": config.CONTACT_EMAIL})
    return _openalex_norm(w) if w and w.get("id") else None


def openalex_search(query):
    data = _get("https://api.openalex.org/works", {"search": query[:250], "per-page": 3, "mailto": config.CONTACT_EMAIL})
    try:
        return [_openalex_norm(w) for w in data["results"]]
    except Exception:
        return []


# ---------------- Semantic Scholar ----------------
S2_FIELDS = "title,abstract,year,authors,externalIds,openAccessPdf,citationCount,url"


def _s2_norm(p):
    ext = p.get("externalIds") or {}
    return {
        "provider": "semantic_scholar",
        "title": p.get("title") or "",
        "year": p.get("year"),
        "doi": ext.get("DOI"),
        "arxiv": ext.get("ArXiv"),
        "authors": [a.get("name", "") for a in p.get("authors", [])][:6],
        "abstract": p.get("abstract") or "",
        "url": p.get("url"),
        "cited_by": p.get("citationCount"),
        "pdf_url": (p.get("openAccessPdf") or {}).get("url"),
    }


def _s2_headers():
    return {"x-api-key": config.S2_API_KEY} if config.S2_API_KEY else {}


def s2_by_id(paper_id):
    p = _get(f"https://api.semanticscholar.org/graph/v1/paper/{quote(paper_id, safe=':/')}", {"fields": S2_FIELDS}, _s2_headers())
    return _s2_norm(p) if p and p.get("title") else None


def s2_search(query):
    data = _get(
        "https://api.semanticscholar.org/graph/v1/paper/search",
        {"query": query[:250], "limit": 3, "fields": S2_FIELDS},
        _s2_headers(),
    )
    try:
        return [_s2_norm(p) for p in data["data"]]
    except Exception:
        return []


# ---------------- arXiv ----------------
_ATOM = "{http://www.w3.org/2005/Atom}"


def _arxiv_parse(xml_text):
    out = []
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return out
    for e in root.findall(f"{_ATOM}entry"):
        aid = (e.findtext(f"{_ATOM}id") or "").rsplit("/abs/", 1)[-1]
        aid = re.sub(r"v\d+$", "", aid)
        pub = e.findtext(f"{_ATOM}published") or ""
        out.append(
            {
                "provider": "arxiv",
                "title": re.sub(r"\s+", " ", e.findtext(f"{_ATOM}title") or "").strip(),
                "year": int(pub[:4]) if pub[:4].isdigit() else None,
                "arxiv": aid,
                "authors": [a.findtext(f"{_ATOM}name") or "" for a in e.findall(f"{_ATOM}author")][:6],
                "abstract": re.sub(r"\s+", " ", e.findtext(f"{_ATOM}summary") or "").strip(),
                "url": f"https://arxiv.org/abs/{aid}",
                "pdf_url": f"https://arxiv.org/pdf/{aid}",
            }
        )
    return out


def arxiv_by_id(aid):
    xml = _get("https://export.arxiv.org/api/query", {"id_list": aid}, as_json=False)
    res = _arxiv_parse(xml) if xml else []
    return res[0] if res else None


def arxiv_search(title):
    xml = _get("https://export.arxiv.org/api/query", {"search_query": f'ti:"{title[:200]}"', "max_results": 3}, as_json=False)
    return _arxiv_parse(xml) if xml else []


# ---------------- Unpaywall + PDF download ----------------
def unpaywall_pdf(doi):
    data = _get(f"https://api.unpaywall.org/v2/{quote(doi, safe='/')}", {"email": config.CONTACT_EMAIL})
    if not data:
        return None
    loc = data.get("best_oa_location") or {}
    return loc.get("url_for_pdf")


def fetch_pdf_pages(url):
    """Download an open-access PDF and return [(page, text)]. Cached. Returns [] on any problem."""
    key = "pdf:" + hashlib.sha256(url.encode()).hexdigest()
    hit = storage.cache_get(key)
    if hit is not None:
        return [tuple(x) for x in hit]
    try:
        r = requests.get(url, headers={"User-Agent": config.USER_AGENT}, timeout=30, stream=True)
        if r.status_code != 200:
            return []
        data = b""
        for chunk in r.iter_content(65536):
            data += chunk
            if len(data) > config.MAX_PDF_BYTES:
                return []
        if not data.startswith(b"%PDF"):
            return []
        from .extract import pdf_pages

        pages = pdf_pages(data, config.MAX_PDF_PAGES)
    except Exception:
        return []
    storage.cache_set(key, pages)
    return pages


# ---------------- Orchestrator ----------------
def _first(*vals):
    for v in vals:
        if v:
            return v
    return None


def resolve_reference(ref: dict) -> dict:
    """Find the cited publication. Returns a normalised 'source' dict (never raises)."""
    src = {
        "found": False, "title": "", "authors": [], "year": None, "doi": ref.get("doi"), "arxiv": ref.get("arxiv"),
        "url": "", "abstract": "", "pages": [], "access": "none", "retracted": False, "cited_by": None,
        "match_score": 0.0, "doi_valid": None, "providers": [], "notes": [],
    }
    try:
        query = ref.get("title") or ref["raw"]
        is_raw = not ref.get("title")
        cands = []

        if ref.get("doi"):
            cr = crossref_by_doi(ref["doi"])
            src["doi_valid"] = cr is not None
            if not cr:
                src["notes"].append("DOI did not resolve in Crossref")
            for c in (cr, openalex_by_doi(ref["doi"]), s2_by_id("DOI:" + ref["doi"])):
                if c:
                    cands.append(c)
        if ref.get("arxiv"):
            for c in (arxiv_by_id(ref["arxiv"]), s2_by_id("ARXIV:" + ref["arxiv"])):
                if c:
                    cands.append(c)
        if not cands:  # no identifier (or identifiers failed) -> search by title / full text
            for fn in (crossref_search, openalex_search, s2_search, arxiv_search):
                if fn is arxiv_search and not ref.get("title"):
                    continue
                for c in fn(query):
                    if title_score(query, c["title"], is_raw) >= 0.55:
                        cands.append(c)
                if len(cands) >= 2:
                    break

        if not cands:
            src["notes"].append("No matching publication found in Crossref, OpenAlex, Semantic Scholar or arXiv")
            return src

        cands.sort(key=lambda c: title_score(query, c["title"], is_raw), reverse=True)
        best = cands[0]
        src["match_score"] = round(title_score(query, best["title"], is_raw), 3)
        # identifiers given in the reference list are strong evidence of the right paper
        if ref.get("doi") and src["doi_valid"] or ref.get("arxiv"):
            src["match_score"] = max(src["match_score"], 0.75)
        src.update(found=True, title=best["title"], authors=best.get("authors", []), year=best.get("year"))
        src["providers"] = sorted({c["provider"] for c in cands})
        src["doi"] = _first(src["doi"], *[c.get("doi") for c in cands])
        src["arxiv"] = _first(src["arxiv"], *[c.get("arxiv") for c in cands])
        src["url"] = _first(*[c.get("url") for c in cands]) or ""
        if src["doi"]:
            src["url"] = f"https://doi.org/{src['doi']}"
        src["abstract"] = _first(*sorted([c.get("abstract", "") for c in cands], key=len, reverse=True)) or ""
        src["retracted"] = any(c.get("retracted") for c in cands)
        src["cited_by"] = _first(*[c.get("cited_by") for c in cands])

        # try to obtain open-access full text
        pdf_urls = [c.get("pdf_url") for c in cands if c.get("pdf_url")]
        if src["arxiv"]:
            pdf_urls.insert(0, f"https://arxiv.org/pdf/{src['arxiv']}")
        if src["doi"] and not pdf_urls:
            u = unpaywall_pdf(src["doi"])
            if u:
                pdf_urls.append(u)
        for u in dict.fromkeys(pdf_urls):
            pages = fetch_pdf_pages(u)
            if pages:
                src["pages"] = pages
                src["notes"].append(f"Open-access full text read from {u}")
                break
        src["access"] = "full_text" if src["pages"] else ("abstract" if src["abstract"] else "metadata")
    except Exception as exc:  # never crash the pipeline on a network problem
        src["notes"].append(f"Retrieval error: {exc}")
    return src


def age_years(src):
    return (datetime.now().year - src["year"]) if src.get("year") else None
