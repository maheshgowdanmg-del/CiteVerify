"""End-to-end test with network access mocked (works offline, no API keys needed)."""
import tempfile
from pathlib import Path
from unittest import mock

from src import pipeline, report, storage

SAMPLE = Path("data/sample/sample_paper.txt").read_text(encoding="utf-8")


def fake_resolve(ref):
    base = {"found": True, "title": ref["title"], "authors": [], "year": ref["year"], "doi": ref.get("doi"), "arxiv": ref.get("arxiv"),
            "url": "https://example.org/" + str(ref["id"]), "pages": [], "access": "abstract", "retracted": False, "cited_by": 1,
            "match_score": 0.9, "doi_valid": None, "providers": ["mock"], "notes": [], "abstract": ""}
    if ref["id"] == 1:
        base["abstract"] = "The Transformer achieved 28.4 BLEU on the WMT 2014 English-to-German translation task, improving over existing results."
    if ref["id"] == 4:
        base.update(retracted=True, abstract="We report a series of children with bowel disease and developmental regression in 1998.")
    if ref["id"] == 5:
        base.update(found=False, match_score=0.0, access="none")
    if ref["id"] in (2, 3):
        base["abstract"] = "Deep residual learning makes very deep networks easier to train and won first place in ILSVRC 2015 classification."
    return base


def test_full_pipeline_offline():
    with tempfile.TemporaryDirectory() as d:
        with mock.patch.object(storage, "DB_PATH", Path(d) / "t.db"), mock.patch.object(pipeline, "resolve_reference", fake_resolve):
            run = pipeline.run_pipeline(SAMPLE, "sample.txt", use_llm=False)
            by = {r["claim_id"]: r for r in run["results"]}
            assert by["C1"]["status"] in ("supported", "possibly_outdated")        # correct number
            assert "numeric_mismatch" in by["C2"]["flags"]                        # 45.0 BLEU not in evidence
            assert by["C5"]["status"] == "unsupported" and "retracted_source" in by["C5"]["flags"]
            assert by["C6"]["status"] == "bad_reference"                           # fabricated reference
            assert by["C7"]["status"] == "missing_citation"
            assert all(r["needs_review"] for r in run["results"] if r["status"] != "supported")
            storage.add_review(run["run_id"], by["C6"]["result_id"], "override", "unsupported", "checked manually")
            rv = storage.get_reviews(run["run_id"])
            assert report.apply_reviews(run["results"], rv)[0] is not None
            assert report.to_pdf(run, rv)[:4] == b"%PDF"
            assert storage.load_run(run["run_id"])["filename"] == "sample.txt"
