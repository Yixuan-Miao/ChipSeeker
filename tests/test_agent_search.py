import chipseeker.agent_search as agent_search

from chipseeker.agent_search import (
    build_response,
    compact_paper,
    parse_year_range,
    run_filtered_lite_search,
    run_keyword_search,
    run_lite_search,
    run_lite_searches,
    run_pro_search,
)


class FakeSearcher:
    def __init__(self, *_args, **_kwargs):
        pass

    def search(self, query, top_k):
        assert query == "cryo LNA"
        assert top_k == 200
        return [
            {
                "similarity": 0.9,
                "paper": {
                    "title": "Cryogenic LNA",
                    "abstract": "A" * 300,
                    "year": "2024",
                    "venue": "IEEE Journal of Solid-State Circuits",
                    "doi": "10.example/one",
                    "authors": ["A. Author"],
                },
            },
            {
                "similarity": 0.8,
                "paper": {
                    "title": "Older LNA",
                    "abstract": "B",
                    "year": "2010",
                    "venue": "IEEE Journal of Solid-State Circuits",
                },
            },
        ]


class FakeBatchSearcher:
    def __init__(self):
        self.calls = []

    def search_many(self, queries, top_k):
        self.calls.append((list(queries), top_k))
        return [
            [
                {
                    "similarity": 0.9,
                    "paper": {"title": f"Result for {query}", "year": "2024"},
                }
            ]
            for query in queries
        ]


class FakeCandidateSearcher:
    def __init__(self):
        self.candidates = []

    def search_candidates_many(self, queries, candidate_papers, top_k):
        self.candidates = list(candidate_papers)
        return [
            [
                {"similarity": 0.8, "paper": paper}
                for paper in reversed(self.candidates[:top_k])
            ]
            for _query in queries
        ]


def test_parse_year_range():
    assert parse_year_range("2020:2024") == (2020, 2024)
    assert parse_year_range("2024") == (2024, 2024)


def test_lite_agent_search_is_compact_and_filters_years():
    response = run_lite_search(
        "cryo LNA",
        db_file="papers.json",
        embedding_model="test-model",
        embedding_api_key="",
        top_k=10,
        selected_years=(2020, 2026),
        abstract_chars=120,
        searcher_factory=FakeSearcher,
    )

    assert response["schema"] == "chipseeker-agent-search/v1"
    assert response["candidate_count"] == 2
    assert response["result_count"] == 1
    assert response["results"][0]["abstract"] == "A" * 120
    assert response["results"][0]["abstract_truncated"] is True


def test_compact_paper_preserves_llm_evidence():
    item = compact_paper({"title": "Paper", "abstract": "text", "llm_score": 90, "llm_reason": "direct"}, 0.8, 1, 100)
    assert item["llm_score"] == 90
    assert item["llm_reason"] == "direct"


def test_compact_paper_supports_title_first_without_abstract():
    item = compact_paper({"title": "Paper", "abstract": "long abstract"}, 0.8, 1, 0)

    assert item["abstract"] == ""
    assert item["abstract_truncated"] is True


def test_keyword_search_scans_full_corpus_and_reports_match_fields():
    papers = [
        {
            "title": "A Cryogenic InP HEMT Low-Noise Amplifier",
            "abstract": "The LNA covers C-band.",
            "authors": ["A. Researcher"],
            "year": "2024",
            "venue": "TMTT",
            "doi": "10.example/inp",
            "keywords": ["InP", "LNA"],
        },
        {
            "title": "A Cryogenic CMOS Receiver",
            "abstract": "A receiver is presented.",
            "authors": ["B. Researcher"],
            "year": "2024",
            "venue": "JSSC",
            "keywords": ["CMOS"],
        },
    ]

    response = run_keyword_search(
        "InP,LNA/low-noise amplifier",
        db_file="papers.json",
        top_k=0,
        fields="title,abstract,authors,keywords",
        abstract_chars=0,
        paper_loader=lambda _path: papers,
    )

    assert response["mode"] == "keyword"
    assert response["candidate_count"] == 2
    assert response["matched_count"] == 1
    assert response["result_count"] == 1
    assert response["results"][0]["abstract"] == ""
    assert "title" in response["results"][0]["matched_fields"]
    assert "keywords" in response["results"][0]["matched_fields"]


def test_title_result_view_omits_abstract_and_terms():
    response = run_keyword_search(
        "InP,LNA",
        db_file="papers.json",
        top_k=0,
        fields="title,keywords",
        result_view="titles",
        paper_loader=lambda _path: [
            {
                "title": "An InP LNA",
                "abstract": "Long detail.",
                "year": "2024",
                "keywords": ["InP", "LNA"],
                "ieee_terms": ["Cryogenics"],
            }
        ],
    )

    paper = response["results"][0]
    assert response["result_view"] == "titles"
    assert "abstract" not in paper
    assert "keywords" not in paper
    assert "ieee_terms" not in paper
    assert paper["title"] == "An InP LNA"


def test_lite_searches_batch_multiple_queries_once():
    searcher = FakeBatchSearcher()
    responses = run_lite_searches(
        ["cryogenic InP LNA", "InP qubit readout amplifier"],
        db_file="papers.json",
        embedding_model="test-model",
        embedding_api_key="",
        top_k=20,
        searcher=searcher,
    )

    assert len(searcher.calls) == 1
    assert len(responses) == 2
    assert responses[1]["results"][0]["title"] == "Result for InP qubit readout amplifier"


def test_filtered_lite_ranks_only_full_corpus_keyword_matches():
    papers = [
        {"title": "Cryogenic InP LNA", "year": "2024", "keywords": ["InP", "LNA"]},
        {"title": "Room Temperature InP LNA", "year": "2024", "keywords": ["InP", "LNA"]},
        {"title": "Cryogenic CMOS LNA", "year": "2024", "keywords": ["CMOS", "LNA"]},
    ]
    searcher = FakeCandidateSearcher()
    response = run_filtered_lite_search(
        "best cryogenic amplifier",
        db_file="papers.json",
        embedding_model="test-model",
        embedding_api_key="",
        top_k=10,
        fields="title,keywords",
        all_terms=["InP", "LNA"],
        paper_loader=lambda _path: papers,
        searcher=searcher,
    )

    assert response["mode"] == "filtered_lite"
    assert response["candidate_count"] == 2
    assert {paper["title"] for paper in searcher.candidates} == {
        "Cryogenic InP LNA",
        "Room Temperature InP LNA",
    }
    assert response["filters"]["structured"]["all_terms"] == ["InP", "LNA"]


def test_response_preserves_pro_item_llm_evidence():
    response = build_response(
        "query",
        "pro",
        "deepseek-v4-pro",
        (2020, 2026),
        [],
        "",
        [{"similarity": 0.8, "llm_score": 90, "llm_reason": "direct", "paper": {"title": "Paper"}}],
        1,
        100,
    )
    assert response["results"][0]["llm_score"] == 90
    assert response["results"][0]["llm_reason"] == "direct"


def test_pro_search_falls_back_and_reduces_rerank_batch(monkeypatch):
    calls = []

    def fake_once(query, **kwargs):
        calls.append((kwargs["llm_model"], kwargs["rerank_limit"]))
        if kwargs["llm_model"] == "deepseek-v4-pro":
            raise ConnectionError("primary unavailable")
        return {"mode": "pro", "query": query, "model": kwargs["llm_model"], "results": []}

    monkeypatch.setattr(agent_search, "_run_pro_search_once", fake_once)

    response = run_pro_search(
        "cryogenic LNA",
        db_file="papers.json",
        embedding_model="embedding",
        embedding_api_key="",
        llm_api_key="key",
        llm_base_url="https://example.invalid",
        llm_model="deepseek-v4-pro",
        fallback_models=["deepseek-v4-flash"],
        rerank_limit=40,
    )

    assert calls == [("deepseek-v4-pro", 40), ("deepseek-v4-flash", 25)]
    assert response["pro_fallback_used"] is True
    assert [item["status"] for item in response["pro_attempts"]] == ["failed", "completed"]
