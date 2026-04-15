import argparse
import csv
import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import quote_plus

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


def build_search_query(query, categories=None):
    parts = []
    if query:
        parts.append(f"all:{quote_plus(query)}")
    if categories:
        category_filters = [f"cat:{quote_plus(category)}" for category in categories if category]
        if category_filters:
            parts.append("(" + "+OR+".join(category_filters) + ")")
    return "+AND+".join(parts) if parts else "all:chip"


def fetch_feed(query, categories=None, start=0, max_results=100, sort_by="submittedDate"):
    params = {
        "search_query": build_search_query(query, categories=categories),
        "start": start,
        "max_results": max_results,
        "sortBy": sort_by,
        "sortOrder": "descending",
    }
    response = requests.get(ARXIV_API_URL, params=params, timeout=30)
    response.raise_for_status()
    return response.text


def parse_feed(feed_text, start_date=None):
    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    root = ET.fromstring(feed_text)
    rows = []
    seen_ids = set()
    for entry in root.findall("atom:entry", ns):
        entry_id = entry.findtext("atom:id", default="", namespaces=ns).strip()
        published = entry.findtext("atom:published", default="", namespaces=ns).strip()
        if not entry_id or entry_id in seen_ids:
            continue
        if start_date and published:
            published_date = datetime.fromisoformat(published.replace("Z", "+00:00")).date()
            if published_date < start_date:
                continue
        seen_ids.add(entry_id)
        title = " ".join(entry.findtext("atom:title", default="", namespaces=ns).split())
        abstract = " ".join(entry.findtext("atom:summary", default="", namespaces=ns).split())
        authors = [author.findtext("atom:name", default="", namespaces=ns).strip() for author in entry.findall("atom:author", ns)]
        tags = [tag.attrib.get("term", "").strip() for tag in entry.findall("atom:category", ns)]
        doi_node = entry.find("arxiv:doi", ns)
        doi = (doi_node.text or "").strip() if doi_node is not None and doi_node.text else ""
        pdf_link = ""
        for link in entry.findall("atom:link", ns):
            if link.attrib.get("title") == "pdf":
                pdf_link = link.attrib.get("href", "").strip()
                break
        year = published[:4] if published else ""
        rows.append(
            {
                "Document Title": title,
                "Abstract": abstract,
                "Authors": "; ".join([author for author in authors if author]),
                "Author Keywords": "; ".join(sorted({tag for tag in tags if tag})),
                "Publication Year": year,
                "Publication Title": "arXiv",
                "DOI": doi,
                "PDF Link": pdf_link,
                "Source URL": entry_id,
            }
        )
    return rows


def grab_arxiv(query, output_file, categories=None, start_date=None, max_results=100, sleep_seconds=0.5):
    resolved_output = resolve_output_path(output_file)
    parsed_start_date = datetime.fromisoformat(start_date).date() if start_date else None
    feed_text = fetch_feed(query, categories=categories or [], max_results=max_results)
    rows = parse_feed(feed_text, start_date=parsed_start_date)
    with open(resolved_output, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    time.sleep(sleep_seconds)
    print(f"[Arxiv_Grabber] wrote {len(rows)} rows to {resolved_output}")
    return rows


def main():
    parser = argparse.ArgumentParser(description="Collect arXiv metadata into app-compatible CSV.")
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument("--output", required=True, help="Output CSV path")
    parser.add_argument("--category", action="append", dest="categories", default=[], help="Optional arXiv category filter, can be repeated")
    parser.add_argument("--start-date", default="", help="Optional ISO start date, e.g. 2026-04-01")
    parser.add_argument("--max-results", type=int, default=100, help="Max results to request")
    parser.add_argument("--sleep", type=float, default=0.5, help="Delay after fetch in seconds")
    args = parser.parse_args()

    grab_arxiv(
        query=args.query,
        output_file=args.output,
        categories=args.categories,
        start_date=args.start_date or None,
        max_results=args.max_results,
        sleep_seconds=args.sleep,
    )


if __name__ == "__main__":
    main()
