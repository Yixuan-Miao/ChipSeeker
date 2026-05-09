import argparse
import json

from chipseeker.data_sync import enrich_bibliographic_metadata
from chipseeker.paths import DB_FILE, SOURCE_CSV_DIR, SOURCE_MANIFEST_FILE


def main():
    parser = argparse.ArgumentParser(description="Repair BibTeX metadata in isscc_papers.json from source CSV files.")
    parser.add_argument("--db-file", default=DB_FILE)
    parser.add_argument("--source-root", default=SOURCE_CSV_DIR)
    parser.add_argument("--manifest-path", default=SOURCE_MANIFEST_FILE)
    args = parser.parse_args()

    result = enrich_bibliographic_metadata(
        args.db_file,
        source_root=args.source_root,
        manifest_path=args.manifest_path,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
