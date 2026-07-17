import csv
from datetime import date, timedelta
import requests

import Arxiv_Grabber as ag


def test_grab_arxiv_writes_relative_output(monkeypatch, tmp_path):
    monkeypatch.setattr(ag, "DEFAULT_OUTPUT_DIR", str(tmp_path / "arxiv"))
    monkeypatch.setattr(
        ag,
        "fetch_feed",
        lambda *args, **kwargs: """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns='http://www.w3.org/2005/Atom' xmlns:arxiv='http://arxiv.org/schemas/atom'>
  <entry>
    <id>http://arxiv.org/abs/1234.5678v1</id>
    <published>2026-04-10T00:00:00Z</published>
    <title>AI Accelerator Test</title>
    <summary>""" + ("A" * 120) + """</summary>
    <author><name>Alice</name></author>
    <category term='cs.AR' />
    <link title='pdf' href='http://arxiv.org/pdf/1234.5678v1' />
  </entry>
</feed>""",
    )
    monkeypatch.setattr(ag.time, "sleep", lambda *_args, **_kwargs: None)

    ag.grab_arxiv(
        query="AI accelerator",
        output_file="arxiv_test.csv",
        categories=["cs.AR"],
        start_date="2026-04-01",
        max_results=25,
        sleep_seconds=0.0,
    )

    output_path = tmp_path / "arxiv" / "arxiv_test.csv"
    assert output_path.exists()
    with open(output_path, "r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["Publication Title"] == "arXiv"


def test_arxiv_query_is_encoded_only_once():
    query = ag.build_search_query(
        '"cryogenic CMOS" OR "qubit readout"',
        ["quant-ph"],
        start_date="2026-07-01",
        end_date="2026-07-17",
    )
    prepared = requests.Request("GET", ag.ARXIV_API_URL, params={"search_query": query}).prepare()

    assert "%" not in query
    assert "all:\"cryogenic CMOS\"" in query
    assert "submittedDate:[202607010000 TO 202607172359]" in query
    assert "%2522" not in prepared.url
    assert "%22cryogenic" in prepared.url


def test_incremental_date_windows_cover_range_without_gaps():
    windows = ag.incremental_date_windows("2026-01-01", "2026-07-17", window_days=30)

    assert windows[0][1] == date(2026, 7, 17)
    assert windows[-1][0] == date(2026, 1, 1)
    for newer, older in zip(windows, windows[1:]):
        assert older[1] == newer[0] - timedelta(days=1)


def test_grab_arxiv_pages_until_checkpoint(monkeypatch, tmp_path):
    monkeypatch.setattr(ag, "DEFAULT_OUTPUT_DIR", str(tmp_path / "arxiv"))
    calls = []

    def feed(entries, total):
        body = "".join(
            f"""
  <entry>
    <id>http://arxiv.org/abs/{paper_id}v1</id>
    <published>{published}T00:00:00Z</published>
    <updated>{updated}T00:00:00Z</updated>
    <title>{title}</title>
    <summary>{'A' * 120}</summary>
    <author><name>Alice</name></author>
    <category term='cs.AR' />
  </entry>"""
            for paper_id, published, updated, title in entries
        )
        return f"""<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns='http://www.w3.org/2005/Atom' xmlns:arxiv='http://arxiv.org/schemas/atom' xmlns:opensearch='http://a9.com/-/spec/opensearch/1.1/'>
  <opensearch:totalResults>{total}</opensearch:totalResults>{body}
</feed>"""

    pages = {
        0: feed(
            [
                ("2607.0001", "2026-07-10", "2026-07-11", "Newest chip paper"),
                ("2607.0002", "2026-07-08", "2026-07-09", "Second chip paper"),
            ],
            4,
        ),
        2: feed(
            [
                ("2606.0003", "2026-06-20", "2026-06-21", "Checkpoint paper"),
                ("2605.0004", "2026-05-20", "2026-05-21", "Old paper"),
            ],
            4,
        ),
    }

    def fake_fetch(*_args, **kwargs):
        calls.append(kwargs["start"])
        return pages[kwargs["start"]]

    monkeypatch.setattr(ag, "fetch_feed", fake_fetch)
    monkeypatch.setattr(ag.time, "sleep", lambda *_args, **_kwargs: None)
    report = ag.grab_arxiv(
        query="chip",
        output_file="paged.csv",
        start_date="2026-06-01",
        max_results=0,
        page_size=2,
        return_report=True,
    )

    assert calls == [0, 2]
    assert report["completed"] is True
    assert report["row_count"] == 3
    assert all("Old paper" != row["Document Title"] for row in report["rows"])
