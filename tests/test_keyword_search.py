from chipseeker.keyword_search import (
    KeywordSearchIndex,
    build_structured_query,
    normalize_search_text,
)
from chipseeker.utils import extract_year
from chipseeker.venue_data import analyze_venue


def test_structured_doi_preserves_literal_slash():
    papers = [
        {"title": "Target", "doi": "10.1109/TMTT.2025.1234567", "year": "2025"},
        {"title": "Other", "doi": "10.1109/OTHER.2025.1234567", "year": "2025"},
    ]
    index = KeywordSearchIndex(papers, analyze_venue, extract_year)

    matches, scanned = index.search(
        build_structured_query(dois=["https://doi.org/10.1109/TMTT.2025.1234567"])
    )

    assert scanned == 1
    assert [match["paper"]["title"] for match in matches] == ["Target"]


def test_unicode_normalization_matches_diacritics_and_units():
    assert normalize_search_text("Rücker 12 μW") == "rucker 12 uw"
    assert normalize_search_text("GF SiGe130nm at 4K") == "gf sige 130 nm at 4 k"
    papers = [
        {
            "title": "A 12 μW Receiver",
            "authors": ["H. Rücker"],
            "year": "2024",
        }
    ]
    index = KeywordSearchIndex(papers, analyze_venue, extract_year)

    matches, _ = index.search(
        build_structured_query(all_terms=["uW"], authors=["Rucker"]),
        fields=["title", "authors"],
    )

    assert len(matches) == 1
