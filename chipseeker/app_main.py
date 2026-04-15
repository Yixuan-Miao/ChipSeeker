import asyncio
import math
import os
import sys
import time
import webbrowser
from datetime import date, datetime

import streamlit as st

from chipseeker.config_store import UserDataStore, load_app_config
from chipseeker.conflict_review import collect_source_records, detect_conflicts, dismiss_conflict, load_conflict_resolutions, restore_conflicts
from chipseeker.data_sync import (
    build_paper_from_row,
    build_source_state,
    list_source_csv_files,
    paper_identity_key,
    scan_and_import_csvs,
)
from chipseeker.embedding_scope import available_years, build_scope_key, filter_papers_by_years, scope_label
from chipseeker.exports import build_bibtex, build_csv_rows, build_notebooklm_export, generate_csv_link, write_text_file
from chipseeker.llm_tools import analyze_with_llm, generate_global_report_with_llm, generate_search_keywords, get_batch_citations
from chipseeker.maintenance import compute_papers_to_purge, generate_db_stats, purge_papers_from_sources
from chipseeker.migrations import migrate_local_data
from chipseeker.paths import (
    BACKUP_ROOT_DIR,
    ARXIV_UPDATE_DIR,
    CACHE_DIR,
    CONFIG_FILE,
    CONFLICT_RESOLUTIONS_FILE,
    DB_FILE,
    DOWNLOAD_DIR,
    EXAMPLE_CONFIG_FILE,
    IEEE_UPDATE_DIR,
    LEGACY_CONFIG_FILE,
    LOCAL_DATA_STATE_FILE,
    NATURE_UPDATE_DIR,
    NOTEBOOKLM_EXPORT_FILE,
    SOURCE_CSV_DIR,
    SOURCE_MANIFEST_FILE,
    SOURCE_REGISTRY_FILE,
    USER_DATA_FILE,
)
from chipseeker.search_ui import collect_year_counts, filter_search_results, get_paper_id, highlight_text, required_words_from_query, result_bucket_counts, sort_results
from chipseeker.task_queue import cleanup_task, get_task, submit_arxiv_incremental, submit_embedding_build, submit_nature_incremental, submit_pdf_download
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
from search_runtime import PaperSearcher, get_cache_paths


CURRENT_YEAR = datetime.now().year


def _vx_auth():
    import base64
    import hashlib

    _x = hashlib.sha256(b"MiaoYixuan_ChipSeeker_PRO").hexdigest()
    _y = base64.b64encode(b"guangeofaisa@gmail.com").decode()
    if not _x or not _y:
        raise SystemExit("ERR_LICENSE: Integrity check failed.")


@st.cache_resource(show_spinner=False)
def get_searcher_engine(db_file, model_name, api_key="", scope_key="all", scope_years=()):
    papers_override = None
    if scope_years:
        papers_override = filter_papers_by_years(load_json(db_file, []), scope_years)
    return PaperSearcher(db_file, model_name=model_name, api_key=api_key, papers_override=papers_override, scope_key=scope_key)


def render_taxonomy_matrix(total_papers, db_stats, active_years):
    with st.expander(f"Taxonomy & Library Matrix (Total Records: {total_papers})", expanded=True):
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


def render_task_status(task_id, label, success_message=None, container=st):
    if not task_id:
        return None
    task = get_task(task_id)
    if not task:
        return None

    status = task.get("status")
    message = task.get("message", "")
    progress = float(task.get("progress", 0.0))
    if status in {"queued", "running"}:
        container.info(f"{label}: {message or status}")
        container.progress(progress if progress > 0 else 0.01)
    elif status == "completed":
        if success_message:
            container.success(success_message(task.get("result", {})))
        cleanup_task(task_id)
        return None
    elif status == "failed":
        container.error(f"{label} failed: {task.get('error', 'unknown error')}")
    return task


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


def render_update_manager(source_csv_files):
    st.header("Update Manager")
    st.caption("IEEE uses manual incremental batches. Nature uses automatic incremental updates.")

    registry = load_source_registry(SOURCE_REGISTRY_FILE)
    ieee_sources = list_sources(registry, "ieee")
    nature_sources = list_sources(registry, "nature")
    arxiv_sources = list_sources(registry, "arxiv")

    metric_col1, metric_col2, metric_col3 = st.columns(3)
    metric_col1.metric("IEEE Sources", sum(1 for source in ieee_sources if source.get("enabled")))
    metric_col2.metric("Auto Sources", sum(1 for source in (nature_sources + arxiv_sources) if source.get("enabled")))
    metric_col3.metric("Pending IEEE Batch", 1 if registry.get("pending_ieee_batch") else 0)

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
                        options=["", "nature", "nature-electronics"],
                        index=["", "nature", "nature-electronics"].index(source.get("journal", "")) if source.get("journal", "") in {"", "nature", "nature-electronics"} else 0,
                        format_func=lambda value: {"": "All Nature journals", "nature": "Nature", "nature-electronics": "Nature Electronics"}.get(value, value),
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
                new_journal = st.selectbox("Journal", options=["", "nature", "nature-electronics"], format_func=lambda value: {"": "All Nature journals", "nature": "Nature", "nature-electronics": "Nature Electronics"}.get(value, value))
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
        )
        if task is None and nature_task_id:
            st.session_state.pop(nature_task_key, None)
            st.session_state["csv_state"] = ()
            st.rerun()
        if st.button("Run Nature Incremental Update", type="primary", use_container_width=True):
            if not selected_nature_ids:
                st.warning("Select at least one Nature source with a query.")
            else:
                st.session_state[nature_task_key] = submit_nature_incremental(SOURCE_REGISTRY_FILE, selected_nature_ids, NATURE_UPDATE_DIR)
                st.success("Nature incremental update queued in the background.")

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


def run():
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    _vx_auth()
    migrate_local_data()

    st.set_page_config(page_title="ChipSeeker", layout="wide")
    st.title("ChipSeeker")
    st.markdown(
        """
**Author:** Miao Yixuan | **Email:** [guangeofaisa@gmail.com](mailto:guangeofaisa@gmail.com) | **GitHub:** [https://github.com/Yixuan-Miao](https://github.com/Yixuan-Miao)
"""
    )

    if "citations_fetched" not in st.session_state:
        st.session_state.citations_fetched = False
        st.session_state.citations_map = {}

    app_config = load_app_config((CONFIG_FILE, LEGACY_CONFIG_FILE, EXAMPLE_CONFIG_FILE))
    user_store = UserDataStore(USER_DATA_FILE)
    schema_state = load_json(LOCAL_DATA_STATE_FILE, {})

    def get_user_data(title):
        return user_store.get(title)

    def update_user_data(title, key, value):
        user_store.update(title, key, value)

    source_csv_files = list_source_csv_files(source_root=SOURCE_CSV_DIR, manifest_path=SOURCE_MANIFEST_FILE)
    current_csv_state = build_source_state(source_csv_files)
    if st.session_state.get("csv_state") != current_csv_state:
        with st.spinner("Syncing library..."):
            added_count, updated_count, removed_count, file_summaries = scan_and_import_csvs(
                DB_FILE,
                CACHE_DIR,
                source_root=SOURCE_CSV_DIR,
                manifest_path=SOURCE_MANIFEST_FILE,
            )
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
                st.toast("\n\n".join(msg))
                st.cache_resource.clear()
                time.sleep(1.0)
                st.rerun()

    workspace_view = st.sidebar.radio("Workspace", ["Search", "Update Manager", "Conflict Review"], horizontal=False)
    st.sidebar.caption(f"local_data schema v{schema_state.get('schema_version', '?')}")

    all_papers_in_db = load_json(DB_FILE, [])
    library_years = available_years(all_papers_in_db)
    total_papers, db_stats, active_years = generate_db_stats(all_papers_in_db, analyze_venue)

    if workspace_view == "Update Manager":
        render_update_manager(source_csv_files)
        return

    if workspace_view == "Conflict Review":
        render_conflict_review(source_csv_files)
        return

    render_taxonomy_matrix(total_papers, db_stats, active_years)

    st.sidebar.header("Embedding Engine")
    emb_models = ["voyage-4-large", "voyage-4", "voyage-4-lite", "voyage-context-3", "text-embedding-3-large", "all-MiniLM-L6-v2"]
    selected_emb_model = st.sidebar.selectbox("Model", emb_models, index=emb_models.index(app_config.get("embedding_model", "all-MiniLM-L6-v2")) if app_config.get("embedding_model") in emb_models else 5)
    emb_api_key = ""
    if "voyage" in selected_emb_model or "text-embedding" in selected_emb_model:
        emb_api_key = st.sidebar.text_input("Embedding API Key", value=app_config.get("emb_api_key", ""), type="password")
    scope_mode = st.sidebar.radio(
        "Semantic Coverage",
        ["Latest Year (Recommended)", "Latest 3 Years", "Custom Years", "Full Library"],
        index=0 if total_papers > 10000 else 3,
    )
    selected_scope_years = []
    if scope_mode == "Latest Year (Recommended)" and library_years:
        selected_scope_years = [library_years[0]]
    elif scope_mode == "Latest 3 Years":
        selected_scope_years = library_years[:3]
    elif scope_mode == "Custom Years":
        selected_scope_years = st.sidebar.multiselect("Years To Embed/Search", options=library_years, default=library_years[:1] if library_years else [])
    scope_key = build_scope_key(selected_scope_years)
    scope_text = scope_label(selected_scope_years)
    st.sidebar.caption(f"Semantic scope: {scope_text}")

    st.sidebar.markdown("---")
    st.sidebar.header("LLM API Config")
    preset_options = ["DeepSeek", "SiliconFlow", "Kimi", "Custom OpenAI"]
    current_preset = st.sidebar.selectbox("Provider Preset", preset_options, index=preset_options.index(app_config.get("provider_preset", "DeepSeek")) if app_config.get("provider_preset") in preset_options else 0)
    default_base, default_model = "", ""
    if current_preset == "DeepSeek":
        default_base, default_model = "https://api.deepseek.com", "deepseek-chat"
    elif current_preset == "SiliconFlow":
        default_base, default_model = "https://api.siliconflow.cn/v1", "Qwen/Qwen2.5-7B-Instruct"
    elif current_preset == "Kimi":
        default_base, default_model = "https://api.moonshot.cn/v1", "moonshot-v1-8k"
    else:
        default_base, default_model = app_config.get("llm_base_url", ""), app_config.get("llm_model", "")
    api_key = st.sidebar.text_input("LLM API Key", value=app_config.get("llm_api_key", ""), type="password")
    base_url = st.sidebar.text_input("Base URL", value=default_base)
    model_name = st.sidebar.text_input("Model ID", value=default_model)
    if st.sidebar.button("Save Global Config", use_container_width=True):
        app_config.update({"embedding_model": selected_emb_model, "emb_api_key": emb_api_key, "provider_preset": current_preset, "llm_api_key": api_key, "llm_base_url": base_url, "llm_model": model_name})
        save_json(CONFIG_FILE, app_config)
        st.cache_resource.clear()
        st.sidebar.success("Config saved.")

    cache_file, _ = get_cache_paths(DB_FILE, selected_emb_model, scope_key=scope_key)
    embedding_task_key = f"embedding_task::{selected_emb_model}::{scope_key}"
    embedding_task_id = st.session_state.get(embedding_task_key)
    embedding_ready = os.path.exists(cache_file)
    if not embedding_ready and os.path.exists(DB_FILE):
        if not embedding_task_id:
            st.session_state[embedding_task_key] = submit_embedding_build(DB_FILE, selected_emb_model, emb_api_key, years=selected_scope_years, scope_key=scope_key)
            embedding_task_id = st.session_state[embedding_task_key]
        task = render_task_status(
            embedding_task_id,
            f"Embedding build for {selected_emb_model} ({scope_text})",
            success_message=lambda result: f"Embedding cache ready for {result.get('model_name', selected_emb_model)} on {scope_label(result.get('years', []))}.",
            container=st.sidebar,
        )
        if task is None:
            st.session_state.pop(embedding_task_key, None)
            st.cache_resource.clear()
            embedding_ready = os.path.exists(cache_file)
    elif embedding_task_id:
        task = render_task_status(
            embedding_task_id,
            f"Embedding build for {selected_emb_model} ({scope_text})",
            success_message=lambda result: f"Embedding cache ready for {result.get('model_name', selected_emb_model)} on {scope_label(result.get('years', []))}.",
            container=st.sidebar,
        )
        if task is None:
            st.session_state.pop(embedding_task_key, None)
            st.cache_resource.clear()

    searcher = get_searcher_engine(DB_FILE, selected_emb_model, emb_api_key, scope_key=scope_key, scope_years=tuple(selected_scope_years)) if embedding_ready else None

    with st.sidebar.expander("Background Coverage Builder", expanded=False):
        st.caption("Queue other year ranges in the background so you can keep using the current scope immediately.")
        for state_key, state_value in list(st.session_state.items()):
            if not str(state_key).startswith(f"embedding_task::{selected_emb_model}::"):
                continue
            if state_key == embedding_task_key:
                continue
            task_scope_key = state_key.split("::", 2)[-1]
            task = render_task_status(
                state_value,
                f"Background embedding build ({task_scope_key})",
                success_message=lambda result: f"Background cache ready for {scope_label(result.get('years', []))}.",
                container=st.sidebar,
            )
            if task is None:
                st.session_state.pop(state_key, None)
        background_choice = st.radio(
            "Queue Build",
            ["Latest Year", "Latest 3 Years", "Full Library", "Custom Years"],
            key="background_scope_mode",
        )
        background_years = []
        if background_choice == "Latest Year" and library_years:
            background_years = [library_years[0]]
        elif background_choice == "Latest 3 Years":
            background_years = library_years[:3]
        elif background_choice == "Custom Years":
            background_years = st.multiselect("Background Years", options=library_years, default=library_years[:1] if library_years else [], key="background_years")
        background_scope_key = build_scope_key(background_years)
        background_cache_file, _ = get_cache_paths(DB_FILE, selected_emb_model, scope_key=background_scope_key)
        if st.button("Queue Background Embedding Build", use_container_width=True):
            if background_choice != "Full Library" and not background_years:
                st.sidebar.warning("Select at least one year for background embedding.")
            elif os.path.exists(background_cache_file):
                st.sidebar.info("That background scope is already cached.")
            else:
                bg_task_key = f"embedding_task::{selected_emb_model}::{background_scope_key}"
                st.session_state[bg_task_key] = submit_embedding_build(DB_FILE, selected_emb_model, emb_api_key, years=background_years, scope_key=background_scope_key)
                st.sidebar.success(f"Queued background build for {scope_label(background_years)}.")

    st.sidebar.markdown("---")
    st.sidebar.header("DB Maintenance")
    papers_to_purge = compute_papers_to_purge(all_papers_in_db, db_stats, analyze_venue)
    if "purge_mode" not in st.session_state:
        st.session_state.purge_mode = False
    if st.sidebar.button("Scan & Purge Low-Volume Papers", use_container_width=True):
        st.session_state.purge_mode = not st.session_state.purge_mode
    if st.session_state.purge_mode:
        if not papers_to_purge:
            st.sidebar.success("No low-volume papers found.")
            st.session_state.purge_mode = False
        else:
            with st.sidebar.form("purge_form"):
                options = [f"{paper['title']} [{paper.get('venue', 'Other')}]" for paper in papers_to_purge]
                selected_options = st.multiselect("Select papers to permanently delete:", options=options, default=[])
                if st.form_submit_button("Confirm Delete from CSV & JSON", use_container_width=True):
                    if selected_options:
                        selected_papers = [papers_to_purge[options.index(option)] for option in selected_options]
                        purge_result = purge_papers_from_sources(selected_papers, source_csv_files, BACKUP_ROOT_DIR, CACHE_DIR, build_paper_from_row, paper_identity_key)
                        if purge_result["backup_dir"]:
                            st.sidebar.info(f"Backup saved to {purge_result['backup_dir']}")
                        st.session_state.purge_mode = False
                        st.session_state["csv_state"] = ()
                        st.rerun()
                    else:
                        st.warning("No papers selected.")

    st.sidebar.markdown("---")
    with st.sidebar.expander("Nature Grabber"):
        ng_query = st.text_input("Search Query", key="ng_query", placeholder="e.g. cryogenic CMOS qubit readout")
        ng_journal = st.selectbox("Journal Filter", ["", "nature", "nature-electronics"], format_func=lambda value: {"": "All Nature journals", "nature": "Nature", "nature-electronics": "Nature Electronics"}.get(value, value), key="ng_journal")
        ng_year_from = st.number_input("Start Year", min_value=1990, max_value=CURRENT_YEAR, value=2015, step=1, key="ng_year_from")
        ng_max_pages = st.number_input("Max Pages", min_value=1, max_value=50, value=5, step=1, key="ng_max_pages")
        ng_sleep = st.number_input("Request Delay (s)", min_value=0.0, max_value=10.0, value=1.0, step=0.5, key="ng_sleep")
        ng_output = st.text_input("Output CSV", value=f"{slugify_filename(ng_query or 'nature_search')}.csv", key="ng_output")
        if st.button("Run Nature Grabber", use_container_width=True):
            if not ng_query.strip():
                st.sidebar.warning("Nature search query is required.")
            else:
                from Nature_Grabber import grab_nature

                output_name = ng_output if ng_output.lower().endswith(".csv") else f"{ng_output}.csv"
                output_file = output_name if os.path.isabs(output_name) else os.path.join(SOURCE_CSV_DIR, "manual", output_name)
                with st.spinner("Fetching Nature metadata..."):
                    grab_nature(query=ng_query, output_file=output_file, journal=ng_journal, year_from=int(ng_year_from), max_pages=int(ng_max_pages), sleep_seconds=float(ng_sleep))
                st.session_state["csv_state"] = ()
                st.sidebar.success(f"Saved to {output_file}")
                st.rerun()

    st.markdown("---")
    st.markdown("### Keyword Generator")
    user_idea = st.text_input("Describe your topic in any language (press Enter to generate keywords)...", key="user_idea_input")
    if user_idea and user_idea != st.session_state.get("last_idea"):
        if not api_key:
            st.error("Please configure the LLM API key first.")
        else:
            with st.spinner("Generating..."):
                st.session_state.kw_result = generate_search_keywords(user_idea, api_key, base_url, model_name)
                st.session_state.last_idea = user_idea
    if st.session_state.get("kw_result"):
        st.info(f"Suggested Keywords: `{st.session_state.kw_result}`")

    st.markdown("---")
    st.markdown("### Hybrid Search Engine")
    st.caption(f"Semantic search currently uses embedding coverage: {scope_text}")
    with st.expander("Metadata Pre-Filters", expanded=False):
        filter_col1, filter_col2 = st.columns(2)
        with filter_col1:
            unique_venues = sorted({analyze_venue(paper.get("venue", ""))["n"] for paper in all_papers_in_db if paper.get("venue")})
            unique_venues = [venue for venue in unique_venues if venue != "Other"]
            selected_ui_venues = st.multiselect("Filter by Unified Venue", unique_venues)
        with filter_col2:
            if active_years:
                min_year, max_year = min(active_years), max(active_years)
                if min_year == max_year:
                    min_year -= 1
                selected_years = st.slider("Filter by Year", min_year, max_year, (min_year, max_year))
            else:
                selected_years = (2000, CURRENT_YEAR)

    col_s1, col_s2, col_s3 = st.columns([3, 2, 1])
    with col_s1:
        search_query = st.text_input("1. Semantic Query (Optional)", placeholder="Leave blank for pure keyword/filter search")
    with col_s2:
        must_have = st.text_input("2. Exact Match (AND/OR logic)", help="Space = OR. Comma or & = AND.")
    with col_s3:
        top_k_val = st.number_input("3. Search Depth", min_value=50, max_value=2000, value=50, step=50)

    trigger_search = bool(search_query or selected_ui_venues or must_have)
    if trigger_search:
        query_state_key = f"{search_query}_must{must_have}_top{top_k_val}_{selected_emb_model}_v{selected_ui_venues}_y{selected_years}_csv{hash(current_csv_state)}"
        if st.session_state.get("current_query") != query_state_key:
            st.session_state.citations_fetched = False
            st.session_state.citations_map = {}
            with st.spinner("Scanning library..."):
                if search_query and not searcher:
                    st.warning("Embedding cache is still building in the background. You can use metadata filters now and run semantic search after the task completes.")
                    raw_hits = []
                else:
                    raw_hits = searcher.search(query=search_query, top_k=top_k_val) if search_query else [{"similarity": 1.0, "paper": paper} for paper in all_papers_in_db]
                filtered_results = filter_search_results(raw_hits, selected_years, selected_ui_venues, must_have, analyze_venue, extract_year)
                st.session_state.raw_results = filtered_results
                st.session_state.initial_count = len(raw_hits)
                st.session_state.current_query = query_state_key
                for item in filtered_results:
                    if item["similarity"] >= 0.25 and search_query:
                        title = item["paper"].get("title")
                        user_data = get_user_data(title)
                        if search_query not in user_data["matched_queries"]:
                            user_data["matched_queries"].append(search_query)
                            update_user_data(title, "matched_queries", user_data["matched_queries"])
                for key in list(st.session_state.keys()):
                    if key.startswith("chk_"):
                        del st.session_state[key]

    results = st.session_state.get("raw_results", [])
    initial_count = st.session_state.get("initial_count", 0)
    required_words_hl = required_words_from_query(must_have)
    if trigger_search:
        if not results:
            st.warning(f"{initial_count} records scanned, but all were eliminated by your filters.")
            st.stop()
        bucket_counts = result_bucket_counts(results, search_query)
        st.success(f"Extracted {len(results)} matches. Rare/All: {bucket_counts['rare']} | Perfect: {bucket_counts['perfect']} | Valuable: {bucket_counts['valuable']} | Relevant: {bucket_counts['relevant']}")
        year_counts = collect_year_counts(results, extract_year)
        if year_counts:
            with st.expander("Analytics: Publication Trend", expanded=False):
                st.bar_chart(year_counts)

    st.markdown("---")
    col_sort, col_batch, col_cite = st.columns([1.5, 2.5, 1])
    with col_sort:
        sort_option = st.radio("Sort By", ["Relevance", "Year (Newest)", "Comprehensive Score"], horizontal=True)
    with col_cite:
        default_fetch_num = sum(1 for item in results if item["similarity"] >= 0.40 or not search_query)
        if default_fetch_num == 0 and results:
            default_fetch_num = min(10, len(results))
        fetch_limit = st.number_input("Fetch Count", min_value=0, max_value=max(1, len(results)), value=min(default_fetch_num, len(results)), step=10)
        if st.button("Fetch & Update Scores", use_container_width=True):
            with st.spinner(f"Batch fetching citations for top {fetch_limit} papers..."):
                dois_to_fetch = [result["paper"].get("doi") for result in results if result["paper"].get("doi")][:fetch_limit]
                st.session_state.citations_map = get_batch_citations(dois_to_fetch)
                st.session_state.citations_fetched = True
                st.rerun()

    results = sort_results(results, sort_option, search_query, st.session_state.citations_map, st.session_state.citations_fetched, analyze_venue, extract_year, CURRENT_YEAR)
    selected_papers = []
    high_value_papers_for_report = []

    with col_batch:
        rel_threshold = st.slider("Select Relevance >=", 0.0, 1.0, 0.40, 0.05)
        b1, b2, b3, b4, b5 = st.columns(5)

        def do_batch_select(mode, val=None):
            for idx, item in enumerate(results):
                paper = item["paper"]
                chk_key = f"chk_{idx}_{get_paper_id(paper)}"
                similarity = item["similarity"]
                if mode == "threshold" and (similarity >= val or not search_query):
                    st.session_state[chk_key] = True
                elif mode == "rare" and (similarity >= 0.60 or not search_query):
                    st.session_state[chk_key] = True
                elif mode == "perfect" and (similarity >= 0.40 or not search_query):
                    st.session_state[chk_key] = True
                elif mode == "valuable" and 0.25 <= similarity < 0.40 and search_query:
                    st.session_state[chk_key] = True
                elif mode == "deselect":
                    st.session_state[chk_key] = False

        with b1:
            st.button(f">= {rel_threshold:.2f}", on_click=do_batch_select, args=("threshold", rel_threshold), use_container_width=True)
        with b2:
            st.button("Rare", on_click=do_batch_select, args=("rare",), use_container_width=True)
        with b3:
            st.button("Perfect", on_click=do_batch_select, args=("perfect",), use_container_width=True)
        with b4:
            st.button("Valuable", on_click=do_batch_select, args=("valuable",), use_container_width=True)
        with b5:
            st.button("Clear", on_click=do_batch_select, args=("deselect",), use_container_width=True)

    for idx, item in enumerate(results):
        paper = item["paper"]
        similarity = item["similarity"]
        title = paper.get("title", "Untitled")
        venue = paper.get("venue", "Unknown Venue")
        year = paper.get("year", "N/A")
        doi = paper.get("doi", "")
        abstract = paper.get("abstract", "No Abstract")
        author_str = f"{paper.get('first_author', 'Unknown')} ... {paper.get('last_author', 'Unknown')}"
        chk_key = f"chk_{idx}_{get_paper_id(paper)}"
        user_data = get_user_data(title)
        venue_data = analyze_venue(venue)
        base_score = venue_data["s"]
        domain_color = DOMAIN_COLORS.get(venue_data["d"][0], "#757575")
        tier_color = TIER_COLORS.get(venue_data["t"], "#9E9E9E")
        year_value = extract_year(year)
        year_bonus = max(0, 10 - (CURRENT_YEAR - year_value)) if year_value > 1900 and (CURRENT_YEAR - year_value) < 10 else (10 if year_value > 1900 and (CURRENT_YEAR - year_value) <= 0 else 0)
        if similarity >= 0.60 or not search_query:
            color, badge = "#9C27B0", "Rare Match"
        elif similarity >= 0.40:
            color, badge = "#00C853", "Perfect Match"
        elif similarity >= 0.25:
            color, badge = "#2196F3", "Highly Valuable"
        elif similarity >= 0.15:
            color, badge = "#FF9800", "Relevant"
        else:
            color, badge = "#9E9E9E", "Noise"
        if similarity >= 0.25 or not search_query:
            high_value_papers_for_report.append(paper)
        citations = st.session_state.citations_map.get(doi.upper(), 0) if st.session_state.citations_fetched else 0
        citation_bonus = min(15, math.log10(citations + 1) * 6) if citations > 0 else 0
        final_score = item.get("comp_score", base_score + year_bonus + citation_bonus)
        st.markdown(f"**{badge}** | Relevance: `{similarity * 100:.1f}%` | Score: `{final_score:.1f}`")
        c1, c2, c3 = st.columns([6, 2, 2])
        with c1:
            cc1, cc2 = st.columns([0.5, 9.5])
            with cc1:
                checked = st.checkbox(" ", key=chk_key, label_visibility="collapsed")
            with cc2:
                st.markdown(f"<span style='font-size:1.1em; font-weight:bold; color:{color};'>{highlight_text(title, required_words_hl)}</span>", unsafe_allow_html=True)
            st.markdown(f"**Authors:** {highlight_text(author_str, required_words_hl)}", unsafe_allow_html=True)
            st.markdown(f"**Venue:** <span style='color:{domain_color}; font-weight:bold;'>{highlight_text(get_venue_display_str(venue_data), required_words_hl)}</span> ({year}) | **Tier:** <span style='background-color:{tier_color}; color:white; padding:2px 6px; border-radius:4px;'>{venue_data['t']}</span>", unsafe_allow_html=True)
            if user_data["matched_queries"]:
                st.markdown("**Matched:** " + " ".join([f"`{query}`" for query in user_data["matched_queries"]]))
        with c2:
            st.markdown(f"**Reads:** `{user_data['open_count']}`")
            st.markdown(f"**Cites:** `{citations}`")
        with c3:
            new_rating = st.selectbox("Rating", ["Unrated", "Masterpiece", "Solid", "Average", "Marginal", "Poor"], index=["Unrated", "Masterpiece", "Solid", "Average", "Marginal", "Poor"].index(user_data["rating"] if user_data["rating"] in ["Unrated", "Masterpiece", "Solid", "Average", "Marginal", "Poor"] else "Unrated"), key=f"rate_{chk_key}", label_visibility="collapsed")
            if new_rating != user_data["rating"]:
                update_user_data(title, "rating", new_rating)
            new_comments = st.text_input("Notes", value=user_data["comments"], key=f"comment_{chk_key}", placeholder="Take notes...")
            if new_comments != user_data["comments"]:
                update_user_data(title, "comments", new_comments)
        if checked:
            selected_papers.append(paper)
        with st.expander("Read Abstract"):
            st.markdown(highlight_text(abstract, required_words_hl), unsafe_allow_html=True)
        if similarity >= 0.25 or not search_query:
            with st.expander("AI Deep Dive"):
                if st.button("Analyze with LLM", key=f"ai_btn_{chk_key}"):
                    if not api_key:
                        st.error("API key missing.")
                    else:
                        with st.spinner("Analyzing..."):
                            st.markdown(analyze_with_llm(title, abstract, search_query or "Summarize", api_key, base_url, model_name))
        st.markdown("---")

    st.sidebar.markdown("---")
    if high_value_papers_for_report and st.sidebar.button("Generate State-of-the-Art Review", type="primary", use_container_width=True):
        if not api_key:
            st.sidebar.error("API key missing.")
        else:
            with st.spinner("LLM is reading top papers..."):
                st.session_state.mega_report = generate_global_report_with_llm(high_value_papers_for_report, search_query or "General Review", api_key, base_url, model_name)
    if "mega_report" in st.session_state:
        st.markdown("## AI Global Review Report")
        st.markdown(st.session_state.mega_report)

    st.sidebar.markdown("---")
    st.sidebar.header(f"Selected Papers ({len(selected_papers)})")
    if st.sidebar.button("Open Selected PDFs", use_container_width=True):
        success_count = 0
        for paper in selected_papers:
            title = paper.get("title")
            user_data = get_user_data(title)
            update_user_data(title, "open_count", user_data["open_count"] + 1)
            url = paper.get("pdf_link") or (f"https://doi.org/{paper['doi']}" if paper.get("doi") else "")
            if url:
                webbrowser.open_new_tab(url)
                success_count += 1
        st.sidebar.info(f"Opened {success_count} tabs.")

    st.sidebar.markdown("---")
    save_dir = st.sidebar.text_input("Local Save Folder", value=DOWNLOAD_DIR, help="The local directory where PDFs will be saved.")
    pdf_task_key = "pdf_download_task"
    pdf_task_id = st.session_state.get(pdf_task_key)
    task = render_task_status(
        pdf_task_id,
        "PDF download queue",
        success_message=lambda result: f"PDF download finished. Success: {result.get('success', 0)}, Failed: {result.get('failed', 0)}",
        container=st.sidebar,
    )
    if task is None and pdf_task_id:
        st.session_state.pop(pdf_task_key, None)
    if st.sidebar.button("Batch Download Selected PDFs", type="primary", use_container_width=True):
        if not selected_papers:
            st.sidebar.warning("No papers selected.")
        else:
            st.session_state[pdf_task_key] = submit_pdf_download(selected_papers, save_dir)
            st.sidebar.success("PDF download task queued in the background.")

    if st.sidebar.button("Export to NotebookLM", type="primary", use_container_width=True):
        export_content = build_notebooklm_export(selected_papers, search_query or "Filtered Subset", get_user_data)
        write_text_file(NOTEBOOKLM_EXPORT_FILE, export_content)
        st.sidebar.success(f"Markdown generated: {NOTEBOOKLM_EXPORT_FILE}")

    if selected_papers:
        st.sidebar.markdown(generate_csv_link(build_csv_rows(selected_papers)), unsafe_allow_html=True)
        st.sidebar.markdown("<br>", unsafe_allow_html=True)
        st.sidebar.download_button(label="Export IEEE BibTeX", data=build_bibtex(selected_papers), file_name="references.bib", mime="text/plain", use_container_width=True)
