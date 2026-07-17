import argparse
import csv
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

import requests

from chipseeker.paths import GENERATED_SOURCE_DIR


ARXIV_API_URL = "http://export.arxiv.org/api/query"
DEFAULT_OUTPUT_DIR = os.path.join(GENERATED_SOURCE_DIR, "arxiv_updates")
OUTPUT_FIELDS = [
    "Document Title",
    "Abstract",
    "Authors",
    "Author Keywords",
    "Publication Year",
    "Publication Title",
    "DOI",
    "PDF Link",
    "Source URL",
]


def resolve_output_path(output_file):
    if os.path.isabs(output_file):
        target_path = output_file
    else:
        target_path = os.path.join(DEFAULT_OUTPUT_DIR, output_file)
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    return target_path


def split_query_terms(query):
    terms = []
    for part in re.split(r"\s+OR\s+|\|", str(query or ""), flags=re.IGNORECASE):
        term = re.sub(r"\s+", " ", part.strip()).strip("() ").strip('"').strip()
        if term and term.lower() not in {item.lower() for item in terms}:
            terms.append(term)
    return terms


def _arxiv_term(term):
    escaped = str(term).replace('"', r'\"')
    return f'all:"{escaped}"' if re.search(r"\s", escaped) else f"all:{escaped}"


def build_search_query(query, categories=None, start_date=None, end_date=None):
    """Build raw arXiv API syntax; requests performs URL encoding exactly once."""
    terms = split_query_terms(query) or ["chip"]
    topic_expression = " OR ".join(_arxiv_term(term) for term in terms)
    parts = [f"({topic_expression})"]
    category_filters = [f"cat:{str(category).strip()}" for category in (categories or []) if str(category).strip()]
    if category_filters:
        parts.append("(" + " OR ".join(category_filters) + ")")
    if start_date and end_date:
        start_text = str(start_date).replace("-", "")
        end_text = str(end_date).replace("-", "")
        parts.append(f"submittedDate:[{start_text}0000 TO {end_text}2359]")
    return " AND ".join(parts)


def fetch_feed(
    query,
    categories=None,
    start=0,
    max_results=100,
    sort_by="lastUpdatedDate",
    session=None,
    retries=3,
    start_date=None,
    end_date=None,
):
    params = {
        "search_query": build_search_query(query, categories=categories, start_date=start_date, end_date=end_date),
        "start": int(start),
        "max_results": int(max_results),
        "sortBy": sort_by,
        "sortOrder": "descending",
    }
    client = session or requests.Session()
    last_error = None
    for attempt in range(max(1, int(retries))):
        try:
            response = client.get(ARXIV_API_URL, params=params, timeout=60)
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(min(12.0, 2.0 ** attempt))
    raise RuntimeError(f"arXiv API request failed after {retries} attempts: {last_error}")


def _parse_iso_datetime(value):
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_feed_page(feed_text, start_date=None):
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
        "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
    }
    root = ET.fromstring(feed_text)
    rows = []
    effective_dates = []
    entries = root.findall("atom:entry", ns)
    for entry in entries:
        entry_id = entry.findtext("atom:id", default="", namespaces=ns).strip()
        published = entry.findtext("atom:published", default="", namespaces=ns).strip()
        updated = entry.findtext("atom:updated", default="", namespaces=ns).strip()
        effective_dt = _parse_iso_datetime(updated) or _parse_iso_datetime(published)
        if effective_dt:
            effective_dates.append(effective_dt.date())
        if not entry_id:
            continue
        if start_date and effective_dt and effective_dt.date() < start_date:
            continue

        title = " ".join(entry.findtext("atom:title", default="", namespaces=ns).split())
        abstract = " ".join(entry.findtext("atom:summary", default="", namespaces=ns).split())
        if not title or not abstract:
            continue
        authors = [author.findtext("atom:name", default="", namespaces=ns).strip() for author in entry.findall("atom:author", ns)]
        tags = [tag.attrib.get("term", "").strip() for tag in entry.findall("atom:category", ns)]
        doi_node = entry.find("arxiv:doi", ns)
        doi = (doi_node.text or "").strip() if doi_node is not None and doi_node.text else ""
        pdf_link = ""
        for link in entry.findall("atom:link", ns):
            if link.attrib.get("title") == "pdf":
                pdf_link = link.attrib.get("href", "").strip()
                break
        rows.append(
            {
                "Document Title": title,
                "Abstract": abstract,
                "Authors": "; ".join(author for author in authors if author),
                "Author Keywords": "; ".join(sorted({tag for tag in tags if tag})),
                "Publication Year": published[:4] if published else "",
                "Publication Title": "arXiv",
                "DOI": doi,
                "PDF Link": pdf_link,
                "Source URL": re.sub(r"v\d+$", "", entry_id),
            }
        )

    total_text = root.findtext("opensearch:totalResults", default="0", namespaces=ns)
    try:
        total_results = int(total_text)
    except (TypeError, ValueError):
        total_results = 0
    return {
        "rows": rows,
        "entry_count": len(entries),
        "total_results": total_results,
        "oldest_date": min(effective_dates).isoformat() if effective_dates else "",
    }


def parse_feed(feed_text, start_date=None):
    parsed_start = start_date
    if isinstance(start_date, str) and start_date:
        parsed_start = datetime.fromisoformat(start_date).date()
    return parse_feed_page(feed_text, start_date=parsed_start)["rows"]


def _write_rows(output_path, rows):
    temporary_path = output_path + ".part"
    with open(temporary_path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary_path, output_path)


def incremental_date_windows(start_date, end_date=None, window_days=90):
    if not start_date:
        return [(None, None)]
    start = start_date if isinstance(start_date, date) else datetime.fromisoformat(str(start_date)).date()
    end = end_date or date.today()
    if isinstance(end, str):
        end = datetime.fromisoformat(end).date()
    windows = []
    cursor_end = end
    width = max(1, int(window_days))
    while cursor_end >= start:
        cursor_start = max(start, cursor_end - timedelta(days=width - 1))
        windows.append((cursor_start, cursor_end))
        cursor_end = cursor_start - timedelta(days=1)
    return windows


def grab_arxiv(
    query,
    output_file,
    categories=None,
    start_date=None,
    max_results=100,
    sleep_seconds=3.0,
    page_size=100,
    return_report=False,
    progress_callback=None,
    cancel_callback=None,
    window_days=90,
):
    output_path = resolve_output_path(output_file)
    parsed_start_date = datetime.fromisoformat(start_date).date() if start_date else None
    page_size = max(1, min(2000, int(page_size or 100)))
    result_limit = max(0, int(max_results or 0))
    rows = []
    seen = set()
    pages = 0
    total_results = 0
    truncated = False
    session = requests.Session()
    windows = incremental_date_windows(parsed_start_date, date.today(), window_days=window_days)
    request_count = 0
    completed_windows = 0

    for window_index, (window_start, window_end) in enumerate(windows, start=1):
        start = 0
        window_total = 0
        while True:
            if cancel_callback and cancel_callback():
                raise RuntimeError("Task was canceled.")
            request_size = page_size
            if result_limit:
                request_size = min(request_size, result_limit - len(rows))
                if request_size <= 0:
                    truncated = True
                    break
            if start >= 30000:
                truncated = True
                break
            if request_count:
                time.sleep(max(3.0, float(sleep_seconds)))
            feed_text = fetch_feed(
                query,
                categories=categories or [],
                start=start,
                max_results=request_size,
                sort_by="submittedDate",
                session=session,
                start_date=window_start.isoformat() if window_start else None,
                end_date=window_end.isoformat() if window_end else None,
            )
            request_count += 1
            page = parse_feed_page(feed_text, start_date=window_start)
            pages += 1
            window_total = max(window_total, int(page["total_results"] or 0))
            for row in page["rows"]:
                key = (row.get("DOI") or row.get("Source URL") or row.get("Document Title", "")).lower()
                if key and key not in seen:
                    seen.add(key)
                    rows.append(row)
            if progress_callback:
                progress_callback(
                    {
                        "pages": pages,
                        "rows": len(rows),
                        "total_results": total_results + window_total,
                        "window": window_index,
                        "windows": len(windows),
                    }
                )
            if page["entry_count"] < request_size or start + page["entry_count"] >= window_total:
                completed_windows += 1
                break
            start += page["entry_count"]
        total_results += window_total
        if truncated:
            break

    _write_rows(output_path, rows)
    report = {
        "rows": rows,
        "row_count": len(rows),
        "pages": pages,
        "total_results": total_results,
        "windows": len(windows),
        "completed_windows": completed_windows,
        "completed": bool(completed_windows == len(windows) and not truncated),
        "truncated": truncated,
        "output_file": output_path,
    }
    print(
        f"[Arxiv_Grabber] wrote {len(rows)} rows from {pages} page(s) to {output_path}; "
        f"completed={report['completed']}",
        flush=True,
    )
    return report if return_report else rows


def main():
    parser = argparse.ArgumentParser(description="Collect arXiv metadata into app-compatible CSV.")
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument("--output", required=True, help="Output CSV path")
    parser.add_argument("--category", action="append", dest="categories", default=[], help="Optional arXiv category filter, can be repeated")
    parser.add_argument("--start-date", default="", help="Optional ISO start date, e.g. 2026-04-01")
    parser.add_argument("--max-results", type=int, default=0, help="Optional total cap; 0 scans through the checkpoint")
    parser.add_argument("--page-size", type=int, default=100, help="Results requested per API page")
    parser.add_argument("--sleep", type=float, default=3.0, help="Delay between API pages in seconds")
    parser.add_argument("--window-days", type=int, default=90, help="Submitted-date window size for complete incremental paging")
    args = parser.parse_args()
    grab_arxiv(
        query=args.query,
        output_file=args.output,
        categories=args.categories,
        start_date=args.start_date or None,
        max_results=args.max_results,
        page_size=args.page_size,
        sleep_seconds=args.sleep,
        window_days=args.window_days,
    )


if __name__ == "__main__":
    main()
