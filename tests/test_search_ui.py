from chipseeker.search_ui import build_and_groups, filter_search_results


def analyze_venue(value):
    return {"n": value or "Other"}


def extract_year(value):
    return int(value or 0)


def test_exact_match_expands_domain_synonyms():
    raw_hits = [
        {
            "similarity": 0.8,
            "paper": {
                "title": "A SAR Analog-to-Digital Converter With Calibration",
                "abstract": "A compact converter is presented.",
                "year": "2025",
                "venue": "JSSC",
                "keywords": [],
            },
        }
    ]

    results = filter_search_results(raw_hits, (2020, 2026), [], "adc", analyze_venue, extract_year)

    assert len(results) == 1


def test_exact_match_searches_full_author_list():
    raw_hits = [
        {
            "similarity": 0.8,
            "paper": {
                "title": "Pulsed HEMT LNA Operation for Qubit Readout",
                "abstract": "Cryogenic readout paper.",
                "authors": ["Y. Zeng", "J. Stenarson", "P. Sobis", "J. Grahn"],
                "first_author": "Y. Zeng",
                "last_author": "J. Grahn",
                "year": "2025",
                "venue": "TMTT",
                "keywords": [],
            },
        }
    ]

    results = filter_search_results(raw_hits, (2020, 2026), [], "Sobis", analyze_venue, extract_year)

    assert len(results) == 1


def test_exact_match_keeps_spaces_inside_author_phrase():
    raw_hits = [
        {
            "similarity": 0.8,
            "paper": {
                "title": "Pulsed HEMT LNA Operation for Qubit Readout",
                "abstract": "Cryogenic readout paper.",
                "authors": ["Y. Zeng", "J. Stenarson", "P. Sobis", "J. Grahn"],
                "year": "2025",
                "venue": "TMTT",
                "keywords": [],
            },
        }
    ]

    results = filter_search_results(raw_hits, (2020, 2026), [], "Y. Zeng", analyze_venue, extract_year)

    assert len(results) == 1


def test_exact_match_uses_slash_for_or_not_spaces():
    slash_group = build_and_groups("adc/pll")[0]
    assert "adc" in slash_group
    assert "analog-to-digital converter" in slash_group
    assert "pll" in slash_group
    assert "phase-locked loop" in slash_group
    assert build_and_groups("adc pll")[0][0] == "adc pll"


def test_exact_match_comma_means_and():
    raw_hits = [
        {
            "similarity": 0.8,
            "paper": {
                "title": "A SAR ADC With Calibration",
                "abstract": "A compact converter is presented.",
                "year": "2025",
                "venue": "JSSC",
                "keywords": [],
            },
        },
        {
            "similarity": 0.7,
            "paper": {
                "title": "A SAR ADC",
                "abstract": "A compact converter is presented.",
                "year": "2025",
                "venue": "JSSC",
                "keywords": [],
            },
        },
    ]

    results = filter_search_results(raw_hits, (2020, 2026), [], "adc, calibration", analyze_venue, extract_year)

    assert [item["paper"]["title"] for item in results] == ["A SAR ADC With Calibration"]
