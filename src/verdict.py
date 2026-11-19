"""Step 4b/5 - compare claim with evidence, decide a verdict, verify the quote, compute confidence."""
import hashlib
import json
import re
from difflib import SequenceMatcher

from . import config, storage
from .matching import build_passages, numbers_in, rank_passages
from .retrieval import age_years

STATUS = {
    "supported": ("Supported", "#1a7f37"),
    "partly_supported": ("Partly supported", "#9a6700"),
    "unsupported": ("Unsupported", "#cf222e"),
    "contradictory": ("Contradictory", "#a40e26"),
    "possibly_outdated": ("Possibly outdated", "#8250df"),
    "cannot_verify": ("Cannot verify", "#57606a"),
    "missing_citation": ("Missing citation", "#bc4c00"),
    "bad_reference": ("Bad / not-found reference", "#cf222e"),
}
SEVERITY = {"contradictory": 0, "bad_reference": 1, "unsupported": 2, "missing_citation": 3, "partly_supported": 4,
            "possibly_outdated": 5, "cannot_verify": 6, "supported": 7}
ACCESS_SCORE = {"full_text": 1.0, "abstract": 0.6, "metadata": 0.2, "none": 0.0}


# ---------------- numeric check ----------------
def numeric_check(claim: str, passages: list):
    claim_nums = numbers_in(claim)
    evidence_nums = set()
    for p in passages:
        evidence_nums.update(numbers_in(p["text"]))
    matched = [n for n in claim_nums if n in evidence_nums]
    missing = [n for n in claim_nums if n not in evidence_nums]
    return {"claim_numbers": claim_nums, "matched": matched, "missing": missing}


# ---------------- quote verification (anti-hallucination) ----------------
def _n(s):
    s = s.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    s = re.sub(r"[\u2010-\u2015]", "-", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def verify_quote(quote: str, passages: list):
    """True only if the quoted evidence really exists in the retrieved source text."""
    nq = _n(quote or "")
    if len(nq) < 15:
        return False, None
    for p in passages:
        np_ = _n(p["text"])
        if nq in np_:
            return True, p
        m = SequenceMatcher(None, nq, np_, autojunk=False).find_longest_match(0, len(nq), 0, len(np_))
        if m.size / len(nq) >= 0.9:
            return True, p
    return False, None


# ---------------- LLM judge (free provider) ----------------
SYSTEM_PROMPT = """You are a meticulous scientific fact-checker. You receive a CLAIM from a document and numbered
PASSAGES from the paper cited for it. Decide whether the passages support the claim.
Rules:
- Use ONLY the passages. Never use outside knowledge about the paper.
- supported = passages clearly state the same finding, numbers and scope.
- partly_supported = related finding but numbers, scope, strength or causality differ.
- unsupported = passages do not contain the claimed finding.
- contradictory = passages state the opposite or an incompatible result.
- evidence_quote must be copied EXACTLY (max 40 words) from one passage, or null if none is relevant.
- Check numbers, populations/sample size, causal wording ('causes' vs 'associated with') and generalisation.
- certainty is your honest 0-1 certainty. Be conservative.
Reply with ONLY a JSON object:
{"verdict":"supported|partly_supported|unsupported|contradictory","explanation":"1-3 plain sentences",
 "evidence_passage_id":"P1 or null","evidence_quote":"exact text or null","certainty":0.0,
 "scope_issues":["short strings"]}"""


def _parse_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    a, b = text.find("{"), text.rfind("}")
    return json.loads(text[a : b + 1])


def llm_judge(claim: str, source: dict, passages: list):
    """Call any OpenAI-compatible chat endpoint (Groq / Gemini / Ollama - all have free options)."""
    key = "llm:" + hashlib.sha256(
        json.dumps([config.LLM_MODEL, claim, [p["text"] for p in passages]]).encode()
    ).hexdigest()
    hit = storage.cache_get(key)
    if hit:
        return hit
    import time

    import requests

    blocks = "\n".join(f'<passage id="{p["id"]}" section="{p["section"]}">{p["text"]}</passage>' for p in passages)
    user = (
        f"<claim>{claim}</claim>\n<cited_paper title=\"{source.get('title','')}\" year=\"{source.get('year')}\" "
        f"access=\"{source.get('access')}\"/>\n<passages>\n{blocks}\n</passages>"
    )
    headers = {"Content-Type": "application/json"}
    if config.LLM_API_KEY:
        headers["Authorization"] = f"Bearer {config.LLM_API_KEY}"
    body = {
        "model": config.LLM_MODEL, "temperature": 0, "max_tokens": 700,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
    }
    last = None
    for attempt in range(4):  # free tiers are rate-limited: back off and retry
        r = requests.post(f"{config.LLM_BASE_URL}/chat/completions", headers=headers, json=body, timeout=90)
        if r.status_code == 429 or r.status_code >= 500:
            last = f"HTTP {r.status_code}"
            time.sleep(2 * (attempt + 1) ** 2)
            continue
        r.raise_for_status()
        out = _parse_json(r.json()["choices"][0]["message"]["content"])
        storage.cache_set(key, out)
        time.sleep(1.0)  # gentle pacing for free-tier limits
        return out
    raise RuntimeError(f"LLM rate limit / server error ({last})")


def heuristic_judge(claim: str, passages: list, numeric: dict):
    """Offline fallback (no API key). Deliberately conservative; confidence is capped later."""
    top = passages[0]["raw_similarity"] if passages else 0.0
    if top < 0.08:
        v, why = "unsupported", "No passage in the retrieved text is lexically related to the claim."
    elif numeric["missing"]:
        v = "partly_supported" if top >= 0.2 else "unsupported"
        why = f"Related text found, but the numbers {numeric['missing']} do not appear in the evidence."
    elif top >= 0.35:
        v, why = "supported", "A highly similar passage was found and all numbers in the claim appear in it."
    else:
        v, why = "partly_supported", "Some related text was found but the match is weak."
    return {
        "verdict": v, "explanation": why + " (rule-based offline mode)",
        "evidence_passage_id": passages[0]["id"] if passages else None,
        "evidence_quote": passages[0]["text"][:250] if passages else None,
        "certainty": 0.35, "scope_issues": [], "_heuristic": True,
    }


# ---------------- confidence ----------------
def compute_confidence(top_sim, access, numeric, certainty, quote_ok, quote_needed, ref_match, used_llm):
    if not numeric["claim_numbers"]:
        num = 0.6
    elif not numeric["missing"]:
        num = 1.0
    elif not numeric["matched"]:
        num = 0.8 if access == "full_text" else 0.4
    else:
        num = 0.5
    comp = {
        "retrieval_similarity": round(min(1.0, top_sim / 0.5), 2),
        "source_access": ACCESS_SCORE.get(access, 0.0),
        "number_agreement": num,
        "model_certainty": round(certainty if used_llm else 0.35, 2),
        "quote_verified": 1.0 if quote_ok else (0.5 if not quote_needed else 0.0),
        "reference_match": round(min(1.0, ref_match), 2),
    }
    w = {"retrieval_similarity": .20, "source_access": .20, "number_agreement": .15,
         "model_certainty": .25, "quote_verified": .10, "reference_match": .10}
    score = sum(comp[k] * w[k] for k in w)
    if quote_needed and not quote_ok:
        score = min(score, 0.4)
    if not used_llm:
        score = min(score, 0.5)
    score = round(score, 2)
    return {"score": score, "label": "High" if score >= 0.75 else "Medium" if score >= 0.5 else "Low", "components": comp}


# ---------------- main entry ----------------
def verify_claim(claim: dict, ref: dict, source: dict, use_llm: bool):
    flags, base = [], {
        "claim_id": claim["id"], "claim": claim["text"], "citation": ref["raw"] if ref else "",
        "ref_id": ref["id"] if ref else None,
    }
    src_view = {k: source.get(k) for k in ("title", "year", "doi", "url", "access", "retracted", "providers", "authors", "notes", "match_score")} if source else {}

    def finish(status, explanation, evidence=None, conf=None, numeric=None, passages=None, method="rules", extra_flags=()):
        flags.extend(extra_flags)
        conf = conf or {"score": 0.9 if status in ("missing_citation", "bad_reference") else 0.3, "label": "Low", "components": {}}
        if conf["score"] >= 0.75:
            conf["label"] = "High"
        needs = status != "supported" or conf["score"] < 0.75 or bool(flags)
        return {**base, "source": src_view, "status": status, "explanation": explanation, "evidence": evidence,
                "numeric_check": numeric, "top_passages": passages or [], "flags": sorted(set(flags)),
                "confidence": conf, "needs_review": needs, "method": method}

    if claim["kind"] == "uncited":
        return finish("missing_citation", "This sentence reads like a factual/research claim but has no citation.",
                      conf={"score": 0.5, "label": "Medium", "components": {}}, extra_flags=["no_citation"])
    if ref is None:
        return finish("bad_reference", f"Citation {claim['unmatched_citations']} does not match any entry in the reference list.",
                      extra_flags=["citation_not_in_reference_list"])
    if not source or not source.get("found") or source.get("match_score", 0) < 0.55:
        return finish("bad_reference",
                      "The cited publication could not be located in Crossref, OpenAlex, Semantic Scholar or arXiv. "
                      "It may be mistyped or fabricated - check manually.", extra_flags=["reference_not_found"])

    passages = rank_passages(claim["clean_text"], build_passages(source), k=5)
    numeric = numeric_check(claim["clean_text"], passages)
    top_sim = passages[0]["raw_similarity"] if passages else 0.0
    if source.get("doi_valid") is False:
        flags.append("doi_invalid")
    if source.get("retracted"):
        flags.append("retracted_source")
    if source["access"] in ("abstract", "metadata"):
        flags.append("abstract_only" if source["access"] == "abstract" else "metadata_only")
    if numeric["missing"]:
        flags.append("numeric_mismatch")
    age = age_years(source)
    if age is not None and age >= config.OUTDATED_YEARS:
        flags.append("old_source")

    if source["access"] == "metadata" or not passages:
        return finish("cannot_verify", "Only metadata was available (no abstract or full text), so the claim cannot be checked.",
                      numeric=numeric, extra_flags=())

    used_llm = bool(use_llm and config.llm_available())
    try:
        j = llm_judge(claim["clean_text"], source, passages) if used_llm else heuristic_judge(claim["clean_text"], passages, numeric)
    except Exception as exc:
        used_llm = False
        j = heuristic_judge(claim["clean_text"], passages, numeric)
        flags.append("llm_error_fallback")
        j["explanation"] += f" (LLM call failed: {type(exc).__name__})"

    verdict = j.get("verdict", "unsupported")
    if verdict not in ("supported", "partly_supported", "unsupported", "contradictory"):
        verdict = "unsupported"
    quote = j.get("evidence_quote")
    quote_needed = verdict in ("supported", "partly_supported", "contradictory")
    ok, qp = verify_quote(quote, passages) if quote else (False, None)
    if used_llm and quote_needed and not ok:
        flags.append("quote_unverified")
    ev_passage = qp or next((p for p in passages if p["id"] == j.get("evidence_passage_id")), passages[0])
    evidence = {"quote": quote, "verified": bool(ok), "passage": ev_passage["text"], "section": ev_passage["section"],
                "page": ev_passage.get("page"), "source_url": source.get("url")}
    for s in j.get("scope_issues", []) or []:
        flags.append("scope: " + str(s)[:80])

    status, expl = verdict, j.get("explanation", "")
    if source.get("retracted"):
        status, expl = "unsupported", "The cited paper has been RETRACTED, so it cannot be relied on as evidence. " + expl
    elif verdict in ("supported", "partly_supported") and "old_source" in flags:
        status = "possibly_outdated"
        expl += f" The source is {age} years old; newer research may exist."

    conf = compute_confidence(top_sim, source["access"], numeric, float(j.get("certainty", 0.5)), ok, quote_needed,
                              source.get("match_score", 0), used_llm)
    return finish(status, expl, evidence, conf, numeric, passages, "llm" if used_llm else "rules")
