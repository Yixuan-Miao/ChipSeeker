import csv
import json

from chipseeker.data_sync import enrich_bibliographic_metadata, list_source_csv_files, scan_and_import_csvs


def write_csv(path, rows):
    fieldnames = [
        "Document Title",
        "Abstract",
        "Authors",
        "Author Keywords",
        "IEEE Terms",
        "Publication Year",
        "Publication Title",
        "Volume",
        "Issue",
        "Start Page",
        "End Page",
        "DOI",
        "PDF Link",
        "Document Identifier",
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


def test_metadata_only_refresh_preserves_embedding_cache(tmp_path):
    source_root = tmp_path / "sources"
    source_root.mkdir()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    db_file = tmp_path / "papers.json"
    manifest_path = tmp_path / "source_manifest.json"

    old_cache = cache_dir / "cache_test.npy"
    old_cache.write_text("cache", encoding="utf-8")

    source_csv = source_root / "manual.csv"
    write_csv(
        source_csv,
        [
            {
                "Document Title": "Metadata Paper",
                "Abstract": "A" * 120,
                "Authors": "Alice; Bob",
                "Author Keywords": "adc",
                "IEEE Terms": "Noise;Qubit",
                "Publication Year": "2025",
                "Publication Title": "JSSC",
                "Volume": "73",
                "Issue": "9",
                "Start Page": "1",
                "End Page": "8",
                "DOI": "10.1000/meta",
                "PDF Link": "https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=123456",
                "Document Identifier": "IEEE Journals",
            }
        ],
    )
    db_file.write_text(
        """[
  {
    "title": "Metadata Paper",
    "abstract": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    "year": "2025",
    "venue": "JSSC",
    "doi": "10.1000/meta",
    "pdf_link": "https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=123456",
    "authors": ["Alice", "Bob"],
    "first_author": "Alice",
    "last_author": "Bob",
    "keywords": ["adc"]
  }
]""",
        encoding="utf-8",
    )

    added_count, updated_count, removed_count, _ = scan_and_import_csvs(
        str(db_file),
        str(cache_dir),
        source_root=str(source_root),
        manifest_path=str(manifest_path),
    )

    assert added_count == 0
    assert updated_count == 1
    assert removed_count == 0
    assert old_cache.exists()
    db_text = db_file.read_text(encoding="utf-8")
    assert '"volume": "73"' in db_text
    assert '"pages": "1-8"' in db_text
    assert '"article_number": "123456"' in db_text


def test_enrich_bibliographic_metadata_repairs_existing_db_without_removal(tmp_path):
    source_root = tmp_path / "sources"
    source_root.mkdir()
    db_file = tmp_path / "papers.json"
    manifest_path = tmp_path / "source_manifest.json"

    source_csv = source_root / "export2026.csv"
    write_csv(
        source_csv,
        [
            {
                "Document Title": "Pulsed HEMT LNA Operation for Qubit Readout",
                "Abstract": "A" * 160,
                "Authors": "Y. Zeng; J. Grahn",
                "Author Keywords": "Cryogenic;qubit readout",
                "IEEE Terms": "Noise;Qubit;HEMTs",
                "Publication Year": "2025",
                "Publication Title": "IEEE Transactions on Microwave Theory and Techniques",
                "Volume": "73",
                "Issue": "9",
                "Start Page": "6539",
                "End Page": "6553",
                "DOI": "10.1109/TMTT.2025.3556982",
                "PDF Link": "https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=10969553",
                "Document Identifier": "IEEE Journals",
            }
        ],
    )
    db_file.write_text(
        json.dumps(
            [
                {
                    "title": "Pulsed HEMT LNA Operation for Qubit Readout",
                    "abstract": "A" * 160,
                    "year": "2025",
                    "venue": "IEEE Transactions on Microwave Theory and Techniques",
                    "doi": "10.1109/TMTT.2025.3556982",
                    "pdf_link": "https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=10969553",
                    "authors": ["Y. Zeng", "J. Grahn"],
                    "first_author": "Y. Zeng",
                    "last_author": "J. Grahn",
                    "keywords": ["Cryogenic"],
                },
                {
                    "title": "Manual Textbook Chapter",
                    "abstract": "B" * 160,
                    "year": "2006",
                    "venue": "Textbook",
                    "doi": "",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = enrich_bibliographic_metadata(str(db_file), source_root=str(source_root), manifest_path=str(manifest_path))

    assert result["updated_count"] == 1
    papers = json.loads(db_file.read_text(encoding="utf-8"))
    assert len(papers) == 2
    repaired = papers[0]
    assert repaired["volume"] == "73"
    assert repaired["number"] == "9"
    assert repaired["pages"] == "6539-6553"
    assert repaired["article_number"] == "10969553"
    assert repaired["ieee_terms"] == ["Noise", "Qubit", "HEMTs"]


def test_source_manifest_records_skip_reasons_for_non_source_csv(tmp_path):
    source_root = tmp_path / "sources"
    source_root.mkdir()
    manifest_path = tmp_path / "source_manifest.json"
    non_source = source_root / "random.csv"
    non_source.write_text("Document Title,Abstract\nOnly title,Only abstract\n", encoding="utf-8")

    valid_files = list_source_csv_files(str(source_root), str(manifest_path))

    assert valid_files == []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["entries"][0]["valid_source"] is False
    assert "missing paper metadata columns" in manifest["entries"][0]["skip_reason"]
