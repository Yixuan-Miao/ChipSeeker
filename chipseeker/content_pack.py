import errno
import hashlib
import io
import json
import os
import shutil
import time
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone

from chipseeker.paths import CONTENT_PACK_EXPORT_DIR, CONTENT_PACK_STATE_FILE
from chipseeker.utils import load_json, normalize_doi, normalize_text, normalize_title, save_json
from chipseeker.version import APP_VERSION
from search_runtime import describe_cache_status


PACK_ROOT_NAME = "local_data"
PACK_FILES = [
    "isscc_papers.json",
    "user_data.json",
    "user_stats.json",
    "venue_metrics.json",
    "results.json",
    "source_manifest.json",
    "schema_state.json",
    "conflict_resolutions.json",
    "source_registry.json",
]
PACK_DIRS = ["sources", "cache"]


class ContentPackInstallError(RuntimeError):
    pass


@contextmanager
def _safe_temporary_directory(prefix, parent_dir):
    parent = os.path.realpath(parent_dir)
    os.makedirs(parent, exist_ok=True)
    temp_dir = os.path.realpath(os.path.join(parent, f"{prefix}{uuid.uuid4().hex}"))
    os.makedirs(temp_dir)
    try:
        yield temp_dir
    finally:
        if temp_dir != parent and os.path.commonpath([parent, temp_dir]) == parent:
            shutil.rmtree(temp_dir, ignore_errors=True)


def _read_papers(db_file):
    papers = load_json(db_file, [])
    return papers if isinstance(papers, list) else []


def _paper_identity_key(paper):
    title = normalize_title((paper or {}).get("title", ""))
    year = normalize_text((paper or {}).get("year", ""))
    venue = normalize_text((paper or {}).get("venue", "")).lower()
    doi = normalize_doi((paper or {}).get("doi", ""))
    looks_like_textbook = "textbook" in venue
    if doi and not looks_like_textbook:
        return f"doi::{doi}"
    if title and year:
        return f"title_year::{title}::{year}"
    return f"title::{title}" if title else ""


def _paper_fingerprint(paper):
    payload = json.dumps(paper or {}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _sha1_file(path):
    digest = hashlib.sha1()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_state(data_dir):
    source_root = os.path.join(data_dir, "sources")
    files = {}
    if not os.path.isdir(source_root):
        return files
    for root, _, names in os.walk(source_root):
        for name in names:
            path = os.path.join(root, name)
            relative = os.path.relpath(path, data_dir).replace("\\", "/")
            stat = os.stat(path)
            files[relative] = {
                "sha1": _sha1_file(path),
                "size_bytes": int(stat.st_size),
            }
    return files


def _cache_state(cache_dir):
    files = {}
    if not os.path.isdir(cache_dir):
        return files
    for name in sorted(os.listdir(cache_dir)):
        if not name.endswith(".npy"):
            continue
        cache_path = os.path.join(cache_dir, name)
        meta_name = name[:-4] + ".meta.json"
        meta_path = os.path.join(cache_dir, meta_name)
        meta = load_json(meta_path, {}) if os.path.exists(meta_path) else {}
        files[name] = {
            "sha1": _sha1_file(cache_path),
            "size_bytes": int(os.path.getsize(cache_path)),
            "meta_name": meta_name,
            "fingerprints": meta.get("fingerprints", []) if isinstance(meta, dict) else [],
        }
    return files


def _content_pack_state(data_dir, db_file, cache_dir, baseline_kind="snapshot"):
    papers = _read_papers(db_file)
    paper_entries = {}
    ordered_papers = []
    for paper in papers:
        key = _paper_identity_key(paper)
        if not key:
            continue
        fingerprint = _paper_fingerprint(paper)
        paper_entries[key] = fingerprint
        ordered_papers.append({"key": key, "fingerprint": fingerprint})
    return {
        "state_version": 1,
        "app_version": APP_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "baseline_kind": baseline_kind,
        "db_file": os.path.abspath(db_file),
        "paper_count": len(papers),
        "papers": paper_entries,
        "paper_order": ordered_papers,
        "sources": _source_state(data_dir),
        "caches": _cache_state(cache_dir),
    }


def _save_pack_state(state, state_path=CONTENT_PACK_STATE_FILE):
    save_json(state_path, state)


def _default_state_path(data_dir, state_path=None):
    return state_path or os.path.join(data_dir, "content_pack_state.json")


def detect_content_pack_status(data_dir, db_file, cache_dir, manifest_path, schema_state=None):
    state = schema_state if isinstance(schema_state, dict) else {}
    library_sync = state.get("library_sync", {}) if isinstance(state, dict) else {}
    manifest = load_json(manifest_path, {"entries": []})
    entries = manifest.get("entries", []) if isinstance(manifest, dict) else []
    cache_files = sorted(
        name for name in os.listdir(cache_dir)
        if os.path.isfile(os.path.join(cache_dir, name)) and name.endswith(".npy")
    ) if os.path.isdir(cache_dir) else []
    paper_count = int(library_sync.get("db_record_count", 0) or 0)
    if paper_count == 0 and os.path.exists(db_file):
        paper_count = len(load_json(db_file, []))
    minilm_cache_status = describe_cache_status(db_file, "all-MiniLM-L6-v2", scope_key="all") if os.path.exists(db_file) else {}
    return {
        "data_dir": data_dir,
        "pack_ready": os.path.exists(db_file) and paper_count > 0,
        "db_exists": os.path.exists(db_file),
        "paper_count": paper_count,
        "source_count": sum(1 for entry in entries if entry.get("valid_source")),
        "cache_count": len(cache_files),
        "has_minilm_cache": bool(minilm_cache_status.get("up_to_date")),
        "cache_files": cache_files,
        "last_synced_at_utc": library_sync.get("last_synced_at_utc", ""),
    }


def _pack_manifest(content_status, pack_kind="full", paper_delta_count=0, paper_removed_count=0):
    return {
        "pack_version": 1,
        "pack_kind": pack_kind,
        "app_version": APP_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "paper_count": content_status.get("paper_count", 0),
        "paper_delta_count": int(paper_delta_count or 0),
        "paper_removed_count": int(paper_removed_count or 0),
        "source_count": content_status.get("source_count", 0),
        "cache_count": content_status.get("cache_count", 0),
        "has_minilm_cache": bool(content_status.get("has_minilm_cache")),
    }


def refresh_content_pack_baseline(data_dir, db_file, cache_dir, state_path=None, baseline_kind="full"):
    state_path = _default_state_path(data_dir, state_path)
    _save_pack_state(_content_pack_state(data_dir, db_file, cache_dir, baseline_kind=baseline_kind), state_path=state_path)
    return state_path


def describe_content_update_status(data_dir, db_file, state_path=None):
    """Return a lightweight summary for deciding whether an update ZIP is needed."""
    state_path = _default_state_path(data_dir, state_path)
    baseline = load_json(state_path, {})
    papers = _read_papers(db_file)
    current_paper_count = len(papers)
    if not isinstance(baseline, dict) or not baseline.get("papers"):
        return {
            "baseline_ready": False,
            "baseline_kind": "",
            "baseline_created_at_utc": "",
            "baseline_paper_count": 0,
            "current_paper_count": current_paper_count,
            "paper_delta_count": current_paper_count,
            "paper_removed_count": 0,
        }

    baseline_papers = baseline.get("papers", {}) if isinstance(baseline.get("papers"), dict) else {}
    delta_count = 0
    current_keys = set()
    for paper in papers:
        key = _paper_identity_key(paper)
        if key:
            current_keys.add(key)
        if key and baseline_papers.get(key) != _paper_fingerprint(paper):
            delta_count += 1
    return {
        "baseline_ready": True,
        "baseline_kind": baseline.get("baseline_kind", "baseline"),
        "baseline_created_at_utc": baseline.get("created_at_utc", ""),
        "baseline_paper_count": int(baseline.get("paper_count", 0) or 0),
        "current_paper_count": current_paper_count,
        "paper_delta_count": delta_count,
        "paper_removed_count": sum(key not in current_keys for key in baseline_papers),
    }


def build_content_pack(data_dir, db_file, cache_dir, manifest_path, schema_state=None, output_dir=CONTENT_PACK_EXPORT_DIR, pack_name=None, state_path=None, save_state=True):
    os.makedirs(output_dir, exist_ok=True)
    content_status = detect_content_pack_status(data_dir, db_file, cache_dir, manifest_path, schema_state=schema_state)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = pack_name or f"ChipSeeker_ContentPack_{timestamp}.zip"
    if not filename.lower().endswith(".zip"):
        filename = f"{filename}.zip"
    zip_path = os.path.join(output_dir, filename)
    included_files = []

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative_name in PACK_FILES:
            source_path = os.path.join(data_dir, relative_name)
            if not os.path.exists(source_path):
                continue
            archive.write(source_path, arcname=f"{PACK_ROOT_NAME}/{relative_name}")
            included_files.append(relative_name)
        for relative_dir in PACK_DIRS:
            source_dir = os.path.join(data_dir, relative_dir)
            if not os.path.isdir(source_dir):
                continue
            for root, _, files in os.walk(source_dir):
                for file_name in files:
                    source_path = os.path.join(root, file_name)
                    arcname = os.path.join(PACK_ROOT_NAME, os.path.relpath(source_path, data_dir)).replace("\\", "/")
                    archive.write(source_path, arcname=arcname)
                    included_files.append(arcname)
        archive.writestr("content_pack_manifest.json", json.dumps(_pack_manifest(content_status, pack_kind="full"), indent=2, ensure_ascii=False))

    if save_state:
        refresh_content_pack_baseline(data_dir, db_file, cache_dir, state_path=state_path, baseline_kind="full")

    return {
        "zip_path": zip_path,
        "paper_count": content_status["paper_count"],
        "source_count": content_status["source_count"],
        "cache_count": content_status["cache_count"],
        "included_count": len(included_files),
    }


def build_content_update_pack(
    data_dir,
    db_file,
    cache_dir,
    manifest_path,
    schema_state=None,
    output_dir=CONTENT_PACK_EXPORT_DIR,
    pack_name=None,
    state_path=None,
    save_state=True,
):
    state_path = _default_state_path(data_dir, state_path)
    baseline = load_json(state_path, {})
    if not isinstance(baseline, dict) or not baseline.get("papers"):
        raise ContentPackInstallError("No previous content-pack baseline was found. Build one full Content Pack ZIP first.")

    os.makedirs(output_dir, exist_ok=True)
    content_status = detect_content_pack_status(data_dir, db_file, cache_dir, manifest_path, schema_state=schema_state)
    current_state = _content_pack_state(data_dir, db_file, cache_dir, baseline_kind="update")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = pack_name or f"ChipSeeker_ContentUpdate_{timestamp}.zip"
    if not filename.lower().endswith(".zip"):
        filename = f"{filename}.zip"
    zip_path = os.path.join(output_dir, filename)

    baseline_papers = baseline.get("papers", {}) if isinstance(baseline.get("papers"), dict) else {}
    delta_papers = []
    for paper in _read_papers(db_file):
        key = _paper_identity_key(paper)
        if key and baseline_papers.get(key) != _paper_fingerprint(paper):
            delta_papers.append(paper)
    current_paper_keys = set(current_state.get("papers", {}))
    removed_paper_keys = sorted(key for key in baseline_papers if key not in current_paper_keys)

    baseline_sources = baseline.get("sources", {}) if isinstance(baseline.get("sources"), dict) else {}
    current_sources = current_state.get("sources", {})
    changed_sources = [
        relative_path
        for relative_path, info in current_sources.items()
        if baseline_sources.get(relative_path, {}).get("sha1") != info.get("sha1")
    ]

    baseline_caches = baseline.get("caches", {}) if isinstance(baseline.get("caches"), dict) else {}
    included_files = []
    cache_delta_count = 0
    cache_full_count = 0
    temp_parent = os.path.join(output_dir, "_tmp")
    os.makedirs(temp_parent, exist_ok=True)
    with _safe_temporary_directory("chipseeker_update_build_", temp_parent) as temp_dir:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                f"{PACK_ROOT_NAME}/isscc_papers.delta.json",
                json.dumps(delta_papers, indent=2, ensure_ascii=False),
            )
            included_files.append("isscc_papers.delta.json")
            archive.writestr(
                f"{PACK_ROOT_NAME}/isscc_papers.removed.json",
                json.dumps(removed_paper_keys, indent=2, ensure_ascii=False),
            )
            included_files.append("isscc_papers.removed.json")

            for relative_path in changed_sources:
                source_path = os.path.join(data_dir, relative_path.replace("/", os.sep))
                if os.path.exists(source_path):
                    archive.write(source_path, arcname=f"{PACK_ROOT_NAME}/{relative_path}")
                    included_files.append(relative_path)

            for cache_name, cache_info in current_state.get("caches", {}).items():
                source_cache = os.path.join(cache_dir, cache_name)
                source_meta = os.path.join(cache_dir, cache_info.get("meta_name", cache_name[:-4] + ".meta.json"))
                baseline_cache = baseline_caches.get(cache_name) or {}
                old_fingerprints = baseline_cache.get("fingerprints", [])
                new_fingerprints = cache_info.get("fingerprints", [])
                cache_payload_written = False
                if (
                    old_fingerprints
                    and new_fingerprints
                    and len(new_fingerprints) > len(old_fingerprints)
                    and new_fingerprints[:len(old_fingerprints)] == old_fingerprints
                    and os.path.exists(source_cache)
                ):
                    import numpy as np

                    embeddings = np.load(source_cache, mmap_mode="r")
                    if embeddings.shape[0] == len(new_fingerprints):
                        delta_array = embeddings[len(old_fingerprints):]
                        delta_name = f"{cache_name}.delta.npy"
                        delta_path = os.path.join(temp_dir, delta_name)
                        np.save(delta_path, delta_array)
                        archive.write(delta_path, arcname=f"{PACK_ROOT_NAME}/cache_delta/{delta_name}")
                        archive.writestr(
                            f"{PACK_ROOT_NAME}/cache_delta/{cache_name}.delta.meta.json",
                            json.dumps(
                                {
                                    "target_cache": cache_name,
                                    "target_meta": cache_info.get("meta_name", cache_name[:-4] + ".meta.json"),
                                    "old_fingerprints": old_fingerprints,
                                    "new_fingerprints": new_fingerprints,
                                    "delta_count": len(new_fingerprints) - len(old_fingerprints),
                                },
                                indent=2,
                                ensure_ascii=False,
                            ),
                        )
                        cache_delta_count += len(new_fingerprints) - len(old_fingerprints)
                        included_files.append(f"cache_delta/{delta_name}")
                        cache_payload_written = True
                if not cache_payload_written and cache_name not in baseline_caches and os.path.exists(source_cache):
                    archive.write(source_cache, arcname=f"{PACK_ROOT_NAME}/cache/{cache_name}")
                    included_files.append(f"cache/{cache_name}")
                    if os.path.exists(source_meta):
                        archive.write(source_meta, arcname=f"{PACK_ROOT_NAME}/cache/{os.path.basename(source_meta)}")
                        included_files.append(f"cache/{os.path.basename(source_meta)}")
                    cache_full_count += 1
                elif (
                    not cache_payload_written
                    and baseline_cache
                    and os.path.exists(source_cache)
                    and (
                        baseline_cache.get("fingerprints", []) != new_fingerprints
                        or baseline_cache.get("sha1", "") != cache_info.get("sha1", "")
                    )
                ):
                    archive.write(source_cache, arcname=f"{PACK_ROOT_NAME}/cache/{cache_name}")
                    included_files.append(f"cache/{cache_name}")
                    if os.path.exists(source_meta):
                        archive.write(source_meta, arcname=f"{PACK_ROOT_NAME}/cache/{os.path.basename(source_meta)}")
                        included_files.append(f"cache/{os.path.basename(source_meta)}")
                    cache_full_count += 1

            archive.writestr(
                "content_pack_manifest.json",
                json.dumps(
                    _pack_manifest(
                        content_status,
                        pack_kind="update",
                        paper_delta_count=len(delta_papers),
                        paper_removed_count=len(removed_paper_keys),
                    ),
                    indent=2,
                    ensure_ascii=False,
                ),
            )

    if save_state:
        _save_pack_state(current_state, state_path=state_path)
    return {
        "zip_path": zip_path,
        "paper_count": content_status["paper_count"],
        "paper_delta_count": len(delta_papers),
        "paper_removed_count": len(removed_paper_keys),
        "source_delta_count": len(changed_sources),
        "cache_delta_count": cache_delta_count,
        "cache_full_count": cache_full_count,
        "included_count": len(included_files),
    }


def _validate_zip_members(member_names):
    for member in member_names:
        normalized = member.replace("\\", "/")
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError(f"Unsafe content pack path: {member}")


def _format_bytes(size):
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024


def _archive_uncompressed_size(archive):
    return sum(info.file_size for info in archive.infolist() if not info.is_dir())


def _ensure_install_space(target_parent, required_bytes):
    os.makedirs(target_parent, exist_ok=True)
    free_bytes = shutil.disk_usage(target_parent).free
    required_with_margin = max(int(required_bytes * 1.25), required_bytes + 512 * 1024 * 1024)
    if free_bytes < required_with_margin:
        raise ContentPackInstallError(
            "Not enough disk space to install this content pack. "
            f"Required: {_format_bytes(required_with_margin)} free, available: {_format_bytes(free_bytes)}. "
            "Please free space on the ChipSeeker install drive or move ChipSeeker to a larger drive, then retry. "
            "磁盘空间不足，无法安装内容包。请清理 ChipSeeker 所在磁盘，或把 ChipSeeker 移到更大的磁盘后重试。"
        )


def _locate_pack_root(extract_root):
    candidate = os.path.join(extract_root, PACK_ROOT_NAME)
    if os.path.isdir(candidate):
        return candidate
    for root, dirs, _ in os.walk(extract_root):
        if PACK_ROOT_NAME in dirs:
            return os.path.join(root, PACK_ROOT_NAME)
    if any(os.path.exists(os.path.join(extract_root, name)) for name in PACK_FILES + PACK_DIRS):
        return extract_root
    raise FileNotFoundError("Could not locate local_data root in the content pack.")


def _clear_existing_targets(data_dir):
    for relative_name in PACK_FILES:
        target_file = os.path.join(data_dir, relative_name)
        if os.path.exists(target_file):
            os.remove(target_file)
    for relative_dir in PACK_DIRS:
        target_dir = os.path.join(data_dir, relative_dir)
        if os.path.isdir(target_dir):
            shutil.rmtree(target_dir)


def _move_existing_targets_to_backup(data_dir, backup_dir):
    os.makedirs(backup_dir, exist_ok=True)
    for relative_name in PACK_FILES:
        target_file = os.path.join(data_dir, relative_name)
        if os.path.exists(target_file):
            backup_file = os.path.join(backup_dir, relative_name)
            os.makedirs(os.path.dirname(backup_file), exist_ok=True)
            shutil.move(target_file, backup_file)
    for relative_dir in PACK_DIRS:
        target_dir = os.path.join(data_dir, relative_dir)
        if os.path.isdir(target_dir):
            backup_target = os.path.join(backup_dir, relative_dir)
            os.makedirs(os.path.dirname(backup_target), exist_ok=True)
            shutil.move(target_dir, backup_target)


def _backup_contains_targets(backup_dir):
    if not os.path.isdir(backup_dir):
        return False
    for relative_name in PACK_FILES:
        if os.path.exists(os.path.join(backup_dir, relative_name)):
            return True
    for relative_dir in PACK_DIRS:
        if os.path.isdir(os.path.join(backup_dir, relative_dir)):
            return True
    return False


def _restore_existing_targets_from_backup(data_dir, backup_dir, clear_existing=True):
    if not _backup_contains_targets(backup_dir):
        return
    if clear_existing:
        _clear_existing_targets(data_dir)
    for relative_name in PACK_FILES:
        backup_file = os.path.join(backup_dir, relative_name)
        if os.path.exists(backup_file):
            target_file = os.path.join(data_dir, relative_name)
            os.makedirs(os.path.dirname(target_file), exist_ok=True)
            shutil.move(backup_file, target_file)
    for relative_dir in PACK_DIRS:
        backup_dir_path = os.path.join(backup_dir, relative_dir)
        if os.path.isdir(backup_dir_path):
            target_dir = os.path.join(data_dir, relative_dir)
            os.makedirs(os.path.dirname(target_dir), exist_ok=True)
            shutil.move(backup_dir_path, target_dir)


def _uploaded_bytes(uploaded_file):
    if hasattr(uploaded_file, "getvalue"):
        return uploaded_file.getvalue()
    if hasattr(uploaded_file, "read"):
        return uploaded_file.read()
    raise TypeError("Unsupported uploaded content pack object.")


def content_pack_kind(uploaded_file):
    payload = _uploaded_bytes(uploaded_file)
    try:
        with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
            _validate_zip_members(archive.namelist())
            try:
                manifest = json.loads(archive.read("content_pack_manifest.json").decode("utf-8"))
            except (KeyError, UnicodeError, json.JSONDecodeError):
                manifest = {}
    except zipfile.BadZipFile as exc:
        raise ContentPackInstallError("The selected file is not a valid ChipSeeker ZIP package.") from exc
    kind = str(manifest.get("pack_kind", "full") or "full").strip().lower()
    if kind not in {"full", "update"}:
        raise ContentPackInstallError(f"Unsupported ChipSeeker content pack kind: {kind}")
    return kind, payload


def install_content_package(uploaded_file, data_dir):
    """Install either a full member package or an incremental update package."""
    kind, payload = content_pack_kind(uploaded_file)
    stream = io.BytesIO(payload)
    result = install_content_update_pack(stream, data_dir) if kind == "update" else install_content_pack(stream, data_dir)
    result["pack_kind"] = kind
    return result


def install_content_pack(uploaded_file, data_dir):
    payload = _uploaded_bytes(uploaded_file)
    data_dir = os.path.abspath(data_dir)
    staging_parent = os.path.dirname(data_dir)
    os.makedirs(staging_parent, exist_ok=True)
    try:
        with _safe_temporary_directory("chipseeker_content_pack_", staging_parent) as temp_dir:
            with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
                member_names = archive.namelist()
                _validate_zip_members(member_names)
                declared_size = _archive_uncompressed_size(archive)
                _ensure_install_space(staging_parent, declared_size)
                archive.extractall(temp_dir)
                # ZIP bomb check: actual extracted size must not exceed 2x declared.
                actual_size = 0
                for _root, _, _files in os.walk(temp_dir):
                    for _name in _files:
                        actual_size += os.path.getsize(os.path.join(_root, _name))
                if actual_size > declared_size * 2:
                    raise ContentPackInstallError(
                        "Content pack extraction exceeded expected size: "
                        f"declared={_format_bytes(declared_size)}, actual={_format_bytes(actual_size)}. "
                        "This may indicate a malicious ZIP bomb. Installation aborted."
                    )
            pack_root = _locate_pack_root(temp_dir)
            os.makedirs(data_dir, exist_ok=True)
            backup_dir = os.path.join(temp_dir, "previous_local_data")
            backup_complete = False
            try:
                _move_existing_targets_to_backup(data_dir, backup_dir)
                backup_complete = True

                copied_files = 0
                for relative_name in PACK_FILES:
                    source_file = os.path.join(pack_root, relative_name)
                    if os.path.exists(source_file):
                        shutil.move(source_file, os.path.join(data_dir, relative_name))
                        copied_files += 1
                for relative_dir in PACK_DIRS:
                    source_dir = os.path.join(pack_root, relative_dir)
                    if os.path.isdir(source_dir):
                        copied_files += sum(len(files) for _, _, files in os.walk(source_dir))
                        shutil.move(source_dir, os.path.join(data_dir, relative_dir))
            except Exception:
                _restore_existing_targets_from_backup(data_dir, backup_dir, clear_existing=backup_complete)
                raise
    except OSError as exc:
        if exc.errno == errno.ENOSPC:
            free_bytes = shutil.disk_usage(staging_parent).free
            raise ContentPackInstallError(
                "Disk became full while installing the content pack. "
                f"Available now: {_format_bytes(free_bytes)}. "
                "Please free more space on the ChipSeeker install drive and retry. "
                "安装内容包时磁盘已满，请清理 ChipSeeker 所在磁盘后重试。"
            ) from exc
        raise

    return {"copied_entries": copied_files, "data_dir": data_dir}


def _merge_tree(source_dir, target_dir):
    copied_files = 0
    os.makedirs(target_dir, exist_ok=True)
    for root, _, files in os.walk(source_dir):
        relative_root = os.path.relpath(root, source_dir)
        target_root = target_dir if relative_root == "." else os.path.join(target_dir, relative_root)
        os.makedirs(target_root, exist_ok=True)
        for file_name in files:
            source_path = os.path.join(root, file_name)
            target_path = os.path.join(target_root, file_name)
            if os.path.exists(target_path):
                replaced = False
                for attempt in range(3):
                    try:
                        os.replace(source_path, target_path)
                        replaced = True
                        break
                    except PermissionError:
                        if attempt < 2:
                            time.sleep(0.1 * (attempt + 1))
                if not replaced:
                    shutil.copy2(source_path, target_path)
                    os.remove(source_path)
            else:
                shutil.move(source_path, target_path)
            copied_files += 1
    return copied_files


def _merge_delta_papers(pack_root, data_dir):
    delta_file = os.path.join(pack_root, "isscc_papers.delta.json")
    if not os.path.exists(delta_file):
        return {"added": 0, "updated": 0, "skipped": 0}
    delta_papers = load_json(delta_file, [])
    if not isinstance(delta_papers, list) or not delta_papers:
        return {"added": 0, "updated": 0, "skipped": 0}

    target_db = os.path.join(data_dir, "isscc_papers.json")
    existing_papers = _read_papers(target_db)
    key_to_index = {}
    for index, paper in enumerate(existing_papers):
        key = _paper_identity_key(paper)
        if key and key not in key_to_index:
            key_to_index[key] = index

    added = 0
    updated = 0
    skipped = 0
    for paper in delta_papers:
        key = _paper_identity_key(paper)
        if not key:
            skipped += 1
            continue
        existing_index = key_to_index.get(key)
        if existing_index is None:
            key_to_index[key] = len(existing_papers)
            existing_papers.append(paper)
            added += 1
            continue
        if _paper_fingerprint(existing_papers[existing_index]) == _paper_fingerprint(paper):
            skipped += 1
            continue
        existing_papers[existing_index] = paper
        updated += 1

    save_json(target_db, existing_papers)
    return {"added": added, "updated": updated, "skipped": skipped}


def _remove_delta_papers(pack_root, data_dir):
    removed_file = os.path.join(pack_root, "isscc_papers.removed.json")
    removed_keys = load_json(removed_file, []) if os.path.exists(removed_file) else []
    if not isinstance(removed_keys, list) or not removed_keys:
        return 0
    targets = {str(key) for key in removed_keys if str(key)}
    if not targets:
        return 0

    target_db = os.path.join(data_dir, "isscc_papers.json")
    existing_papers = _read_papers(target_db)
    kept_papers = [paper for paper in existing_papers if _paper_identity_key(paper) not in targets]
    removed_count = len(existing_papers) - len(kept_papers)
    if removed_count:
        save_json(target_db, kept_papers)
    return removed_count


def _append_cache_deltas(pack_root, data_dir):
    cache_delta_dir = os.path.join(pack_root, "cache_delta")
    if not os.path.isdir(cache_delta_dir):
        return {"appended": 0, "skipped": 0}
    target_cache_dir = os.path.join(data_dir, "cache")
    os.makedirs(target_cache_dir, exist_ok=True)
    appended = 0
    skipped = 0
    for name in sorted(os.listdir(cache_delta_dir)):
        if not name.endswith(".delta.meta.json"):
            continue
        delta_meta = load_json(os.path.join(cache_delta_dir, name), {})
        target_cache_name = delta_meta.get("target_cache", "")
        target_meta_name = delta_meta.get("target_meta", "")
        if not target_cache_name or not target_meta_name:
            skipped += 1
            continue
        delta_array_path = os.path.join(cache_delta_dir, f"{target_cache_name}.delta.npy")
        target_cache_path = os.path.join(target_cache_dir, target_cache_name)
        target_meta_path = os.path.join(target_cache_dir, target_meta_name)
        if not (os.path.exists(delta_array_path) and os.path.exists(target_cache_path) and os.path.exists(target_meta_path)):
            skipped += 1
            continue
        target_meta = load_json(target_meta_path, {})
        old_fingerprints = delta_meta.get("old_fingerprints", [])
        new_fingerprints = delta_meta.get("new_fingerprints", [])
        if target_meta.get("fingerprints", []) != old_fingerprints:
            skipped += 1
            continue
        import numpy as np

        existing = np.load(target_cache_path)
        delta = np.load(delta_array_path)
        if existing.shape[0] != len(old_fingerprints) or delta.shape[0] != len(new_fingerprints) - len(old_fingerprints):
            skipped += 1
            continue
        merged = np.vstack((existing, delta))
        temp_cache_path = f"{target_cache_path}.tmp.npy"
        np.save(temp_cache_path, merged)
        os.replace(temp_cache_path, target_cache_path)
        target_meta["fingerprints"] = new_fingerprints
        save_json(target_meta_path, target_meta)
        appended += int(delta.shape[0])
    return {"appended": appended, "skipped": skipped}


def install_content_update_pack(uploaded_file, data_dir):
    payload = _uploaded_bytes(uploaded_file)
    data_dir = os.path.abspath(data_dir)
    staging_parent = os.path.dirname(data_dir)
    os.makedirs(staging_parent, exist_ok=True)
    try:
        with _safe_temporary_directory("chipseeker_update_pack_", staging_parent) as temp_dir:
            with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
                member_names = archive.namelist()
                _validate_zip_members(member_names)
                declared_size = _archive_uncompressed_size(archive)
                _ensure_install_space(staging_parent, declared_size)
                archive.extractall(temp_dir)
                # ZIP bomb check: actual extracted size must not exceed 2x declared.
                actual_size = 0
                for _root, _, _files in os.walk(temp_dir):
                    for _name in _files:
                        actual_size += os.path.getsize(os.path.join(_root, _name))
                if actual_size > declared_size * 2:
                    raise ContentPackInstallError(
                        "Update pack extraction exceeded expected size: "
                        f"declared={_format_bytes(declared_size)}, actual={_format_bytes(actual_size)}. "
                        "This may indicate a malicious ZIP bomb. Installation aborted."
                    )
            pack_root = _locate_pack_root(temp_dir)
            os.makedirs(data_dir, exist_ok=True)

            copied_files = 0
            paper_merge = _merge_delta_papers(pack_root, data_dir)
            paper_removed = _remove_delta_papers(pack_root, data_dir)
            for relative_dir in PACK_DIRS:
                source_dir = os.path.join(pack_root, relative_dir)
                if os.path.isdir(source_dir):
                    copied_files += _merge_tree(source_dir, os.path.join(data_dir, relative_dir))
            cache_merge = _append_cache_deltas(pack_root, data_dir)
    except OSError as exc:
        if exc.errno == errno.ENOSPC:
            free_bytes = shutil.disk_usage(staging_parent).free
            raise ContentPackInstallError(
                "Disk became full while installing the update pack. "
                f"Available now: {_format_bytes(free_bytes)}. "
                "Please free more space on the ChipSeeker install drive and retry."
            ) from exc
        raise

    return {
        "copied_entries": copied_files,
        "data_dir": data_dir,
        "paper_added": paper_merge.get("added", 0),
        "paper_updated": paper_merge.get("updated", 0),
        "paper_skipped": paper_merge.get("skipped", 0),
        "paper_removed": paper_removed,
        "cache_appended": cache_merge.get("appended", 0),
        "cache_skipped": cache_merge.get("skipped", 0),
    }


def install_bundled_demo_csv(demo_csv_path, source_root):
    if not os.path.exists(demo_csv_path):
        raise FileNotFoundError(f"Bundled demo CSV not found: {demo_csv_path}")
    target_dir = os.path.join(source_root, "generated_exports")
    os.makedirs(target_dir, exist_ok=True)
    target_path = os.path.join(target_dir, os.path.basename(demo_csv_path))
    shutil.copy2(demo_csv_path, target_path)
    return target_path
