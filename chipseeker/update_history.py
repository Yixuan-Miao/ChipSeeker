import csv
import os
import threading
import uuid
from datetime import datetime, timezone

from chipseeker.utils import load_json, normalize_text, save_json
from chipseeker.venue_data import analyze_venue


_HISTORY_LOCK = threading.RLock()
_MAX_EVENTS = 500


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def load_update_history(path):
    payload = load_json(path, {"schema_version": 1, "events": []})
    if not isinstance(payload, dict):
        payload = {"schema_version": 1, "events": []}
    events = payload.get("events", [])
    payload["events"] = events if isinstance(events, list) else []
    payload.setdefault("schema_version", 1)
    return payload


def record_update_event(path, event_type, label, status="completed", details=None, happened_at_utc=None):
    with _HISTORY_LOCK:
        payload = load_update_history(path)
        event = {
            "id": uuid.uuid4().hex,
            "happened_at_utc": happened_at_utc or _utc_now(),
            "event_type": str(event_type or "update"),
            "label": str(label or "Update"),
            "status": str(status or "completed"),
            "details": details if isinstance(details, dict) else {},
        }
        payload["events"].append(event)
        payload["events"] = payload["events"][-_MAX_EVENTS:]
        payload["updated_at_utc"] = _utc_now()
        save_json(path, payload)
        return event


def _canonical_venue(value):
    raw = normalize_text(value)
    if not raw:
        return "Unclassified"
    analyzed = analyze_venue(raw)
    canonical = normalize_text(analyzed.get("n", "")) if isinstance(analyzed, dict) else ""
    if canonical.lower() in {"other", "unknown"}:
        return raw
    return canonical or raw


def collect_database_update_rows(source_csv_files, source_root):
    """Summarize actual local CSV update times by publication, not registry guesses."""
    grouped = {}
    root = os.path.abspath(source_root)
    for path in source_csv_files:
        absolute_path = os.path.abspath(path)
        try:
            stat = os.stat(absolute_path)
            modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
            relative_path = os.path.relpath(absolute_path, root).replace("\\", "/")
            per_file_counts = {}
            with open(absolute_path, "r", encoding="utf-8-sig", errors="ignore", newline="") as handle:
                for row in csv.DictReader(handle):
                    venue = _canonical_venue(row.get("Publication Title", ""))
                    per_file_counts[venue] = per_file_counts.get(venue, 0) + 1
            if not per_file_counts:
                continue
        except (OSError, csv.Error, UnicodeError):
            continue

        for venue, row_count in per_file_counts.items():
            item = grouped.setdefault(
                venue,
                {
                    "publication": venue,
                    "last_updated_at_utc": modified_at,
                    "source_rows": 0,
                    "source_files": set(),
                    "latest_file": relative_path,
                },
            )
            item["source_rows"] += int(row_count)
            item["source_files"].add(relative_path)
            if modified_at > item["last_updated_at_utc"]:
                item["last_updated_at_utc"] = modified_at
                item["latest_file"] = relative_path

    rows = []
    for item in grouped.values():
        rows.append(
            {
                "publication": item["publication"],
                "last_updated_at_utc": item["last_updated_at_utc"],
                "source_rows": item["source_rows"],
                "source_files": len(item["source_files"]),
                "latest_file": item["latest_file"],
            }
        )
    return sorted(rows, key=lambda item: (item["last_updated_at_utc"], item["publication"]), reverse=True)
