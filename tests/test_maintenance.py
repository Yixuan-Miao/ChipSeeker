import csv

from chipseeker.data_sync import build_paper_from_row, paper_identity_key
from chipseeker.maintenance import purge_papers_from_sources


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


def test_purge_papers_from_sources_creates_backup_and_clears_cache(tmp_path):
    source_csv = tmp_path / "manual.csv"
    backup_root = tmp_path / "backups"
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "cache_test.npy").write_text("cache", encoding="utf-8")
    write_csv(
        source_csv,
        [
            {
                "Document Title": "Delete Me",
                "Abstract": "A" * 120,
                "Authors": "Alice",
                "Author Keywords": "",
                "Publication Year": "2025",
                "Publication Title": "ISSCC",
                "DOI": "10.1000/delete",
                "PDF Link": "",
            },
            {
                "Document Title": "Keep Me",
                "Abstract": "B" * 120,
                "Authors": "Bob",
                "Author Keywords": "",
                "Publication Year": "2025",
                "Publication Title": "ISSCC",
                "DOI": "10.1000/keep",
                "PDF Link": "",
            },
        ],
    )

    purge_result = purge_papers_from_sources(
        selected_papers=[{"title": "Delete Me", "year": "2025", "doi": "10.1000/delete"}],
        source_files=[str(source_csv)],
        backup_root_dir=str(backup_root),
        cache_dir=str(cache_dir),
        build_paper_from_row=build_paper_from_row,
        paper_identity_key=paper_identity_key,
    )

    assert purge_result["removed_rows"] == 1
    assert purge_result["backup_dir"] is not None
    assert not (cache_dir / "cache_test.npy").exists()

    text = source_csv.read_text(encoding="utf-8-sig")
    assert "Delete Me" not in text
    assert "Keep Me" in text

