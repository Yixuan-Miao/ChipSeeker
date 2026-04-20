import requests

from chipseeker.cloud_access import cloud_chat, is_cloud_token


def get_batch_citations(dois, logger=None):
    valid_dois = [doi for doi in dois if doi]
    if not valid_dois:
        return {}
    try:
        response = requests.post(
            "https://api.semanticscholar.org/graph/v1/paper/batch?fields=citationCount",
            json={"ids": [f"DOI:{doi}" for doi in valid_dois]},
            timeout=15,
        )
        if response.status_code == 200:
            data = response.json()
            return {
                item["externalIds"].get("DOI", "").upper(): item.get("citationCount", 0)
                for item in data
                if item and item.get("externalIds")
            }
    except Exception as exc:
        if logger:
            logger.warning("Failed to fetch citations: %s", exc)
    return {}


def call_llm_api(prompt, api_key, base_url, model_name, temp=0.3):
    if is_cloud_token(api_key):
        return cloud_chat(api_key, prompt, model_name=model_name or "deepseek-chat", temperature=temp)

    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url)
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": "You are a top-tier Cryo-CMOS & Quantum IC expert."},
            {"role": "user", "content": prompt},
        ],
        temperature=temp,
    )
    return response.choices[0].message.content


def generate_search_keywords(description, api_key, base_url, model_name):
    prompt = f"""Task: Extract a highly precise English search query (<= 10 words) for vector embedding search. Focus on circuit architectures, cryogenic specs, or quantum qubit control/readout terms.
User Input: "{description}"
Output: ONLY the English query, no quotes, no explanations."""
    return call_llm_api(prompt, api_key, base_url, model_name).strip()


def analyze_with_llm(title, abstract, user_query, api_key, base_url, model_name):
    prompt = f"""Context: User searches "{user_query}".
Title: {title}
Abstract: {abstract}
Format required:
**[Bilingual Title]** **[Core Tech & Metrics]** (Summarize architecture, process node, power, noise, temp limit in Chinese)
**[Relevance]** (How it solves the user's problem)"""
    return call_llm_api(prompt, api_key, base_url, model_name)


def generate_global_report_with_llm(papers_data, user_query, api_key, base_url, model_name):
    papers_text = "".join(
        [f"{idx}. Title: {paper['title']}\nAbstract: {paper['abstract']}\n\n" for idx, paper in enumerate(papers_data, 1)]
    )
    prompt = f"""Focus: "{user_query}". Selected Papers/Chapters:
{papers_text}

Write a comprehensive 'State-of-the-Art Review' in Chinese:
1. **[Trend Overview]**
2. **[Architectures & Topologies]**
3. **[Key Metrics Comparison]**
4. **[Actionable Advice]**"""
    return call_llm_api(prompt, api_key, base_url, model_name, temp=0.5)
