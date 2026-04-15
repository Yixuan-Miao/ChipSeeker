import csv
import glob
import os
import shutil
from datetime import datetime

from chipseeker.utils import extract_year, normalize_title


def clear_embedding_cache(cache_dir, logger=None):
    for cache_pattern in ("cache_*.npy", "cache_*.meta.json"):
        for cache_file in glob.glob(os.path.join(cache_dir, cache_pattern)):
            try:
                os.remove(cache_file)
            except Exception as exc:
                if logger:
                    logger.warning("Failed to remove cache file %s: %s", cache_file, exc)


def generate_db_stats(all_papers, analyze_venue):
    stats = {}
    active_years = set()
    for paper in all_papers:
        venue_str = paper.get("venue", "")
        year = extract_year(paper.get("year", ""))
        if year < 1900:
            continue
        venue_data = analyze_venue(venue_str)
        venue_name = venue_data["n"]
        if venue_name == "Other":
            continue
        if venue_name not in stats:
            stats[venue_name] = {"data": venue_data, "years": {}}
        stats[venue_name]["years"][year] = stats[venue_name]["years"].get(year, 0) + 1
        active_years.add(year)
    return len(all_papers), stats, sorted(active_years, reverse=True)


def compute_papers_to_purge(all_papers, db_stats, analyze_venue, min_records=50):
    low_volume_venues = [
        venue_name
        for venue_name, content in db_stats.items()
        if sum(content["years"].values()) < min_records
    ]
    return [
        paper
        for paper in all_papers
        if analyze_venue(paper.get("venue", ""))["n"] in low_volume_venues
        or analyze_venue(paper.get("venue", ""))["n"] == "Other"
    ]


def purge_papers_from_sources(
    selected_papers,
    source_files,
    backup_root_dir,
    cache_dir,
    build_paper_from_row,
    paper_identity_key,
    logger=None,
):
    selected_keys = {paper_identity_key(paper) for paper in selected_papers if paper_identity_key(paper)}
    selected_titles = {normalize_title(paper.get("title", "")) for paper in selected_papers}
    backup_dir = os.path.join(backup_root_dir, f"csv_purge_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    backup_created = False
    modified_files = []
    removed_rows = 0

    for file in source_files:
        try:
            with open(file, "r", encoding="utf-8-sig", errors="ignore") as f:
                reader = list(csv.DictReader(f))
                if not reader:
                    continue
                headers = list(reader[0].keys())

            new_rows = []
            modified = False
            for row in reader:
                paper_obj = build_paper_from_row(row)
                paper_key = paper_identity_key(paper_obj)
                title_key = normalize_title(row.get("Document Title", ""))
                if paper_key in selected_keys or title_key in selected_titles:
                    modified = True
                    removed_rows += 1
                else:
                    new_rows.append(row)

            if modified:
                if not backup_created:
                    os.makedirs(backup_dir, exist_ok=True)
                    backup_created = True
                shutil.copy2(file, os.path.join(backup_dir, os.path.basename(file)))
                with open(file, "w", encoding="utf-8-sig", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=headers)
                    writer.writeheader()
                    writer.writerows(new_rows)
                modified_files.append(file)
        except Exception as exc:
            if logger:
                logger.warning("Failed to purge %s: %s", file, exc)

    if modified_files:
        clear_embedding_cache(cache_dir, logger=logger)

    return {
        "backup_dir": backup_dir if backup_created else None,
        "modified_files": modified_files,
        "removed_rows": removed_rows,
    }
