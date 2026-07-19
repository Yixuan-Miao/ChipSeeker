import csv

import Nature_Grabber as ng


def test_grab_nature_writes_relative_output_to_default_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(ng, "DEFAULT_OUTPUT_DIR", str(tmp_path / "sources"))
    monkeypatch.setattr(ng, "ensure_bs4", lambda: None)
    monkeypatch.setattr(ng, "fetch_html", lambda *args, **kwargs: "<html></html>")
    monkeypatch.setattr(ng, "parse_search_results", lambda html: ["https://example.org/paper"])
    monkeypatch.setattr(
        ng,
        "parse_article",
        lambda session, article_url: {
            "Document Title": "Nature Test Paper",
            "Abstract": "A" * 120,
            "Authors": "Alice; Bob",
            "Author Keywords": "quantum",
            "Publication Year": "2025",
            "Publication Title": "Nature Electronics",
            "DOI": "10.1000/nature",
            "PDF Link": "",
            "Source URL": article_url,
        },
    )
    monkeypatch.setattr(ng.time, "sleep", lambda *_args, **_kwargs: None)

    ng.grab_nature(
        query="test query",
        output_file="nature_test.csv",
        journal="nature-electronics",
        year_from=2025,
        max_pages=1,
        sleep_seconds=0.0,
    )

    output_path = tmp_path / "sources" / "nature_test.csv"
    assert output_path.exists()
    with open(output_path, "r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["Document Title"] == "Nature Test Paper"


def test_nature_page_cap_marks_source_incomplete(monkeypatch, tmp_path):
    monkeypatch.setattr(ng, "DEFAULT_OUTPUT_DIR", str(tmp_path / "sources"))
    monkeypatch.setattr(ng, "ensure_bs4", lambda: None)
    monkeypatch.setattr(ng, "fetch_html", lambda *args, **kwargs: "<html></html>")
    monkeypatch.setattr(ng, "parse_search_results", lambda html: ["https://example.org/paper"])
    monkeypatch.setattr(
        ng,
        "parse_article",
        lambda session, article_url: {
            "Document Title": "Nature Test Paper",
            "Abstract": "A" * 120,
            "Authors": "Alice",
            "Author Keywords": "chip",
            "Publication Year": "2026",
            "Publication Title": "Nature Electronics",
            "DOI": "10.1000/test",
            "PDF Link": "",
            "Source URL": article_url,
        },
    )
    monkeypatch.setattr(ng.time, "sleep", lambda *_args, **_kwargs: None)

    report = ng.grab_nature("chip", "capped.csv", max_pages=1, return_report=True)

    assert report["row_count"] == 1
    assert report["truncated"] is True
    assert report["completed"] is False


def test_nature_can_fetch_article_metadata_concurrently(monkeypatch, tmp_path):
    monkeypatch.setattr(ng, "DEFAULT_OUTPUT_DIR", str(tmp_path / "sources"))
    monkeypatch.setattr(ng, "ensure_bs4", lambda: None)
    monkeypatch.setattr(ng, "fetch_html", lambda *args, **kwargs: "<html></html>")
    monkeypatch.setattr(
        ng,
        "parse_search_results",
        lambda html: ["https://example.org/one", "https://example.org/two"],
    )
    monkeypatch.setattr(
        ng,
        "fetch_article",
        lambda article_url: {
            "Document Title": article_url.rsplit("/", 1)[-1],
            "Abstract": "Complete metadata",
            "Publication Year": "2026",
            "Publication Title": "Nature Electronics",
            "Source URL": article_url,
        },
    )

    report = ng.grab_nature(
        "chip",
        "concurrent.csv",
        max_pages=1,
        article_workers=2,
        return_report=True,
    )

    assert [row["Document Title"] for row in report["rows"]] == ["one", "two"]
