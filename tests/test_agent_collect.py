from chipseeker.agent_collect import merge_search_responses


def test_collection_deduplicates_doi_and_preserves_retrieval_sources():
    lite = {
        "mode": "lite",
        "query": "cryogenic InP LNA",
        "candidate_count": 100,
        "result_count": 1,
        "results": [
            {
                "rank": 2,
                "similarity": 0.81,
                "title": "A Cryogenic InP LNA",
                "year": "2024",
                "doi": "10.example/LNA",
                "abstract": "",
            }
        ],
    }
    keyword = {
        "mode": "keyword",
        "query": "InP,LNA",
        "candidate_count": 1000,
        "result_count": 1,
        "results": [
            {
                "rank": 5,
                "similarity": 1.0,
                "title": "A Cryogenic InP LNA",
                "year": "2024",
                "doi": "10.EXAMPLE/lna",
                "abstract": "Measured at 4 K.",
                "matched_fields": ["title", "abstract"],
            }
        ],
    }

    response = merge_search_responses([lite, keyword])

    assert response["raw_result_count"] == 2
    assert response["deduplicated_count"] == 1
    assert response["result_view"] == "standard"
    assert response["results"][0]["retrieval_count"] == 2
    assert response["results"][0]["abstract"] == "Measured at 4 K."
    assert {item["mode"] for item in response["results"][0]["retrievals"]} == {"lite", "keyword"}


def test_collection_keeps_different_year_publications_and_links_work_family():
    responses = [
        {
            "mode": "lite",
            "query": "query one",
            "result_view": "titles",
            "results": [{"title": "A Cryogenic InP LNA", "year": "2023", "doi": ""}],
        },
        {
            "mode": "keyword",
            "query": "InP,LNA",
            "result_view": "titles",
            "results": [{"title": "A Cryogenic InP LNA!", "year": "2024", "doi": "10.example/inp"}],
        },
    ]

    response = merge_search_responses(responses)

    assert response["deduplicated_count"] == 2
    assert response["result_view"] == "titles"
    assert len({paper["work_family_id"] for paper in response["results"]}) == 1


def test_collection_keeps_same_title_different_dois_as_publication_variants():
    responses = [
        {
            "mode": "lite",
            "query": "query",
            "results": [
                {
                    "title": "A Cryogenic LNA",
                    "year": "2024",
                    "doi": "10.example/conference",
                    "authors": ["A. Author"],
                }
            ],
        },
        {
            "mode": "keyword",
            "query": "LNA",
            "results": [
                {
                    "title": "A Cryogenic LNA",
                    "year": "2024",
                    "doi": "10.example/journal",
                    "authors": ["A. Author"],
                }
            ],
        },
    ]

    response = merge_search_responses(responses)

    assert response["deduplicated_count"] == 2
    assert len({paper["work_family_id"] for paper in response["results"]}) == 1


def test_collection_merges_missing_doi_with_same_title_and_year():
    responses = [
        {
            "mode": "lite",
            "query": "query",
            "results": [{"title": "A Cryogenic LNA", "year": "2024", "doi": ""}],
        },
        {
            "mode": "keyword",
            "query": "LNA",
            "results": [
                {"title": "A Cryogenic LNA!", "year": "2024", "doi": "10.example/paper"}
            ],
        },
    ]

    response = merge_search_responses(responses)

    assert response["deduplicated_count"] == 1
    assert response["results"][0]["doi"] == "10.example/paper"


def test_collection_counts_query_families_and_marginal_yield():
    paper = {"title": "A Cryogenic InP LNA", "year": "2024", "doi": "10.example/lna"}
    responses = [
        {"mode": "lite", "query": "cryogenic InP LNA", "results": [paper]},
        {"mode": "lite", "query": "InP cryogenic low-noise amplifier", "results": [paper]},
        {"mode": "keyword", "query": "InP,LNA", "results": [paper]},
    ]

    response = merge_search_responses(responses)

    assert response["query_family_count"] == 2
    assert [search["new_unique_count"] for search in response["searches"]] == [1, 0, 0]
    assert response["results"][0]["retrieval_count"] == 3
    assert response["results"][0]["retrieval_family_count"] == 2
    assert response["saturation"]["zero_yield_search_tail"] == 2


def test_collection_does_not_guess_when_missing_doi_matches_two_publications():
    responses = [
        {
            "mode": "keyword",
            "query": "first",
            "results": [
                {"title": "Shared Title", "year": "2024", "doi": "10.example/one"}
            ],
        },
        {
            "mode": "keyword",
            "query": "second",
            "results": [
                {"title": "Shared Title", "year": "2024", "doi": "10.example/two"}
            ],
        },
        {
            "mode": "lite",
            "query": "third",
            "results": [{"title": "Shared Title", "year": "2024", "doi": ""}],
        },
    ]

    response = merge_search_responses(responses)

    assert response["deduplicated_count"] == 3
    assert len({paper["work_family_id"] for paper in response["results"]}) == 1


def test_collection_uses_screened_work_family_yield_for_saturation():
    first = {"title": "Relevant LNA", "year": "2024", "doi": "10.example/relevant"}
    noise = {"title": "Unrelated paper", "year": "2025", "doi": "10.example/noise"}
    responses = [
        {"mode": "lite", "query": "direct", "query_family": "direct", "results": [first]},
        {"mode": "lite", "query": "broad one", "query_family": "broad", "results": [noise]},
        {"mode": "lite", "query": "broad two", "query_family": "container", "results": [noise]},
    ]
    decisions = {
        "doi:10.example/relevant": {**first, "screening_decision": "include"},
        "doi:10.example/noise": {**noise, "screening_decision": "exclude"},
    }

    response = merge_search_responses(responses, screening_decisions=decisions)

    assert response["saturation"]["basis"] == "retained_work_families"
    assert response["searches"][0]["new_retained_family_count"] == 1
    assert response["searches"][1]["new_retained_family_count"] == 0
    assert response["screening"]["retained_count"] == 1


def test_collection_preserves_success_when_another_query_fails():
    responses = [
        {
            "mode": "pro",
            "query": "ambiguous",
            "query_id": "pro-one",
            "query_role": "rerank",
            "status": "failed",
            "error": "connection error",
            "results": [],
        },
        {
            "mode": "lite",
            "query": "direct",
            "query_id": "lite-one",
            "query_role": "standalone_lna",
            "coverage": {"technology": ["InP"]},
            "results": [{"title": "Relevant", "year": "2024", "doi": "10.example/one"}],
        },
    ]

    response = merge_search_responses(responses)

    assert response["failed_search_count"] == 1
    assert response["deduplicated_count"] == 1
    assert response["query_coverage"]["technology"]["InP"] == ["lite-one"]
