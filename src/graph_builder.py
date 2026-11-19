"""Citation Trust Graph module for CiteVerify using Plotly.
Visualizes the network connecting scientific claims, in-text citations, and external research papers.
Colors:
- GREEN: Verified citation with supporting evidence.
- RED: Citation exists but evidence contradicts or refutes the claim.
- YELLOW: Insufficient evidence.
- ORANGE: Invalid or mismatched citation.
- BLUE: External research source paper.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import plotly.graph_objects as go

from . import config


def build_citation_trust_graph(
    doc_title: str,
    claims: List[Dict[str, Any]],
    citations: List[Dict[str, Any]],
    results: List[Dict[str, Any]]
) -> go.Figure:
    """Generate an interactive Plotly Citation Trust Graph."""
    if not claims:
        # Return empty figure with message
        fig = go.Figure()
        fig.add_annotation(
            text="No claims or citations available to graph.",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=14, color="#64748B")
        )
        fig.update_layout(
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            plot_bgcolor="#FFFFFF",
            paper_bgcolor="#FFFFFF",
            height=400
        )
        return fig

    # Map claim results
    res_dict = {r["claim_id"]: r for r in results}
    cit_dict = {c["ref_marker"]: c for c in citations}

    # Node positions
    node_x = []
    node_y = []
    node_text = []
    node_color = []
    node_size = []
    node_hover = []
    node_symbols = []

    # 1. Root Node: Document (Center)
    center_x, center_y = 0.0, 0.0
    node_x.append(center_x)
    node_y.append(center_y)
    node_text.append(doc_title[:20] + "...")
    node_color.append("#0F172A")  # Dark Slate
    node_size.append(36)
    node_symbols.append("circle")
    node_hover.append(f"<b>Audited Document</b><br>{doc_title}")

    # 2. Place Claims in an inner circle
    n_c = len(claims)
    claim_coords = {}
    r_claim = 1.6

    edge_x = []
    edge_y = []

    for i, cl in enumerate(claims):
        angle = (2 * math.pi * i) / max(1, n_c)
        cx = r_claim * math.cos(angle)
        cy = r_claim * math.sin(angle)
        cid = cl.get("claim_id", f"C{i+1}")
        claim_coords[cid] = (cx, cy)

        # Connect Document -> Claim
        edge_x.extend([center_x, cx, None])
        edge_y.extend([center_y, cy, None])

        res = res_dict.get(cid, {})
        v = res.get("final_verdict") or res.get("verdict", "NOT_ENOUGH_EVIDENCE")

        # Color logic as required by problem statement:
        # Green: Supporting evidence
        # Red: Refuted / Contradictory
        # Orange: Partially supported / Mismatched
        # Yellow: Insufficient evidence
        if v == "SUPPORTED":
            color = "#10B981"  # GREEN
        elif v in ("REFUTED", "CONTRADICTORY"):
            color = "#EF4444"  # RED
        elif v == "PARTIALLY_SUPPORTED":
            color = "#F59E0B"  # AMBER/ORANGE
        else:
            color = "#EAB308"  # YELLOW

        claim_text = cl.get("claim_text") or cl.get("claim", "")
        ev_snippet = (res.get("evidence_quote") or "None indexed")[:140]

        hover_info = (
            f"<b>Claim {cid}</b><br>"
            f"<b>Verdict:</b> {v}<br>"
            f"<b>Statement:</b> {claim_text[:90]}...<br>"
            f"<b>Evidence:</b> {ev_snippet}..."
        )

        node_x.append(cx)
        node_y.append(cy)
        node_text.append(cid)
        node_color.append(color)
        node_size.append(26)
        node_symbols.append("diamond")
        node_hover.append(hover_info)

    # 3. Place Research Sources in an outer ring
    n_cit = max(1, len(citations))
    r_cit = 3.2
    cit_coords = {}

    for j, ct in enumerate(citations):
        angle = (2 * math.pi * j) / n_cit + (math.pi / max(2, n_cit))
        sx = r_cit * math.cos(angle)
        sy = r_cit * math.sin(angle)
        marker = ct.get("ref_marker", str(j+1))
        cit_coords[marker] = (sx, sy)

        # Check citation status:
        # Orange if invalid/mismatched/fake DOI; Blue if genuine research source
        c_status = ct.get("verified_status", "UNVERIFIED")
        if c_status in ("DOI_NOT_FOUND", "METADATA_MISMATCH", "POSSIBLY_RETRACTED"):
            s_color = "#F97316"  # ORANGE (Invalid / Mismatched)
        else:
            s_color = "#2563EB"  # BLUE (Research Source)

        c_title = ct.get("title", "Research Paper")
        c_doi = ct.get("doi") or "No DOI"
        c_reason = ct.get("reason", "")

        hover_source = (
            f"<b>Reference [{marker}]</b><br>"
            f"<b>Title:</b> {c_title[:80]}...<br>"
            f"<b>DOI:</b> {c_doi}<br>"
            f"<b>Status:</b> {c_status}<br>"
            f"<b>Registry Audit:</b> {c_reason[:100]}..."
        )

        node_x.append(sx)
        node_y.append(sy)
        node_text.append(f"[{marker}]")
        node_color.append(s_color)
        node_size.append(22)
        node_symbols.append("square")
        node_hover.append(hover_source)

    # 4. Connect Claims -> Research Sources
    for cl in claims:
        cid = cl.get("claim_id")
        marker = cl.get("citation_marker") or cl.get("citation", "")
        # Extract number if bracketed e.g. [1]
        import re
        nums = re.findall(r"\d+", marker)
        if cid in claim_coords:
            c_pos = claim_coords[cid]
            for num in nums:
                if num in cit_coords:
                    s_pos = cit_coords[num]
                    edge_x.extend([c_pos[0], s_pos[0], None])
                    edge_y.extend([c_pos[1], s_pos[1], None])

    # Build Plotly Figure
    fig = go.Figure()

    # Add Edges Trace
    fig.add_trace(go.Scatter(
        x=edge_x, y=edge_y,
        mode="lines",
        line=dict(width=1.5, color="#CBD5E1"),
        hoverinfo="none",
        showlegend=False
    ))

    # Add Nodes Trace
    fig.add_trace(go.Scatter(
        x=node_x, y=node_y,
        mode="markers+text",
        text=node_text,
        textposition="top center",
        textfont=dict(size=10, family="Helvetica", color="#0F172A"),
        hovertext=node_hover,
        hoverinfo="text",
        marker=dict(
            symbol=node_symbols,
            size=node_size,
            color=node_color,
            line=dict(width=2, color="#FFFFFF")
        ),
        showlegend=False
    ))

    # Add Legend Markers
    legend_items = [
        ("Verified & Supported Evidence", "#10B981", "diamond"),
        ("Refuted / Contradictory Claim", "#EF4444", "diamond"),
        ("Partially Supported", "#F59E0B", "diamond"),
        ("Insufficient Evidence", "#EAB308", "diamond"),
        ("External Research Source", "#2563EB", "square"),
        ("Invalid / Mismatched Citation", "#F97316", "square"),
    ]
    for label, col, sym in legend_items:
        fig.add_trace(go.Scatter(
            x=[None], y=[None],
            mode="markers",
            name=label,
            marker=dict(size=10, color=col, symbol=sym)
        ))

    fig.update_layout(
        title=dict(
            text="Interactive Citation & Evidence Trust Graph",
            font=dict(size=16, color="#0F172A", family="Helvetica")
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="center",
            x=0.5,
            font=dict(size=10)
        ),
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        plot_bgcolor="#F8FAFC",
        paper_bgcolor="#FFFFFF",
        margin=dict(l=20, r=20, t=60, b=20),
        height=560,
        hovermode="closest"
    )

    return fig
