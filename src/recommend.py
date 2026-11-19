"""Source recommender: suggests published papers worth reading for a claim.

Design rules (important for academic integrity):
* A recommendation is a *candidate to read and verify*, never proof of support.
  Every candidate carries ``support_verified = False``.
* Nothing is invented. If no provider can be reached, the result is empty and the
  reason is reported in ``provider_status``.
* Retracted papers are never recommended; they are listed under ``avoid``.
* Ranking is transparent: each candidate exposes its component scores and reasons.

Free providers used (no paid API needed): OpenAlex, Semantic Scholar, Crossref.
"""
from __future__ import annotations

import copy
import csv
import difflib
import io
import logging
import math
import re
from datetime import date

import requests

log = logging.getLogger(__name__)

DEFAULT_PROVIDERS = ("openalex", "semanticscholar", "crossref")
OPENALEX_URL = "https://api.openalex.org/works"
S2_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
CROSSREF_URL = "https://api.crossref.org/works"
TIMEOUT = 15

# Component weights (sum = 1.0). "number_match" is only applied when the claim has numbers;
# the remaining weights are then renormalised.
WEIGHTS = {
    "relevance": 0.45,      # TF-IDF cosine between claim and title+abstract
    "number_match": 0.10,   # claim numbers that also appear in the title/abstract
    "accessibility": 0.15,  # open-access full text > abstract only > metadata only
    "authority": 0.15,      # log-scaled citation count
    "recency": 0.10,        # gentle decay; old papers are never discarded for age alone
    "integrity": 0.05,      # known-not-retracted > unknown
}

STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "have", "has", "had", "are", "was", "were", "been",
    "being", "will", "would", "can", "could", "may", "might", "into", "than", "then", "their", "there", "these",
    "those", "which", "while", "when", "where", "who", "whom", "what", "also", "such", "its", "our", "your",
    "not", "but", "all", "any", "some", "more", "most", "much", "many", "very", "about", "over", "under",
    "between", "within", "across", "among", "per", "via", "show", "shows", "showed", "shown", "study",
    "studies", "found", "finding", "findings", "result", "results", "research", "evidence", "significant",
    "significantly", "recent", "recently", "based", "using", "used", "use", "paper", "papers", "report",
    "reported", "reports", "according", "however", "therefore", "thus",
}

_CACHE: dict[tuple, list] = {}


# --------------------------------------------------------------------------- text helpers
def clean_claim(text: str) -> str:
    """Remove citation markers like [3], [1-3] and (Author, 2019; Other, 2020) from a claim."""
    t = re.sub(r"\[[^\]]*\]", " ", text or "")
    t = re.sub(r"\((?:[^()]*?\b(?:19|20)\d{2}[a-z]?[^()]*)\)", " ", t)
    return " ".join(t.split())


def extract_numbers(text: str) -> list[str]:
    """Numbers in a claim, ignoring bare years (1900-2100) which are usually dates, not results."""
    nums = re.findall(r"\d+(?:\.\d+)?", clean_claim(text))
    out = []
    for n in nums:
        if "." not in n and 1900 <= int(n) <= 2100:
            continue
        if n not in out:
            out.append(n)
    return out


def build_query(claim: str, max_terms: int = 10) -> str:
    """Turn a claim into a compact keyword query (longer / capitalised terms are kept first)."""
    cleaned = clean_claim(claim)
    words = re.findall(r"[A-Za-z][A-Za-z\-]{2,}", cleaned)
    seen, scored = set(), []
    for i, w in enumerate(words):
        lw = w.lower()
        if lw in STOPWORDS or lw in seen:
            continue
        seen.add(lw)
        bonus = 3 if (w.isupper() or (w[0].isupper() and i > 0)) else 0
        scored.append((len(lw) + bonus, i, lw))
    top = sorted(scored, key=lambda t: (-t[0], t[1]))[:max_terms]
    return " ".join(w for _, _, w in sorted(top, key=lambda t: t[1]))


def _norm_doi(doi) -> str:
    d = (doi or "").strip().lower()
    return re.sub(r"^https?://(?:dx\.)?doi\.org/", "", d)


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", (text or "").lower()) if w not in STOPWORDS}


# --------------------------------------------------------------------------- providers
def _cand(**kw) -> dict:
    base = {"title": "", "authors": [], "year": None, "venue": "", "doi": "", "url": "", "cited_by": 0,
            "abstract": "", "open_access": None, "pdf_url": "", "retracted": None, "providers": []}
    base.update(kw)
    return base


def _get_json(http_get, url, params, headers=None):
    resp = http_get(url, params=params, headers=headers or {}, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _openalex_abstract(inv) -> str:
    if not inv:
        return ""
    pos = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos))


def _search_openalex(q, n, email, http_get):
    params = {"search": q, "per-page": n,
              "select": "id,display_name,publication_year,doi,cited_by_count,is_retracted,open_access,"
                        "primary_location,authorships,abstract_inverted_index"}
    if email:
        params["mailto"] = email
    data = _get_json(http_get, OPENALEX_URL, params)
    out = []
    for w in data.get("results") or []:
        src = (w.get("primary_location") or {}).get("source") or {}
        oa = w.get("open_access") or {}
        retracted = w.get("is_retracted")
        out.append(_cand(
            title=w.get("display_name") or "",
            authors=[((a.get("author") or {}).get("display_name") or "") for a in (w.get("authorships") or [])][:6],
            year=w.get("publication_year"),
            venue=src.get("display_name") or "",
            doi=_norm_doi(w.get("doi")),
            url=w.get("doi") or w.get("id") or "",
            cited_by=int(w.get("cited_by_count") or 0),
            abstract=_openalex_abstract(w.get("abstract_inverted_index")),
            open_access=bool(oa.get("is_oa")),
            pdf_url=oa.get("oa_url") or "",
            retracted=retracted if isinstance(retracted, bool) else None,
            providers=["openalex"],
        ))
    return out


def _search_s2(q, n, api_key, http_get):
    params = {"query": q, "limit": n,
              "fields": "title,year,abstract,citationCount,externalIds,openAccessPdf,url,venue,authors"}
    headers = {"x-api-key": api_key} if api_key else {}
    data = _get_json(http_get, S2_URL, params, headers)
    out = []
    for p in data.get("data") or []:
        pdf = (p.get("openAccessPdf") or {}).get("url") or ""
        doi = _norm_doi((p.get("externalIds") or {}).get("DOI"))
        out.append(_cand(
            title=p.get("title") or "",
            authors=[(a.get("name") or "") for a in (p.get("authors") or [])][:6],
            year=p.get("year"),
            venue=p.get("venue") or "",
            doi=doi,
            url=(f"https://doi.org/{doi}" if doi else p.get("url") or ""),
            cited_by=int(p.get("citationCount") or 0),
            abstract=p.get("abstract") or "",
            open_access=True if pdf else None,
            pdf_url=pdf,
            providers=["semanticscholar"],
        ))
    return out


def _search_crossref(q, n, email, http_get):
    params = {"query.bibliographic": q, "rows": n,
              "select": "DOI,title,author,issued,container-title,is-referenced-by-count,URL,abstract"}
    if email:
        params["mailto"] = email
    data = _get_json(http_get, CROSSREF_URL, params)
    out = []
    for it in (data.get("message") or {}).get("items") or []:
        parts = ((it.get("issued") or {}).get("date-parts") or [[None]])[0] or [None]
        authors = [f"{a.get('given', '')} {a.get('family', '')}".strip() for a in (it.get("author") or [])][:6]
        abstract = re.sub(r"<[^>]+>", " ", it.get("abstract") or "")
        doi = _norm_doi(it.get("DOI"))
        out.append(_cand(
            title=((it.get("title") or [""])[0]) or "",
            authors=authors,
            year=parts[0],
            venue=((it.get("container-title") or [""])[0]) or "",
            doi=doi,
            url=it.get("URL") or (f"https://doi.org/{doi}" if doi else ""),
            cited_by=int(it.get("is-referenced-by-count") or 0),
            abstract=" ".join(abstract.split()),
            providers=["crossref"],
        ))
    return out


# --------------------------------------------------------------------------- merge + score
def _merge(cands: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for c in cands:
        key = c["doi"] or _norm_title(c["title"])
        if not key:
            continue
        if key not in merged:
            merged[key] = copy.deepcopy(c)
            continue
        m = merged[key]
        for f in ("title", "venue", "doi", "url", "abstract", "pdf_url"):
            if not m[f] and c[f]:
                m[f] = c[f]
        if not m["authors"] and c["authors"]:
            m["authors"] = c["authors"]
        m["year"] = m["year"] or c["year"]
        m["cited_by"] = max(m["cited_by"], c["cited_by"])
        m["open_access"] = True if (m["open_access"] or c["open_access"]) else (
            m["open_access"] if m["open_access"] is not None else c["open_access"])
        if m["retracted"] is True or c["retracted"] is True:
            m["retracted"] = True
        elif m["retracted"] is False or c["retracted"] is False:
            m["retracted"] = False
        m["providers"] = sorted(set(m["providers"]) | set(c["providers"]))
    return list(merged.values())


def _relevance(claim_clean: str, cands: list[dict]) -> list[float]:
    texts = [f"{c['title']}. {c['abstract']}" for c in cands]
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
        mat = vec.fit_transform([claim_clean] + texts)
        return [float(s) for s in cosine_similarity(mat[0], mat[1:])[0]]
    except Exception:  # sklearn missing, or empty vocabulary
        ct = _tokens(claim_clean)
        return [len(ct & _tokens(t)) / max(1, len(ct | _tokens(t))) for t in texts]


def _recency(year, outdated_years: int, now: int) -> float:
    if not year:
        return 0.5
    age = now - int(year)
    half = outdated_years / 2
    if age <= half:
        return 1.0
    return max(0.4, 1 - 0.6 * (age - half) / (2.5 * outdated_years))


def _score(c: dict, cos: float, nums: list[str], outdated_years: int, now: int) -> tuple[float, dict, list[str], list[str]]:
    comps, reasons, flags = {}, [], []
    comps["relevance"] = min(1.0, cos / 0.45)
    if cos >= 0.25:
        reasons.append(f"Strong topical overlap with the claim (similarity {cos:.2f}).")
    elif cos >= 0.12:
        reasons.append(f"Moderate topical overlap with the claim (similarity {cos:.2f}).")
    else:
        reasons.append(f"Weak topical overlap (similarity {cos:.2f}); read critically.")

    if nums:
        hay = set(re.findall(r"\d+(?:\.\d+)?", f"{c['title']} {c['abstract']}"))
        hit = [n for n in nums if n in hay]
        comps["number_match"] = len(hit) / len(nums)
        if hit:
            reasons.append("Abstract mentions the claim's number(s): " + ", ".join(hit) + ".")
        elif c["abstract"]:
            reasons.append("The claim's number(s) do not appear in the abstract - check the full text.")

    if c["open_access"]:
        comps["accessibility"] = 1.0
        reasons.append("Open-access full text available, so the evidence can actually be checked.")
    elif c["abstract"]:
        comps["accessibility"] = 0.4
        reasons.append("Only the abstract is available from open metadata (full text may be paywalled).")
    else:
        comps["accessibility"] = 0.1
        flags.append("no_abstract")
        reasons.append("No abstract available from providers - relevance is based on the title only.")

    comps["authority"] = min(1.0, math.log10(1 + c["cited_by"]) / 3)
    if c["cited_by"]:
        reasons.append(f"Cited {c['cited_by']:,} times (a signal of influence, not of correctness).")

    comps["recency"] = _recency(c["year"], outdated_years, now)
    if c["year"]:
        age = now - int(c["year"])
        reasons.append(f"Published {c['year']} ({age} yr old)." + (
            " Older work can still be foundational; check whether newer studies superseded it."
            if age > outdated_years else ""))
        if age > outdated_years:
            flags.append("older_publication")

    comps["integrity"] = 1.0 if c["retracted"] is False else 0.6
    if c["retracted"] is None:
        flags.append("retraction_status_unknown")

    weights = {k: w for k, w in WEIGHTS.items() if k in comps}
    total_w = sum(weights.values())
    score = sum(comps[k] * w for k, w in weights.items()) / total_w
    return round(score * 100, 1), {k: round(v, 3) for k, v in comps.items()}, reasons, flags


# --------------------------------------------------------------------------- public API
def recommend_sources(claim: str, *, top_k: int = 5, cited_title: str | None = None,
                      providers=DEFAULT_PROVIDERS, contact_email: str | None = None,
                      s2_api_key: str | None = None, outdated_years: int = 10, per_provider: int = 12,
                      min_relevance: float = 0.04, http_get=None, today_year: int | None = None,
                      use_cache: bool = True) -> dict:
    """Return ranked candidate sources for ``claim``. See module docstring for guarantees."""
    http_get = http_get or requests.get
    now = today_year or date.today().year
    claim_clean = clean_claim(claim)
    result = {"ok": False, "query": "", "claim_clean": claim_clean, "numbers": extract_numbers(claim),
              "candidates": [], "avoid": [], "dropped_low_relevance": 0, "provider_status": {}, "notes": [],
              "weights": dict(WEIGHTS), "disclaimer": (
                  "Recommendations are papers worth reading to check this claim. They are NOT verified as "
                  "supporting it - read the source and confirm before citing.")}
    if len(claim_clean) < 20:
        result["notes"].append("Claim is too short to search reliably.")
        return result
    query = build_query(claim)
    result["query"] = query
    if not query:
        result["notes"].append("No searchable keywords could be extracted from the claim.")
        return result

    pool = []
    for name in providers:
        ck = (name, query, per_provider)
        try:
            if use_cache and ck in _CACHE:
                items = copy.deepcopy(_CACHE[ck])
            else:
                if name == "openalex":
                    items = _search_openalex(query, per_provider, contact_email, http_get)
                elif name == "semanticscholar":
                    items = _search_s2(query, per_provider, s2_api_key, http_get)
                elif name == "crossref":
                    items = _search_crossref(query, per_provider, contact_email, http_get)
                else:
                    raise ValueError(f"unknown provider {name}")
                if use_cache:
                    _CACHE[ck] = copy.deepcopy(items)
            result["provider_status"][name] = f"ok ({len(items)} results)"
            pool.extend(items)
        except Exception as exc:  # network error, rate limit, bad JSON ...
            log.warning("provider %s failed: %s", name, exc)
            result["provider_status"][name] = f"failed: {type(exc).__name__}: {str(exc)[:120]}"

    if not pool:
        result["notes"].append("No provider returned results, so no sources are recommended (nothing is invented).")
        return result

    cands = _merge(pool)
    # drop retraction notices and clearly retracted papers from the recommendation list
    keep = []
    for c in cands:
        t = c["title"].strip().lower()
        if t.startswith(("retraction", "retracted", "withdrawn")) or c["retracted"] is True:
            result["avoid"].append({"title": c["title"], "doi": c["doi"], "year": c["year"],
                                    "reason": "Retracted or a retraction notice - do not cite as support."})
        else:
            keep.append(c)

    sims = _relevance(claim_clean, keep) if keep else []
    ranked = []
    for c, cos in zip(keep, sims):
        if cos < min_relevance:
            result["dropped_low_relevance"] += 1
            continue
        score, comps, reasons, flags = _score(c, cos, result["numbers"], outdated_years, now)
        if cited_title and difflib.SequenceMatcher(None, _norm_title(cited_title), _norm_title(c["title"])).ratio() >= 0.85:
            flags.append("already_cited")
            reasons.insert(0, "This is the paper currently cited for the claim.")
        abstract = c["abstract"]
        ranked.append({
            "title": c["title"], "authors": c["authors"], "year": c["year"], "venue": c["venue"],
            "doi": c["doi"], "url": c["url"], "pdf_url": c["pdf_url"], "citation_count": c["cited_by"],
            "open_access": c["open_access"], "retracted": c["retracted"], "providers": c["providers"],
            "abstract_available": bool(abstract),
            "abstract_excerpt": (abstract[:320] + "…") if len(abstract) > 320 else abstract,
            "score": score, "components": comps, "similarity": round(cos, 3),
            "reasons": reasons, "flags": flags, "support_verified": False,
        })
    ranked.sort(key=lambda r: (-r["score"], -r["citation_count"]))
    for i, r in enumerate(ranked[:top_k], 1):
        r["rank"] = i
    result["candidates"] = ranked[:top_k]
    result["ok"] = bool(result["candidates"])
    if not ranked:
        result["notes"].append("Results were found but none were relevant enough to recommend.")
    return result


def recommendations_to_csv(reco: dict) -> str:
    """CSV export of a recommendation result (for the Export tab / report appendix)."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["rank", "score", "title", "year", "venue", "doi", "url", "open_access", "citations",
                "similarity", "flags", "support_verified", "providers"])
    for c in reco.get("candidates", []):
        w.writerow([c["rank"], c["score"], c["title"], c["year"], c["venue"], c["doi"], c["url"], c["open_access"],
                    c["citation_count"], c["similarity"], ";".join(c["flags"]), c["support_verified"],
                    ";".join(c["providers"])])
    return buf.getvalue()
