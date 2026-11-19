"""Smoke tests for the Streamlit renderers using a fake `st` (no Streamlit install needed)."""
from unittest.mock import MagicMock

from src import recommend, ui_extras
try:
    from test_insights import RUN, RESULTS          # pytest rootdir/prepend mode
except ImportError:
    from tests.test_insights import RUN, RESULTS    # package mode


def make_st(button=False):
    st = MagicMock()
    st.session_state = {}
    def col():
        c = MagicMock()
        c.slider.return_value = 5
        c.multiselect.side_effect = lambda label, options, default=None, **kw: default
        return c
    st.columns.side_effect = lambda spec, **kw: [col() for _ in range(spec if isinstance(spec, int) else len(spec))]
    st.selectbox.side_effect = lambda label, options, **kw: options[0]
    st.text_area.side_effect = lambda label, value="", **kw: value
    st.slider.return_value = 5
    st.multiselect.side_effect = lambda label, options, default=None, **kw: default
    st.button.return_value = button
    return st


def test_render_insights_runs():
    st = make_st()
    ui_extras.render_insights(st, RUN, RESULTS)
    st.graphviz_chart.assert_called_once()
    assert st.dataframe.call_count >= 3 and st.bar_chart.called


def test_render_recommender_searches_and_stores():
    calls = []

    def fake_search(text, **kw):
        calls.append((text, kw))
        return {"ok": True, "query": "q", "provider_status": {"openalex": "ok (1 results)", "crossref": "failed: X"},
                "notes": [], "disclaimer": "d", "avoid": [{"title": "Bad", "year": 2000}],
                "candidates": [{"rank": 1, "title": "Paper [x]", "year": 2020, "score": 70.0, "authors": ["A"], "venue": "V",
                                "doi": "10.1/x", "url": "https://doi.org/10.1/x", "pdf_url": "", "reasons": ["r"], "flags": [],
                                "abstract_excerpt": "abs", "components": {"relevance": 1}, "providers": ["openalex"],
                                "citation_count": 3, "similarity": 0.3, "open_access": True, "support_verified": False}]}
    st = make_st(button=True)
    ui_extras.render_recommender(st, RUN, RESULTS, {"supported": ("Supported", "#0f0")}, searcher=fake_search)
    assert calls and calls[0][1]["top_k"] == 5
    assert st.session_state and st.download_button.called and st.warning.called and st.error.called
    # highest-risk claim (C2: unsupported, number not found, quote unverified) is offered first
    assert calls[0][0].startswith("ResNets")


def test_render_recommender_without_click_is_quiet():
    st = make_st(button=False)
    ui_extras.render_recommender(st, RUN, RESULTS, {})
    assert not st.download_button.called
