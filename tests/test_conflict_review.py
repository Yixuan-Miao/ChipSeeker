import csv

from chipseeker.conflict_review import collect_source_records, detect_conflicts
from chipseeker.utils import normalize_doi, normalize_title


def _record(title, doi, abstract, year="2026"):
    return {
        "paper": {"title": title, "doi": doi, "abstract": abstract, "year": year, "venue": "JSSC"},
        "source_file": "source.csv",
        "row_number": 2,
        "title_key": normalize_title(title),
        "doi_key": normalize_doi(doi),
        "abstract_hash": str(hash(abstract)),
        "abstract_text": abstract,
    }


def write_csv(path, rows):
    fieldnames = [
        "Document Title",
        "Abstract",
        "Authors",
        "Author Keywords",
        "Publication Year",
        "Publication Title",
        "DOI",
        "PDF Link",
    ]
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_conflict_review_ignores_title_punctuation_and_extended_abstract():
    base = "A low-noise amplifier for cryogenic quantum readout with broadband input matching and low power."
    records = [
        _record("A 4-GHz LNA: Design", "10.1000/example", base),
        _record("A 4 GHz LNA Design", "10.1000/example", base + " Additional measurement details are provided here."),
    ]

    assert detect_conflicts(records) == []


def test_conflict_review_keeps_material_same_doi_conflict():
    records = [
        _record("Cryogenic LNA", "10.1000/example", "A" * 180),
        _record("Quantum ADC", "10.1000/example", "B" * 180),
    ]

    conflicts = detect_conflicts(records)
    assert {item["kind"] for item in conflicts} == {"same_doi_different_abstract", "same_doi_different_title"}
    assert all(item["severity"] == "high" for item in conflicts)


def test_conflict_review_ignores_early_access_year_change_for_same_doi():
    records = [
        _record("A Cryogenic Receiver", "10.1000/example", "A" * 180, year="2025"),
        _record("A Cryogenic Receiver", "10.1000/example", "A" * 180, year="2026"),
    ]

    assert detect_conflicts(records) == []


def test_detect_conflicts_finds_title_year_and_doi_abstract(tmp_path):
    source_file = tmp_path / "manual.csv"
    write_csv(
        source_file,
        [
            {
                "Document Title": "Same Title",
                "Abstract": "A" * 120,
                "Authors": "Alice",
                "Author Keywords": "",
                "Publication Year": "2023",
                "Publication Title": "ISSCC",
                "DOI": "",
                "PDF Link": "",
            },
            {
                "Document Title": "Same Title",
                "Abstract": "B" * 120,
                "Authors": "Bob",
                "Author Keywords": "",
                "Publication Year": "2024",
                "Publication Title": "ISSCC",
                "DOI": "",
                "PDF Link": "",
            },
            {
                "Document Title": "DOI Paper",
                "Abstract": "C" * 120,
                "Authors": "Carol",
                "Author Keywords": "",
                "Publication Year": "2024",
                "Publication Title": "JSSC",
                "DOI": "10.1000/test",
                "PDF Link": "",
            },
            {
                "Document Title": "DOI Paper",
                "Abstract": "D" * 120,
                "Authors": "Dan",
                "Author Keywords": "",
                "Publication Year": "2024",
                "Publication Title": "JSSC",
                "DOI": "10.1000/test",
                "PDF Link": "",
            },
        ],
    )

    records = collect_source_records([str(source_file)])
    conflict_kinds = {conflict["kind"] for conflict in detect_conflicts(records)}

    assert "same_title_different_year" in conflict_kinds
    assert "same_doi_different_abstract" in conflict_kinds


def test_detect_conflicts_ignores_book_chapters_sharing_same_doi(tmp_path):
    source_file = tmp_path / "book.csv"
    write_csv(
        source_file,
        [
            {
                "Document Title": "Chapter 1 - Operational Amplifiers",
                "Abstract": "A" * 120,
                "Authors": "Behzad Razavi",
                "Author Keywords": "",
                "Publication Year": "2006",
                "Publication Title": "Textbook",
                "DOI": "10.1000/book",
                "PDF Link": "",
            },
            {
                "Document Title": "Chapter 2 - Current Mirrors",
                "Abstract": "B" * 120,
                "Authors": "Behzad Razavi",
                "Author Keywords": "",
                "Publication Year": "2006",
                "Publication Title": "Textbook",
                "DOI": "10.1000/book",
                "PDF Link": "",
            },
        ],
    )

    conflict_kinds = {conflict["kind"] for conflict in detect_conflicts(collect_source_records([str(source_file)]))}

    assert "same_doi_different_abstract" not in conflict_kinds
    assert "same_doi_different_title" not in conflict_kinds
