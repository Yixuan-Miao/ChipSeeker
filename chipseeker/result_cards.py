import math
from datetime import datetime

from chipseeker.exports import paper_authors_display
from chipseeker.search_ui import highlight_text, required_words_from_query
from chipseeker.utils import extract_year
from chipseeker.venue_data import TIER_COLORS, analyze_venue, get_venue_display_str


def result_badge(similarity, has_query):
    if similarity >= 0.60 or not has_query:
        return {"color": "#9C27B0", "label": "Rare Match"}
    if similarity >= 0.40:
        return {"color": "#00C853", "label": "Perfect Match"}
    if similarity >= 0.25:
        return {"color": "#2196F3", "label": "Highly Valuable"}
    if similarity >= 0.15:
        return {"color": "#FF9800", "label": "Relevant"}
    return {"color": "#9E9E9E", "label": "Noise"}


def paper_state_key(paper):
    doi = str((paper or {}).get("doi", "")).strip().upper()
    if doi:
        return f"doi:{doi}"
    title = str((paper or {}).get("title", "")).strip().lower()
    year = str((paper or {}).get("year", "")).strip()
    if year:
        return f"title_year:{title}|{year}"
    return f"title:{title}"


def default_card_state():
    return {
        "rating": "Unrated",
        "comments": "",
        "open_count": 0,
        "matched_queries": [],
        "search_count": 0,
    }


def build_result_cards(results, query_text="", exact_query="", user_states=None, citations_map=None):
    required_terms = required_words_from_query(exact_query)
    cards = []
    current_year = datetime.now().year
    user_states = user_states or {}
    citations_map = citations_map or {}

    for index, item in enumerate(results, start=1):
        paper = item.get("paper", {})
        similarity = float(item.get("similarity", 0.0))
        badge = result_badge(similarity, bool(query_text))
        venue_data = analyze_venue(paper.get("venue", ""))
        venue_display = get_venue_display_str(venue_data)
        year_value = extract_year(paper.get("year", ""))
        if year_value > 1900 and (current_year - year_value) < 10:
            year_bonus = max(0, 10 - (current_year - year_value))
        elif year_value > 1900 and (current_year - year_value) <= 0:
            year_bonus = 10
        else:
            year_bonus = 0
        base_score = float(venue_data.get("s", 0))
        doi = str(paper.get("doi", "")).strip().upper()
        citation_count = int(citations_map.get(doi, 0)) if doi else 0
        citation_bonus = min(15, math.log10(citation_count + 1) * 6) if citation_count > 0 else 0.0
        comp_score = float(base_score + year_bonus + citation_bonus)
        author_display = paper_authors_display(paper)
        state_key = paper_state_key(paper)
        user_state = dict(default_card_state(), **(user_states.get(state_key) or {}))
        llm_score = item.get("llm_score")
        llm_delta_text = ""
        llm_delta_class = ""
        if llm_score is not None:
            try:
                llm_delta = float(llm_score) - (similarity * 100.0)
                llm_delta_text = f"{llm_delta:+.1f}"
                llm_delta_class = "llm-delta-up" if llm_delta >= 0 else "llm-delta-down"
            except (TypeError, ValueError):
                pass
        cards.append(
            {
                "index": index,
                "selection_value": index - 1,
                "title_html": highlight_text(paper.get("title", "Untitled"), required_terms),
                "abstract_html": highlight_text(paper.get("abstract", "No abstract"), required_terms).replace("\n", "<br>"),
                "authors_text": author_display,
                "authors_html": highlight_text(author_display, required_terms),
                "venue_text": venue_display,
                "venue_html": highlight_text(venue_display, required_terms),
                "venue_raw": paper.get("venue", "Unknown"),
                "year_text": str(paper.get("year", "")),
                "year_html": highlight_text(str(paper.get("year", "")), required_terms),
                "tier_text": venue_data.get("t", "N/A"),
                "tier_color": TIER_COLORS.get(venue_data.get("t", ""), "#9E9E9E"),
                "doi": paper.get("doi", ""),
                "pdf_link": paper.get("pdf_link", ""),
                "similarity_percent": f"{similarity * 100:.1f}",
                "badge_color": badge["color"],
                "badge_label": badge["label"],
                "score_text": f"{comp_score:.1f}",
                "llm_score": llm_score,
                "llm_reason": item.get("llm_reason", ""),
                "llm_delta_text": llm_delta_text,
                "llm_delta_class": llm_delta_class,
                "matched_terms": required_terms,
                "paper_key": state_key,
                "rating": user_state.get("rating", "Unrated"),
                "comments": user_state.get("comments", ""),
                "open_count": int(user_state.get("open_count", 0)),
                "search_count": int(user_state.get("search_count", len(user_state.get("matched_queries", [])))),
                "citation_count": citation_count,
                "paper": paper,
            }
        )
    return cards
