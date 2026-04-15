import csv

from chipseeker.conflict_review import collect_source_records, detect_conflicts


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
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


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
    conflicts = detect_conflicts(records)
    conflict_kinds = {conflict["kind"] for conflict in conflicts}

    assert "same_title_different_year" in conflict_kinds
    assert "same_doi_different_abstract" in conflict_kinds
