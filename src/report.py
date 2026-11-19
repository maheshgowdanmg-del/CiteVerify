"""Exports: JSON, CSV, HTML and PDF verification reports (with human-review history)."""
import csv
import html
import io
import json

from .verdict import STATUS


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


def to_json(run, reviews):
    return json.dumps({**run, "results": apply_reviews(run["results"], reviews), "review_history": reviews}, indent=2, default=str)


def to_csv(run, reviews):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["result_id", "claim", "citation", "status", "final_status", "review_decision", "confidence", "confidence_label",
                "flags", "explanation", "evidence_quote", "quote_verified", "section", "source_url"])
    for r in apply_reviews(run["results"], reviews):
        ev = r.get("evidence") or {}
        w.writerow([r["result_id"], r["claim"], r["citation"], r["status"], r["final_status"], r["review_decision"],
                    r["confidence"]["score"], r["confidence"]["label"], "; ".join(r["flags"]), r["explanation"],
                    ev.get("quote") or "", ev.get("verified", ""), ev.get("section", ""), (r["source"] or {}).get("url", "")])
    return buf.getvalue()


def to_html(run, reviews):
    e = html.escape
    rows = []
    for r in apply_reviews(run["results"], reviews):
        ev = r.get("evidence") or {}
        color = STATUS.get(r["final_status"], ("", "#333"))[1]
        rows.append(
            f"<div class='card'><span class='badge' style='background:{color}'>{e(label(r['final_status']))}</span> "
            f"<b>Confidence {r['confidence']['score']} ({r['confidence']['label']})</b> "
            f"{'&bull; NEEDS HUMAN REVIEW' if r['needs_review'] else ''}"
            f"<p><b>Claim:</b> {e(r['claim'])}</p><p><b>Citation:</b> {e(r['citation'])}</p>"
            f"<p><b>Verdict reason:</b> {e(r['explanation'])}</p>"
            + (f"<p><b>Evidence ({e(str(ev.get('section','')))}, verified={ev.get('verified')}):</b> "
               f"<i>{e(ev.get('quote') or ev.get('passage','')[:300])}</i></p>" if ev else "")
            + (f"<p><b>Flags:</b> {e(', '.join(r['flags']))}</p>" if r["flags"] else "")
            + (f"<p><b>Source:</b> <a href='{e(r['source'].get('url') or '#')}'>{e(r['source'].get('title') or 'n/a')}</a> "
               f"({e(str(r['source'].get('year')))}) - access: {e(str(r['source'].get('access')))}</p>" if r["source"] else "")
            + f"<p><b>Review decision:</b> {e(r['review_decision'])}</p></div>"
        )
    s = run["summary"]
    return (
        "<html><head><meta charset='utf-8'><title>CiteVerify report</title><style>body{font-family:Arial;max-width:900px;margin:auto;padding:20px}"
        ".card{border:1px solid #ddd;border-radius:8px;padding:12px;margin:12px 0}.badge{color:#fff;padding:2px 8px;border-radius:10px}</style></head><body>"
        f"<h1>CiteVerify verification report</h1><p>File: {e(run['filename'])} &bull; Run: {run['run_id']} &bull; {e(run['created'])}</p>"
        f"<p>Findings: {s['total_findings']} &bull; Needs review: {s['needs_review']} &bull; Avg confidence: {s['avg_confidence']} &bull; "
        f"References resolved: {s['references_resolved']}/{s['references_total']}</p><p>Status counts: {e(json.dumps(s['by_status']))}</p>"
        "<p><i>Automated findings are decision support, not final academic judgments. Every item remains open to human review.</i></p>"
        + "".join(rows) + "</body></html>"
    )


def to_pdf(run, reviews):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    e = html.escape
    st = getSampleStyleSheet()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title="CiteVerify report")
    s = run["summary"]
    flow = [Paragraph("CiteVerify Verification Report", st["Title"]),
            Paragraph(f"File: {e(run['filename'])} | Run: {run['run_id']} | {e(run['created'])}", st["Normal"]),
            Paragraph(f"Findings: {s['total_findings']} | Needs review: {s['needs_review']} | Avg confidence: {s['avg_confidence']} | "
                      f"References resolved: {s['references_resolved']}/{s['references_total']}", st["Normal"]),
            Paragraph("<i>Automated findings are decision support, not final academic judgments.</i>", st["Normal"]), Spacer(1, 12)]
    for r in apply_reviews(run["results"], reviews):
        ev = r.get("evidence") or {}
        flow.append(Paragraph(f"<b>[{e(label(r['final_status']))}]</b> confidence {r['confidence']['score']} ({r['confidence']['label']})"
                              f"{' - NEEDS REVIEW' if r['needs_review'] else ''}", st["Heading4"]))
        flow.append(Paragraph(f"<b>Claim:</b> {e(r['claim'])}", st["Normal"]))
        flow.append(Paragraph(f"<b>Citation:</b> {e(r['citation'][:300])}", st["Normal"]))
        flow.append(Paragraph(f"<b>Reason:</b> {e(r['explanation'])}", st["Normal"]))
        if ev:
            flow.append(Paragraph(f"<b>Evidence ({e(str(ev.get('section','')))}):</b> <i>{e((ev.get('quote') or ev.get('passage',''))[:400])}</i>", st["Normal"]))
        if r["flags"]:
            flow.append(Paragraph(f"<b>Flags:</b> {e(', '.join(r['flags']))}", st["Normal"]))
        if r["source"] and r["source"].get("url"):
            flow.append(Paragraph(f"<b>Source:</b> {e(r['source']['url'])}", st["Normal"]))
        flow.append(Spacer(1, 10))
    doc.build(flow)
    return buf.getvalue()
