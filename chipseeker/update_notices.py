import json
from pathlib import Path


NOTICE_FILE = Path(__file__).with_name("update_notices.json")

FALLBACK_NOTICES = [
    {
        "date": "2026-07-19",
        "title": "IEEE IC library: RFIC 2026 papers are live.",
        "title_zh": "IEEE 集成电路库：RFIC 2026 已更新。",
    },
    {
        "date": "2026-07-19",
        "title": "IEEE IC library: IMS 2026 papers are live.",
        "title_zh": "IEEE 集成电路库：IMS 2026 已更新。",
    },
    {
        "date": "2026-05-16",
        "title": "Library update: JSSC May 2026 and CICC 2026 papers are now in the update pipeline.",
        "title_zh": "文献库更新：JSSC 2026 五月与 CICC 2026 论文已进入更新流程。",
    }
]


def load_update_notices(limit=20):
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
