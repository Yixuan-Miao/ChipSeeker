import csv

from chipseeker.data_sync import list_source_csv_files, scan_and_import_csvs


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


def test_scan_and_import_uses_multilevel_keys_and_clears_cache(tmp_path):
    source_root = tmp_path / "sources"
    source_root.mkdir()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    db_file = tmp_path / "papers.json"
    manifest_path = tmp_path / "source_manifest.json"

    old_cache = cache_dir / "cache_test.npy"
    old_cache.write_text("cache", encoding="utf-8")

    export_csv = source_root / "export2026.03.06-04.47.10.csv"
    manual_csv = source_root / "manual.csv"
    write_csv(
        export_csv,
        [
            {
                "Document Title": "Same Title",
                "Abstract": "A" * 120,
                "Authors": "Alice; Bob",
                "Author Keywords": "adc",
                "Publication Year": "2024",
                "Publication Title": "ISSCC",
                "DOI": "",
                "PDF Link": "",
            }
        ],
    )
    write_csv(
        manual_csv,
        [
            {
                "Document Title": "Updater Paper",
                "Abstract": "New abstract " + ("B" * 120),
                "Authors": "Carol; Dan",
                "Author Keywords": "pll",
                "Publication Year": "2025",
                "Publication Title": "JSSC",
                "DOI": "10.1000/update",
                "PDF Link": "",
            }
        ],
    )
    db_file.write_text(
        """[
  {
    "title": "Updater Paper",
    "abstract": "Old abstract",
    "year": "2025",
    "venue": "JSSC",
    "doi": "10.1000/update",
    "pdf_link": "",
    "authors": ["Carol"],
    "first_author": "Carol",
    "last_author": "Carol",
    "keywords": []
  }
]""",
        encoding="utf-8",
    )

    valid_files = list_source_csv_files(str(source_root), str(manifest_path))
    assert any("generated_exports" in path for path in valid_files)
    assert any("manual" in path for path in valid_files)

    added_count, updated_count, removed_count, _ = scan_and_import_csvs(
        str(db_file),
        str(cache_dir),
        source_root=str(source_root),
        manifest_path=str(manifest_path),
    )

    assert added_count == 1
    assert updated_count == 1
    assert removed_count == 0
    assert not old_cache.exists()

    db_text = db_file.read_text(encoding="utf-8")
    assert "10.1000/update" in db_text
    assert db_text.count('"title": "Same Title"') == 1
    assert db_text.count('"title": "Updater Paper"') == 1

