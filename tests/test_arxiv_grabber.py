import csv

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
