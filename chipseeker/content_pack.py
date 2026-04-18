import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone

from chipseeker.paths import CONTENT_PACK_EXPORT_DIR
from chipseeker.utils import load_json
from chipseeker.version import APP_VERSION
from search_runtime import get_cache_paths


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


def detect_content_pack_status(data_dir, db_file, cache_dir, manifest_path, schema_state=None):
    state = schema_state if isinstance(schema_state, dict) else {}
    library_sync = state.get("library_sync", {}) if isinstance(state, dict) else {}
    manifest = load_json(manifest_path, {"entries": []})
    entries = manifest.get("entries", []) if isinstance(manifest, dict) else []
    cache_files = sorted(
        name for name in os.listdir(cache_dir)
        if os.path.isfile(os.path.join(cache_dir, name)) and name.endswith(".npy")
    ) if os.path.isdir(cache_dir) else []
    minilm_cache_file, _ = get_cache_paths(db_file, "all-MiniLM-L6-v2", scope_key="all")
    paper_count = int(library_sync.get("db_record_count", 0) or 0)
    if paper_count == 0 and os.path.exists(db_file):
        paper_count = len(load_json(db_file, []))
    return {
        "data_dir": data_dir,
        "pack_ready": os.path.exists(db_file) and paper_count > 0,
        "db_exists": os.path.exists(db_file),
        "paper_count": paper_count,
        "source_count": sum(1 for entry in entries if entry.get("valid_source")),
        "cache_count": len(cache_files),
        "has_minilm_cache": os.path.exists(minilm_cache_file),
        "cache_files": cache_files,
        "last_synced_at_utc": library_sync.get("last_synced_at_utc", ""),
    }


def _pack_manifest(content_status):
    return {
        "pack_version": 1,
        "app_version": APP_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "paper_count": content_status.get("paper_count", 0),
        "source_count": content_status.get("source_count", 0),
        "cache_count": content_status.get("cache_count", 0),
        "has_minilm_cache": bool(content_status.get("has_minilm_cache")),
    }


def build_content_pack(data_dir, db_file, cache_dir, manifest_path, schema_state=None, output_dir=CONTENT_PACK_EXPORT_DIR, pack_name=None):
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
        archive.writestr("content_pack_manifest.json", json.dumps(_pack_manifest(content_status), indent=2, ensure_ascii=False))

    return {
        "zip_path": zip_path,
        "paper_count": content_status["paper_count"],
        "source_count": content_status["source_count"],
        "cache_count": content_status["cache_count"],
        "included_count": len(included_files),
    }


def _validate_zip_members(member_names):
    for member in member_names:
        normalized = member.replace("\\", "/")
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError(f"Unsafe content pack path: {member}")


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


def _uploaded_bytes(uploaded_file):
    if hasattr(uploaded_file, "getvalue"):
        return uploaded_file.getvalue()
    if hasattr(uploaded_file, "read"):
        return uploaded_file.read()
    raise TypeError("Unsupported uploaded content pack object.")


def install_content_pack(uploaded_file, data_dir):
    payload = _uploaded_bytes(uploaded_file)
    with tempfile.TemporaryDirectory() as temp_dir:
        zip_path = os.path.join(temp_dir, "content_pack.zip")
        with open(zip_path, "wb") as f:
            f.write(payload)
        with zipfile.ZipFile(zip_path, "r") as archive:
            _validate_zip_members(archive.namelist())
            archive.extractall(temp_dir)
        pack_root = _locate_pack_root(temp_dir)
        os.makedirs(data_dir, exist_ok=True)
        _clear_existing_targets(data_dir)

        copied_files = 0
        for relative_name in PACK_FILES:
            source_file = os.path.join(pack_root, relative_name)
            if os.path.exists(source_file):
                shutil.copy2(source_file, os.path.join(data_dir, relative_name))
                copied_files += 1
        for relative_dir in PACK_DIRS:
            source_dir = os.path.join(pack_root, relative_dir)
            if os.path.isdir(source_dir):
                shutil.copytree(source_dir, os.path.join(data_dir, relative_dir), dirs_exist_ok=True)
                copied_files += sum(len(files) for _, _, files in os.walk(source_dir))

    return {"copied_entries": copied_files, "data_dir": data_dir}


def install_bundled_demo_csv(demo_csv_path, source_root):
    if not os.path.exists(demo_csv_path):
        raise FileNotFoundError(f"Bundled demo CSV not found: {demo_csv_path}")
    target_dir = os.path.join(source_root, "generated_exports")
    os.makedirs(target_dir, exist_ok=True)
    target_path = os.path.join(target_dir, os.path.basename(demo_csv_path))
    shutil.copy2(demo_csv_path, target_path)
    return target_path
