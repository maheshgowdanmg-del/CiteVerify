"""Offline tests for src/insights.py using a hand-made run."""
from src import insights

RUN = {
    "summary": {"references_resolved": 3, "references_total": 5},
    "references": [{"id": 1, "raw": "Vaswani, A. (2017). Attention is all you need. arXiv:1706.03762"},
                   {"id": 2, "raw": "He, K. (2016). Deep residual learning. CVPR. 10.1109/CVPR.2016.90"},
                   {"id": 3, "raw": "Wakefield, A. (1998). Ileal-lymphoid hyperplasia. The Lancet"},
                   {"id": 4, "raw": "Smith, J. (2021). Quantum gravity fields and crop yield."},
                   {"id": 5, "raw": "He, K. (2016). Deep residual learning. CVPR. 10.1109/CVPR.2016.90"}],
    "sources": {"1": {"found": True, "year": 2017}, "2": {"found": True, "year": 2016},
                "3": {"found": True, "year": 1998, "retracted": True}, "4": {"found": False},
                "5": {"found": "not cited"}},
}
RESULTS = [
    {"claim_id": "C1", "claim": "Transformers reach 28.4 BLEU [1].", "citation": "[1]", "final_status": "supported",
     "confidence": {"score": 0.9}, "evidence": {"verified": True, "section": "Results"}, "source": {"title": "Attention is all you need", "year": 2017},
     "needs_review": False, "review_decision": "pending"},
    {"claim_id": "C2", "claim": "ResNets reach 45.0 BLEU [2].", "citation": "[2]", "final_status": "unsupported",
     "confidence": {"score": 0.4}, "evidence": {"verified": False, "section": "Abstract"}, "source": {"title": "Deep residual learning"},
     "numeric_check": {"claim_numbers": ["45.0"], "missing": ["45.0"]}, "needs_review": True, "review_decision": "pending"},
    {"claim_id": "C3", "claim": "MMR vaccine causes autism [3].", "citation": "[3]", "final_status": "contradictory",
     "confidence": {"score": 0.7}, "source": {"title": "Ileal-lymphoid hyperplasia"}, "needs_review": True, "review_decision": "pending"},
    {"claim_id": "C4", "claim": "Many projects fail.", "citation": None, "final_status": "missing_citation",
     "confidence": {"score": 0.2}, "source": None, "needs_review": True, "review_decision": "accepted"},
    {"claim_id": "C5", "claim": "Quantum fields boost crops [4].", "citation": "(Smith, 2021)", "final_status": "bad_reference",
     "confidence": {"score": 0.3}, "source": None, "needs_review": True, "review_decision": "pending"},
]


def test_classification_order_and_official_labels():
    assert insights.classify_status("unsupported") == "unsupported"
    assert insights.classify_status("Partly supported") == "partial"
    assert insights.classify_status("possibly_outdated") == "outdated"
    assert insights.official_label("cannot_verify") == "Needs Review"
    dist = insights.official_distribution(RESULTS)
    assert list(dist) == insights.OFFICIAL_LABELS and sum(dist.values()) == 5 and dist["Needs Review"] == 2


def test_trust_score_components_and_bounds():
    ts = insights.trust_score(RUN, RESULTS)
    assert 0 <= ts["score"] <= 100 and ts["grade"] in {"Strong", "Moderate", "Weak", "Poor"}
    assert {c["component"] for c in ts["components"]} == set(insights.TRUST_WEIGHTS)
    assert "not an officially recognised" in ts["disclaimer"]
    assert insights.trust_score({}, [])["score"] is None


def test_good_document_scores_higher_than_bad():
    good = [dict(RESULTS[0])] * 3
    assert insights.trust_score({"summary": {"references_resolved": 1, "references_total": 1}, "sources": {}}, good)["score"] > \
        insights.trust_score(RUN, RESULTS)["score"]


def test_reference_health_funnel():
    h = insights.reference_health(RUN, RESULTS, outdated_years=10, today_year=2026)
    rows = {r["id"]: r for r in h["rows"]}
    assert rows["1"]["exists"] is True and rows["1"]["supports"] == "yes"
    assert rows["2"]["exists"] is True and rows["2"]["supports"] == "no"   # exists + matched, but does NOT support
    assert rows["3"]["retracted"] and "retracted" in rows["3"]["flags"]
    assert rows["4"]["exists"] is False and rows["4"]["matched_claims"] == 1   # author-year citation mapped via text
    assert rows["5"]["exists"] is None and rows["5"]["duplicate_of"] == "2"
    f = h["funnel"]
    assert f["references"] == 5 and f["exist"] == 3 and f["support_a_claim"] == 1 and f["claims_missing_citation"] == 1


def test_citation_range_parsing():
    assert insights._ref_ids_from_citation("[1, 3-5]") == {"1", "3", "4", "5"}


def test_review_priority_orders_by_risk():
    q = insights.review_priority(RESULTS, top=5)
    assert {q[0]["claim_id"], q[1]["claim_id"]} == {"C2", "C3"}   # unsupported+number mismatch and contradictory lead
    assert q[-1]["claim_id"] == "C1"                     # supported + verified last
    assert all(0 <= r["risk"] <= 1 for r in q)


def test_graph_dot_is_valid_and_escaped():
    risky = [dict(RESULTS[0], claim='He said "hello" \\ world')]
    dot = insights.claim_graph_dot(RESULTS + risky)
    assert dot.startswith("digraph") and dot.rstrip().endswith("}")
    assert dot.count("{") == dot.count("}") and '\\"hello\\"' in dot and "#16a34a" in dot and "#7c3aed" in dot
