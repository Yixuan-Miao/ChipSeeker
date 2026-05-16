import os
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

from chipseeker.paths import SOURCE_REGISTRY_FILE, SOURCE_REGISTRY_TEMPLATE_FILE
from chipseeker.utils import load_json, normalize_text, save_json, slugify_filename


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _default_registry_payload():
    template = load_json(
        SOURCE_REGISTRY_TEMPLATE_FILE,
        {"schema_version": 1, "sources": [], "pending_ieee_batch": None},
    )
    template.setdefault("schema_version", 1)
    template.setdefault("sources", [])
    template.setdefault("pending_ieee_batch", None)
    template.setdefault("updated_at_utc", _utc_now())
    return template


def _safe_revision(source):
    try:
        return int(source.get("revision", 0))
    except Exception:
        return 0


def _merge_template_sources(payload):
    """Add or refresh built-in source templates without losing local progress."""
    template_payload = _default_registry_payload()
    template_sources = template_payload.get("sources", [])
    if not isinstance(template_sources, list):
        return False

    payload.setdefault("sources", [])
    existing_by_id = {
        source.get("id"): index
        for index, source in enumerate(payload["sources"])
        if isinstance(source, dict) and source.get("id")
    }
    preserve_keys = {
        "enabled",
        "last_checked_date",
        "last_completed_month",
        "pending_ieee_batch",
    }
    changed = False

    for template_source in template_sources:
        if not isinstance(template_source, dict) or not template_source.get("id"):
            continue
        source_id = template_source["id"]
        existing_index = existing_by_id.get(source_id)
        if existing_index is None:
            payload["sources"].append(dict(template_source))
            existing_by_id[source_id] = len(payload["sources"]) - 1
            changed = True
            continue

        existing_source = payload["sources"][existing_index]
        if not isinstance(existing_source, dict):
            payload["sources"][existing_index] = dict(template_source)
            changed = True
            continue
        if _safe_revision(template_source) <= _safe_revision(existing_source):
            continue

        refreshed = dict(template_source)
        for key in preserve_keys:
            if key in existing_source:
                refreshed[key] = existing_source[key]
        payload["sources"][existing_index] = refreshed
        changed = True

    return changed


def load_source_registry(registry_path=SOURCE_REGISTRY_FILE):
    payload = load_json(registry_path, None)
    if not isinstance(payload, dict):
        payload = _default_registry_payload()
        save_json(registry_path, payload)
    payload.setdefault("schema_version", 1)
    payload.setdefault("sources", [])
    payload.setdefault("pending_ieee_batch", None)
    payload.setdefault("updated_at_utc", _utc_now())
    if _merge_template_sources(payload):
        save_source_registry(payload, registry_path)
    return payload


def save_source_registry(payload, registry_path=SOURCE_REGISTRY_FILE):
    payload["updated_at_utc"] = _utc_now()
    save_json(registry_path, payload)


def list_sources(payload, provider=None):
    sources = payload.get("sources", [])
    if provider:
        return [source for source in sources if source.get("provider") == provider]
    return list(sources)


def find_source(payload, source_id):
    for source in payload.get("sources", []):
        if source.get("id") == source_id:
            return source
    return None


def replace_source(payload, source_id, updates):
    for index, source in enumerate(payload.get("sources", [])):
        if source.get("id") == source_id:
            merged = dict(source)
            merged.update(updates)
            payload["sources"][index] = merged
            return merged
    return None


def current_month_string(today=None):
    current = today or date.today()
    return current.strftime("%Y-%m")


def parse_month_string(value):
    text = normalize_text(value)
    if len(text) != 7 or text[4] != "-":
        raise ValueError("Month must use YYYY-MM format.")
    year = int(text[:4])
    month = int(text[5:7])
    return date(year, month, 1)


def parse_iso_date(value):
    text = normalize_text(value)
    if not text:
        return None
    return date.fromisoformat(text)


def month_bounds(month_str):
    start = parse_month_string(month_str)
    end = date(start.year, start.month, monthrange(start.year, start.month)[1])
    return start.isoformat(), end.isoformat()


def source_next_start_date(source, target_month):
    if source.get("source_kind") == "conference":
        target_year = parse_month_string(target_month).year
        return f"{target_year}-01-01"
    last_completed = parse_month_string(source.get("last_completed_month", "")) if source.get("last_completed_month") else None
    if not last_completed:
        return month_bounds(target_month)[0]

    next_month = date(
        last_completed.year + (1 if last_completed.month == 12 else 0),
        1 if last_completed.month == 12 else last_completed.month + 1,
        1,
    )
    target_start = parse_month_string(target_month)
    return min(next_month, target_start).isoformat()


def source_target_window(source, target_month):
    if source.get("source_kind") == "conference":
        target_year = parse_month_string(target_month).year
        return f"{target_year}-01-01", f"{target_year}-12-31"
    start_date = source_next_start_date(source, target_month)
    _, end_date = month_bounds(target_month)
    return start_date, end_date


def build_ieee_search_url(source, start_date, end_date):
    open_url = normalize_text(source.get("open_url", ""))
    if open_url:
        year = start_date[:4]
        month = start_date[5:7]
        open_url = open_url.replace("{year}", year).replace("{month}", month)
        return open_url
    query = normalize_text(source.get("search_query", source.get("name", "")))
    encoded_query = quote(query or source.get("name", "IEEE"))
    return f"https://ieeexplore.ieee.org/search/searchresult.jsp?newsearch=true&queryText={encoded_query}"


def start_ieee_batch(payload, source_ids, target_month):
    windows = []
    for source_id in source_ids:
        source = find_source(payload, source_id)
        if not source:
            continue
        start_date, end_date = source_target_window(source, target_month)
        windows.append(
            {
                "source_id": source_id,
                "source_name": source.get("name", source_id),
                "start_date": start_date,
                "end_date": end_date,
                "open_url": build_ieee_search_url(source, start_date, end_date),
            }
        )
    batch = {
        "id": f"ieee-{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "target_month": target_month,
        "source_ids": list(source_ids),
        "windows": windows,
        "created_at_utc": _utc_now(),
        "status": "prepared",
    }
    payload["pending_ieee_batch"] = batch
    return batch


def clear_pending_ieee_batch(payload):
    payload["pending_ieee_batch"] = None


def advance_ieee_sources(payload, source_ids, target_month):
    for source_id in source_ids:
        source = find_source(payload, source_id)
        if source and source.get("source_kind") == "conference":
            target_year = parse_month_string(target_month).year
            replace_source(payload, source_id, {"last_completed_month": f"{target_year}-12"})
        else:
            replace_source(payload, source_id, {"last_completed_month": target_month})


def save_ieee_uploaded_file(uploaded_file, source, target_month, ieee_update_dir):
    source_dir = os.path.join(ieee_update_dir, source["id"])
    os.makedirs(source_dir, exist_ok=True)
    suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{source.get('export_prefix', source['id'])}_{target_month}_{suffix}"
    target_path = os.path.join(source_dir, slugify_filename(filename, fallback=source["id"]) + ".csv")
    with open(target_path, "wb") as f:
        f.write(uploaded_file.getvalue())
    return target_path


def default_incremental_start_date(source):
    last_checked = parse_iso_date(source.get("last_checked_date", ""))
    if last_checked:
        return (last_checked + timedelta(days=1)).isoformat()
    return "2015-01-01"


def default_nature_start_date(source):
    return default_incremental_start_date(source)


def save_incremental_run_result(payload, source_ids, checked_date):
    for source_id in source_ids:
        replace_source(payload, source_id, {"last_checked_date": checked_date})


def save_nature_run_result(payload, source_ids, checked_date):
    save_incremental_run_result(payload, source_ids, checked_date)
