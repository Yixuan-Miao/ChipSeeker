import os
import shutil
from datetime import datetime, timezone

from chipseeker.paths import (
    CONFLICT_RESOLUTIONS_FILE,
    CURRENT_LOCAL_DATA_VERSION,
    LOCAL_DATA_STATE_FILE,
    MANUAL_SOURCE_DIR,
    SOURCE_CSV_DIR,
    SOURCE_MANIFEST_FILE,
)
from chipseeker.utils import load_json, save_json


def _default_state():
    return {
        "schema_version": 0,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "history": [],
    }


def _record_state(state, version, note):
    state["schema_version"] = version
    state["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    state.setdefault("history", []).append(
        {
            "version": version,
            "note": note,
            "applied_at_utc": state["updated_at_utc"],
        }
    )


def _migrate_to_v1(state):
    if os.path.exists(SOURCE_MANIFEST_FILE):
        manifest = load_json(SOURCE_MANIFEST_FILE, [])
        if isinstance(manifest, list):
            save_json(
                SOURCE_MANIFEST_FILE,
                {
                    "schema_version": 1,
                    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                    "entries": manifest,
                },
            )
    if not os.path.exists(CONFLICT_RESOLUTIONS_FILE):
        save_json(CONFLICT_RESOLUTIONS_FILE, {"dismissed": []})
    _record_state(state, 1, "Initialized versioned local_data metadata files.")


def _migrate_to_v2(state):
    os.makedirs(MANUAL_SOURCE_DIR, exist_ok=True)
    for name in sorted(os.listdir(SOURCE_CSV_DIR)):
        source_path = os.path.join(SOURCE_CSV_DIR, name)
        if not os.path.isfile(source_path) or not name.lower().endswith(".csv"):
            continue
        target_path = os.path.join(MANUAL_SOURCE_DIR, name)
        if os.path.abspath(source_path) == os.path.abspath(target_path):
            continue
        shutil.move(source_path, target_path)
    _record_state(state, 2, "Normalized source CSV layout under local_data/sources.")


def migrate_local_data():
    state = load_json(LOCAL_DATA_STATE_FILE, _default_state())
    if not isinstance(state, dict):
        state = _default_state()

    version = int(state.get("schema_version", 0))
    if version < 1:
        _migrate_to_v1(state)
        version = 1
    if version < 2:
        _migrate_to_v2(state)
        version = 2

    if version != CURRENT_LOCAL_DATA_VERSION:
        state["schema_version"] = CURRENT_LOCAL_DATA_VERSION
        state["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    save_json(LOCAL_DATA_STATE_FILE, state)
    return state
