import math


def compute_paper_score(venue_data, year_value, citation_count, current_year):
    """Compute a unified paper quality score from venue tier, recency, and citations.

    Returns base_score + year_bonus + citation_bonus as a float.
    """
    base_score = float(venue_data.get("s", 0))
    if year_value > 1900 and (current_year - year_value) < 10:
        year_bonus = max(0, 10 - (current_year - year_value))
    elif year_value > 1900 and (current_year - year_value) <= 0:
        year_bonus = 10
    else:
        year_bonus = 0
    citation_bonus = (
        min(15, math.log10(citation_count + 1) * 6) if citation_count > 0 else 0.0
    )
    return base_score + year_bonus + citation_bonus
