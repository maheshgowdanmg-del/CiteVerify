"""Document-level insights computed from a finished CiteVerify run (no network, no LLM).

Everything here reads the ``run`` / ``results`` structures produced by the pipeline and the UI:
  result : claim_id, claim, citation, final_status, confidence{score}, needs_review, evidence{verified, section},
           source{title, year}, flags, numeric_check{claim_numbers, missing}
  run    : summary{references_resolved, references_total}, references[{id, raw}], sources{id: {...}}
Status keys are matched by keyword so this works with the STATUS table in src/verdict.py.
"""
from __future__ import annotations

import re
import textwrap
from datetime import date
from difflib import SequenceMatcher

OFFICIAL_LABELS = ["Supported", "Partially Supported", "Unsupported", "Contradictory", "Possibly Outdated", "Needs Review"]
VERDICT_COLORS = {"supported": "#16a34a", "partial": "#f59e0b", "outdated": "#0ea5e9", "unsupported": "#dc2626",
                  "contradictory": "#7c3aed"}
GREY = "#6b7280"


def classify_status(key) -> str:
    """Map an internal status key/name to a coarse class (order matters: 'unsupported' contains 'supported')."""
    k = str(key or "").lower().replace("-", "_").replace(" ", "_")
    if "contradict" in k:
        return "contradictory"
    if "unsupport" in k or "not_support" in k:
        return "unsupported"
    if "partial" in k or "partly" in k:
        return "partial"
    if "support" in k:
        return "supported"
    if "outdated" in k:
        return "outdated"
    if "missing" in k or "uncited" in k or "no_cit" in k:
        return "missing"
    if "bad" in k or "invalid" in k:
        return "bad_reference"
    if "cannot" in k or "unverif" in k or "review" in k or "unknown" in k:
        return "unverifiable"
    return "other"


def official_label(key) -> str:
    """The verdict labels named in the problem statement (supported, partly supported, unsupported, contradictory,
    possibly outdated). Everything not decisive (cannot verify, missing/bad reference) is 'Needs Review'."""
    return {"supported": "Supported", "partial": "Partially Supported", "unsupported": "Unsupported",
            "contradictory": "Contradictory", "outdated": "Possibly Outdated"}.get(classify_status(key), "Needs Review")


def official_distribution(results) -> dict:
    out = {label: 0 for label in OFFICIAL_LABELS}
    for r in results:
        out[official_label(r.get("final_status"))] += 1
    return out


# --------------------------------------------------------------------------- trust score
CREDIT = {"supported": 1.0, "outdated": 0.8, "partial": 0.5, "unsupported": 0.0, "contradictory": 0.0}
TRUST_WEIGHTS = {"claim_support": 0.40, "reference_resolution": 0.20, "evidence_integrity": 0.15,
                 "coverage": 0.15, "penalties": 0.10}


def _grade(score):
    if score is None:
        return "Not enough data"
    return "Strong" if score >= 80 else "Moderate" if score >= 60 else "Weak" if score >= 40 else "Poor"


def trust_score(run: dict, results: list) -> dict:
    """Transparent 0-100 'CiteVerify Trust Score'. A CiteVerify assessment, not an official quality measure."""
    n = len(results)
    classes = [classify_status(r.get("final_status")) for r in results]
    decided = [c for c in classes if c in CREDIT]
    summary = run.get("summary") or {}
    sources = (run.get("sources") or {}).values()
    comps = []

    def add(name, value, detail):
        comps.append({"component": name, "weight": TRUST_WEIGHTS[name], "value": None if value is None else round(value, 3),
                      "detail": detail})

    add("claim_support", (sum(CREDIT[c] for c in decided) / len(decided)) if decided else None,
        f"Credit per decided claim (supported 1, outdated 0.8, partial 0.5, else 0) over {len(decided)} decided claims.")
    tot, res = summary.get("references_total") or 0, summary.get("references_resolved") or 0
    add("reference_resolution", (res / tot) if tot else None, f"{res} of {tot} references resolved to a real publication.")
    with_ev = [r for r in results if r.get("evidence")]
    ver = sum(1 for r in with_ev if (r["evidence"] or {}).get("verified"))
    add("evidence_integrity", (ver / len(with_ev)) if with_ev else None,
        f"{ver} of {len(with_ev)} evidence quotes were found verbatim in the retrieved source.")
    add("coverage", (len(decided) / n) if n else None, f"{len(decided)} of {n} claims reached a decisive verdict.")
    retracted = sum(1 for s in sources if s.get("retracted"))
    contr, missing, bad = classes.count("contradictory"), classes.count("missing"), classes.count("bad_reference")
    pen = (contr + retracted + 0.5 * missing + 0.5 * bad) / max(1, n)
    add("penalties", max(0.0, 1 - pen) if n else None,
        f"{contr} contradictory, {retracted} retracted source(s), {missing} missing citation(s), {bad} bad reference(s).")

    usable = [c for c in comps if c["value"] is not None]
    score = None
    if usable:
        tw = sum(c["weight"] for c in usable)
        score = round(100 * sum(c["value"] * c["weight"] for c in usable) / tw, 1)
    return {"score": score, "grade": _grade(score), "components": comps, "n_claims": n,
            "methodology": ("Weighted mean of the components above (weights 40/20/15/15/10). Components with no data "
                            "are skipped and the remaining weights renormalised."),
            "disclaimer": "CiteVerify assessment for decision support only - not an officially recognised academic quality measure."}


# --------------------------------------------------------------------------- reference health
def _ref_ids_from_citation(citation: str) -> set:
    ids = set()
    for grp in re.findall(r"\[([^\]]+)\]", citation or ""):
        for part in re.split(r"[,;]", grp):
            part = part.strip()
            m = re.fullmatch(r"(\d+)\s*[-\u2013]\s*(\d+)", part)
            if m:
                a, b = int(m.group(1)), int(m.group(2))
                if 0 < b - a <= 50:
                    ids.update(str(i) for i in range(a, b + 1))
            elif part.isdigit():
                ids.add(part)
    return ids


def _ref_ids_author_year(citation: str, refs: list) -> set:
    cit = (citation or "").strip("() ")
    year = re.search(r"\b(?:19|20)\d{2}\b", cit)
    name = re.search(r"[A-Z][A-Za-z'\-]+", cit)
    if not (year and name):
        return set()
    return {str(r["id"]) for r in refs if name.group(0) in r.get("raw", "") and year.group(0) in r.get("raw", "")}


def _exists(src: dict):
    found = src.get("found")
    if found is None or (isinstance(found, str) and found.strip().lower() == "not cited"):
        return None  # never looked up (reference not cited by any claim)
    if isinstance(found, str):
        return found.strip().lower() not in ("no", "false", "not found", "none", "")
    return bool(found)


def reference_health(run: dict, results: list, outdated_years: int = 10, today_year: int | None = None) -> dict:
    """Per-reference funnel: exists -> matched to a claim -> actually supports a claim (best-effort mapping)."""
    now = today_year or date.today().year
    refs = run.get("references") or []
    sources = run.get("sources") or {}
    claim_map: dict[str, list] = {}
    for r in results:
        cit = r.get("citation") or ""
        ids = _ref_ids_from_citation(cit) or _ref_ids_author_year(cit, refs)
        for i in ids:
            claim_map.setdefault(i, []).append(classify_status(r.get("final_status")))

    rows = []
    for ref in refs:
        rid = str(ref["id"])
        src = sources.get(rid, {})
        classes = claim_map.get(rid, [])
        supports = ("n/a" if not classes else "yes" if "supported" in classes else
                    "partial" if any(c in ("partial", "outdated") for c in classes) else "no")
        year = src.get("year")
        age = (now - int(year)) if str(year or "").isdigit() else None
        flags = []
        if src.get("retracted"):
            flags.append("retracted")
        if age is not None and age > outdated_years:
            flags.append(f"older ({age} yr)")
        if not classes:
            flags.append("unmatched (no claim cites it)")
        rows.append({"id": rid, "reference": ref.get("raw", "")[:110], "exists": _exists(src),
                     "matched_claims": len(classes), "supports": supports, "year": year, "age": age,
                     "retracted": bool(src.get("retracted")), "duplicate_of": None, "flags": flags})

    for i, a in enumerate(rows):  # duplicate references (near-identical text)
        for b in rows[:i]:
            if b["duplicate_of"] is None and SequenceMatcher(None, a["reference"].lower(), b["reference"].lower()).ratio() >= 0.92:
                a["duplicate_of"] = b["id"]
                a["flags"].append(f"duplicate of [{b['id']}]")
                break

    classes_all = [classify_status(r.get("final_status")) for r in results]
    funnel = {"references": len(rows), "exist": sum(1 for r in rows if r["exists"] is True),
              "matched_to_claim": sum(1 for r in rows if r["matched_claims"]),
              "support_a_claim": sum(1 for r in rows if r["supports"] in ("yes", "partial")),
              "not_found": sum(1 for r in rows if r["exists"] is False),
              "retracted": sum(1 for r in rows if r["retracted"]),
              "older": sum(1 for r in rows if r["age"] is not None and r["age"] > outdated_years),
              "duplicates": sum(1 for r in rows if r["duplicate_of"]),
              "unmatched": sum(1 for r in rows if not r["matched_claims"]),
              "claims_missing_citation": classes_all.count("missing")}
    return {"rows": rows, "funnel": funnel,
            "note": "Existing, matched and supporting are three different things: a real paper is never treated as proof."}


# --------------------------------------------------------------------------- review priority
BASE_RISK = {"contradictory": 1.0, "unsupported": 0.85, "missing": 0.8, "bad_reference": 0.75, "partial": 0.6,
             "unverifiable": 0.5, "other": 0.5, "outdated": 0.4, "supported": 0.1}


def review_priority(results: list, top: int = 10) -> list:
    """Rank claims by how urgently a human should look at them (highest risk first)."""
    out = []
    for r in results:
        cls = classify_status(r.get("final_status"))
        conf = float((r.get("confidence") or {}).get("score") or 0)
        risk = BASE_RISK.get(cls, 0.5) * (0.8 + 0.2 * (1 - min(1.0, conf)))
        reasons = [f"verdict: {official_label(r.get('final_status'))}", f"confidence {conf:.2f}"]
        nc = r.get("numeric_check") or {}
        if nc.get("missing"):
            risk += 0.1
            reasons.append("number(s) not found in source: " + ", ".join(map(str, nc["missing"])))
        if r.get("evidence") and not r["evidence"].get("verified"):
            risk += 0.1
            reasons.append("evidence quote not verified in source")
        out.append({"claim_id": r.get("claim_id"), "claim": (r.get("claim") or "")[:110], "status": official_label(r.get("final_status")),
                    "risk": round(min(1.0, risk), 2), "reasons": "; ".join(reasons),
                    "reviewed": r.get("review_decision", "pending") != "pending"})
    return sorted(out, key=lambda x: (-x["risk"], str(x["claim_id"])))[:top]


# --------------------------------------------------------------------------- claim graph (Graphviz DOT)
def _label(text, width=30, maxlen=90) -> str:
    t = " ".join(str(text or "").split())
    if len(t) > maxlen:
        t = t[: maxlen - 1] + "\u2026"
    return "\\n".join(l.replace("\\", "\\\\").replace('"', '\\"') for l in textwrap.wrap(t, width) or [""])


def claim_graph_dot(results: list, max_claims: int = 30) -> str:
    """claim -> (citation) source paper, with an evidence node; colour = verdict. Render with st.graphviz_chart."""
    lines = ["digraph CiteVerify {", '  rankdir=LR; bgcolor="transparent"; nodesep=0.25; ranksep=0.7;',
             '  node [fontname="Helvetica", fontsize=10, style="filled,rounded", shape=box, fontcolor="white", color="#00000000"];',
             '  edge [fontname="Helvetica", fontsize=9, color="#9ca3af", fontcolor="#9ca3af"];']
    src_ids: dict[str, str] = {}
    for i, r in enumerate(results[:max_claims]):
        cls = classify_status(r.get("final_status"))
        color = VERDICT_COLORS.get(cls, GREY)
        conf = float((r.get("confidence") or {}).get("score") or 0)
        lines.append(f'  c{i} [label="{_label(str(r.get("claim_id")) + ": " + (r.get("claim") or ""))}", fillcolor="{color}"];')
        src = r.get("source") or {}
        title = src.get("title")
        if title:
            key = title.lower()
            if key not in src_ids:
                src_ids[key] = f"s{len(src_ids)}"
                lines.append(f'  {src_ids[key]} [label="{_label(title + (" (" + str(src.get("year")) + ")" if src.get("year") else ""))}", '
                             f'fillcolor="#1f2937", shape=folder];')
            lines.append(f'  c{i} -> {src_ids[key]} [label="{_label(r.get("citation") or "", 20, 24)} \\n conf {conf:.2f}"];')
        else:
            lines.append(f'  c{i} -> none [style=dashed, label="no source"];')
        ev = r.get("evidence")
        if ev:
            ok = ev.get("verified")
            lines.append(f'  e{i} [label="{_label("Evidence (" + str(ev.get("section")) + ")" + (" quote verified" if ok else " quote NOT verified"), 26)}", '
                         f'fillcolor="{"#065f46" if ok else "#7f1d1d"}", shape=note];')
            lines.append(f"  c{i} -> e{i} [style=dotted];")
    lines.append(f'  none [label="No retrievable source", fillcolor="{GREY}", shape=box];')
    lines.append("}")
    return "\n".join(lines)
