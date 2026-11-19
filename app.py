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
    gemini_active = config.is_gemini_configured()
    if gemini_active:
        st.markdown(
            f"<div style='background:#064E3B;color:#6EE7B7;padding:6px 12px;border-radius:8px;"
            f"font-size:0.75rem;font-weight:600;display:flex;align-items:center;gap:6px;margin-bottom:12px;'>"
            f"● Gemini AI Active ({config.GEMINI_MODEL})</div>",
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            "<div style='background:#451A03;color:#FDBA74;padding:6px 12px;border-radius:8px;"
            "font-size:0.75rem;font-weight:600;display:flex;align-items:center;gap:6px;margin-bottom:12px;'>"
            "● Offline Rule Engine (No API Key)</div>",
            unsafe_allow_html=True
        )

    st.markdown("<p style='font-size:0.75rem;font-weight:700;color:#94A3B8;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:6px;'>Navigation</p>", unsafe_allow_html=True)
    
    NAV_ITEMS = [
        "Overview",
        "Document Analysis",
        "Citation Fraud Detection",
        "Claim Verification",
        "Evidence Comparison",
        "Contradiction Intelligence",
        "Citation Trust Graph",
        "Academic Trust Score",
        "Research Recommendations",
        "Verification Reports",
        "Settings"
    ]

    selected_nav = st.radio(
        "Menu",
        NAV_ITEMS,
        index=NAV_ITEMS.index(st.session_state.selected_page) if st.session_state.selected_page in NAV_ITEMS else 0,
        label_visibility="collapsed"
    )
    st.session_state.selected_page = selected_nav

    st.divider()

    # Document History Quick Switcher
    st.markdown("<p style='font-size:0.75rem;font-weight:700;color:#94A3B8;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:6px;'>Past Analyses</p>", unsafe_allow_html=True)
    history_docs = database.list_documents()
    if history_docs:
        options = ["Select past document..."] + [f"{d['filename']} ({d['claims_count']} claims)" for d in history_docs]
        hist_choice = st.selectbox("Load History", options, label_visibility="collapsed")
        if hist_choice != "Select past document...":
            chosen_idx = options.index(hist_choice) - 1
            chosen_id = history_docs[chosen_idx]["id"]
            if st.button("📂 Load Selected Document", use_container_width=True):
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
        "CiteVerify AI operates as academic decision support. Automated findings must be confirmed by human peer review."
        "</div>",
        unsafe_allow_html=True
    )


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
                        <div style="font-size:1.05rem;font-weight:800;color:#0F172A;">{filename}</div>
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
                    st.session_state.selected_page = "Claim Verification"
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
            <div style="font-size:1.1rem;font-weight:700;color:#0F172A;">Browse or Drag & Drop File from File Explorer</div>
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
        "System Overview",
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
        <div style="background:#FFFFFF;border:1px solid #CBD5E1;border-left:5px solid #2563EB;border-radius:14px;padding:18px 24px;margin-bottom:18px;box-shadow:0 2px 10px rgba(15,23,42,0.04);">
            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;">
                <div>
                    <div style="display:flex;align-items:center;gap:8px;">
                        <span style="font-size:0.75rem;font-weight:700;color:#2563EB;text-transform:uppercase;letter-spacing:0.04em;">Active Document Under Audit</span>
                        <span class="cv-file-badge cv-badge-analyzed">ACTIVE</span>
                    </div>
                    <div style="font-size:1.25rem;font-weight:800;color:#0F172A;margin-top:2px;">{d_meta['filename']}</div>
                    <div style="font-size:0.82rem;color:#64748B;margin-top:4px;">
                        <span><b>{claims_cnt}</b> Claims Audited</span> &bull; 
                        <span><b>{cits_cnt}</b> References</span> &bull; 
                        <span><b>{d_meta.get('page_count', 1)}</b> Page(s)</span> &bull; 
                        <span>Analyzed: {d_meta.get('created_at', 'Recently')}</span>
                    </div>
                </div>
                <div style="text-align:right;">
                    <div style="font-size:0.78rem;color:#64748B;font-weight:600;">Academic Trust Score</div>
                    <div style="font-size:2rem;font-weight:800;color:#2563EB;line-height:1.1;">{score_val}/100</div>
                    <div style="font-size:0.82rem;font-weight:700;color:#1E40AF;">{grade_val}</div>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Quick Navigation Bar for Active Document
        nb1, nb2, nb3, nb4, nb5 = st.columns(5)
        with nb1:
            if st.button("📋 View Claim Audit", use_container_width=True):
                st.session_state.selected_page = "Claim Verification"
                st.rerun()
        with nb2:
            if st.button("🛡️ Citation Fraud", use_container_width=True):
                st.session_state.selected_page = "Citation Fraud Detection"
                st.rerun()
        with nb3:
            if st.button("🕸️ Citation Trust Graph", use_container_width=True):
                st.session_state.selected_page = "Citation Trust Graph"
                st.rerun()
        with nb4:
            if st.button("📥 Download PDF Report", use_container_width=True):
                st.session_state.selected_page = "Verification Reports"
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
        st.markdown(theme.render_kpi_card("Total Documents", stats["total_documents"], "Stored in SQLite", "#2563EB"), unsafe_allow_html=True)
    with k2:
        st.markdown(theme.render_kpi_card("Claims Audited", stats["total_claims"], f"{stats['supported_claims']} Supported ({supp_pct:.0f}%)", "#10B981"), unsafe_allow_html=True)
    with k3:
        st.markdown(theme.render_kpi_card("Integrity Flags", stats["invalid_or_mismatched_citations"], "Fabricated / Mismatched DOIs", "#EF4444"), unsafe_allow_html=True)
    with k4:
        st.markdown(theme.render_kpi_card("Evidence Coverage", f"{stats['evidence_coverage']}%", "Verbatim Quotations", "#8B5CF6"), unsafe_allow_html=True)
    with k5:
        st.markdown(theme.render_kpi_card("Avg Trust Score", f"{stats['avg_trust_score']}/100", "Overall Academic Integrity", "#F59E0B"), unsafe_allow_html=True)

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
                "NUMERICAL_MATCH": "#10B981",
                "NUMERICAL_MISMATCH": "#EF4444",
                "NUMERICAL_UNCONFIRMED": "#94A3B8"
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
# 2. DOCUMENT ANALYSIS & EXTRACTION
# ==============================================================================
elif current_page == "Document Analysis":
    st.markdown(theme.render_hero(
        "Document Upload & Text Extraction",
        "Document Processing",
        "Upload research manuscripts or student reports in PDF, DOCX, or TXT format. "
        "CiteVerify parses document structures, separates body claims from bibliographies, and detects citations."
    ), unsafe_allow_html=True)

    render_upload_section(context_key="doc_analysis_page", max_claims_default=25)


# ==============================================================================
# 3. CITATION FRAUD DETECTION
# ==============================================================================
elif current_page == "Citation Fraud Detection":
    st.markdown(theme.render_hero(
        "Citation Fraud & Legitimacy Engine",
        "Reference Integrity",
        "Evaluates whether cited publications genuinely exist in official scholarly registries (Crossref/OpenAlex), "
        "checks for metadata hijacking, author discrepancies, and flags retracted papers."
    ), unsafe_allow_html=True)

    if not doc_data:
        st.warning("No document currently loaded. Please upload a document in 'Document Analysis' or load a past run.")
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

    f1.markdown(theme.render_kpi_card("Total References", total_cit, "In Bibliography", "#2563EB"), unsafe_allow_html=True)
    f2.markdown(theme.render_kpi_card("Verified DOIs", verified_cit, "Crossref Confirmed", "#10B981"), unsafe_allow_html=True)
    f3.markdown(theme.render_kpi_card("Metadata Conflicts", mismatch_cit, "Title/Year Mismatch", "#F59E0B"), unsafe_allow_html=True)
    f4.markdown(theme.render_kpi_card("Fabricated / Retracted", notfound_cit + retracted_cit, "High Risk Entries", "#EF4444"), unsafe_allow_html=True)

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

        with st.expander(f"[{marker}] {title[:80]}... - {st_meta['label']}", expanded=(st_key in ("DOI_NOT_FOUND", "METADATA_MISMATCH", "POSSIBLY_RETRACTED"))):
            st.markdown(f"{badge_html} &nbsp; <b>DOI:</b> `{doi or 'None specified'}`", unsafe_allow_html=True)
            st.markdown(f"**Full Reference Text:** {raw}")
            if reason:
                st.markdown(f"**Audit Finding:** {reason}")
            if url:
                st.markdown(f"**Official Source Record:** [{url}]({url})")
            if c.get("retracted"):
                st.error("🚨 CRITICAL WARNING: This paper has been flagged as retracted or subject to formal concern!")


# ==============================================================================
# 4. CLAIM VERIFICATION (CLAIM-BY-CLAIM & HUMAN REVIEW)
# ==============================================================================
elif current_page == "Claim Verification":
    st.markdown(theme.render_hero(
        "Scientific Claim Verification Engine",
        "Evidence Corroboration",
        "Evaluates whether original cited research papers actually support the scientific claims made. "
        "Every claim includes verbatim evidence passages, confidence estimation, and human-in-the-loop review controls."
    ), unsafe_allow_html=True)

    if not doc_data:
        st.warning("No document currently loaded. Please upload a document in 'Document Analysis' or load a past run.")
        st.stop()

    results = doc_data.get("results", [])
    claims = doc_data.get("claims", [])
    claims_dict = {c["claim_id"]: c for c in claims}
    doc_id = doc_data["document"]["id"]

    # Filter row
    cf1, cf2 = st.columns([2, 1])
    with cf1:
        selected_verdicts = st.multiselect(
            "Filter by AI / Human Verdict",
            options=list(config.VERDICTS.keys()),
            default=[],
            format_func=lambda x: f"{config.VERDICTS[x]['icon']} {config.VERDICTS[x]['label']}"
        )
    with cf2:
        only_needs_review = st.checkbox("Show only items requiring review", value=False)

    for idx, r in enumerate(results, 1):
        cid = r.get("claim_id", f"C{idx}")
        c_info = claims_dict.get(cid, {})
        claim_text = c_info.get("claim_text") or c_info.get("claim", "")
        citation_marker = c_info.get("citation_marker") or c_info.get("citation", "")
        v_current = r.get("final_verdict") or r.get("verdict", "NOT_ENOUGH_EVIDENCE")
        orig_v = r.get("verdict", "NOT_ENOUGH_EVIDENCE")
        action = r.get("review_action", "pending")

        if selected_verdicts and v_current not in selected_verdicts:
            continue
        if only_needs_review and not r.get("needs_review"):
            continue

        v_meta = config.VERDICTS.get(v_current, config.VERDICTS["NOT_ENOUGH_EVIDENCE"])
        badge_html = utils.render_verdict_badge(v_current)
        conf_pct = int(r.get("confidence_score", 0.5) * 100)

        ev_passage = r.get("evidence", {}).get("passage") or r.get("evidence_quote") or ""
        ev_quote = r.get("evidence", {}).get("quote") or r.get("evidence_quote") or ""
        highlighted_ev = utils.highlight_passage(ev_passage, ev_quote)

        with st.expander(f"{cid} - {v_meta['label']} - {claim_text[:85]}...", expanded=False):
            st.markdown(
                f"{badge_html} &nbsp; <b>🤖 Autonomous AI Verified</b> &bull; <b>Confidence:</b> {conf_pct}% ({r.get('confidence_label', 'High')})",
                unsafe_allow_html=True
            )
            st.markdown(f"**Scientific Claim:** {claim_text}")
            st.markdown(f"**Cited Marker:** `{citation_marker}` &nbsp;|&nbsp; **Cited Source:** *{r.get('source_title', 'Not specified')}* ({r.get('source_year', 'n.d.')})")
            if r.get("source_doi"):
                st.markdown(f"**Source DOI:** [`{r['source_doi']}`](https://doi.org/{r['source_doi']}) &nbsp;|&nbsp; **Authors:** {r.get('source_authors', 'n/a')}")
            
            st.markdown(f"**AI Verification Analysis:** {r.get('explanation')}")

            if highlighted_ev:
                st.markdown(
                    f"**Retrieved Source Evidence:**"
                    f"<div style='border-left:4px solid #2563EB;background:#F8FAFC;padding:10px 14px;border-radius:6px;margin:6px 0;font-size:0.9rem;line-height:1.5;'>"
                    f"{highlighted_ev}</div>",
                    unsafe_allow_html=True
                )

            if r.get("limitations"):
                st.caption(f"**Methodological Limitations:** {r['limitations']}")

            # Numerical Analysis summary
            nc = r.get("numeric_check") or {}
            if nc.get("verdict") == "NUMERICAL_MISMATCH":
                st.warning(f"⚠️ **Numerical Mismatch:** {nc.get('explanation')}")
            elif nc.get("verdict") == "NUMERICAL_MATCH":
                st.success(f"✅ **Numerical Verification:** {nc.get('explanation')}")

            # Optional Auditor Override
            with st.expander("🛠️ Auditor Override (Optional - Autonomous AI Verification Certified)", expanded=False):
                st.markdown("<p style='font-size:0.85rem;font-weight:700;color:#0F172A;margin-bottom:4px;'>Human Review & Audit Override</p>", unsafe_allow_html=True)
                hr_col1, hr_col2, hr_col3 = st.columns([1.5, 2, 1])

                with hr_col1:
                    hr_decision = st.radio(
                        "Decision",
                        ["Accept AI Verdict", "Override Verdict", "Add Comment"],
                        key=f"hr_act_{cid}",
                        horizontal=True
                    )
                with hr_col2:
                    new_verdict = None
                    if hr_decision == "Override Verdict":
                        new_verdict = st.selectbox(
                            "Select Overriding Verdict",
                            list(config.VERDICTS.keys()),
                            index=list(config.VERDICTS.keys()).index(v_current),
                            format_func=lambda x: f"{config.VERDICTS[x]['icon']} {config.VERDICTS[x]['label']}",
                            key=f"hr_ovr_{cid}"
                        )
                    hr_comment = st.text_input("Reviewer Notes / Feedback", value=r.get("review_comment", ""), key=f"hr_com_{cid}")
                with hr_col3:
                    st.markdown("<div style='height:24px;'></div>", unsafe_allow_html=True)
                    if st.button("💾 Save Review", key=f"hr_btn_{cid}", use_container_width=True):
                        act_type = "accept" if hr_decision == "Accept AI Verdict" else ("override" if hr_decision == "Override Verdict" else "comment")
                        database.add_human_review(
                            doc_id=doc_id,
                            claim_id=cid,
                            action=act_type,
                            original_verdict=orig_v,
                            reviewed_verdict=new_verdict,
                            comments=hr_comment,
                            reviewer="Lead Academic Auditor"
                        )
                        r["review_action"] = act_type
                        r["final_verdict"] = new_verdict if act_type == "override" and new_verdict else orig_v
                        r["review_comment"] = hr_comment
                        st.success("Review saved to database!")
                        st.rerun()

                st.caption(f"Status: **{action.upper()}** &bull; Autonomous AI Verdict: **{orig_v}**")


# ==============================================================================
# 5. EVIDENCE COMPARISON & NUMERICAL VERIFICATION
# ==============================================================================
elif current_page == "Evidence Comparison":
    st.markdown(theme.render_hero(
        "Side-by-Side Evidence & Numerical Comparison",
        "Direct Evidence Audit",
        "Inspect claims directly alongside the verbatim passages extracted from retrieved research papers. "
        "Automated numerical audits compare reported percentages, sample sizes, and benchmark metrics."
    ), unsafe_allow_html=True)

    if not doc_data:
        st.warning("No document currently loaded. Please upload a document in 'Document Analysis' or load a past run.")
        st.stop()

    results = doc_data.get("results", [])
    claims_dict = {c["claim_id"]: c for c in doc_data.get("claims", [])}

    for r in results:
        cid = r.get("claim_id")
        c_info = claims_dict.get(cid, {})
        claim_text = c_info.get("claim_text") or c_info.get("claim", "")
        ev_passage = r.get("evidence", {}).get("passage") or r.get("evidence_quote") or "No passage retrieved."
        ev_quote = r.get("evidence", {}).get("quote") or r.get("evidence_quote") or ""
        v = r.get("final_verdict") or r.get("verdict")
        v_meta = config.VERDICTS.get(v, config.VERDICTS["NOT_ENOUGH_EVIDENCE"])

        st.markdown(f"### Claim {cid} &nbsp; {utils.render_verdict_badge(v)}", unsafe_allow_html=True)
        
        col_c, col_e = st.columns(2)
        with col_c:
            st.markdown(
                f"<div style='background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;padding:16px;box-shadow:0 2px 6px rgba(0,0,0,0.02);'>"
                f"<span style='font-size:0.75rem;font-weight:700;color:#2563EB;text-transform:uppercase;'>Document Claim</span>"
                f"<p style='font-size:1.05rem;font-weight:600;color:#0F172A;margin:8px 0;'>\"{claim_text}\"</p>"
                f"<div style='font-size:0.8rem;color:#64748B;'>Citation: <code>{c_info.get('citation_marker') or c_info.get('citation')}</code></div>"
                f"</div>",
                unsafe_allow_html=True
            )

        with col_e:
            hl = utils.highlight_passage(ev_passage, ev_quote)
            st.markdown(
                f"<div style='background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;padding:16px;box-shadow:0 2px 6px rgba(0,0,0,0.02);'>"
                f"<span style='font-size:0.75rem;font-weight:700;color:#10B981;text-transform:uppercase;'>Retrieved Scholarly Evidence</span>"
                f"<p style='font-size:0.9rem;line-height:1.5;color:#334155;margin:8px 0;'>{hl}</p>"
                f"<div style='font-size:0.8rem;color:#64748B;'>Source: <i>{r.get('source_title', 'Unknown')}</i> ({r.get('source_year', 'n.d.')})</div>"
                f"</div>",
                unsafe_allow_html=True
            )

        # Numerical comparison box
        nc = r.get("numeric_check") or {}
        if nc.get("claim_numbers") or nc.get("evidence_numbers"):
            st.markdown(
                f"<div style='background:#F8FAFC;border:1px dashed #CBD5E1;border-radius:8px;padding:10px 14px;margin-top:8px;font-size:0.85rem;'>"
                f"<b>Quantitative Check:</b> {nc.get('explanation')}<br/>"
                f"Claim Numbers: <code>{nc.get('claim_numbers')}</code> &rarr; Evidence Numbers: <code>{nc.get('evidence_numbers')}</code>"
                f"</div>",
                unsafe_allow_html=True
            )
        st.divider()


# ==============================================================================
# 6. CONTRADICTION INTELLIGENCE
# ==============================================================================
elif current_page == "Contradiction Intelligence":
    st.markdown(theme.render_hero(
        "Contradiction & Consensus Intelligence",
        "Cross-Study Analysis",
        "Synthesizes scientific consensus across peer-reviewed literature, identifies opposing trials, "
        "and highlights methodological divergences and demographic scanner drifts."
    ), unsafe_allow_html=True)

    if not doc_data:
        st.warning("No document currently loaded. Please upload a document in 'Document Analysis' or load a past run.")
        st.stop()

    results = doc_data.get("results", [])
    claims_dict = {c["claim_id"]: c for c in doc_data.get("claims", [])}

    # Group claims by topic
    topics: Dict[str, List[Any]] = {}
    for r in results:
        cid = r.get("claim_id")
        topic = claims_dict.get(cid, {}).get("topic", "General Science")
        topics.setdefault(topic, []).append(r)

    for topic_name, topic_results in topics.items():
        st.markdown(f"### Subdomain: {topic_name}")
        
        # Check if topic has any contradictory results
        has_contr = any(r.get("final_verdict") in ("CONTRADICTORY", "REFUTED") for r in topic_results)
        
        status_color = "#8B5CF6" if has_contr else "#10B981"
        status_label = "Mixed / Divergent Literature Findings" if has_contr else "Consistent Empirical Literature"

        st.markdown(
            f"<div style='background:{status_color}10;border-left:4px solid {status_color};padding:12px 16px;border-radius:8px;margin-bottom:14px;'>"
            f"<b>Consensus Assessment:</b> {status_label}<br/>"
            f"<span style='font-size:0.88rem;color:#475569;'>Auditing {len(topic_results)} empirical statement(s) and associated peer-reviewed benchmarks in this subdomain.</span>"
            f"</div>",
            unsafe_allow_html=True
        )

        for r in topic_results:
            cid = r.get("claim_id")
            c_text = claims_dict.get(cid, {}).get("claim_text") or claims_dict.get(cid, {}).get("claim", "")
            notes = r.get("contradiction_notes") or r.get("explanation", "")
            with st.expander(f"{cid} - {c_text[:75]}..."):
                st.markdown(f"**Claim Statement:** {c_text}")
                st.markdown(f"**Literature Findings & Synthesis:** {notes}")
                if r.get("limitations"):
                    st.info(f"**Reported Study Limitations:** {r['limitations']}")

        st.divider()


# ==============================================================================
# 7. CITATION TRUST GRAPH
# ==============================================================================
elif current_page == "Citation Trust Graph":
    st.markdown(theme.render_hero(
        "Interactive Citation Trust Graph",
        "Network Visualization",
        "Visualizes relationships between audited documents, scientific claims, and external peer-reviewed publications. "
        "Nodes are color-coded by verified support, contradictions, or citation fraud alerts."
    ), unsafe_allow_html=True)

    if not doc_data:
        st.warning("No document currently loaded. Please upload a document in 'Document Analysis' or load a past run.")
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
    **Graph Interpretation Guide:**
    - 🟢 **Green Diamonds:** Verified citations with corroborating evidence quotes.
    - 🔴 **Red Diamonds:** Contradicted or refuted claims (or numerical mismatches).
    - 🟡 **Yellow/Amber Diamonds:** Insufficient or partial evidence in open indexes.
    - 🟦 **Blue Squares:** Genuine external peer-reviewed research papers (Crossref verified).
    - 🟧 **Orange Squares:** Citation fraud alert (DOI Not Found, Retracted, or Metadata Mismatch).
    """)


# ==============================================================================
# 8. ACADEMIC TRUST SCORE
# ==============================================================================
elif current_page == "Academic Trust Score":
    st.markdown(theme.render_hero(
        "CiteVerify Academic Trust Score",
        "Integrity Metrics",
        "A transparent, mathematically derived 0-100 assessment calculated across claim corroboration, "
        "citation resolution, verbatim evidence coverage, and fraud penalties."
    ), unsafe_allow_html=True)

    if not doc_data:
        st.warning("No document currently loaded. Please upload a document in 'Document Analysis' or load a past run.")
        st.stop()

    claims = doc_data.get("claims", [])
    citations = doc_data.get("citations", [])
    results = doc_data.get("results", [])

    t_data = trust_score.calculate_academic_trust_score(claims, citations, results)
    score = t_data["score"]
    grade = t_data["grade"]
    grade_color = t_data["grade_color"]

    # Gauge & Score Hero
    sc_col1, sc_col2 = st.columns([1, 2])
    with sc_col1:
        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number",
            value=score,
            domain={'x': [0, 1], 'y': [0, 1]},
            title={'text': "Document Score", 'font': {'size': 16, 'color': "#0F172A"}},
            number={'suffix': "/100", 'font': {'size': 26, 'color': grade_color}},
            gauge={
                'axis': {'range': [0, 100], 'tickwidth': 1, 'tickcolor': "#CBD5E1"},
                'bar': {'color': grade_color},
                'bgcolor': "#FFFFFF",
                'borderwidth': 1,
                'bordercolor': "#E2E8F0",
                'steps': [
                    {'range': [0, 40], 'color': '#FEE2E2'},
                    {'range': [40, 60], 'color': '#FFEDD5'},
                    {'range': [60, 80], 'color': '#FEF3C7'},
                    {'range': [80, 100], 'color': '#DCFCE7'}
                ],
            }
        ))
        fig_gauge.update_layout(height=260, margin=dict(t=30, b=10, l=20, r=20), paper_bgcolor="#FFFFFF")
        st.plotly_chart(fig_gauge, use_container_width=True)

    with sc_col2:
        st.markdown(f"""
        <div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:14px;padding:22px;box-shadow:0 2px 8px rgba(0,0,0,0.03);">
            <span style="font-size:0.8rem;font-weight:700;color:{grade_color};text-transform:uppercase;letter-spacing:0.04em;">Classification</span>
            <div style="font-size:1.6rem;font-weight:800;color:#0F172A;margin:4px 0 10px;">{grade}</div>
            <p style="color:#64748B;font-size:0.9rem;line-height:1.5;">{t_data['explanation']}</p>
        </div>
        """, unsafe_allow_html=True)

    # Component Breakdown Table
    st.markdown("#### Mathematical Component Breakdown")
    comps_df = pd.DataFrame(t_data["components"])
    comps_df = comps_df.rename(columns={
        "name": "Component",
        "weight": "Weight",
        "score": "Score (0-100)",
        "details": "Evaluation Detail"
    })
    st.dataframe(comps_df, use_container_width=True)

    # Penalties
    if t_data["penalties_applied"]:
        st.markdown("#### Integrity Deductions & Penalties")
        for p in t_data["penalties_applied"]:
            st.error(f"⚠️ {p}")
    else:
        st.success("🛡️ No integrity deductions applied. Zero retractions or fabricated DOIs detected.")


# ==============================================================================
# 9. RESEARCH RECOMMENDATIONS
# ==============================================================================
elif current_page == "Research Recommendations":
    st.markdown(theme.render_hero(
        "Authoritative Research Recommender",
        "Literature Recommendations",
        "For scientific claims flagged as unsupported, outdated, or lacking evidence, CiteVerify queries "
        "OpenAlex and Semantic Scholar to recommend reputable, peer-reviewed alternative publications."
    ), unsafe_allow_html=True)

    if not doc_data:
        st.warning("No document currently loaded. Please upload a document in 'Document Analysis' or load a past run.")
        st.stop()

    results = doc_data.get("results", [])
    claims_dict = {c["claim_id"]: c for c in doc_data.get("claims", [])}

    unsupported_items = [r for r in results if r.get("final_verdict") in ("NOT_ENOUGH_EVIDENCE", "REFUTED", "PARTIALLY_SUPPORTED")]

    if not unsupported_items:
        st.success("🎉 All scientific claims in this document are well-corroborated! No replacement recommendations needed.")
    else:
        st.write(f"Displaying curated recommendations for **{len(unsupported_items)}** claim(s) requiring stronger literature support:")

        for r in unsupported_items:
            cid = r.get("claim_id")
            c_text = claims_dict.get(cid, {}).get("claim_text") or claims_dict.get(cid, {}).get("claim", "")
            topic = claims_dict.get(cid, {}).get("topic", "General Science")

            st.markdown(f"#### For Claim {cid}: *\"{c_text[:90]}...\"*")
            st.caption(f"Current Status: **{r.get('final_verdict')}** &bull; Topic: **{topic}**")

            # Query OpenAlex for relevant alternative literature
            with st.spinner(f"Querying scholarly registries for alternative papers on {topic}..."):
                candidates = research_retriever.search_openalex(f"{topic} {c_text[:50]}", limit=3)

            if candidates:
                for cand in candidates:
                    doi_str = cand.get("doi", "")
                    url_str = cand.get("url") or (f"https://doi.org/{doi_str}" if doi_str else "")
                    authors_str = ", ".join(cand.get("authors") or [])
                    st.markdown(
                        f"<div style='background:#FFFFFF;border:1px solid #E2E8F0;border-left:4px solid #2563EB;border-radius:8px;padding:12px 16px;margin:8px 0;'>"
                        f"<div style='font-size:0.95rem;font-weight:700;color:#0F172A;'><a href='{url_str}' target='_blank'>{cand.get('title')}</a></div>"
                        f"<div style='font-size:0.8rem;color:#64748B;'>Authors: {authors_str or 'n/a'} &bull; Year: {cand.get('year')} &bull; Venue: {cand.get('journal') or 'Scholarly Journal'}</div>"
                        f"<div style='font-size:0.8rem;color:#475569;margin-top:4px;'><b>DOI:</b> <code>{doi_str or 'None'}</code></div>"
                        f"<p style='font-size:0.85rem;color:#334155;margin-top:6px;'>{cand.get('abstract', '')[:250]}...</p>"
                        f"</div>",
                        unsafe_allow_html=True
                    )
            else:
                st.caption("No additional recommendations found.")
            st.divider()


# ==============================================================================
# 10. VERIFICATION REPORTS & EXPORTS
# ==============================================================================
elif current_page == "Verification Reports":
    st.markdown(theme.render_hero(
        "Verification Reports & Audit Export",
        "Export & Archival",
        "Export comprehensive academic audit reports in PDF, JSON, and CSV format. "
        "Includes claim verification outcomes, verbatim evidence quotes, citation health, and human review logs."
    ), unsafe_allow_html=True)

    if not doc_data:
        st.warning("No document currently loaded. Please upload a document in 'Document Analysis' or load a past run.")
        st.stop()

    doc_meta = doc_data["document"]
    run_id = doc_meta.get("id", "run")

    st.markdown("### Download Verification Deliverables")

    rep_col1, rep_col2, rep_col3 = st.columns(3)

    with rep_col1:
        st.markdown("""
        **📄 Executive PDF Report**  
        Official formatted audit report generated with ReportLab, including KPI summary, Trust Score badge, and claim evidence cards.
        """)
        with st.spinner("Generating PDF report..."):
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

    with rep_col3:
        st.markdown("""
        **📈 Spreadsheet CSV Export**  
        Flat tabular spreadsheet containing claims, verdicts, numerical check outcomes, and cited DOIs for tabular analysis.
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
# 11. SETTINGS & API CONFIGURATION
# ==============================================================================
elif current_page == "Settings":
    st.markdown(theme.render_hero(
        "CiteVerify Settings & Configuration",
        "System Settings",
        "Configure Gemini AI credentials, select model parameters, manage local SQLite databases, "
        "and adjust scholarly API rate limits."
    ), unsafe_allow_html=True)

    s_col1, s_col2 = st.columns(2)

    with s_col1:
        st.markdown("#### Google Gemini AI Configuration")
        curr_key = os.getenv("GEMINI_API_KEY", "")
        masked_key = curr_key[:6] + "..." + curr_key[-4:] if len(curr_key) > 10 else ""

        new_key = st.text_input("Gemini API Key", value=masked_key, type="password", help="Get a free key from Google AI Studio (https://aistudio.google.com/)")

        model_choices = ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"]
        curr_model = config.GEMINI_MODEL
        sel_model = st.selectbox("Gemini Model", model_choices, index=model_choices.index(curr_model) if curr_model in model_choices else 0)

        if st.button("💾 Save AI Settings"):
            if new_key and not new_key.startswith("...") and "..." not in new_key:
                os.environ["GEMINI_API_KEY"] = new_key
                config.GEMINI_API_KEY = new_key
            os.environ["GEMINI_MODEL"] = sel_model
            config.GEMINI_MODEL = sel_model
            st.success("Gemini AI settings updated!")
            st.rerun()

    with s_col2:
        st.markdown("#### Scholarly Registries & Database")
        st.text_input("Crossref & OpenAlex Contact Email", value=config.CONTACT_EMAIL, disabled=True)
        st.text_input("Database File Location", value=config.DB_PATH, disabled=True)

        st.markdown("#### Maintenance")
        if st.button("🗑️ Reset Local Database & Clear Cache"):
            conn = database.get_connection()
            cur = conn.cursor()
            cur.execute("DELETE FROM human_reviews;")
            cur.execute("DELETE FROM verification_results;")
            cur.execute("DELETE FROM claims;")
            cur.execute("DELETE FROM citations;")
            cur.execute("DELETE FROM documents;")
            conn.commit()
            conn.close()
            st.session_state.current_doc = None
            st.success("Database cleared!")
            st.rerun()
