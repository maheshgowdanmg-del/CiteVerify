"""Streamlit renderers for the Insights and Source-recommender tabs.

``st`` is passed in (instead of imported) so the functions can be unit-tested with a fake Streamlit object.
"""
from __future__ import annotations

import pandas as pd

from src import insights, recommend


def _md_safe(text: str) -> str:
    return (text or "").replace("[", "(").replace("]", ")").replace("\n", " ")


def _tick(v):
    return "✅" if v is True else "❌" if v is False else "—"


def render_insights(st, run: dict, results: list, outdated_years: int = 10) -> None:
    """Trust score, five-label distribution, reference funnel, review queue and claim graph."""
    st.subheader("🛡️ Academic Trust Score")
    ts = insights.trust_score(run, results)
    c1, c2 = st.columns([1, 3])
    c1.metric("CiteVerify Trust Score", "n/a" if ts["score"] is None else f"{ts['score']}/100", ts["grade"])
    if ts["score"] is not None:
        c2.progress(min(1.0, ts["score"] / 100))
    c2.caption(ts["disclaimer"])
    with st.expander("How the score is calculated"):
        st.write(ts["methodology"])
        st.dataframe(pd.DataFrame(ts["components"]), use_container_width=True)

    st.subheader("Verdicts in the five official labels")
    dist = insights.official_distribution(results)
    st.bar_chart(pd.DataFrame({"claims": list(dist.values())}, index=list(dist.keys())))

    st.subheader("Reference health: exists ≠ matched ≠ supports")
    health = insights.reference_health(run, results, outdated_years=outdated_years)
    f = health["funnel"]
    cols = st.columns(5)
    cols[0].metric("References", f["references"])
    cols[1].metric("Verified to exist", f["exist"])
    cols[2].metric("Matched to a claim", f["matched_to_claim"])
    cols[3].metric("Support a claim", f["support_a_claim"])
    cols[4].metric("Retracted", f["retracted"])
    st.caption(health["note"] + f" Also: {f['not_found']} not found, {f['older']} older than {outdated_years} yr "
               f"(age alone is not a verdict), {f['duplicates']} duplicate(s), {f['unmatched']} unmatched, "
               f"{f['claims_missing_citation']} claim(s) with no citation.")
    if health["rows"]:
        df = pd.DataFrame(health["rows"]).drop(columns=["duplicate_of", "age"])
        df["exists"] = df["exists"].map(_tick)
        df["flags"] = df["flags"].map(lambda x: ", ".join(x))
        st.dataframe(df, use_container_width=True)

    st.subheader("Review priority queue")
    st.caption("Highest-risk claims first (verdict severity, low confidence, unmatched numbers, unverified quotes).")
    st.dataframe(pd.DataFrame(insights.review_priority(results)), use_container_width=True)

    st.subheader("Claim → source → evidence map")
    st.caption("Colour = verdict: green supported · amber partly supported · sky outdated · red unsupported · "
               "purple contradictory · grey other. Folder = source paper, note = evidence passage.")
    st.graphviz_chart(insights.claim_graph_dot(results), use_container_width=True)


def render_recommender(st, run: dict, results: list, status_names: dict, *, contact_email=None, s2_api_key=None,
                       outdated_years: int = 10, searcher=None) -> None:
    """Find papers worth reading for a claim (live search; ranked with transparent components)."""
    searcher = searcher or recommend.recommend_sources
    st.subheader("💡 Source recommender")
    st.caption("Suggests published papers to read for a claim, ranked by relevance, open-access availability, influence, "
               "recency and integrity. A recommendation is a candidate to check, never proof of support.")
    if not results:
        st.info("Run a verification first, or type any statement below.")

    run_id = run.get("run_id", "run")
    order = sorted(results, key=lambda r: -next((x["risk"] for x in insights.review_priority([r], 1)), 0))
    by_id = {str(r["claim_id"]): r for r in order}

    def fmt(cid):
        r = by_id[cid]
        name = status_names.get(r.get("final_status"), (r.get("final_status"),))[0]
        return f"{cid} · {name} · {(r.get('claim') or '')[:70]}"

    picked = st.selectbox("Claim to find sources for (weakest first)", list(by_id), format_func=fmt,
                          key=f"reco_sel_{run_id}") if by_id else None
    base = by_id[picked] if picked else {}
    text = st.text_area("Claim text (edit it or type your own statement)", value=base.get("claim", ""),
                        key=f"reco_txt_{run_id}_{picked}", height=100)
    c1, c2 = st.columns(2)
    top_k = c1.slider("How many sources", 3, 10, 5, key=f"reco_k_{run_id}")
    provs = c2.multiselect("Search providers", list(recommend.DEFAULT_PROVIDERS), default=list(recommend.DEFAULT_PROVIDERS),
                           key=f"reco_p_{run_id}")
    store = f"reco_result_{run_id}_{picked}"
    if st.button("🔎 Find sources", type="primary", key=f"reco_go_{run_id}"):
        with st.spinner("Searching OpenAlex, Semantic Scholar and Crossref..."):
            st.session_state[store] = searcher(
                text, top_k=top_k, providers=tuple(provs) or recommend.DEFAULT_PROVIDERS,
                cited_title=(base.get("source") or {}).get("title"), contact_email=contact_email,
                s2_api_key=s2_api_key, outdated_years=outdated_years)

    reco = st.session_state.get(store)
    if not reco:
        return
    st.caption(f"Search query: `{reco['query']}`")
    for name, status in reco["provider_status"].items():
        (st.warning if status.startswith("failed") else st.caption)(f"{name}: {status}")
    for note in reco["notes"]:
        st.info(note)
    if reco["candidates"]:
        st.warning(reco["disclaimer"])
    for c in reco["candidates"]:
        label = f"#{c['rank']} · {_md_safe(c['title'])} ({c['year'] or 'n.d.'}) — score {c['score']}"
        with st.expander(label, expanded=c["rank"] == 1):
            link = c["url"] or (f"https://doi.org/{c['doi']}" if c["doi"] else "")
            st.markdown(f"**[{_md_safe(c['title'])}]({link or '#'})**  \n{', '.join(c['authors']) or 'authors n/a'}"
                        f" · {c['venue'] or 'venue n/a'} · DOI: `{c['doi'] or 'n/a'}`")
            if c["pdf_url"]:
                st.markdown(f"[Open-access PDF]({c['pdf_url']})")
            st.markdown("**Why it was recommended**")
            for reason in c["reasons"]:
                st.markdown(f"- {reason}")
            if c["flags"]:
                st.markdown("**Flags:** " + " ".join(f"`{f}`" for f in c["flags"]))
            if c["abstract_excerpt"]:
                st.markdown(f"**Abstract excerpt (from provider metadata):** {c['abstract_excerpt']}")
            st.json(c["components"])
            st.caption(f"Found via: {', '.join(c['providers'])} · support verified: no")
    if reco["avoid"]:
        st.error("Do not cite as support (retracted):\n" + "\n".join(f"- {a['title']} ({a['year']})" for a in reco["avoid"]))
    if reco["candidates"]:
        st.download_button("⬇️ Recommendations (CSV)", recommend.recommendations_to_csv(reco),
                           f"citeverify_sources_{run_id}.csv", "text/csv", key=f"reco_dl_{run_id}")
