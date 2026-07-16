import re

from chipseeker.scoring import compute_paper_score


KEYWORD_SEARCH_FIELDS = (
    "title",
    "abstract",
    "authors",
    "venue",
    "year",
    "keywords",
    "ieee_terms",
    "doi",
)


def _keyword_field_text(value):
    if isinstance(value, (list, tuple, set)):
        return " ".join(str(item) for item in value if str(item).strip())
    return str(value or "")


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
    and_groups = []
    if must_have:
        for group in re.split(r"\s*(?:,|&|\band\b)\s*", must_have, flags=re.IGNORECASE):
            raw_words = [word.strip().lower().strip('"') for word in re.split(r"\s*/\s*", group) if word.strip()]
            or_words = raw_words
            if or_words:
                and_groups.append(list(dict.fromkeys(or_words)))
    return and_groups


def required_words_from_query(must_have):
    required_words = []
    for group in build_and_groups(must_have):
        required_words.extend(group)
    return required_words


def normalize_keyword_fields(fields):
    aliases = {
        "author": "authors",
        "keyword": "keywords",
        "ieee": "ieee_terms",
        "terms": "ieee_terms",
    }
    normalized = []
    for field in fields or KEYWORD_SEARCH_FIELDS:
        field = aliases.get(str(field or "").strip().lower(), str(field or "").strip().lower())
        if field not in KEYWORD_SEARCH_FIELDS:
            raise ValueError(
                f"Unknown keyword field '{field}'. Choose from: {', '.join(KEYWORD_SEARCH_FIELDS)}."
            )
        if field not in normalized:
            normalized.append(field)
    return normalized


def paper_keyword_fields(paper, analyze_venue):
    authors = paper.get("authors", [])
    author_str = " ".join(authors) if isinstance(authors, list) else str(authors or "")
    if not author_str.strip():
        author_str = f"{paper.get('first_author', '')} {paper.get('last_author', '')}"
    venue_data = analyze_venue(paper.get("venue", ""))
    venue_terms = " ".join(
        [
            str(paper.get("venue", "")),
            str(venue_data.get("n", "")),
            str(venue_data.get("t", "")),
            " ".join(venue_data.get("d", []) or []),
        ]
    )
    return {
        "title": str(paper.get("title", "") or ""),
        "abstract": str(paper.get("abstract", "") or ""),
        "authors": author_str,
        "venue": venue_terms,
        "year": str(paper.get("year", "") or ""),
        "keywords": _keyword_field_text(paper.get("keywords", [])),
        "ieee_terms": _keyword_field_text(paper.get("ieee_terms", [])),
        "doi": str(paper.get("doi", "") or ""),
    }


def keyword_match_details(paper, must_have, analyze_venue, fields=None):
    and_groups = build_and_groups(must_have)
    if not and_groups:
        return {"matched": True, "matched_fields": [], "matched_terms": []}

    selected_fields = normalize_keyword_fields(fields)
    field_text = paper_keyword_fields(paper, analyze_venue)
    normalized = {
        field: re.sub(r"[^a-z0-9+]+", " ", field_text[field].lower())
        for field in selected_fields
    }
    matched_fields = set()
    matched_terms = []
    for group in and_groups:
        group_match = None
        for term in group:
            term_fields = [
                field
                for field in selected_fields
                if term_matches(term, field_text[field].lower(), normalized[field])
            ]
            if term_fields:
                group_match = {"term": term, "fields": term_fields}
                matched_fields.update(term_fields)
                break
        if group_match is None:
            return {"matched": False, "matched_fields": [], "matched_terms": []}
        matched_terms.append(group_match)
    return {
        "matched": True,
        "matched_fields": [field for field in selected_fields if field in matched_fields],
        "matched_terms": matched_terms,
    }


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
    term = str(term or "").strip().lower()
    if not term:
        return False
    normalized_corpus = normalized_corpus or re.sub(r"[^a-z0-9+]+", " ", corpus.lower())
    normalized_term = re.sub(r"[^a-z0-9+]+", " ", term).strip()
    if not normalized_term:
        return False
    if " " in normalized_term:
        return f" {normalized_term} " in f" {normalized_corpus} "
    return re.search(r"\b" + re.escape(normalized_term) + r"\b", normalized_corpus) is not None


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
