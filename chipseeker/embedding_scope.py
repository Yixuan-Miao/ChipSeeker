from chipseeker.utils import extract_year


def available_years(papers):
    years = sorted({extract_year(paper.get("year", "")) for paper in papers if extract_year(paper.get("year", "")) >= 1900}, reverse=True)
    return years


def filter_papers_by_years(papers, years):
    year_set = {int(year) for year in years}
    return [paper for paper in papers if extract_year(paper.get("year", "")) in year_set]


def build_scope_key(years):
    normalized = sorted({int(year) for year in years}, reverse=True)
    if not normalized:
        return "all"
    return "years_" + "_".join(str(year) for year in normalized)


def scope_label(years):
    normalized = sorted({int(year) for year in years}, reverse=True)
    if not normalized:
        return "Full library"
    if len(normalized) == 1:
        return f"{normalized[0]} only"
    return f"Years: {', '.join(str(year) for year in normalized)}"
