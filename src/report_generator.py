"""Verification Report Generator for CiteVerify.
Generates comprehensive downloadable PDF (ReportLab), JSON, and CSV reports.
Includes claim verification outcomes, evidence quotes, citation health,
trust score breakdown, and human review decisions.
"""
from __future__ import annotations

import io
import csv
import json
import datetime
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, HRFlowable
)

from . import config


def generate_json_report(doc_data: Dict[str, Any]) -> str:
    """Export complete document analysis, citations, claims, results, and reviews as JSON."""
    return json.dumps(doc_data, indent=2, default=str)


def generate_csv_report(doc_data: Dict[str, Any]) -> str:
    """Export claims and verification results as CSV for spreadsheet analysis."""
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Claim_ID",
        "Topic",
        "Claim_Text",
        "Citation_Marker",
        "AI_Verdict",
        "Final_Verdict",
        "Review_Action",
        "Confidence_Score",
        "Confidence_Label",
        "Explanation",
        "Evidence_Quote",
        "Numeric_Verdict",
        "Source_Title",
        "Source_Authors",
        "Source_Year",
        "Source_DOI",
        "Source_URL",
        "Review_Comments"
    ])

    results = doc_data.get("results") or []
    claims_dict = {c["claim_id"]: c for c in doc_data.get("claims") or []}

    for r in results:
        cid = r.get("claim_id", "")
        c_info = claims_dict.get(cid, {})
        ev_quote = r.get("evidence_quote") or ""
        src_url = r.get("source_url") or ""

        writer.writerow([
            cid,
            c_info.get("topic", "General Science"),
            c_info.get("claim_text") or c_info.get("claim", ""),
            c_info.get("citation_marker") or c_info.get("citation", ""),
            r.get("verdict", ""),
            r.get("final_verdict") or r.get("verdict", ""),
            r.get("review_action", "pending"),
            r.get("confidence_score", 0.0),
            r.get("confidence_label", ""),
            r.get("explanation", ""),
            ev_quote,
            r.get("numeric_verdict", ""),
            r.get("source_title", ""),
            r.get("source_authors", ""),
            r.get("source_year", ""),
            r.get("source_doi", ""),
            src_url,
            r.get("review_comment", "")
        ])

    return output.getvalue()


def generate_pdf_report(doc_data: Dict[str, Any]) -> bytes:
    """Generate professional executive PDF report using ReportLab."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40
    )

    styles = getSampleStyleSheet()

    # Custom typography styles
    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=26,
        textColor=colors.HexColor("#0F172A")
    )
    subtitle_style = ParagraphStyle(
        "DocSubTitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#64748B")
    )
    h2_style = ParagraphStyle(
        "Heading2Custom",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=17,
        textColor=colors.HexColor("#1E293B"),
        spaceBefore=14,
        spaceAfter=6
    )
    body_style = ParagraphStyle(
        "BodyCustom",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#334155")
    )
    evidence_style = ParagraphStyle(
        "EvidenceQuote",
        parent=styles["Normal"],
        fontName="Helvetica-Oblique",
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#0F766E"),
        backColor=colors.HexColor("#F0FDFA"),
        borderColor=colors.HexColor("#14B8A6"),
        borderWidth=1,
        borderPadding=6,
        spaceBefore=4,
        spaceAfter=4
    )
    table_cell_style = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#1E293B")
    )
    badge_style = ParagraphStyle(
        "BadgeText",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#2563EB")
    )

    story = []

    document = doc_data.get("document") or {}
    results = doc_data.get("results") or []
    citations = doc_data.get("citations") or []
    claims = doc_data.get("claims") or []
    claims_dict = {c["claim_id"]: c for c in claims}

    # Header / Title banner
    story.append(Paragraph("CITEVERIFY AI", ParagraphStyle(
        "BrandHeader", fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=colors.HexColor("#2563EB")
    )))
    story.append(Paragraph("Scientific Claim & Citation Verification Report", title_style))
    story.append(Spacer(1, 4))
    
    timestamp = datetime.datetime.now().strftime("%B %d, %Y - %H:%M UTC")
    filename = document.get("filename", "Uploaded Document")
    story.append(Paragraph(f"Document: <b>{filename}</b> &nbsp;|&nbsp; Generated: {timestamp}", subtitle_style))
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#CBD5E1"), spaceAfter=14))

    # Executive Summary Card
    t_score = document.get("trust_score", 0.0) or 0.0
    t_grade = document.get("trust_grade", "Evaluated") or "Evaluated"

    score_color = colors.HexColor("#10B981") if t_score >= 80 else (colors.HexColor("#F59E0B") if t_score >= 60 else colors.HexColor("#EF4444"))

    summary_data = [
        [
            Paragraph(f"<b>Academic Trust Score</b><br/><font size='18' color='{score_color.hexval()}'><b>{t_score}/100</b></font><br/><font size='8' color='#64748B'>{t_grade}</font>", body_style),
            Paragraph(f"<b>Claims Audited:</b> {len(claims)}<br/><b>References Resolved:</b> {len(citations)}<br/><b>Pages Analyzed:</b> {document.get('page_count', 1)}", body_style),
            Paragraph(f"<b>Supported:</b> {sum(1 for r in results if r.get('verdict')=='SUPPORTED')}<br/><b>Partially Supported:</b> {sum(1 for r in results if r.get('verdict')=='PARTIALLY_SUPPORTED')}<br/><b>Refuted / Disputed:</b> {sum(1 for r in results if r.get('verdict') in ('REFUTED','CONTRADICTORY'))}", body_style)
        ]
    ]
    summary_table = Table(summary_data, colWidths=[2.2*inch, 2.5*inch, 2.5*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F8FAFC")),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor("#E2E8F0")),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING', (0,0), (-1,-1), 10),
        ('RIGHTPADDING', (0,0), (-1,-1), 10),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 14))

    # Claim-by-Claim Findings
    story.append(Paragraph("Detailed Claim-by-Claim Audit", h2_style))
    story.append(Paragraph("Every scientific statement extracted from the document was matched against original retrieved peer-reviewed source literature.", body_style))
    story.append(Spacer(1, 8))

    for idx, r in enumerate(results, 1):
        cid = r.get("claim_id", f"C{idx}")
        c_info = claims_dict.get(cid, {})
        claim_text = c_info.get("claim_text") or c_info.get("claim", "")
        citation_marker = c_info.get("citation_marker") or c_info.get("citation", "")
        verdict = r.get("final_verdict") or r.get("verdict", "NOT_ENOUGH_EVIDENCE")
        explanation = r.get("explanation", "")
        ev_quote = r.get("evidence_quote", "")
        src_title = r.get("source_title", "Cited Source")
        src_doi = r.get("source_doi", "")
        src_year = r.get("source_year", "")
        src_authors = r.get("source_authors", "")
        conf_score = int(r.get("confidence_score", 0.5) * 100)
        review_action = r.get("review_action", "pending")

        v_meta = config.VERDICTS.get(verdict, config.VERDICTS["NOT_ENOUGH_EVIDENCE"])
        v_color = colors.HexColor(v_meta["color"])

        claim_card_data = [
            [
                Paragraph(f"<b>{cid}</b> &nbsp;|&nbsp; Citation: <b>{citation_marker}</b>", body_style),
                Paragraph(f"<font color='{v_color.hexval()}'><b>{v_meta['icon']} {v_meta['label']}</b></font> (Confidence: {conf_score}%)", ParagraphStyle("R", parent=body_style, alignment=2))
            ],
            [
                Paragraph(f"<b>Claim:</b> \"{claim_text}\"", body_style),
                Paragraph(f"<b>Human Review:</b> {review_action.upper()}", ParagraphStyle("HR", parent=body_style, alignment=2))
            ],
            [
                Paragraph(f"<b>Cited Source:</b> {src_title} ({src_year}) &nbsp; <b>DOI:</b> {src_doi or 'n/a'}<br/><b>Authors:</b> {src_authors or 'n/a'}", body_style),
                Paragraph("", body_style)
            ],
            [
                Paragraph(f"<b>Verification Analysis:</b> {explanation}", body_style),
                Paragraph("", body_style)
            ]
        ]

        if ev_quote:
            claim_card_data.append([
                Paragraph(f"<b>Retrieved Evidence Passage:</b><br/>{ev_quote}", evidence_style),
                Paragraph("", body_style)
            ])

        card_table = Table(claim_card_data, colWidths=[5.4*inch, 1.8*inch])
        card_table.setStyle(TableStyle([
            ('SPAN', (0, 2), (1, 2)),
            ('SPAN', (0, 3), (1, 3)),
            ('SPAN', (0, 4), (1, 4)) if ev_quote else ('BACKGROUND', (0,0), (-1,-1), colors.white),
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#FFFFFF")),
            ('BOX', (0,0), (-1,-1), 1, colors.HexColor("#CBD5E1")),
            ('LINEBELOW', (0,0), (-1,0), 0.5, colors.HexColor("#E2E8F0")),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('LEFTPADDING', (0,0), (-1,-1), 8),
            ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ]))

        story.append(KeepTogether([card_table, Spacer(1, 10)]))

    # Academic Disclaimer Footer
    story.append(Spacer(1, 14))
    story.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#E2E8F0"), spaceAfter=8))
    story.append(Paragraph(
        "<b>Notice:</b> Automated findings are intended for research integrity decision support, not final academic judgments. "
        "A citation is not proof by itself. 'Not Enough Evidence' indicates that open abstracts lacked sufficient methodology, "
        "not that the claim is inherently false. All results should be audited with the full source publication.",
        ParagraphStyle("Notice", parent=styles["Normal"], fontName="Helvetica", fontSize=7.5, leading=10, textColor=colors.HexColor("#94A3B8"))
    ))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


def generate_html_report(doc_data: Dict[str, Any]) -> str:
    """Generate a standalone, styled HTML verification report."""
    doc_meta = doc_data.get("document") or {}
    t_score = doc_data.get("trust_score") or {}
    score_val = t_score.get("score", doc_meta.get("trust_score", 0.0))
    grade_val = t_score.get("grade", doc_meta.get("trust_grade", "Evaluated"))
    fname = doc_meta.get("filename", "Unknown Document")
    created = doc_meta.get("created_at", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))

    claims = doc_data.get("claims") or []
    results = doc_data.get("results") or []
    citations = doc_data.get("citations") or []
    claims_dict = {c["claim_id"]: c for c in claims}

    # Count verdicts
    v_counts = {"SUPPORTED": 0, "PARTIALLY_SUPPORTED": 0, "UNSUPPORTED": 0, "CONTRADICTORY": 0, "NEEDS_REVIEW": 0}
    for r in results:
        v = config.normalize_verdict(r.get("verdict", "NEEDS_REVIEW"))
        v_counts[v] = v_counts.get(v, 0) + 1

    claim_rows_html = ""
    for r in results:
        cid = r.get("claim_id", "")
        cl_obj = claims_dict.get(cid, {})
        claim_text = cl_obj.get("claim") or cl_obj.get("claim_text", "")
        topic = cl_obj.get("topic", "General Science")
        c_marker = cl_obj.get("citation") or cl_obj.get("citation_marker") or r.get("citation_marker", "")
        norm_v = config.normalize_verdict(r.get("verdict", "NEEDS_REVIEW"))
        v_meta = config.VERDICTS.get(norm_v, config.VERDICTS["NEEDS_REVIEW"])
        expl = r.get("explanation", "")
        ev_quote = r.get("evidence_quote") or (r.get("evidence") or {}).get("quote", "")
        src_title = r.get("source_title", "")
        src_doi = r.get("source_doi", "")
        conf = int(float(r.get("confidence_score", 0.5)) * 100)
        review_action = r.get("review_action", "Pending")
        reviewer_comment = r.get("review_comments", "")

        claim_rows_html += f"""
        <div class="claim-card">
            <div class="claim-header">
                <div>
                    <span class="claim-id">{cid}</span>
                    <span class="claim-topic">{topic}</span>
                    <span class="claim-cite">Citation: {c_marker}</span>
                </div>
                <div class="verdict-badge" style="background:{v_meta['bg']}; color:{v_meta['color']}; border-color:{v_meta['color']};">
                    {v_meta['icon']} {v_meta['label']} ({conf}% Confidence)
                </div>
            </div>
            <div class="claim-body">
                <p><strong>Claim:</strong> &ldquo;{claim_text}&rdquo;</p>
                <p><strong>Cited Source:</strong> {src_title} {f'(DOI: {src_doi})' if src_doi else ''}</p>
                <p><strong>Verification Analysis:</strong> {expl}</p>
                {f'<div class="evidence-quote"><strong>Retrieved Evidence Quote:</strong><br/>&ldquo;{ev_quote}&rdquo;</div>' if ev_quote else ''}
                {f'<div class="review-box"><strong>Human Review:</strong> {review_action.upper()} - {reviewer_comment}</div>' if reviewer_comment else ''}
            </div>
        </div>
        """

    cit_rows_html = ""
    for c in citations[:20]:
        c_stat = c.get("verified_status") or c.get("status", "UNVERIFIED")
        c_meta = config.CITATION_STATUSES.get(c_stat, config.CITATION_STATUSES["UNVERIFIED"])
        cit_rows_html += f"""
        <tr>
            <td><strong>{c.get('ref_id', '')}</strong></td>
            <td>{c.get('raw_text', '')[:120]}...</td>
            <td><code>{c.get('doi', 'None')}</code></td>
            <td><span style="color:{c_meta['color']}; font-weight:700;">{c_meta['icon']} {c_meta['label']}</span></td>
        </tr>
        """

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>CiteVerify Verification Report - {fname}</title>
<style>
    body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        background: #F7F9FC;
        color: #0B1220;
        margin: 0;
        padding: 40px 20px;
    }}
    .container {{
        max-width: 900px;
        margin: 0 auto;
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 14px;
        padding: 40px;
        box-shadow: 0 4px 20px rgba(11, 18, 32, 0.05);
    }}
    .header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 2px solid #E2E8F0;
        padding-bottom: 24px;
        margin-bottom: 30px;
    }}
    .brand {{
        font-size: 1.4rem;
        font-weight: 800;
        color: #0B1220;
    }}
    .score-box {{
        text-align: right;
    }}
    .score-val {{
        font-size: 2.2rem;
        font-weight: 800;
        color: #14B8A6;
    }}
    .kpi-row {{
        display: grid;
        grid-template-columns: repeat(5, 1fr);
        gap: 12px;
        margin-bottom: 30px;
    }}
    .kpi-tile {{
        background: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        padding: 14px;
        text-align: center;
    }}
    .kpi-num {{
        font-size: 1.5rem;
        font-weight: 800;
        color: #0B1220;
    }}
    .kpi-label {{
        font-size: 0.75rem;
        color: #64748B;
        font-weight: 600;
        text-transform: uppercase;
    }}
    .claim-card {{
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        padding: 18px 20px;
        margin-bottom: 16px;
        background: #FFFFFF;
    }}
    .claim-header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 10px;
    }}
    .claim-id {{
        font-weight: 800;
        color: #0B1220;
        margin-right: 8px;
    }}
    .claim-topic {{
        background: #EFF6FF;
        color: #1D4ED8;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 0.75rem;
        font-weight: 600;
        margin-right: 8px;
    }}
    .claim-cite {{
        color: #64748B;
        font-size: 0.8rem;
    }}
    .verdict-badge {{
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.8rem;
        font-weight: 700;
        border: 1px solid;
    }}
    .evidence-quote {{
        background: #F8FAFC;
        border-left: 3px solid #14B8A6;
        padding: 10px 14px;
        font-style: italic;
        margin-top: 10px;
        border-radius: 0 8px 8px 0;
        color: #334155;
        font-size: 0.9rem;
    }}
    .review-box {{
        background: #FFFBEB;
        border: 1px solid #FDE68A;
        padding: 8px 12px;
        border-radius: 6px;
        margin-top: 10px;
        font-size: 0.85rem;
        color: #92400E;
    }}
    table {{
        width: 100%;
        border-collapse: collapse;
        margin-top: 16px;
        font-size: 0.85rem;
    }}
    th, td {{
        padding: 10px;
        border-bottom: 1px solid #E2E8F0;
        text-align: left;
    }}
    th {{
        background: #F8FAFC;
        color: #475569;
        font-weight: 600;
    }}
    .footer {{
        border-top: 1px solid #E2E8F0;
        margin-top: 40px;
        padding-top: 20px;
        font-size: 0.75rem;
        color: #94A3B8;
        line-height: 1.5;
    }}
    @media print {{
        body {{ background: #FFFFFF; padding: 0; }}
        .container {{ border: none; box-shadow: none; padding: 0; }}
    }}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <div>
            <div class="brand">CiteVerify AI</div>
            <div style="font-size:1.1rem; font-weight:700; color:#1E293B; margin-top:4px;">{fname}</div>
            <div style="font-size:0.8rem; color:#64748B; margin-top:2px;">Analyzed: {created} &bull; Citations: {len(citations)} &bull; Claims: {len(claims)}</div>
        </div>
        <div class="score-box">
            <div class="score-val">{score_val}/100</div>
            <div style="font-size:0.85rem; font-weight:700; color:#0F766E;">{grade_val}</div>
        </div>
    </div>

    <div class="kpi-row">
        <div class="kpi-tile"><div class="kpi-num" style="color:#14B8A6;">{v_counts['SUPPORTED']}</div><div class="kpi-label">Supported</div></div>
        <div class="kpi-tile"><div class="kpi-num" style="color:#D6B56D;">{v_counts['PARTIALLY_SUPPORTED']}</div><div class="kpi-label">Partial</div></div>
        <div class="kpi-tile"><div class="kpi-num" style="color:#E11D48;">{v_counts['UNSUPPORTED']}</div><div class="kpi-label">Unsupported</div></div>
        <div class="kpi-tile"><div class="kpi-num" style="color:#8B5CF6;">{v_counts['CONTRADICTORY']}</div><div class="kpi-label">Contradictory</div></div>
        <div class="kpi-tile"><div class="kpi-num" style="color:#64748B;">{v_counts['NEEDS_REVIEW']}</div><div class="kpi-label">Needs Review</div></div>
    </div>

    <h2 style="font-size:1.15rem; color:#0B1220; margin-bottom:14px;">Scientific Claims & Evidence Verification</h2>
    {claim_rows_html}

    <h2 style="font-size:1.15rem; color:#0B1220; margin-top:36px; margin-bottom:14px;">Citation Registry & Fraud Audit</h2>
    <table>
        <thead>
            <tr>
                <th>Marker</th>
                <th>Bibliographic Reference</th>
                <th>DOI</th>
                <th>Registry Status</th>
            </tr>
        </thead>
        <tbody>
            {cit_rows_html}
        </tbody>
    </table>

    <div class="footer">
        <strong>Academic Integrity Notice:</strong> CiteVerify AI operates as academic research intelligence and decision support. 
        Automated verdicts evaluate statements against accessible open abstracts and scholarly metadata from Crossref, OpenAlex, Semantic Scholar, and PubMed.
        All findings must be confirmed by authorized peer reviewers and editorial committees.
    </div>
</div>
</body>
</html>
"""
    return html_content

