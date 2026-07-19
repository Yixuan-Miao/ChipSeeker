import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from chipseeker.literature_relevance import relevance_labels
from chipseeker.literature_update import OUTPUT_FIELDS


HARDWARE_TITLE_TERMS = (
    "on-chip",
    "on chip",
    "on a chip",
    "chip-scale",
    "chip scale",
    "integrated photonic",
    "photonic integrated",
    "optoelectronic chip",
    "integrated optoelectronic",
    "semiconductor",
    "transistor",
    "integrated circuit",
    "electronic circuit",
    "microelectronic",
    "cmos",
    "bicmos",
    "rfic",
    "mmic",
    "mixed-signal",
    "mixed signal",
    "processor",
    "accelerator",
    "neuromorphic",
    "compute-in-memory",
    "in-memory computing",
    "memristor",
    "sram",
    "dram",
    "rram",
    "mram",
    "qubit",
    "quantum computing",
    "quantum processor",
    "quantum control",
    "quantum error correction",
    "cryogenic electronics",
    "cryo-cmos",
    "photonic computing",
    "optical computing",
    "photonic neural",
    "optical neural",
    "image sensor",
    "photodetector",
    "readout circuit",
    "frequency comb",
    "terahertz wireless",
    "integrated wireless",
    "microantenna",
    "analog computation",
    "analog computing",
    "physical neural network",
)
NATURE_HARDWARE_TITLE_TERMS = (
    "photonic",
    "photon",
    "optoelectronic",
    "optical",
    "laser",
    "waveguide",
    "grating coupler",
    "modulator",
    "metasurface",
    "metalens",
    "terahertz",
    "wireless",
    "antenna",
    "rydberg",
    "electrometry",
    "resonator",
    "frequency comb",
    "lithography",
    "photoresponse",
    "single photon",
    "single-photon",
)


def row_key(row):
    doi = str(row.get("DOI", "")).strip().lower()
    if doi:
        return f"doi::{doi}"
    title = re.sub(r"[\W_]+", " ", str(row.get("Document Title", "")).lower(), flags=re.UNICODE).strip()
    return f"title::{title}" if title else ""


def read_rows(path):
    with open(path, "r", encoding="utf-8-sig", errors="ignore", newline="") as handle:
        return list(csv.DictReader(handle))


def should_rescue(row):
    if relevance_labels(
        row.get("Document Title", ""),
        row.get("Abstract", ""),
        row.get("Author Keywords", ""),
        row.get("Publication Title", ""),
    ):
        return True
    title = str(row.get("Document Title", "")).lower()
    if any(term in title for term in HARDWARE_TITLE_TERMS):
        return True
    venue = str(row.get("Publication Title", "")).strip().lower()
    if venue not in {"science", "science advances"}:
        return any(term in title for term in NATURE_HARDWARE_TITLE_TERMS)
    return False


def write_rows(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary_path = path + ".part"
    with open(temporary_path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in OUTPUT_FIELDS} for row in rows)
    os.replace(temporary_path, path)


def main():
    parser = argparse.ArgumentParser(description="Curate superseded broad literature-source files.")
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--bad-source", action="append", required=True)
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    source_root = os.path.abspath(args.source_root)
    bad_sources = [os.path.abspath(path) for path in args.bad_source]
    ignored = {os.path.normcase(path) for path in bad_sources + [os.path.abspath(args.output_csv)]}
    other_keys = set()
    unreadable_files = []
    for path in Path(source_root).rglob("*.csv"):
        absolute_path = os.path.abspath(path)
        if os.path.normcase(absolute_path) in ignored:
            continue
        try:
            for row in read_rows(absolute_path):
                key = row_key(row)
                if key:
                    other_keys.add(key)
        except OSError as exc:
            unreadable_files.append({"path": absolute_path, "error": str(exc)})

    rescued = {}
    removed = {}
    source_reports = []
    for source_path in bad_sources:
        rows = read_rows(source_path)
        unique_rows = {row_key(row): row for row in rows if row_key(row)}
        exclusive = {key: row for key, row in unique_rows.items() if key not in other_keys}
        source_rescued = {key: row for key, row in exclusive.items() if should_rescue(row)}
        source_removed = {key: row for key, row in exclusive.items() if key not in source_rescued}
        rescued.update(source_rescued)
        removed.update(source_removed)
        source_reports.append(
            {
                "source": source_path,
                "rows": len(rows),
                "unique_rows": len(unique_rows),
                "covered_by_other_sources": len(unique_rows) - len(exclusive),
                "rescued_exclusive_rows": len(source_rescued),
                "removed_exclusive_rows": len(source_removed),
            }
        )

    write_rows(args.output_csv, list(rescued.values()))
    report = {
        "source_root": source_root,
        "bad_sources": source_reports,
        "other_source_key_count": len(other_keys),
        "rescued_count": len(rescued),
        "removed_count": len(removed),
        "rescued_rows": [
            {
                "title": row.get("Document Title", ""),
                "venue": row.get("Publication Title", ""),
                "year": row.get("Publication Year", ""),
                "doi": row.get("DOI", ""),
            }
            for row in rescued.values()
        ],
        "removed_rows": [
            {
                "title": row.get("Document Title", ""),
                "venue": row.get("Publication Title", ""),
                "year": row.get("Publication Year", ""),
                "doi": row.get("DOI", ""),
            }
            for row in removed.values()
        ],
        "unreadable_files": unreadable_files,
    }
    os.makedirs(os.path.dirname(args.report), exist_ok=True)
    with open(args.report, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    print(json.dumps({"rescued": len(rescued), "removed": len(removed), "sources": source_reports}, ensure_ascii=False))


if __name__ == "__main__":
    main()
