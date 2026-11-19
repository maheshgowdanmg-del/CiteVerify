from src.claims import extract_claims, find_citations, map_citation, parse_references, split_sentences
from src.extract import split_references
from src.matching import build_passages, numbers_in, rank_passages
from src.report import apply_reviews, to_csv, to_html
from src.verdict import compute_confidence, numeric_check, verify_quote

SAMPLE = open("data/sample/sample_paper.txt", encoding="utf-8").read()


def test_numeric_and_author_citations():
    assert find_citations("Foo bar [1, 3].")[0]["ids"] == [1, 3]
    assert find_citations("Range [2-4].")[0]["ids"] == [2, 3, 4]
    c = find_citations("It was shown (Smith & Lee, 2019; Wu et al., 2020).")
    assert [x["surname"] for x in c] == ["Smith", "Wu"]


def test_reference_parsing_and_mapping():
    body, refs_text = split_references(SAMPLE)
    refs = parse_references(refs_text)
    assert len(refs) == 5
    assert refs[0]["arxiv"] == "1706.03762"
    assert refs[1]["doi"] == "10.1109/CVPR.2016.90"
    assert refs[1]["year"] == 2016 and refs[1]["first_author"] == "He"
    assert "attention is all you need" in refs[0]["title"].lower()


def test_claim_extraction_finds_cited_and_uncited():
    body, refs_text = split_references(SAMPLE)
    claims = extract_claims(body, parse_references(refs_text))
    kinds = [c["kind"] for c in claims]
    assert kinds.count("cited") == 6 and kinds.count("uncited") == 1
    assert claims[0]["ref_ids"] == [1]


def test_unmatched_citation_detected():
    refs = parse_references("[1] Lee, A. (2020). A title about things and stuff. Journal.")
    claims = extract_claims("Models improved accuracy significantly in all tests [7].", refs)
    assert claims[0]["unmatched_citations"] == ["[7]"]


def test_numbers_ignore_years_and_handle_percent():
    assert numbers_in("In 2019 accuracy rose 30 percent and 1,200 samples") == [30.0, 1200.0]


def test_numeric_check_flags_wrong_number():
    p = [{"text": "The model reached 28.4 BLEU on the task."}]
    r = numeric_check("It reached 45.0 BLEU", p)
    assert r["missing"] == [45.0]


def test_quote_verification_blocks_hallucinated_quote():
    p = [{"text": "We report a 12% gain in a small pilot group of 20 students."}]
    assert verify_quote("a 12% gain in a small pilot group", p)[0] is True
    assert verify_quote("improved scores by thirty percent overall in all schools", p)[0] is False


def test_passage_ranking_prefers_relevant_text():
    src = {"abstract": "Cats sleep a lot during the day. The Transformer reached 28.4 BLEU on translation. Weather is nice today."}
    ranked = rank_passages("Transformer reached 28.4 BLEU", build_passages(src))
    assert "28.4" in ranked[0]["text"]


def test_confidence_capped_without_verified_quote():
    nc = {"claim_numbers": [], "matched": [], "missing": []}
    c = compute_confidence(0.9, "full_text", nc, 0.95, False, True, 1.0, True)
    assert c["score"] <= 0.4


def test_review_override_and_exports():
    run = {"run_id": "x", "filename": "f", "created": "now", "summary": {"total_findings": 1, "needs_review": 1, "avg_confidence": 0.5,
           "references_resolved": 0, "references_total": 1, "by_status": {"unsupported": 1}},
           "results": [{"result_id": "C1-1", "claim_id": "C1", "claim": "A <b>claim</b>", "citation": "ref", "status": "unsupported",
                        "explanation": "why", "evidence": None, "flags": [], "source": {}, "needs_review": True,
                        "confidence": {"score": 0.5, "label": "Medium"}}]}
    rv = [{"result_id": "C1-1", "action": "override", "new_status": "supported", "comment": "", "ts": "t"}]
    assert apply_reviews(run["results"], rv)[0]["final_status"] == "supported"
    assert "supported" in to_csv(run, rv) and "&lt;b&gt;" in to_html(run, rv)


def test_llm_judge_openai_compatible_call(monkeypatch=None):
    """The free-LLM client parses a JSON reply (HTTP mocked)."""
    import tempfile
    from pathlib import Path
    from unittest import mock

    from src import config, storage, verdict

    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": '```json\n{"verdict":"supported","explanation":"ok","evidence_passage_id":"P1","evidence_quote":"reached 28.4 BLEU on the task","certainty":0.9,"scope_issues":[]}\n```'}}]}

    with tempfile.TemporaryDirectory() as d, mock.patch.object(storage, "DB_PATH", Path(d) / "t.db"), \
         mock.patch.object(config, "LLM_BASE_URL", "http://x/v1"), mock.patch.object(config, "LLM_MODEL", "m"), \
         mock.patch("requests.post", return_value=R()), mock.patch("time.sleep"):
        out = verdict.llm_judge("claim", {"title": "t", "year": 2020, "access": "abstract"}, [{"id": "P1", "section": "Abstract", "text": "It reached 28.4 BLEU on the task."}])
    assert out["verdict"] == "supported"


def test_llm_availability_rules():
    from unittest import mock
    from src import config
    with mock.patch.object(config, "LLM_PROVIDER", "none"):
        assert config.llm_available() is False
    with mock.patch.object(config, "LLM_PROVIDER", "groq"), mock.patch.object(config, "LLM_API_KEY", ""):
        assert config.llm_available() is False
