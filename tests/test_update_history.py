import csv

from chipseeker.update_history import collect_database_update_rows, load_update_history, record_update_event


def _write_csv(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Document Title", "Publication Title"])
        writer.writeheader()
        writer.writerows(rows)


def test_update_history_appends_events(tmp_path):
    history_path = tmp_path / "history.json"

    record_update_event(str(history_path), "content_pack", "Incremental pack", status="published", details={"papers": 3})
    record_update_event(str(history_path), "library_sync", "Paper import", details={"added": 5})

    payload = load_update_history(str(history_path))
    assert [event["event_type"] for event in payload["events"]] == ["content_pack", "library_sync"]
    assert payload["events"][0]["details"]["papers"] == 3


def test_database_update_rows_use_real_csv_mtime_and_group_venues(tmp_path):
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    _write_csv(
        first,
        [
            {"Document Title": "A", "Publication Title": "IEEE Journal of Solid-State Circuits"},
            {"Document Title": "B", "Publication Title": "IEEE Journal of Solid-State Circuits"},
        ],
    )
    _write_csv(second, [{"Document Title": "C", "Publication Title": "Nature Electronics"}])

    rows = collect_database_update_rows([str(first), str(second)], str(tmp_path))
    by_name = {row["publication"]: row for row in rows}

    assert by_name["JSSC"]["source_rows"] == 2
    assert by_name["JSSC"]["source_files"] == 1
    assert by_name["Nature Electronics"]["latest_file"] == "second.csv"
