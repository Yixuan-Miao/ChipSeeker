from chipseeker.agent_search import build_response, compact_paper, parse_year_range, run_lite_search


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
