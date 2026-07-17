"""Deterministic evidence and regression audits for Ultra Search candidates."""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone

from chipseeker.keyword_search import normalize_search_text
from chipseeker.utils import extract_year
from chipseeker.work_family import publication_key


ULTRA_AUDIT_SCHEMA = "chipseeker-ultra-audit/v1"
EVIDENCE_AXES = ("technology", "cryogenic", "circuit", "frequency")

_TECHNOLOGY_PATTERNS = {
    "InP": ("inp", "indium phosphide", "ingaas", "inalas"),
    "SiGe": ("sige", "silicon germanium"),
    "CMOS": ("cmos", "finfet", "fd-soi", "fdsoi", "mosfet"),
    "GaAs": ("gaas",),
    "GaN": ("gan",),
}
_LNA_TERMS = (" lna ", " lnas ", "low noise amplifier", "low-noise amplifier")
_LOW_NOISE_FRONTEND_TERMS = ("low noise front end", "low-noise front-end")
_CONTAINER_TERMS = ("receiver", "readout ic", "readout soc", "system-on-chip", " soc ", "front-end", "frontend", "mixer")
_DEVICE_TERMS = ("transistor", "device characterization", "noise model", "technology characterization", "process characterization")


def parse_band(value):
    if isinstance(value, (list, tuple)) and len(value) == 2:
        low, high = float(value[0]), float(value[1])
    elif isinstance(value, dict):
        low, high = float(value["low"]), float(value["high"])
    else:
        raw = str(value or "").strip().lower().replace("ghz", "")
        parts = re.split(r"\s*(?::|\-|–|—|to)\s*", raw, maxsplit=1)
        try:
            low, high = float(parts[0]), float(parts[1])
        except (IndexError, ValueError):
            numbers = re.findall(r"\d+(?:\.\d+)?", raw)
            if len(numbers) < 2:
                raise ValueError("Band must contain LOW and HIGH edges, for example 4:8 GHz.")
            low, high = float(numbers[0]), float(numbers[1])
    if low < 0 or high <= low:
        raise ValueError("Band high edge must exceed the low edge.")
    return (low, high)


def band_relation(candidate_band, target_band):
    low, high = parse_band(candidate_band)
    target_low, target_high = parse_band(target_band)
    overlap = max(0.0, min(high, target_high) - max(low, target_low))
    if overlap <= 0:
        relation = "endpoint_only" if high == target_low or low == target_high else "outside"
    elif low <= target_low and high >= target_high:
        relation = "full_cover"
    elif low >= target_low and high <= target_high:
        relation = "inside_target"
    else:
        relation = "partial_overlap"
    return {
        "low": low,
        "high": high,
        "target_low": target_low,
        "target_high": target_high,
        "positive_width_overlap_ghz": round(overlap, 6),
        "relation": relation,
    }


def _paper_text(paper):
    values = [
        paper.get("title", ""),
        paper.get("abstract", ""),
        paper.get("abstract_summary", ""),
        paper.get("technology_process", ""),
        paper.get("physical_temperature", ""),
        paper.get("record_type", ""),
        paper.get("frequency_range_ghz", ""),
        paper.get("lna_band_ghz", ""),
        paper.get("system_band_ghz", ""),
    ]
    values.extend(paper.get("keywords", []) or [])
    values.extend(paper.get("ieee_terms", []) or [])
    return " " + " ".join(str(value or "") for value in values) + " "


def extract_frequency_mentions(text):
    text = str(text or "")
    text = re.sub(r"(?<=\d)\s*每\s*(?=\d)", "-", text)
    mentions = []
    range_pattern = re.compile(
        r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:-|–|—|to)\s*(\d+(?:\.\d+)?)\s*(g|m)hz\b",
        re.IGNORECASE,
    )
    for match in range_pattern.finditer(text):
        factor = 1.0 if match.group(3).lower() == "g" else 0.001
        low, high = float(match.group(1)) * factor, float(match.group(2)) * factor
        if high > low:
            mentions.append(
                {
                    "low_ghz": round(low, 6),
                    "high_ghz": round(high, 6),
                    "text": match.group(0),
                    "inferred_standard_band": False,
                }
            )
    if re.search(r"\bc[ -]?band\b", text, re.IGNORECASE):
        mentions.append(
            {
                "low_ghz": 4.0,
                "high_ghz": 8.0,
                "text": "C-band",
                "inferred_standard_band": True,
            }
        )
    unique = {}
    for item in mentions:
        unique[(item["low_ghz"], item["high_ghz"], item["text"].lower())] = item
    return list(unique.values())


def extract_temperature_mentions(text):
    text = str(text or "")
    values = []
    for match in re.finditer(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:k|kelvin)\b", text, re.IGNORECASE):
        value = float(match.group(1))
        if 0 < value <= 400:
            values.append({"kelvin": value, "text": match.group(0)})
    return values


def temperature_bucket(kelvin):
    kelvin = float(kelvin)
    if kelvin <= 4.2:
        return "<=4.2K"
    if kelvin <= 20:
        return "4.2-20K"
    if kelvin <= 77:
        return "20-77K"
    if kelvin <= 120:
        return "77-120K"
    return ">120K"


def infer_record_type(paper):
    title = " " + normalize_search_text(paper.get("title", "")) + " "
    text = " " + normalize_search_text(_paper_text(paper)) + " "
    has_lna_title = any(term in title for term in _LNA_TERMS)
    has_lna_text = has_lna_title or any(term in text for term in _LNA_TERMS)
    has_low_noise_frontend = any(term in text for term in _LOW_NOISE_FRONTEND_TERMS)
    has_container = any(term in title for term in _CONTAINER_TERMS)
    if has_container and has_lna_text:
        return "receiver_or_soc_with_explicit_lna"
    if has_lna_title:
        return "standalone_lna_or_lna_focused"
    if has_container:
        return "receiver_or_soc_with_low_noise_frontend" if has_low_noise_frontend else "receiver_or_soc_requires_lna_verification"
    if any(term in title for term in _DEVICE_TERMS):
        return "device_or_process_paper"
    return "unclassified"


def build_evidence_snapshot(paper, target_band=None):
    text = _paper_text(paper)
    normalized = " " + normalize_search_text(text) + " "
    technologies = []
    for technology, patterns in _TECHNOLOGY_PATTERNS.items():
        if any(re.search(rf"\b{re.escape(pattern)}\b", normalized) for pattern in patterns):
            technologies.append(technology)
    temperatures = extract_temperature_mentions(text)
    for item in temperatures:
        item["bucket"] = temperature_bucket(item["kelvin"])
    cryogenic_language = bool(re.search(r"\bcryo(?:genic|cooled)?\b", normalized))
    frequencies = extract_frequency_mentions(text)
    structured_bands = {}
    for label, field in (("lna", "lna_band_ghz"), ("system", "system_band_ghz"), ("reported", "frequency_range_ghz")):
        if not paper.get(field):
            continue
        try:
            low, high = parse_band(paper[field])
        except (KeyError, TypeError, ValueError):
            continue
        structured_bands[label] = {"low_ghz": low, "high_ghz": high, "source_field": field}
        frequencies.append(
            {
                "low_ghz": low,
                "high_ghz": high,
                "text": str(paper[field]),
                "inferred_standard_band": False,
                "source_field": field,
            }
        )
    frequency_relations = []
    if target_band:
        for mention in frequencies:
            relation = band_relation((mention["low_ghz"], mention["high_ghz"]), target_band)
            frequency_relations.append({**mention, **relation})
    has_lna = any(term in normalized for term in _LNA_TERMS)
    measured = bool(re.search(r"\bmeasure(?:d|ment|ments)?\b|experimental", normalized))
    simulated = bool(re.search(r"\bsimulat(?:e|ed|ion|ions)\b", normalized))
    credibility_flags = []
    metadata_quality_flags = []
    if re.search(r"(?<=\d)\s*每\s*(?=\d)", text):
        metadata_quality_flags.append("suspected_corrupted_frequency_range_separator")
    if re.search(r"\barxiv\b|\bpreprint\b", normalized):
        credibility_flags.append("preprint_requires_primary_evidence_check")
    if "lt1028" in normalized and any(item["high_ghz"] >= 1.0 for item in frequencies):
        credibility_flags.append("implausible_component_frequency_claim")
    if simulated and not measured:
        credibility_flags.append("simulation_only")

    has_positive_overlap = any(item["positive_width_overlap_ghz"] > 0 for item in frequency_relations)
    best_frequency_relation = None
    if frequency_relations:
        best_frequency_relation = max(
            frequency_relations,
            key=lambda item: (
                item["positive_width_overlap_ghz"],
                item["relation"] == "full_cover",
                not item.get("inferred_standard_band", False),
            ),
        )
    axes = {
        "technology": "evidenced" if technologies else "unknown",
        "cryogenic": "evidenced" if cryogenic_language or any(item["kelvin"] <= 120 for item in temperatures) else "unknown",
        "circuit": "evidenced" if has_lna else "unknown",
        "frequency": "evidenced" if has_positive_overlap else ("contradicted" if frequency_relations else "unknown"),
    }
    return {
        "record_type_hint": infer_record_type(paper),
        "technology_mentions": technologies,
        "temperature_mentions": temperatures,
        "temperature_buckets": sorted({item["bucket"] for item in temperatures}),
        "cryogenic_language": cryogenic_language,
        "frequency_mentions": frequency_relations if target_band else frequencies,
        "structured_bands": structured_bands,
        "best_target_frequency_relation": best_frequency_relation,
        "measurement_status_hint": "measured" if measured else ("simulation_only" if simulated else "unknown"),
        "evidence_axes": axes,
        "missing_evidence_axes": [axis for axis, status in axes.items() if status != "evidenced"],
        "credibility_flags": credibility_flags,
        "metadata_quality_flags": metadata_quality_flags,
    }


def compare_paper_sets(current, prior):
    current_by_key = {publication_key(paper): paper for paper in current or []}
    prior_by_key = {publication_key(paper): paper for paper in prior or []}

    def summarize(keys, source):
        return [
            {
                "publication_key": key,
                "title": str(source[key].get("title", "") or ""),
                "year": str(source[key].get("year", "") or ""),
                "doi": str(source[key].get("doi", "") or ""),
            }
            for key in sorted(keys)
        ]

    retained = current_by_key.keys() & prior_by_key.keys()
    added = current_by_key.keys() - prior_by_key.keys()
    removed = prior_by_key.keys() - current_by_key.keys()
    prior_local = {
        key
        for key, paper in prior_by_key.items()
        if bool(paper.get("source_in_current_corpus", paper.get("source_in_chipseeker_current_corpus", False)))
    }
    retained_local = retained & prior_local
    prior_external = set(prior_by_key) - prior_local
    return {
        "prior_count": len(prior_by_key),
        "current_count": len(current_by_key),
        "retained_count": len(retained),
        "added_count": len(added),
        "removed_count": len(removed),
        "prior_retention_rate": round(len(retained) / len(prior_by_key), 6) if prior_by_key else None,
        "prior_corpus_resident_count": len(prior_local),
        "retained_corpus_resident_count": len(retained_local),
        "corpus_resident_recall": round(len(retained_local) / len(prior_local), 6) if prior_local else None,
        "prior_external_or_corpus_gap_count": len(prior_external),
        "removed_external_or_corpus_gap_count": len(removed & prior_external),
        "added": summarize(added, current_by_key),
        "removed": summarize(removed, prior_by_key),
    }


def corpus_coverage(papers):
    year_counts = Counter(extract_year(paper.get("year", "")) for paper in papers or [])
    year_counts.pop(0, None)
    venue_latest = {}
    for paper in papers or []:
        venue = str(paper.get("venue", "") or "").strip()
        year = extract_year(paper.get("year", ""))
        if venue and year:
            venue_latest[venue] = max(year, venue_latest.get(venue, 0))
    latest_year = max(year_counts, default=0)
    return {
        "paper_count": len(papers or []),
        "earliest_year": min(year_counts, default=0),
        "latest_year": latest_year,
        "latest_year_count": year_counts.get(latest_year, 0),
        "year_counts": {str(year): year_counts[year] for year in sorted(year_counts)},
        "venue_latest_year": dict(sorted(venue_latest.items())),
    }


def audit_candidates(candidates, *, target_band=None, prior=None, corpus=None):
    audited = []
    included_missing_axes = []
    for paper in candidates or []:
        item = dict(paper)
        item["publication_key"] = publication_key(item)
        item["source_provenance"] = {
            "source_in_current_corpus": bool(item.get("source_in_current_corpus", item.get("source_in_chipseeker_current_corpus", False))),
            "abstract_kind": str(item.get("abstract_kind", "source_abstract" if item.get("abstract") else "missing") or "missing"),
            "doi_link": str(item.get("doi_link", "") or (f"https://doi.org/{item['doi']}" if item.get("doi") else "")),
            "pdf_link": str(item.get("pdf_link", "") or ""),
            "source_url": str(item.get("url", "") or ""),
        }
        item["evidence_snapshot"] = build_evidence_snapshot(item, target_band=target_band)
        decision = str(item.get("screening_decision", item.get("decision", "")) or "").lower()
        if decision in {"include", "included", "retain", "retained"}:
            missing = item["evidence_snapshot"]["missing_evidence_axes"]
            if missing:
                included_missing_axes.append(
                    {"publication_key": item["publication_key"], "title": item.get("title", ""), "missing_axes": missing}
                )
        audited.append(item)
    result = {
        "schema": ULTRA_AUDIT_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_band_ghz": list(parse_band(target_band)) if target_band else None,
        "candidate_count": len(audited),
        "included_with_missing_evidence_count": len(included_missing_axes),
        "included_with_missing_evidence": included_missing_axes,
        "results": audited,
    }
    if prior is not None:
        result["comparison"] = compare_paper_sets(audited, prior)
    if corpus is not None:
        result["corpus_coverage"] = corpus_coverage(corpus)
    return result
