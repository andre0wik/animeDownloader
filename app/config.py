import json
from pathlib import Path

IMPERSONATE   = "chrome124"
DEFAULT_BASE  = "https://www.animeunity.so"
MANGADEX_API  = "https://api.mangadex.org"

_BASE_DIR       = Path(__file__).parent.parent
FFMPEG_DIR      = _BASE_DIR / "ffmpeg"
FFMPEG_EXE      = FFMPEG_DIR / "ffmpeg.exe"
FFPROBE_EXE     = FFMPEG_DIR / "ffprobe.exe"
HISTORY_FILE       = _BASE_DIR / "history.json"
MANGA_HISTORY_FILE = _BASE_DIR / "manga_history.json"
SETTINGS_FILE   = _BASE_DIR / "settings.json"
SYNC_QUEUE_FILE = _BASE_DIR / "sync_queue.json"

_VIDEO_EXT = {".mp4", ".mkv", ".avi", ".webm"}
_TEMP_EXT  = {".part", ".ytdl", ".tmp"}

_DEFAULT_DOWNLOAD_DIR = str(_BASE_DIR / "downloads")

_SETTING_DEFAULTS: dict = {
    "download_dir":    _DEFAULT_DOWNLOAD_DIR,
    "ssh_host":        "gengar@192.168.78.172",
    "ssh_remote_base": "/home/gengar/qbit/filesRepo/tvseries",
    "animeunity_base": "https://www.animeunity.so",
    "max_concurrent":  2,
    "auto_sync":       False,
    "cbz_to_pdf":      False,
    "toonily_user":    "",
    "toonily_pass":    "",
    "zlib_email":      "",
    "zlib_password":   "",
}


def load_settings() -> dict:
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return {**_SETTING_DEFAULTS, **{k: v for k, v in data.items() if k in _SETTING_DEFAULTS}}
    except Exception:
        return dict(_SETTING_DEFAULTS)


def save_settings(cfg: dict) -> None:
    SETTINGS_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


_CFG: dict = load_settings()


def _anime_dl_dir() -> Path:
    return Path(_CFG["download_dir"]) / "AnimeUnity"


def _manga_dl_dir() -> Path:
    return Path(_CFG["download_dir"]) / "MangaDex"


def _ebook_dl_dir() -> Path:
    return Path(_CFG["download_dir"]) / "Ebook"
