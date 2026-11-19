"""Glue: upload -> extract -> claims -> retrieve -> compare -> report."""
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from . import storage
from .claims import extract_claims, parse_references
from .extract import split_references
from .retrieval import resolve_reference
from .verdict import SEVERITY, verify_claim


def summarize(results, refs, sources):
    status = Counter(r["status"] for r in results)
    confs = [r["confidence"]["score"] for r in results if r["confidence"].get("components")]
    access = Counter(s["access"] for s in sources.values())
    return {
        "total_findings": len(results),
        "by_status": dict(status),
        "needs_review": sum(r["needs_review"] for r in results),
        "avg_confidence": round(sum(confs) / len(confs), 2) if confs else None,
        "references_total": len(refs),
        "references_resolved": sum(1 for s in sources.values() if s["found"] and s["match_score"] >= 0.55),
        "source_access": dict(access),
    }


def run_pipeline(text, filename="document", use_llm=True, max_claims=40, progress=None):
    def tick(frac, msg):
        if progress:
            progress(frac, msg)

    tick(0.05, "Splitting body and reference list")
    body, ref_text = split_references(text)
    refs = parse_references(ref_text)
    tick(0.15, f"Parsed {len(refs)} references; extracting claims")
    claims = extract_claims(body, refs, max_claims)
    refs_by_id = {r["id"]: r for r in refs}

    used_ids = sorted({i for c in claims for i in c["ref_ids"]})
    tick(0.25, f"Retrieving {len(used_ids)} cited papers (Crossref, OpenAlex, Semantic Scholar, arXiv, Unpaywall)")
    sources = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for rid, src in zip(used_ids, pool.map(lambda i: resolve_reference(refs_by_id[i]), used_ids)):
            sources[rid] = src

    results = []
    for n, c in enumerate(claims, 1):
        tick(0.5 + 0.45 * n / max(1, len(claims)), f"Verifying claim {n}/{len(claims)}")
        if c["kind"] == "uncited":
            r = verify_claim(c, None, None, use_llm)
            r["result_id"] = f"{c['id']}-none"
            results.append(r)
            continue
        targets = [refs_by_id[i] for i in c["ref_ids"]] or [None]
        for ref in targets:
            r = verify_claim(c, ref, sources.get(ref["id"]) if ref else None, use_llm)
            r["result_id"] = f"{c['id']}-{ref['id'] if ref else 'x'}"
            results.append(r)
    results.sort(key=lambda r: (SEVERITY.get(r["status"], 9), r["claim_id"]))

    slim_sources = {str(k): {kk: vv for kk, vv in v.items() if kk != "pages"} for k, v in sources.items()}
    run = {
        "run_id": uuid.uuid4().hex[:10], "filename": filename, "created": storage.now(),
        "used_llm": bool(use_llm), "claims": claims, "references": refs, "sources": slim_sources,
        "results": results, "summary": summarize(results, refs, sources),
    }
    storage.save_run(run)
    tick(1.0, "Done")
    return run
