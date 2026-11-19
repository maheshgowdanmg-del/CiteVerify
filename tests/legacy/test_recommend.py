"""Offline tests for src/recommend.py (all network calls are faked)."""
from src import recommend


class FakeResp:
    def __init__(self, payload, status=200):
        self.payload, self.status = payload, status

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    def json(self):
        return self.payload


OPENALEX = {"results": [
    {"id": "https://openalex.org/W1", "display_name": "Attention is all you need", "publication_year": 2017,
     "doi": "https://doi.org/10.5555/attn", "cited_by_count": 100000, "is_retracted": False,
     "open_access": {"is_oa": True, "oa_url": "https://arxiv.org/pdf/1706.03762"},
     "primary_location": {"source": {"display_name": "NeurIPS"}}, "authorships": [{"author": {"display_name": "A. Vaswani"}}],
     "abstract_inverted_index": {"Transformer": [0], "models": [1], "reach": [2], "28.4": [3], "BLEU": [4], "on": [5],
                                 "machine": [6], "translation": [7]}},
    {"id": "https://openalex.org/W2", "display_name": "Retracted: transformer translation gains", "publication_year": 2019,
     "doi": "https://doi.org/10.1/ret", "cited_by_count": 5, "is_retracted": True, "open_access": {"is_oa": False},
     "primary_location": None, "authorships": [], "abstract_inverted_index": {"transformer": [0], "translation": [1]}},
    {"id": "https://openalex.org/W3", "display_name": "Gardening in spring", "publication_year": 2020, "doi": None,
     "cited_by_count": 1, "is_retracted": False, "open_access": {"is_oa": False}, "primary_location": None,
     "authorships": [], "abstract_inverted_index": {"tulips": [0], "bloom": [1]}},
]}
S2 = {"data": [{"title": "Attention Is All You Need", "year": 2017, "abstract": None, "citationCount": 120000,
                "externalIds": {"DOI": "10.5555/ATTN"}, "openAccessPdf": None, "url": "https://s2/x", "venue": "NIPS",
                "authors": [{"name": "Ashish Vaswani"}]}]}
CROSSREF = {"message": {"items": [{"DOI": "10.7/zzz", "title": ["Machine translation with transformer models"],
                                   "issued": {"date-parts": [[2021]]}, "is-referenced-by-count": 40,
                                   "abstract": "<jats:p>Transformer machine translation improves BLEU.</jats:p>"}]}}


def fake_get(url, params=None, headers=None, timeout=None):
    if "openalex" in url:
        return FakeResp(OPENALEX)
    if "semanticscholar" in url:
        return FakeResp(S2)
    return FakeResp(CROSSREF)


CLAIM = "Transformer models achieve 28.4 BLEU on machine translation tasks [1]."


def test_query_and_numbers():
    q = recommend.build_query(CLAIM)
    assert "transformer" in q and "translation" in q and "[1]" not in q
    assert recommend.extract_numbers("In 2019 accuracy rose to 45.0% (Smith, 2018)") == ["45.0"]


def test_ranking_merge_and_retraction():
    res = recommend.recommend_sources(CLAIM, http_get=fake_get, today_year=2026, use_cache=False,
                                      cited_title="Attention is all you need")
    assert res["ok"]
    titles = [c["title"] for c in res["candidates"]]
    assert titles[0].lower().startswith("attention")          # OpenAlex + S2 merged into one candidate
    assert titles.count("Attention is all you need") + titles.count("Attention Is All You Need") == 1
    top = res["candidates"][0]
    assert sorted(top["providers"]) == ["openalex", "semanticscholar"]
    assert "already_cited" in top["flags"] and top["support_verified"] is False
    assert any("28.4" in r for r in top["reasons"])
    assert all("Gardening" not in t for t in titles)           # irrelevant paper filtered out
    assert res["dropped_low_relevance"] >= 1
    assert res["avoid"] and "Retracted" in res["avoid"][0]["title"]
    assert all("Retracted" not in t for t in titles)           # retracted never recommended
    assert [c["rank"] for c in res["candidates"]] == list(range(1, len(titles) + 1))


def test_provider_failure_is_reported_not_hidden():
    def broken(url, **kw):
        if "openalex" in url:
            return FakeResp({}, status=429)
        return fake_get(url, **kw)
    res = recommend.recommend_sources(CLAIM, http_get=broken, use_cache=False, today_year=2026)
    assert res["provider_status"]["openalex"].startswith("failed")
    assert res["provider_status"]["crossref"].startswith("ok")
    assert res["ok"]


def test_all_providers_down_invents_nothing():
    def down(url, **kw):
        raise ConnectionError("offline")
    res = recommend.recommend_sources(CLAIM, http_get=down, use_cache=False)
    assert res["candidates"] == [] and not res["ok"] and res["notes"]


def test_short_claim_and_csv():
    assert recommend.recommend_sources("Too short", http_get=fake_get)["notes"]
    res = recommend.recommend_sources(CLAIM, http_get=fake_get, use_cache=False, today_year=2026)
    csv_text = recommend.recommendations_to_csv(res)
    assert csv_text.splitlines()[0].startswith("rank,score,title") and "10.5555/attn" in csv_text
