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
