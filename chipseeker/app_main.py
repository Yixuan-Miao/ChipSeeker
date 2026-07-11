import asyncio
import html as html_lib
import math
import os
import sys
import time
import webbrowser
from datetime import date, datetime, timezone

import streamlit as st

from chipseeker.config_store import UserDataStore, load_app_config
from chipseeker.cloud_access import build_cloud_token, cloud_access_configured
from chipseeker.content_pack import ContentPackInstallError, build_content_pack, build_content_update_pack, describe_content_update_status, detect_content_pack_status, install_bundled_demo_csv, install_content_pack, install_content_update_pack, refresh_content_pack_baseline
from chipseeker.content_release import ContentReleaseError, content_release_configured, load_content_release_config, publish_content_pack_to_release
from chipseeker.conflict_review import collect_source_records, detect_conflicts, dismiss_conflict, load_conflict_resolutions, restore_conflicts
from chipseeker.data_sync import (
    bibliographic_metadata_enrich_required,
    build_source_snapshot,
    build_source_state,
    enrich_bibliographic_metadata,
    library_sync_required,
    list_source_csv_files,
    scan_and_import_csvs,
)
from chipseeker.embedding_scope import available_years, build_scope_key, filter_papers_by_years, scope_label
from chipseeker.exports import build_annual_conference_report, build_bibtex, build_csv_rows, build_notebooklm_export, build_search_results_html, generate_csv_link, paper_authors_display, write_text_file
from chipseeker.llm_tools import analyze_with_llm, generate_global_report_with_llm, generate_search_keywords, get_batch_citations
from chipseeker.maintenance import generate_db_stats
from chipseeker.migrations import migrate_local_data
from chipseeker.paths import (
    ARXIV_UPDATE_DIR,
    CACHE_DIR,
    CONFIG_FILE,
    BUNDLED_DEMO_CSV,
    CONTENT_PACK_EXPORT_DIR,
    CONFLICT_RESOLUTIONS_FILE,
    DATA_DIR,
    DB_FILE,
    DOWNLOAD_DIR,
    EXAMPLE_CONFIG_FILE,
    EXPORT_DIR,
    IEEE_UPDATE_DIR,
    LEGACY_CONFIG_FILE,
    LOCAL_DATA_STATE_FILE,
    NATURE_UPDATE_DIR,
    NOTEBOOKLM_EXPORT_FILE,
    SOURCE_CSV_DIR,
    SOURCE_MANIFEST_FILE,
    SOURCE_REGISTRY_FILE,
    SCIENCE_UPDATE_DIR,
    USER_DATA_FILE,
)
from chipseeker.search_ui import collect_year_counts, filter_search_results, get_paper_id, highlight_text, required_words_from_query, result_bucket_counts, sort_results
from chipseeker.scoring import compute_paper_score
from chipseeker.task_queue import cancel_task, cleanup_task, get_task, submit_arxiv_incremental, submit_embedding_build, submit_llm_powered_search, submit_nature_incremental, submit_pdf_download, submit_science_incremental
from chipseeker.update_notices import load_update_notices
from chipseeker.update_manager import (
    advance_ieee_sources,
    build_ieee_search_url,
    clear_pending_ieee_batch,
    current_month_string,
    default_incremental_start_date,
    find_source,
    list_sources,
    load_source_registry,
    replace_source,
    save_ieee_uploaded_file,
    save_source_registry,
    source_target_window,
    start_ieee_batch,
)
from chipseeker.utils import extract_year, load_json, save_json, slugify_filename
from chipseeker.venue_data import DOMAIN_COLORS, TIER_COLORS, analyze_venue, get_venue_display_str
from chipseeker.version import APP_VERSION, GITHUB_REPO_URL
from search_runtime import PaperSearcher, describe_cache_status, get_cache_paths


CURRENT_YEAR = datetime.now().year
SEMANTIC_PREFILTER_MULTIPLIER = 20
SEMANTIC_PREFILTER_MIN = 1000
SEMANTIC_PREFILTER_MAX = 5000
PUBLIC_CLOUD_ACCESS_UI_ENABLED = False
LLM_SEARCH_UI_TIMEOUT_SECONDS = 240
LANGUAGE_OPTIONS = ["English", "简体中文"]
NATURE_JOURNAL_OPTIONS = [
    ("", "All Nature journals"),
    ("nature", "Nature"),
    ("natelectron", "Nature Electronics"),
    ("ncomms", "Nature Communications"),
    ("nature-machine-intelligence", "Nature Machine Intelligence"),
    ("nature-nanotechnology", "Nature Nanotechnology"),
    ("nature-photonics", "Nature Photonics"),
    ("communications-engineering", "Communications Engineering"),
    ("npj-quantum-information", "npj Quantum Information"),
]
RATING_OPTIONS = ["Unrated", "Masterpiece", "Solid", "Average", "Marginal", "Poor"]
RATING_LABELS = {
    "Unrated": "☆ Unrated",
    "Masterpiece": "★★★★★ Masterpiece",
    "Solid": "★★★★ Solid",
    "Average": "★★★ Average",
    "Marginal": "★★ Marginal",
    "Poor": "★ Poor",
}
DEEPSEEK_MODEL_OPTIONS = {
    "DeepSeek Pro (deepseek-v4-pro)": "deepseek-v4-pro",
    "DeepSeek Lite/Fast (deepseek-v4-flash)": "deepseek-v4-flash",
}


def _vx_auth():
    # Placeholder license check — reserved for future activation.
    # If a real license check is needed, validate against a signed token here.
    pass


def tr(ui_language, english, chinese=None):
    if ui_language == "简体中文" and chinese:
        return chinese
    return english


def format_nature_journal(value):
    return dict(NATURE_JOURNAL_OPTIONS).get(value, value or "All Nature journals")


def render_help_panel(ui_language):
    steps = [
        (
            tr(ui_language, "Step 1", "第 1 步"),
            tr(
                ui_language,
                "Choose all-MiniLM-L6-v2 first if you want zero-config local search. Switch to voyage-4-large only after adding the embedding API key.",
                "如果你想先零配置体验，请先用 all-MiniLM-L6-v2。只有在填好 embedding API key 之后，再切到 voyage-4-large。",
            ),
        ),
        (
            tr(ui_language, "Step 2", "第 2 步"),
            tr(
                ui_language,
                "Use the build buttons in Search Mode to prepare the newest-year, newest-three-year, or full-library ChipSeeker Lite cache. Search will automatically use the largest ready cache.",
                "在 Search Mode 里用构建按钮准备“最新一年 / 最新三年 / 全库”的 ChipSeeker Lite 缓存。搜索会自动使用当前已就绪的最大缓存范围。",
            ),
        ),
        (
            tr(ui_language, "Step 3", "第 3 步"),
            tr(
                ui_language,
                "Use the ChipSeeker Lite query box for meaning-based retrieval, then optionally add Exact Match terms to hard-filter titles and abstracts.",
                "先用 ChipSeeker Lite query 做含义检索，再按需用 Exact Match 对标题和摘要做硬关键词过滤。",
            ),
        ),
        (
            tr(ui_language, "Step 4", "第 4 步"),
            tr(
                ui_language,
                "Use the checkboxes or the batch-selection controls to build your Selected Papers set.",
                "用复选框或批量选择控件整理出你的 Selected Papers 集合。",
            ),
        ),
        (
            tr(ui_language, "Step 5", "第 5 步"),
            tr(
                ui_language,
                "From Selected Papers, open PDFs, batch-download PDFs, export BibTeX, or export to NotebookLM. LLM review is optional and stays at the bottom.",
                "在 Selected Papers 里可以打开 PDF、批量下载 PDF、导出 BibTeX，或者导出到 NotebookLM。LLM 分析是可选项，放在最底部。",
            ),
        ),
    ]
    st.markdown(f"### {tr(ui_language, 'Quick Help', '快速帮助')}")
    for title, body in steps:
        st.markdown(
            f"""
<div style="border:1px solid #f3c2c2; background:#fff7f7; padding:14px 16px; border-radius:12px; margin-bottom:12px;">
  <div style="color:#c62828; font-weight:700; margin-bottom:8px;">➜ {title}</div>
  <div>{body}</div>
</div>
            """,
            unsafe_allow_html=True,
        )


def semantic_scope_presets(library_years):
    latest_years = [library_years[0]] if library_years else []
    latest_three_years = library_years[:3]
    return [
        {"id": "latest_year", "label": "Latest Year", "years": latest_years},
        {"id": "latest_three_years", "label": "Latest 3 Years", "years": latest_three_years},
        {"id": "full_library", "label": "Full Library", "years": []},
    ]


def semantic_scope_summary(ui_language, label, total_papers, cache_status):
    cached = cache_status.get("cached_papers", 0)
    total = total_papers
    ready = cache_status.get("up_to_date", False)
    return (
        f"**{tr(ui_language, label, {'Latest Year': '最新一年', 'Latest 3 Years': '最新三年', 'Full Library': '全库'}[label])}**  \n"
        f"{tr(ui_language, 'Detected', '检测到')} `{total}` | "
        f"{tr(ui_language, 'Cached', '已缓存')} `{cached}` | "
        f"{tr(ui_language, 'Status', '状态')} `{tr(ui_language, 'Ready', '已就绪') if ready else tr(ui_language, 'Needs Build', '需要构建')}`"
    )


def cached_embedding_models(cache_dir):
    if not os.path.isdir(cache_dir):
        return set()
    models = set()
    for file_name in os.listdir(cache_dir):
        if not file_name.endswith(".meta.json"):
            continue
        meta = load_json(os.path.join(cache_dir, file_name), {})
        model_name = str(meta.get("model_name", "")).strip() if isinstance(meta, dict) else ""
        if model_name:
            models.add(model_name)
    return models


def ready_cache_suggestions(db_file, cache_dir, model_names, selected_model, scope_presets, all_papers):
    installed_models = cached_embedding_models(cache_dir)
    if not installed_models:
        return []

    preset_by_id = {preset["id"]: preset for preset in scope_presets}
    scope_priority = ["full_library", "latest_three_years", "latest_year"]
    model_priority = {
        "voyage-4-large": 0,
        "voyage-4": 1,
        "voyage-4-lite": 2,
        "voyage-context-3": 3,
        "text-embedding-3-large": 4,
        "all-MiniLM-L6-v2": 5,
    }
    suggestions = []

    for model_name in model_names:
        if model_name == selected_model or model_name not in installed_models:
            continue
        for scope_id in scope_priority:
            preset = preset_by_id.get(scope_id)
            if not preset:
                continue
            preset_papers = filter_papers_by_years(all_papers, preset["years"]) if preset["years"] else list(all_papers)
            if not preset_papers:
                continue
            status = describe_cache_status(
                db_file,
                model_name,
                scope_key=build_scope_key(preset["years"]),
                papers_override=preset_papers,
            )
            if status.get("up_to_date"):
                suggestions.append(
                    {
                        "model": model_name,
                        "scope_id": scope_id,
                        "scope_label": preset["label"],
                        "scope_text": scope_label(preset["years"]),
                        "cached_papers": status.get("cached_papers", len(preset_papers)),
                        "needs_api": embedding_model_requires_api(model_name),
                    }
                )
                break

    suggestions.sort(key=lambda item: (model_priority.get(item["model"], 99), scope_priority.index(item["scope_id"])))
    return suggestions


@st.cache_resource(show_spinner=False)
def get_searcher_engine(db_file, model_name, api_key="", scope_key="all", scope_years=()):
    papers_override = None
    if scope_years:
        papers_override = filter_papers_by_years(load_json(db_file, []), scope_years)
    return PaperSearcher(db_file, model_name=model_name, api_key=api_key, papers_override=papers_override, scope_key=scope_key)


def render_taxonomy_matrix(total_papers, db_stats, active_years):
    with st.expander(f"Taxonomy & Library Matrix (Total Records: {total_papers})", expanded=True):
        notices = load_update_notices(limit=20)
        if notices:
            notice_rows = []
            history_rows = []
            for notice in notices[:2]:
                text = html_lib.escape(notice.get("title_zh") or notice.get("title") or "")
                date_text = html_lib.escape(notice.get("date") or "Update")
                notice_rows.append(
                    f"<div style='display:flex; gap:10px; align-items:flex-start; padding:6px 0; border-top:1px solid rgba(15,23,42,0.08);'>"
                    f"<span style='font-size:12px; font-weight:900; color:#2563eb; min-width:74px;'>{date_text}</span>"
                    f"<span style='font-size:13px; line-height:1.45; color:#334155; font-weight:700;'>{text}</span>"
                    f"</div>"
                )
            for notice in notices:
                text = html_lib.escape(notice.get("title_zh") or notice.get("title") or "")
                date_text = html_lib.escape(notice.get("date") or "Update")
                history_rows.append(
                    f"<div style='display:flex; gap:10px; align-items:flex-start; padding:7px 0; border-top:1px solid rgba(15,23,42,0.06);'>"
                    f"<span style='font-size:12px; font-weight:900; color:#64748b; min-width:74px;'>{date_text}</span>"
                    f"<span style='font-size:13px; line-height:1.45; color:#475569;'>{text}</span>"
                    f"</div>"
                )
            st.markdown(
                "<div style='margin:0 0 14px; padding:12px 14px; border:1px solid #dbeafe; border-radius:14px; "
                "background:linear-gradient(135deg,#eff6ff,#f8fafc); box-shadow:0 10px 24px rgba(37,99,235,0.08);'>"
                "<div style='font-size:12px; font-weight:950; color:#1d4ed8; letter-spacing:.08em; text-transform:uppercase;'>Library Updates</div>"
                + "".join(notice_rows)
                + "<details style='margin-top:8px;'>"
                + "<summary style='cursor:pointer; color:#1d4ed8; font-size:12px; font-weight:900;'>View all update history</summary>"
                + "<div style='margin-top:8px;'>"
                + "".join(history_rows)
                + "</div></details>"
                + "</div>",
                unsafe_allow_html=True,
            )
        if not active_years:
            st.info("No recognized venues found. Please import source CSV files.")
            return
        show_all = st.checkbox("Show all earlier years")
        display_years = active_years if show_all else [year for year in active_years if year >= 2019]
        older_years = [] if show_all else [year for year in active_years if year < 2019]
        has_older = len(older_years) > 0

        table_md = "| **Venue** | **Tier** | **Domain** | " + " | ".join(map(str, display_years))
        if has_older:
            table_md += " | **Earlier** |"
        table_md += "\n|---|---|---|" + "---|" * len(display_years)
        if has_older:
            table_md += "---|"
        table_md += "\n"

        sorted_venues = sorted(db_stats.items(), key=lambda item: item[1]["data"]["s"], reverse=True)
        for venue_name, content in sorted_venues:
            if sum(content["years"].values()) < 50:
                continue
            venue_data = content["data"]
            tier_color = TIER_COLORS.get(venue_data["t"], "#9E9E9E")
            venue_display = get_venue_display_str(venue_data)
            venue_styled = f"**[{venue_display}]({venue_data['u']})**"
            tier_styled = f"<span style='background-color:{tier_color}; color:white; padding:2px 6px; border-radius:4px; font-size:0.8em; font-weight:bold;'>{venue_data['t']}</span>"
            domains_html = " ".join([f"<span style='color:{DOMAIN_COLORS.get(domain, '#757575')}; border: 1px solid {DOMAIN_COLORS.get(domain, '#757575')}; padding: 1px 4px; border-radius: 4px; font-size: 0.75em;'>{domain}</span>" for domain in venue_data["d"]])
            row = f"| {venue_styled} | {tier_styled} | {domains_html} |"
            for year in display_years:
                count = content["years"].get(year, 0)
                row += f" {count if count > 0 else '-'} |"
            if has_older:
                older_count = sum(content["years"].get(year, 0) for year in older_years)
                row += f" {older_count if older_count > 0 else '-'} |"
            table_md += row + "\n"
        st.markdown(table_md, unsafe_allow_html=True)


def render_task_status(task_id, label, success_message=None, container=st, cleanup_on_complete=True, auto_refresh=False, show_history=False):
    if not task_id:
        return None
    task = get_task(task_id)
    if not task:
        return None

    status = task.get("status")
    message = task.get("message", "")
    progress = float(task.get("progress", 0.0))
    started_at = float(task.get("started_at") or task.get("created_at") or time.time())
    updated_at = float(task.get("updated_at") or started_at)
    elapsed = max(0.0, time.time() - started_at)
    updated_label = time.strftime("%H:%M:%S", time.localtime(updated_at))
    if status in {"queued", "running"}:
        container.info(f"{label}: {message or status} | elapsed {elapsed:.0f}s | last update {updated_label}")
        container.progress(progress if progress > 0 else 0.01)
        if show_history:
            container.code(format_task_history(task, limit=12), language="text")
        if auto_refresh:
            time.sleep(1.0)
            st.rerun()
    elif status == "completed":
        if success_message:
            container.success(success_message(task.get("result", {})))
        if show_history:
            container.code(format_task_history(task, limit=12), language="text")
        if cleanup_on_complete:
            cleanup_task(task_id)
            return None
    elif status == "failed":
        container.error(f"{label} failed: {task.get('error', 'unknown error')}")
        if show_history:
            container.code(format_task_history(task, limit=12), language="text")
    return task


def format_task_history(task, limit=30):
    history = task.get("history", [])[-limit:] if isinstance(task, dict) else []
    return "\n".join(f"[{entry.get('timestamp', '--:--:--')}] {entry.get('message', '')}" for entry in history)


def render_foreground_task_console(task_id, label, success_message=None):
    if not task_id:
        return None

    title_placeholder = st.empty()
    progress_placeholder = st.empty()
    status_placeholder = st.empty()
    history_placeholder = st.empty()
    detail_placeholder = st.empty()

    def draw(task):
        status = task.get("status")
        progress = float(task.get("progress", 0.0))
        message = task.get("message", "")
        result = task.get("result", {})
        title_placeholder.markdown(f"### Embedding Console\n{label}")
        if status in {"queued", "running"}:
            progress_placeholder.progress(progress if progress > 0 else 0.01)
            status_placeholder.info(message or status)
        elif status == "completed":
            progress_placeholder.progress(1.0)
            if success_message:
                status_placeholder.success(success_message(result))
            else:
                status_placeholder.success("Embedding build completed.")
        else:
            progress_placeholder.progress(progress if progress > 0 else 0.01)
            status_placeholder.error(task.get("error", "unknown error"))

        with detail_placeholder.container():
            detail_cols = st.columns(4)
            detail_cols[0].metric("Status", status.title())
            detail_cols[1].metric("Progress", f"{progress * 100:.1f}%")
            detail_cols[2].metric("Scope", result.get("scope_key", task.get("payload", {}).get("scope_key", "all")))
            detail_cols[3].metric("Papers", result.get("paper_count", task.get("payload", {}).get("paper_count", 0)))
        history_placeholder.code(format_task_history(task), language="text")

    task = get_task(task_id)
    if not task:
        status_placeholder.warning("Task record was not found.")
        return None

    loops = 0
    while task and task.get("status") in {"queued", "running"} and loops < 600:
        draw(task)
        time.sleep(1.0)
        task = get_task(task_id)
        loops += 1

    if task:
        draw(task)
    return task


def embedding_model_requires_api(model_name):
    return "voyage" in model_name or "text-embedding" in model_name


def resolve_provider_defaults(current_preset, app_config):
    if current_preset == "DeepSeek":
        configured_model = str(app_config.get("llm_model", "")).strip()
        model = configured_model if configured_model in DEEPSEEK_MODEL_OPTIONS.values() else "deepseek-v4-pro"
        return "https://api.deepseek.com", model
    if current_preset == "SiliconFlow":
        return "https://api.siliconflow.cn/v1", "Qwen/Qwen2.5-7B-Instruct"
    if current_preset == "Kimi":
        return "https://api.moonshot.cn/v1", "moonshot-v1-8k"
    return app_config.get("llm_base_url", ""), app_config.get("llm_model", "")


def render_llm_model_input(ui_language, current_preset, default_model, key):
    if current_preset != "DeepSeek":
        return st.text_input(tr(ui_language, "Model ID", "模型 ID"), value=default_model, key=key)
    labels = list(DEEPSEEK_MODEL_OPTIONS.keys())
    model_to_label = {model: label for label, model in DEEPSEEK_MODEL_OPTIONS.items()}
    current_label = model_to_label.get(default_model, labels[0])
    selected_label = st.selectbox(
        tr(ui_language, "DeepSeek Model", "DeepSeek 模型"),
        labels,
        index=labels.index(current_label),
        key=key,
        help=tr(
            ui_language,
            "Lite/Fast uses deepseek-v4-flash for speed. Pro uses deepseek-v4-pro for higher quality but slower responses.",
            "Lite/Fast 使用 deepseek-v4-flash，速度更快；Pro 使用 deepseek-v4-pro，质量更高但更慢。",
        ),
    )
    return DEEPSEEK_MODEL_OPTIONS[selected_label]


def cloud_access_ready(app_config):
    if not PUBLIC_CLOUD_ACCESS_UI_ENABLED:
        return False
    if not bool(app_config.get("cloud_access_enabled", False)):
        return False
    return cloud_access_configured(
        app_config.get("cloud_access_email", ""),
        app_config.get("cloud_access_code", ""),
    )


def cloud_access_token(app_config):
    return build_cloud_token(
        app_config.get("cloud_access_base_url", "https://chipseeker.online"),
        app_config.get("cloud_access_email", ""),
        app_config.get("cloud_access_code", ""),
    )


def runtime_embedding_key(app_config, direct_key):
    if str(direct_key or "").strip():
        return direct_key
    if cloud_access_ready(app_config):
        return cloud_access_token(app_config)
    return ""


def runtime_llm_key(app_config, direct_key):
    if str(direct_key or "").strip():
        return direct_key
    if cloud_access_ready(app_config):
        return cloud_access_token(app_config)
    return ""


def install_uploaded_content_pack(uploaded_pack):
    try:
        result = install_content_pack(uploaded_pack, DATA_DIR)
    except ContentPackInstallError as exc:
        st.error(str(exc))
        return
    st.cache_resource.clear()
    st.session_state["csv_state"] = ()
    st.success(f"Installed content pack into `{result['data_dir']}` with {result['copied_entries']} copied entries.")
    time.sleep(1.0)
    st.rerun()


def install_uploaded_update_pack(uploaded_pack):
    try:
        result = install_content_update_pack(uploaded_pack, DATA_DIR)
    except ContentPackInstallError as exc:
        st.error(str(exc))
        return
    st.cache_resource.clear()
    st.session_state["csv_state"] = ()
    st.success(
        "Installed update pack into "
        f"`{result['data_dir']}`. Papers added: {result.get('paper_added', 0)}, "
        f"updated: {result.get('paper_updated', 0)}, duplicate/skipped: {result.get('paper_skipped', 0)}, "
        f"cache rows appended: {result.get('cache_appended', 0)}, files merged: {result['copied_entries']}."
    )
    time.sleep(1.0)
    st.rerun()


def install_bundled_demo_library():
    target_path = install_bundled_demo_csv(BUNDLED_DEMO_CSV, SOURCE_CSV_DIR)
    st.cache_resource.clear()
    st.session_state["csv_state"] = ()
    st.success(f"Bundled demo CSV installed to `{target_path}`.")
    time.sleep(1.0)
    st.rerun()


def latest_content_update_pack(output_dir):
    if not os.path.isdir(output_dir):
        return ""
    candidates = [
        os.path.join(output_dir, name)
        for name in os.listdir(output_dir)
        if name.lower().startswith("chipseeker_contentupdate_") and name.lower().endswith(".zip")
    ]
    if not candidates:
        return ""
    return max(candidates, key=lambda path: os.path.getmtime(path))


def format_content_pack_time(value):
    value = str(value or "").strip()
    if not value:
        return "N/A"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%Y-%m-%d %H:%M")
    except Exception:
        return value


def render_content_pack_sidebar(content_status, ui_language):
    with st.sidebar.expander(tr(ui_language, "Content Pack", "内容包"), expanded=False):
        status_text = "Ready" if content_status["pack_ready"] else "Not installed"
        st.caption(
            f"Status: {status_text} | Papers: {content_status['paper_count']} | "
            f"Sources: {content_status['source_count']} | Cache files: {content_status['cache_count']}"
        )
        update_status = describe_content_update_status(DATA_DIR, DB_FILE)
        if update_status["baseline_ready"]:
            baseline_kind = str(update_status.get("baseline_kind") or "baseline").title()
            st.caption(
                f"Last {baseline_kind}: {format_content_pack_time(update_status['baseline_created_at_utc'])} | "
                f"Baseline papers: {update_status['baseline_paper_count']} | "
                f"Current: {update_status['current_paper_count']} | "
                f"Incremental papers: {update_status['paper_delta_count']}"
            )
        else:
            st.caption(
                "No local baseline yet. Build one local full pack once; later update ZIPs only include incremental papers."
            )
        if st.button(tr(ui_language, "Open Quick Start", "打开快速开始"), use_container_width=True):
            st.session_state["show_quick_start"] = True
            st.rerun()
        if st.button(tr(ui_language, "Build Content Pack ZIP", "生成内容包 ZIP"), use_container_width=True):
            build_result = build_content_pack(
                DATA_DIR,
                DB_FILE,
                CACHE_DIR,
                SOURCE_MANIFEST_FILE,
                schema_state=load_json(LOCAL_DATA_STATE_FILE, {}),
                output_dir=CONTENT_PACK_EXPORT_DIR,
            )
            st.success(f"Created: {build_result['zip_path']}")
        if st.button(tr(ui_language, "Build Incremental Update ZIP", "生成增量更新 ZIP"), use_container_width=True):
            try:
                update_result = build_content_update_pack(
                    DATA_DIR,
                    DB_FILE,
                    CACHE_DIR,
                    SOURCE_MANIFEST_FILE,
                    schema_state=load_json(LOCAL_DATA_STATE_FILE, {}),
                    output_dir=CONTENT_PACK_EXPORT_DIR,
                    save_state=False,
                )
                st.success(
                    f"Created: {update_result['zip_path']} | "
                    f"papers: {update_result['paper_delta_count']} | "
                    f"sources: {update_result['source_delta_count']} | "
                    f"cache rows: {update_result['cache_delta_count']} | "
                    f"full caches: {update_result.get('cache_full_count', 0)} | "
                    "Baseline not advanced until upload succeeds."
                )
            except ContentPackInstallError as exc:
                st.error(str(exc))
        app_config = load_app_config([CONFIG_FILE, LEGACY_CONFIG_FILE])
        release_config = load_content_release_config(app_config)
        if content_release_configured(release_config):
            st.markdown("---")
            st.caption("Internal private publisher is enabled on this machine.")
            st.caption(
                f"Target: `{release_config.repo}` / `{release_config.tag}` / "
                f"`{release_config.update_asset_name}`"
            )
            if st.button("Build & Upload Private Update Pack", use_container_width=True):
                try:
                    update_result = build_content_update_pack(
                        DATA_DIR,
                        DB_FILE,
                        CACHE_DIR,
                        SOURCE_MANIFEST_FILE,
                        schema_state=load_json(LOCAL_DATA_STATE_FILE, {}),
                        output_dir=CONTENT_PACK_EXPORT_DIR,
                        pack_name=release_config.update_asset_name,
                        save_state=False,
                    )
                    publish_result = publish_content_pack_to_release(
                        update_result["zip_path"],
                        release_config,
                        asset_name=release_config.update_asset_name,
                    )
                    refresh_content_pack_baseline(DATA_DIR, DB_FILE, CACHE_DIR, baseline_kind="update")
                    st.success(
                        "Uploaded private update pack: "
                        f"{publish_result['asset_name']} ({publish_result['size_bytes'] / 1024 / 1024:.1f} MB)"
                    )
                except (ContentPackInstallError, ContentReleaseError) as exc:
                    st.error(str(exc))
            latest_update_pack = latest_content_update_pack(CONTENT_PACK_EXPORT_DIR)
            if latest_update_pack:
                st.caption(f"Latest local update ZIP: `{os.path.basename(latest_update_pack)}`")
                if st.button("Upload Latest Existing Update Pack", use_container_width=True):
                    try:
                        publish_result = publish_content_pack_to_release(
                            latest_update_pack,
                            release_config,
                            asset_name=release_config.update_asset_name,
                        )
                        refresh_content_pack_baseline(DATA_DIR, DB_FILE, CACHE_DIR, baseline_kind="update")
                        st.success(
                            "Uploaded existing private update pack: "
                            f"{publish_result['asset_name']} ({publish_result['size_bytes'] / 1024 / 1024:.1f} MB)"
                        )
                    except ContentReleaseError as exc:
                        st.error(str(exc))
        st.caption(tr(ui_language, "Large ZIP files are supported locally.", "本地支持较大的 ZIP 内容包。"))
        uploaded_pack = st.file_uploader(tr(ui_language, "Install Content Pack ZIP", "安装内容包 ZIP"), type=["zip"], key="sidebar_content_pack_upload")
        if uploaded_pack is not None and st.button(tr(ui_language, "Install Uploaded Pack", "安装上传内容包"), use_container_width=True):
            install_uploaded_content_pack(uploaded_pack)
        uploaded_update_pack = st.file_uploader(tr(ui_language, "Install Incremental Update ZIP", "安装增量更新 ZIP"), type=["zip"], key="sidebar_update_pack_upload")
        if uploaded_update_pack is not None and st.button(tr(ui_language, "Install Update Pack", "安装增量更新包"), use_container_width=True):
            install_uploaded_update_pack(uploaded_update_pack)
        st.caption(tr(ui_language, "Update ZIPs merge new sources/cache files into the existing library instead of replacing the full 30k+ database.", "增量更新 ZIP 会合并新的 sources/cache 文件，不会替换已有 3 万+ 全库。"))
        if os.path.exists(BUNDLED_DEMO_CSV) and st.button(tr(ui_language, "Install Bundled TMTT 2026 Demo", "安装内置 TMTT 2026 演示库"), use_container_width=True):
            install_bundled_demo_library()


def render_quick_start(app_config, content_status, ui_language):
    st.header(tr(ui_language, "Quick Start", "快速开始"))
    st.caption(tr(ui_language, "Default mode is bundled local search. Direct API keys are optional upgrades, not setup blockers.", "默认模式是本地搜索。直接 API key 是可选增强，不是使用门槛。"))

    info_col1, info_col2, info_col3 = st.columns(3)
    info_col1.metric("Bundled Papers", content_status["paper_count"])
    info_col2.metric("Source CSVs", content_status["source_count"])
    info_col3.metric("Cache Files", content_status["cache_count"])

    if content_status["pack_ready"]:
        st.success(tr(ui_language, "Bundled library detected. You can start searching immediately after this one-time setup.", "检测到内容库。完成这一步后可以直接开始搜索。"))
    else:
        st.warning(tr(ui_language, "No bundled content pack detected yet. Import one now, or continue with an empty library.", "还没有检测到内容包。你可以现在导入，或者先用空库继续。"))

    uploaded_pack = st.file_uploader(tr(ui_language, "Import Content Pack ZIP", "导入内容包 ZIP"), type=["zip"], key="quickstart_content_pack_upload")
    if uploaded_pack is not None and st.button(tr(ui_language, "Install Content Pack", "安装内容包"), type="primary", use_container_width=True):
        install_uploaded_content_pack(uploaded_pack)
    if os.path.exists(BUNDLED_DEMO_CSV):
        st.info(tr(ui_language, "Repo bundle includes `export2026.03.04-08.56.26.csv`, a 2026 TMTT demo CSV for quick validation.", "仓库内置 `export2026.03.04-08.56.26.csv`，可快速体验 2026 TMTT 演示库。"))
        if st.button(tr(ui_language, "Load Bundled TMTT 2026 Demo CSV", "加载内置 TMTT 2026 演示 CSV"), use_container_width=True):
            install_bundled_demo_library()

    with st.form("quick_start_form"):
        search_mode = st.radio(
            tr(ui_language, "Search Mode", "搜索模式"),
            [
                tr(ui_language, "Bundled MiniLM (No API Required)", "内置 MiniLM（不需要 API）"),
                tr(ui_language, "Voyage 4 Large (Requires API Key)", "Voyage 4 Large（需要 API Key）"),
            ],
            index=0 if content_status["has_minilm_cache"] or app_config.get("embedding_model", "all-MiniLM-L6-v2") == "all-MiniLM-L6-v2" else 1,
        )
        st.caption(tr(ui_language, "MiniLM may download model weights once on the first machine that uses it, unless you bundle them separately.", "MiniLM 在新机器首次使用时可能会下载一次模型权重，除非你把本地模型也一起打包。"))
        with st.expander(tr(ui_language, "Optional API Keys", "可选 API Key"), expanded=False):
            emb_api_key = st.text_input("Voyage / OpenAI Embedding API Key", value=app_config.get("emb_api_key", ""), type="password")
            preset_options = ["DeepSeek", "SiliconFlow", "Kimi", "Custom OpenAI"]
            current_preset = st.selectbox(
                tr(ui_language, "LLM Provider Preset", "LLM 服务商预设"),
                preset_options,
                index=preset_options.index(app_config.get("provider_preset", "DeepSeek")) if app_config.get("provider_preset") in preset_options else 0,
            )
            default_base, default_model = resolve_provider_defaults(current_preset, app_config)
            llm_api_key = st.text_input("LLM API Key", value=app_config.get("llm_api_key", ""), type="password")
            llm_base_url = st.text_input("LLM Base URL", value=default_base)
            llm_model = render_llm_model_input(ui_language, current_preset, default_model, "quick_start_llm_model")
        start_now = st.form_submit_button(tr(ui_language, "Save and Start Exploring", "保存并开始使用"), type="primary", use_container_width=True)

    if start_now:
        app_config.update(
            {
                "embedding_model": "all-MiniLM-L6-v2" if "MiniLM" in search_mode else "voyage-4-large",
                "emb_api_key": emb_api_key,
                "provider_preset": current_preset,
                "llm_api_key": llm_api_key,
                "llm_base_url": llm_base_url,
                "llm_model": llm_model,
                "cloud_access_enabled": False,
                "onboarding_completed": True,
            }
        )
        save_json(CONFIG_FILE, app_config)
        st.session_state.pop("show_quick_start", None)
        st.cache_resource.clear()
        st.rerun()

    if st.button(tr(ui_language, "Continue Without Bundled Content", "不导入内容包继续"), use_container_width=True):
        app_config.update({"embedding_model": "all-MiniLM-L6-v2", "onboarding_completed": True})
        save_json(CONFIG_FILE, app_config)
        st.session_state.pop("show_quick_start", None)
        st.cache_resource.clear()
        st.rerun()

    st.stop()


def render_conflict_review(source_csv_files):
    st.header("Dedup Conflict Review")
    st.caption("Review edge cases before they silently collapse under the dedupe key.")

    resolution_payload = load_conflict_resolutions(CONFLICT_RESOLUTIONS_FILE)
    dismissed_ids = set(resolution_payload.get("dismissed", []))
    source_records = collect_source_records(source_csv_files)
    conflicts = detect_conflicts(source_records)
    visible_conflicts = [item for item in conflicts if item["id"] not in dismissed_ids]

    metric_col1, metric_col2, metric_col3 = st.columns(3)
    metric_col1.metric("Active Conflicts", len(visible_conflicts))
    metric_col2.metric("Dismissed", len(dismissed_ids))
    metric_col3.metric("Source Records Scanned", len(source_records))

    action_col1, action_col2 = st.columns(2)
    with action_col1:
        if st.button("Refresh Conflict Scan", use_container_width=True):
            st.rerun()
    with action_col2:
        if st.button("Restore Dismissed Conflicts", use_container_width=True):
            restore_conflicts(CONFLICT_RESOLUTIONS_FILE)
            st.rerun()

    if not conflicts:
        st.success("No dedupe conflicts detected in the current source CSV files.")
        return

    if not visible_conflicts:
        st.info("All detected conflicts are currently dismissed.")
        return

    for conflict in visible_conflicts:
        with st.expander(f"{conflict['kind']}: {conflict['headline']}", expanded=False):
            st.markdown(conflict["summary"])
            if conflict.get("signals"):
                st.json(conflict["signals"], expanded=False)
            for source in conflict["sources"]:
                st.markdown(
                    f"- `{os.path.relpath(source['source_file'], SOURCE_CSV_DIR)}` line {source['row_number']} | "
                    f"Year: `{source['year'] or 'N/A'}` | DOI: `{source['doi'] or 'N/A'}` | Venue: `{source['venue'] or 'N/A'}`"
                )
                if source["abstract_preview"]:
                    st.caption(source["abstract_preview"])
            if st.button("Dismiss This Conflict", key=f"dismiss_{conflict['id']}", use_container_width=True):
                dismiss_conflict(CONFLICT_RESOLUTIONS_FILE, conflict["id"])
                st.rerun()


def render_annual_conference_report_export(all_papers):
    with st.expander("Annual Conference Report Export", expanded=False):
        st.caption(
            "Generate a clean Markdown/TXT source pack from the deduplicated database. "
            "Use it after importing a full-year conference CSV, then paste the file into an AI tool for an annual report."
        )
        conference_papers = []
        for paper in all_papers:
            venue_info = analyze_venue(paper.get("venue", ""))
            if venue_info.get("ty") == "Conference":
                conference_papers.append((paper, venue_info))

        if not conference_papers:
            st.info("No conference papers found in the current database.")
            return

        venue_options = sorted({venue_info["n"] for _, venue_info in conference_papers})
        years = sorted(
            {extract_year(paper.get("year", "")) for paper, _ in conference_papers if extract_year(paper.get("year", ""))},
            reverse=True,
        )
        default_year = years[0] if years else CURRENT_YEAR
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            selected_venues = st.multiselect(
                "Conference venue(s)",
                options=venue_options,
                default=venue_options[:1],
                help="Select one or more conferences, e.g. ISSCC + CICC for a yearly AI report.",
            )
        with col2:
            selected_year = st.selectbox("Year", options=years or [CURRENT_YEAR], index=(years.index(default_year) if default_year in years else 0))
        with col3:
            output_format = st.radio("Format", ["md", "txt"], horizontal=True)

        selected_set = set(selected_venues)
        selected_papers = [
            paper
            for paper, venue_info in conference_papers
            if venue_info["n"] in selected_set and extract_year(paper.get("year", "")) == int(selected_year)
        ]
        st.caption(f"Matched `{len(selected_papers)}` cleaned records from the current JSON database.")

        if st.button("Generate Annual Conference Report Source Pack", use_container_width=True, disabled=not selected_papers):
            venue_label = "+".join(selected_venues) if selected_venues else "Conference"
            content = build_annual_conference_report(selected_papers, venue_label, str(selected_year), output_format=output_format)
            filename = f"ChipSeeker_{slugify_filename(venue_label)}_{selected_year}_annual_report_source.{output_format}"
            output_path = os.path.join(EXPORT_DIR, "conference_reports", filename)
            write_text_file(output_path, content)
            st.session_state["annual_conference_report"] = {
                "content": content,
                "filename": filename,
                "path": output_path,
                "count": len(selected_papers),
            }

        report = st.session_state.get("annual_conference_report", {})
        if report:
            st.success(f"Created `{report['filename']}` with {report['count']} paper records.")
            st.caption(f"Saved locally: `{report['path']}`")
            st.download_button(
                "Download Report Source Pack",
                data=report["content"],
                file_name=report["filename"],
                mime="text/markdown" if report["filename"].endswith(".md") else "text/plain",
                use_container_width=True,
            )


def render_one_click_literature_update(nature_sources, science_sources):
    today_iso = date.today().isoformat()
    enabled_sources = [source for source in (nature_sources + science_sources) if source.get("enabled") and source.get("query")]
    enabled_nature_sources = [source for source in nature_sources if source.get("enabled") and source.get("query")]
    enabled_science_sources = [source for source in science_sources if source.get("enabled") and source.get("query")]
    due_sources = [source for source in enabled_sources if default_incremental_start_date(source) <= today_iso]
    due_nature_sources = [source for source in enabled_nature_sources if default_incremental_start_date(source) <= today_iso]
    due_science_sources = [source for source in enabled_science_sources if default_incremental_start_date(source) <= today_iso]
    earliest_due = min((default_incremental_start_date(source) for source in due_sources), default="Up to date")
    checked_dates = [source.get("last_checked_date") for source in enabled_sources if source.get("last_checked_date")]
    last_checked = max(checked_dates, default="Never")

    st.markdown("### One-Click Literature Update")
    st.caption("Fetch every enabled Nature/NE/NC/Science source from its last successful update date to today, then import the new CSVs automatically.")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Enabled Sources", len(enabled_sources))
    col2.metric("Need Update", len(due_sources))
    col3.metric("From", earliest_due)
    col4.metric("To", today_iso)
    st.caption(f"Latest saved checkpoint: `{last_checked}`. Each source keeps its own checkpoint, so repeated full-year downloads will not duplicate the JSON library.")

    nature_task_key = "one_click_nature_update_task"
    science_task_key = "one_click_science_update_task"
    nature_task_id = st.session_state.get(nature_task_key)
    science_task_id = st.session_state.get(science_task_key)

    def success_message(result):
        imported = result.get("import_result") or {}
        failed = [item for item in result.get("written_files", []) if item.get("error")]
        failed_names = ", ".join(item.get("source_id", "") for item in failed[:5] if item.get("source_id"))
        failed_hint = f" Failed sources still need update: {failed_names}." if failed_names else ""
        return (
            "One-click literature update completed. "
            f"Sources: {len(result.get('source_ids', []))}; "
            f"added {imported.get('added', 0)}, updated {imported.get('updated', 0)}, removed {imported.get('removed', 0)}; "
            f"failed {len(failed)}."
            f"{failed_hint}"
        )

    nature_task = render_task_status(
        nature_task_id,
        "One-click Nature/NE/NC update",
        success_message=success_message,
        cleanup_on_complete=False,
        auto_refresh=True,
        show_history=True,
    )
    science_task = render_task_status(
        science_task_id,
        "One-click Science update",
        success_message=success_message,
        cleanup_on_complete=False,
        auto_refresh=True,
        show_history=True,
    )
    if nature_task is None and nature_task_id:
        st.session_state.pop(nature_task_key, None)
        st.session_state["csv_state"] = ()
        st.rerun()
    if science_task is None and science_task_id:
        st.session_state.pop(science_task_key, None)
        st.session_state["csv_state"] = ()
        st.rerun()

    running = any(
        bool(task and task.get("status") in {"queued", "running"})
        for task in (nature_task, science_task)
    )
    button_label = "Update Nature/NE/Science Now"
    if not due_sources:
        button_label = "Literature Sources Already Up To Date"
    if st.button(button_label, type="primary", use_container_width=True, disabled=running or not due_sources):
        if due_nature_sources:
            st.session_state[nature_task_key] = submit_nature_incremental(
                SOURCE_REGISTRY_FILE,
                [source["id"] for source in due_nature_sources],
                NATURE_UPDATE_DIR,
                import_after=True,
                db_file=DB_FILE,
                cache_dir=CACHE_DIR,
                source_root=SOURCE_CSV_DIR,
                manifest_path=SOURCE_MANIFEST_FILE,
            )
        if due_science_sources:
            st.session_state[science_task_key] = submit_science_incremental(
                SOURCE_REGISTRY_FILE,
                [source["id"] for source in due_science_sources],
                SCIENCE_UPDATE_DIR,
                import_after=True,
                db_file=DB_FILE,
                cache_dir=CACHE_DIR,
                source_root=SOURCE_CSV_DIR,
                manifest_path=SOURCE_MANIFEST_FILE,
            )
        st.rerun()


def render_update_manager(source_csv_files, all_papers):
    st.header("Update Manager")
    st.caption("Default path: one click updates Nature/NE from the last checkpoint to today and imports the new papers automatically.")

    registry = load_source_registry(SOURCE_REGISTRY_FILE)
    ieee_sources = list_sources(registry, "ieee")
    nature_sources = list_sources(registry, "nature")
    arxiv_sources = list_sources(registry, "arxiv")
    science_sources = list_sources(registry, "science")

    metric_col1, metric_col2, metric_col3 = st.columns(3)
    metric_col1.metric("IEEE Sources", sum(1 for source in ieee_sources if source.get("enabled")))
    metric_col2.metric("Auto Sources", sum(1 for source in (nature_sources + arxiv_sources + science_sources) if source.get("enabled")))
    metric_col3.metric("Pending IEEE Batch", 1 if registry.get("pending_ieee_batch") else 0)

    render_one_click_literature_update(nature_sources, science_sources)

    render_annual_conference_report_export(all_papers)

    st.markdown("---")
    show_advanced_updates = st.toggle(
        "Show advanced update tools",
        value=False,
        help="Open this only when you need to edit source templates, run manual IEEE batches, or debug Nature/arXiv fetches.",
    )
    if not show_advanced_updates:
        return

    tab_ieee, tab_nature, tab_arxiv = st.tabs(["IEEE Incremental", "Nature Incremental", "arXiv Incremental"])

    with tab_ieee:
        st.markdown("### IEEE Source Registry")
        st.caption("ChipSeeker opens venue-specific IEEE Xplore pages and shows the exact target date window. Xplore date facets are not stable enough to encode as a durable URL.")

        with st.form("ieee_registry_form"):
            for source in ieee_sources:
                with st.expander(source.get("name", source["id"]), expanded=False):
                    st.checkbox("Enabled", value=source.get("enabled", True), key=f"ieee_enabled_{source['id']}")
                    st.text_input("Search Query", value=source.get("search_query", ""), key=f"ieee_query_{source['id']}")
                    st.text_input("Open URL", value=source.get("open_url", ""), key=f"ieee_url_{source['id']}")
                    st.text_input("Last Completed Month (YYYY-MM)", value=source.get("last_completed_month", ""), key=f"ieee_last_month_{source['id']}")
                    st.caption(source.get("notes", ""))
            if st.form_submit_button("Save IEEE Source Settings", use_container_width=True):
                for source in ieee_sources:
                    replace_source(
                        registry,
                        source["id"],
                        {
                            "enabled": st.session_state[f"ieee_enabled_{source['id']}"],
                            "search_query": st.session_state[f"ieee_query_{source['id']}"],
                            "open_url": st.session_state[f"ieee_url_{source['id']}"],
                            "last_completed_month": st.session_state[f"ieee_last_month_{source['id']}"],
                        },
                    )
                save_source_registry(registry, SOURCE_REGISTRY_FILE)
                st.success("IEEE source settings saved.")

        enabled_ieee_sources = [source for source in list_sources(load_source_registry(SOURCE_REGISTRY_FILE), "ieee") if source.get("enabled")]
        default_ieee_selection = [source["id"] for source in enabled_ieee_sources]
        target_month = st.text_input("Target Update Month (YYYY-MM)", value=current_month_string(), key="ieee_target_month")
        selected_ieee_ids = st.multiselect(
            "Sources to update",
            options=[source["id"] for source in enabled_ieee_sources],
            default=default_ieee_selection,
            format_func=lambda source_id: find_source(load_source_registry(SOURCE_REGISTRY_FILE), source_id).get("name", source_id),
            key="ieee_selected_sources",
        )

        for source_id in selected_ieee_ids:
            source = find_source(load_source_registry(SOURCE_REGISTRY_FILE), source_id)
            start_date, end_date = source_target_window(source, target_month)
            open_url = build_ieee_search_url(source, start_date, end_date)
            st.markdown(
                f"- **{source['name']}**: export papers for `{start_date}` to `{end_date}`. "
                f"[Open IEEE Xplore]({open_url})"
            )

        action_col1, action_col2 = st.columns(2)
        with action_col1:
            if st.button("Open Selected IEEE Pages", use_container_width=True):
                if not selected_ieee_ids:
                    st.warning("Select at least one IEEE source.")
                else:
                    registry = load_source_registry(SOURCE_REGISTRY_FILE)
                    batch = start_ieee_batch(registry, selected_ieee_ids, target_month)
                    save_source_registry(registry, SOURCE_REGISTRY_FILE)
                    for window in batch["windows"]:
                        webbrowser.open_new_tab(window["open_url"])
                    st.success("IEEE source pages opened. Download CSVs, then upload them below to finalize the batch.")

        pending_batch = load_source_registry(SOURCE_REGISTRY_FILE).get("pending_ieee_batch")
        with action_col2:
            if pending_batch and st.button("Cancel Pending IEEE Batch", use_container_width=True):
                registry = load_source_registry(SOURCE_REGISTRY_FILE)
                clear_pending_ieee_batch(registry)
                save_source_registry(registry, SOURCE_REGISTRY_FILE)
                st.rerun()

        if pending_batch:
            st.markdown("### Finalize IEEE Batch")
            st.info(
                f"Pending batch `{pending_batch['id']}` targeting `{pending_batch['target_month']}` "
                f"for {len(pending_batch['source_ids'])} source(s)."
            )
            uploaded_ieee_files = st.file_uploader(
                "Upload the IEEE CSV exports for this batch",
                type=["csv"],
                accept_multiple_files=True,
                key="ieee_batch_uploads",
            )
            if uploaded_ieee_files:
                with st.form("ieee_import_form"):
                    file_mappings = {}
                    for index, uploaded_file in enumerate(uploaded_ieee_files):
                        mapped_source_id = st.selectbox(
                            f"Map `{uploaded_file.name}` to source",
                            options=pending_batch["source_ids"],
                            format_func=lambda source_id: find_source(load_source_registry(SOURCE_REGISTRY_FILE), source_id).get("name", source_id),
                            key=f"ieee_map_{index}_{uploaded_file.name}",
                        )
                        file_mappings[uploaded_file.name] = mapped_source_id
                    if st.form_submit_button("Import IEEE Batch and Advance Watermarks", use_container_width=True):
                        registry = load_source_registry(SOURCE_REGISTRY_FILE)
                        touched_source_ids = []
                        saved_paths = []
                        for uploaded_file in uploaded_ieee_files:
                            source_id = file_mappings[uploaded_file.name]
                            source = find_source(registry, source_id)
                            if not source:
                                continue
                            saved_paths.append(save_ieee_uploaded_file(uploaded_file, source, pending_batch["target_month"], IEEE_UPDATE_DIR))
                            touched_source_ids.append(source_id)
                        scan_and_import_csvs(
                            DB_FILE,
                            CACHE_DIR,
                            source_root=SOURCE_CSV_DIR,
                            manifest_path=SOURCE_MANIFEST_FILE,
                        )
                        advance_ieee_sources(registry, sorted(set(touched_source_ids)), pending_batch["target_month"])
                        clear_pending_ieee_batch(registry)
                        save_source_registry(registry, SOURCE_REGISTRY_FILE)
                        st.session_state["csv_state"] = ()
                        st.success(f"Imported {len(saved_paths)} IEEE CSV file(s) and advanced {len(set(touched_source_ids))} source watermark(s).")
                        st.rerun()

    with tab_nature:
        st.markdown("### Nature Source Registry")
        with st.form("nature_registry_form"):
            for source in nature_sources:
                with st.expander(source.get("name", source["id"]), expanded=False):
                    st.checkbox("Enabled", value=source.get("enabled", True), key=f"nature_enabled_{source['id']}")
                    st.text_input("Display Name", value=source.get("name", ""), key=f"nature_name_{source['id']}")
                    st.text_input("Query", value=source.get("query", ""), key=f"nature_query_{source['id']}")
                    st.selectbox(
                        "Journal Filter",
                        options=[value for value, _ in NATURE_JOURNAL_OPTIONS],
                        index=[value for value, _ in NATURE_JOURNAL_OPTIONS].index(source.get("journal", "")) if source.get("journal", "") in {value for value, _ in NATURE_JOURNAL_OPTIONS} else 0,
                        format_func=format_nature_journal,
                        key=f"nature_journal_{source['id']}",
                    )
                    st.number_input("Max Pages", min_value=1, max_value=50, value=int(source.get("max_pages", 5)), step=1, key=f"nature_pages_{source['id']}")
                    st.number_input("Request Delay (s)", min_value=0.0, max_value=10.0, value=float(source.get("sleep_seconds", 1.0)), step=0.5, key=f"nature_sleep_{source['id']}")
                    last_checked = source.get("last_checked_date", "") or "2015-01-01"
                    st.date_input("Last Checked Date", value=date.fromisoformat(last_checked), key=f"nature_last_checked_{source['id']}")
                    st.caption(f"Next incremental start date: `{default_incremental_start_date(source)}`")
                    st.caption(source.get("notes", ""))
            if st.form_submit_button("Save Nature Source Settings", use_container_width=True):
                for source in nature_sources:
                    replace_source(
                        registry,
                        source["id"],
                        {
                            "enabled": st.session_state[f"nature_enabled_{source['id']}"],
                            "name": st.session_state[f"nature_name_{source['id']}"],
                            "query": st.session_state[f"nature_query_{source['id']}"],
                            "journal": st.session_state[f"nature_journal_{source['id']}"],
                            "max_pages": int(st.session_state[f"nature_pages_{source['id']}"]),
                            "sleep_seconds": float(st.session_state[f"nature_sleep_{source['id']}"]),
                            "last_checked_date": st.session_state[f"nature_last_checked_{source['id']}"].isoformat(),
                        },
                    )
                save_source_registry(registry, SOURCE_REGISTRY_FILE)
                st.success("Nature source settings saved.")

        with st.expander("Add Nature Source", expanded=False):
            with st.form("nature_add_form"):
                new_id = st.text_input("New Source ID", value="nature_new_source")
                new_name = st.text_input("New Source Name", value="New Nature Source")
                new_query = st.text_input("Nature Query", value="")
                new_journal = st.selectbox("Journal", options=[value for value, _ in NATURE_JOURNAL_OPTIONS], format_func=format_nature_journal)
                if st.form_submit_button("Add Nature Source", use_container_width=True):
                    registry = load_source_registry(SOURCE_REGISTRY_FILE)
                    if find_source(registry, new_id):
                        st.error("Source ID already exists.")
                    else:
                        registry["sources"].append(
                            {
                                "id": new_id,
                                "provider": "nature",
                                "mode": "auto_incremental",
                                "enabled": True,
                                "name": new_name,
                                "query": new_query,
                                "journal": new_journal,
                                "max_pages": 5,
                                "sleep_seconds": 1.0,
                                "last_checked_date": "",
                                "export_prefix": new_id,
                                "notes": "",
                            }
                        )
                        save_source_registry(registry, SOURCE_REGISTRY_FILE)
                        st.rerun()

        registry = load_source_registry(SOURCE_REGISTRY_FILE)
        runnable_nature_sources = [source for source in list_sources(registry, "nature") if source.get("enabled") and source.get("query")]
        selected_nature_ids = st.multiselect(
            "Nature sources to run",
            options=[source["id"] for source in runnable_nature_sources],
            default=[source["id"] for source in runnable_nature_sources],
            format_func=lambda source_id: find_source(load_source_registry(SOURCE_REGISTRY_FILE), source_id).get("name", source_id),
            key="nature_selected_sources",
        )
        for source_id in selected_nature_ids:
            source = find_source(registry, source_id)
            st.markdown(
                f"- **{source['name']}**: query `{source.get('query', '')}` | "
                f"journal `{source.get('journal') or 'all'}` | next start `{default_incremental_start_date(source)}`"
            )

        nature_task_key = "nature_incremental_task"
        nature_task_id = st.session_state.get(nature_task_key)
        task = render_task_status(
            nature_task_id,
            "Nature incremental update",
            success_message=lambda result: f"Nature incremental update finished for {len(result.get('source_ids', []))} source(s).",
            cleanup_on_complete=False,
            auto_refresh=True,
            show_history=True,
        )
        if task is None and nature_task_id:
            st.session_state.pop(nature_task_key, None)
            st.session_state["csv_state"] = ()
            st.rerun()
        if st.button("Run Nature Incremental Update", type="primary", use_container_width=True):
            if not selected_nature_ids:
                st.warning("Select at least one Nature source with a query.")
            else:
                st.session_state[nature_task_key] = submit_nature_incremental(
                    SOURCE_REGISTRY_FILE,
                    selected_nature_ids,
                    NATURE_UPDATE_DIR,
                    import_after=True,
                    db_file=DB_FILE,
                    cache_dir=CACHE_DIR,
                    source_root=SOURCE_CSV_DIR,
                    manifest_path=SOURCE_MANIFEST_FILE,
                )
                st.success("Nature incremental update queued in the background. New CSVs will be imported automatically.")
                st.rerun()

        st.markdown("---")
        st.markdown("### Manual Nature Grabber")
        st.caption("Use this only when you want an ad-hoc manual Nature-family pull outside the saved auto-incremental sources.")
        manual_col1, manual_col2 = st.columns(2)
        with manual_col1:
            ng_query = st.text_input("Search Query", key="nature_manual_query", placeholder="e.g. cryogenic CMOS qubit readout")
            ng_journal = st.selectbox(
                "Journal Filter",
                options=[value for value, _ in NATURE_JOURNAL_OPTIONS],
                format_func=format_nature_journal,
                key="nature_manual_journal",
            )
            ng_year_from = st.number_input("Start Year", min_value=1990, max_value=CURRENT_YEAR, value=2015, step=1, key="nature_manual_year_from")
        with manual_col2:
            ng_max_pages = st.number_input("Max Pages", min_value=1, max_value=50, value=5, step=1, key="nature_manual_pages")
            ng_sleep = st.number_input("Request Delay (s)", min_value=0.0, max_value=10.0, value=1.0, step=0.5, key="nature_manual_sleep")
            ng_output = st.text_input("Output CSV", value=f"{slugify_filename(ng_query or 'nature_search')}.csv", key="nature_manual_output")
        if st.button("Run Manual Nature Grabber", use_container_width=True):
            if not ng_query.strip():
                st.warning("Nature search query is required.")
            else:
                from Nature_Grabber import grab_nature

                output_name = ng_output if ng_output.lower().endswith(".csv") else f"{ng_output}.csv"
                output_file = output_name if os.path.isabs(output_name) else os.path.join(SOURCE_CSV_DIR, "manual", output_name)
                with st.spinner("Fetching Nature metadata..."):
                    grab_nature(
                        query=ng_query,
                        output_file=output_file,
                        journal=ng_journal,
                        year_from=int(ng_year_from),
                        max_pages=int(ng_max_pages),
                        sleep_seconds=float(ng_sleep),
                    )
                st.session_state["csv_state"] = ()
                st.success(f"Saved to {output_file}")
                st.rerun()

    with tab_arxiv:
        st.markdown("### arXiv Source Registry")
        with st.form("arxiv_registry_form"):
            for source in arxiv_sources:
                with st.expander(source.get("name", source["id"]), expanded=False):
                    st.checkbox("Enabled", value=source.get("enabled", True), key=f"arxiv_enabled_{source['id']}")
                    st.text_input("Display Name", value=source.get("name", ""), key=f"arxiv_name_{source['id']}")
                    st.text_input("Query", value=source.get("query", ""), key=f"arxiv_query_{source['id']}")
                    st.text_input("Categories (; separated)", value="; ".join(source.get("categories", [])), key=f"arxiv_categories_{source['id']}")
                    st.number_input("Max Results", min_value=10, max_value=300, value=int(source.get("max_results", 100)), step=10, key=f"arxiv_results_{source['id']}")
                    st.number_input("Request Delay (s)", min_value=0.0, max_value=10.0, value=float(source.get("sleep_seconds", 0.5)), step=0.5, key=f"arxiv_sleep_{source['id']}")
                    last_checked = source.get("last_checked_date", "") or "2015-01-01"
                    st.date_input("Last Checked Date", value=date.fromisoformat(last_checked), key=f"arxiv_last_checked_{source['id']}")
                    st.caption(f"Next incremental start date: `{default_incremental_start_date(source)}`")
                    st.caption(source.get("notes", ""))
            if st.form_submit_button("Save arXiv Source Settings", use_container_width=True):
                for source in arxiv_sources:
                    replace_source(
                        registry,
                        source["id"],
                        {
                            "enabled": st.session_state[f"arxiv_enabled_{source['id']}"],
                            "name": st.session_state[f"arxiv_name_{source['id']}"],
                            "query": st.session_state[f"arxiv_query_{source['id']}"],
                            "categories": [item.strip() for item in str(st.session_state[f"arxiv_categories_{source['id']}"]).split(";") if item.strip()],
                            "max_results": int(st.session_state[f"arxiv_results_{source['id']}"]),
                            "sleep_seconds": float(st.session_state[f"arxiv_sleep_{source['id']}"]),
                            "last_checked_date": st.session_state[f"arxiv_last_checked_{source['id']}"].isoformat(),
                        },
                    )
                save_source_registry(registry, SOURCE_REGISTRY_FILE)
                st.success("arXiv source settings saved.")

        registry = load_source_registry(SOURCE_REGISTRY_FILE)
        runnable_arxiv_sources = [source for source in list_sources(registry, "arxiv") if source.get("enabled") and source.get("query")]
        selected_arxiv_ids = st.multiselect(
            "arXiv sources to run",
            options=[source["id"] for source in runnable_arxiv_sources],
            default=[source["id"] for source in runnable_arxiv_sources],
            format_func=lambda source_id: find_source(load_source_registry(SOURCE_REGISTRY_FILE), source_id).get("name", source_id),
            key="arxiv_selected_sources",
        )
        for source_id in selected_arxiv_ids:
            source = find_source(registry, source_id)
            st.markdown(
                f"- **{source['name']}**: query `{source.get('query', '')}` | "
                f"categories `{', '.join(source.get('categories', [])) or 'all'}` | next start `{default_incremental_start_date(source)}`"
            )

        arxiv_task_key = "arxiv_incremental_task"
        arxiv_task_id = st.session_state.get(arxiv_task_key)
        task = render_task_status(
            arxiv_task_id,
            "arXiv incremental update",
            success_message=lambda result: f"arXiv incremental update finished for {len(result.get('source_ids', []))} source(s).",
            cleanup_on_complete=False,
            auto_refresh=True,
            show_history=True,
        )
        if task is None and arxiv_task_id:
            st.session_state.pop(arxiv_task_key, None)
            st.session_state["csv_state"] = ()
            st.rerun()
        if st.button("Run arXiv Incremental Update", type="primary", use_container_width=True):
            if not selected_arxiv_ids:
                st.warning("Select at least one arXiv source with a query.")
            else:
                st.session_state[arxiv_task_key] = submit_arxiv_incremental(SOURCE_REGISTRY_FILE, selected_arxiv_ids, ARXIV_UPDATE_DIR)
                st.success("arXiv incremental update queued in the background.")
                st.rerun()


def run():
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    _vx_auth()
    migrate_local_data()

    st.set_page_config(page_title=f"ChipSeeker {APP_VERSION}", layout="wide")
    st.title(f"ChipSeeker {APP_VERSION}")
    st.markdown(
        """
**Author:** Miao Yixuan | **Email:** [guangeofaisa@gmail.com](mailto:guangeofaisa@gmail.com) | **GitHub:** [https://github.com/Yixuan-Miao](https://github.com/Yixuan-Miao)
"""
    )
    st.caption(f"Version: {APP_VERSION} | Repo: {GITHUB_REPO_URL}")

    if "citations_fetched" not in st.session_state:
        st.session_state.citations_fetched = False
        st.session_state.citations_map = {}

    app_config = load_app_config((CONFIG_FILE, LEGACY_CONFIG_FILE, EXAMPLE_CONFIG_FILE))
    ui_language = app_config.get("ui_language", "English")
    user_store = UserDataStore(USER_DATA_FILE)
    schema_state = load_json(LOCAL_DATA_STATE_FILE, {})
    content_status = detect_content_pack_status(DATA_DIR, DB_FILE, CACHE_DIR, SOURCE_MANIFEST_FILE, schema_state=schema_state)

    if st.session_state.get("show_quick_start") or not app_config.get("onboarding_completed", False):
        render_quick_start(app_config, content_status, ui_language)

    def get_user_data(title):
        return user_store.get(title)

    def update_user_data(title, key, value):
        user_store.update(title, key, value)

    source_csv_files = list_source_csv_files(source_root=SOURCE_CSV_DIR, manifest_path=SOURCE_MANIFEST_FILE)
    current_csv_state = build_source_state(source_csv_files)
    current_source_snapshot = build_source_snapshot(source_csv_files, source_root=SOURCE_CSV_DIR)
    if library_sync_required(schema_state, current_source_snapshot, DB_FILE):
        with st.spinner("Syncing library..."):
            added_count, updated_count, removed_count, file_summaries = scan_and_import_csvs(
                DB_FILE,
                CACHE_DIR,
                source_root=SOURCE_CSV_DIR,
                manifest_path=SOURCE_MANIFEST_FILE,
            )
            schema_state["library_sync"] = {
                "db_file": os.path.abspath(DB_FILE),
                "source_token": current_source_snapshot["token"],
                "source_files": current_source_snapshot["files"],
                "last_synced_at_utc": datetime.now(timezone.utc).isoformat(),
                "db_record_count": len(load_json(DB_FILE, [])),
            }
            save_json(LOCAL_DATA_STATE_FILE, schema_state)
            st.session_state["csv_state"] = current_csv_state
            if added_count or updated_count or removed_count:
                msg = list(file_summaries)
                if removed_count:
                    msg.append(f"Removed: {removed_count}")
                if added_count:
                    msg.append(f"Added: {added_count}")
                if updated_count:
                    msg.append(f"Updated: {updated_count}")
                for state_key in ("current_query", "raw_results", "initial_count"):
                    st.session_state.pop(state_key, None)
                st.toast("\n\n".join(msg + ["Embedding cache preserved; search cache will refresh incrementally if needed."]))
                st.cache_resource.clear()
                time.sleep(1.0)
                st.rerun()
    else:
        st.session_state["csv_state"] = current_csv_state

    if bibliographic_metadata_enrich_required(schema_state, current_source_snapshot, DB_FILE):
        with st.spinner("Repairing bibliographic metadata from source CSVs..."):
            enrich_result = enrich_bibliographic_metadata(
                DB_FILE,
                source_root=SOURCE_CSV_DIR,
                manifest_path=SOURCE_MANIFEST_FILE,
            )
            schema_state["bibliographic_metadata_enrich"] = {
                "db_file": os.path.abspath(DB_FILE),
                "source_token": current_source_snapshot["token"],
                "source_files": current_source_snapshot["files"],
                "schema_version": schema_state.get("schema_version", 0),
                "last_enriched_at_utc": datetime.now(timezone.utc).isoformat(),
                "matched_rows": enrich_result.get("matched_rows", 0),
                "updated_count": enrich_result.get("updated_count", 0),
            }
            save_json(LOCAL_DATA_STATE_FILE, schema_state)
            if enrich_result.get("updated_count", 0):
                st.cache_resource.clear()
                st.toast(
                    "BibTeX metadata repaired from source CSVs: "
                    f"{enrich_result['updated_count']} paper(s) updated. Embedding cache preserved."
                )
                time.sleep(1.0)
                st.rerun()

    content_status = detect_content_pack_status(DATA_DIR, DB_FILE, CACHE_DIR, SOURCE_MANIFEST_FILE, schema_state=load_json(LOCAL_DATA_STATE_FILE, {}))
    ui_language = st.sidebar.selectbox(
        "Language / 语言",
        LANGUAGE_OPTIONS,
        index=LANGUAGE_OPTIONS.index(app_config.get("ui_language", "English")) if app_config.get("ui_language", "English") in LANGUAGE_OPTIONS else 0,
    )
    if app_config.get("ui_language", "English") != ui_language:
        app_config["ui_language"] = ui_language
        save_json(CONFIG_FILE, app_config)
    workspace_view = st.sidebar.radio(tr(ui_language, "Workspace", "工作区"), ["Search", "Update Manager", "Conflict Review"], horizontal=False)
    st.sidebar.caption(f"local_data schema v{schema_state.get('schema_version', '?')}")
    render_content_pack_sidebar(content_status, ui_language)

    all_papers_in_db = load_json(DB_FILE, [])
    library_years = available_years(all_papers_in_db)
    total_papers, db_stats, active_years = generate_db_stats(all_papers_in_db, analyze_venue)

    if workspace_view == "Update Manager":
        render_update_manager(source_csv_files, all_papers_in_db)
        return

    if workspace_view == "Conflict Review":
        render_conflict_review(source_csv_files)
        return

    _, help_col_right = st.columns([8, 1])
    with help_col_right:
        if st.button(tr(ui_language, "Help", "帮助"), use_container_width=True):
            st.session_state["show_help_panel"] = not st.session_state.get("show_help_panel", False)
    if st.session_state.get("show_help_panel", False):
        render_help_panel(ui_language)

    render_taxonomy_matrix(total_papers, db_stats, active_years)

    st.sidebar.header(tr(ui_language, "Search Mode", "搜索模式"))
    emb_models = ["voyage-4-large", "voyage-4", "voyage-4-lite", "voyage-context-3", "text-embedding-3-large", "all-MiniLM-L6-v2"]
    selected_emb_model = st.sidebar.selectbox(tr(ui_language, "Model", "模型"), emb_models, index=emb_models.index(app_config.get("embedding_model", "all-MiniLM-L6-v2")) if app_config.get("embedding_model") in emb_models else 5)
    emb_api_key = app_config.get("emb_api_key", "")
    if selected_emb_model == "all-MiniLM-L6-v2":
        st.sidebar.caption(tr(ui_language, "Default local path. No embedding API key required.", "默认本地路径，不需要 embedding API key。"))
    else:
        st.sidebar.markdown(
            tr(
                ui_language,
                "Recommended strongest ChipSeeker Lite Search model: **voyage-4-large**. Get an API key from [Voyage AI](https://dash.voyageai.com/).",
                "推荐最强语义模型：**voyage-4-large**。可在 [Voyage AI](https://dash.voyageai.com/) 申请 API key。",
            )
        )
        emb_api_key = st.sidebar.text_input(tr(ui_language, "Embedding API Key", "Embedding API Key"), value=app_config.get("emb_api_key", ""), type="password")
        st.sidebar.caption(tr(ui_language, "No key? Switch to MiniLM for local search, or use your own Voyage key.", "没有 key？可以切回 MiniLM 本地搜索，或填写自己的 Voyage key。"))
    config_updates = {
        "embedding_model": selected_emb_model,
        "emb_api_key": emb_api_key,
        "cloud_access_enabled": False,
    }
    if any(app_config.get(key) != value for key, value in config_updates.items()):
        app_config.update(config_updates)
        save_json(CONFIG_FILE, app_config)

    current_preset = app_config.get("provider_preset", "DeepSeek")
    api_key = app_config.get("llm_api_key", "")
    base_url, model_name = resolve_provider_defaults(current_preset, app_config)
    emb_runtime_key = runtime_embedding_key(app_config, emb_api_key) if embedding_model_requires_api(selected_emb_model) else ""
    llm_runtime_key = runtime_llm_key(app_config, api_key)
    embedding_api_ready = (not embedding_model_requires_api(selected_emb_model)) or bool(str(emb_runtime_key).strip())
    selected_papers_panel = st.sidebar.container()
    llm_tools_panel = st.sidebar.container()
    scope_presets = semantic_scope_presets(library_years)
    scope_status_map = {}
    for preset in scope_presets:
        preset_papers = filter_papers_by_years(all_papers_in_db, preset["years"]) if preset["years"] else list(all_papers_in_db)
        preset_scope_key = build_scope_key(preset["years"])
        scope_status_map[preset["id"]] = {
            "scope_key": preset_scope_key,
            "scope_text": scope_label(preset["years"]),
            "years": preset["years"],
            "total_papers": len(preset_papers),
            "cache_status": describe_cache_status(DB_FILE, selected_emb_model, scope_key=preset_scope_key, papers_override=preset_papers) if preset_papers else {
                "cache_file": "",
                "meta_file": "",
                "total_papers": 0,
                "cached_papers": 0,
                "has_cache": False,
                "up_to_date": False,
                "needs_build": False,
                "append_only": False,
                "new_papers": 0,
            },
        }

    semantic_scope_candidates = ["full_library", "latest_three_years", "latest_year"]
    active_scope_id = next(
        (
            scope_id
            for scope_id in semantic_scope_candidates
            if scope_status_map.get(scope_id, {}).get("cache_status", {}).get("up_to_date") and scope_status_map.get(scope_id, {}).get("total_papers", 0) > 0
        ),
        None,
    )
    active_scope_years = scope_status_map[active_scope_id]["years"] if active_scope_id else []
    active_scope_key = scope_status_map[active_scope_id]["scope_key"] if active_scope_id else "all"
    active_scope_text = scope_status_map[active_scope_id]["scope_text"] if active_scope_id else tr(ui_language, "No ChipSeeker Lite cache ready", "还没有可用的 ChipSeeker Lite 缓存")
    other_ready_caches = ready_cache_suggestions(
        DB_FILE,
        CACHE_DIR,
        emb_models,
        selected_emb_model,
        scope_presets,
        all_papers_in_db,
    )

    foreground_task_id = st.session_state.get("foreground_embedding_task_id")
    foreground_task_scope_id = st.session_state.get("foreground_embedding_scope_id")
    foreground_task_model = st.session_state.get("foreground_embedding_model")
    foreground_task = get_task(foreground_task_id) if foreground_task_id and foreground_task_model == selected_emb_model else None
    if foreground_task and foreground_task.get("status") == "completed":
        st.session_state.pop("foreground_embedding_task_id", None)
        st.session_state.pop("foreground_embedding_scope_id", None)
        st.session_state.pop("foreground_embedding_model", None)
        st.cache_resource.clear()
        time.sleep(0.5)
        st.rerun()
    elif foreground_task and foreground_task.get("status") == "failed":
        st.warning(f"Previous embedding build failed: {foreground_task.get('error', 'unknown error')}")

    searcher = (
        get_searcher_engine(DB_FILE, selected_emb_model, emb_runtime_key, scope_key=active_scope_key, scope_years=tuple(active_scope_years))
        if active_scope_id and embedding_api_ready
        else None
    )

    st.markdown("---")
    st.markdown(f"### {tr(ui_language, 'ChipSeeker Lite Cache Builder', 'ChipSeeker Lite 缓存构建器')}")
    st.caption(
        tr(
            ui_language,
            "Build a small scope first for fast onboarding. ChipSeeker Lite Search will automatically use the largest ready cache.",
            "建议先构建一个较小范围快速上手。ChipSeeker Lite Search 会自动使用当前已就绪的最大缓存范围。",
        )
    )
    if active_scope_id:
        active_scope_label = next(preset["label"] for preset in scope_presets if preset["id"] == active_scope_id)
        st.info(
            tr(
                ui_language,
                f"Current ChipSeeker Lite Search coverage: {active_scope_label} ({active_scope_text})",
                f"当前 ChipSeeker Lite Search 覆盖范围：{tr(ui_language, active_scope_label, {'Latest Year': '最新一年', 'Latest 3 Years': '最新三年', 'Full Library': '全库'}[active_scope_label])}（{active_scope_text}）",
            )
        )
    else:
        st.warning(tr(ui_language, "No ChipSeeker Lite cache is ready yet. Build one of the ranges below first.", "目前还没有可用的 ChipSeeker Lite 缓存，请先构建下面的任一范围。"))

    if other_ready_caches and (not active_scope_id or (embedding_model_requires_api(selected_emb_model) and not embedding_api_ready)):
        st.info(
            tr(
                ui_language,
                f"Ready caches were found for other models. Content-pack .npy files are model-specific: a voyage-4-large cache cannot be used by the currently selected {selected_emb_model}.",
                f"检测到其他模型已有可用缓存。内容包里的 .npy 按模型区分：voyage-4-large 的缓存不能被当前选择的 {selected_emb_model} 直接使用。",
            )
        )
        st.caption(
            tr(
                ui_language,
                "If you use Voyage/OpenAI models, the paper cache can be prebuilt, but each new search query still needs a direct API key. MiniLM works locally without an API key.",
                "如果使用 Voyage/OpenAI 模型，论文向量缓存可以预先打包，但每次新搜索的 query 仍然需要直接 API key。MiniLM 可以完全本地运行。",
            )
        )
        suggestion_cols = st.columns(min(3, len(other_ready_caches)))
        for col, suggestion in zip(suggestion_cols, other_ready_caches[:3]):
            with col:
                needs_api_label = tr(ui_language, "needs API key", "需要 API key") if suggestion["needs_api"] else tr(ui_language, "local, no API", "本地无需 API")
                st.markdown(
                    f"**{suggestion['model']}**  \n"
                    f"{suggestion['scope_label']} · `{suggestion['cached_papers']}` papers  \n"
                    f"`{needs_api_label}`"
                )
                if st.button(
                    tr(ui_language, f"Switch to {suggestion['model']}", f"切换到 {suggestion['model']}"),
                    key=f"switch_ready_cache_{suggestion['model']}_{suggestion['scope_id']}",
                    use_container_width=True,
                ):
                    app_config["embedding_model"] = suggestion["model"]
                    save_json(CONFIG_FILE, app_config)
                    st.cache_resource.clear()
                    st.rerun()

    preset_cols = st.columns(3)
    for col, preset in zip(preset_cols, scope_presets):
        scope_info = scope_status_map[preset["id"]]
        cache_status = scope_info["cache_status"]
        with col:
            st.markdown(semantic_scope_summary(ui_language, preset["label"], scope_info["total_papers"], cache_status))
            button_label = tr(
                ui_language,
                f"Build {preset['label']}",
                {
                    "Latest Year": "构建最新一年",
                    "Latest 3 Years": "构建最新三年",
                    "Full Library": "构建全库",
                }[preset["label"]],
            )
            disabled = (
                scope_info["total_papers"] == 0
                or cache_status.get("up_to_date", False)
                or (foreground_task and foreground_task.get("status") in {"queued", "running"})
                or (embedding_model_requires_api(selected_emb_model) and not embedding_api_ready)
            )
            if st.button(button_label, key=f"build_scope_{preset['id']}", use_container_width=True, disabled=disabled):
                st.session_state["foreground_embedding_task_id"] = submit_embedding_build(
                    DB_FILE,
                    selected_emb_model,
                    emb_runtime_key,
                    years=scope_info["years"],
                    scope_key=scope_info["scope_key"],
                )
                st.session_state["foreground_embedding_scope_id"] = preset["id"]
                st.session_state["foreground_embedding_model"] = selected_emb_model
                st.rerun()

    if embedding_model_requires_api(selected_emb_model) and not embedding_api_ready:
        st.warning(
            tr(
                ui_language,
                "Selected embedding model needs a direct API key. Use MiniLM for zero-config local search or add your own Voyage/OpenAI-compatible key.",
                "当前 embedding 模型需要直接 API key。你可以先用 MiniLM，或者填写自己的 Voyage/OpenAI 兼容 key。",
            )
        )

    if foreground_task_id and foreground_task_scope_id and foreground_task_model == selected_emb_model:
        foreground_scope_text = scope_status_map.get(foreground_task_scope_id, {}).get("scope_text", foreground_task_scope_id)
        foreground_task = render_foreground_task_console(
            foreground_task_id,
            f"Embedding build for {selected_emb_model} ({foreground_scope_text})",
            success_message=lambda result: f"Embedding cache ready for {result.get('model_name', selected_emb_model)} on {scope_label(result.get('years', []))}.",
        )

    st.markdown("---")
    st.markdown(f"### {tr(ui_language, 'Search Papers', '搜索论文')}")
    st.caption(
        tr(
            ui_language,
            "Main workflow: describe the paper direction first, then optionally filter those results with exact keywords.",
            "主流程：先描述你想找的论文方向，再按需用精确关键词过滤这些结果。",
        )
    )
    st.caption(
        tr(
            ui_language,
            f"Current ChipSeeker Lite Search coverage: {active_scope_text}",
            f"当前 ChipSeeker Lite Search 覆盖范围：{active_scope_text}",
        )
    )

    search_query = st.text_area(
        tr(ui_language, "Step 1. Describe your topic", "步骤 1：描述你想搜索的论文方向"),
        placeholder=tr(
            ui_language,
            "Describe your topic, circuit type, application, method, or problem. Full sentences are OK.",
            "描述论文方向、电路类型、应用、方法或问题。不需要只写关键词，句子也可以。",
        ),
        height=86,
        key="semantic_query_input",
    )

    col_s2, col_s3, col_s4 = st.columns([2.5, 1, 1])
    with col_s2:
        must_have = st.text_input(
            tr(
                ui_language,
                "Step 2. Optional keyword search inside results",
                "步骤 2：可选，在结果中做关键词过滤",
            ),
            placeholder=tr(ui_language, "Examples: Y. Zeng | ADC/PLL | ADC, calibration", "示例：Y. Zeng | ADC/PLL | ADC, calibration"),
            help=tr(
                ui_language,
                "Case-insensitive. Spaces stay inside one phrase, so `Y. Zeng` searches that name. Use `/` for OR: `ADC/PLL`. Use comma, `&`, or `and` for AND: `ADC, calibration`.",
                "不区分大小写。空格保留为短语，所以 `Y. Zeng` 会按作者名搜索。用 `/` 表示 OR：`ADC/PLL`。用逗号、`&` 或 `and` 表示 AND：`ADC, calibration`。",
            ),
        )
    with col_s3:
        display_limit_val = st.number_input(
            tr(ui_language, "Display Limit", "展示数量"),
            min_value=50,
            max_value=2000,
            value=50,
            step=50,
            help=tr(ui_language, "Controls how many final results are displayed. Exact Match still scans the full library.", "只控制最终展示多少条结果；Exact Match 仍然扫描全库。"),
        )
    with col_s4:
        rerank_limit_val = st.number_input(
            tr(ui_language, "LLM Rerank Limit", "LLM 重排篇数"),
            min_value=5,
            max_value=100,
            value=30,
            step=5,
            help=tr(ui_language, "How many top papers are reranked by DeepSeek LLM in Pro Search. More papers = slower but better coverage.", "Pro Search 中用 DeepSeek LLM 重排多少篇候选论文。越多越慢但覆盖更全。"),
        )

    search_btn_col1, search_btn_col2 = st.columns([1, 1])
    with search_btn_col1:
        semantic_search_clicked = st.button(
            tr(ui_language, "ChipSeeker Lite Search", "ChipSeeker Lite 搜索"),
            type="primary",
            use_container_width=True,
            help=tr(ui_language, "Fast search with your direct query.", "使用原始输入快速搜索。"),
        )
    with search_btn_col2:
        llm_powered_clicked = st.button(
            tr(ui_language, "ChipSeeker Pro Search", "ChipSeeker Pro 搜索"),
            use_container_width=True,
            help=tr(ui_language, "DeepSeek expands your query, runs ChipSeeker Lite Search, then reranks the top candidates.", "DeepSeek 先扩展搜索词，再运行 ChipSeeker Lite Search 并重排候选结果。"),
        )
    selected_ui_venues = []
    selected_years = (2000, CURRENT_YEAR)
    with st.expander(tr(ui_language, "Optional helpers and filters", "可选辅助工具和过滤器"), expanded=False):
        st.caption(tr(ui_language, "These tools are optional. They are not the main search box.", "这些只是可选辅助功能，不是主搜索框。"))
        st.markdown(f"##### {tr(ui_language, 'Keyword Generator', '关键词生成器')}")
        st.caption(tr(ui_language, "Optional helper for generating better exact-match terms.", "可选：帮你生成更适合 Step 2 使用的关键词。"))
        user_idea = st.text_input(
            tr(ui_language, "Describe a topic to generate keywords", "描述一个主题来生成关键词"),
            key="user_idea_input",
        )
        generate_keywords_clicked = st.button(
            tr(ui_language, "Generate Keywords", "生成关键词"),
            use_container_width=True,
        )
        if generate_keywords_clicked:
            if not user_idea.strip():
                st.warning(tr(ui_language, "Enter a topic first.", "请先输入主题。"))
                st.stop()
            if not llm_runtime_key:
                st.error(tr(ui_language, "Please configure an LLM API key first.", "请先配置 LLM API key。"))
            else:
                with st.spinner("Generating..."):
                    try:
                        st.session_state.kw_result = generate_search_keywords(user_idea, llm_runtime_key, base_url, model_name)
                        st.session_state.last_idea = user_idea
                    except Exception as exc:
                        st.error(str(exc))
        if st.session_state.get("kw_result"):
            st.info(f"{tr(ui_language, 'Suggested Keywords', '推荐关键词')}: `{st.session_state.kw_result}`")

        st.markdown(f"##### {tr(ui_language, 'Metadata Pre-Filters', '元数据预过滤')}")
        filter_col1, filter_col2 = st.columns(2)
        with filter_col1:
            unique_venues = sorted({analyze_venue(paper.get("venue", ""))["n"] for paper in all_papers_in_db if paper.get("venue")})
            unique_venues = [venue for venue in unique_venues if venue != "Other"]
            selected_ui_venues = st.multiselect(tr(ui_language, "Filter by Unified Venue", "按统一 Venue 过滤"), unique_venues)
        with filter_col2:
            if active_years:
                min_year, max_year = min(active_years), max(active_years)
                if min_year == max_year:
                    min_year -= 1
                selected_years = st.slider(tr(ui_language, "Filter by Year", "按年份过滤"), min_year, max_year, (min_year, max_year))
            else:
                selected_years = (2000, CURRENT_YEAR)

    def apply_search_results(filtered_results, initial_scan_count, query_state_key, search_mode, effective_query):
        st.session_state.raw_results = filtered_results
        st.session_state.initial_count = initial_scan_count
        st.session_state.current_query = query_state_key
        st.session_state.current_search_mode = search_mode
        st.session_state["last_effective_search_query"] = effective_query
        st.session_state["last_search_mode"] = search_mode
        for item in filtered_results:
            title = item["paper"].get("title")
            user_data = get_user_data(title)
            update_user_data(title, "search_count", int(user_data.get("search_count", 0)) + 1)
            if item["similarity"] >= 0.25 and search_query:
                if search_query not in user_data["matched_queries"]:
                    user_data["matched_queries"].append(search_query)
                    update_user_data(title, "matched_queries", user_data["matched_queries"])
        for key in list(st.session_state.keys()):
            if key.startswith("chk_"):
                del st.session_state[key]

    llm_task_active = False
    trigger_search = bool(search_query or selected_ui_venues or must_have)
    search_requested = bool(semantic_search_clicked or llm_powered_clicked)
    query_state_key = ""
    if trigger_search:
        source_token = current_source_snapshot.get("token", "")
        query_state_key = f"{search_query}_must{must_have}_limit{display_limit_val}_rerank{rerank_limit_val}_{selected_emb_model}_v{selected_ui_venues}_y{selected_years}_csv{source_token}"

    llm_task_id = st.session_state.get("llm_search_task_id")
    if llm_task_id:
        llm_task = get_task(llm_task_id)
        if llm_task and llm_task.get("status") in {"queued", "running"}:
            started_at = float(llm_task.get("started_at") or llm_task.get("created_at") or time.time())
            elapsed = max(0.0, time.time() - started_at)
            if elapsed > LLM_SEARCH_UI_TIMEOUT_SECONDS:
                cancel_task(llm_task_id, "Canceled automatically after UI timeout")
                cleanup_task(llm_task_id)
                st.session_state.pop("llm_search_task_id", None)
                st.warning("ChipSeeker Pro Search timed out. The old running job was cleared; please try again with a narrower query or faster DeepSeek model.")
                st.rerun()
            llm_task_active = True
            st.info(f"ChipSeeker Pro Search: {llm_task.get('message', llm_task.get('status', 'running'))}")
            task_cols = st.columns([5, 1, 1])
            task_cols[0].progress(float(llm_task.get("progress", 0.0)) or 0.01)
            if task_cols[1].button("Refresh", use_container_width=True):
                st.rerun()
            if task_cols[2].button("Cancel", use_container_width=True, type="primary"):
                cancel_task(llm_task_id)
                st.session_state.pop("llm_search_task_id", None)
                st.warning("ChipSeeker Pro Search canceled. Any late DeepSeek response will be ignored.")
                st.rerun()
            with st.expander("LLM Search Console", expanded=False):
                st.code(format_task_history(llm_task), language="text")
            time.sleep(2.5)
            st.rerun()
        elif llm_task and llm_task.get("status") == "completed":
            result = llm_task.get("result", {})
            apply_search_results(
                result.get("results", []),
                int(result.get("initial_count", 0)),
                result.get("query_state_key") or query_state_key or llm_task_id,
                "llm_powered",
                result.get("effective_query", search_query),
            )
            st.success(f"ChipSeeker Pro Search finished. Reranked top {result.get('rerank_limit', 20)} papers.")
            cleanup_task(llm_task_id)
            st.session_state.pop("llm_search_task_id", None)
            st.rerun()
        elif llm_task and llm_task.get("status") == "canceled":
            st.warning("ChipSeeker Pro Search was canceled.")
            cleanup_task(llm_task_id)
            st.session_state.pop("llm_search_task_id", None)
        elif llm_task and llm_task.get("status") == "failed":
            st.error(f"ChipSeeker Pro Search failed: {llm_task.get('error', 'unknown error')}")
            cleanup_task(llm_task_id)
            st.session_state.pop("llm_search_task_id", None)
        else:
            st.session_state.pop("llm_search_task_id", None)

    if search_requested and not llm_task_active:
        if not trigger_search:
            st.warning(tr(ui_language, "Enter a Step 1 query, Step 2 exact keyword, or metadata filter first.", "请先输入步骤 1 查询、步骤 2 精确关键词，或选择元数据过滤。"))
            st.stop()
        if search_requested:
            search_mode = "llm_powered" if llm_powered_clicked else "semantic"
            st.session_state.citations_fetched = False
            st.session_state.citations_map = {}
            if llm_powered_clicked:
                if not search_query:
                    st.error("ChipSeeker Pro Search needs a Step 1 search query.")
                    st.stop()
                if not llm_runtime_key:
                    st.error(tr(ui_language, "LLM API key is missing.", "缺少 LLM API key。"))
                    st.stop()
                if not active_scope_id:
                    st.error("ChipSeeker Lite cache is not ready. Build a cache first.")
                    st.stop()
                st.session_state["llm_search_task_id"] = submit_llm_powered_search(
                    DB_FILE,
                    search_query,
                    must_have,
                    display_limit_val,
                    selected_ui_venues,
                    selected_years,
                    selected_emb_model,
                    embedding_api_key=emb_runtime_key,
                    active_scope_key=active_scope_key,
                    active_scope_years=active_scope_years,
                    llm_api_key=llm_runtime_key,
                    llm_base_url=base_url,
                    llm_model=model_name,
                    rerank_limit=rerank_limit_val,
                    query_state_key=query_state_key,
                )
                st.rerun()
            with st.spinner("Scanning library..."):
                effective_query = search_query
                st.session_state["last_effective_search_query"] = search_query
                st.session_state["last_search_mode"] = search_mode

                if search_query:
                    if not searcher:
                        if embedding_model_requires_api(selected_emb_model) and not embedding_api_ready:
                            st.warning(tr(ui_language, "ChipSeeker Lite Search is disabled because the selected embedding model requires an API key. Switch to MiniLM or add a key first.", "ChipSeeker Lite Search 当前不可用，因为所选 embedding 模型需要 API key。你可以先切回 MiniLM，或者先填写 key。"))
                        else:
                            st.warning(tr(ui_language, "Current ChipSeeker Lite cache is not ready. Build one of the ranges above first, or keep using metadata filters for now.", "当前 ChipSeeker Lite 缓存还没准备好。请先构建上面的任一范围，或者暂时只使用元数据过滤。"))
                        filtered_results = []
                        initial_scan_count = 0
                    elif must_have or selected_ui_venues:
                        semantic_top_k = min(
                            max(int(display_limit_val) * SEMANTIC_PREFILTER_MULTIPLIER, SEMANTIC_PREFILTER_MIN),
                            SEMANTIC_PREFILTER_MAX,
                        )
                        semantic_hits = searcher.search(query=effective_query, top_k=semantic_top_k)
                        initial_scan_count = len(semantic_hits)
                        filtered_results = filter_search_results(
                            semantic_hits,
                            selected_years,
                            selected_ui_venues,
                            must_have,
                            analyze_venue,
                            extract_year,
                        )
                    else:
                        candidate_top_k = display_limit_val
                        filtered_results = searcher.search(query=effective_query, top_k=candidate_top_k)
                        filtered_results = filter_search_results(filtered_results, selected_years, selected_ui_venues, "", analyze_venue, extract_year)
                        initial_scan_count = len(filtered_results)
                else:
                    exact_source_papers = all_papers_in_db
                    exact_first_hits = [{"similarity": 1.0, "paper": paper} for paper in exact_source_papers]
                    exact_first_hits = filter_search_results(
                        exact_first_hits,
                        selected_years,
                        selected_ui_venues,
                        must_have,
                        analyze_venue,
                        extract_year,
                    )
                    initial_scan_count = len(exact_first_hits)
                    filtered_results = exact_first_hits[:display_limit_val]
                if len(filtered_results) > display_limit_val:
                    filtered_results = filtered_results[:display_limit_val]
                apply_search_results(filtered_results, initial_scan_count, query_state_key, search_mode, effective_query)

    results = st.session_state.get("raw_results", [])
    initial_count = st.session_state.get("initial_count", 0)
    required_words_hl = required_words_from_query(must_have)
    show_current_results = bool(trigger_search and st.session_state.get("current_query") == query_state_key)
    if not show_current_results:
        results = []
        initial_count = 0
        required_words_hl = []
    if show_current_results:
        if not results:
            st.warning(f"{initial_count} records scanned, but all were eliminated by your filters.")
            st.stop()
        bucket_counts = result_bucket_counts(results, search_query)
        st.success(f"Extracted {len(results)} matches. Rare/All: {bucket_counts['rare']} | Perfect: {bucket_counts['perfect']} | Valuable: {bucket_counts['valuable']} | Relevant: {bucket_counts['relevant']}")
        if st.session_state.get("current_search_mode") == "llm_powered":
            st.caption(f"ChipSeeker Pro Search | expanded query: {st.session_state.get('last_effective_search_query', search_query)}")
        year_counts = collect_year_counts(results, extract_year)
        if year_counts:
            with st.expander(tr(ui_language, "Optional analytics: Publication Trend", "可选分析：发表年份趋势"), expanded=False):
                st.bar_chart(year_counts)

    st.markdown("---")
    col_sort, col_batch, col_cite, col_export = st.columns([1.4, 2.2, 1, 1.2])
    with col_sort:
        st.markdown(f"### {tr(ui_language, 'Sort By', '排序方式')}")
        sort_option = st.radio(
            "Dimension",
            ["Relevance", "Year (Newest)", "Comprehensive Score"],
            horizontal=True,
            label_visibility="collapsed",
        )
    with col_cite:
        st.markdown(f"### {tr(ui_language, 'Citations', '引用数')}")
        default_fetch_num = sum(1 for item in results if item["similarity"] >= 0.40 or not search_query)
        if default_fetch_num == 0 and results:
            default_fetch_num = min(10, len(results))
        fetch_limit = st.number_input(
            tr(ui_language, "Fetch Count (Top-N)", "抓取数量（Top-N）"),
            min_value=0,
            max_value=max(1, len(results)),
            value=min(default_fetch_num, len(results)),
            step=10,
            label_visibility="collapsed",
        )
        if st.button(tr(ui_language, "Fetch & Update Scores", "抓取并更新分数"), use_container_width=True):
            with st.spinner(f"Batch fetching citations for top {fetch_limit} papers..."):
                dois_to_fetch = [result["paper"].get("doi") for result in results if result["paper"].get("doi")][:fetch_limit]
                try:
                    st.session_state.citations_map = get_batch_citations(dois_to_fetch)
                    st.session_state.citations_fetched = True
                except RuntimeError as exc:
                    st.error(f"Citation fetch failed: {exc}")
                st.rerun()

    results = sort_results(results, sort_option, search_query, st.session_state.citations_map, st.session_state.citations_fetched, analyze_venue, extract_year, CURRENT_YEAR)
    selected_papers = []
    high_value_papers_for_report = []

    with col_export:
        st.markdown(f"### {tr(ui_language, 'Export', '导出')}")
        export_limit = min(50, len(results))
        export_query_label = slugify_filename(search_query or must_have or "search_results")
        export_html_name = f"ChipSeeker_{export_query_label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        export_dir = os.path.join(EXPORT_DIR, "search_results_html")
        export_html = build_search_results_html(
            results,
            search_query,
            CURRENT_YEAR,
            analyze_venue,
            get_user_data,
            citations_map=st.session_state.citations_map,
            citations_fetched=st.session_state.citations_fetched,
            max_results=export_limit,
        )
        if st.button(tr(ui_language, f"Export Top {export_limit} as HTML", f"导出前 {export_limit} 条为 HTML"), use_container_width=True):
            export_path = os.path.join(export_dir, export_html_name)
            write_text_file(export_path, export_html)
            st.session_state["last_exported_results_html"] = export_path
        st.download_button(
            tr(ui_language, "Download HTML", "下载 HTML"),
            data=export_html,
            file_name=export_html_name,
            mime="text/html",
            use_container_width=True,
            key=f"download_results_html_{export_html_name}",
        )
        if st.session_state.get("last_exported_results_html"):
            st.caption(tr(ui_language, f"Saved to: {st.session_state['last_exported_results_html']}", f"已保存到：{st.session_state['last_exported_results_html']}"))

    with col_batch:
        st.markdown(f"### {tr(ui_language, 'Batch Select', '批量选择')}")
        rel_threshold = st.slider(tr(ui_language, "Select Relevance >=", "选择相似度阈值 >="), 0.0, 1.0, 0.40, 0.05)
        b1, b2, b3, b4, b5 = st.columns(5)

        def do_batch_select(mode, val=None):
            count = 0
            for idx, item in enumerate(results):
                paper = item["paper"]
                chk_key = f"chk_{idx}_{get_paper_id(paper)}"
                similarity = item["similarity"]
                if mode == "threshold" and (similarity >= val or not search_query):
                    st.session_state[chk_key] = True
                    count += 1
                elif mode == "rare" and (similarity >= 0.60 or not search_query):
                    st.session_state[chk_key] = True
                    count += 1
                elif mode == "perfect" and (similarity >= 0.40 or not search_query):
                    st.session_state[chk_key] = True
                    count += 1
                elif mode == "valuable" and 0.25 <= similarity < 0.40 and search_query:
                    st.session_state[chk_key] = True
                    count += 1
                elif mode == "deselect":
                    st.session_state[chk_key] = False
                    count += 1
            if mode == "deselect":
                st.toast(tr(ui_language, "Cleared all selections.", "已清空所有选择。"))
            else:
                st.toast(tr(ui_language, f"Selected {count} papers.", f"已选择 {count} 篇论文。"))

        with b1:
            st.button(f">= {rel_threshold:.2f}", on_click=do_batch_select, args=("threshold", rel_threshold), use_container_width=True)
        with b2:
            st.button("Rare", on_click=do_batch_select, args=("rare",), use_container_width=True)
        with b3:
            st.button("Perfect", on_click=do_batch_select, args=("perfect",), use_container_width=True)
        with b4:
            st.button("Valuable", on_click=do_batch_select, args=("valuable",), use_container_width=True)
        with b5:
            st.button(tr(ui_language, "Clear", "清空"), on_click=do_batch_select, args=("deselect",), use_container_width=True)

    for idx, item in enumerate(results):
        paper = item["paper"]
        similarity = item["similarity"]
        title = paper.get("title", "Untitled")
        venue = paper.get("venue", "Unknown Venue")
        year = paper.get("year", "N/A")
        doi = paper.get("doi", "")
        abstract = paper.get("abstract", "No Abstract")
        author_str = paper_authors_display(paper)
        chk_key = f"chk_{idx}_{get_paper_id(paper)}"
        user_data = get_user_data(title)
        venue_data = analyze_venue(venue)
        base_score = venue_data["s"]
        domain_color = DOMAIN_COLORS.get(venue_data["d"][0], "#757575")
        tier_color = TIER_COLORS.get(venue_data["t"], "#9E9E9E")
        year_value = extract_year(year)
        year_bonus = max(0, 10 - (CURRENT_YEAR - year_value)) if year_value > 1900 and (CURRENT_YEAR - year_value) < 10 else (10 if year_value > 1900 and (CURRENT_YEAR - year_value) <= 0 else 0)
        if similarity >= 0.60 or not search_query:
            color, badge = "#9C27B0", tr(ui_language, "Rare Match", "高稀有匹配")
        elif similarity >= 0.40:
            color, badge = "#00C853", tr(ui_language, "Perfect Match", "完美匹配")
        elif similarity >= 0.25:
            color, badge = "#2196F3", tr(ui_language, "Highly Valuable", "高价值")
        elif similarity >= 0.15:
            color, badge = "#FF9800", tr(ui_language, "Relevant", "相关")
        else:
            color, badge = "#9E9E9E", tr(ui_language, "Noise", "噪声")
        if similarity >= 0.25 or not search_query:
            high_value_papers_for_report.append(paper)
        highlighted_title = highlight_text(title, required_words_hl)
        highlighted_author = highlight_text(author_str, required_words_hl)
        venue_display = get_venue_display_str(venue_data)
        highlighted_venue = highlight_text(venue_display, required_words_hl)
        highlighted_year = highlight_text(str(year), required_words_hl)
        year_display = highlighted_year
        highlighted_abstract = highlight_text(abstract, required_words_hl)
        citations = st.session_state.citations_map.get(doi.upper(), 0) if st.session_state.citations_fetched else 0
        citation_bonus = min(15, math.log10(citations + 1) * 6) if citations > 0 else 0
        final_score = item.get("comp_score", compute_paper_score(venue_data, year_value, citations, CURRENT_YEAR))
        relevance_html = f"Relevance: {similarity * 100:.1f}%"
        if item.get("llm_score") is not None:
            try:
                llm_score = float(item.get("llm_score"))
                llm_delta = llm_score - (similarity * 100.0)
                delta_color = "#15803d" if llm_delta >= 0 else "#b91c1c"
                delta_bg = "#dcfce7" if llm_delta >= 0 else "#fee2e2"
                relevance_html = (
                    f"Relevance: {similarity * 100:.1f}% &rarr; LLM {llm_score:.0f}% "
                    f"<span style='color:{delta_color}; background:{delta_bg}; padding:2px 8px; "
                    f"border-radius:999px; font-size:0.78em; font-weight:900;'>{llm_delta:+.1f}</span>"
                )
            except (TypeError, ValueError):
                pass
        st.markdown(
            f"""
            <div style="display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; margin-bottom: 8px; padding: 6px 12px; background-color: #f8f9fa; border-radius: 8px; border-left: 5px solid {color}; gap: 10px;">
                <div style="flex: 1 1 auto; min-width: 200px;">
                    <span style="font-size: 1.1em; font-weight: 900; color: {color};">{relevance_html}</span>
                    <span style="background-color: {color}; color: white; padding: 2px 8px; border-radius: 12px; margin-left: 10px; font-size: 0.8em; display: inline-block;">{badge}</span>
                </div>
                <div style="flex: 0 1 auto; text-align: right; font-size: 1.05em; font-weight: bold; color: #D84315;">
                    Score: {final_score:.1f} <span style="font-size:0.7em; color:#757575;">(Base {base_score} + Yr {year_bonus} + Cites {citation_bonus:.1f})</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        c1, c2, c3 = st.columns([6, 2, 2])
        with c1:
            cc1, cc2 = st.columns([0.2, 9.8], gap="small")
            with cc1:
                checked = st.checkbox("", key=chk_key, label_visibility="collapsed")
            with cc2:
                st.markdown(f"<span style='font-size:1.1em; font-weight:bold;'>{highlighted_title}</span>", unsafe_allow_html=True)
            st.markdown(f"**{tr(ui_language, 'Authors', '作者')}:** {highlighted_author}", unsafe_allow_html=True)
            st.markdown(
                f"**{tr(ui_language, 'Venue', '期刊/会议')}:** <span style='color:{domain_color}; font-weight:bold;'>{highlighted_venue}</span> ({year_display}) &nbsp;&nbsp;|&nbsp;&nbsp; **Tier:** <span style='background-color:{tier_color}; color:white; padding:2px 6px; border-radius:4px; font-size:0.85em; font-weight:bold;'>{venue_data['t']}</span>",
                unsafe_allow_html=True,
            )
            if item.get("llm_score") is not None:
                st.markdown(
                    f"**LLM relevance:** `{item.get('llm_score')}/100` &nbsp; {item.get('llm_reason', '')}",
                    unsafe_allow_html=True,
                )
        with c2:
            search_hits = int(user_data.get("search_count", len(user_data.get("matched_queries", []))))
            st.markdown(f"**{tr(ui_language, 'Search Hits', '搜索命中次数')}:** `{search_hits}`")
            st.markdown(f"**{tr(ui_language, 'Reads', '阅读次数')}:** `{user_data['open_count']}`")
            if st.session_state.citations_fetched:
                st.markdown(f"**{tr(ui_language, 'Cites', '引用数')}:** `{citations}` `{tr(ui_language, 'Fetched', '已抓取')}`")
            else:
                st.markdown(f"**{tr(ui_language, 'Cites', '引用数')}:** `{tr(ui_language, 'Pending (Manual Fetch)', '待抓取（手动）')}`")
        with c3:
            rating_alias = {
                "Masterpiece": "Masterpiece",
                "Solid": "Solid",
                "Average": "Average",
                "Marginal": "Marginal",
                "Poor": "Poor",
            }
            current_rating = rating_alias.get(user_data["rating"], user_data["rating"] if user_data["rating"] in RATING_OPTIONS else "Unrated")
            rating_labels = [RATING_LABELS[value] for value in RATING_OPTIONS]
            selected_rating_label = st.selectbox(
                tr(ui_language, "Rating", "评分"),
                rating_labels,
                index=RATING_OPTIONS.index(current_rating),
                key=f"rate_{chk_key}",
                label_visibility="collapsed",
            )
            new_rating = RATING_OPTIONS[rating_labels.index(selected_rating_label)]
            if new_rating != user_data["rating"]:
                update_user_data(title, "rating", new_rating)
            new_comments = st.text_input(tr(ui_language, "Notes", "笔记"), value=user_data["comments"], key=f"comment_{chk_key}", placeholder=tr(ui_language, "Take notes...", "写点笔记..."))
            if new_comments != user_data["comments"]:
                update_user_data(title, "comments", new_comments)
        if checked:
            selected_papers.append(paper)
        with st.expander(tr(ui_language, "Read Abstract", "查看摘要")):
            st.markdown(highlighted_abstract, unsafe_allow_html=True)
        if similarity >= 0.25 or not search_query:
            with st.expander(tr(ui_language, "LLM Deep Dive", "LLM 深度分析")):
                if st.button(tr(ui_language, "Analyze with LLM", "用 LLM 分析"), key=f"ai_btn_{chk_key}"):
                    if not llm_runtime_key:
                        st.error(tr(ui_language, "LLM API key is missing.", "缺少 LLM API key。"))
                    else:
                        with st.spinner("Analyzing..."):
                            try:
                                st.markdown(analyze_with_llm(title, abstract, search_query or "Summarize", llm_runtime_key, base_url, model_name))
                            except Exception as exc:
                                st.error(str(exc))
        st.markdown("---")

    llm_tools_panel.markdown("---")
    llm_tools_panel.header(tr(ui_language, "LLM Review & Analysis (Optional)", "LLM 分析（可选）"))
    llm_tools_panel.caption(tr(ui_language, "Not required for core search. Configure an LLM API only if you want summaries and review generation.", "核心搜索不需要这个。只有在你想生成总结或综述时才需要配置 LLM API。"))
    with llm_tools_panel.expander(tr(ui_language, "Configure LLM API", "配置 LLM API"), expanded=False):
        preset_options = ["DeepSeek", "SiliconFlow", "Kimi", "Custom OpenAI"]
        current_preset = st.selectbox(
            tr(ui_language, "Provider Preset", "服务商预设"),
            preset_options,
            index=preset_options.index(app_config.get("provider_preset", "DeepSeek")) if app_config.get("provider_preset") in preset_options else 0,
            key="llm_provider_preset",
        )
        default_base, default_model = resolve_provider_defaults(current_preset, app_config)
        api_key = st.text_input(tr(ui_language, "LLM API Key", "LLM API Key"), value=app_config.get("llm_api_key", ""), type="password", key="llm_api_key_input")
        base_url = st.text_input(tr(ui_language, "Base URL", "Base URL"), value=default_base, key="llm_base_url_input")
        model_name = render_llm_model_input(ui_language, current_preset, default_model, "llm_model_input")
        if st.button(tr(ui_language, "Save LLM Settings", "保存 LLM 设置"), use_container_width=True, key="save_llm_settings"):
            app_config.update({"provider_preset": current_preset, "llm_api_key": api_key, "llm_base_url": base_url, "llm_model": model_name})
            save_json(CONFIG_FILE, app_config)
            llm_tools_panel.success(tr(ui_language, "LLM settings saved.", "LLM 设置已保存。"))
    llm_runtime_key = runtime_llm_key(app_config, api_key)
    if high_value_papers_for_report and llm_tools_panel.button(tr(ui_language, "Generate State-of-the-Art Review", "生成综述报告"), type="primary", use_container_width=True):
        if not llm_runtime_key:
            llm_tools_panel.error(tr(ui_language, "LLM API key is missing.", "缺少 LLM API key。"))
        else:
            with st.spinner("LLM is reading top papers..."):
                st.session_state.mega_report = generate_global_report_with_llm(high_value_papers_for_report, search_query or "General Review", llm_runtime_key, base_url, model_name)
    if "mega_report" in st.session_state:
        st.markdown(f"## {tr(ui_language, 'LLM Review Report', 'LLM 综述报告')}")
        st.markdown(st.session_state.mega_report)

    selected_papers_panel.markdown("---")
    selected_papers_panel.header(tr(ui_language, f"Selected Papers ({len(selected_papers)})", f"已选论文 ({len(selected_papers)})"))
    selected_papers_panel.caption(tr(ui_language, "This is the core working set for opening, downloading, and exporting.", "这是打开、下载和导出的核心论文集合。"))
    if selected_papers_panel.button(tr(ui_language, "Open Selected PDFs", "打开已选 PDF"), use_container_width=True):
        success_count = 0
        for paper in selected_papers:
            title = paper.get("title")
            user_data = get_user_data(title)
            update_user_data(title, "open_count", user_data["open_count"] + 1)
            url = paper.get("pdf_link") or (f"https://doi.org/{paper['doi']}" if paper.get("doi") else "")
            if url:
                webbrowser.open_new_tab(url)
                success_count += 1
        selected_papers_panel.info(tr(ui_language, f"Opened {success_count} tabs.", f"已打开 {success_count} 个标签页。"))

    save_dir = selected_papers_panel.text_input(
        tr(ui_language, "Batch Downloaded PDF Folder", "批量下载 PDF 文件夹"),
        value=DOWNLOAD_DIR,
        help=tr(ui_language, "The local directory where PDFs will be saved.", "下载 PDF 的本地保存目录。"),
    )
    pdf_task_key = "pdf_download_task"
    pdf_task_id = st.session_state.get(pdf_task_key)
    task = render_task_status(
        pdf_task_id,
        tr(ui_language, "PDF download queue", "PDF 下载队列"),
        success_message=lambda result: tr(
            ui_language,
            f"PDF download finished. Success: {result.get('success', 0)}, Failed: {result.get('failed', 0)}",
            f"PDF 下载完成。成功：{result.get('success', 0)}，失败：{result.get('failed', 0)}",
        ),
        container=selected_papers_panel,
    )
    if task is None and pdf_task_id:
        st.session_state.pop(pdf_task_key, None)
    if selected_papers_panel.button(tr(ui_language, "Batch Download Selected PDFs", "批量下载已选 PDF"), type="primary", use_container_width=True):
        if not selected_papers:
            selected_papers_panel.warning(tr(ui_language, "No papers selected.", "还没有选择论文。"))
        else:
            st.session_state[pdf_task_key] = submit_pdf_download(selected_papers, save_dir)
            selected_papers_panel.success(tr(ui_language, "PDF download task started.", "PDF 下载任务已开始。"))

    if selected_papers_panel.button(tr(ui_language, "Export to NotebookLM", "导出到 NotebookLM"), type="primary", use_container_width=True):
        export_content = build_notebooklm_export(selected_papers, search_query or "Filtered Subset", get_user_data)
        write_text_file(NOTEBOOKLM_EXPORT_FILE, export_content)
        selected_papers_panel.success(f"Markdown generated: {NOTEBOOKLM_EXPORT_FILE}")

    if selected_papers:
        selected_papers_panel.markdown(generate_csv_link(build_csv_rows(selected_papers)), unsafe_allow_html=True)
        selected_papers_panel.download_button(
            label=tr(ui_language, "Export IEEE BibTeX", "导出 IEEE BibTeX"),
            data=build_bibtex(selected_papers),
            file_name="references.bib",
            mime="text/plain",
            use_container_width=True,
        )
