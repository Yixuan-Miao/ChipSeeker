import json
import re

import requests

from chipseeker.cloud_access import cloud_chat, is_cloud_token
from chipseeker.domain_synonyms import synonym_prompt_context


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

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=180.0, max_retries=0)
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "You are a top-tier Cryo-CMOS & Quantum IC expert."},
                {"role": "user", "content": prompt},
            ],
            temperature=temp,
        )
        return response.choices[0].message.content
    except Exception as exc:
        message = str(exc)
        lower_message = message.lower()
        if "authentication" in lower_message or "api key" in lower_message or "401" in lower_message:
            raise RuntimeError(
                "LLM API authentication failed. The saved key is invalid or expired. "
                "Open LLM Review & Analysis -> Configure LLM API and update the key."
            ) from exc
        if "timed out" in lower_message or "timeout" in lower_message:
            raise RuntimeError("LLM request timed out after 3 minutes. Try again later or switch to a faster model.") from exc
        raise


def generate_search_keywords(description, api_key, base_url, model_name):
    prompt = f"""Task: Extract a highly precise English search query (<= 10 words) for vector embedding search. Focus on circuit architectures, cryogenic specs, or quantum qubit control/readout terms.
User Input: "{description}"
Output: ONLY the English query, no quotes, no explanations."""
    return call_llm_api(prompt, api_key, base_url, model_name).strip()


def expand_search_query_with_llm(description, api_key, base_url, model_name):
    synonym_context = synonym_prompt_context(description)
    prompt = f"""Task: Rewrite the user request into one precise English semantic-search query for an IC / AI hardware / quantum hardware paper database.

Rules:
- Keep the user's intent. Do not invent unrelated topics.
- Expand abbreviations and include equivalent technical phrases when useful.
- Prefer architecture, circuit block, application, metrics, and device/process terms.
- Output one line only. No bullets, no quotes.

Domain synonym hints:
{synonym_context or "- No direct dictionary hit. Use your IC design knowledge."}

User request: {description}
"""
    return call_llm_api(prompt, api_key, base_url, model_name, temp=0.2).strip().strip('"')


def _extract_json_array(text):
    text = str(text or "").strip()
    try:
        payload = json.loads(text)
        return payload if isinstance(payload, list) else []
    except Exception:
        pass
    match = re.search(r"\[[\s\S]*\]", text)
    if not match:
        return []
    try:
        payload = json.loads(match.group(0))
        return payload if isinstance(payload, list) else []
    except Exception:
        return []


def rerank_results_with_llm(user_query, expanded_query, results, api_key, base_url, model_name, limit=50):
    candidates = []
    for idx, item in enumerate(results[:limit], start=1):
        paper = item.get("paper", {})
        keywords = paper.get("keywords", [])
        ieee_terms = paper.get("ieee_terms", [])
        if isinstance(keywords, list):
            keywords = "; ".join(keywords[:12])
        if isinstance(ieee_terms, list):
            ieee_terms = "; ".join(ieee_terms[:12])
        candidates.append(
            {
                "id": idx,
                "title": paper.get("title", ""),
                "venue": paper.get("venue", ""),
                "year": paper.get("year", ""),
                "keywords": keywords,
                "ieee_terms": ieee_terms,
                "abstract": str(paper.get("abstract", ""))[:900],
                "semantic_similarity": round(float(item.get("similarity", 0.0)), 4),
            }
        )
    prompt = f"""You are reranking papers for an integrated-circuit researcher.

Original user query:
{user_query}

Expanded semantic query:
{expanded_query}

Score each candidate for true topical relevance to the original user query.
Use the abstract, title, venue, keywords, and IEEE terms.
Prefer papers that solve the user's technical problem, not papers that only share generic words.

Return ONLY a JSON array. Each item must be:
{{"id": <candidate id>, "score": <0-100 integer>, "reason": "<short English reason>"}}

Candidates:
{json.dumps(candidates, ensure_ascii=False)}
"""
    response = call_llm_api(prompt, api_key, base_url, model_name, temp=0.0)
    payload = _extract_json_array(response)
    scores = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        try:
            candidate_id = int(row.get("id"))
        except Exception:
            continue
        score = max(0, min(100, int(float(row.get("score", 0)))))
        scores[candidate_id] = {
            "score": score,
            "reason": str(row.get("reason", "")).strip()[:240],
        }

    reranked = []
    for idx, item in enumerate(results[:limit], start=1):
        item = dict(item)
        if idx in scores:
            item["llm_score"] = scores[idx]["score"]
            item["llm_reason"] = scores[idx]["reason"]
        else:
            item["llm_score"] = int(round(float(item.get("similarity", 0.0)) * 100))
            item["llm_reason"] = "Fallback semantic score; LLM did not return this candidate."
        reranked.append(item)
    reranked.sort(key=lambda item: (item.get("llm_score", 0), item.get("similarity", 0.0)), reverse=True)
    reranked.extend(results[limit:])
    return reranked


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
