import base64
import csv
import html
import io
import math
import os
import re
from datetime import datetime

from chipseeker.utils import extract_year


def _normalize_author_items(value):
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        parts = re.split(r"\s*;\s*", value.strip())
        return [part.strip() for part in parts if part.strip()]
    return []


def paper_authors(paper):
    authors = _normalize_author_items(paper.get("authors"))
    if not authors:
        authors = [author for author in [paper.get("first_author", ""), paper.get("last_author", "")] if author]
    return authors or ["Unknown"]


def paper_authors_display(paper):
    return "; ".join(paper_authors(paper))


def paper_bibtex_authors(paper):
    return " and ".join(paper_authors(paper))


def _normalize_keyword_items(value):
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(";") if item.strip()]
    return []


def _bibtex_escape(value):
    return str(value or "").replace("\n", " ").strip()


def _bibtex_key(paper):
    article_number = str(paper.get("article_number", "") or "").strip()
    if article_number:
        return re.sub(r"[^A-Za-z0-9:_-]", "", article_number)
    doi = str(paper.get("doi", "") or "").strip()
    doi_suffix = doi.rsplit("/", 1)[-1] if doi else ""
    if doi_suffix and re.fullmatch(r"[A-Za-z0-9._:-]+", doi_suffix):
        return doi_suffix
    first_author = paper_authors(paper)[0]
    last_name = first_author.split()[-1].replace("-", "") if first_author else "Anon"
    year_str = str(extract_year(paper.get("year", "202X")))
    title_words = re.sub(r"[^a-zA-Z0-9\s]", "", paper.get("title", "paper")).split()
    first_word = title_words[0].capitalize() if title_words else "Paper"
    return f"{last_name}{year_str}{first_word}"


def _bibtex_entry_type(paper):
    explicit = str(paper.get("bibtex_type", "") or "").strip().upper()
    if explicit:
        return explicit
    document_identifier = str(paper.get("document_identifier", "") or "").lower()
    venue = str(paper.get("venue", "") or "").lower()
    if "conference" in document_identifier or "conference" in venue or "symposium" in venue:
        return "INPROCEEDINGS"
    return "ARTICLE"


def _paper_pages(paper):
    pages = str(paper.get("pages", "") or "").strip()
    if pages:
        return pages
    start = str(paper.get("start_page", "") or "").strip()
    end = str(paper.get("end_page", "") or "").strip()
    if start and end:
        return f"{start}-{end}"
    return start or end


def _paper_keywords_for_bibtex(paper):
    # IEEE BibTeX exports put IEEE Terms before author keywords.
    keywords = []
    for item in _normalize_keyword_items(paper.get("ieee_terms")) + _normalize_keyword_items(paper.get("keywords")):
        if item and item not in keywords:
            keywords.append(item)
    return ";".join(keywords)


def _paper_keywords_display(paper):
    keywords = []
    for item in _normalize_keyword_items(paper.get("keywords")):
        if item and item not in keywords:
            keywords.append(item)
    return "; ".join(keywords)


def _paper_ieee_terms_display(paper):
    terms = []
    for item in _normalize_keyword_items(paper.get("ieee_terms")):
        if item and item not in terms:
            terms.append(item)
    return "; ".join(terms)


def _append_bibtex_field(fields, name, value):
    value = _bibtex_escape(value)
    if value:
        fields.append((name, value))


def build_notebooklm_export(selected_papers, query_label, get_user_data):
    content = f"# Papers Context for '{query_label}'\n\n"
    for paper in selected_papers:
        title = paper.get("title", "")
        user_data = get_user_data(title)
        content += (
            f"## {title}\n"
            f"- **Authors:** {', '.join(paper_authors(paper))}\n"
            f"- **Venue & Year:** {paper.get('venue', '')} ({paper.get('year', '')})\n"
            f"- **My Rating:** {user_data['rating']}\n"
        )
        if user_data["comments"]:
            content += f"- **My Comments:** {user_data['comments']}\n"
        content += f"### Abstract\n{paper.get('abstract', '')}\n\n---\n\n"
    return content


def _report_line(label, value):
    value = str(value or "").strip()
    return f"- **{label}:** {value}\n" if value else ""


def _plain_report_line(label, value):
    value = str(value or "").strip()
    return f"- {label}: {value}\n" if value else ""


def build_annual_conference_report(papers, venue_label, year_label, output_format="md"):
    output_format = (output_format or "md").lower()
    is_markdown = output_format == "md"
    selected = list(papers or [])
    selected.sort(
        key=lambda paper: (
            str(paper.get("venue", "") or "").lower(),
            extract_year(paper.get("year", "")),
            str(paper.get("title", "") or "").lower(),
        )
    )
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if is_markdown:
        content = (
            f"# {venue_label} {year_label} Annual Conference Paper Pack\n\n"
            f"- **Generated by:** ChipSeeker\n"
            f"- **Generated at:** {generated_at}\n"
            f"- **Paper count:** {len(selected)}\n\n"
            "Use this file as source material for an AI-generated annual conference report. "
            "It contains deduplicated papers after ChipSeeker CSV import, metadata enrichment, and junk-page filtering.\n\n"
        )
    else:
        content = (
            f"{venue_label} {year_label} Annual Conference Paper Pack\n"
            f"Generated by: ChipSeeker\n"
            f"Generated at: {generated_at}\n"
            f"Paper count: {len(selected)}\n\n"
            "Use this file as source material for an AI-generated annual conference report. "
            "It contains deduplicated papers after ChipSeeker CSV import, metadata enrichment, and junk-page filtering.\n\n"
        )

    for index, paper in enumerate(selected, start=1):
        title = str(paper.get("title", "Untitled") or "Untitled").strip()
        abstract = str(paper.get("abstract", "") or "").strip()
        pages = _paper_pages(paper)
        keyword_text = _paper_keywords_display(paper)
        ieee_terms_text = _paper_ieee_terms_display(paper)
        if is_markdown:
            content += f"## {index}. {title}\n\n"
            content += _report_line("Authors", paper_authors_display(paper))
            content += _report_line("Venue", paper.get("venue", ""))
            content += _report_line("Year", paper.get("year", ""))
            content += _report_line("DOI", paper.get("doi", ""))
            content += _report_line("PDF Link", paper.get("pdf_link", ""))
            content += _report_line("Volume", paper.get("volume", ""))
            content += _report_line("Issue/Number", paper.get("number", "") or paper.get("issue", ""))
            content += _report_line("Pages", pages)
            content += _report_line("Article Number", paper.get("article_number", ""))
            content += _report_line("Online Date", paper.get("online_date", ""))
            content += _report_line("Issue Date", paper.get("issue_date", ""))
            content += _report_line("Date Added To Xplore", paper.get("date_added_to_xplore", ""))
            content += _report_line("Author Keywords", keyword_text)
            content += _report_line("IEEE Terms", ieee_terms_text)
            content += _report_line("Funding", paper.get("funding_information", ""))
            content += _report_line("Article Citations", paper.get("article_citation_count", ""))
            content += _report_line("Patent Citations", paper.get("patent_citation_count", ""))
            content += _report_line("Reference Count", paper.get("reference_count", ""))
            content += _report_line("License", paper.get("license", ""))
            content += _report_line("Publisher", paper.get("publisher", ""))
            content += _report_line("Document Identifier", paper.get("document_identifier", ""))
            content += f"\n### Abstract\n{abstract or 'No abstract available.'}\n\n---\n\n"
        else:
            content += f"{index}. {title}\n"
            content += _plain_report_line("Authors", paper_authors_display(paper))
            content += _plain_report_line("Venue", paper.get("venue", ""))
            content += _plain_report_line("Year", paper.get("year", ""))
            content += _plain_report_line("DOI", paper.get("doi", ""))
            content += _plain_report_line("PDF Link", paper.get("pdf_link", ""))
            content += _plain_report_line("Volume", paper.get("volume", ""))
            content += _plain_report_line("Issue/Number", paper.get("number", "") or paper.get("issue", ""))
            content += _plain_report_line("Pages", pages)
            content += _plain_report_line("Article Number", paper.get("article_number", ""))
            content += _plain_report_line("Online Date", paper.get("online_date", ""))
            content += _plain_report_line("Issue Date", paper.get("issue_date", ""))
            content += _plain_report_line("Date Added To Xplore", paper.get("date_added_to_xplore", ""))
            content += _plain_report_line("Author Keywords", keyword_text)
            content += _plain_report_line("IEEE Terms", ieee_terms_text)
            content += _plain_report_line("Funding", paper.get("funding_information", ""))
            content += _plain_report_line("Article Citations", paper.get("article_citation_count", ""))
            content += _plain_report_line("Patent Citations", paper.get("patent_citation_count", ""))
            content += _plain_report_line("Reference Count", paper.get("reference_count", ""))
            content += _plain_report_line("License", paper.get("license", ""))
            content += _plain_report_line("Publisher", paper.get("publisher", ""))
            content += _plain_report_line("Document Identifier", paper.get("document_identifier", ""))
            content += f"\nAbstract:\n{abstract or 'No abstract available.'}\n\n{'-' * 72}\n\n"

    return content


def write_text_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def build_csv_rows(selected_papers):
    rows = [["Title", "Authors", "Year", "Venue", "DOI", "Abstract"]]
    for paper in selected_papers:
        rows.append(
            [
                paper.get("title", ""),
                "; ".join(paper_authors(paper)),
                paper.get("year", ""),
                paper.get("venue", ""),
                paper.get("doi", ""),
                paper.get("abstract", ""),
            ]
        )
    return rows


def generate_csv_link(rows, filename="ChipSeeker_Export.csv"):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerows(rows)
    encoded = base64.b64encode(output.getvalue().encode("utf-8-sig")).decode()
    return (
        f'<a href="data:text/csv;base64,{encoded}" download="{filename}" '
        'style="display:block; text-align:center; padding:10px; background-color:#28a745; '
        'color:white; border-radius:4px; text-decoration:none; font-weight:bold;">Download CSV Database</a>'
    )


def build_bibtex(selected_papers):
    content = ""
    for paper in selected_papers:
        entry_type = _bibtex_entry_type(paper)
        venue_field = "booktitle" if entry_type == "INPROCEEDINGS" else "journal"
        fields = []
        _append_bibtex_field(fields, "author", paper_bibtex_authors(paper))
        _append_bibtex_field(fields, venue_field, paper.get("venue", ""))
        _append_bibtex_field(fields, "title", paper.get("title", ""))
        _append_bibtex_field(fields, "year", paper.get("year", ""))
        _append_bibtex_field(fields, "volume", paper.get("volume", ""))
        _append_bibtex_field(fields, "number", paper.get("number", "") or paper.get("issue", ""))
        _append_bibtex_field(fields, "pages", _paper_pages(paper))
        _append_bibtex_field(fields, "keywords", _paper_keywords_for_bibtex(paper))
        _append_bibtex_field(fields, "doi", paper.get("doi", ""))

        content += f"@{entry_type}{{{_bibtex_key(paper)},\n"
        for idx, (name, value) in enumerate(fields):
            suffix = "," if idx < len(fields) - 1 else ""
            content += f"  {name}={{{value}}}{suffix}\n"
        content += "}\n\n"
    return content


def _result_badge(similarity, has_query):
    if similarity >= 0.60 or not has_query:
        return "#9C27B0", "Rare Match"
    if similarity >= 0.40:
        return "#00C853", "Perfect Match"
    if similarity >= 0.25:
        return "#2196F3", "Highly Valuable"
    if similarity >= 0.15:
        return "#FF9800", "Relevant"
    return "#9E9E9E", "Noise"


def build_search_results_html(results, search_query, current_year, analyze_venue, get_user_data, citations_map=None, citations_fetched=False, max_results=50):
    citations_map = citations_map or {}
    cards = []
    trimmed_results = list(results[:max_results])
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for index, item in enumerate(trimmed_results, start=1):
        paper = item.get("paper", {})
        similarity = float(item.get("similarity", 0.0))
        title = paper.get("title", "Untitled")
        abstract = paper.get("abstract", "No Abstract")
        venue = paper.get("venue", "Unknown Venue")
        year = paper.get("year", "N/A")
        doi = paper.get("doi", "")
        pdf_link = paper.get("pdf_link", "")
        author_str = paper_authors_display(paper)
        user_data = get_user_data(title)
        venue_data = analyze_venue(venue)
        venue_display = venue_data.get("n", venue)
        base_score = float(venue_data.get("s", 0))
        year_value = extract_year(year)
        if year_value > 1900 and (current_year - year_value) < 10:
            year_bonus = max(0, 10 - (current_year - year_value))
        elif year_value > 1900 and (current_year - year_value) <= 0:
            year_bonus = 10
        else:
            year_bonus = 0
        citations = int(citations_map.get(str(doi).upper(), 0)) if citations_fetched else 0
        citation_bonus = min(15, math.log10(citations + 1) * 6) if citations > 0 else 0
        final_score = float(item.get("comp_score", base_score + year_bonus + citation_bonus))
        color, badge = _result_badge(similarity, bool(search_query))
        tier_color = {
            "S+": "#E53935",
            "S": "#FB8C00",
            "AA": "#1E88E5",
            "A": "#43A047",
            "B": "#8E24AA",
            "C": "#757575",
        }.get(venue_data.get("t", ""), "#9E9E9E")
        citation_text = f"{citations} (Fetched)" if citations_fetched else "Pending (Manual Fetch)"
        links = []
        if doi:
            links.append(f"<a href='https://doi.org/{html.escape(doi)}' target='_blank' rel='noreferrer'>DOI</a>")
        if pdf_link:
            links.append(f"<a href='{html.escape(pdf_link)}' target='_blank' rel='noreferrer'>PDF</a>")
        links_html = " | ".join(links)
        abstract_block = html.escape(abstract).replace("\n", "<br>")
        notes = html.escape(user_data.get("comments", "") or "")
        rating_value = user_data.get("rating", "Unrated")
        rating = html.escape(
            {
                "Unrated": "☆ Unrated",
                "Masterpiece": "★★★★★ Masterpiece",
                "Solid": "★★★★ Solid",
                "Average": "★★★ Average",
                "Marginal": "★★ Marginal",
                "Poor": "★ Poor",
            }.get(rating_value, rating_value)
        )
        search_count = int(user_data.get("search_count", len(user_data.get("matched_queries", []))))
        llm_score = item.get("llm_score")
        llm_delta_html = ""
        llm_reason_html = ""
        if llm_score is not None:
            try:
                llm_score_value = float(llm_score)
                llm_delta = llm_score_value - (similarity * 100.0)
                llm_delta_class = "llm-delta-up" if llm_delta >= 0 else "llm-delta-down"
                llm_delta_html = (
                    f'<span class="llm-arrow">&rarr;</span> '
                    f'<span class="llm-score">LLM {llm_score_value:.0f}%</span> '
                    f'<span class="llm-delta {llm_delta_class}">{llm_delta:+.1f}</span>'
                )
            except (TypeError, ValueError):
                llm_delta_html = f'<span class="llm-score">LLM {html.escape(str(llm_score))}</span>'
        if item.get("llm_reason"):
            llm_reason_html = f'<div class="llm-match-note"><strong>LLM match:</strong> {html.escape(str(item.get("llm_reason")))}</div>'

        cards.append(
            f"""
            <section class="result-card">
              <div class="result-banner" style="border-left-color:{color};">
                <div class="banner-left">
                  <span class="relevance" style="color:{color};">Relevance: {similarity * 100:.1f}%</span>
                  {llm_delta_html}
                  <span class="badge" style="background:{color};">{html.escape(badge)}</span>
                </div>
                <div class="banner-right">
                  Score: {final_score:.1f}
                  <span class="score-breakdown">(Base {base_score:.0f} + Yr {year_bonus:.0f} + Cites {citation_bonus:.1f})</span>
                </div>
              </div>
              <div class="result-body">
                <div class="main-col">
                  <div class="title-row">
                    <span class="result-index">#{index}</span>
                    <span class="title">{html.escape(title)}</span>
                  </div>
                  <div class="meta-row"><strong>Authors:</strong> {html.escape(author_str)}</div>
                  <div class="meta-row">
                    <strong>Venue:</strong>
                    <span class="venue">{html.escape(venue_display)}</span> ({html.escape(str(year))})
                    &nbsp;|&nbsp;
                    <strong>Tier:</strong>
                    <span class="tier" style="background:{tier_color};">{html.escape(venue_data.get("t", "N/A"))}</span>
                  </div>
                  {llm_reason_html}
                  <details class="abstract-box">
                    <summary>Read Abstract</summary>
                    <div class="abstract-text">{abstract_block}</div>
                  </details>
                </div>
                <div class="side-col">
                  <div><strong>Search Hits:</strong> <code>{search_count}</code></div>
                  <div><strong>Reads:</strong> <code>{int(user_data.get("open_count", 0))}</code></div>
                  <div><strong>Cites:</strong> <code>{html.escape(citation_text)}</code></div>
                  <div><strong>Rating:</strong> <code>{rating}</code></div>
                  <div><strong>Notes:</strong> {notes or "<span class='muted'>None</span>"}</div>
                  <div class="links">{links_html or "<span class='muted'>No DOI / PDF link</span>"}</div>
                </div>
              </div>
            </section>
            """
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ChipSeeker Search Results</title>
  <style>
    :root {{
      --bg: #f4f7fb;
      --card: #ffffff;
      --line: #dde5ef;
      --text: #18212b;
      --muted: #6b7785;
      --accent: #0f766e;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
      background: linear-gradient(180deg, #f7faff 0%, #eef3f9 100%);
      color: var(--text);
    }}
    .page {{
      max-width: 1280px;
      margin: 0 auto;
      padding: 28px 20px 48px;
    }}
    .header {{
      background: rgba(255,255,255,0.86);
      backdrop-filter: blur(8px);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 20px 22px;
      margin-bottom: 20px;
      box-shadow: 0 14px 40px rgba(19, 38, 63, 0.08);
    }}
    .header h1 {{
      margin: 0 0 8px;
      font-size: 30px;
    }}
    .header p {{
      margin: 4px 0;
      color: var(--muted);
    }}
    .result-card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 14px 16px 16px;
      margin-bottom: 16px;
      box-shadow: 0 14px 32px rgba(15, 23, 42, 0.06);
    }}
    .result-banner {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      margin-bottom: 10px;
      padding: 8px 12px;
      background: #f8fafc;
      border-radius: 10px;
      border-left: 5px solid #9e9e9e;
      flex-wrap: wrap;
    }}
    .banner-left {{
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .relevance {{
      font-size: 1.08rem;
      font-weight: 900;
    }}
    .llm-arrow {{
      color: #9c27b0;
      font-weight: 950;
      font-size: 1.08rem;
    }}
    .llm-score {{
      color: #9c27b0;
      font-size: 1.08rem;
      font-weight: 950;
    }}
    .llm-delta {{
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 0.82rem;
      font-weight: 900;
    }}
    .llm-delta-up {{
      color: #15803d;
      background: #dcfce7;
    }}
    .llm-delta-down {{
      color: #b91c1c;
      background: #fee2e2;
    }}
    .llm-match-note {{
      margin: 9px 0;
      border: 1px solid #bfdbfe;
      background: #eff6ff;
      color: #1e3a8a;
      border-radius: 12px;
      padding: 10px 12px;
      line-height: 1.55;
      font-size: 0.94rem;
    }}
    .badge {{
      color: white;
      padding: 3px 10px;
      border-radius: 999px;
      font-size: 0.82rem;
      font-weight: 700;
    }}
    .banner-right {{
      font-size: 1rem;
      font-weight: 800;
      color: #d84315;
    }}
    .score-breakdown {{
      display: block;
      font-size: 0.74rem;
      color: var(--muted);
      font-weight: 600;
    }}
    .result-body {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 280px;
      gap: 18px;
    }}
    .title-row {{
      display: flex;
      gap: 10px;
      align-items: flex-start;
      margin-bottom: 8px;
    }}
    .result-index {{
      color: var(--muted);
      font-weight: 700;
      min-width: 28px;
    }}
    .title {{
      font-size: 1.08rem;
      font-weight: 800;
      line-height: 1.45;
    }}
    .meta-row {{
      margin: 7px 0;
      line-height: 1.55;
    }}
    .venue {{
      color: var(--accent);
      font-weight: 800;
    }}
    .tier {{
      color: white;
      padding: 2px 7px;
      border-radius: 6px;
      font-size: 0.82rem;
      font-weight: 800;
    }}
    code {{
      background: #f1f5f9;
      border-radius: 6px;
      padding: 2px 6px;
      font-family: Consolas, monospace;
    }}
    .abstract-box {{
      margin-top: 12px;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px 12px;
      background: #fbfdff;
    }}
    .abstract-box summary {{
      cursor: pointer;
      font-weight: 700;
    }}
    .abstract-text {{
      margin-top: 10px;
      color: #334155;
      line-height: 1.65;
    }}
    .side-col {{
      border-left: 1px dashed var(--line);
      padding-left: 16px;
      display: grid;
      gap: 10px;
      align-content: start;
    }}
    .links a {{
      color: #0f62fe;
      text-decoration: none;
      font-weight: 700;
    }}
    .muted {{
      color: var(--muted);
    }}
    @media (max-width: 900px) {{
      .result-body {{
        grid-template-columns: 1fr;
      }}
      .side-col {{
        border-left: none;
        border-top: 1px dashed var(--line);
        padding-left: 0;
        padding-top: 12px;
      }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <header class="header">
      <h1>ChipSeeker Search Results</h1>
      <p><strong>Query:</strong> {html.escape(search_query or 'No semantic query')}</p>
      <p><strong>Exported:</strong> {html.escape(generated_at)}</p>
      <p><strong>Included Results:</strong> {len(trimmed_results)} / {len(results)}</p>
    </header>
    {''.join(cards)}
  </main>
</body>
</html>
"""
