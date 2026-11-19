"""Offline tests for src/theme.py (HTML builders and the overview renderer)."""
from unittest.mock import MagicMock

from src import theme

try:
    from test_insights import RUN, RESULTS
except ImportError:
    from tests.test_insights import RUN, RESULTS


def _clean_markdown_html(s):
    assert "\n\n" not in s and not any(line.startswith("    ") for line in s.split("\n"))


def test_builders_escape_and_are_markdown_safe():
    h = theme.hero("Cite<b>", "eye", "sub & more", [("1", "<x>")])
    assert "<b>" not in h.replace("<b>1</b>", "") and "&lt;x&gt;" in h
    for html_ in (h, theme.kpi_grid([{"icon": "x", "value": 3, "label": "L", "hint": "h"}]),
                  theme.donut({"A": 1, "B": 3}, {"A": "#111", "B": "#222"}), theme.bars([("a", 1, "1")]),
                  theme.welcome_steps(), theme.column_chart([("a", 2), ("b", 0)]), theme.workflow_nav(2), theme.brand(),
                  theme.area_chart([(0.5, "#111", "t", "C1"), (0.9, "#222", "t", "C2")]), theme.attention_list(
                      [{"claim_id": "C1", "claim": "<x>", "status": "Unsupported", "risk": 0.9}])):
        _clean_markdown_html(html_)


def test_donut_percentages_and_empty():
    d = theme.donut({"A": 1, "B": 3}, {"A": "#111111", "B": "#222222"})
    assert "#111111 0.00% 25.00%" in d and "#222222 25.00% 100.00%" in d
    assert "#E2EDED 0% 100%" in theme.donut({"A": 0}, {})


def test_confidence_bins_cover_all_claims():
    bins = theme.confidence_bins(RESULTS)
    assert sum(n for _, n in bins) == len(RESULTS)


def test_render_overview_uses_real_numbers():
    st = MagicMock()
    st.columns.side_effect = lambda n, **kw: [MagicMock() for _ in range(n if isinstance(n, int) else len(n))]
    theme.render_overview(st, RUN, RESULTS, {"total_findings": 5, "needs_review": 4, "avg_confidence": 0.5,
                                             "references_resolved": 3, "references_total": 5, "source_access": "x"},
                          n_documents=2, mode="Gemini")
    first = st.markdown.call_args_list[0][0][0]
    assert 'Documents verified' in first and '>2<' in first and 'Claims analysed' in first


def test_area_chart_handles_empty_and_single_point():
    assert "No claims" in theme.area_chart([])
    assert "<svg" in theme.area_chart([(0.7, "#111", "t", "C1")])


def test_official_labels_include_possibly_outdated():
    from src import insights
    assert insights.official_label("possibly_outdated") == "Possibly Outdated"
    assert "Possibly Outdated" in insights.OFFICIAL_LABELS
