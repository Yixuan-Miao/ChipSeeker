import json
import os
import re
from functools import lru_cache

from chipseeker.paths import PACKAGE_DATA_DIR


SYNONYM_FILE = os.path.join(PACKAGE_DATA_DIR, "domain_synonyms.json")


def _normalize_term(value):
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


@lru_cache(maxsize=1)
def load_domain_synonym_groups():
    if not os.path.exists(SYNONYM_FILE):
        return []
    with open(SYNONYM_FILE, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    groups = payload.get("groups", []) if isinstance(payload, dict) else []
    return [group for group in groups if isinstance(group, dict)]


@lru_cache(maxsize=1)
def synonym_lookup():
    lookup = {}
    for group in load_domain_synonym_groups():
        terms = [_normalize_term(group.get("canonical", ""))]
        terms.extend(_normalize_term(term) for term in group.get("terms", []))
        terms = [term for term in dict.fromkeys(terms) if term]
        for term in terms:
            lookup[term] = terms
    return lookup


def expand_exact_term(term):
    normalized = _normalize_term(term)
    if not normalized:
        return []
    variants = synonym_lookup().get(normalized, [normalized])
    return list(dict.fromkeys(variants))


def expand_exact_terms(terms):
    expanded = []
    for term in terms:
        expanded.extend(expand_exact_term(term))
    return list(dict.fromkeys(expanded))


def _query_tokens(query):
    normalized = _normalize_term(query)
    tokens = set(re.findall(r"[a-z0-9][a-z0-9+\-/.]*", normalized))
    for group in load_domain_synonym_groups():
        for term in [_normalize_term(group.get("canonical", ""))] + [_normalize_term(x) for x in group.get("terms", [])]:
            if term and " " in term and term in normalized:
                tokens.add(term)
    return tokens


def matching_synonym_groups(query, limit=24):
    tokens = _query_tokens(query)
    matches = []
    seen = set()
    for group in load_domain_synonym_groups():
        canonical = _normalize_term(group.get("canonical", ""))
        terms = [_normalize_term(group.get("canonical", ""))]
        terms.extend(_normalize_term(term) for term in group.get("terms", []))
        terms = [term for term in dict.fromkeys(terms) if term]
        if any(term in tokens or any(part in tokens for part in term.split()) for term in terms):
            key = canonical or terms[0]
            if key not in seen:
                matches.append(group)
                seen.add(key)
        if len(matches) >= limit:
            break
    return matches


def synonym_prompt_context(query, limit=24):
    lines = []
    for group in matching_synonym_groups(query, limit=limit):
        canonical = group.get("canonical", "")
        terms = [term for term in group.get("terms", []) if term and term != canonical]
        if terms:
            lines.append(f"- {canonical}: {', '.join(terms[:8])}")
        elif canonical:
            lines.append(f"- {canonical}")
    return "\n".join(lines)
