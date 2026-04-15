import base64
import csv
import io
import os
import re

from chipseeker.utils import extract_year


def paper_authors(paper):
    authors = paper.get("authors") or [author for author in [paper.get("first_author", ""), paper.get("last_author", "")] if author]
    return authors or ["Unknown"]


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
        last_name = paper.get("first_author", "Anon").split()[-1].replace("-", "")
        year_str = str(extract_year(paper.get("year", "202X")))
        title_words = re.sub(r"[^a-zA-Z0-9\s]", "", paper.get("title", "paper")).split()
        first_word = title_words[0].capitalize() if title_words else "Paper"
        bibkey = f"{last_name}{year_str}{first_word}"
        author_str = " and ".join(paper_authors(paper))
        content += (
            f"@article{{{bibkey},\n"
            f"  title={{{paper.get('title', '')}}},\n"
            f"  author={{{author_str}}},\n"
            f"  journal={{{paper.get('venue', '')}}},\n"
            f"  year={{{paper.get('year', '')}}},\n"
        )
        if paper.get("doi"):
            content += f"  doi={{{paper.get('doi')}}}\n"
        content += "}\n\n"
    return content
