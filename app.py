# ==============================================================================
# Copyright (c) 2026 Miao Yixuan. All rights reserved.
# Author: Miao Yixuan
# Contact: guangeofaisa@gmail.com
#
# PROPRIETARY AND CONFIDENTIAL.
# Unauthorized copying, distribution, modification, or use of this file, 
# via any medium, is strictly prohibited without prior written permission.
# ==============================================================================

import streamlit as st
import json, os, glob, csv, webbrowser, requests, math, re, hashlib, base64
from search import PaperSearcher

def _vx_auth():
    _x = hashlib.sha256(b"MiaoYixuan_ChipSeeker_PRO").hexdigest()
    _y = base64.b64encode(b"guangeofaisa@gmail.com").decode()
    if not _x or not _y: raise SystemExit("ERR_LICENSE: Integrity check failed.")
_vx_auth()

st.set_page_config(page_title="ChipSeeker 芯寻", layout="wide")
st.title("🔬 ChipSeeker 芯寻")
st.markdown("""
**Author:** Miao Yixuan &nbsp;&nbsp;|&nbsp;&nbsp; 
**Email:** [guangeofaisa@gmail.com](mailto:guangeofaisa@gmail.com) &nbsp;&nbsp;|&nbsp;&nbsp; 
**GitHub:** [https://github.com/Yixuan-Miao](https://github.com/Yixuan-Miao)
""")

DB_FILE = 'isscc_papers.json'
CONFIG_FILE = 'config.json'
USER_DATA_FILE = 'user_data.json'

if 'citations_fetched' not in st.session_state:
    st.session_state.citations_fetched = False
    st.session_state.citations_map = {}

def extract_year(year_str):
    match = re.search(r'\d{4}', str(year_str))
    return int(match.group()) if match else 0

def load_json(filepath, default_val):
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f: return json.load(f)
        except: pass
    return default_val

def save_json(filepath, data):
    with open(filepath, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)

app_config = load_json(CONFIG_FILE, {
    "llm_api_key": "", "llm_base_url": "https://api.deepseek.com", 
    "llm_model": "deepseek-chat", "provider_preset": "DeepSeek",
    "embedding_model": "all-MiniLM-L6-v2"
})
user_data = load_json(USER_DATA_FILE, {})

LEGACY_RATING_MAP = {"未评分": "Unrated", "🌟🌟🌟🌟🌟 神作": "🌟🌟🌟🌟🌟 Masterpiece", "⭐⭐⭐⭐ 干货": "⭐⭐⭐⭐ Solid", "⭐⭐⭐ 一般": "⭐⭐⭐ Average", "⭐⭐ 鸡肋": "⭐⭐ Marginal", "💩 垃圾": "💩 Poor"}

def get_user_data(title):
    udata = user_data.get(title, {"rating": "Unrated", "open_count": 0, "comments": "", "matched_queries": []})
    if udata["rating"] in LEGACY_RATING_MAP: udata["rating"] = LEGACY_RATING_MAP[udata["rating"]]
    return udata

def update_user_data(title, key, value):
    if title not in user_data: user_data[title] = {"rating": "Unrated", "open_count": 0, "comments": "", "matched_queries": []}
    user_data[title][key] = value
    save_json(USER_DATA_FILE, user_data)

def get_paper_id(paper): return str(paper.get('doi') or paper.get('title', 'unknown'))

def is_junk_paper(title, abstract):
    tl = title.get('title', '').lower() if isinstance(title, dict) else str(title).lower()
    al = str(abstract).lower()
    jk = [
        "guest editorial", "table of contents", "front cover", "frontmatter",
        "author index", "message from", "call for papers", "committee list",
        "reviewers list", "index of authors", "issue information", "editor's note", 
        "editorial:", "special issue on", "list of reviewers", "special event",
        "student research preview", "srp", "technical session", "plenary session"
    ]
    if any(kw in tl for kw in jk): return True
    if re.search(r'session\s+\d+\s+overview', tl) or re.search(r'^session\s+\d+:', tl): return True
    if len(al) < 100 or al in ["", "na", "n/a", "no abstract available.", "no abstract"]: return True
    return False

def highlight_text(text, keywords):
    if not text or not keywords: return text
    highlighted = text
    for kw in keywords:
        if kw:
            pattern = re.compile(f"({re.escape(kw)})", re.IGNORECASE)
            highlighted = pattern.sub(r'<span style="background-color: #ffeb3b; color: black; font-weight: bold; padding: 0 4px; border-radius: 4px;">\1</span>', highlighted)
    return highlighted

def scan_and_import_csvs():
    csv_files = glob.glob('*.csv')
    if not csv_files: return 0
    all_papers = load_json(DB_FILE, [])
    seen_titles = {p.get('title', '').strip().lower() for p in all_papers}
    new_count = 0
    for file in csv_files:
        try:
            with open(file, mode='r', encoding='utf-8-sig', errors='ignore') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    title = row.get('Document Title', '').strip()
                    abstract = row.get('Abstract', '').strip()
                    if is_junk_paper(title, abstract): 
                        continue
                    if title and abstract and abstract != 'NA':
                        title_norm = title.lower()
                        if title_norm in seen_titles: continue
                        authors_raw = row.get('Authors', '')
                        authors_list = [a.strip() for a in authors_raw.split(';') if a.strip()] if authors_raw else []
                        kw_raw = row.get('Author Keywords', '')
                        paper_obj = {
                            "title": title, "abstract": abstract, "year": row.get('Publication Year', '').strip(),
                            "venue": row.get('Publication Title', '').strip(), "doi": row.get('DOI', '').strip(),
                            "pdf_link": row.get('PDF Link', '').strip(),
                            "first_author": authors_list[0] if authors_list else "Unknown",
                            "last_author": authors_list[-1] if authors_list else "Unknown",
                            "keywords": [k.strip() for k in kw_raw.split(';') if k.strip()]
                        }
                        seen_titles.add(title_norm)
                        all_papers.append(paper_obj)
                        new_count += 1
        except: pass
    if new_count > 0:
        save_json(DB_FILE, all_papers)
        for cache_file in glob.glob('cache_*.npy'): os.remove(cache_file)
    return new_count

current_csv_state = sum(os.path.getmtime(f) for f in glob.glob('*.csv')) if glob.glob('*.csv') else 0
if st.session_state.get('csv_state') != current_csv_state:
    with st.spinner("Syncing Library..."):
        added_count = scan_and_import_csvs()
        st.session_state['csv_state'] = current_csv_state
        if added_count > 0:
            st.toast(f"🎉 Imported {added_count} new entries.")
            if 'get_searcher_engine' in st.session_state: st.cache_resource.clear()

def get_batch_citations(dois):
    valid_dois = [d for d in dois if d]
    if not valid_dois: return {}
    try:
        res = requests.post(
            'https://api.semanticscholar.org/graph/v1/paper/batch?fields=citationCount',
            json={"ids": [f"DOI:{d}" for d in valid_dois]},
            timeout=15
        )
        if res.status_code == 200:
            data = res.json()
            return {item['externalIds'].get('DOI', '').upper(): item.get('citationCount', 0) for item in data if item and item.get('externalIds')}
    except: pass
    return {}

DOMAIN_COLORS = {"Analog Circuits": "#1565C0", "Devices": "#C62828", "Quantum & Physics": "#6A1B9A", "RF & mm-Wave": "#EF6C00", "Education": "#4E342E", "Other": "#757575"}
TIER_COLORS = {"SS": "#9C27B0", "S+": "#D32F2F", "S": "#F57C00", "AA": "#1976D2", "A": "#388E3C", "B": "#757575", "C": "#9E9E9E"}

VENUE_DB = [
    {"k": ["nature electronics"], "n": "Nature Electronics", "t": "SS", "s": 98, "d": ["Devices", "Analog Circuits"], "ty": "Journal", "u": "https://www.nature.com/natelectron/", "if": 33.7, "q": "Q1"},
    {"k": ["nature communications"], "n": "Nature Communications", "t": "SS", "s": 97, "d": ["Quantum & Physics", "Devices"], "ty": "Journal", "u": "https://www.nature.com/ncomms/", "if": 14.8, "q": "Q1"},
    {"k": ["nature physics"], "n": "Nature Physics", "t": "SS", "s": 97, "d": ["Quantum & Physics"], "ty": "Journal", "u": "https://www.nature.com/nphys/", "if": 19.6, "q": "Q1"},
    {"k": ["nature nanotechnology"], "n": "Nature Nanotech", "t": "SS", "s": 97, "d": ["Devices", "Quantum & Physics"], "ty": "Journal", "u": "https://www.nature.com/nnano/", "if": 38.3, "q": "Q1"},
    {"k": ["nature"], "n": "Nature", "t": "SS", "s": 99, "d": ["Quantum & Physics", "Devices", "Analog Circuits"], "ty": "Journal", "u": "https://www.nature.com/", "if": 50.5, "q": "Q1"},
    {"k": ["science"], "n": "Science", "t": "SS", "s": 99, "d": ["Quantum & Physics", "Devices", "Analog Circuits"], "ty": "Journal", "u": "https://www.science.org/", "if": 44.7, "q": "Q1"},
    {"k": ["cell device", "device"], "ex": ["electron", "circuit", "system", "solid"], "n": "Device (Cell)", "t": "SS", "s": 96, "d": ["Devices"], "ty": "Journal", "u": "https://www.cell.com/device/home", "if": 10.7, "q": "Q1"},
    {"k": ["prx", "physical review x"], "n": "PRX", "t": "SS", "s": 96, "d": ["Quantum & Physics"], "ty": "Journal", "u": "https://journals.aps.org/prx/", "if": 12.5, "q": "Q1"},
    {"k": ["isscc", "solid-state circuits conference"], "ex": ["asian", "a-sscc", "european", "esscirc"], "n": "ISSCC", "t": "S+", "s": 95, "d": ["Analog Circuits", "RF & mm-Wave", "Quantum & Physics"], "ty": "Conference", "u": "https://www.isscc.org/"},
    {"k": ["jssc", "journal of solid-state circuits"], "n": "JSSC", "t": "S+", "s": 94, "d": ["Analog Circuits", "RF & mm-Wave"], "ty": "Journal", "u": "https://ieeexplore.ieee.org/xpl/RecentIssue.jsp?punumber=4", "if": 6.2, "q": "Q1"},
    {"k": ["vlsi", "symposium on vlsi"], "n": "VLSI", "t": "S+", "s": 92, "d": ["Analog Circuits", "Devices"], "ty": "Conference", "u": "https://www.vlsisymposium.org/"},
    {"k": ["prl", "physical review letters"], "n": "PRL", "t": "S", "s": 90, "d": ["Quantum & Physics"], "ty": "Journal", "u": "https://journals.aps.org/prl/", "if": 8.1, "q": "Q1"},
    {"k": ["iedm", "electron devices meeting"], "n": "IEDM", "t": "S", "s": 90, "d": ["Devices", "Analog Circuits"], "ty": "Conference", "u": "https://www.ieee-iedm.org/"},
    {"k": ["npj quantum information", "quantum information"], "n": "npj Quantum Info", "t": "S", "s": 88, "d": ["Quantum & Physics"], "ty": "Journal", "u": "https://www.nature.com/npjqi/", "if": 9.2, "q": "Q1"},
    {"k": ["quantum"], "n": "Quantum", "t": "S", "s": 88, "d": ["Quantum & Physics"], "ty": "Journal", "u": "https://quantum-journal.org/", "if": 6.7, "q": "Q1"},
    {"k": ["tcas-ii", "tcas ii", "circuits and systems ii"], "n": "TCAS-II", "t": "A", "s": 82, "d": ["Analog Circuits"], "ty": "Journal", "u": "https://ieee-cas.org/pubs/tcas-ii", "if": 4.8, "q": "Q2"},
    {"k": ["tcas-i", "tcas i", "circuits and systems i"], "n": "TCAS-I", "t": "AA", "s": 85, "d": ["Analog Circuits"], "ty": "Journal", "u": "https://ieee-cas.org/pubs/tcas-i", "if": 5.1, "q": "Q1"},
    {"k": ["tmtt", "microwave theory and techniques"], "n": "TMTT", "t": "AA", "s": 85, "d": ["RF & mm-Wave"], "ty": "Journal", "u": "https://mtt.org/publications/transactions-on-microwave-theory-and-techniques/", "if": 4.7, "q": "Q1"},
    {"k": ["tbcas", "biomedical circuits and systems", "biocas"], "n": "BioCAS/TBCAS", "t": "AA", "s": 85, "d": ["Analog Circuits"], "ty": "Journal", "u": "https://ieee-cas.org/pubs/tbcas", "if": 5.5, "q": "Q1"},
    {"k": ["tqe", "quantum engineering"], "n": "IEEE TQE", "t": "A", "s": 80, "d": ["Quantum & Physics"], "ty": "Journal", "u": "https://tqe.ieee.org/", "if": 3.8, "q": "Q2"},
    {"k": ["cicc", "custom integrated circuits"], "n": "CICC", "t": "AA", "s": 85, "d": ["Analog Circuits"], "ty": "Conference", "u": "https://ieee-cicc.org/"},
    {"k": ["esscirc", "european solid-state circuits", "european solid state circuits", "european solid-state", "european solid state"], "n": "ESSCIRC", "t": "AA", "s": 85, "d": ["Analog Circuits"], "ty": "Conference", "u": "https://www.esscirc-essderc.org/"},
    {"k": ["rfic", "radio frequency integrated circuits"], "n": "RFIC", "t": "AA", "s": 85, "d": ["RF & mm-Wave", "Analog Circuits"], "ty": "Conference", "u": "https://rfic-ieee.org/"},
    {"k": ["a-sscc", "asscc", "asian solid-state", "asian solid state"], "n": "A-SSCC", "t": "AA", "s": 85, "d": ["Analog Circuits"], "ty": "Conference", "u": "https://www.a-sscc.org/"},
    {"k": ["dac", "design automation conference"], "n": "DAC", "t": "AA", "s": 85, "d": ["Analog Circuits", "EDA"], "ty": "Conference", "u": "https://www.dac.com/"},
    {"k": ["iccad"], "n": "ICCAD", "t": "AA", "s": 85, "d": ["Analog Circuits", "EDA"], "ty": "Conference", "u": "https://iccad.com/"},
    {"k": ["ims", "international microwave symposium"], "n": "IMS", "t": "A", "s": 82, "d": ["RF & mm-Wave"], "ty": "Conference", "u": "https://ims-ieee.org/"},
    {"k": ["textbook", "book", "textbooks"], "n": "Textbook", "t": "A", "s": 82, "d": ["Education"], "ty": "Textbook", "u": "#"},
    {"k": ["ssc-l", "solid-state circuits letters"], "n": "SSC-L", "t": "A", "s": 80, "d": ["Analog Circuits"], "ty": "Journal", "u": "https://sscs.ieee.org/publications/ieee-solid-state-circuits-letters", "if": 3.5, "q": "Q2"},
    {"k": ["ted", "transactions on electron devices"], "n": "TED", "t": "A", "s": 80, "d": ["Devices"], "ty": "Journal", "u": "https://eds.ieee.org/publications/transactions-on-electron-devices", "if": 3.4, "q": "Q2"},
    {"k": ["apl", "applied physics letters"], "n": "APL", "t": "A", "s": 80, "d": ["Quantum & Physics", "Devices"], "ty": "Journal", "u": "https://pubs.aip.org/aip/apl", "if": 4.0, "q": "Q2"},
    {"k": ["prb", "physical review b"], "n": "PRB", "t": "A", "s": 80, "d": ["Quantum & Physics"], "ty": "Journal", "u": "https://journals.aps.org/prb/", "if": 3.7, "q": "Q2"},
    {"k": ["mwcl", "microwave and wireless components"], "n": "MWCL", "t": "A", "s": 80, "d": ["RF & mm-Wave"], "ty": "Journal", "u": "https://mtt.org/publications/microwave-and-wireless-components-letters/", "if": 3.2, "q": "Q2"},
    {"k": ["rsi", "review of scientific instruments"], "n": "Rev. Sci. Instrum.", "t": "B", "s": 75, "d": ["Quantum & Physics", "Devices"], "ty": "Journal", "u": "https://pubs.aip.org/aip/rsi", "if": 1.6, "q": "Q3"},
    {"k": ["tas", "applied superconductivity"], "n": "IEEE TAS", "t": "B", "s": 75, "d": ["Quantum & Physics"], "ty": "Journal", "u": "https://ieeexplore.ieee.org/xpl/RecentIssue.jsp?punumber=77", "if": 1.8, "q": "Q3"},
    {"k": ["iscas"], "n": "ISCAS", "t": "B", "s": 75, "d": ["Analog Circuits"], "ty": "Conference", "u": "https://ieee-cas.org/conferences/iscas"},
    {"k": ["iws", "international wireless symposium", "wireless symposium"], "n": "IWS", "t": "B", "s": 75, "d": ["RF & mm-Wave"], "ty": "Conference", "u": "https://mtt.org/conferences/iws/"},
    {"k": ["tcas", "circuits and systems"], "ex": ["tcas-i", "tcas i", "tcas-ii", "tcas ii"], "n": "TCAS (Gen)", "t": "B", "s": 70, "d": ["Analog Circuits"], "ty": "Journal", "u": "https://ieee-cas.org/", "if": 2.9, "q": "Q3"},
    {"k": ["sscm", "solid-state circuits magazine"], "n": "SSC-M", "t": "C", "s": 65, "d": ["Analog Circuits"], "ty": "Journal", "u": "https://sscs.ieee.org/publications/ieee-solid-state-circuits-magazine", "if": 1.5, "q": "Q4"},
    {"k": ["mwcas"], "n": "MWCAS", "t": "C", "s": 60, "d": ["Analog Circuits"], "ty": "Conference", "u": "#"},
    {"k": ["apccas"], "n": "APCCAS", "t": "C", "s": 60, "d": ["Analog Circuits"], "ty": "Conference", "u": "#"},
    {"k": ["icta"], "n": "ICTA", "t": "C", "s": 60, "d": ["Analog Circuits"], "ty": "Conference", "u": "#"},
    {"k": ["appeec"], "n": "APPEEC", "t": "C", "s": 60, "d": ["Analog Circuits"], "ty": "Conference", "u": "#"}
]

def analyze_venue(venue_str):
    v_lower = venue_str.lower()
    for v in VENUE_DB:
        if "ex" in v and any(ex in v_lower for ex in v["ex"]): continue
        for k in v["k"]:
            if len(k) <= 6:
                if re.search(r'\b' + re.escape(k) + r'\b', v_lower): return v
            else:
                if k in v_lower: return v
    return {"n": "Other", "t": "C", "s": 50, "d": ["Other"], "ty": "Journal", "u": "#", "if": None, "q": None}

def get_venue_display_str(v_data):
    if v_data['n'] == 'Other': return "Other"
    if v_data['ty'] == 'Journal': 
        if_str = ""
        if v_data.get('if') and v_data.get('q'):
            if_str = f" (IF: {v_data['if']}, {v_data['q']})"
        elif v_data.get('if'):
            if_str = f" (IF: {v_data['if']})"
        return f"{v_data['n']}{if_str}"
    elif v_data['ty'] == 'Conference': return f"{v_data['n']} (Conference)"
    elif v_data['ty'] == 'Textbook': return f"{v_data['n']} (Textbook)"
    return v_data['n']

def call_llm_api(prompt, api_key, base_url, model_name, temp=0.3):
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=base_url)
    try:
        response = client.chat.completions.create(model=model_name, messages=[{"role": "system", "content": "You are a top-tier Cryo-CMOS & Quantum IC expert."}, {"role": "user", "content": prompt}], temperature=temp)
        return response.choices[0].message.content
    except Exception as e: raise Exception(f"API Error: {str(e)}")

def generate_search_keywords(description, api_key, base_url, model_name):
    prompt = f"""Task: Extract a highly precise English search query (<= 10 words) for vector embedding search. Focus on circuit architectures, cryogenic specs, or quantum qubit control/readout terms.
User Input: "{description}"
Output: ONLY the English query, no quotes, no explanations."""
    return call_llm_api(prompt, api_key, base_url, model_name).strip()

def analyze_with_llm(title, abstract, user_query, api_key, base_url, model_name):
    prompt = f"""Context: User searches "{user_query}".
Title: {title}\nAbstract: {abstract}
Format required:
**[Bilingual Title]** **[Core Tech & Metrics]** (Summarize architecture, process node, power, noise, temp limit in Chinese)
**[Relevance]** (How it solves the user's problem)"""
    return call_llm_api(prompt, api_key, base_url, model_name)

def generate_global_report_with_llm(papers_data, user_query, api_key, base_url, model_name):
    papers_text = "".join([f"{idx}. Title: {p['title']}\nAbstract: {p['abstract']}\n\n" for idx, p in enumerate(papers_data, 1)])
    prompt = f"""Focus: "{user_query}". Selected Papers/Chapters: \n{papers_text}\n
Write a comprehensive 'State-of-the-Art Review' in Chinese:
1. **[Trend Overview]**
2. **[Architectures & Topologies]**
3. **[Key Metrics Comparison]**
4. **[Actionable Advice]**"""
    return call_llm_api(prompt, api_key, base_url, model_name, temp=0.5)

all_papers_in_db = load_json(DB_FILE, [])
def generate_db_stats():
    stats, active_years = {}, set()
    for p in all_papers_in_db:
        venue_str = p.get('venue', '')
        year = extract_year(p.get('year', ''))
        if year < 1900: continue
        v_data = analyze_venue(venue_str)
        v_name = v_data["n"]
        if v_name != 'Other':
            if v_name not in stats: stats[v_name] = {'data': v_data, 'years': {}}
            stats[v_name]['years'][year] = stats[v_name]['years'].get(year, 0) + 1
            active_years.add(year)
    return len(all_papers_in_db), stats, sorted(list(active_years), reverse=True)

total_papers, db_stats, active_years = generate_db_stats()

with st.expander(f"📊 Taxonomy & Library Matrix (Total Records: {total_papers})", expanded=True):
    if active_years:
        show_all = st.checkbox("Show all earlier years 🔽")
        display_years = active_years if show_all else [y for y in active_years if y >= 2019]
        older_years = [] if show_all else [y for y in active_years if y < 2019]
        has_older = len(older_years) > 0

        table_md = "| **Venue** | **Tier** | **Domain** | " + " | ".join(map(str, display_years))
        if has_older: table_md += " | **Earlier** |"
        table_md += "\n|---|---|---|---" + "|---" * (len(display_years) - 1)
        if has_older: table_md += "|---|"
        table_md += "\n"
        
        sorted_venues = sorted(db_stats.items(), key=lambda x: x[1]['data']['s'], reverse=True)

        for v_name, content in sorted_venues:
                if sum(content['years'].values()) < 50:
                    continue

                d = content['data']
                tier_color = TIER_COLORS.get(d['t'], "#9E9E9E")
                
                venue_display = get_venue_display_str(d)
                venue_styled = f"**[{venue_display}]({d['u']})**"
                tier_styled = f"<span style='background-color:{tier_color}; color:white; padding:2px 6px; border-radius:4px; font-size:0.8em; font-weight:bold;'>{d['t']}</span>"
                domains_html = " ".join([f"<span style='color:{DOMAIN_COLORS.get(dom, '#757575')}; border: 1px solid {DOMAIN_COLORS.get(dom, '#757575')}; padding: 1px 4px; border-radius: 4px; font-size: 0.75em;'>{dom}</span>" for dom in d['d']])
                
                row = f"| {venue_styled} | {tier_styled} | {domains_html} |"
                for y in display_years:
                    c = content['years'].get(y, 0)
                    row += f" {c if c > 0 else '-'} |"
                if has_older:
                    older_c = sum(content['years'].get(y, 0) for y in older_years)
                    row += f" {older_c if older_c > 0 else '-'} |"
                table_md += row + "\n"
        st.markdown(table_md, unsafe_allow_html=True)
    else:
        st.info("No recognized venues found. Please import CSV files.")

st.sidebar.header("⚙️ Embedding Engine")

emb_models = [
    "voyage-4-large",
    "voyage-4",
    "voyage-4-lite",
    "voyage-context-3",
    "text-embedding-3-large",
    "all-MiniLM-L6-v2"
]
current_emb_idx = emb_models.index(app_config.get("embedding_model", "all-MiniLM-L6-v2")) if app_config.get("embedding_model") in emb_models else 5
selected_emb_model = st.sidebar.selectbox("Model", emb_models, index=current_emb_idx)

emb_api_key = ""
if "voyage" in selected_emb_model or "text-embedding" in selected_emb_model:
    emb_api_key = st.sidebar.text_input(f"{selected_emb_model.split('-')[0].capitalize()} API Key", 
                                        value=app_config.get("emb_api_key", ""), 
                                        type="password", 
                                        help="Required for non-local API embedding models")

st.sidebar.markdown("---")
st.sidebar.header("🧠 LLM API Config")
preset_options = ["DeepSeek", "SiliconFlow", "Kimi", "Custom OpenAI"]
current_preset = st.sidebar.selectbox("Provider Preset", preset_options, index=preset_options.index(app_config.get("provider_preset", "DeepSeek")) if app_config.get("provider_preset") in preset_options else 0)

default_base, default_model = "", ""
if current_preset == "DeepSeek": default_base, default_model = "https://api.deepseek.com", "deepseek-chat"
elif current_preset == "SiliconFlow": default_base, default_model = "https://api.siliconflow.cn/v1", "Qwen/Qwen2.5-7B-Instruct"
elif current_preset == "Kimi": default_base, default_model = "https://api.moonshot.cn/v1", "moonshot-v1-8k"
else: default_base, default_model = app_config.get("llm_base_url", ""), app_config.get("llm_model", "")

api_key = st.sidebar.text_input("LLM API Key", value=app_config.get("llm_api_key", ""), type="password")
base_url = st.sidebar.text_input("Base URL", value=default_base)
model_name = st.sidebar.text_input("Model ID", value=default_model)

if st.sidebar.button("💾 Save Global Config", use_container_width=True):
    app_config.update({
        "embedding_model": selected_emb_model, 
        "emb_api_key": emb_api_key, 
        "provider_preset": current_preset, 
        "llm_api_key": api_key, 
        "llm_base_url": base_url, 
        "llm_model": model_name
    })
    save_json(CONFIG_FILE, app_config)
    if 'get_searcher_engine' in st.session_state: st.cache_resource.clear()
    st.sidebar.success("✅ Config Saved.")

@st.cache_resource(show_spinner=False)
def get_searcher_engine(db_file, model_name, _emb_api_key=""):
    return PaperSearcher(db_file, model_name=model_name, api_key=_emb_api_key)

safe_name = app_config.get("embedding_model", "all-MiniLM-L6-v2").replace('/', '_')
cache_file = f"cache_{safe_name}.npy"

if not os.path.exists(cache_file) and os.path.exists(DB_FILE):
    with st.spinner(f"🚀 Initializing {app_config.get('embedding_model')}. Building embedding matrix..."):
        searcher = get_searcher_engine(DB_FILE, app_config.get("embedding_model", "all-MiniLM-L6-v2"), app_config.get("emb_api_key", ""))
    st.toast("✅ Matrix built successfully!")
else:
    searcher = get_searcher_engine(DB_FILE, app_config.get("embedding_model", "all-MiniLM-L6-v2"), app_config.get("emb_api_key", ""))

if not searcher: st.stop()

st.sidebar.markdown("---")
st.sidebar.header("🧹 DB Maintenance")
if st.sidebar.button("Purge Junk Papers", help="Scans and removes non-academic entries based on enhanced regex", use_container_width=True):
    with st.spinner("Scanning and purging junk..."):
        all_p = load_json(DB_FILE, [])
        original_len = len(all_p)
        clean_p = [p for p in all_p if not is_junk_paper(p.get('title', ''), p.get('abstract', ''))]
        removed = original_len - len(clean_p)
        
        if removed > 0:
            save_json(DB_FILE, clean_p)
            for c_f in glob.glob('cache_*.npy'): os.remove(c_f)
            if 'get_searcher_engine' in st.session_state: st.cache_resource.clear()
            st.sidebar.success(f"✅ Success! Purged {removed} junk entries.")
        else:
            st.sidebar.info("Database is already clean. No junk found.")

st.markdown("---")
st.markdown("### 💡 Keyword Generator")
user_idea = st.text_input("Describe your topic in any language (Press Enter to generate keywords)...", key="user_idea_input")

if user_idea and user_idea != st.session_state.get('last_idea'):
    if not api_key: st.error("Please configure API Key first.")
    else:
        with st.spinner("Generating..."):
            try:
                best_kw = generate_search_keywords(user_idea, api_key, base_url, model_name)
                st.session_state.kw_result = best_kw
                st.session_state.last_idea = user_idea
            except Exception as e: st.error(str(e))

if st.session_state.get('kw_result'):
    st.info(f"👉 **Suggested Keywords:** `{st.session_state.kw_result}`")

st.markdown("---")
st.markdown("### 🎯 Hybrid Search Engine")

with st.expander("🛠️ Metadata Pre-Filters (Optional)", expanded=False):
    c_f1, c_f2 = st.columns(2)
    with c_f1:
        unique_parsed_venues = sorted(list(set([analyze_venue(p.get('venue', ''))['n'] for p in all_papers_in_db if p.get('venue')])))
        unique_parsed_venues = [v for v in unique_parsed_venues if v != "Other"]
        selected_ui_venues = st.multiselect("Filter by Unified Venue", unique_parsed_venues)
        
    with c_f2:
        if active_years: 
            min_y, max_y = min(active_years), max(active_years)
            # 🌟 核心修复：如果只有一个年份，强行把下限往前推一年，避免滑动条崩溃
            if min_y == max_y: min_y -= 1 
            selected_years = st.slider("Filter by Year", min_y, max_y, (min_y, max_y))
        else: 
            selected_years = (2000, 2026)

col_s1, col_s2, col_s3 = st.columns([3, 2, 1])
with col_s1: search_query = st.text_input("1. Semantic Query (Optional)", placeholder="Leave blank for pure keyword/filter search")
with col_s2: must_have = st.text_input("2. Exact Match (AND/OR logic)", help="Space = OR. Comma (,) or Ampersand (&) = AND. E.g., 'pulsed LNA, 65nm'")
with col_s3: top_k_val = st.number_input("3. Search Depth (Top-K)", min_value=50, max_value=2000, value=50, step=50)

trigger_search = bool(search_query or selected_ui_venues or must_have)

if trigger_search:
    query_state_key = f"{search_query}_must{must_have}_top{top_k_val}_{app_config.get('embedding_model')}_v{selected_ui_venues}_y{selected_years}"
    if 'current_query' not in st.session_state or st.session_state.current_query != query_state_key:
        st.session_state.citations_fetched = False
        st.session_state.citations_map = {}
        
        with st.spinner(f"Scanning Library..."):
            if search_query: 
                raw_hits = searcher.search(query=search_query, top_k=top_k_val)
            else: 
                raw_hits = [{"similarity": 1.0, "paper": p} for p in all_papers_in_db]

            filtered_results = []
            
            and_groups = []
            if must_have:
                and_groups_raw = re.split(r'[,&]', must_have)
                for group in and_groups_raw:
                    or_words = [w.strip().lower() for w in group.split() if w.strip()]
                    if or_words: and_groups.append(or_words)
            
            for item in raw_hits:
                p = item['paper']
                y_val = extract_year(p.get('year', ''))
                if not (selected_years[0] <= y_val <= selected_years[1]): continue
                
                if selected_ui_venues:
                    parsed_v = analyze_venue(p.get('venue', ''))['n']
                    if parsed_v not in selected_ui_venues: continue

                if and_groups:
                    author_str = f"{p.get('first_author', '')} {p.get('last_author', '')}"
                    kw_str = " ".join(p.get('keywords', []))
                    corpus = f"{p.get('title', '')} {p.get('abstract', '')} {author_str} {p.get('venue', '')} {kw_str}".lower()
                    
                    is_match = True
                    for or_words in and_groups:
                        group_match = False
                        for ow in or_words:
                            if re.search(r'\b' + re.escape(ow) + r'\b', corpus):
                                group_match = True
                                break
                        if not group_match:
                            is_match = False
                            break
                    
                    if not is_match: continue
                
                filtered_results.append(item)
            
            st.session_state.raw_results = filtered_results
            st.session_state.initial_count = len(raw_hits)
            st.session_state.current_query = query_state_key
            
            for item in st.session_state.raw_results:
                if item['similarity'] >= 0.25 and search_query:
                    title = item['paper'].get('title')
                    udata = get_user_data(title)
                    if search_query not in udata['matched_queries']:
                        udata['matched_queries'].append(search_query)
                        update_user_data(title, "matched_queries", udata['matched_queries'])
            
            for key in list(st.session_state.keys()):
                if key.startswith("chk_"): del st.session_state[key]

results = st.session_state.get('raw_results', [])
initial_c = st.session_state.get('initial_count', 0)

required_words_hl = []
if must_have:
    for group in re.split(r'[,&]', must_have):
        required_words_hl.extend([w.strip() for w in group.split() if w.strip()])

if trigger_search:
    if not results:
        st.warning(f"📭 {initial_c} records scanned, but all were eliminated by your Strict Filters.")
        st.stop()
    else:
        c_rare = sum(1 for i in results if i['similarity'] >= 0.60 or not search_query)
        c_perf = sum(1 for i in results if 0.40 <= i['similarity'] < 0.60 and search_query)
        c_valu = sum(1 for i in results if 0.25 <= i['similarity'] < 0.40 and search_query)
        c_rele = sum(1 for i in results if 0.15 <= i['similarity'] < 0.25 and search_query)
        st.success(f"✅ Extracted **{len(results)}** precise matches. (💎 Rare/All: {c_rare} | 🎯 Perfect: {c_perf} | ⭐ Valuable: {c_valu} | 💡 Relevant: {c_rele})")

        y_c = {}
        for r in results:
            y = extract_year(r['paper'].get('year', ''))
            if y > 1900: y_c[y] = y_c.get(y, 0) + 1
        if y_c:
            with st.expander("📈 Analytics: Publication Trend", expanded=False):
                st.bar_chart(y_c)

st.markdown("---")

col_sort, col_batch, col_cite = st.columns([1.5, 2.5, 1])

with col_sort:
    st.markdown("### 🔀 Sort By")
    sort_option = st.radio("Dimension", ["⚡ Relevance", "📅 Year (Newest)", "🏆 Comprehensive Score"], horizontal=True, label_visibility="collapsed")

with col_cite:
    st.markdown("### 🔄 Citations")
    default_fetch_num = sum(1 for i in results if i['similarity'] >= 0.40 or not search_query)
    if default_fetch_num == 0 and len(results) > 0: default_fetch_num = min(10, len(results))
    fetch_limit = st.number_input("Fetch Count (Top-N)", min_value=0, max_value=max(1, len(results)), value=min(default_fetch_num, len(results)), step=10, label_visibility="collapsed")
    if st.button("Fetch & Update Scores", use_container_width=True):
        with st.spinner(f"Batch fetching citations for top {fetch_limit} papers..."):
            dois_to_fetch = [r['paper'].get('doi') for r in results if r['paper'].get('doi')][:fetch_limit]
            st.session_state.citations_map = get_batch_citations(dois_to_fetch)
            st.session_state.citations_fetched = True
            st.rerun()

if sort_option == "📅 Year (Newest)":
    results = sorted(results, key=lambda x: (extract_year(x['paper'].get('year', '')), x['similarity']), reverse=True)
elif sort_option == "🏆 Comprehensive Score":
    with st.spinner("Calculating Rankings..."):
        high_val_results = [r for r in results if (r['similarity'] >= 0.25 or not search_query)]
        for r in high_val_results:
            p = r['paper']
            y_val = extract_year(p.get('year', ''))
            cites = st.session_state.citations_map.get(p.get('doi', '').upper(), 0) if st.session_state.citations_fetched else 0
            v_data = analyze_venue(p.get('venue', ''))
            b_score = v_data['s']
            y_bonus = max(0, 10 - (2026 - y_val)) if y_val > 1900 and (2026 - y_val) < 10 else (10 if y_val > 1900 and (2026 - y_val) <= 0 else 0)
            c_bonus = min(15, math.log10(cites + 1) * 6) if cites > 0 else 0
            r['comp_score'] = b_score + y_bonus + c_bonus
        results = sorted(high_val_results, key=lambda x: x['comp_score'], reverse=True)

with col_batch:
    st.markdown("### 🛠️ Batch Select")
    rel_threshold = st.slider("Select Relevance >=", 0.0, 1.0, 0.40, 0.05)
    c_b1, c_b2, c_b3, c_b4 = st.columns(4)
    
    def do_batch_select(mode, val=None):
        count = 0
        for idx, item in enumerate(results):
            p = item['paper']
            sim = item['similarity']
            chk_key = f"chk_{idx}_{get_paper_id(p)}" 
            if mode == 'threshold' and (sim >= val or not search_query): 
                st.session_state[chk_key] = True
                count += 1
            elif mode == 'perfect' and (sim >= 0.40 or not search_query): 
                st.session_state[chk_key] = True
                count += 1
            elif mode == 'valuable' and 0.25 <= sim < 0.40 and search_query: 
                st.session_state[chk_key] = True
                count += 1
            elif mode == 'deselect': 
                st.session_state[chk_key] = False
                count += 1
        if mode == 'deselect': st.toast("🧹 Cleared all selections.")
        else: st.toast(f"✅ Successfully selected {count} papers!")

    with c_b1: st.button(f"≥ {rel_threshold:.2f}", on_click=do_batch_select, args=('threshold', rel_threshold), use_container_width=True)
    with c_b2: st.button("🎯 Perfect", on_click=do_batch_select, args=('perfect',), use_container_width=True)
    with c_b3: st.button("⭐ Valuable", on_click=do_batch_select, args=('valuable',), use_container_width=True)
    with c_b4: st.button("❌ Clear All", on_click=do_batch_select, args=('deselect',), use_container_width=True)

st.markdown("---")

selected_papers = []
high_value_papers_for_report = [] 

for idx, item in enumerate(results):
    paper = item['paper']
    sim = item['similarity']
    title = paper.get('title', 'Untitled')
    venue = paper.get('venue', 'Unknown Venue')
    year = paper.get('year', 'N/A')
    doi = paper.get('doi', '')
    abstract = paper.get('abstract', 'No Abstract')
    author_str = f"{paper.get('first_author', 'Unknown')} ... {paper.get('last_author', 'Unknown')}"
    
    chk_key = f"chk_{idx}_{get_paper_id(paper)}" 
    udata = get_user_data(title)
    
    v_data = analyze_venue(venue)
    base_score = v_data['s']
    tier_label = v_data['t']
    domain_color = DOMAIN_COLORS.get(v_data['d'][0], "#757575")
    tier_color = TIER_COLORS.get(v_data['t'], "#9E9E9E")
    
    y_val = extract_year(year)
    year_bonus = max(0, 10 - (2026 - y_val)) if y_val > 1900 and (2026 - y_val) < 10 else (10 if y_val > 1900 and (2026 - y_val) <= 0 else 0)
    
    if sim >= 0.60 or not search_query: color, badge = "#9C27B0", "💎 Rare Match"
    elif sim >= 0.40: color, badge = "#00C853", "🎯 Perfect Match"
    elif sim >= 0.25: color, badge = "#2196F3", "⭐ Highly Valuable"
    elif sim >= 0.15: color, badge = "#FF9800", "💡 Relevant"
    else: color, badge = "#9E9E9E", "🗑️ Noise"

    if sim >= 0.25 or not search_query: high_value_papers_for_report.append(paper)

    hl_title = highlight_text(title, required_words_hl)
    hl_author = highlight_text(author_str, required_words_hl)
    venue_display_str = get_venue_display_str(v_data)
    hl_venue = highlight_text(venue_display_str, required_words_hl)
    hl_abstract = highlight_text(abstract, required_words_hl)

    cites = st.session_state.citations_map.get(doi.upper(), 0) if st.session_state.citations_fetched else 0
    cite_bonus = min(15, math.log10(cites + 1) * 6) if cites > 0 else 0
    final_score = item.get('comp_score', base_score + year_bonus + cite_bonus)

    st.markdown(f"""
        <div style="display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; margin-bottom: 8px; padding: 6px 12px; background-color: #f8f9fa; border-radius: 8px; border-left: 5px solid {color}; gap: 10px;">
            <div style="flex: 1 1 auto; min-width: 200px;">
                <span style="font-size: 1.1em; font-weight: 900; color: {color};">Relevance: {sim * 100:.1f}%</span>
                <span style="background-color: {color}; color: white; padding: 2px 8px; border-radius: 12px; margin-left: 10px; font-size: 0.8em; display: inline-block;">{badge}</span>
            </div>
            <div style="flex: 0 1 auto; text-align: right; font-size: 1.05em; font-weight: bold; color: #D84315;">
                🏆 Score: {final_score:.1f} <span style="font-size:0.7em; color:#757575;">(Base {base_score} + Yr {year_bonus} + Cites {cite_bonus:.1f})</span>
            </div>
        </div>""", unsafe_allow_html=True)

    c1, c2, c3 = st.columns([6, 2, 2])
    with c1:
        cc1, cc2 = st.columns([0.5, 9.5])
        with cc1: checked = st.checkbox(" ", key=chk_key, label_visibility="collapsed")
        with cc2: st.markdown(f"<span style='font-size:1.1em; font-weight:bold;'>{hl_title}</span>", unsafe_allow_html=True)
            
        st.markdown(f"**👨‍🔬 Authors:** {hl_author}", unsafe_allow_html=True)
        st.markdown(f"**🏛️ Venue:** <span style='color:{domain_color}; font-weight:bold;'>{hl_venue}</span> ({year}) &nbsp;&nbsp;|&nbsp;&nbsp; **Tier:** <span style='background-color:{tier_color}; color:white; padding:2px 6px; border-radius:4px; font-size:0.85em; font-weight:bold;'>{tier_label}</span>", unsafe_allow_html=True)
        if udata['matched_queries']:
            st.markdown(f"**💡 Matched:** " + " ".join([f"`🎯 {q}`" for q in udata['matched_queries']]))
            
    with c2:
        st.markdown(f"**👀 Reads:** `{udata['open_count']}`")
        if st.session_state.citations_fetched:
            st.markdown(f"**🔥 Cites:** `{cites}` `✅ Fetched`")
        else:
            st.markdown("**🔥 Cites:** `⏳ Pending (Manual Fetch)`")
        
    with c3:
        new_rating = st.selectbox("Rating", ["Unrated", "🌟🌟🌟🌟🌟 Masterpiece", "⭐⭐⭐⭐ Solid", "⭐⭐⭐ Average", "⭐⭐ Marginal", "💩 Poor"],
            index=["Unrated", "🌟🌟🌟🌟🌟 Masterpiece", "⭐⭐⭐⭐ Solid", "⭐⭐⭐ Average", "⭐⭐ Marginal", "💩 Poor"].index(udata['rating']), key=f"rate_{chk_key}", label_visibility="collapsed")
        if new_rating != udata['rating']: update_user_data(title, "rating", new_rating)
        
        new_comments = st.text_input("Notes", value=udata['comments'], key=f"comment_{chk_key}", placeholder="Take notes...")
        if new_comments != udata['comments']: update_user_data(title, "comments", new_comments)

    if checked: selected_papers.append(paper)

    with st.expander("📖 Read Abstract"): 
        st.markdown(hl_abstract, unsafe_allow_html=True)

    if sim >= 0.25 or not search_query:
        with st.expander("🤖 AI Deep Dive"):
            if st.button("🚀 Analyze with LLM", key=f"ai_btn_{chk_key}"):
                if not api_key: st.error("API Key missing.")
                else:
                    with st.spinner("Analyzing..."):
                        try: st.markdown(analyze_with_llm(title, abstract, search_query or "Summarize", api_key, base_url, model_name))
                        except Exception as e: st.error(str(e))
    
    st.markdown("---")

st.sidebar.markdown("---")
st.sidebar.header("🧠 Global Insights")
if len(high_value_papers_for_report) > 0:
    if st.sidebar.button("📊 Generate State-of-the-Art Review", type="primary", use_container_width=True):
        if not api_key: st.sidebar.error("API Key missing.")
        else:
            with st.spinner("LLM is reading top papers..."):
                try:
                    mega_report = generate_global_report_with_llm(high_value_papers_for_report, search_query or "General Review", api_key, base_url, model_name)
                    st.session_state.mega_report = mega_report
                except Exception as e: st.sidebar.error(str(e))

if 'mega_report' in st.session_state:
    st.markdown("## 📊 AI Global Review Report")
    st.markdown(st.session_state.mega_report)

st.sidebar.markdown("---")
with st.sidebar.expander("🛠️ Debug: Unclassified Venues (Other)"):
    other_raw_venues = set()
    for p in all_papers_in_db:
        raw_v = p.get('venue', '')
        if raw_v and analyze_venue(raw_v)['n'] == 'Other':
            other_raw_venues.add(raw_v)
            
    if other_raw_venues:
        st.warning(f"Found {len(other_raw_venues)} unrecognized venue name formats:")
        st.write(list(other_raw_venues))
    else:
        st.success("All venues are perfectly classified!")

st.sidebar.markdown("---")
st.sidebar.header(f"🛒 Selected Papers ({len(selected_papers)})")

if st.sidebar.button("📄 Open Selected PDFs", type="secondary", use_container_width=True):
    success_count = 0
    for p in selected_papers:
        title = p.get('title')
        udata = get_user_data(title)
        update_user_data(title, "open_count", udata['open_count'] + 1)
        url = p.get('pdf_link') or (f"https://doi.org/{p['doi']}" if p.get('doi') else '')
        if url: webbrowser.open_new_tab(url); success_count += 1
    st.sidebar.info(f"Opened {success_count} tabs.")
    
if st.sidebar.button("📚 Export to NotebookLM", type="primary", use_container_width=True):
    export_content = f"# Papers Context for '{search_query or 'Filtered Subset'}'\n\n"
    for p in selected_papers:
        title = p.get('title', '')
        udata = get_user_data(title)
        export_content += f"## {title}\n- **Authors:** {p.get('first_author', '')} ... {p.get('last_author', '')}\n- **Venue & Year:** {p.get('venue', '')} ({p.get('year', '')})\n- **My Rating:** {udata['rating']}\n"
        if udata['comments']: export_content += f"- **My Comments:** {udata['comments']}\n"
        export_content += f"### Abstract\n{p.get('abstract', '')}\n\n---\n\n"
    with open("NotebookLM_Sources.md", "w", encoding="utf-8") as f: f.write(export_content)
    st.sidebar.success("🎉 Markdown Generated.")

if selected_papers:
    csv_data = [["Title", "Year", "Venue", "DOI", "Abstract"]]
    for p in selected_papers:
        csv_data.append([p.get('title', ''), p.get('year', ''), p.get('venue', ''), p.get('doi', ''), p.get('abstract', '')])
    import io
    def generate_csv_link(data):
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerows(data)
        b64 = base64.b64encode(output.getvalue().encode('utf-8-sig')).decode()
        return f'<a href="data:text/csv;base64,{b64}" download="ChipSeeker_Export.csv" style="display:block; text-align:center; padding:10px; background-color:#28a745; color:white; border-radius:4px; text-decoration:none; font-weight:bold;">📊 Download CSV Database</a>'
    st.sidebar.markdown(generate_csv_link(csv_data), unsafe_allow_html=True)
    st.sidebar.markdown("<br>", unsafe_allow_html=True)

    bib_content = ""
    for p in selected_papers:
        last_name = p.get('first_author', 'Anon').split()[-1].replace("-", "")
        year_str = str(extract_year(p.get('year', '202X')))
        title_words = re.sub(r'[^a-zA-Z0-9\s]', '', p.get('title', 'paper')).split()
        first_word = title_words[0].capitalize() if title_words else "Paper"
        bibkey = f"{last_name}{year_str}{first_word}"
        author_str = f"{p.get('first_author', 'Unknown')} and {p.get('last_author', 'Unknown')}"
        bib_content += f"@article{{{bibkey},\n  title={{{p.get('title', '')}}},\n  author={{{author_str}}},\n  journal={{{p.get('venue', '')}}},\n  year={{{p.get('year', '')}}},\n"
        if p.get('doi'): bib_content += f"  doi={{{p.get('doi')}}}\n"
        bib_content += f"}}\n\n"
        
    st.sidebar.download_button(label="📑 Export IEEE BibTeX", data=bib_content, file_name="references.bib", mime="text/plain", use_container_width=True)