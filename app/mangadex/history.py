import json
import datetime

from ..config import MANGA_HISTORY_FILE


def load_manga_history() -> list[dict]:
    if MANGA_HISTORY_FILE.exists():
        try:
            return json.loads(MANGA_HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def save_manga_history(
    manga_id: str, title: str, lang: str, platform: str = "mangadex"
) -> None:
    history = [
        h for h in load_manga_history()
        if not (h.get("manga_id") == manga_id and h.get("platform", "mangadex") == platform)
    ]
    history.insert(0, {
        "manga_id":  manga_id,
        "title":     title,
        "lang":      lang,
        "platform":  platform,
        "last_used": datetime.date.today().isoformat(),
    })
    MANGA_HISTORY_FILE.write_text(
        json.dumps(history[:50], ensure_ascii=False, indent=2), encoding="utf-8"
    )
