import argparse
import csv
import os
import re
import time
from urllib.parse import urljoin

import requests
from chipseeker.paths import MANUAL_SOURCE_DIR

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None


BASE_URL = "https://www.nature.com"
SEARCH_URL = "https://www.nature.com/search"
DEFAULT_OUTPUT_DIR = MANUAL_SOURCE_DIR
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
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
    return re.sub(r"\s+", " ", (text or "").strip())


def ensure_bs4():
    if BeautifulSoup is None:
        raise ImportError("beautifulsoup4 is not installed. Run `pip install -r requirements.txt` first.")

def resolve_output_path(output_file):
    if os.path.isabs(output_file):
        target_path = output_file
    else:
        target_path = os.path.join(DEFAULT_OUTPUT_DIR, output_file)
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    return target_path


def build_search_params(query, journal, year_from, page, start_date=None):
    params = {
        "q": query,
        "page": page,
        "date_range": f"{start_date or f'{year_from}-01-01'}_{time.strftime('%Y-%m-%d')}",
    }
    if journal:
        params["journal"] = journal
    return params


def fetch_html(session, url, params=None):
    response = session.get(url, params=params, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text


def parse_search_results(html):
    ensure_bs4()
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for anchor in soup.select("a[href*='/articles/']"):
        href = anchor.get("href", "")
        title = clean_text(anchor.get_text(" ", strip=True))
        if not href or not title:
            continue
        article_url = urljoin(BASE_URL, href.split("?")[0])
        if article_url not in links:
            links.append(article_url)
    return links


def parse_article(session, article_url):
    ensure_bs4()
    html = fetch_html(session, article_url)
    soup = BeautifulSoup(html, "html.parser")

    title = clean_text((soup.select_one("meta[name='dc.title']") or {}).get("content", ""))
    abstract = clean_text((soup.select_one("meta[name='dc.description']") or {}).get("content", ""))
    venue = clean_text((soup.select_one("meta[name='prism.publicationName']") or {}).get("content", ""))
    doi = clean_text((soup.select_one("meta[name='citation_doi']") or {}).get("content", ""))
    year = clean_text((soup.select_one("meta[name='dc.date']") or {}).get("content", ""))[:4]

    author_nodes = soup.select("meta[name='dc.creator']")
    authors = [clean_text(node.get("content", "")) for node in author_nodes if clean_text(node.get("content", ""))]

    keyword_nodes = soup.select("meta[name='news_keywords'], meta[name='citation_keywords'], meta[name='keywords']")
    keywords = []
    for node in keyword_nodes:
        raw = clean_text(node.get("content", ""))
        if raw:
            keywords.extend([k.strip() for k in re.split(r"[;,]", raw) if k.strip()])

    pdf_link = ""
    pdf_meta = soup.select_one("meta[name='citation_pdf_url']")
    if pdf_meta and pdf_meta.get("content"):
        pdf_link = clean_text(pdf_meta.get("content"))

    if not pdf_link:
        pdf_anchor = soup.select_one("a[href$='.pdf'], a[data-track-action='download pdf']")
        if pdf_anchor and pdf_anchor.get("href"):
            pdf_link = urljoin(BASE_URL, pdf_anchor.get("href"))

    return {
        "Document Title": title,
        "Abstract": abstract,
        "Authors": "; ".join(authors),
        "Author Keywords": "; ".join(sorted(set(keywords))),
        "Publication Year": year,
        "Publication Title": venue,
        "DOI": doi,
        "PDF Link": pdf_link,
        "Source URL": article_url,
    }


def grab_nature(query, output_file, journal="", year_from=2015, start_date=None, max_pages=5, sleep_seconds=1.0):
    ensure_bs4()
    output_path = resolve_output_path(output_file)
    session = requests.Session()
    rows = []
    seen_urls = set()

    for page in range(1, max_pages + 1):
        html = fetch_html(session, SEARCH_URL, build_search_params(query, journal, year_from, page, start_date=start_date))
        article_urls = parse_search_results(html)
        if not article_urls:
            break

        for article_url in article_urls:
            if article_url in seen_urls:
                continue
            seen_urls.add(article_url)
            try:
                row = parse_article(session, article_url)
                if row["Document Title"] and row["Abstract"]:
                    rows.append(row)
            except Exception as exc:
                print(f"[Nature_Grabber] skip {article_url}: {exc}")
            time.sleep(sleep_seconds)

    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[Nature_Grabber] wrote {len(rows)} rows to {output_path}")
    return rows


def main():
    parser = argparse.ArgumentParser(description="Collect Nature / Nature Electronics article metadata into app-compatible CSV.")
    parser.add_argument("--query", required=True, help="Search query, for example: cryogenic CMOS qubit readout")
    parser.add_argument("--output", required=True, help="Output CSV path")
    parser.add_argument("--journal", default="", help="Journal filter, e.g. nature or nature-electronics")
    parser.add_argument("--year-from", type=int, default=2015, help="Start year")
    parser.add_argument("--start-date", default="", help="Optional ISO start date for incremental updates, e.g. 2026-04-01")
    parser.add_argument("--max-pages", type=int, default=5, help="Max search pages to scan")
    parser.add_argument("--sleep", type=float, default=1.0, help="Delay between article requests in seconds")
    args = parser.parse_args()

    grab_nature(
        query=args.query,
        output_file=args.output,
        journal=args.journal,
        year_from=args.year_from,
        start_date=args.start_date or None,
        max_pages=args.max_pages,
        sleep_seconds=args.sleep,
    )


if __name__ == "__main__":
    main()
