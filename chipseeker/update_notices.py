import json
from pathlib import Path


NOTICE_FILE = Path(__file__).with_name("update_notices.json")

FALLBACK_NOTICES = [
    {
        "date": "2026-05-15",
        "title": "Library update: ISSCC 2026 and early-2026 IEEE journal papers are now included.",
        "title_zh": "文献库更新：已加入 ISSCC 2026 与 2026 年初 IEEE 期刊新论文。",
    }
]


def load_update_notices(limit=3):
    try:
        notices = json.loads(NOTICE_FILE.read_text(encoding="utf-8"))
    except Exception:
        notices = FALLBACK_NOTICES
    if not isinstance(notices, list):
        notices = FALLBACK_NOTICES
    clean = []
    for item in notices:
        if not isinstance(item, dict):
            continue
        date = str(item.get("date", "")).strip()
        title = str(item.get("title", "")).strip()
        title_zh = str(item.get("title_zh", "")).strip()
        if title or title_zh:
            clean.append({"date": date, "title": title, "title_zh": title_zh})
    return clean[:limit]
