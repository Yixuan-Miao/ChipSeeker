import json
from pathlib import Path


NOTICE_FILE = Path(__file__).with_name("update_notices.json")

FALLBACK_NOTICES = [
    {
        "date": "2026-05-15",
        "title": "Coverage audit: current library includes ISSCC 2026, IEEE journal 2026 Jan-Mar issues plus Early Access. Next refresh target: IEEE Apr-May and Nature/NE Mar-May.",
        "title_zh": "覆盖检查：当前库已包含 ISSCC 2026、IEEE 期刊 2026 年 1-3 月正刊和 Early Access。下一次补充目标：IEEE 4-5 月、Nature/NE 3-5 月。",
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
