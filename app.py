"""CiteVerify - Streamlit web app.  Run with:  streamlit run app.py"""
import html
import re
from pathlib import Path

import pandas as pd
import streamlit as stgit --version

from src import config, report, storage
from src.extract import extract_text
from src.pipeline import run_pipeline
from src.verdict import STATUS

st.set_page_config(page_title="CiteVerify", page_icon="🔎", layout="wide")
SAMPLE = Path(__file__).parent / "data" / "sample" / "sample_paper.txt"


def badge(status):
    name, color = STATUS.get(status, (status, "#555"))
    return f"<span style='background:{color};color:#fff;padding:2px 10px;border-radius:12px;font-size:0.85em'>{name}</span>"


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

st.header("CiteVerify - does the cited paper really support the claim?")

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
    st.info("Upload a document (or click **Use sample document**) and press **Verify claims**.")
    st.stop()

reviews = storage.get_reviews(run["run_id"])
results = report.apply_reviews(run["results"], reviews)
s = run["summary"]

tabs = st.tabs(["📊 Overview", "🧾 Claim-by-claim", "⚠️ Needs human review", "📚 References", "🕘 Review history", "⬇️ Export"])

# ---------------- overview ----------------
with tabs[0]:
    m = st.columns(5)
    m[0].metric("Findings", s["total_findings"])
    m[1].metric("Needs review", s["needs_review"])
    m[2].metric("Avg confidence", s["avg_confidence"] if s["avg_confidence"] is not None else "n/a")
    m[3].metric("References resolved", f"{s['references_resolved']}/{s['references_total']}")
    m[4].metric("Mode", config.LLM_PROVIDER.title() if run["used_llm"] and config.llm_available() else "Rules")
    df = pd.DataFrame({"status": [STATUS.get(k, (k,))[0] for k in s["by_status"]], "count": list(s["by_status"].values())}).set_index("status")
    st.bar_chart(df)
    st.caption(f"Source access: {s['source_access']}  |  full text = best evidence; abstract-only results are flagged and get lower confidence.")


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


with tabs[1]:
    only = st.multiselect("Filter by status", list(STATUS), format_func=lambda k: STATUS[k][0])
    for r in results:
        if only and r["final_status"] not in only:
            continue
        with st.expander(f"{r['claim_id']} - {STATUS.get(r['final_status'], (r['final_status'],))[0]} - {r['claim'][:90]}..."):
            render(r, "all")

with tabs[2]:
    todo = [r for r in results if r["needs_review"] and r["review_decision"] == "pending"]
    st.write(f"{len(todo)} items waiting for a human decision.")
    for r in todo:
        with st.expander(f"{r['claim_id']} - {STATUS.get(r['final_status'], (r['final_status'],))[0]} - {r['claim'][:90]}..."):
            render(r, "todo")

with tabs[3]:
    rows = []
    for ref in run["references"]:
        src = run["sources"].get(str(ref["id"]), {})
        rows.append({"id": ref["id"], "reference": ref["raw"][:110], "found": src.get("found", "not cited"), "match": src.get("match_score"),
                     "year": src.get("year"), "access": src.get("access"), "retracted": src.get("retracted"), "doi": src.get("doi"), "via": ", ".join(src.get("providers", []))})
    st.dataframe(pd.DataFrame(rows), use_container_width=True)

with tabs[4]:
    st.dataframe(pd.DataFrame(reviews) if reviews else pd.DataFrame(columns=["result_id", "action", "new_status", "comment", "ts"]), use_container_width=True)

with tabs[5]:
    st.download_button("⬇️ PDF report", report.to_pdf(run, reviews), f"citeverify_{run['run_id']}.pdf", "application/pdf")
    st.download_button("⬇️ HTML report", report.to_html(run, reviews), f"citeverify_{run['run_id']}.html", "text/html")
    st.download_button("⬇️ JSON (full data + audit trail)", report.to_json(run, reviews), f"citeverify_{run['run_id']}.json", "application/json")
    st.download_button("⬇️ CSV (spreadsheet)", report.to_csv(run, reviews), f"citeverify_{run['run_id']}.csv", "text/csv")
