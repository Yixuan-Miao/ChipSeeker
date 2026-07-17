from chipseeker.work_family import (
    assign_work_families,
    expand_work_family,
    expand_work_family_closure,
    relation_between,
)


def test_work_family_links_same_title_publication_variants_without_merging():
    papers = [
        {
            "title": "A Cryogenic InP LNA",
            "year": "2023",
            "doi": "10.example/conference",
            "authors": ["Y. Zeng", "J. Grahn"],
        },
        {
            "title": "A Cryogenic InP LNA",
            "year": "2024",
            "doi": "10.example/journal",
            "authors": ["Y. Zeng", "J. Grahn"],
        },
    ]

    assign_work_families(papers)

    assert papers[0]["work_family_id"] == papers[1]["work_family_id"]
    assert papers[0]["work_family_size"] == 2


def test_work_family_retains_topical_multi_author_followup():
    seed = {
        "title": "Sub-mW Cryogenic InP HEMT LNA for Qubit Readout",
        "year": "2024",
        "doi": "10.example/seed",
        "authors": ["Y. Zeng", "J. Stenarson", "N. Wadefalk", "J. Grahn"],
    }
    followup = {
        "title": "A 300-uW Cryogenic HEMT LNA for Quantum Computing",
        "year": "2020",
        "doi": "10.example/followup",
        "authors": ["Y. Zeng", "J. Stenarson", "N. Wadefalk", "J. Grahn"],
    }

    relation = relation_between(seed, followup)
    expanded = expand_work_family(seed, [followup])

    assert relation["relation"] == "related_followup"
    assert len(expanded) == 1


def test_work_family_closure_adds_likely_extensions_until_convergence():
    seed = {
        "title": "A Cryogenic CMOS LNA for Qubit Readout",
        "authors": ["A. Researcher"],
        "year": "2023",
        "doi": "10.example/conference",
    }
    journal = {
        "title": "A Cryogenic CMOS LNA for Scalable Qubit Readout",
        "authors": ["A. Researcher"],
        "year": "2024",
        "doi": "10.example/journal",
    }

    response = expand_work_family_closure([seed], [journal])

    assert len(response["confirmed"]) == 2
    assert response["rounds"][0]["added_count"] == 1
