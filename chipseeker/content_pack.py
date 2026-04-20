import errno
import io
import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone

from chipseeker.paths import CONTENT_PACK_EXPORT_DIR
from chipseeker.utils import load_json
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


def _uploaded_bytes(uploaded_file):
    if hasattr(uploaded_file, "getvalue"):
        return uploaded_file.getvalue()
    if hasattr(uploaded_file, "read"):
        return uploaded_file.read()
    raise TypeError("Unsupported uploaded content pack object.")


def install_content_pack(uploaded_file, data_dir):
    payload = _uploaded_bytes(uploaded_file)
    data_dir = os.path.abspath(data_dir)
    staging_parent = os.path.dirname(data_dir)
    os.makedirs(staging_parent, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="chipseeker_content_pack_", dir=staging_parent) as temp_dir:
            with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
                member_names = archive.namelist()
                _validate_zip_members(member_names)
                _ensure_install_space(staging_parent, _archive_uncompressed_size(archive))
                archive.extractall(temp_dir)
            pack_root = _locate_pack_root(temp_dir)
            os.makedirs(data_dir, exist_ok=True)
            _clear_existing_targets(data_dir)

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
            shutil.move(os.path.join(root, file_name), os.path.join(target_root, file_name))
            copied_files += 1
    return copied_files


def install_content_update_pack(uploaded_file, data_dir):
    payload = _uploaded_bytes(uploaded_file)
    data_dir = os.path.abspath(data_dir)
    staging_parent = os.path.dirname(data_dir)
    os.makedirs(staging_parent, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="chipseeker_update_pack_", dir=staging_parent) as temp_dir:
            with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
                member_names = archive.namelist()
                _validate_zip_members(member_names)
                _ensure_install_space(staging_parent, _archive_uncompressed_size(archive))
                archive.extractall(temp_dir)
            pack_root = _locate_pack_root(temp_dir)
            os.makedirs(data_dir, exist_ok=True)

            copied_files = 0
            for relative_dir in PACK_DIRS:
                source_dir = os.path.join(pack_root, relative_dir)
                if os.path.isdir(source_dir):
                    copied_files += _merge_tree(source_dir, os.path.join(data_dir, relative_dir))
    except OSError as exc:
        if exc.errno == errno.ENOSPC:
            free_bytes = shutil.disk_usage(staging_parent).free
            raise ContentPackInstallError(
                "Disk became full while installing the update pack. "
                f"Available now: {_format_bytes(free_bytes)}. "
                "Please free more space on the ChipSeeker install drive and retry."
            ) from exc
        raise

    return {"copied_entries": copied_files, "data_dir": data_dir}


def install_bundled_demo_csv(demo_csv_path, source_root):
    if not os.path.exists(demo_csv_path):
        raise FileNotFoundError(f"Bundled demo CSV not found: {demo_csv_path}")
    target_dir = os.path.join(source_root, "generated_exports")
    os.makedirs(target_dir, exist_ok=True)
    target_path = os.path.join(target_dir, os.path.basename(demo_csv_path))
    shutil.copy2(demo_csv_path, target_path)
    return target_path
