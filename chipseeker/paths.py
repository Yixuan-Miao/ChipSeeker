import os


PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(PACKAGE_DIR)
PACKAGE_DATA_DIR = os.path.join(PACKAGE_DIR, "data")
DATA_DIR = os.path.join(BASE_DIR, "local_data")
SOURCE_CSV_DIR = os.path.join(DATA_DIR, "sources")
MANUAL_SOURCE_DIR = os.path.join(SOURCE_CSV_DIR, "manual")
GENERATED_SOURCE_DIR = os.path.join(SOURCE_CSV_DIR, "generated_exports")
IEEE_UPDATE_DIR = os.path.join(MANUAL_SOURCE_DIR, "ieee_updates")
NATURE_UPDATE_DIR = os.path.join(GENERATED_SOURCE_DIR, "nature_updates")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
EXPORT_DIR = os.path.join(DATA_DIR, "exports")
DOWNLOAD_DIR = os.path.join(DATA_DIR, "downloads")
BACKUP_ROOT_DIR = os.path.join(DATA_DIR, "backups")
DB_FILE = os.path.join(DATA_DIR, "isscc_papers.json")
USER_DATA_FILE = os.path.join(DATA_DIR, "user_data.json")
USER_STATS_FILE = os.path.join(DATA_DIR, "user_stats.json")
VENUE_METRICS_FILE = os.path.join(DATA_DIR, "venue_metrics.json")
RESULTS_FILE = os.path.join(DATA_DIR, "results.json")
SOURCE_MANIFEST_FILE = os.path.join(DATA_DIR, "source_manifest.json")
LOCAL_DATA_STATE_FILE = os.path.join(DATA_DIR, "schema_state.json")
CONFLICT_RESOLUTIONS_FILE = os.path.join(DATA_DIR, "conflict_resolutions.json")
SOURCE_REGISTRY_FILE = os.path.join(DATA_DIR, "source_registry.json")
NOTEBOOKLM_EXPORT_FILE = os.path.join(EXPORT_DIR, "NotebookLM_Sources.md")
VENUE_RULES_FILE = os.path.join(PACKAGE_DATA_DIR, "venue_rules.json")
SOURCE_REGISTRY_TEMPLATE_FILE = os.path.join(PACKAGE_DATA_DIR, "source_registry_template.json")
CONFIG_FILE = os.path.join(BASE_DIR, "config.local.json")
LEGACY_CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
EXAMPLE_CONFIG_FILE = os.path.join(BASE_DIR, "config.example.json")
CURRENT_LOCAL_DATA_VERSION = 3


def ensure_runtime_dirs():
    for path in (
        PACKAGE_DATA_DIR,
        DATA_DIR,
        SOURCE_CSV_DIR,
        MANUAL_SOURCE_DIR,
        GENERATED_SOURCE_DIR,
        IEEE_UPDATE_DIR,
        NATURE_UPDATE_DIR,
        CACHE_DIR,
        EXPORT_DIR,
        DOWNLOAD_DIR,
        BACKUP_ROOT_DIR,
    ):
        os.makedirs(path, exist_ok=True)


ensure_runtime_dirs()
