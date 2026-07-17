import argparse
import csv
import os
import re
import time
from datetime import date

import requests

from chipseeker.paths import MANUAL_SOURCE_DIR


CROSSREF_URL = "https://api.crossref.org/works"
DEFAULT_OUTPUT_DIR = MANUAL_SOURCE_DIR
DEFAULT_HEADERS = {
    "User-Agent": "ChipSeeker/2.3 (mailto:guangeofaisa@gmail.com)",
}
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


def clean_text(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()


def resolve_output_path(output_file):
    if os.path.isabs(output_file):
        target_path = output_file
    else:
        target_path = os.path.join(DEFAULT_OUTPUT_DIR, output_file)
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    return target_path


def split_query_terms(query):
    terms = []
    for part in re.split(r"\s+OR\s+|\|", query or "", flags=re.IGNORECASE):
        part = clean_text(part).strip('"').strip()
        if len(part) >= 3 and part.lower() not in {item.lower() for item in terms}:
            terms.append(part)
    return terms or [clean_text(query)]


def published_year(item):
    for key in ("published-print", "published-online", "published", "issued"):
        parts = (item.get(key) or {}).get("date-parts") or []
        if parts and parts[0]:
            return str(parts[0][0])
    return ""


def first_url(item):
    if item.get("URL"):
        return item["URL"]
    doi = clean_text(item.get("DOI", ""))
    return f"https://doi.org/{doi}" if doi else ""


def item_authors(item):
    names = []
    for author in item.get("author", []) or []:
        given = clean_text(author.get("given", ""))
        family = clean_text(author.get("family", ""))
        name = clean_text(f"{given} {family}")
        if name:
            names.append(name)
    return "; ".join(names)


def item_title(item):
    titles = item.get("title") or []
    return clean_text(titles[0] if titles else "")


def item_venue(item):
    venues = item.get("container-title") or []
    return clean_text(venues[0] if venues else "")


def is_relevant_record(item):
    text = " ".join(
        [
            item_title(item),
            clean_text(item.get("abstract", "")),
            item_keywords(item),
            item_venue(item),
        ]
    ).lower()
    text = text.replace("cryo–", "cryo-").replace("low temperature", "low-temperature")

    reject_terms = (
        "cryo-em",
        "cryo electron microscopy",
        "cryo-electron microscopy",
        "cryo–electron microscopy",
        "neural circuit",
        "brain circuit",
        "stress response",
        "immune circuit",
        "biochemical network",
    )
    if any(term in text for term in reject_terms):
        return False

    strong_terms = (
        "artificial intelligence",
        "machine learning",
        "deep learning",
        "neural network",
        "foundation model",
        "large language model",
        "generative ai",
        "computer vision",
        "reinforcement learning",
        "robot learning",
        "cryogenic cmos",
        "cryo-cmos",
        "cryo cmos",
        "low-temperature cmos",
        "readout integrated circuit",
        "control integrated circuit",
        "rf integrated circuit",
        "radio-frequency integrated circuit",
        "mixed-signal cmos",
        "analog cmos",
        "cmos circuit",
        "cmos circuits",
        "integrated electronics",
        "integrated photonics",
        "semiconductor chip",
        "semiconductor device",
        "artificial intelligence accelerator",
        "ai accelerator",
        "machine learning accelerator",
        "compute-in-memory",
        "in-memory computing",
        "neuromorphic hardware",
        "photonic computing",
        "quantum processor",
        "quantum computing hardware",
        "quantum chip",
        "superconducting qubit",
        "spin qubit",
        "silicon qubit",
        "qubit readout",
        "quantum control electronics",
        "quantum algorithm",
        "quantum simulation",
        "quantum annealing",
        "quantum error correction",
        "quantum network",
    )
    if any(term in text for term in strong_terms):
        return True

    if "integrated circuit" in text or "integrated circuits" in text:
        return any(term in text for term in ("cmos", "semiconductor", "transistor", "qubit", "quantum", "readout", "rf", "radio frequency", "chip"))

    if "cmos" in text:
        return any(term in text for term in ("cryogenic", "low-temperature", "qubit", "readout", "rf", "analog", "mixed-signal", "semiconductor", "chip"))

    if "chip" in text:
        return any(
            term in text
            for term in (
                "quantum",
                "qubit",
                "semiconductor",
                "photonic",
                "accelerator",
                "cmos",
                "processor",
                "memory",
                "sensor",
                "packaging",
            )
        )

    if "qubit" in text or "quantum processor" in text:
        return any(term in text for term in ("comput", "control", "readout", "hardware", "circuit", "electronics", "chip"))

    return False


def item_keywords(item):
    subjects = item.get("subject") or []
    return "; ".join(clean_text(subject) for subject in subjects if clean_text(subject))


def crossref_items(session, term, issn, start_date, rows, cursor="*", retries=3):
    params = {
        "query.bibliographic": term,
        "filter": f"from-pub-date:{start_date},until-pub-date:{date.today().isoformat()},type:journal-article,issn:{issn}",
        "rows": rows,
        "sort": "published",
        "order": "desc",
        "cursor": cursor,
    }
    last_error = None
    for attempt in range(max(1, int(retries))):
        try:
            response = session.get(CROSSREF_URL, params=params, headers=DEFAULT_HEADERS, timeout=45)
            response.raise_for_status()
            message = response.json().get("message") or {}
            return {
                "items": message.get("items", []) or [],
                "next_cursor": message.get("next-cursor", ""),
                "total_results": int(message.get("total-results", 0) or 0),
            }
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(min(10.0, 2.0 ** attempt))
    raise RuntimeError(f"Crossref request failed after {retries} attempts: {last_error}")


def grab_science(
    query,
    output_file,
    issns=None,
    start_date=None,
    max_results=100,
    sleep_seconds=0.5,
    return_report=False,
    progress_callback=None,
    cancel_callback=None,
):
    output_path = resolve_output_path(output_file)
    terms = split_query_terms(query)
    journal_issns = issns or ["0036-8075", "1095-9203", "2375-2548"]
    per_query_rows = max(20, min(1000, int(max_results or 200)))
    start = start_date or f"{date.today().year - 5}-01-01"
    rows = []
    seen_dois = set()
    session = requests.Session()
    failures = []
    pages = 0

    for issn in journal_issns:
        for term in terms:
            cursor = "*"
            seen_cursors = set()
            term_pages = 0
            while cursor and cursor not in seen_cursors and term_pages < 200:
                if cancel_callback and cancel_callback():
                    raise RuntimeError("Task was canceled.")
                seen_cursors.add(cursor)
                try:
                    page = crossref_items(session, term, issn, start, per_query_rows, cursor=cursor)
                except Exception as exc:
                    failures.append({"term": term, "issn": issn, "error": str(exc)})
                    print(f"[Science_Grabber] skip term={term} issn={issn}: {exc}", flush=True)
                    break
                pages += 1
                term_pages += 1
                items = page["items"]
                for item in items:
                    doi = clean_text(item.get("DOI", ""))
                    if not doi or doi.lower() in seen_dois:
                        continue
                    title = item_title(item)
                    venue = item_venue(item)
                    if not title or not venue.lower().startswith("science") or not is_relevant_record(item):
                        continue
                    seen_dois.add(doi.lower())
                    rows.append(
                        {
                            "Document Title": title,
                            "Abstract": clean_text(item.get("abstract", "")),
                            "Authors": item_authors(item),
                            "Author Keywords": item_keywords(item),
                            "Publication Year": published_year(item),
                            "Publication Title": venue,
                            "DOI": doi,
                            "PDF Link": "",
                            "Source URL": first_url(item),
                        }
                    )
                if progress_callback:
                    progress_callback({"pages": pages, "rows": len(rows), "term": term, "issn": issn})
                if len(items) < per_query_rows or not page["next_cursor"]:
                    break
                cursor = page["next_cursor"]
                time.sleep(max(0.0, float(sleep_seconds)))
            if term_pages >= 200:
                failures.append({"term": term, "issn": issn, "error": "Crossref pagination safety limit reached."})

    temporary_path = output_path + ".part"
    with open(temporary_path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary_path, output_path)

    report = {
        "rows": rows,
        "row_count": len(rows),
        "pages": pages,
        "failed": failures,
        "completed": not failures,
        "truncated": False,
        "output_file": output_path,
    }
    print(f"[Science_Grabber] wrote {len(rows)} rows to {output_path}; completed={report['completed']}", flush=True)
    return report if return_report else rows


def main():
    parser = argparse.ArgumentParser(description="Collect highly relevant Science / Science Advances metadata into ChipSeeker CSV.")
    parser.add_argument("--query", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--issns", default="0036-8075;1095-9203;2375-2548", help="Semicolon-separated ISSNs.")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--max-results", type=int, default=100)
    parser.add_argument("--sleep", type=float, default=0.5)
    args = parser.parse_args()
    grab_science(
        query=args.query,
        output_file=args.output,
        issns=[item.strip() for item in args.issns.split(";") if item.strip()],
        start_date=args.start_date or None,
        max_results=args.max_results,
        sleep_seconds=args.sleep,
    )


if __name__ == "__main__":
    main()
