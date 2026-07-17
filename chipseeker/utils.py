import json
import os
import re
import tempfile


def extract_year(year_str):
    match = re.search(r"\d{4}", str(year_str))
    return int(match.group()) if match else 0


def load_json(filepath, default_val):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default_val
    return default_val


def save_json(filepath, data):
    parent_dir = os.path.dirname(filepath)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)
    target_dir = parent_dir or "."
    fd, temporary_path = tempfile.mkstemp(prefix=".chipseeker-", suffix=".tmp", dir=target_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary_path, filepath)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


def normalize_text(value):
    return re.sub(r"\s+", " ", str(value or "").strip())


def normalize_title(value):
    return normalize_text(value).lower()


def normalize_doi(value):
    return normalize_text(value).lower()


def slugify_filename(value, fallback="export"):
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", normalize_text(value))
    return cleaned.strip("._") or fallback
