"""CiteVerify - Streamlit web app.  Run with:  streamlit run app.py"""
import html
import re
from pathlib import Path

import os

import pandas as pd
import streamlit as st

from src import config, report, storage, theme, ui_extras
from src.extract import extract_text
from src.pipeline import run_pipeline
from src.verdict import STATUS

st.set_page_config(page_title="CiteVerify", page_icon="🔎", layout="wide")
theme.inject(st)
SAMPLE = Path(__file__).parent / "data" / "sample" / "sample_paper.txt"


def badge(status):
    name, color = STATUS.get(status, (status, "#555"))
    return theme.pill(name, color)


def highlight(passage, quote):
    safe = html.escape(passage)
    if not quote:
        return safe
    words = [re.escape(html.escape(w)) for w in quote.split()]
    if not words:
        return safe
    return re.sub("(" + r"\s+".join(words) + ")", r"<mark>\1</mark>", safe, count=1, flags=re.I)


# ---------------- sidebar ----------------
with st.sidebar:
    st.title("🔎 CiteVerify")
    st.caption("Scientific claim & citation verification")
    llm_ready = config.llm_available()
    use_llm = st.toggle(f"Use free LLM ({config.LLM_PROVIDER}) for verdicts", value=llm_ready, disabled=not llm_ready)
    if not llm_ready:
        st.warning("No free LLM configured in .env (LLM_PROVIDER / LLM_API_KEY) - running in offline rule-based mode (lower confidence).")
    max_claims = st.slider("Max claims to check", 5, 80, 30)
    st.divider()
    st.subheader("History")
    runs = storage.list_runs()
    choice = st.selectbox("Open a past run", ["-"] + [f"{r[0]} | {r[1]}" for r in runs])
    if choice != "-" and st.button("Load run"):
        st.session_state.run = storage.load_run(choice.split(" | ")[0])
    st.divider()
    st.caption("⚠️ Automated findings are decision support, not final academic judgments. Every result is open to human review.")

st.markdown(theme.hero(
    "CiteVerify", "Scientific Intelligence. Academic Integrity.",
    "Verify scientific claims. Validate citations. Build trustworthy research - by checking whether the original paper really supports each statement.",
    [("1", "Extract claims"), ("2", "Map citations"), ("3", "Retrieve originals"), ("4", "Compare evidence"), ("5", "Verdict + report")]),
    unsafe_allow_html=True)

# ---------------- upload ----------------
c1, c2 = st.columns([3, 1])
up = c1.file_uploader("Upload a research paper or document (PDF, DOCX, TXT)", type=["pdf", "docx", "txt"])
use_sample = c2.button("Use sample document", use_container_width=True)

text, fname = None, None
if up is not None:
    text, fname = extract_text(up.getvalue(), up.name), up.name
elif use_sample or st.session_state.get("sample_loaded"):
    st.session_state.sample_loaded = True
    text, fname = SAMPLE.read_text(encoding="utf-8"), "sample_paper.txt"

if text:
    with st.expander("Extracted text preview"):
        st.text(text[:3000])
    if st.button("▶ Verify claims", type="primary"):
        bar = st.progress(0.0)
        run = run_pipeline(text, fname, use_llm=use_llm, max_claims=max_claims, progress=lambda f, m: bar.progress(min(f, 1.0), text=m))
        st.session_state.run = run
        bar.empty()

run = st.session_state.get("run")
if not run:
    st.markdown(theme.welcome_steps(), unsafe_allow_html=True)
    st.info("Upload a document (or click **Use sample document**) and press **Verify claims**.")
    st.stop()

reviews = storage.get_reviews(run["run_id"])
results = report.apply_reviews(run["results"], reviews)
s = run["summary"]

t_over, t_claims, t_review, t_insights, t_reco, t_refs, t_hist, t_export = st.tabs(
    ["📊 Overview", "🧾 Claim-by-claim", "⚠️ Needs human review", "🛡️ Insights", "💡 Source recommender", "📚 References", "🕘 Review history", "⬇️ Export"])

# ---------------- overview ----------------
with t_over:
    theme.render_overview(
        st, run, results, s, n_documents=len(runs),
        mode=config.LLM_PROVIDER.title() if run["used_llm"] and config.llm_available() else "Rules (offline)",
        outdated_years=int(getattr(config, "OUTDATED_YEARS", 10) or 10))


def render(r, key_prefix):
    ev = r.get("evidence")
    st.markdown(f"{badge(r['final_status'])} &nbsp; **Confidence: {r['confidence']['score']} ({r['confidence']['label']})** "
                f"{'&nbsp; 🔍 *needs human review*' if r['needs_review'] else ''}", unsafe_allow_html=True)
    st.markdown(f"**Claim:** {r['claim']}")
    st.markdown(f"**Citation:** {r['citation'] or '-'}")
    st.markdown(f"**Why:** {r['explanation']}")
    if ev:
        st.markdown(f"**Evidence** ({ev['section']}) - quote verified in source: {'✅' if ev['verified'] else '❌'}")
        st.markdown(f"<div style='border-left:4px solid #888;padding-left:10px'>{highlight(ev['passage'], ev.get('quote'))}</div>", unsafe_allow_html=True)
    src = r.get("source") or {}
    if src.get("title"):
        st.markdown(f"**Source trace:** [{src['title']}]({src.get('url') or '#'}) ({src.get('year')}) - access: `{src.get('access')}` - found via: {', '.join(src.get('providers') or [])}")
    if r["flags"]:
        st.markdown("**Flags:** " + " ".join(f"`{f}`" for f in r["flags"]))
    nc = r.get("numeric_check")
    if nc and nc["claim_numbers"]:
        st.markdown(f"**Numeric check:** claim numbers {nc['claim_numbers']} -> found {nc['matched']}, not found {nc['missing']}")
    if r["confidence"].get("components"):
        with st.expander("Confidence breakdown"):
            st.json(r["confidence"]["components"])
    with st.expander("Human review"):
        action = st.radio("Decision", ["accept", "override", "comment"], horizontal=True, key=f"a_{key_prefix}{r['result_id']}")
        new_status = ""
        if action == "override":
            new_status = st.selectbox("New status", list(STATUS), key=f"s_{key_prefix}{r['result_id']}")
        comment = st.text_input("Comment", key=f"c_{key_prefix}{r['result_id']}")
        if st.button("Save review", key=f"b_{key_prefix}{r['result_id']}"):
            storage.add_review(run["run_id"], r["result_id"], action, new_status, comment)
            st.rerun()
        st.caption(f"Current decision: {r['review_decision']}")


with t_claims:
    only = st.multiselect("Filter by status", list(STATUS), format_func=lambda k: STATUS[k][0])
    for r in results:
        if only and r["final_status"] not in only:
            continue
        with st.expander(f"{r['claim_id']} - {STATUS.get(r['final_status'], (r['final_status'],))[0]} - {r['claim'][:90]}..."):
            render(r, "all")

with t_review:
    todo = [r for r in results if r["needs_review"] and r["review_decision"] == "pending"]
    st.write(f"{len(todo)} items waiting for a human decision.")
    for r in todo:
        with st.expander(f"{r['claim_id']} - {STATUS.get(r['final_status'], (r['final_status'],))[0]} - {r['claim'][:90]}..."):
            render(r, "todo")

with t_insights:
    ui_extras.render_insights(st, run, results, outdated_years=int(getattr(config, "OUTDATED_YEARS", 10) or 10))

with t_reco:
    ui_extras.render_recommender(
        st, run, results, STATUS,
        contact_email=getattr(config, "CONTACT_EMAIL", None) or os.getenv("CONTACT_EMAIL"),
        s2_api_key=getattr(config, "SEMANTIC_SCHOLAR_API_KEY", None) or os.getenv("SEMANTIC_SCHOLAR_API_KEY"),
        outdated_years=int(getattr(config, "OUTDATED_YEARS", 10) or 10))

with t_refs:
    rows = []
    for ref in run["references"]:
        src = run["sources"].get(str(ref["id"]), {})
        rows.append({"id": ref["id"], "reference": ref["raw"][:110], "found": src.get("found", "not cited"), "match": src.get("match_score"),
                     "year": src.get("year"), "access": src.get("access"), "retracted": src.get("retracted"), "doi": src.get("doi"), "via": ", ".join(src.get("providers", []))})
    st.dataframe(pd.DataFrame(rows), use_container_width=True)

with t_hist:
    st.dataframe(pd.DataFrame(reviews) if reviews else pd.DataFrame(columns=["result_id", "action", "new_status", "comment", "ts"]), use_container_width=True)

with t_export:
    st.download_button("⬇️ PDF report", report.to_pdf(run, reviews), f"citeverify_{run['run_id']}.pdf", "application/pdf")
    st.download_button("⬇️ HTML report", report.to_html(run, reviews), f"citeverify_{run['run_id']}.html", "text/html")
    st.download_button("⬇️ JSON (full data + audit trail)", report.to_json(run, reviews), f"citeverify_{run['run_id']}.json", "application/json")
    st.download_button("⬇️ CSV (spreadsheet)", report.to_csv(run, reviews), f"citeverify_{run['run_id']}.csv", "text/csv")