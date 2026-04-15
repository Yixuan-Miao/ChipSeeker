import json
import re

from chipseeker.paths import VENUE_RULES_FILE


with open(VENUE_RULES_FILE, "r", encoding="utf-8") as f:
    _VENUE_RULES = json.load(f)


DOMAIN_COLORS = _VENUE_RULES["domain_colors"]
TIER_COLORS = _VENUE_RULES["tier_colors"]
DEFAULT_VENUE = _VENUE_RULES["default_venue"]
VENUE_DB = _VENUE_RULES["venues"]


def analyze_venue(venue_str):
    venue_lower = str(venue_str).lower()
    for venue in VENUE_DB:
        excluded = venue.get("ex", [])
        if excluded and any(exclude in venue_lower for exclude in excluded):
            continue
        for keyword in venue["k"]:
            if len(keyword) <= 6:
                if re.search(r"\b" + re.escape(keyword) + r"\b", venue_lower):
                    return venue
            elif keyword in venue_lower:
                return venue
    return dict(DEFAULT_VENUE)


def get_venue_display_str(venue_data):
    if venue_data["n"] == "Other":
        return "Other"
    if venue_data["ty"] == "Journal":
        if_str = ""
        if venue_data.get("if") and venue_data.get("q"):
            if_str = f" (IF: {venue_data['if']}, {venue_data['q']})"
        elif venue_data.get("if"):
            if_str = f" (IF: {venue_data['if']})"
        return f"{venue_data['n']}{if_str}"
    if venue_data["ty"] == "Conference":
        return f"{venue_data['n']} (Conference)"
    if venue_data["ty"] == "Textbook":
        return f"{venue_data['n']} (Textbook)"
    return venue_data["n"]
