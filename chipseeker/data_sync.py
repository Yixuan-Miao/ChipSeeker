import csv
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone

from chipseeker.paths import CURRENT_LOCAL_DATA_VERSION, SOURCE_CSV_DIR, SOURCE_MANIFEST_FILE
from chipseeker.utils import load_json, normalize_doi, normalize_text, normalize_title, save_json


SOURCE_CSV_REQUIRED_FIELDS = {"Document Title", "Abstract"}


def split_multi_value(value):
    return [item.strip() for item in normalize_text(value).split(";") if item.strip()]


def classify_source_file(path):
    name = os.path.basename(path).lower()
    if name.startswith("export"):
        return "generated_exports"
    return "manual"


def source_target_dir(source_root, category):
    if category == "generated_exports":
        return os.path.join(source_root, "generated_exports")
    return os.path.join(source_root, "manual")


def inspect_csv_headers(path, logger=None):
    try:
        with open(path, mode="r", encoding="utf-8-sig", errors="ignore") as f:
            reader = csv.reader(f)
            headers = next(reader, [])
    except Exception as exc:
        if logger:
            logger.warning("Failed to inspect CSV %s: %s", path, exc)
        return []
    return [normalize_text(header) for header in headers if normalize_text(header)]


def load_source_manifest_entries(manifest_path=SOURCE_MANIFEST_FILE):
    payload = load_json(manifest_path, {"entries": []})
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return payload.get("entries", [])
    return []


def refresh_source_manifest(source_root=SOURCE_CSV_DIR, manifest_path=SOURCE_MANIFEST_FILE, logger=None):
    entries = []
    for root, _, files in os.walk(source_root):
        for name in sorted(files):
            if not name.lower().endswith(".csv"):
                continue
            path = os.path.join(root, name)
            headers = inspect_csv_headers(path, logger=logger)
            entries.append(
                {
                    "relative_path": os.path.relpath(path, source_root).replace("\\", "/"),
                    "category": classify_source_file(path),
                    "size_bytes": os.path.getsize(path),
                    "modified_at_utc": datetime.fromtimestamp(
                        os.path.getmtime(path), tz=timezone.utc
                    ).isoformat(),
                    "headers": headers,
                    "valid_source": SOURCE_CSV_REQUIRED_FIELDS.issubset(set(headers)),
                }
            )
    save_json(
        manifest_path,
        {
            "schema_version": CURRENT_LOCAL_DATA_VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "entries": entries,
        },
    )
    return entries


def organize_source_files(source_root=SOURCE_CSV_DIR, logger=None):
    moved_files = []
    os.makedirs(source_target_dir(source_root, "manual"), exist_ok=True)
    os.makedirs(source_target_dir(source_root, "generated_exports"), exist_ok=True)
    for name in sorted(os.listdir(source_root)):
        path = os.path.join(source_root, name)
        if not os.path.isfile(path) or not name.lower().endswith(".csv"):
            continue
        category = classify_source_file(path)
        target_dir = source_target_dir(source_root, category)
        target_path = os.path.join(target_dir, name)
        if os.path.abspath(path) == os.path.abspath(target_path):
            continue
        shutil.move(path, target_path)
        moved_files.append(target_path)
        if logger:
            logger.info("Organized source CSV %s -> %s", path, target_path)
    return moved_files


def list_source_csv_files(source_root=SOURCE_CSV_DIR, manifest_path=SOURCE_MANIFEST_FILE, logger=None):
    organize_source_files(source_root=source_root, logger=logger)
    manifest_entries = refresh_source_manifest(source_root=source_root, manifest_path=manifest_path, logger=logger)
    valid_files = []
    for entry in manifest_entries:
        if entry["valid_source"]:
            valid_files.append(os.path.join(source_root, entry["relative_path"].replace("/", os.sep)))
        elif logger:
            logger.info("Skipping non-source CSV: %s", entry["relative_path"])
    return valid_files


def build_source_state(csv_files):
    return tuple((path, os.path.getmtime(path), os.path.getsize(path)) for path in csv_files) if csv_files else ()


def build_source_snapshot(csv_files, source_root=SOURCE_CSV_DIR):
    files = []
    for path in csv_files:
        stat = os.stat(path)
        files.append(
            {
                "relative_path": os.path.relpath(path, source_root).replace("\\", "/"),
                "mtime_ns": int(stat.st_mtime_ns),
                "size_bytes": int(stat.st_size),
            }
        )
    payload = {"files": sorted(files, key=lambda item: item["relative_path"])}
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["token"] = hashlib.sha1(payload_json.encode("utf-8")).hexdigest()
    return payload


def library_sync_required(state_payload, source_snapshot, db_file):
    if not os.path.exists(db_file):
        return True
    library_sync = state_payload.get("library_sync", {}) if isinstance(state_payload, dict) else {}
    return (
        library_sync.get("db_file") != os.path.abspath(db_file)
        or library_sync.get("source_token") != source_snapshot.get("token")
    )


def build_paper_from_row(row):
    authors_list = split_multi_value(row.get("Authors", ""))
    keywords = split_multi_value(row.get("Author Keywords", ""))
    return {
        "title": normalize_text(row.get("Document Title", "")),
        "abstract": normalize_text(row.get("Abstract", "")),
        "year": normalize_text(row.get("Publication Year", "")),
        "venue": normalize_text(row.get("Publication Title", "")),
        "doi": normalize_text(row.get("DOI", "")),
        "pdf_link": normalize_text(row.get("PDF Link", "")),
        "authors": authors_list,
        "first_author": authors_list[0] if authors_list else "Unknown",
        "last_author": authors_list[-1] if authors_list else "Unknown",
        "keywords": keywords,
    }


def paper_identity_key(paper):
    doi = normalize_doi(paper.get("doi", ""))
    title = normalize_title(paper.get("title", ""))
    year = normalize_text(paper.get("year", ""))
    if doi:
        return f"doi::{doi}"
    if title and year:
        return f"title_year::{title}::{year}"
    return f"title::{title}" if title else ""


def paper_signature(paper):
    return (
        normalize_text(paper.get("title", "")),
        normalize_text(paper.get("abstract", "")),
        normalize_text(paper.get("year", "")),
        normalize_text(paper.get("venue", "")),
        normalize_text(paper.get("doi", "")),
        normalize_text(paper.get("pdf_link", "")),
        tuple(paper.get("authors", [])),
        tuple(paper.get("keywords", [])),
    )


def is_junk_paper(title, abstract):
    title_lower = title.get("title", "").lower() if isinstance(title, dict) else str(title).lower()
    abstract_lower = str(abstract).lower()
    junk_keywords = [
        "guest editorial",
        "table of contents",
        "front cover",
        "frontmatter",
        "author index",
        "message from",
        "call for papers",
        "committee list",
        "reviewers list",
        "index of authors",
        "issue information",
        "editor's note",
        "editorial:",
        "special issue on",
        "list of reviewers",
        "special event",
        "student research preview",
        "srp",
        "technical session",
        "plenary session",
    ]
    if any(keyword in title_lower for keyword in junk_keywords):
        return True
    if len(abstract_lower) < 100 or abstract_lower in {"", "na", "n/a", "no abstract available.", "no abstract"}:
        return True
    return False


def scan_and_import_csvs(db_file, cache_dir, source_root=SOURCE_CSV_DIR, manifest_path=SOURCE_MANIFEST_FILE, logger=None):
    csv_files = list_source_csv_files(source_root=source_root, manifest_path=manifest_path, logger=logger)
    current_keys = set()
    ordered_keys = []
    new_files_info = {}
    updated_files_info = {}

    all_papers = load_json(db_file, [])
    existing_papers = {}
    for paper in all_papers:
        key = paper_identity_key(paper)
        if key:
            existing_papers[key] = paper
    original_keys = set(existing_papers.keys())

    for file in csv_files:
        new_in_file = 0
        updated_in_file = 0
        try:
            with open(file, mode="r", encoding="utf-8-sig", errors="ignore") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    title = normalize_text(row.get("Document Title", ""))
                    abstract = normalize_text(row.get("Abstract", ""))
                    if is_junk_paper(title, abstract):
                        continue
                    if not title or not abstract or abstract.upper() == "NA":
                        continue

                    paper_obj = build_paper_from_row(row)
                    paper_key = paper_identity_key(paper_obj)
                    if not paper_key:
                        continue

                    if paper_key not in current_keys:
                        ordered_keys.append(paper_key)
                    current_keys.add(paper_key)

                    existing_paper = existing_papers.get(paper_key)
                    if existing_paper is None:
                        existing_papers[paper_key] = paper_obj
                        new_in_file += 1
                    elif paper_signature(existing_paper) != paper_signature(paper_obj):
                        merged_paper = existing_paper.copy()
                        merged_paper.update(paper_obj)
                        existing_papers[paper_key] = merged_paper
                        updated_in_file += 1

            if new_in_file > 0:
                new_files_info[os.path.relpath(file, source_root)] = new_in_file
            if updated_in_file > 0:
                updated_files_info[os.path.relpath(file, source_root)] = updated_in_file
        except Exception as exc:
            if logger:
                logger.warning("Error reading CSV %s: %s", file, exc)

    removed_count = len(original_keys - current_keys)
    added_count = sum(new_files_info.values())
    updated_count = sum(updated_files_info.values())
    final_papers = [existing_papers[paper_key] for paper_key in ordered_keys]

    if added_count > 0 or updated_count > 0 or removed_count > 0:
        save_json(db_file, final_papers)

    file_summaries = [f"{path} (+{count} added)" for path, count in new_files_info.items()]
    file_summaries.extend([f"{path} ({count} updated)" for path, count in updated_files_info.items()])
    refresh_source_manifest(source_root=source_root, manifest_path=manifest_path, logger=logger)
    return added_count, updated_count, removed_count, file_summaries
