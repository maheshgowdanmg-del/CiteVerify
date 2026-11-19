"""CiteVerify - Scientific Claim and Citation Verification System.
Main Streamlit Application.
Run with: streamlit run app.py or python app.py
"""
from __future__ import annotations

import sys
import streamlit.runtime

# Auto-launch Streamlit if executed via 'python app.py' or IDE Run button
if not streamlit.runtime.exists():
    from streamlit.web import cli as stcli
    sys.argv = ["streamlit", "run", __file__] + sys.argv[1:]
    sys.exit(stcli.main())

import os
import io
import time
import sqlite3
from pathlib import Path
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Configure Streamlit page
st.set_page_config(
    page_title="CiteVerify AI - Scientific Claim & Citation Verification",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Import internal modules
from src import (
    ai_provider,
    config,
    database,
    pdf_extractor,
    citation_parser,
    citation_checker,
    claim_extractor,
    research_retriever,
    evidence_matcher,
    gemini_engine,
    contradiction_detector,
    trust_score,
    report_generator,
    graph_builder,
    theme,
    utils,
    pipeline,
)

# Initialize database
database.init_db()

# Inject custom Linear/Stripe/Vercel SaaS theme
theme.inject_theme(st)

# Load sample paper path
SAMPLE_TXT_PATH = config.BASE_DIR / "data" / "sample" / "sample_paper.txt"


# ---------------- SESSION STATE INITIALIZATION ----------------
if "upload_key" not in st.session_state:
    st.session_state.upload_key = 0
if "staged_file" not in st.session_state:
    st.session_state.staged_file = None
if "current_doc" not in st.session_state:
    recent_docs = database.list_documents()
    if recent_docs:
        st.session_state.current_doc = database.get_document_run(recent_docs[0]["id"])
    else:
        st.session_state.current_doc = None
if "selected_page" not in st.session_state:
    st.session_state.selected_page = "Overview"


# ---------------- SIDEBAR NAVIGATION ----------------
with st.sidebar:
    st.markdown(theme.render_brand(), unsafe_allow_html=True)

    # API Status Indicator
    active_prov = config.get_active_provider()
    ai_active = config.is_ai_configured()
    active_model = config.get_active_model()
    if active_prov == "gemini" and ai_active:
        st.markdown(
            f"<div style='background:#042F2E;color:#2DD4BF;padding:6px 12px;border-radius:8px;"
            f"font-size:0.75rem;font-weight:600;display:flex;align-items:center;gap:6px;margin-bottom:12px;'>"
            f"● Gemini AI Active ({active_model})</div>",
            unsafe_allow_html=True
        )
    elif active_prov == "groq" and ai_active:
        st.markdown(
            f"<div style='background:#1C1917;color:#F59E0B;padding:6px 12px;border-radius:8px;"
            f"font-size:0.75rem;font-weight:600;display:flex;align-items:center;gap:6px;margin-bottom:12px;'>"
            f"● Groq Cloud Active ({active_model})</div>",
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            "<div style='background:#1E293B;color:#94A3B8;padding:6px 12px;border-radius:8px;"
            "font-size:0.75rem;font-weight:600;display:flex;align-items:center;gap:6px;margin-bottom:12px;'>"
            "● Offline Rule Engine</div>",
            unsafe_allow_html=True
        )

    st.markdown("<p style='font-size:0.75rem;font-weight:700;color:#94A3B8;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:6px;'>Navigation</p>", unsafe_allow_html=True)

    NAV_ITEMS = [
        "Overview",
        "New Verification",
        "Claim Intelligence",
        "Citation Integrity",
        "Evidence Explorer",
        "Claim Relationship Map",
        "Human Review",
        "Verification History",
        "Report Center",
        "Settings"
    ]

    # Map legacy page names to new standard items if present in session state
    nav_alias_map = {
        "Document Analysis": "New Verification",
        "Claim Verification": "Claim Intelligence",
        "Citation Fraud Detection": "Citation Integrity",
        "Evidence Comparison": "Evidence Explorer",
        "Citation Trust Graph": "Claim Relationship Map",
        "Verification Reports": "Report Center",
    }
    cur_selected = nav_alias_map.get(st.session_state.selected_page, st.session_state.selected_page)
    if cur_selected not in NAV_ITEMS:
        cur_selected = "Overview"

    selected_nav = st.radio(
        "Menu",
        NAV_ITEMS,
        index=NAV_ITEMS.index(cur_selected),
        label_visibility="collapsed"
    )
    st.session_state.selected_page = selected_nav

    st.divider()

    # Document History Quick Switcher
    st.markdown("<p style='font-size:0.75rem;font-weight:700;color:#94A3B8;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:6px;'>Active Session</p>", unsafe_allow_html=True)
    history_docs = database.list_documents()
    if history_docs:
        options = ["Select document to load..."] + [f"{d['filename']} ({d['claims_count']} claims)" for d in history_docs]
        hist_choice = st.selectbox("Load History", options, label_visibility="collapsed")
        if hist_choice != "Select document to load...":
            chosen_idx = options.index(hist_choice) - 1
            chosen_id = history_docs[chosen_idx]["id"]
            if st.button("📂 Switch to Document", use_container_width=True):
                loaded = database.get_document_run(chosen_id)
                if loaded:
                    st.session_state.current_doc = loaded
                    st.success(f"Loaded: {loaded['document']['filename']}")
                    st.rerun()
    else:
        st.caption("No past document runs stored yet.")

    st.divider()
    st.markdown(
        "<div style='font-size:0.75rem;color:#94A3B8;line-height:1.4;'>"
        "CiteVerify AI operates as academic research intelligence. Automated verdicts evaluate statements against "
        "open scholarly abstracts and metadata from Crossref, OpenAlex, Semantic Scholar, and PubMed."
        "</div>",
        unsafe_allow_html=True
    )


# ---------------- HELPER FUNCTIONS & UPLOAD COMPONENT ----------------

def format_file_size(bytes_len: int) -> str:
    """Format bytes into readable string."""
    if bytes_len < 1024:
        return f"{bytes_len} B"
    elif bytes_len < 1024 * 1024:
        return f"{bytes_len / 1024:.1f} KB"
    else:
        return f"{bytes_len / (1024 * 1024):.2f} MB"


def cancel_staged_file():
    """Cancel and remove the currently staged file and reset uploader widget."""
    st.session_state.upload_key += 1
    st.session_state.staged_file = None
    st.session_state.temp_extracted = None
    st.session_state.temp_bytes = None
    st.session_state.temp_fname = None
    st.toast("Uploaded document cancelled and removed.", icon="🗑️")
    st.rerun()


def unload_active_document():
    """Unload the active document to view global system state."""
    st.session_state.current_doc = None
    st.toast("Active document unloaded.", icon="ℹ️")
    st.rerun()


def render_upload_section(context_key: str = "main", max_claims_default: int = 20):
    """Render a premium file upload component with File Explorer browsing, demo loader,
    staged document card with clear cancel button, and preview tabs."""
    if "upload_key" not in st.session_state:
        st.session_state.upload_key = 0
    if "staged_file" not in st.session_state:
        st.session_state.staged_file = None

    # If a file is currently staged: show File Attached Card with Cancel and Verify triggers
    staged = st.session_state.staged_file
    if staged is not None:
        filename = staged["filename"]
        meta = staged["meta"]
        ext = meta.get("file_type", "FILE").upper()
        icon = "📕" if ext == "PDF" else ("📘" if "DOC" in ext else "📄")
        size_str = staged.get("size_str", format_file_size(len(staged["bytes"])))
        pages = meta.get("page_count", 1)
        words = meta.get("word_count", 0)
        refs = len(meta.get("references", []))

        st.markdown(f"""
        <div class="cv-file-card">
            <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;">
                <div style="display:flex;align-items:center;gap:14px;">
                    <div style="font-size:2.2rem;line-height:1;">{icon}</div>
                    <div>
                        <div style="font-size:1.05rem;font-weight:800;color:#0B1220;">{filename}</div>
                        <div style="font-size:0.82rem;color:#64748B;margin-top:4px;">
                            <span>Format: <b>{ext}</b></span> &bull; 
                            <span>Size: <b>{size_str}</b></span> &bull; 
                            <span>Pages: <b>{pages}</b></span> &bull; 
                            <span>Words: <b>~{words:,}</b></span> &bull; 
                            <span>Detected References: <b>{refs}</b></span>
                        </div>
                    </div>
                </div>
                <div>
                    <span class="cv-file-badge cv-badge-ready">● READY TO VERIFY</span>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        col_c, col_v = st.columns([1.1, 2.2])
        with col_c:
            if st.button("❌ Cancel / Remove File", key=f"cancel_btn_{context_key}", type="secondary", use_container_width=True):
                cancel_staged_file()

        with col_v:
            max_c = st.slider(
                "Maximum scientific claims to audit",
                min_value=5, max_value=50, value=max_claims_default, step=5,
                key=f"slider_claims_{context_key}"
            )
            if st.button("🚀 Verify Claims & Citations", key=f"verify_btn_{context_key}", type="primary", use_container_width=True):
                prog_bar = st.progress(0.0)
                status_text = st.empty()

                def update_cb(pct, msg):
                    prog_bar.progress(pct)
                    status_text.markdown(f"**Verification Progress:** {msg}")

                try:
                    run_res = pipeline.run_full_verification_pipeline(
                        staged["bytes"],
                        staged["filename"],
                        max_claims=max_c,
                        progress_callback=update_cb
                    )
                    st.session_state.current_doc = run_res
                    st.session_state.staged_file = None
                    status_text.empty()
                    prog_bar.empty()
                    st.success(f"Verification complete! Audited {len(run_res['claims'])} claims.")
                    st.session_state.selected_page = "Claim Intelligence"
                    st.rerun()
                except Exception as ex:
                    status_text.empty()
                    prog_bar.empty()
                    st.error(f"Verification failed: {str(ex)}")

        # Document Text Preview Expander
        with st.expander("📄 Document Text & Extracted References Preview", expanded=False):
            tab_body, tab_refs, tab_full = st.tabs(["Body Text Preview", "References Section", "Full Raw Text"])
            with tab_body:
                st.text_area("Body Text", meta.get("body_text", "")[:4000], height=220, key=f"txt_body_{context_key}")
            with tab_refs:
                st.text_area("References Section", meta.get("references_text", ""), height=220, key=f"txt_refs_{context_key}")
            with tab_full:
                st.text_area("Full Text", meta.get("raw_text", "")[:4000], height=220, key=f"txt_raw_{context_key}")

        return

    # If no file is staged: show Dropzone with File Explorer + Demo + Local Path Tabs
    upload_tab1, upload_tab2, upload_tab3 = st.tabs([
        "📂 Browse from File Explorer",
        "📚 Built-in Scientific Library",
        "💻 Local File Path"
    ])

    with upload_tab1:
        st.markdown("""
        <div class="cv-dropzone">
            <div style="font-size:2.4rem;margin-bottom:6px;">📂</div>
            <div style="font-size:1.1rem;font-weight:700;color:#0B1220;">Browse or Drag & Drop File from File Explorer</div>
            <div style="font-size:0.82rem;color:#64748B;margin-top:4px;">Supported Formats: PDF, DOCX, TXT &bull; Max size: 50 MB</div>
        </div>
        """, unsafe_allow_html=True)

        up_file = st.file_uploader(
            "Choose research document from your computer",
            type=["pdf", "docx", "txt"],
            key=f"file_uploader_{context_key}_{st.session_state.upload_key}",
            label_visibility="collapsed"
        )
        if up_file is not None:
            raw_b = up_file.getvalue()
            raw_n = up_file.name
            try:
                meta = pdf_extractor.process_uploaded_document(raw_b, raw_n)
                st.session_state.staged_file = {
                    "bytes": raw_b,
                    "filename": raw_n,
                    "size_str": format_file_size(len(raw_b)),
                    "meta": meta
                }
                st.rerun()
            except Exception as e:
                st.error(f"Error parsing uploaded file: {str(e)}")

    with upload_tab2:
        st.markdown("<p style='font-size:0.85rem;color:#64748B;margin-bottom:8px;'>Select a peer-reviewed benchmark document with known valid/fabricated claims:</p>", unsafe_allow_html=True)
        demo_papers = {
            "Oncology AI Screening (sample_paper.txt)": {
                "file": "sample_paper.txt",
                "desc": "Breast cancer deep learning trial containing supported benchmarks, 2 fabricated DOIs, and numerical mismatches."
            },
            "Clean Energy & Storage Integration (climate_renewable_energy.txt)": {
                "file": "climate_renewable_energy.txt",
                "desc": "Grid resilience, solar PV degradation, and utility-scale battery storage claims."
            },
            "Alzheimer's Disease Biomarkers (alzheimers_neuroscience.txt)": {
                "file": "alzheimers_neuroscience.txt",
                "desc": "Clinical evaluation of CSF p-tau217, amyloid PET imaging, and cognition decline metrics."
            }
        }
        chosen_demo_label = st.selectbox(
            "Select Demo Document",
            list(demo_papers.keys()),
            key=f"sel_demo_{context_key}"
        )
        st.caption(f"ℹ️ {demo_papers[chosen_demo_label]['desc']}")
        if st.button("📄 Load Selected Demo Paper", key=f"btn_demo_{context_key}", use_container_width=True):
            p_file = demo_papers[chosen_demo_label]["file"]
            sample_p = config.BASE_DIR / "data" / "sample" / p_file
            if sample_p.exists():
                with open(sample_p, "rb") as f:
                    raw_b = f.read()
                meta = pdf_extractor.process_uploaded_document(raw_b, p_file)
                st.session_state.staged_file = {
                    "bytes": raw_b,
                    "filename": p_file,
                    "size_str": format_file_size(len(raw_b)),
                    "meta": meta
                }
                st.rerun()
            else:
                st.error("Demo file could not be found.")

    with upload_tab3:
        st.markdown("<p style='font-size:0.85rem;color:#64748B;margin-bottom:8px;'>Enter absolute path to a file on your computer:</p>", unsafe_allow_html=True)
        path_input = st.text_input(
            "File Explorer Absolute Path",
            placeholder="e.g. C:/Users/Name/Documents/paper.pdf",
            key=f"local_path_inp_{context_key}",
            label_visibility="collapsed"
        )
        if st.button("📂 Load from Local Path", key=f"btn_path_{context_key}", use_container_width=True):
            if path_input and Path(path_input).exists():
                p_obj = Path(path_input)
                if p_obj.suffix.lower() in [".pdf", ".docx", ".txt"]:
                    with open(p_obj, "rb") as f:
                        raw_b = f.read()
                    meta = pdf_extractor.process_uploaded_document(raw_b, p_obj.name)
                    st.session_state.staged_file = {
                        "bytes": raw_b,
                        "filename": p_obj.name,
                        "size_str": format_file_size(len(raw_b)),
                        "meta": meta
                    }
                    st.rerun()
                else:
                    st.error("Unsupported file extension. Please select .pdf, .docx, or .txt.")
            else:
                st.error("Specified file path does not exist on disk.")


# ---------------- WORKSPACE ROUTER ----------------
current_page = st.session_state.selected_page
doc_data = st.session_state.current_doc


# ==============================================================================
# 1. OVERVIEW DASHBOARD
# ==============================================================================
if current_page == "Overview":
    st.markdown(theme.render_hero(
        "Scientific Claim & Citation Verification Intelligence",
        "Executive Research Intelligence",
        "A citation is not proof by itself. CiteVerify verifies whether cited scholarly research "
        "actually corroborates scientific claims, checks citation legitimacy via Crossref, detects contradictions, "
        "and computes transparent academic integrity scores."
    ), unsafe_allow_html=True)

    stats = database.get_global_statistics()

    # Active Document Banner if a document is loaded
    if doc_data:
        d_meta = doc_data["document"]
        t_sc = doc_data.get("trust_score") or {}
        score_val = t_sc.get("score", d_meta.get("trust_score", 0.0))
        grade_val = t_sc.get("grade", d_meta.get("trust_grade", "Evaluated"))
        claims_cnt = len(doc_data.get('claims', []))
        cits_cnt = len(doc_data.get('citations', []))

        st.markdown(f"""
        <div style="background:#FFFFFF;border:1px solid #CBD5E1;border-left:5px solid #14B8A6;border-radius:14px;padding:18px 24px;margin-bottom:18px;box-shadow:0 2px 10px rgba(11,18,32,0.04);">
            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;">
                <div>
                    <div style="display:flex;align-items:center;gap:8px;">
                        <span style="font-size:0.75rem;font-weight:700;color:#14B8A6;text-transform:uppercase;letter-spacing:0.04em;">Active Document Under Audit</span>
                        <span class="cv-file-badge cv-badge-analyzed">ACTIVE</span>
                    </div>
                    <div style="font-size:1.25rem;font-weight:800;color:#0B1220;margin-top:2px;">{d_meta['filename']}</div>
                    <div style="font-size:0.82rem;color:#64748B;margin-top:4px;">
                        <span><b>{claims_cnt}</b> Claims Audited</span> &bull; 
                        <span><b>{cits_cnt}</b> References</span> &bull; 
                        <span><b>{d_meta.get('page_count', 1)}</b> Page(s)</span> &bull; 
                        <span>Analyzed: {d_meta.get('created_at', 'Recently')}</span>
                    </div>
                </div>
                <div style="text-align:right;">
                    <div style="font-size:0.78rem;color:#64748B;font-weight:600;">Academic Trust Score</div>
                    <div style="font-size:2rem;font-weight:800;color:#14B8A6;line-height:1.1;">{score_val}/100</div>
                    <div style="font-size:0.82rem;font-weight:700;color:#0F766E;">{grade_val}</div>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Quick Navigation Bar for Active Document
        nb1, nb2, nb3, nb4, nb5 = st.columns(5)
        with nb1:
            if st.button("📋 Claim Intelligence", use_container_width=True):
                st.session_state.selected_page = "Claim Intelligence"
                st.rerun()
        with nb2:
            if st.button("🛡️ Citation Integrity", use_container_width=True):
                st.session_state.selected_page = "Citation Integrity"
                st.rerun()
        with nb3:
            if st.button("🔍 Evidence Explorer", use_container_width=True):
                st.session_state.selected_page = "Evidence Explorer"
                st.rerun()
        with nb4:
            if st.button("📥 Download Report", use_container_width=True):
                st.session_state.selected_page = "Report Center"
                st.rerun()
        with nb5:
            if st.button("🔄 Unload Document", use_container_width=True):
                unload_active_document()

        st.markdown("<div style='margin-bottom:14px;'></div>", unsafe_allow_html=True)

    # Quick Upload & Audit Center right on the Overview Dashboard!
    with st.expander("📤 Quick Document Audit & File Upload (File Explorer / Demo)", expanded=(st.session_state.staged_file is not None or not doc_data)):
        render_upload_section(context_key="overview_dash", max_claims_default=15)

    # Global KPI Metric Cards
    k1, k2, k3, k4, k5 = st.columns(5)
    supp_pct = (stats['supported_claims'] / max(1, stats['total_claims'])) * 100
    with k1:
        st.markdown(theme.render_kpi_card("Total Documents", stats["total_documents"], "Stored in SQLite", "#14B8A6"), unsafe_allow_html=True)
    with k2:
        st.markdown(theme.render_kpi_card("Claims Audited", stats["total_claims"], f"{stats['supported_claims']} Supported ({supp_pct:.0f}%)", "#2DD4BF"), unsafe_allow_html=True)
    with k3:
        st.markdown(theme.render_kpi_card("Integrity Flags", stats["invalid_or_mismatched_citations"], "Fabricated / Mismatched DOIs", "#E11D48"), unsafe_allow_html=True)
    with k4:
        st.markdown(theme.render_kpi_card("Evidence Coverage", f"{stats['evidence_coverage']}%", "Verbatim Quotations", "#8B5CF6"), unsafe_allow_html=True)
    with k5:
        st.markdown(theme.render_kpi_card("Avg Trust Score", f"{stats['avg_trust_score']}/100", "Overall Academic Integrity", "#D6B56D"), unsafe_allow_html=True)

    st.markdown("<br/>", unsafe_allow_html=True)

    # Analytical Charts Row
    ch1, ch2, ch3 = st.columns([1.2, 1.2, 1.0])

    with ch1:
        st.markdown("#### Claim Verification Verdicts")
        v_dist = stats["verdict_distribution"]
        if sum(v_dist.values()) > 0:
            df_v = pd.DataFrame([
                {"Verdict": config.VERDICTS[k]["label"], "Count": v, "Color": config.VERDICTS[k]["color"]}
                for k, v in v_dist.items() if v > 0
            ])
            fig_v = px.pie(
                df_v, values="Count", names="Verdict",
                color="Verdict",
                color_discrete_map={row["Verdict"]: row["Color"] for _, row in df_v.iterrows()},
                hole=0.45
            )
            fig_v.update_traces(textposition='inside', textinfo='percent+label')
            fig_v.update_layout(showlegend=False, margin=dict(t=20, b=20, l=20, r=20), height=280)
            st.plotly_chart(fig_v, use_container_width=True)
        else:
            st.info("No claim verification results to chart.")

    with ch2:
        st.markdown("#### Citation Integrity Status")
        c_dist = stats["citation_integrity"]
        if sum(c_dist.values()) > 0:
            df_c = pd.DataFrame([
                {"Status": config.CITATION_STATUSES[k]["label"], "Count": v, "Color": config.CITATION_STATUSES[k]["color"]}
                for k, v in c_dist.items() if v > 0
            ])
            fig_c = px.bar(
                df_c, x="Status", y="Count",
                color="Status",
                color_discrete_map={row["Status"]: row["Color"] for _, row in df_c.iterrows()},
                text="Count"
            )
            fig_c.update_layout(showlegend=False, xaxis_title="", yaxis_title="Citations", margin=dict(t=20, b=20, l=20, r=20), height=280)
            st.plotly_chart(fig_c, use_container_width=True)
        else:
            st.info("No citations evaluated to chart.")

    with ch3:
        st.markdown("#### Numerical Consistency")
        n_dist = stats.get("numeric_distribution", {})
        if sum(n_dist.values()) > 0:
            n_colors = {
                "NUMERICAL_MATCH": "#14B8A6",
                "NUMERICAL_MISMATCH": "#E11D48",
                "NUMERICAL_UNCONFIRMED": "#64748B"
            }
            n_labels = {
                "NUMERICAL_MATCH": "Verified Match",
                "NUMERICAL_MISMATCH": "Mismatch / Distortion",
                "NUMERICAL_UNCONFIRMED": "Unconfirmed in Abstract"
            }
            df_n = pd.DataFrame([
                {"Metric": n_labels.get(k, k), "Count": v, "Color": n_colors.get(k, "#64748B")}
                for k, v in n_dist.items() if v > 0
            ])
            fig_n = px.pie(
                df_n, values="Count", names="Metric",
                color="Metric",
                color_discrete_map={row["Metric"]: row["Color"] for _, row in df_n.iterrows()},
                hole=0.45
            )
            fig_n.update_traces(textposition='inside', textinfo='percent+label')
            fig_n.update_layout(showlegend=False, margin=dict(t=20, b=20, l=20, r=20), height=280)
            st.plotly_chart(fig_n, use_container_width=True)
        else:
            st.info("No numerical checks evaluated.")

    # Recent Activity Table
    st.markdown("#### Recent Document Analyses")
    if stats["recent_activity"]:
        df_act = pd.DataFrame(stats["recent_activity"])
        df_act = df_act.rename(columns={
            "id": "Doc ID",
            "filename": "Filename",
            "claims_count": "Claims",
            "trust_score": "Trust Score",
            "trust_grade": "Grade",
            "created_at": "Analyzed At"
        })
        st.dataframe(df_act[["Filename", "Claims", "Trust Score", "Grade", "Analyzed At"]], use_container_width=True)
    else:
        st.caption("No recent activity.")


# ==============================================================================
# 2. NEW VERIFICATION (DOCUMENT PROCESSING & PIPELINE)
# ==============================================================================
elif current_page == "New Verification":
    st.markdown(theme.render_hero(
        "Document Ingestion & Verification Pipeline",
        "Verification Station",
        "Upload research manuscripts or student reports in PDF, DOCX, or TXT format. "
        "CiteVerify parses document structures, separates body claims from bibliographies, detects citations, "
        "retrieves original evidence passages, and generates transparent verdicts."
    ), unsafe_allow_html=True)

    render_upload_section(context_key="new_verification_page", max_claims_default=25)


# ==============================================================================
# 3. CLAIM INTELLIGENCE & EXPLAINABILITY
# ==============================================================================
elif current_page == "Claim Intelligence":
    st.markdown(theme.render_hero(
        "Scientific Claim Intelligence & Verification",
        "Evidence Corroboration",
        "Evaluates whether original cited research papers actually support the scientific claims made. "
        "Every claim includes explainable verification breakdowns, verbatim evidence passages, confidence estimation, "
        "and human-in-the-loop review controls."
    ), unsafe_allow_html=True)

    if not doc_data:
        st.warning("No document currently loaded. Please start a verification in 'New Verification' or load a past run.")
        st.stop()

    results = doc_data.get("results", [])
    claims = doc_data.get("claims", [])
    claims_dict = {c["claim_id"]: c for c in claims}
    doc_id = doc_data["document"]["id"]

    # Filter row
    cf1, cf2, cf3 = st.columns([1.5, 1.2, 1.2])
    with cf1:
        search_kw = st.text_input("🔍 Search claims by keyword or topic", placeholder="e.g. cancer, accuracy, battery")
    with cf2:
        selected_verdicts = st.multiselect(
            "Filter by Verdict",
            options=list(config.VERDICTS.keys())[:5],
            default=[],
            format_func=lambda x: f"{config.VERDICTS[x]['icon']} {config.VERDICTS[x]['label']}"
        )
    with cf3:
        selected_types = st.multiselect(
            "Filter by Claim Type",
            options=claim_extractor.CLAIM_TYPES,
            default=[]
        )

    matched_count = 0
    for idx, r in enumerate(results, 1):
        cid = r.get("claim_id", f"C{idx}")
        c_info = claims_dict.get(cid, {})
        claim_text = c_info.get("claim_text") or c_info.get("claim", "")
        citation_marker = c_info.get("citation_marker") or c_info.get("citation", "")
        claim_type = c_info.get("claim_type", "Empirical")
        topic = c_info.get("topic", "General Science")
        v_current = config.normalize_verdict(r.get("final_verdict") or r.get("verdict", "NEEDS_REVIEW"))
        orig_v = config.normalize_verdict(r.get("verdict", "NEEDS_REVIEW"))
        action = r.get("review_action", "AI Verified")

        # Apply filters
        if search_kw and (search_kw.lower() not in claim_text.lower() and search_kw.lower() not in topic.lower()):
            continue
        if selected_verdicts and v_current not in selected_verdicts:
            continue
        if selected_types and claim_type not in selected_types:
            continue

        matched_count += 1
        v_meta = config.VERDICTS.get(v_current, config.VERDICTS["NEEDS_REVIEW"])
        badge_html = utils.render_verdict_badge(v_current)
        conf_pct = int(float(r.get("confidence_score", 0.5)) * 100)
        ev_quote = r.get("evidence_quote") or (r.get("evidence") or {}).get("quote", "")

        # Outdated research check
        src_year = r.get("source_year")
        is_outdated = False
        if src_year and isinstance(src_year, int):
            current_year = time.localtime().tm_year
            if current_year - src_year > config.OUTDATED_YEARS_THRESHOLD:
                is_outdated = True

        with st.expander(f"{cid} &bull; {v_meta['label']} &bull; {claim_text[:85]}...", expanded=False):
            st.markdown(
                f"{badge_html} &nbsp; <b>Claim Type:</b> `{claim_type}` &bull; <b>Subdomain:</b> `{topic}` &bull; <b>Confidence:</b> {conf_pct}% ({r.get('confidence_label', 'High')})",
                unsafe_allow_html=True
            )
            st.markdown(f"**Scientific Claim Statement:** \"{claim_text}\"")
            st.markdown(f"**Cited Reference Marker:** `{citation_marker}` &nbsp;|&nbsp; **Source:** *{r.get('source_title', 'Not specified')}* ({r.get('source_year', 'n.d.')})")
            if r.get("source_doi"):
                st.markdown(f"**Source DOI:** [`{r['source_doi']}`](https://doi.org/{r['source_doi']}) &nbsp;|&nbsp; **Authors:** {r.get('source_authors', 'n/a')}")

            if is_outdated:
                st.warning(f"⏳ **Outdated Research Alert:** This publication is {time.localtime().tm_year - src_year} years old ({src_year}). Recent replication or newer clinical trials recommended.")

            # Explainable Verification 6-Point Breakdown
            expl = r.get("explainability") or {}
            st.markdown("##### 🔍 Explainable Verification Breakdown")
            ex_col1, ex_col2 = st.columns(2)
            with ex_col1:
                st.markdown(f"**1. What was claimed?**<br/>{expl.get('what_was_claimed', claim_text)}", unsafe_allow_html=True)
                st.markdown(f"**2. What did the source actually report?**<br/>{expl.get('what_source_reported', r.get('explanation', ''))}", unsafe_allow_html=True)
                st.markdown(f"**3. What matched?**<br/>{expl.get('what_matched', 'General topical agreement')}", unsafe_allow_html=True)
            with ex_col2:
                st.markdown(f"**4. What did not match / discrepancies?**<br/>{expl.get('what_did_not_match', 'None noted')}", unsafe_allow_html=True)
                st.markdown(f"**5. Why was this verdict assigned?**<br/>{expl.get('why_assigned', r.get('explanation', ''))}", unsafe_allow_html=True)
                st.markdown(f"**6. What remains uncertain?**<br/>{expl.get('what_remains_uncertain', r.get('limitations', 'No bounds noted'))}", unsafe_allow_html=True)

            if ev_quote:
                st.markdown(
                    f"**Verbatim Retrieved Evidence Quote:**"
                    f"<div style='border-left:4px solid #14B8A6;background:#F8FAFC;padding:10px 14px;border-radius:6px;margin:6px 0;font-size:0.9rem;line-height:1.5;'>"
                    f"&ldquo;{ev_quote}&rdquo;</div>",
                    unsafe_allow_html=True
                )

            # Numerical Check Box
            nc = r.get("numeric_check") or {}
            if nc.get("verdict") == "NUMERICAL_MISMATCH":
                st.error(f"⚠️ **Numerical Mismatch Detected:** {nc.get('explanation')}")
            elif nc.get("verdict") == "NUMERICAL_MATCH":
                st.success(f"✅ **Numerical Verification Confirmed:** {nc.get('explanation')}")

            # Contradiction note if present
            if r.get("contradiction_notes"):
                st.info(f"⚡ **Multi-Study Consensus Note:** {r['contradiction_notes']}")

    if matched_count == 0:
        st.info("No claims matched the active filter criteria.")


# ==============================================================================
# 4. CITATION INTEGRITY & FRAUD DETECTION
# ==============================================================================
elif current_page == "Citation Integrity":
    st.markdown(theme.render_hero(
        "Citation Integrity & Registry Fraud Detection",
        "Reference Legitimacy",
        "Cross-checks cited publications against official scholarly registries (Crossref, OpenAlex, PubMed), "
        "detects fabricated DOIs, identifies metadata hijacking, and flags retracted papers."
    ), unsafe_allow_html=True)

    if not doc_data:
        st.warning("No document currently loaded. Please start a verification in 'New Verification' or load a past run.")
        st.stop()

    citations = doc_data.get("citations", [])
    if not citations:
        st.info("No citations or references were detected in the current document.")
        st.stop()

    # Integrity Summary Cards
    f1, f2, f3, f4 = st.columns(4)
    total_cit = len(citations)
    verified_cit = sum(1 for c in citations if c.get("verified_status") == "VERIFIED")
    mismatch_cit = sum(1 for c in citations if c.get("verified_status") == "METADATA_MISMATCH")
    notfound_cit = sum(1 for c in citations if c.get("verified_status") == "DOI_NOT_FOUND")
    retracted_cit = sum(1 for c in citations if c.get("retracted") or c.get("verified_status") == "POSSIBLY_RETRACTED")

    f1.markdown(theme.render_kpi_card("Total References", total_cit, "In Bibliography", "#14B8A6"), unsafe_allow_html=True)
    f2.markdown(theme.render_kpi_card("Verified DOIs", verified_cit, "Registry Confirmed", "#2DD4BF"), unsafe_allow_html=True)
    f3.markdown(theme.render_kpi_card("Metadata Conflicts", mismatch_cit, "Title/Year Mismatch", "#D6B56D"), unsafe_allow_html=True)
    f4.markdown(theme.render_kpi_card("Fabricated / Retracted", notfound_cit + retracted_cit, "High Risk Entries", "#E11D48"), unsafe_allow_html=True)

    st.markdown("<br/>", unsafe_allow_html=True)

    # Filter selector
    filter_status = st.multiselect(
        "Filter by Citation Status",
        options=list(config.CITATION_STATUSES.keys()),
        default=[],
        format_func=lambda x: f"{config.CITATION_STATUSES[x]['icon']} {config.CITATION_STATUSES[x]['label']}"
    )

    for c in citations:
        st_key = c.get("verified_status", "UNVERIFIED")
        if filter_status and st_key not in filter_status:
            continue

        st_meta = config.CITATION_STATUSES.get(st_key, config.CITATION_STATUSES["UNVERIFIED"])
        badge_html = utils.render_citation_badge(st_key)
        marker = c.get("ref_marker", "")
        raw = c.get("raw_text", "")
        title = c.get("title", "")
        doi = c.get("doi", "")
        reason = c.get("reason", "")
        url = c.get("source_url") or (f"https://doi.org/{doi}" if doi else "")

        with st.expander(f"[{marker}] {title[:80]}... &bull; {st_meta['label']}", expanded=(st_key in ("DOI_NOT_FOUND", "METADATA_MISMATCH", "POSSIBLY_RETRACTED"))):
            st.markdown(f"{badge_html} &nbsp; <b>DOI:</b> `{doi or 'None specified'}`", unsafe_allow_html=True)
            st.markdown(f"**Full Reference Text:** {raw}")
            if reason:
                st.markdown(f"**Registry Audit Finding:** {reason}")
            if url:
                st.markdown(f"**Official Source Record:** [{url}]({url})")
            if c.get("retracted"):
                st.error("🚨 CRITICAL ALERT: Authoritative scholarly registries indicate this publication has been retracted or flagged with formal concern!")

    # Academic Trust Score Formula & Breakdown
    st.markdown("<br/>", unsafe_allow_html=True)
    st.markdown("### 📊 Academic Trust Score Mathematical Breakdown")
    t_data = trust_score.calculate_academic_trust_score(doc_data.get("claims", []), citations, doc_data.get("results", []))
    st.markdown(r"""
    CiteVerify calculates a transparent, mathematically sound integrity score ($0 \le S \le 100$):
    $$\text{Score} = 0.40 \cdot C_{\text{support}} + 0.25 \cdot I_{\text{citation}} + 0.20 \cdot E_{\text{coverage}} + 0.15 \cdot P_{\text{integrity}}$$
    """)
    comps_df = pd.DataFrame(t_data["components"]).rename(columns={"name": "Component", "weight": "Weight", "score": "Score (0-100)", "details": "Evaluation Detail"})
    st.dataframe(comps_df, use_container_width=True)


# ==============================================================================
# 5. EVIDENCE EXPLORER (SIDE-BY-SIDE COMPARISON)
# ==============================================================================
elif current_page == "Evidence Explorer":
    st.markdown(theme.render_hero(
        "Side-by-Side Evidence Explorer",
        "Direct Evidence Audit",
        "Inspect claims directly alongside the verbatim passages extracted from retrieved research papers. "
        "Automated numerical audits compare reported percentages, sample sizes, and benchmark metrics."
    ), unsafe_allow_html=True)

    if not doc_data:
        st.warning("No document currently loaded. Please start a verification in 'New Verification' or load a past run.")
        st.stop()

    results = doc_data.get("results", [])
    claims_dict = {c["claim_id"]: c for c in doc_data.get("claims", [])}

    # Claim Selector for deep inspection
    claim_options = [f"{r['claim_id']} - {(claims_dict.get(r['claim_id'], {}).get('claim') or '')[:70]}..." for r in results]
    selected_option = st.selectbox("Select Claim for Deep Evidence Inspection", claim_options)
    selected_cid = selected_option.split(" - ")[0] if selected_option else (results[0]["claim_id"] if results else "")

    target_r = next((r for r in results if r["claim_id"] == selected_cid), results[0] if results else None)

    if target_r:
        c_info = claims_dict.get(target_r["claim_id"], {})
        claim_text = c_info.get("claim_text") or c_info.get("claim", "")
        ev_passage = target_r.get("evidence", {}).get("passage") or target_r.get("evidence_quote") or "No passage retrieved."
        ev_quote = target_r.get("evidence", {}).get("quote") or target_r.get("evidence_quote") or ""
        v = config.normalize_verdict(target_r.get("final_verdict") or target_r.get("verdict"))
        v_meta = config.VERDICTS.get(v, config.VERDICTS["NEEDS_REVIEW"])

        st.markdown(f"### Claim {target_r['claim_id']} &nbsp; {utils.render_verdict_badge(v)}", unsafe_allow_html=True)

        col_c, col_e = st.columns(2)
        with col_c:
            st.markdown(
                f"<div style='background:#FFFFFF;border:1px solid #E2E8F0;border-left:4px solid #0B1220;border-radius:12px;padding:18px;box-shadow:0 2px 8px rgba(11,18,32,0.03);'>"
                f"<span style='font-size:0.75rem;font-weight:700;color:#0B1220;text-transform:uppercase;'>Document Claim Statement</span>"
                f"<p style='font-size:1.05rem;font-weight:600;color:#0B1220;margin:10px 0;'>\"{claim_text}\"</p>"
                f"<div style='font-size:0.8rem;color:#64748B;'>Citation: <code>{c_info.get('citation_marker') or c_info.get('citation')}</code> &bull; Topic: <b>{c_info.get('topic', 'Science')}</b></div>"
                f"<div style='margin-top:10px;font-size:0.85rem;color:#334155;'><b>Claim Context:</b> {c_info.get('context') or 'Appears in results/discussion section.'}</div>"
                f"</div>",
                unsafe_allow_html=True
            )

        with col_e:
            hl = utils.highlight_passage(ev_passage, ev_quote)
            st.markdown(
                f"<div style='background:#FFFFFF;border:1px solid #E2E8F0;border-left:4px solid #14B8A6;border-radius:12px;padding:18px;box-shadow:0 2px 8px rgba(11,18,32,0.03);'>"
                f"<span style='font-size:0.75rem;font-weight:700;color:#14B8A6;text-transform:uppercase;'>Retrieved Scholarly Evidence</span>"
                f"<p style='font-size:0.92rem;line-height:1.6;color:#334155;margin:10px 0;'>{hl}</p>"
                f"<div style='font-size:0.8rem;color:#64748B;'>Source: <i>{target_r.get('source_title', 'Unknown')}</i> ({target_r.get('source_year', 'n.d.')})</div>"
                f"<div style='font-size:0.8rem;color:#0B1220;'><b>DOI:</b> {target_r.get('source_doi') or 'None'}</div>"
                f"</div>",
                unsafe_allow_html=True
            )

        # Numerical comparison box
        nc = target_r.get("numeric_check") or {}
        if nc.get("claim_numbers") or nc.get("evidence_numbers"):
            st.markdown(
                f"<div style='background:#F8FAFC;border:1px dashed #CBD5E1;border-radius:8px;padding:12px 16px;margin-top:14px;font-size:0.88rem;'>"
                f"<b>Quantitative Audit:</b> {nc.get('explanation')}<br/>"
                f"Claim Figures: <code>{nc.get('claim_numbers')}</code> &rarr; Evidence Figures: <code>{nc.get('evidence_numbers')}</code>"
                f"</div>",
                unsafe_allow_html=True
            )


# ==============================================================================
# 6. CLAIM RELATIONSHIP MAP
# ==============================================================================
elif current_page == "Claim Relationship Map":
    st.markdown(theme.render_hero(
        "Interactive Claim Relationship Map",
        "Network Graph",
        "Visualizes relationships between audited documents, scientific claims, and external peer-reviewed publications. "
        "Nodes are color-coded by verified support, contradictions, or citation fraud alerts."
    ), unsafe_allow_html=True)

    if not doc_data:
        st.warning("No document currently loaded. Please start a verification in 'New Verification' or load a past run.")
        st.stop()

    doc_meta = doc_data["document"]
    claims = doc_data.get("claims", [])
    citations = doc_data.get("citations", [])
    results = doc_data.get("results", [])

    fig = graph_builder.build_citation_trust_graph(
        doc_title=doc_meta.get("filename", "Document"),
        claims=claims,
        citations=citations,
        results=results
    )

    st.plotly_chart(fig, use_container_width=True)

    st.markdown("""
    **Network Interpretation Guide:**
    - 🟢 **Teal Diamonds:** Verified claims directly supported by retrieved evidence passages.
    - 🟡 **Gold Diamonds:** Partially supported claims or scope differences.
    - 🔴 **Red Diamonds:** Unsupported claims or quantitative contradictions.
    - 🟣 **Purple Diamonds:** Contradictory trial outcomes detected across independent studies.
    - ⚪ **Muted Grey Diamonds:** Insufficient evidence or unconfirmed methodology in open abstracts.
    - 🟦 **Blue Squares:** Genuine external peer-reviewed research papers (Crossref registry verified).
    - 🟧 **Orange Squares:** Citation fraud alert (DOI Not Found, Retracted, or Metadata Mismatch).
    """)


# ==============================================================================
# 7. HUMAN REVIEW & AUDIT TRAIL
# ==============================================================================
elif current_page == "Human Review":
    st.markdown(theme.render_hero(
        "Human Review & Verification Audit Station",
        "Auditor Station",
        "Inspect autonomous AI verdicts, record formal human review decisions, override verdicts with specialist reasoning, "
        "and maintain an immutable audit trail."
    ), unsafe_allow_html=True)

    if not doc_data:
        st.warning("No document currently loaded. Please start a verification in 'New Verification' or load a past run.")
        st.stop()

    results = doc_data.get("results", [])
    claims_dict = {c["claim_id"]: c for c in doc_data.get("claims", [])}
    doc_id = doc_data["document"]["id"]

    # Review status stats
    reviewed_count = sum(1 for r in results if r.get("review_action") in ("accept", "override", "comment"))
    pending_count = len(results) - reviewed_count

    rc1, rc2, rc3 = st.columns(3)
    rc1.markdown(theme.render_kpi_card("Total Claims", len(results), "Under Audit", "#0B1220"), unsafe_allow_html=True)
    rc2.markdown(theme.render_kpi_card("Human Reviewed", reviewed_count, "Audit Actions Recorded", "#14B8A6"), unsafe_allow_html=True)
    rc3.markdown(theme.render_kpi_card("Pending Review", pending_count, "Awaiting Human Sign-off", "#D6B56D"), unsafe_allow_html=True)

    st.markdown("<br/>", unsafe_allow_html=True)

    # Review interactive card
    claim_options = [f"{r['claim_id']} - {(claims_dict.get(r['claim_id'], {}).get('claim') or '')[:70]}..." for r in results]
    selected_option = st.selectbox("Select Claim to Review / Override", claim_options)
    selected_cid = selected_option.split(" - ")[0] if selected_option else (results[0]["claim_id"] if results else "")

    target_r = next((r for r in results if r["claim_id"] == selected_cid), results[0] if results else None)

    if target_r:
        c_info = claims_dict.get(target_r["claim_id"], {})
        claim_text = c_info.get("claim_text") or c_info.get("claim", "")
        orig_v = config.normalize_verdict(target_r.get("verdict", "NEEDS_REVIEW"))
        curr_v = config.normalize_verdict(target_r.get("final_verdict") or orig_v)

        st.markdown(f"### Auditing Claim {target_r['claim_id']}")
        st.markdown(f"**Claim Statement:** \"{claim_text}\"")
        st.markdown(f"**Autonomous AI Verdict:** {utils.render_verdict_badge(orig_v)} &nbsp; (Confidence: {int(float(target_r.get('confidence_score', 0.5)) * 100)}%)", unsafe_allow_html=True)
        st.markdown(f"**AI Reasoning:** {target_r.get('explanation')}")

        ev_q = target_r.get("evidence_quote") or (target_r.get("evidence") or {}).get("quote", "")
        if ev_q:
            st.markdown(f"**Retrieved Evidence Quote:** &ldquo;{ev_q}&rdquo;")

        st.markdown("---")
        st.markdown("#### Reviewer Decision")

        hr_action = st.radio(
            "Select Review Action",
            ["Accept AI Verdict", "Override Verdict", "Flag Questionable Evidence", "Add Reviewer Comment"],
            horizontal=True
        )

        new_v = orig_v
        if hr_action == "Override Verdict":
            verdict_choices = list(config.VERDICTS.keys())[:5]
            new_v = st.selectbox("Select New Verdict", verdict_choices, index=verdict_choices.index(curr_v) if curr_v in verdict_choices else 0)

        reviewer_name = st.text_input("Reviewer Name / Title", value="Lead Academic Auditor")
        reviewer_comment = st.text_area("Reviewer Audit Notes / Justification", placeholder="Detail the empirical rationale for this review decision...")

        if st.button("💾 Submit & Save Review Decision", type="primary", use_container_width=True):
            act_type = "accept" if hr_action == "Accept AI Verdict" else ("override" if hr_action == "Override Verdict" else "comment")
            final_v = new_v if act_type == "override" else orig_v

            database.save_human_review(
                doc_id=doc_id,
                claim_id=target_r["claim_id"],
                action=act_type,
                original_verdict=orig_v,
                reviewed_verdict=final_v,
                comments=reviewer_comment,
                reviewer=reviewer_name
            )

            # Update session state in-memory
            target_r["review_action"] = act_type
            target_r["final_verdict"] = final_v
            target_r["review_comments"] = reviewer_comment

            st.success(f"Review decision recorded for {target_r['claim_id']}!")
            st.rerun()

    # Complete Audit Log Table
    st.markdown("<br/>", unsafe_allow_html=True)
    st.markdown("#### Complete Human Review Audit Trail")
    review_logs = database.get_all_reviews(doc_id)
    if review_logs:
        df_rev = pd.DataFrame(review_logs)
        st.dataframe(df_rev[["claim_id", "action", "original_verdict", "reviewed_verdict", "comments", "reviewer", "created_at"]], use_container_width=True)
    else:
        st.caption("No human review actions recorded yet for this document.")


# ==============================================================================
# 8. VERIFICATION HISTORY
# ==============================================================================
elif current_page == "Verification History":
    st.markdown(theme.render_hero(
        "Verification History & Session Archive",
        "Document Archive",
        "Browse past verification runs stored in the local SQLite database. "
        "Reopen past audits, inspect historical trust scores, and export deliverables."
    ), unsafe_allow_html=True)

    all_docs = database.list_documents()

    if not all_docs:
        st.info("No past verification sessions found in the database. Run your first audit in 'New Verification'!")
    else:
        st.markdown(f"**{len(all_docs)}** Document Analysis Session(s) Recorded:")

        for d in all_docs:
            d_id = d["id"]
            d_fname = d["filename"]
            d_score = d.get("trust_score", 0.0)
            d_grade = d.get("trust_grade", "Evaluated")
            d_claims = d.get("claims_count", 0)
            d_refs = d.get("references_count", 0)
            d_time = d.get("created_at", "Recently")

            with st.container():
                st.markdown(f"""
                <div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;padding:16px 20px;margin-bottom:12px;box-shadow:0 1px 4px rgba(0,0,0,0.03);display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;">
                    <div>
                        <div style="font-size:1.05rem;font-weight:700;color:#0B1220;">{d_fname}</div>
                        <div style="font-size:0.8rem;color:#64748B;margin-top:2px;">
                            <span>Format: <b>{d.get('file_type', 'TXT').upper()}</b></span> &bull; 
                            <span>Claims: <b>{d_claims}</b></span> &bull; 
                            <span>References: <b>{d_refs}</b></span> &bull; 
                            <span>Analyzed: {d_time}</span>
                        </div>
                    </div>
                    <div style="text-align:right;">
                        <span style="font-size:1.4rem;font-weight:800;color:#14B8A6;">{d_score}/100</span>
                        <div style="font-size:0.75rem;font-weight:600;color:#64748B;">{d_grade}</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                col_btn1, col_btn2 = st.columns([1, 4])
                with col_btn1:
                    if st.button("📂 Set as Active", key=f"load_hist_{d_id}", use_container_width=True):
                        loaded = database.get_document_run(d_id)
                        if loaded:
                            st.session_state.current_doc = loaded
                            st.session_state.selected_page = "Overview"
                            st.success(f"Active document set to: {d_fname}")
                            st.rerun()


# ==============================================================================
# 9. REPORT CENTER
# ==============================================================================
elif current_page == "Report Center":
    st.markdown(theme.render_hero(
        "Academic Verification Report Center",
        "Export & Archival",
        "Generate and download comprehensive scientific verification reports in PDF, HTML, JSON, and CSV format. "
        "All data originates from empirical verification records with full provenance."
    ), unsafe_allow_html=True)

    if not doc_data:
        st.warning("No document currently loaded. Please start a verification in 'New Verification' or load a past run.")
        st.stop()

    doc_meta = doc_data["document"]
    run_id = doc_meta.get("id", "run")

    st.markdown(f"### Deliverables for *{doc_meta.get('filename')}*")

    rep_col1, rep_col2, rep_col3, rep_col4 = st.columns(4)

    with rep_col1:
        st.markdown("""
        **📄 Executive PDF Report**  
        Official formatted ReportLab document with KPI tiles, Trust Score badge, and claim evidence cards.
        """)
        with st.spinner("Compiling PDF..."):
            pdf_bytes = report_generator.generate_pdf_report(doc_data)
        st.download_button(
            "⬇️ Download PDF Report",
            data=pdf_bytes,
            file_name=f"CiteVerify_{run_id}.pdf",
            mime="application/pdf",
            type="primary",
            use_container_width=True
        )

    with rep_col2:
        st.markdown("""
        **🌐 Standalone HTML Report**  
        Interactive web report styled with the Deep Navy / Teal palette and print-ready stylesheets.
        """)
        html_str = report_generator.generate_html_report(doc_data)
        st.download_button(
            "⬇️ Download HTML Report",
            data=html_str,
            file_name=f"CiteVerify_{run_id}.html",
            mime="text/html",
            use_container_width=True
        )

    with rep_col3:
        st.markdown("""
        **📊 Complete JSON Archive**  
        Structured JSON file containing full document text, parsed references, claims, evidence quotes, and audit history.
        """)
        json_str = report_generator.generate_json_report(doc_data)
        st.download_button(
            "⬇️ Download JSON Data",
            data=json_str,
            file_name=f"CiteVerify_{run_id}.json",
            mime="application/json",
            use_container_width=True
        )

    with rep_col4:
        st.markdown("""
        **📈 Spreadsheet CSV Export**  
        Flat tabular spreadsheet containing claims, verdicts, numerical check outcomes, and cited DOIs.
        """)
        csv_str = report_generator.generate_csv_report(doc_data)
        st.download_button(
            "⬇️ Download CSV Spreadsheet",
            data=csv_str,
            file_name=f"CiteVerify_{run_id}.csv",
            mime="text/csv",
            use_container_width=True
        )

    st.divider()

    # Human Review Audit Trail History
    st.markdown("### Human Review Audit Trail")
    review_logs = database.get_all_reviews(doc_meta["id"])
    if review_logs:
        df_rev = pd.DataFrame(review_logs)
        st.dataframe(df_rev[["claim_id", "action", "original_verdict", "reviewed_verdict", "comments", "reviewer", "created_at"]], use_container_width=True)
    else:
        st.caption("No human review actions recorded yet for this document.")


# ==============================================================================
# 10. SETTINGS & AI PROVIDER CONFIGURATION
# ==============================================================================
elif current_page == "Settings":
    st.markdown(theme.render_hero(
        "CiteVerify Settings & AI Provider Configuration",
        "System Configuration",
        "Configure AI provider credentials (Google Gemini, Groq, Offline), select model parameters, "
        "test live provider connections, and manage local SQLite caches."
    ), unsafe_allow_html=True)

    s_col1, s_col2 = st.columns(2)

    with s_col1:
        st.markdown("#### AI Inference Provider")
        prov_options = ["gemini", "groq", "offline"]
        curr_prov = config.get_active_provider()
        sel_prov = st.radio(
            "Active Provider",
            prov_options,
            index=prov_options.index(curr_prov) if curr_prov in prov_options else 0,
            format_func=lambda x: "Google Gemini" if x == "gemini" else ("Groq Cloud" if x == "groq" else "Offline / Rule-Based Engine"),
            horizontal=True
        )

        curr_key = config.get_active_api_key()
        masked_key = curr_key[:6] + "..." + curr_key[-4:] if len(curr_key) > 10 else ""
        new_key = st.text_input(
            f"{sel_prov.upper()} API Key",
            value=masked_key,
            type="password",
            help="Your API key is never exposed or logged. It is loaded strictly from environment secrets."
        )

        if sel_prov == "gemini":
            model_choices = ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"]
            curr_model = config.get_active_model()
            sel_model = st.selectbox("Gemini Model", model_choices, index=model_choices.index(curr_model) if curr_model in model_choices else 0)
        elif sel_prov == "groq":
            model_choices = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"]
            curr_model = config.get_active_model()
            sel_model = st.selectbox("Groq Model", model_choices, index=model_choices.index(curr_model) if curr_model in model_choices else 0)
        else:
            sel_model = "rule-engine"
            st.info("Offline rule-based engine operates entirely locally without API calls.")

        temp_val = st.slider("Temperature", min_value=0.0, max_value=1.0, value=config.DEFAULT_TEMPERATURE, step=0.05)

        col_save, col_test = st.columns(2)
        with col_save:
            if st.button("💾 Save AI Configuration", use_container_width=True):
                os.environ["LLM_PROVIDER"] = sel_prov
                config.LLM_PROVIDER = sel_prov
                if new_key and not new_key.startswith("...") and "..." not in new_key:
                    os.environ["LLM_API_KEY"] = new_key
                    config.LLM_API_KEY = new_key
                    if sel_prov == "gemini":
                        os.environ["GEMINI_API_KEY"] = new_key
                        config.GEMINI_API_KEY = new_key
                    elif sel_prov == "groq":
                        os.environ["GROQ_API_KEY"] = new_key
                os.environ["LLM_MODEL"] = sel_model
                config.LLM_MODEL = sel_model
                st.success("AI Configuration saved!")
                st.rerun()

        with col_test:
            if st.button("🧪 Test Connection", use_container_width=True):
                with st.spinner(f"Testing connectivity to {sel_prov.upper()}..."):
                    k_to_test = new_key if (new_key and not new_key.startswith("...") and "..." not in new_key) else curr_key
                    ok, msg = ai_provider.test_ai_connection(provider=sel_prov, api_key=k_to_test, model=sel_model)
                if ok:
                    st.success(f"✅ {msg}")
                else:
                    st.error(f"❌ {msg}")

    with s_col2:
        st.markdown("#### Scholarly Registries & Storage")
        st.text_input("Crossref & OpenAlex Contact Email", value=config.CONTACT_EMAIL, disabled=True)
        st.text_input("Database File Location", value=config.DB_PATH, disabled=True)

        st.markdown("#### Cache & Maintenance")
        try:
            conn = sqlite3.connect(config.DB_PATH)
            cache_rows = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='ai_cache'").fetchone()[0]
            cache_cnt = conn.execute("SELECT count(*) FROM ai_cache").fetchone()[0] if cache_rows else 0
            conn.close()
        except Exception:
            cache_cnt = 0

        st.caption(f"Cached LLM responses in SQLite: **{cache_cnt}** item(s)")
        if st.button("🗑️ Clear LLM Response Cache", use_container_width=True):
            try:
                conn = sqlite3.connect(config.DB_PATH)
                conn.execute("DELETE FROM ai_cache;")
                conn.commit()
                conn.close()
                st.success("AI response cache cleared!")
                st.rerun()
            except Exception as e:
                st.error(f"Error clearing cache: {e}")
