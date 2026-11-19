"""Exports: JSON, CSV, HTML and PDF verification reports (with human-review history).

Each finding shows what the official problem statement asks for: the claim, the matched citation with its publication
details, the evidence passage (section/page), the verdict with a short reason, a confidence indicator, a source link
and whether human review is needed.
"""
import csv
import html
import io
import json

from . import insights
from .verdict import STATUS

DISCLAIMER = ("Automated findings are decision support, not final academic judgments. A citation is not proof by itself. "
              "'Unsupported' means the retrieved text did not contain support - it does not prove the claim is false. "
              "Every item remains open to human review.")


def apply_reviews(results, reviews):
    """Attach the latest human decision to each result (history stays untouched)."""
    latest = {}
    for rv in reviews:
        latest[rv["result_id"]] = rv
    out = []
    for r in results:
        rv = latest.get(r["result_id"])
        final = r["status"]
        decision = "pending"
        if rv:
            decision = rv["action"]
            if rv["action"] == "override" and rv["new_status"]:
                final = rv["new_status"]
        out.append({**r, "final_status": final, "review_decision": decision})
    return out


def label(status):
    return STATUS.get(status, (status, ""))[0]


def _authors(src, limit=4):
    names = [a for a in (src.get("authors") or []) if a]
    return ", ".join(names[:limit]) + (" et al." if len(names) > limit else "")


def _doi_url(src):
    return f"https://doi.org/{src['doi']}" if src.get("doi") else ""


def to_json(run, reviews):
    return json.dumps({**run, "results": apply_reviews(run["results"], reviews), "review_history": reviews}, indent=2, default=str)


def to_csv(run, reviews):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["result_id", "claim", "citation", "status", "final_status", "review_decision", "confidence", "confidence_label",
                "flags", "explanation", "evidence_quote", "quote_verified", "section", "source_title", "source_authors",
                "source_year", "source_doi", "source_url", "source_access"])
    for r in apply_reviews(run["results"], reviews):
        ev, src = r.get("evidence") or {}, r.get("source") or {}
        w.writerow([r["result_id"], r["claim"], r["citation"], r["status"], r["final_status"], r["review_decision"],
                    r["confidence"]["score"], r["confidence"]["label"], "; ".join(r["flags"]), r["explanation"],
                    ev.get("quote") or "", ev.get("verified", ""), ev.get("section", ""), src.get("title", ""), _authors(src),
                    src.get("year", ""), src.get("doi", "") or "", src.get("url", "") or "", src.get("access", "")])
    return buf.getvalue()


def _summary_line(run, final_results):
    s = run["summary"]
    dist = insights.official_distribution(final_results)
    counts = " | ".join(f"{k}: {v}" for k, v in dist.items())
    return (f"Findings: {s['total_findings']} | Needs review: {s['needs_review']} | Avg confidence: {s['avg_confidence']} | "
            f"References resolved: {s['references_resolved']}/{s['references_total']}", counts)


def to_html(run, reviews):
    e = html.escape
    final = apply_reviews(run["results"], reviews)
    rows = []
    for r in final:
        ev, src = r.get("evidence") or {}, r.get("source") or {}
        color = STATUS.get(r["final_status"], ("", "#465C59"))[1]
        pub = ""
        if src.get("title"):
            doi = _doi_url(src)
            pub = (f"<p><b>Cited publication:</b> <a href='{e(src.get('url') or doi or '#')}'>{e(src['title'])}</a>"
                   f"{' - ' + e(_authors(src)) if _authors(src) else ''} ({e(str(src.get('year') or 'n.d.'))})"
                   f"{' - DOI <a href=' + chr(39) + e(doi) + chr(39) + '>' + e(src['doi']) + '</a>' if doi else ''}"
                   f" - access: {e(str(src.get('access')))}</p>")
        rows.append(
            f"<div class='card'><span class='badge' style='background:{color}'>{e(label(r['final_status']))}</span> "
            f"<b>Confidence {r['confidence']['score']} ({r['confidence']['label']})</b> "
            f"{'&bull; NEEDS HUMAN REVIEW' if r['needs_review'] else ''}"
            f"<p><b>Claim:</b> {e(r['claim'])}</p><p><b>Citation:</b> {e(r['citation'] or '-')}</p>{pub}"
            f"<p><b>Verdict reason:</b> {e(r['explanation'])}</p>"
            + (f"<p><b>Evidence ({e(str(ev.get('section', '')))}, quote verified in source={ev.get('verified')}):</b> "
               f"<i>{e(ev.get('quote') or ev.get('passage', '')[:300])}</i></p>" if ev else "")
            + (f"<p><b>Flags:</b> {e(', '.join(r['flags']))}</p>" if r["flags"] else "")
            + f"<p><b>Review decision:</b> {e(r['review_decision'])}</p></div>"
        )
    line, counts = _summary_line(run, final)
    return (
        "<html><head><meta charset='utf-8'><title>CiteVerify report</title><style>body{font-family:Arial,sans-serif;max-width:900px;"
        "margin:auto;padding:20px;background:#F4F8F7;color:#1F2D2B}h1{color:#465C59}.card{background:#fff;border:1px solid #DCE7E5;"
        "border-radius:14px;padding:14px;margin:12px 0}.badge{color:#fff;padding:2px 10px;border-radius:10px}"
        ".note{background:#FBF4DC;border-left:5px solid #CFA123;padding:10px 14px;border-radius:10px}</style></head><body>"
        f"<h1>CiteVerify verification report</h1><p>File: {e(run['filename'])} &bull; Run: {run['run_id']} &bull; {e(run['created'])}</p>"
        f"<p>{e(line)}</p><p>Verdicts: {e(counts)}</p><p class='note'>{e(DISCLAIMER)}</p>" + "".join(rows) + "</body></html>"
    )


def to_pdf(run, reviews):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    e = html.escape
    st = getSampleStyleSheet()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title="CiteVerify report")
    final = apply_reviews(run["results"], reviews)
    line, counts = _summary_line(run, final)
    flow = [Paragraph("CiteVerify Verification Report", st["Title"]),
            Paragraph(f"File: {e(run['filename'])} | Run: {run['run_id']} | {e(run['created'])}", st["Normal"]),
            Paragraph(e(line), st["Normal"]), Paragraph(f"Verdicts - {e(counts)}", st["Normal"]),
            Paragraph(f"<i>{e(DISCLAIMER)}</i>", st["Normal"]), Spacer(1, 12)]
    for r in final:
        ev, src = r.get("evidence") or {}, r.get("source") or {}
        flow.append(Paragraph(f"<b>[{e(label(r['final_status']))}]</b> confidence {r['confidence']['score']} ({r['confidence']['label']})"
                              f"{' - NEEDS REVIEW' if r['needs_review'] else ''}", st["Heading4"]))
        flow.append(Paragraph(f"<b>Claim:</b> {e(r['claim'])}", st["Normal"]))
        flow.append(Paragraph(f"<b>Citation:</b> {e((r['citation'] or '-')[:300])}", st["Normal"]))
        if src.get("title"):
            flow.append(Paragraph(f"<b>Cited publication:</b> {e(src['title'])} ({e(str(src.get('year') or 'n.d.'))})"
                                  f"{' - ' + e(_authors(src)) if _authors(src) else ''}"
                                  f"{' - DOI ' + e(src['doi']) if src.get('doi') else ''} - access: {e(str(src.get('access')))}", st["Normal"]))
        flow.append(Paragraph(f"<b>Reason:</b> {e(r['explanation'])}", st["Normal"]))
        if ev:
            flow.append(Paragraph(f"<b>Evidence ({e(str(ev.get('section', '')))}, quote verified={ev.get('verified')}):</b> "
                                  f"<i>{e((ev.get('quote') or ev.get('passage', ''))[:400])}</i>", st["Normal"]))
        if r["flags"]:
            flow.append(Paragraph(f"<b>Flags:</b> {e(', '.join(r['flags']))}", st["Normal"]))
        if src.get("url"):
            flow.append(Paragraph(f"<b>Source link:</b> {e(src['url'])}", st["Normal"]))
        flow.append(Spacer(1, 10))
    doc.build(flow)
    return buf.getvalue()
