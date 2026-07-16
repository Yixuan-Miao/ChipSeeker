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


def test_collection_deduplicates_normalized_title_when_doi_metadata_differs():
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

    assert response["deduplicated_count"] == 1
    assert response["result_view"] == "titles"
    assert response["results"][0]["doi"] == "10.example/inp"
