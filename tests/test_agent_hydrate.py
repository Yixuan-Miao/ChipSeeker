from chipseeker.agent_hydrate import hydrate_candidates


def test_hydrate_candidates_matches_doi_and_preserves_retrieval_evidence():
    candidates = [
        {
            "title": "Short title",
            "doi": "10.EXAMPLE/ONE",
            "year": "2024",
            "retrieval_family_count": 3,
        }
    ]
    corpus = [
        {
            "title": "Full Corpus Title",
            "doi": "10.example/one",
            "year": "2024",
            "abstract": "Measured at 4 K from 4-8 GHz.",
        }
    ]

    response = hydrate_candidates(candidates, corpus)

    assert response["matched_count"] == 1
    assert response["results"][0]["abstract"] == "Measured at 4 K from 4-8 GHz."
    assert response["results"][0]["retrieval_family_count"] == 3
    assert response["results"][0]["hydration"]["matched_by"] == "doi"


def test_hydrate_candidates_refuses_ambiguous_title_without_year():
    candidate = {"title": "Shared title"}
    corpus = [
        {"title": "Shared title", "year": "2023", "doi": "10.example/one"},
        {"title": "Shared title", "year": "2024", "doi": "10.example/two"},
    ]

    response = hydrate_candidates([candidate], corpus)

    assert response["matched_count"] == 0
    assert response["unresolved"][0]["status"] == "ambiguous"


def test_hydrate_candidates_does_not_replace_nonmatching_doi_by_title():
    candidate = {"title": "Shared title", "year": "2024", "doi": "10.example/external"}
    corpus = [{"title": "Shared title", "year": "2024", "doi": "10.example/local"}]

    response = hydrate_candidates([candidate], corpus)

    assert response["matched_count"] == 0
    assert response["unresolved"][0]["status"] == "missing"
