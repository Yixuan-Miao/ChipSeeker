import argparse
import csv
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

import requests
from chipseeker.literature_relevance import is_relevant_literature
from chipseeker.paths import MANUAL_SOURCE_DIR

logger = logging.getLogger(__name__)

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


def normalize_nature_search_query(query):
    """Nature search is more reliable when phrase quotes are removed."""
    text = clean_text(query)
    text = re.sub(r'"([^"]+)"', r"\1", text)
    return clean_text(text)


def resolve_output_path(output_file):
    if os.path.isabs(output_file):
        target_path = output_file
    else:
        target_path = os.path.join(DEFAULT_OUTPUT_DIR, output_file)
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    return target_path


def build_search_params(query, journal, year_from, page, start_date=None):
    params = {
        "q": normalize_nature_search_query(query),
        "page": page,
        "order": "date_desc",
        "date_range": f"{start_date or f'{year_from}-01-01'}_{time.strftime('%Y-%m-%d')}",
    }
    if journal:
        params["journal"] = journal
    return params


def fetch_html(session, url, params=None, retries=3):
    last_error = None
    for attempt in range(max(1, int(retries))):
        try:
            response = session.get(url, params=params, headers=HEADERS, timeout=45)
            response.raise_for_status()
            if "Client Challenge" in response.text or "/_fs-ch-" in response.text:
                raise RuntimeError("Nature returned a client challenge page.")
            return response.text
        except (requests.RequestException, RuntimeError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(min(10.0, 2.0 ** attempt))
    raise RuntimeError(f"Nature request failed after {retries} attempts: {last_error}")


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
            keywords.extend(k.strip() for k in re.split(r"[;,]", raw) if k.strip())

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


def fetch_article(article_url):
    with requests.Session() as session:
        return parse_article(session, article_url)


def _write_rows(output_path, rows):
    temporary_path = output_path + ".part"
    with open(temporary_path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary_path, output_path)


def grab_nature(
    query,
    output_file,
    journal="",
    year_from=2015,
    start_date=None,
    max_pages=0,
    sleep_seconds=0.4,
    return_report=False,
    article_cache=None,
    progress_callback=None,
    cancel_callback=None,
    relevance_scopes=None,
    article_workers=1,
):
    ensure_bs4()
    output_path = resolve_output_path(output_file)
    session = requests.Session()
    rows = []
    seen_urls = set()
    shared_cache = article_cache if article_cache is not None else {}
    failures = []
    invalid_rows = 0
    pages = 0
    truncated = False
    hard_page_limit = 200

    page = 1
    while page <= hard_page_limit:
        if cancel_callback and cancel_callback():
            raise RuntimeError("Task was canceled.")
        html = fetch_html(session, SEARCH_URL, build_search_params(query, journal, year_from, page, start_date=start_date))
        article_urls = parse_search_results(html)
        pages += 1
        new_urls = [url for url in article_urls if url not in seen_urls]
        if not article_urls or not new_urls:
            break

        uncached_urls = []
        page_rows = {}
        for article_url in new_urls:
            if cancel_callback and cancel_callback():
                raise RuntimeError("Task was canceled.")
            seen_urls.add(article_url)
            cached = shared_cache.get(article_url)
            if cached is not None:
                page_rows[article_url] = dict(cached)
            else:
                uncached_urls.append(article_url)

        worker_count = max(1, min(int(article_workers or 1), len(uncached_urls) or 1))
        if worker_count == 1:
            for article_url in uncached_urls:
                try:
                    row = parse_article(session, article_url)
                    shared_cache[article_url] = dict(row)
                    page_rows[article_url] = row
                except Exception as exc:
                    failures.append({"url": article_url, "error": str(exc)})
                    logger.warning("skip %s: %s", article_url, exc)
                time.sleep(max(0.0, float(sleep_seconds)))
        else:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                future_urls = {executor.submit(fetch_article, url): url for url in uncached_urls}
                for future in as_completed(future_urls):
                    article_url = future_urls[future]
                    try:
                        row = future.result()
                        shared_cache[article_url] = dict(row)
                        page_rows[article_url] = row
                    except Exception as exc:
                        failures.append({"url": article_url, "error": str(exc)})
                        logger.warning("skip %s: %s", article_url, exc)

        for article_url in new_urls:
            row = page_rows.get(article_url)
            if row is None:
                continue
            if (
                row.get("Document Title")
                and row.get("Abstract")
                and (
                    not relevance_scopes
                    or is_relevant_literature(
                        row.get("Document Title", ""),
                        abstract=row.get("Abstract", ""),
                        keywords=row.get("Author Keywords", ""),
                        venue=row.get("Publication Title", ""),
                        scopes=relevance_scopes,
                    )
                )
            ):
                rows.append(row)
            else:
                invalid_rows += 1

        if progress_callback:
            progress_callback(
                {
                    "pages": pages,
                    "discovered": len(seen_urls),
                    "rows": len(rows),
                    "failed": len(failures),
                }
            )
        if max_pages and page >= int(max_pages):
            truncated = True
            break
        page += 1
    else:
        truncated = True

    _write_rows(output_path, rows)
    report = {
        "rows": rows,
        "row_count": len(rows),
        "pages": pages,
        "discovered": len(seen_urls),
        "failed": failures,
        "invalid_rows": invalid_rows,
        "truncated": truncated,
        "completed": not failures and not truncated,
        "output_file": output_path,
    }
    logger.info(
        "wrote %d rows from %d page(s) to %s; failed=%d truncated=%s",
        len(rows),
        pages,
        output_path,
        len(failures),
        truncated,
    )
    return report if return_report else rows


def main():
    parser = argparse.ArgumentParser(description="Collect Nature / Nature Electronics article metadata into app-compatible CSV.")
    parser.add_argument("--query", required=True, help="Search query, for example: cryogenic CMOS qubit readout")
    parser.add_argument("--output", required=True, help="Output CSV path")
    parser.add_argument("--journal", default="", help="Journal filter, e.g. nature or natelectron")
    parser.add_argument("--year-from", type=int, default=2015, help="Start year")
    parser.add_argument("--start-date", default="", help="Optional ISO start date for incremental updates")
    parser.add_argument("--max-pages", type=int, default=0, help="Optional page cap; 0 scans to the end")
    parser.add_argument("--sleep", type=float, default=0.4, help="Delay between article requests in seconds")
    parser.add_argument("--article-workers", type=int, default=3, help="Concurrent article metadata requests")
    args = parser.parse_args()
    grab_nature(
        query=args.query,
        output_file=args.output,
        journal=args.journal,
        year_from=int(args.year_from),
        start_date=args.start_date or None,
        max_pages=int(args.max_pages),
        sleep_seconds=float(args.sleep),
        article_workers=int(args.article_workers),
    )


if __name__ == "__main__":
    main()
