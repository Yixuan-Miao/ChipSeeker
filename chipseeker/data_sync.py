import csv
import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone

from chipseeker.paths import CURRENT_LOCAL_DATA_VERSION, SOURCE_CSV_DIR, SOURCE_MANIFEST_FILE
from chipseeker.utils import load_json, normalize_doi, normalize_text, normalize_title, save_json


SOURCE_CSV_REQUIRED_FIELDS = {"Document Title", "Abstract"}
IEEE_SOURCE_SIGNALS = {
    "Date Added To Xplore",
    "IEEE Terms",
    "Article Citation Count",
    "Patent Citation Count",
    "Reference Count",
    "Document Identifier",
    "Publisher",
}
GENERIC_SOURCE_SIGNALS = {
    "Authors",
    "Publication Year",
    "Publication Title",
    "DOI",
    "PDF Link",
    "Source URL",
}
BIBLIOGRAPHIC_ENRICH_FIELDS = (
    "volume",
    "number",
    "issue",
    "start_page",
    "end_page",
    "pages",
    "issn",
    "isbn",
    "publisher",
    "document_identifier",
    "date_added_to_xplore",
    "online_date",
    "issue_date",
    "meeting_date",
    "funding_information",
    "article_citation_count",
    "patent_citation_count",
    "reference_count",
    "license",
    "article_number",
)
LIST_ENRICH_FIELDS = ("keywords", "ieee_terms")
FILL_IF_MISSING_FIELDS = ("doi", "pdf_link", "year", "venue")


def split_multi_value(value):
    return [item.strip() for item in normalize_text(value).split(";") if item.strip()]


def extract_article_number(row):
    for field in ("Article Number", "Document Number", "Accession Number"):
        value = normalize_text(row.get(field, ""))
        if value:
            return value
    pdf_link = normalize_text(row.get("PDF Link", ""))
    match = re.search(r"(?:arnumber=|/document/)(\d+)", pdf_link)
    return match.group(1) if match else ""


_MONTH_NORMALIZATION = {
    "jan.": "Jan",
    "feb.": "Feb",
    "mar.": "Mar",
    "apr.": "Apr",
    "jun.": "Jun",
    "jul.": "Jul",
    "aug.": "Aug",
    "sep.": "Sep",
    "sept.": "Sep",
    "oct.": "Oct",
    "nov.": "Nov",
    "dec.": "Dec",
}


def parse_source_date_score(value):
    text = normalize_text(value)
    if not text:
        return 0
    normalized = text.replace(",", " ")
    for old, new in _MONTH_NORMALIZATION.items():
        normalized = re.sub(rf"\b{re.escape(old)}", new, normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    formats = (
        "%d %b %Y",
        "%d %B %Y",
        "%b %d %Y",
        "%B %d %Y",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%b %Y",
        "%B %Y",
        "%Y",
    )
    for fmt in formats:
        try:
            parsed = datetime.strptime(normalized, fmt)
        except ValueError:
            continue
        return parsed.year * 10000 + parsed.month * 100 + parsed.day
    match = re.search(r"\b(19|20)\d{2}\b", normalized)
    return int(match.group(0)) * 10000 + 101 if match else 0


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


def file_sha1(path, chunk_size=1024 * 1024):
    digest = hashlib.sha1()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def classify_csv_source(headers):
    header_set = set(headers or [])
    missing = sorted(SOURCE_CSV_REQUIRED_FIELDS - header_set)
    if missing:
        return {
            "valid_source": False,
            "source_type": "unsupported",
            "skip_reason": "missing required field(s): " + ", ".join(missing),
        }
    if header_set & IEEE_SOURCE_SIGNALS:
        return {"valid_source": True, "source_type": "ieee_xplore", "skip_reason": ""}
    if "Source URL" in header_set:
        publication_title = " ".join(sorted(header_set)).lower()
        if "arxiv" in publication_title or {"Publication Title", "Publication Year"} & header_set:
            return {"valid_source": True, "source_type": "web_grabber", "skip_reason": ""}
    if header_set & GENERIC_SOURCE_SIGNALS:
        return {"valid_source": True, "source_type": "generic_paper_source", "skip_reason": ""}
    return {
        "valid_source": False,
        "source_type": "unsupported",
        "skip_reason": "missing paper metadata columns such as Authors, DOI, PDF Link, Publication Year, or Source URL",
    }


def load_source_manifest_entries(manifest_path=SOURCE_MANIFEST_FILE):
    payload = load_json(manifest_path, {"entries": []})
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return payload.get("entries", [])
    return []


def refresh_source_manifest(source_root=SOURCE_CSV_DIR, manifest_path=SOURCE_MANIFEST_FILE, logger=None):
    entries = []
    for root, dirs, files in os.walk(source_root):
        dirs.sort()
        for name in sorted(files):
            if not name.lower().endswith(".csv"):
                continue
            path = os.path.join(root, name)
            headers = inspect_csv_headers(path, logger=logger)
            profile = classify_csv_source(headers)
            try:
                digest = file_sha1(path)
            except Exception as exc:
                digest = ""
                if logger:
                    logger.warning("Could not hash CSV %s: %s", path, exc)
            entries.append(
                {
                    "relative_path": os.path.relpath(path, source_root).replace("\\", "/"),
                    "category": classify_source_file(path),
                    "size_bytes": os.path.getsize(path),
                    "sha1": digest,
                    "modified_at_utc": datetime.fromtimestamp(
                        os.path.getmtime(path), tz=timezone.utc
                    ).isoformat(),
                    "headers": headers,
                    "valid_source": profile["valid_source"],
                    "source_type": profile["source_type"],
                    "skip_reason": profile["skip_reason"],
                }
            )
    seen_hashes = {}
    for entry in sorted(entries, key=lambda item: item["relative_path"]):
        digest = entry.get("sha1", "")
        if not entry.get("valid_source") or not digest:
            continue
        duplicate_of = seen_hashes.get(digest)
        if duplicate_of:
            entry["valid_source"] = False
            entry["duplicate_of"] = duplicate_of
            entry["skip_reason"] = f"duplicate CSV content of {duplicate_of}"
        else:
            seen_hashes[digest] = entry["relative_path"]
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
        if os.path.exists(target_path):
            stem, ext = os.path.splitext(name)
            suffix = 2
            while True:
                candidate = os.path.join(target_dir, f"{stem}_{suffix}{ext}")
                if not os.path.exists(candidate):
                    target_path = candidate
                    break
                suffix += 1
        if os.path.abspath(path) == os.path.abspath(target_path):
            continue
        try:
            shutil.move(path, target_path)
            moved_files.append(target_path)
            if logger:
                logger.info("Organized source CSV %s -> %s", path, target_path)
        except OSError as exc:
            if logger:
                logger.warning(
                    "Could not organize source CSV %s; it will be scanned in place. Error: %s",
                    path,
                    exc,
                )
    return moved_files


def list_source_csv_files(source_root=SOURCE_CSV_DIR, manifest_path=SOURCE_MANIFEST_FILE, logger=None):
    organize_source_files(source_root=source_root, logger=logger)
    manifest_entries = refresh_source_manifest(source_root=source_root, manifest_path=manifest_path, logger=logger)
    valid_files = []
    for entry in manifest_entries:
        if entry["valid_source"]:
            valid_files.append(os.path.join(source_root, entry["relative_path"].replace("/", os.sep)))
        elif logger:
            logger.info("Skipping non-source CSV: %s (%s)", entry["relative_path"], entry.get("skip_reason", "unsupported"))
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


def bibliographic_metadata_enrich_required(state_payload, source_snapshot, db_file):
    if not os.path.exists(db_file):
        return False
    metadata_state = state_payload.get("bibliographic_metadata_enrich", {}) if isinstance(state_payload, dict) else {}
    return (
        metadata_state.get("db_file") != os.path.abspath(db_file)
        or metadata_state.get("source_token") != source_snapshot.get("token")
        or int(metadata_state.get("schema_version", 0) or 0) < CURRENT_LOCAL_DATA_VERSION
    )


def build_paper_from_row(row):
    authors_list = split_multi_value(row.get("Authors", ""))
    keywords = split_multi_value(row.get("Author Keywords", ""))
    ieee_terms = split_multi_value(row.get("IEEE Terms", ""))
    start_page = normalize_text(row.get("Start Page", ""))
    end_page = normalize_text(row.get("End Page", ""))
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
        "ieee_terms": ieee_terms,
        "volume": normalize_text(row.get("Volume", "")),
        "number": normalize_text(row.get("Issue", "")),
        "issue": normalize_text(row.get("Issue", "")),
        "start_page": start_page,
        "end_page": end_page,
        "pages": f"{start_page}-{end_page}" if start_page and end_page else (start_page or end_page),
        "issn": normalize_text(row.get("ISSN", "")),
        "isbn": normalize_text(row.get("ISBNs", "")),
        "publisher": normalize_text(row.get("Publisher", "")),
        "document_identifier": normalize_text(row.get("Document Identifier", "")),
        "date_added_to_xplore": normalize_text(row.get("Date Added To Xplore", "")),
        "online_date": normalize_text(row.get("Online Date", "")),
        "issue_date": normalize_text(row.get("Issue Date", "")),
        "meeting_date": normalize_text(row.get("Meeting Date", "")),
        "funding_information": normalize_text(row.get("Funding Information", "")),
        "article_citation_count": normalize_text(row.get("Article Citation Count", "")),
        "patent_citation_count": normalize_text(row.get("Patent Citation Count", "")),
        "reference_count": normalize_text(row.get("Reference Count", "")),
        "license": normalize_text(row.get("License", "")),
        "article_number": extract_article_number(row),
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


def paper_lookup_keys(paper):
    doi = normalize_doi(paper.get("doi", ""))
    title = normalize_title(paper.get("title", ""))
    year = normalize_text(paper.get("year", ""))
    keys = []
    if doi:
        keys.append(f"doi::{doi}")
    if title and year:
        keys.append(f"title_year::{title}::{year}")
    if title:
        keys.append(f"title::{title}")
    return list(dict.fromkeys(keys))


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
        tuple(paper.get("ieee_terms", [])),
        normalize_text(paper.get("volume", "")),
        normalize_text(paper.get("number", "")),
        normalize_text(paper.get("issue", "")),
        normalize_text(paper.get("start_page", "")),
        normalize_text(paper.get("end_page", "")),
        normalize_text(paper.get("pages", "")),
        normalize_text(paper.get("issn", "")),
        normalize_text(paper.get("isbn", "")),
        normalize_text(paper.get("publisher", "")),
        normalize_text(paper.get("document_identifier", "")),
        normalize_text(paper.get("date_added_to_xplore", "")),
        normalize_text(paper.get("online_date", "")),
        normalize_text(paper.get("issue_date", "")),
        normalize_text(paper.get("meeting_date", "")),
        normalize_text(paper.get("funding_information", "")),
        normalize_text(paper.get("article_citation_count", "")),
        normalize_text(paper.get("patent_citation_count", "")),
        normalize_text(paper.get("reference_count", "")),
        normalize_text(paper.get("license", "")),
        normalize_text(paper.get("article_number", "")),
    )


def embedding_relevant_signature(paper):
    return (
        normalize_text(paper.get("title", "")),
        normalize_text(paper.get("abstract", "")),
    )


def _list_value(value):
    if isinstance(value, (list, tuple)):
        return [normalize_text(item) for item in value if normalize_text(item)]
    if isinstance(value, str):
        return split_multi_value(value)
    return []


def _merge_unique_values(existing, incoming):
    merged = []
    seen = set()
    for item in _list_value(existing) + _list_value(incoming):
        key = item.lower()
        if key and key not in seen:
            merged.append(item)
            seen.add(key)
    return merged


def _paper_source_date_score(paper):
    return max(
        parse_source_date_score(paper.get("date_added_to_xplore", "")),
        parse_source_date_score(paper.get("issue_date", "")),
        parse_source_date_score(paper.get("online_date", "")),
    )


def _paper_metadata_completeness_score(paper):
    score = 0
    if normalize_text(paper.get("volume", "")):
        score += 20
    if normalize_text(paper.get("issue", "")) or normalize_text(paper.get("number", "")):
        score += 20
    if normalize_text(paper.get("start_page", "")):
        score += 10
    if normalize_text(paper.get("end_page", "")):
        score += 10
    pages = normalize_text(paper.get("pages", ""))
    if pages and pages not in {"1", "1-1"}:
        score += 10
    if normalize_text(paper.get("issue_date", "")):
        score += 20
    if normalize_text(paper.get("date_added_to_xplore", "")):
        score += 5
    if normalize_text(paper.get("online_date", "")):
        score += 5
    if normalize_text(paper.get("article_number", "")):
        score += 5
    if normalize_text(paper.get("publisher", "")):
        score += 2
    if normalize_text(paper.get("document_identifier", "")):
        score += 2
    return score


def _paper_metadata_rank(paper):
    return (_paper_metadata_completeness_score(paper), _paper_source_date_score(paper))


def _should_replace_bibliographic_field(existing_paper, source_paper, field):
    incoming = normalize_text(source_paper.get(field, ""))
    if not incoming:
        return False
    current = normalize_text(existing_paper.get(field, ""))
    if not current:
        return True
    if current == incoming:
        return False
    return _paper_metadata_rank(source_paper) >= _paper_metadata_rank(existing_paper)


def _author_richness(authors):
    score = 0
    for author in _list_value(authors):
        score += len(author)
        score += 8 * len(re.findall(r"[A-Za-zÀ-ž]{3,}", author))
        score -= 4 * len(re.findall(r"\b[A-ZÀ-Ž]\.", author))
    return score


def _merge_paper_from_source(existing_paper, source_paper, allow_core_updates=True):
    merged = dict(existing_paper or {})
    before_embedding = embedding_relevant_signature(merged)
    changed = False

    core_fields = ("title", "abstract", "year", "venue", "doi", "pdf_link")
    if allow_core_updates:
        for field in core_fields:
            incoming = source_paper.get(field, "")
            if normalize_text(incoming) and merged.get(field) != incoming:
                merged[field] = incoming
                changed = True
    else:
        for field in FILL_IF_MISSING_FIELDS:
            incoming = source_paper.get(field, "")
            if normalize_text(incoming) and not normalize_text(merged.get(field, "")):
                merged[field] = incoming
                changed = True

    incoming_authors = _list_value(source_paper.get("authors"))
    if incoming_authors and (
        not _list_value(merged.get("authors"))
        or _author_richness(incoming_authors) > _author_richness(merged.get("authors"))
    ):
        merged["authors"] = incoming_authors
        merged["first_author"] = incoming_authors[0]
        merged["last_author"] = incoming_authors[-1]
        changed = True

    for field in LIST_ENRICH_FIELDS:
        merged_list = _merge_unique_values(merged.get(field), source_paper.get(field))
        if merged_list != _list_value(merged.get(field)):
            merged[field] = merged_list
            changed = True

    for field in BIBLIOGRAPHIC_ENRICH_FIELDS:
        if _should_replace_bibliographic_field(merged, source_paper, field):
            merged[field] = source_paper.get(field, "")
            changed = True

    return merged, changed, before_embedding != embedding_relevant_signature(merged)


def _title_has_keyword(title_lower, keyword):
    if keyword.isalnum() and len(keyword) <= 4:
        return re.search(rf"\b{re.escape(keyword)}\b", title_lower) is not None
    return keyword in title_lower


def _title_has_any(title_lower, keywords):
    return any(_title_has_keyword(title_lower, keyword) for keyword in keywords)


def is_junk_paper(title, abstract, row=None):
    title_lower = title.get("title", "").lower() if isinstance(title, dict) else str(title).lower()
    abstract_text = normalize_text(abstract)
    abstract_lower = abstract_text.lower()
    row = row or {}
    has_doi = bool(normalize_doi(row.get("DOI", "")))
    no_abstract_values = {"", "na", "n/a", "no abstract available.", "no abstract"}

    hard_junk_keywords = [
        "table of contents",
        "front cover",
        "back cover",
        "frontmatter",
        "author index",
        "message from",
        "call for papers",
        "committee list",
        "reviewers list",
        "index of authors",
        "issue information",
        "editor's note",
        "list of reviewers",
        "masthead",
        "advertisement",
        "publisher's note",
    ]
    if _title_has_any(title_lower, hard_junk_keywords):
        return True

    useful_intro_keywords = [
        "introduction",
        "overview",
        "technical session",
        "plenary session",
        "session",
        "tutorial",
        "forum",
        "keynote",
        "panel",
        "invited",
        "special issue on",
        "guest editorial",
    ]
    if (
        has_doi
        and _title_has_any(title_lower, useful_intro_keywords)
        and abstract_lower not in no_abstract_values
        and len(abstract_lower) >= 30
    ):
        return False

    soft_junk_keywords = [
        "guest editorial",
        "editorial:",
        "special issue on",
        "special event",
        "student research preview",
        "srp",
        "technical session",
        "plenary session",
    ]
    if _title_has_any(title_lower, soft_junk_keywords):
        return True
    if len(abstract_lower) < 100 or abstract_lower in no_abstract_values:
        return True
    return False


def scan_and_import_csvs(db_file, cache_dir, source_root=SOURCE_CSV_DIR, manifest_path=SOURCE_MANIFEST_FILE, logger=None):
    previous_manifest_entries = load_source_manifest_entries(manifest_path)
    previous_valid_paths = {
        str(entry.get("relative_path", "")).replace("\\", "/")
        for entry in previous_manifest_entries
        if entry.get("valid_source") and entry.get("relative_path")
    }
    csv_files = list_source_csv_files(source_root=source_root, manifest_path=manifest_path, logger=logger)
    current_manifest_entries = load_source_manifest_entries(manifest_path)
    current_paths = {
        str(entry.get("relative_path", "")).replace("\\", "/")
        for entry in current_manifest_entries
        if entry.get("relative_path")
    }
    current_valid_paths = {
        str(entry.get("relative_path", "")).replace("\\", "/")
        for entry in current_manifest_entries
        if entry.get("valid_source") and entry.get("relative_path")
    }
    formerly_valid_now_invalid = sorted((previous_valid_paths & current_paths) - current_valid_paths)
    removal_skip_reasons = []
    if formerly_valid_now_invalid:
        removal_skip_reasons.append(
            "previously valid source(s) are now invalid: " + ", ".join(formerly_valid_now_invalid[:5])
        )
    current_keys = set()
    ordered_keys = []
    new_files_info = {}
    updated_files_info = {}
    cache_invalidating_update_count = 0
    failed_files = []

    all_papers = load_json(db_file, [])
    existing_papers = {}
    original_ordered_keys = []
    lookup = {}
    ambiguous_keys = set()

    def register_lookup_keys(canonical_key, paper):
        for lookup_key in paper_lookup_keys(paper):
            if not lookup_key:
                continue
            current = lookup.get(lookup_key)
            if current and current != canonical_key:
                ambiguous_keys.add(lookup_key)
                lookup.pop(lookup_key, None)
            elif lookup_key not in ambiguous_keys:
                lookup[lookup_key] = canonical_key

    for paper in all_papers:
        key = paper_identity_key(paper)
        if key and key not in existing_papers:
            existing_papers[key] = paper
            original_ordered_keys.append(key)
            register_lookup_keys(key, paper)
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
                    if is_junk_paper(title, abstract, row):
                        continue
                    if not title or not abstract or abstract.upper() == "NA":
                        continue

                    paper_obj = build_paper_from_row(row)
                    paper_key = paper_identity_key(paper_obj)
                    if not paper_key:
                        continue

                    canonical_key = None
                    for lookup_key in paper_lookup_keys(paper_obj):
                        if lookup_key in lookup:
                            canonical_key = lookup[lookup_key]
                            break
                    if canonical_key is None:
                        canonical_key = paper_key

                    if canonical_key not in current_keys:
                        ordered_keys.append(canonical_key)
                    current_keys.add(canonical_key)

                    existing_paper = existing_papers.get(canonical_key)
                    if existing_paper is None:
                        existing_papers[canonical_key] = paper_obj
                        register_lookup_keys(canonical_key, paper_obj)
                        new_in_file += 1
                    else:
                        merged_paper, changed, embedding_changed = _merge_paper_from_source(
                            existing_paper,
                            paper_obj,
                            allow_core_updates=True,
                        )
                        if not changed:
                            continue
                        if embedding_changed:
                            cache_invalidating_update_count += 1
                        existing_papers[canonical_key] = merged_paper
                        register_lookup_keys(canonical_key, merged_paper)
                        updated_in_file += 1

            if new_in_file > 0:
                new_files_info[os.path.relpath(file, source_root)] = new_in_file
            if updated_in_file > 0:
                updated_files_info[os.path.relpath(file, source_root)] = updated_in_file
        except Exception as exc:
            failed_files.append(os.path.relpath(file, source_root).replace("\\", "/"))
            if logger:
                logger.warning("Error reading CSV %s: %s", file, exc)

    if failed_files:
        removal_skip_reasons.append("source read failed: " + ", ".join(failed_files[:5]))

    if removal_skip_reasons:
        if logger:
            logger.warning(
                "Skipping paper removals because this source scan may be incomplete: %s",
                "; ".join(removal_skip_reasons),
            )
        for paper_key in original_ordered_keys:
            if paper_key not in current_keys:
                ordered_keys.append(paper_key)
                current_keys.add(paper_key)
        removed_count = 0
    else:
        removed_count = len(original_keys - current_keys)
    added_count = sum(new_files_info.values())
    updated_count = sum(updated_files_info.values())
    final_papers = [existing_papers[paper_key] for paper_key in ordered_keys]

    if added_count > 0 or updated_count > 0 or removed_count > 0:
        save_json(db_file, final_papers)
        if (added_count > 0 or removed_count > 0 or cache_invalidating_update_count > 0) and logger:
            logger.info("Embedding cache preserved; changed papers will be repaired by fingerprint reuse.")

    file_summaries = [f"{path} (+{count} added)" for path, count in new_files_info.items()]
    file_summaries.extend([f"{path} ({count} updated)" for path, count in updated_files_info.items()])
    if removal_skip_reasons:
        file_summaries.append("Removals skipped: " + "; ".join(removal_skip_reasons))
    refresh_source_manifest(source_root=source_root, manifest_path=manifest_path, logger=logger)
    return added_count, updated_count, removed_count, file_summaries


def enrich_bibliographic_metadata(db_file, source_root=SOURCE_CSV_DIR, manifest_path=SOURCE_MANIFEST_FILE, logger=None):
    csv_files = list_source_csv_files(source_root=source_root, manifest_path=manifest_path, logger=logger)
    all_papers = load_json(db_file, [])
    lookup = {}
    ambiguous_keys = set()
    for index, paper in enumerate(all_papers):
        for key in paper_lookup_keys(paper):
            if key in lookup and lookup[key] != index:
                ambiguous_keys.add(key)
            else:
                lookup[key] = index
    for key in ambiguous_keys:
        lookup.pop(key, None)

    matched_rows = 0
    updated_papers = set()
    updated_files_info = {}
    skipped_ambiguous = 0

    for file in csv_files:
        updated_in_file = 0
        try:
            with open(file, mode="r", encoding="utf-8-sig", errors="ignore") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    title = normalize_text(row.get("Document Title", ""))
                    abstract = normalize_text(row.get("Abstract", ""))
                    if not title or not abstract or is_junk_paper(title, abstract, row):
                        continue
                    source_paper = build_paper_from_row(row)
                    candidate_indexes = []
                    for key in paper_lookup_keys(source_paper):
                        if key in ambiguous_keys:
                            skipped_ambiguous += 1
                            continue
                        if key in lookup:
                            candidate_indexes.append(lookup[key])
                    candidate_indexes = list(dict.fromkeys(candidate_indexes))
                    if len(candidate_indexes) != 1:
                        continue
                    matched_rows += 1
                    index = candidate_indexes[0]
                    merged_paper, changed, _ = _merge_paper_from_source(
                        all_papers[index],
                        source_paper,
                        allow_core_updates=False,
                    )
                    if changed:
                        all_papers[index] = merged_paper
                        updated_papers.add(index)
                        updated_in_file += 1
            if updated_in_file:
                updated_files_info[os.path.relpath(file, source_root)] = updated_in_file
        except Exception as exc:
            if logger:
                logger.warning("Error enriching metadata from CSV %s: %s", file, exc)

    if updated_papers:
        save_json(db_file, all_papers)

    refresh_source_manifest(source_root=source_root, manifest_path=manifest_path, logger=logger)
    return {
        "matched_rows": matched_rows,
        "updated_count": len(updated_papers),
        "skipped_ambiguous": skipped_ambiguous,
        "updated_files": updated_files_info,
        "source_count": len(csv_files),
    }
