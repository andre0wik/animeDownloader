import json
import datetime

from ..config import HISTORY_FILE


def load_history() -> list[dict]:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def save_history(base_url: str, anime_id: str, slug: str, title: str) -> None:
    history = [h for h in load_history() if h.get("anime_id") != anime_id]
    history.insert(0, {
        "base_url": base_url,
        "anime_id": anime_id,
        "slug":     slug,
        "title":    title,
        "last_used": datetime.date.today().isoformat(),
    })
    HISTORY_FILE.write_text(
        json.dumps(history[:20], ensure_ascii=False, indent=2), encoding="utf-8"
    )
