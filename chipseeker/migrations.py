import os
import shutil
from datetime import datetime, timezone

from chipseeker.paths import (
    CONFLICT_RESOLUTIONS_FILE,
    CURRENT_LOCAL_DATA_VERSION,
    LOCAL_DATA_STATE_FILE,
    MANUAL_SOURCE_DIR,
    SOURCE_REGISTRY_FILE,
    SOURCE_REGISTRY_TEMPLATE_FILE,
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


def _migrate_to_v3(state):
    if not os.path.exists(SOURCE_REGISTRY_FILE):
        template = load_json(SOURCE_REGISTRY_TEMPLATE_FILE, {"sources": [], "pending_ieee_batch": None})
        save_json(SOURCE_REGISTRY_FILE, template)
    _record_state(state, 3, "Initialized source registry for IEEE and Nature incremental updates.")


def _merge_template_sources(state, version, note):
    """Merge new source templates from the bundled template file into the registry."""
    registry = load_json(SOURCE_REGISTRY_FILE, {"sources": [], "pending_ieee_batch": None})
    template = load_json(SOURCE_REGISTRY_TEMPLATE_FILE, {"sources": [], "pending_ieee_batch": None})
    if not isinstance(registry, dict):
        registry = {"sources": [], "pending_ieee_batch": None}
    registry.setdefault("sources", [])
    existing_ids = {source.get("id") for source in registry["sources"]}
    for template_source in template.get("sources", []):
        if template_source.get("id") not in existing_ids:
            registry["sources"].append(template_source)
    save_json(SOURCE_REGISTRY_FILE, registry)
    _record_state(state, version, note)


def _migrate_to_v4(state):
    _merge_template_sources(state, 4, "Merged new default update sources into source registry.")


def _migrate_to_v5(state):
    state.setdefault("library_sync", {})
    _merge_template_sources(state, 5, "Expanded default update sources and initialized product-pack state.")


def _migrate_to_v6(state):
    _merge_template_sources(state, 6, "Expanded Nature-family source templates and refreshed registry defaults.")


def _migrate_to_v7(state):
    # Force one library rescan so existing CSV sources can enrich stored papers
    # with volume/issue/pages/IEEE terms used by BibTeX exports.
    state["library_sync"] = {}
    _record_state(state, 7, "Scheduled bibliographic metadata refresh for IEEE-style BibTeX exports.")


def _migrate_to_v8(state):
    # Force one library rescan so existing CSV sources can enrich stored papers
    # with funding/citation/reference/license fields used by annual reports.
    state["library_sync"] = {}
    _record_state(state, 8, "Scheduled metadata refresh for annual conference report exports.")


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
    if version < 3:
        _migrate_to_v3(state)
        version = 3
    if version < 4:
        _migrate_to_v4(state)
        version = 4
    if version < 5:
        _migrate_to_v5(state)
        version = 5
    if version < 6:
        _migrate_to_v6(state)
        version = 6
    if version < 7:
        _migrate_to_v7(state)
        version = 7
    if version < 8:
        _migrate_to_v8(state)
        version = 8

    if version != CURRENT_LOCAL_DATA_VERSION:
        state["schema_version"] = CURRENT_LOCAL_DATA_VERSION
        state["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    save_json(LOCAL_DATA_STATE_FILE, state)
    return state
