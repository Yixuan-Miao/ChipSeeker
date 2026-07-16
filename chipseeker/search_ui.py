import re

from chipseeker.keyword_search import (
    KEYWORD_SEARCH_FIELDS,
    build_structured_query,
    match_paper,
    normalize_keyword_fields,
    normalize_search_text,
    parse_legacy_groups,
    term_matches_normalized,
)
from chipseeker.scoring import compute_paper_score


def get_paper_id(paper):
    return str(paper.get("doi") or paper.get("paper_key") or paper.get("title", "unknown"))


def _flexible_highlight_pattern(keyword):
    tokens = [token for token in re.split(r"[^A-Za-z0-9+]+", str(keyword or "").strip()) if token]
    if not tokens:
        return None
    if len(tokens) == 1:
        return re.compile(r"(?<![A-Za-z0-9+])(" + re.escape(tokens[0]) + r")(?![A-Za-z0-9+])", re.IGNORECASE)
    joined = r"[^A-Za-z0-9+]*".join(re.escape(token) for token in tokens)
    return re.compile(r"(?<![A-Za-z0-9+])(" + joined + r")(?![A-Za-z0-9+])", re.IGNORECASE)


def highlight_text(text, keywords):
    if not text or not keywords:
        return text
    highlighted = text
    for keyword in sorted(dict.fromkeys(str(keyword) for keyword in keywords if keyword), key=len, reverse=True):
        if keyword:
            pattern = _flexible_highlight_pattern(keyword)
            if pattern is None:
                continue
            highlighted = pattern.sub(
                r'<span style="background-color: #ffeb3b; color: black; font-weight: bold; padding: 0 4px; border-radius: 4px;">\1</span>',
                highlighted,
            )
    return highlighted


def build_and_groups(must_have):
    return parse_legacy_groups(must_have)


def required_words_from_query(must_have):
    required_words = []
    for group in build_and_groups(must_have):
        required_words.extend(group)
    return required_words


def keyword_match_details(paper, must_have, analyze_venue, fields=None):
    return match_paper(
        paper,
        build_structured_query(must_have),
        analyze_venue,
        fields,
    )


def filter_search_results(raw_hits, selected_years, selected_ui_venues, must_have, analyze_venue, extract_year):
    filtered_results = []
    and_groups = build_and_groups(must_have)

    for item in raw_hits:
        paper = item["paper"]
        year_value = extract_year(paper.get("year", ""))
        if not (selected_years[0] <= year_value <= selected_years[1]):
            continue

        venue_data = analyze_venue(paper.get("venue", ""))
        if selected_ui_venues:
            parsed_venue = venue_data["n"]
            if parsed_venue not in selected_ui_venues:
                continue

        if and_groups and not keyword_match_details(paper, must_have, analyze_venue)["matched"]:
            continue

        filtered_results.append(item)

    return filtered_results


def term_matches(term, corpus, normalized_corpus=None):
    return term_matches_normalized(term, normalized_corpus or normalize_search_text(corpus))


def result_bucket_counts(results, search_query):
    return {
        "rare": sum(1 for item in results if item["similarity"] >= 0.60 or not search_query),
        "perfect": sum(1 for item in results if 0.40 <= item["similarity"] < 0.60 and search_query),
        "valuable": sum(1 for item in results if 0.25 <= item["similarity"] < 0.40 and search_query),
        "relevant": sum(1 for item in results if 0.15 <= item["similarity"] < 0.25 and search_query),
    }


def collect_year_counts(results, extract_year):
    counts = {}
    for result in results:
        year_value = extract_year(result["paper"].get("year", ""))
        if year_value > 1900:
            counts[year_value] = counts.get(year_value, 0) + 1
    return counts


def sort_results(results, sort_option, search_query, citations_map, citations_fetched, analyze_venue, extract_year, current_year):
    if "Year" in sort_option:
        return sorted(results, key=lambda item: (extract_year(item["paper"].get("year", "")), item["similarity"]), reverse=True)

    if "Comprehensive" not in sort_option:
        return results

    high_value_results = [item for item in results if item["similarity"] >= 0.25 or not search_query]
    for item in high_value_results:
        paper = item["paper"]
        year_value = extract_year(paper.get("year", ""))
        citations = citations_map.get(paper.get("doi", "").upper(), 0) if citations_fetched else 0
        venue_data = analyze_venue(paper.get("venue", ""))
        item["comp_score"] = compute_paper_score(venue_data, year_value, citations, current_year)
    return sorted(high_value_results, key=lambda item: item["comp_score"], reverse=True)
