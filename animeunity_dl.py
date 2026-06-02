#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "yt-dlp",
#     "curl-cffi",
#     "playwright",
#     "rich",
#     "textual",
# ]
# ///

"""
Downloader + sync per AnimeUnity (.so / .to / .tv).

Subcomandi:
  download  Scarica episodi da AnimeUnity (default)
  sync      Verifica e copia gli episodi mancanti su un server SSH

Esempi:
  uv run animeunity_dl.py download https://www.animeunity.so/anime/390-dragon-ball-super-ita 1 10
  uv run animeunity_dl.py sync --local "D:/downloader/Dragon Ball Super Ita"
"""

import re
import sys
import json
import uuid
import time
import html as html_module
import subprocess
import argparse
import zipfile
import datetime
import contextlib
import urllib.request
from dataclasses import dataclass
from pathlib    import Path

from curl_cffi import requests

IMPERSONATE  = "chrome124"
DEFAULT_BASE = "https://www.animeunity.so"

# ffmpeg/ffprobe portatili scaricati nella stessa cartella dello script
FFMPEG_DIR   = Path(__file__).parent / "ffmpeg"
FFMPEG_EXE   = FFMPEG_DIR / "ffmpeg.exe"
FFPROBE_EXE  = FFMPEG_DIR / "ffprobe.exe"
HISTORY_FILE  = Path(__file__).parent / "history.json"
SETTINGS_FILE = Path(__file__).parent / "settings.json"

_SETTING_DEFAULTS: dict = {
    "download_dir":    "D:/downloader",
    "manga_dir":       "D:/downloader/manga",
    "ssh_host":        "gengar@192.168.78.172",
    "ssh_remote_base": "/home/gengar/qbit/filesRepo/tvseries",
    "animeunity_base": "https://www.animeunity.so",
    "max_concurrent":  2,
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

_VIDEO_EXT   = {".mp4", ".mkv", ".avi", ".webm"}
_TEMP_EXT    = {".part", ".ytdl", ".tmp"}

# ── setup ffmpeg/ffprobe ──────────────────────────────────────────────────────

def _ensure_ffmpeg() -> str | None:
    """
    Restituisce il percorso di ffmpeg (e scarica anche ffprobe).
    Se non è nel PATH né in locale, scarica il build ufficiale yt-dlp.
    """
    try:
        r = subprocess.run(["ffmpeg", "-version"], capture_output=True)
        if r.returncode == 0:
            return "ffmpeg"
    except FileNotFoundError:
        pass

    if FFMPEG_EXE.exists():
        return str(FFMPEG_EXE)

    print("  ffmpeg non trovato — scarico build portatile (~70 MB)...")
    FFMPEG_DIR.mkdir(exist_ok=True)

    zip_url  = (
        "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/"
        "latest/ffmpeg-master-latest-win64-gpl.zip"
    )
    zip_path = FFMPEG_DIR / "ffmpeg.zip"

    try:
        urllib.request.urlretrieve(zip_url, zip_path)
        with zipfile.ZipFile(zip_path) as zf:
            for name in zf.namelist():
                if name.endswith("/ffmpeg.exe"):
                    FFMPEG_EXE.write_bytes(zf.read(name))
                elif name.endswith("/ffprobe.exe"):
                    FFPROBE_EXE.write_bytes(zf.read(name))
        zip_path.unlink(missing_ok=True)
        print(f"  ffmpeg/ffprobe installati in {FFMPEG_DIR}")
        return str(FFMPEG_EXE)
    except Exception as e:
        print(f"  [WARN] Download ffmpeg fallito: {e}")
        print("  Installa ffmpeg manualmente: winget install Gyan.FFmpeg")
        return None


def _ffprobe() -> str | None:
    """Restituisce il percorso di ffprobe, o None se non disponibile."""
    try:
        r = subprocess.run(["ffprobe", "-version"], capture_output=True)
        if r.returncode == 0:
            return "ffprobe"
    except FileNotFoundError:
        pass
    return str(FFPROBE_EXE) if FFPROBE_EXE.exists() else None


def _is_complete(path: Path) -> bool:
    """
    True se il file video è completo e riproducibile.
    Usa ffprobe per verificare la durata; fallback su dimensione (>10 MB).
    """
    if not path.exists():
        return False
    size = path.stat().st_size
    if size < 1_000_000:          # < 1 MB → sicuramente parziale
        return False

    probe = _ffprobe()
    if not probe:
        return size > 10_000_000  # fallback grezzo

    try:
        r = subprocess.run(
            [probe, "-v", "error",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1",
             str(path)],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0 and r.stdout.strip():
            return float(r.stdout.strip()) > 0
    except (FileNotFoundError, ValueError, subprocess.TimeoutExpired):
        pass
    return False

# ── helpers ───────────────────────────────────────────────────────────────────

def unescape(s: str) -> str:
    prev = ""
    while prev != s:
        prev = s
        s = html_module.unescape(s)
    return s.replace("\\/", "/")

# ── parsing URL ───────────────────────────────────────────────────────────────

def parse_anime_url(url: str) -> tuple[str, str, str]:
    m = re.search(r"(https://(?:www\.)?animeunity\.\w+)/anime/(\d+)-([^/?#\s]+)", url)
    if not m:
        sys.exit(
            f"[ERRORE] URL non riconosciuta: {url}\n"
            "Formato atteso: https://www.animeunity.so/anime/<ID>-<nome>"
        )
    return m.group(1), m.group(2), m.group(3)

# ── lista episodi ─────────────────────────────────────────────────────────────

def fetch_episodes(base_url: str, anime_id: str, start: int, end: int) -> list[dict]:
    """
    Recupera episodi paginando in chunk da 120 (limite API AnimeUnity).
    Supporta range arbitrariamente grandi (es. 1–9999 per "tutti").
    """
    API_CHUNK = 120
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "it-IT,it;q=0.9",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{base_url}/",
    }
    all_eps: list[dict] = []
    pos = start

    while pos <= end:
        batch_end = min(pos + API_CHUNK - 1, end)
        params = {"start_range": pos, "end_range": batch_end}
        try:
            r = requests.get(
                f"{base_url}/info_api/{anime_id}/1",
                headers=headers, params=params,
                impersonate=IMPERSONATE, timeout=20,
            )
            r.raise_for_status()
        except Exception as e:
            sys.exit(f"[ERRORE] Lista episodi non ottenibile: {e}")

        eps = r.json().get("episodes", [])
        if not eps:
            break                    # nessun episodio → fine serie
        all_eps.extend(eps)
        if len(eps) < API_CHUNK:
            break                    # batch incompleto → ultima pagina
        pos = batch_end + 1

    return all_eps

# ── step 1: embed URL dalla pagina AnimeUnity ─────────────────────────────────

def get_embed_url(episode_page_url: str, base_url: str) -> str | None:
    headers = {
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "it-IT,it;q=0.9",
        "Referer": f"{base_url}/",
    }
    try:
        r = requests.get(episode_page_url, headers=headers,
                         impersonate=IMPERSONATE, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"  [WARN] Fetch pagina episodio: {e}")
        return None

    text = r.text

    for pattern in [
        r':?embed=["\']([^"\']+)["\']',
        r'"embed"\s*:\s*"([^"]+)"',
        r'(https://vixcloud\.co/embed/[^\s"\'<\\]+)',
    ]:
        m = re.search(pattern, text)
        if m:
            return unescape(m.group(1))

    # __NUXT_DATA__ block
    m = re.search(
        r'<script[^>]+(?:id=["\']__NUXT_DATA__["\']|type=["\']application/json["\'])[^>]*>'
        r'(.*?)</script>', text, re.DOTALL
    )
    if m:
        m2 = re.search(r'https://vixcloud\.co/embed/[^"\'\\<\s]+', m.group(1))
        if m2:
            return unescape(m2.group(0))

    return None

# ── step 2: video URL via Playwright (intercetta la richiesta m3u8) ──────────

def _ensure_playwright_chromium() -> bool:
    """Installa Chromium la prima volta che serve."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            b.close()
        return True
    except Exception:
        print("  Prima installazione Chromium (una tantum, ~150 MB)...")
        try:
            subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                check=True, timeout=300,
            )
            return True
        except Exception as e:
            print(f"  [ERRORE] playwright install chromium: {e}")
            return False


def get_video_url(embed_url: str, animeunity_base: str) -> str | None:
    """
    Lancia Chromium headless, naviga sull'embed Vixcloud
    e intercetta la prima richiesta m3u8.
    """
    if not _ensure_playwright_chromium():
        return None

    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    found: list[str] = []

    def on_request(req):
        if found:
            return
        url = req.url
        if "vixcloud.co" in url and ("m3u8" in url or "/playlist/" in url):
            found.append(url)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            extra_http_headers={
                "Referer": f"{animeunity_base}/",
                "Accept-Language": "it-IT,it;q=0.9",
            }
        )
        page = ctx.new_page()
        page.on("request", on_request)

        try:
            page.goto(embed_url, wait_until="domcontentloaded", timeout=30_000)
            # Aspetta che il player carichi e faccia la richiesta m3u8
            for _ in range(20):           # max 10 secondi
                if found:
                    break
                page.wait_for_timeout(500)
        except PWTimeout:
            pass
        except Exception as e:
            print(f"  [WARN] Playwright: {e}")
        finally:
            ctx.close()
            browser.close()

    return found[0] if found else None

# ── download ──────────────────────────────────────────────────────────────────

def download(
    video_url: str,
    out_dir: Path,
    ep_num: int | str,
    title: str,
    animeunity_base: str,
    extra_args: list[str],
    log_fd=None,
) -> bool:
    ep_tag   = f"{title} - Ep{str(ep_num).zfill(3)}"
    out_file = str(out_dir / f"{ep_tag}.%(ext)s")
    ffmpeg   = _ensure_ffmpeg()

    # Controlla file già presenti
    has_part = False
    for existing in out_dir.glob(f"{ep_tag}.*"):
        ext = existing.suffix.lower()
        if ext in _VIDEO_EXT:
            mb = existing.stat().st_size // 1_048_576
            if _is_complete(existing):
                print(f"  Già presente e completo ({mb} MB) — skip")
                return True
            else:
                print(f"  File parziale ({mb} MB) — cancello e riscarico")
                existing.unlink()
        elif ext in _TEMP_EXT:
            # .part = download interrotto: yt-dlp lo usa per riprendere
            mb = existing.stat().st_size // 1_048_576
            print(f"  File .part trovato ({mb} MB) — yt-dlp riprende da qui")
            has_part = True

    cmd = ["yt-dlp", "--output", out_file, "--no-playlist"]
    if ffmpeg:
        cmd += ["--ffmpeg-location", ffmpeg]
    cmd += [
        "--continue",
        "--merge-output-format", "mp4",
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
        "--concurrent-fragments", "4",
        "--retries", "5",
        "--fragment-retries", "5",
        "--add-header", f"Referer:{animeunity_base}/",
        "--add-header", f"Origin:{animeunity_base}",
    ] + extra_args + [video_url]

    if log_fd is not None:
        cmd.insert(-1, "--newline")   # one progress line per update in the log
    print(f"  yt-dlp → {video_url[:90]}{'…' if len(video_url) > 90 else ''}")
    sp_kw = {"stdout": log_fd, "stderr": log_fd} if log_fd is not None else {}
    return subprocess.run(cmd, **sp_kw).returncode == 0

# ── episodi locali completi ───────────────────────────────────────────────────

def local_complete_eps(out_dir: Path, title: str) -> set[int]:
    """Restituisce i numeri degli episodi già scaricati e completi."""
    pat = re.compile(r" - Ep(\d+)\.", re.IGNORECASE)
    found = set()
    for f in out_dir.glob("*.*"):
        if f.suffix.lower() not in _VIDEO_EXT:
            continue
        m = pat.search(f.name)
        if m and _is_complete(f):
            found.add(int(m.group(1)))
    return found

# ── loop download episodi (riusato da download e missing) ─────────────────────

def run_episode_list(
    episodes: list[dict],
    base_url: str,
    anime_id: str,
    slug: str,
    title: str,
    out_dir: Path,
    extra_args: list[str],
) -> None:
    ep_base = f"{base_url}/anime/{anime_id}-{slug}"
    ok = fail = skip = 0
    failed_eps: list = []

    for ep in episodes:
        ep_num_raw = str(ep.get("number", ""))
        ep_id      = ep.get("id")
        if not ep_id:
            skip += 1
            continue

        ep_num = int(ep_num_raw) if ep_num_raw.isdigit() else ep_num_raw
        ep_url = f"{ep_base}/{ep_id}"

        print(f"\n{'='*64}")
        print(f"  Episodio {ep_num}")
        print(f"{'='*64}")

        print("  [1/2] Embed URL da AnimeUnity...")
        embed_url = get_embed_url(ep_url, base_url)
        if not embed_url:
            print(f"  [ERRORE] Embed URL non trovata. Pagina: {ep_url}")
            fail += 1; failed_eps.append(ep_num); continue
        print(f"  Embed : {embed_url[:80]}…")

        print("  [2/2] Video URL da Vixcloud (Playwright)...")
        video_url = get_video_url(embed_url, base_url)
        if not video_url:
            print("  [ERRORE] m3u8 non intercettata. Episodio saltato.")
            fail += 1; failed_eps.append(ep_num); continue
        print(f"  Video : {video_url[:80]}…")

        result = download(video_url, out_dir, ep_num, title, base_url, extra_args)
        if result:
            ok += 1
        else:
            fail += 1; failed_eps.append(ep_num)

    print(f"\n{'='*64}")
    print(f"Completato: {ok} OK  |  {fail} falliti  |  {skip} saltati")
    if failed_eps:
        print(f"Episodi falliti: {failed_eps}")
    print(f"File in: {out_dir}")


def _download_one_episode(
    episode: dict,
    base_url: str, anime_id: str, slug: str,
    title: str, out_dir: Path, extra_args: list[str],
    log_fd=None,
) -> bool:
    """Single-episode download used by the background queue.
    When log_fd is given all output (print + subprocess) goes there."""
    ep_num_raw = str(episode.get("number", "?"))
    ep_id      = episode.get("id")
    if not ep_id:
        return False

    ep_num = int(ep_num_raw) if ep_num_raw.isdigit() else ep_num_raw
    ep_url = f"{base_url}/anime/{anime_id}-{slug}/{ep_id}"

    with contextlib.ExitStack() as stack:
        if log_fd is not None:
            stack.enter_context(contextlib.redirect_stdout(log_fd))
            stack.enter_context(contextlib.redirect_stderr(log_fd))

        print(f"\n{'='*60}\n  Ep {ep_num}  -  {title}\n{'='*60}")

        embed_url = get_embed_url(ep_url, base_url)
        if not embed_url:
            print(f"  [ERRORE] Embed non trovata: {ep_url}")
            return False

        video_url = get_video_url(embed_url, base_url)
        if not video_url:
            print("  [ERRORE] m3u8 non intercettata")
            return False

        return download(video_url, out_dir, ep_num, title, base_url, extra_args, log_fd=log_fd)


# ── history ───────────────────────────────────────────────────────────────────

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

# ── ricerca catalogo AnimeUnity ───────────────────────────────────────────────

# Valori ammessi per i filtri dell'API AnimeUnity
_FILTER_OPTS = {
    "type":   ["", "TV", "Movie", "OVA", "ONA", "Special", "Music"],
    "status": ["", "In corso", "Finito", "Non ancora uscito"],
    "order":  ["Più visti", "Più recenti", "A-Z", "Voto"],
    "season": ["", "Winter", "Spring", "Summer", "Fall"],
}

_GENRES_LIST = [
    "Action", "Adventure", "Comedy", "Drama", "Ecchi", "Fantasy",
    "Horror", "Josei", "Kids", "Magic", "Mecha", "Military", "Music",
    "Mystery", "Psychological", "Romance", "School", "Sci-Fi",
    "Seinen", "Shoujo", "Shounen", "Slice of Life", "Sports",
    "Supernatural", "Thriller",
]


def _normalize(value: str, allowed: list[str]) -> str:
    """Case-insensitive match contro una lista di valori ammessi."""
    v = value.strip().lower()
    for opt in allowed:
        if opt.lower() == v:
            return opt
    return ""


def search_catalog(base_url: str, query: str, filters: dict | None = None) -> list[dict]:
    """
    Cerca nel catalogo AnimeUnity via POST /archivio/get-filtra.
    Restituisce lista di {anime_id, slug, title, type, year, status}.
    """
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{base_url}/archivio",
    }
    body: dict = {
        "title":   query,
        "type":    "",
        "year":    "",
        "order":   "Più visti",
        "status":  "",
        "genres":  [],
        "offset":  0,
        "dubbed":  False,
        "season":  "",
    }
    if filters:
        for k, v in filters.items():
            if k in body:
                body[k] = v
    try:
        r = requests.post(
            f"{base_url}/archivio/get-filtra",
            json=body, headers=headers,
            impersonate=IMPERSONATE, timeout=15,
        )
        r.raise_for_status()
        data  = r.json()
        items = data.get("data", data) if isinstance(data, dict) else data
        if not isinstance(items, list):
            items = []
        return [
            {
                "anime_id": str(item.get("id", "")),
                "slug":     item.get("slug", ""),
                "title":    item.get("title") or item.get("slug", ""),
                "type":     item.get("type", ""),
                "year":     str(item.get("date", "") or ""),
                "status":   item.get("status", ""),
                "url":      f"{base_url}/anime/{item.get('id', '')}-{item.get('slug', '')}",
            }
            for item in items
            if item.get("id") and item.get("slug")
        ]
    except Exception:
        return []


# ── MangaDex API ─────────────────────────────────────────────────────────────

MANGADEX_API = "https://api.mangadex.org"

_MDX_GENRES = [
    ("Action",        "391b0423-d847-456f-aff0-8b0cfc03066b"),
    ("Adventure",     "87cc87cd-a395-47af-b27a-93258283bbc6"),
    ("Comedy",        "4d32cc48-9f00-4cca-9b5a-a839f0764984"),
    ("Drama",         "b9af3a63-f058-46de-a9a0-e0c13906197a"),
    ("Fantasy",       "cdc58593-87dd-415e-bbc0-2ec27bf404cc"),
    ("Historical",    "33771934-028e-4cb3-8744-691e866a923e"),
    ("Horror",        "cdad7e68-1419-41dd-bdce-27753074a640"),
    ("Isekai",        "ace04997-f6bd-436e-b261-779182193d3d"),
    ("Martial Arts",  "799c202e-7daa-44eb-9cf7-8a3b0441094e"),
    ("Mecha",         "e89d6967-3c39-4a57-9bba-0c8cde53b6ae"),
    ("Mystery",       "ee968100-4191-4968-93d3-f82d72be7e46"),
    ("Psychological", "3b60b75c-a2d7-4860-ab56-05f391bb889c"),
    ("Romance",       "423e2eae-a7a2-4a8b-ac03-a8351462d71d"),
    ("School Life",   "caaa44eb-cd40-4177-b930-79d3ef2efa74"),
    ("Sci-Fi",        "256c8bd9-4904-4360-bf4f-508a76d67183"),
    ("Slice of Life", "e5301a23-ebd9-49dd-a0cb-2add944c7fe9"),
    ("Sports",        "69964a64-2f90-4d33-beeb-f3ed2875eb4c"),
    ("Supernatural",  "eabc5b4c-6aff-42f3-b657-3e90cbd00b75"),
    ("Thriller",      "07251805-a27e-4d59-b488-f0bfbec15168"),
    ("Harem",         "aafb99c1-7f60-43fa-89a6-39fbf3b90ccd"),
]

_MDX_LANG_OPTS = [
    ("Italiano",  "it"),
    ("Inglese",   "en"),
    ("Spagnolo",  "es"),
    ("Francese",  "fr"),
]

_MDX_ORIGIN_OPTS = [
    ("Manga (JP)",  "ja"),
    ("Manhwa (KR)", "ko"),
    ("Manhua (CN)", "zh"),
]

_MDX_STATUS_OPTS = [
    ("In corso",   "ongoing"),
    ("Completato", "completed"),
    ("Hiatus",     "hiatus"),
    ("Cancellato", "cancelled"),
]

_MDX_DEMO_OPTS = [
    ("Shounen", "shounen"),
    ("Shoujo",  "shoujo"),
    ("Seinen",  "seinen"),
    ("Josei",   "josei"),
]

_MDX_RATING_OPTS = [
    ("Safe",       "safe"),
    ("Suggestivo", "suggestive"),
    ("Adulti",     "erotica"),
]

_MDX_ORDER_OPTS = [
    ("Più seguiti",       "followedCount"),
    ("Rilevanza",         "relevance"),
    ("Ultimi aggiornati", "latestUploadedChapter"),
    ("Più recenti",       "createdAt"),
]


def _safe_name(s: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '_', s).strip()


def search_mangadex(
    title: str = "",
    translated_lang: str = "it",
    original_lang: str = "",
    status: str = "",
    demographic: str = "",
    content_rating: str = "",
    included_tags: list | None = None,
    order: str = "followedCount",
) -> list[dict]:
    params: dict = {
        "limit": 40,
        "includes[]": "cover_art",
    }
    if title:
        params["title"] = title

    # Content rating: default safe+suggestive, unless specified
    if content_rating == "erotica":
        params["contentRating[]"] = ["erotica"]
    elif content_rating == "suggestive":
        params["contentRating[]"] = ["safe", "suggestive"]
    else:
        params["contentRating[]"] = ["safe", "suggestive"]

    if translated_lang:
        params["availableTranslatedLanguage[]"] = [translated_lang]
    if original_lang:
        params["originalLanguage[]"] = [original_lang]
    if status:
        params["status[]"] = [status]
    if demographic:
        params["publicationDemographic[]"] = [demographic]
    if included_tags:
        params["includedTags[]"] = included_tags

    order_map = {
        "followedCount":         ("followedCount",         "desc"),
        "relevance":             ("relevance",             "desc"),
        "latestUploadedChapter": ("latestUploadedChapter", "desc"),
        "createdAt":             ("createdAt",             "desc"),
    }
    field, direction = order_map.get(order, ("followedCount", "desc"))
    params[f"order[{field}]"] = direction

    try:
        r = requests.get(f"{MANGADEX_API}/manga", params=params, timeout=15)
        r.raise_for_status()
        results = []
        for item in r.json().get("data", []):
            attrs  = item.get("attributes", {})
            titles = attrs.get("title", {})
            name   = (
                titles.get("en") or titles.get("ja-ro") or
                titles.get("ja") or next(iter(titles.values()), "?")
            )
            genre_tags = [
                t["attributes"]["name"].get("en", "")
                for t in attrs.get("tags", [])
                if t.get("attributes", {}).get("group") == "genre"
            ][:3]
            results.append({
                "manga_id":       item["id"],
                "title":          name,
                "status":         attrs.get("status", ""),
                "demographic":    attrs.get("publicationDemographic") or "",
                "content_rating": attrs.get("contentRating", ""),
                "original_lang":  attrs.get("originalLanguage", ""),
                "year":           str(attrs.get("year", "") or ""),
                "genres":         ", ".join(genre_tags),
            })
        return results
    except Exception:
        return []


def fetch_manga_chapters(manga_id: str, translated_lang: str = "it") -> list[dict]:
    all_chapters: list[dict] = []
    offset = 0
    while True:
        try:
            r = requests.get(
                f"{MANGADEX_API}/manga/{manga_id}/feed",
                params={
                    "translatedLanguage[]": [translated_lang],
                    "order[chapter]": "asc",
                    "limit": 500,
                    "offset": offset,
                },
                timeout=20,
            )
            r.raise_for_status()
            data  = r.json()
            items = data.get("data", [])
            if not items:
                break
            for item in items:
                attrs = item.get("attributes", {})
                all_chapters.append({
                    "id":     item["id"],
                    "volume": attrs.get("volume") or "",
                    "number": attrs.get("chapter") or "?",
                    "title":  attrs.get("title") or "",
                    "pages":  attrs.get("pages", 0),
                    "lang":   attrs.get("translatedLanguage", ""),
                })
            total   = data.get("total", 0)
            offset += len(items)
            if offset >= total:
                break
            time.sleep(0.4)
        except Exception:
            break

    # Deduplicate: per chapter number keep highest page count
    seen: dict[str, dict] = {}
    for ch in all_chapters:
        num = ch["number"]
        if num not in seen or ch["pages"] > seen[num]["pages"]:
            seen[num] = ch

    def _num_key(n: str) -> float:
        try:
            return float(n)
        except ValueError:
            return float("inf")

    return sorted(seen.values(), key=lambda c: _num_key(c["number"]))


def local_complete_manga(out_dir: Path) -> set[str]:
    done: set[str] = set()
    for cbz in out_dir.glob("*.cbz"):
        m = re.search(r'Ch\s+([\d.]+)', cbz.stem)
        if m:
            done.add(m.group(1))
    return done


def _download_manga_chapter(item: "QueueItem", log_fd=None) -> bool:
    chapter_id  = item.episode["id"]
    chapter_num = item.episode.get("number", "?")
    volume      = item.episode.get("volume", "")
    ch_title    = item.episode.get("title", "")

    # Build padded chapter number string
    try:
        num_f   = float(chapter_num)
        num_str = f"{num_f:07.1f}" if num_f != int(num_f) else f"{int(num_f):04d}"
    except ValueError:
        num_str = chapter_num

    parts: list[str] = []
    if volume:
        try:
            parts.append(f"Vol {int(float(volume)):02d}")
        except ValueError:
            parts.append(f"Vol {volume}")
    parts.append(f"Ch {num_str}")
    if ch_title:
        parts.append(f"- {_safe_name(ch_title)[:60]}")
    cbz_name = " ".join(parts) + ".cbz"
    cbz_path = item.out_dir / cbz_name

    if cbz_path.exists():
        return True

    tmp_path = cbz_path.with_suffix(".tmp.cbz")
    tmp_path.unlink(missing_ok=True)

    # Fetch page list from MangaDex@Home
    try:
        r = requests.get(
            f"{MANGADEX_API}/at-home/server/{chapter_id}",
            timeout=15,
        )
        r.raise_for_status()
        data      = r.json()
        base_url  = data["baseUrl"]
        ch_hash   = data["chapter"]["hash"]
        pages     = data["chapter"]["data"]
    except Exception as e:
        if log_fd:
            log_fd.write(f"[ERROR] fetch pagine: {e}\n")
        return False

    total = len(pages)
    if total == 0:
        if log_fd:
            log_fd.write("[ERROR] capitolo senza pagine\n")
        return False

    try:
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_STORED) as zf:
            for i, page in enumerate(pages, 1):
                img_url  = f"{base_url}/data/{ch_hash}/{page}"
                ext      = page.rsplit(".", 1)[-1].lower() if "." in page else "jpg"
                arc_name = f"{i:04d}.{ext}"

                img_bytes = b""
                for attempt in range(3):
                    try:
                        ir = requests.get(img_url, timeout=45)
                        ir.raise_for_status()
                        img_bytes = ir.content
                        break
                    except Exception:
                        if attempt == 2:
                            raise
                        time.sleep(2)

                zf.writestr(arc_name, img_bytes)
                pct = i / total * 100
                if log_fd:
                    log_fd.write(f"[download]  {pct:.1f}% at 0.0 MiB/s ETA 00:00\n")
                    log_fd.flush()

        tmp_path.rename(cbz_path)
        return True
    except Exception as e:
        if log_fd:
            log_fd.write(f"[ERROR] download: {e}\n")
        tmp_path.unlink(missing_ok=True)
        return False


# ── status bar helpers ───────────────────────────────────────────────────────

_DL_PROGRESS_RE = re.compile(
    r'\[download\]\s+([\d.]+)%.*?at\s+([\d.]+)([\w/]+)\s+ETA\s+(\S+)'
)


def _parse_last_progress(log_path: "Path") -> tuple[float, str, float, str]:
    """Read the last yt-dlp progress line in the log.
    Returns (speed_mib, speed_label, percent, eta_str).
    All zero/empty when no data is available yet."""
    try:
        with open(log_path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 4096))
            tail = f.read().decode("utf-8", errors="replace")
        for line in reversed(tail.splitlines()):
            m = _DL_PROGRESS_RE.search(line)
            if m:
                pct        = float(m.group(1))
                speed_val  = float(m.group(2))
                speed_unit = m.group(3)
                eta        = m.group(4)
                su = speed_unit.upper()
                if "GIB" in su or "GB" in su:
                    mib = speed_val * 1024
                elif "KIB" in su or "KB" in su:
                    mib = speed_val / 1024
                elif su.startswith("B/"):
                    mib = speed_val / 1_048_576
                else:
                    mib = speed_val
                return mib, f"{speed_val:.1f} {speed_unit}", pct, eta
    except Exception:
        pass
    return 0.0, "", 0.0, ""


def _queue_status_text(queue: list) -> str:
    """One-line Rich-markup status string for the persistent status bar."""
    active  = [i for i in queue if i.status == "downloading"]
    pending = sum(1 for i in queue if i.status == "pending")
    done    = sum(1 for i in queue if i.status == "done")
    errors  = sum(1 for i in queue if i.status == "error")

    if not queue:
        return "[dim]Coda vuota  (Ctrl+D per aprirla)[/dim]"

    total_mib  = 0.0
    best_eta   = ""
    best_secs  = 0

    for item in active:
        if item.log_path:
            mib, _, _, eta = _parse_last_progress(item.log_path)
            total_mib += mib
            if eta:
                try:
                    p    = eta.split(":")
                    secs = int(p[-1]) + int(p[-2]) * 60 + (int(p[-3]) * 3600 if len(p) > 2 else 0)
                    if secs > best_secs:
                        best_secs, best_eta = secs, eta
                except Exception:
                    pass

    parts: list[str] = []
    if active:
        spd     = f"{total_mib:.1f} MiB/s" if total_mib > 0 else "..."
        eta_str = f"  ETA {best_eta}" if best_eta else ""
        parts.append(f"[yellow]>> {len(active)} in corso  {spd}{eta_str}[/yellow]")
    if pending:
        parts.append(f"[dim]{pending} in attesa[/dim]")
    if done:
        parts.append(f"[green]{done} completati[/green]")
    if errors:
        parts.append(f"[red]{errors} errori[/red]")

    hint = "  [dim](Ctrl+D: coda)[/dim]" if (active or pending) else ""
    return "  |  ".join(parts) + hint


# ── TUI Textual ───────────────────────────────────────────────────────────────

from textual.app        import App, ComposeResult
from textual.screen     import Screen
from textual.widgets    import (
    Header, Footer, Input, Select, Checkbox,
    Button, DataTable, SelectionList, Static, Label, LoadingIndicator,
)
from textual.containers import Horizontal, Vertical
from textual            import on, work
from rich.text          import Text as RichText


@dataclass
class QueueItem:
    uid:       str
    base_url:  str
    anime_id:  str
    slug:      str
    title:     str
    out_dir:   Path
    episode:   dict
    status:    str       = "pending"   # pending | downloading | done | error
    log_path:  Path | None = None
    item_type: str       = "anime"     # "anime" | "manga"

    @property
    def ep_num(self) -> str:
        return str(self.episode.get("number", "?"))

    @property
    def label(self) -> str:
        tag = "Ch" if self.item_type == "manga" else "Ep"
        return f"{self.title}  {tag} {self.ep_num}"


_APP_CSS = """\
SearchScreen {
    layout: vertical;
}
#filters {
    height: auto;
    background: $panel;
    padding: 1 2;
}
.filter-row {
    height: 3;
    margin-bottom: 1;
    align: left middle;
}
.flabel {
    width: 10;
    content-align: right middle;
    padding-right: 1;
}
#genres {
    height: 7;
    border: solid $accent;
}
#btn-row {
    height: 3;
    margin-top: 1;
    align: right middle;
}
#results {
    height: 1fr;
    margin-top: 1;
}
AnimeMenuScreen {
    layout: vertical;
}
#series-info {
    height: auto;
    background: $panel;
    padding: 1 2;
}
#ep-list {
    height: 1fr;
    border: solid $accent;
    margin: 0 2;
}
#ep-loading {
    height: 1fr;
}
#ep-actions {
    height: auto;
    padding: 0 2 1 2;
}
.ep-action-row {
    height: 3;
    margin-bottom: 1;
    align: left middle;
}
#sel-count {
    margin-left: 2;
    color: $text-muted;
}
QueueScreen {
    layout: vertical;
}
#queue-summary {
    height: 3;
    background: $panel;
    padding: 1 2;
    content-align: left middle;
}
#queue-table {
    height: 1fr;
}
#queue-actions {
    height: 3;
    padding: 0 2;
    align: left middle;
}
#queue-back {
    dock: right;
}
.dl-status {
    height: 1;
    background: $boost;
    padding: 0 2;
    content-align: left middle;
    color: $text-muted;
}
MainMenuScreen {
    layout: vertical;
    align: center middle;
}
#main-menu {
    width: 60;
    height: auto;
    padding: 2 4;
    background: $panel;
    border: solid $accent;
}
#main-menu Button {
    width: 100%;
    margin-bottom: 1;
}
#main-title {
    text-align: center;
    margin-bottom: 2;
}
MangaDexSearchScreen {
    layout: vertical;
}
#mdx-genres {
    height: 7;
    border: solid $accent;
}
MangaDexMenuScreen {
    layout: vertical;
}
SettingsScreen {
    layout: vertical;
    align: center middle;
}
#settings-form {
    width: 72;
    height: auto;
    padding: 2 4;
    background: $panel;
    border: solid $accent;
}
#settings-title {
    text-align: center;
    margin-bottom: 2;
}
.sfield {
    margin-bottom: 1;
}
.sfield Label {
    margin-bottom: 0;
    color: $text-muted;
}
#settings-btns {
    margin-top: 2;
    height: 3;
    align: left middle;
}
#settings-btns Button {
    margin-right: 2;
}
"""


class AnimeMenuScreen(Screen):

    BINDINGS = [
        ("escape", "pop_screen", "Indietro"),
        ("q",      "pop_screen", "Indietro"),
    ]

    def __init__(
        self,
        base_url: str, anime_id: str, slug: str,
        title: str, out_dir: Path,
    ) -> None:
        super().__init__()
        self._base_url     = base_url
        self._anime_id     = anime_id
        self._slug         = slug
        self._title        = title
        self._out_dir      = out_dir
        self._ep_map:      dict[str, dict] = {}
        self._missing_ids: set[str]        = set()

    def compose(self) -> ComposeResult:
        url = f"{self._base_url}/anime/{self._anime_id}-{self._slug}"
        yield Header()
        with Vertical(id="series-info"):
            yield Static(f"[bold cyan]{self._title}[/bold cyan]")
            yield Static(f"[dim]{url}[/dim]")
            yield Static(f"[dim]Output: {self._out_dir}[/dim]")
        yield LoadingIndicator(id="ep-loading")
        yield SelectionList(id="ep-list")
        with Vertical(id="ep-actions"):
            with Horizontal(classes="ep-action-row"):
                yield Button("Mancanti",         id="sel-missing", variant="default")
                yield Button("Tutti",            id="sel-all",     variant="default")
                yield Button("Nessuno",          id="desel-all",   variant="default")
                yield Label("", id="sel-count")
            with Horizontal(classes="ep-action-row"):
                yield Button("+ Aggiungi alla coda", id="add-queue", variant="success")
            with Horizontal(classes="ep-action-row"):
                yield Button("Sincronizza su Gengar", id="sync", variant="default")
                yield Button("<- Indietro",            id="back", variant="error")
        yield Static("", classes="dl-status", id="dl-status")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#ep-list", SelectionList).display = False
        self._fetch_episodes()
        self.set_interval(1.0, self._refresh_status)

    def _refresh_status(self) -> None:
        self.query_one("#dl-status", Static).update(
            _queue_status_text(getattr(self.app, "_queue", []))
        )

    @work(thread=True)
    def _fetch_episodes(self) -> None:
        all_eps = fetch_episodes(self._base_url, self._anime_id, 1, 9999)
        have    = local_complete_eps(self._out_dir, self._title)
        self.app.call_from_thread(self._populate, all_eps, have)

    def _populate(self, episodes: list[dict], have: set[int]) -> None:
        if not self.is_mounted:
            return
        self._ep_map      = {}
        self._missing_ids = set()
        self._all_options: list[tuple[str, str, bool]] = []
        ep_list = self.query_one("#ep-list", SelectionList)

        for ep in episodes:
            ep_id      = str(ep.get("id", ""))
            ep_num_raw = str(ep.get("number", "?"))
            if not ep_id:
                continue
            ep_num_int = int(ep_num_raw) if ep_num_raw.isdigit() else None
            is_done    = ep_num_int is not None and ep_num_int in have
            label      = f"Ep {ep_num_raw}  [OK]" if is_done else f"Ep {ep_num_raw}"
            self._ep_map[ep_id] = ep
            if not is_done:
                self._missing_ids.add(ep_id)
            self._all_options.append((label, ep_id, is_done))
            ep_list.add_option((label, ep_id, not is_done))

        self.query_one("#ep-loading", LoadingIndicator).display = False
        ep_list.display = True
        self._update_count()

    def _update_count(self) -> None:
        n = len(self.query_one("#ep-list", SelectionList).selected)
        self.query_one("#sel-count", Label).update(f"  {n} selezionati")

    @on(SelectionList.SelectedChanged)
    def _on_sel_changed(self) -> None:
        self._update_count()

    @on(Button.Pressed, "#sel-missing")
    def sel_missing(self) -> None:
        ep_list = self.query_one("#ep-list", SelectionList)
        ep_list.clear_options()
        for label, ep_id, is_done in self._all_options:
            if not is_done:
                ep_list.add_option((label, ep_id, True))
        self._update_count()

    @on(Button.Pressed, "#sel-all")
    def sel_all(self) -> None:
        ep_list = self.query_one("#ep-list", SelectionList)
        ep_list.clear_options()
        for label, ep_id, is_done in self._all_options:
            ep_list.add_option((label, ep_id, True))
        self._update_count()

    @on(Button.Pressed, "#desel-all")
    def desel_all(self) -> None:
        ep_list = self.query_one("#ep-list", SelectionList)
        ep_list.clear_options()
        for label, ep_id, is_done in self._all_options:
            ep_list.add_option((label, ep_id, False))
        self._update_count()

    @on(Button.Pressed, "#add-queue")
    def add_to_queue(self) -> None:
        selected_ids = list(self.query_one("#ep-list", SelectionList).selected)
        if not selected_ids:
            self.notify("Nessun episodio selezionato", severity="warning")
            return
        items = [
            QueueItem(
                uid      = str(uuid.uuid4()),
                base_url = self._base_url,
                anime_id = self._anime_id,
                slug     = self._slug,
                title    = self._title,
                out_dir  = self._out_dir,
                episode  = self._ep_map[eid],
            )
            for eid in selected_ids
            if eid in self._ep_map
        ]
        self.app.add_episodes_to_queue(items)
        ep_list = self.query_one("#ep-list", SelectionList)
        for eid in selected_ids:
            ep_list.deselect(eid)
        self._update_count()
        self.notify(f"{len(items)} episodi aggiunti alla coda", severity="information")

    @on(Button.Pressed, "#back")
    def go_back(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#sync")
    def on_sync(self) -> None:
        self._do_sync()

    @work(thread=True)
    def _do_sync(self) -> None:
        with self.app.suspend():
            cmd_sync(self._out_dir, _CFG["ssh_host"], _CFG["ssh_remote_base"])
            input("\nPremi Invio per continuare...")


class QueueScreen(Screen):

    BINDINGS = [
        ("escape", "pop_screen", "Chiudi"),
        ("q",      "pop_screen", "Chiudi"),
    ]

    _STATUS = {
        "pending":     ("dim",    "..."),
        "downloading": ("yellow", " >> "),
        "done":        ("green",  " OK "),
        "error":       ("red",    " !! "),
    }

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="queue-summary")
        yield DataTable(id="queue-table", cursor_type="row")
        with Horizontal(id="queue-actions"):
            yield Button("Pulisci completati / errori", id="clear-done", variant="default")
            yield Button("← Chiudi", id="queue-back", variant="default")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#queue-table", DataTable)
        table.add_column("Serie + Episodio", width=55, key="label-col")
        table.add_column("Stato",            width=12, key="status-col")
        self._known: set[str] = set()
        self.set_interval(0.5, self._refresh)

    def _refresh(self) -> None:
        items = getattr(self.app, "_queue", [])
        table = self.query_one("#queue-table", DataTable)

        for item in items:
            style, text = self._STATUS.get(item.status, ("", item.status))
            # For active downloads, show live speed + percent instead of static text
            if item.status == "downloading" and item.log_path:
                mib, lbl, pct, eta = _parse_last_progress(item.log_path)
                if mib > 0:
                    short = lbl.replace("MiB/s", "M/s").replace("KiB/s", "K/s")
                    text  = f"{pct:3.0f}% {short}"
            cell = RichText(text, style=style)
            if item.uid not in self._known:
                table.add_row(item.label, cell, key=item.uid)
                self._known.add(item.uid)
            else:
                table.update_cell(item.uid, "status-col", cell, update_width=False)

        self.query_one("#queue-summary", Static).update(
            _queue_status_text(items)
        )

    @on(Button.Pressed, "#queue-back")
    def close_queue(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#clear-done")
    def clear_done(self) -> None:
        to_remove = {i.uid for i in self.app._queue if i.status in ("done", "error")}
        self.app._queue = [i for i in self.app._queue if i.uid not in to_remove]
        table = self.query_one("#queue-table", DataTable)
        for uid in to_remove:
            if uid in self._known:
                table.remove_row(uid)
                self._known.discard(uid)


class SearchScreen(Screen):

    BINDINGS = [
        ("escape", "pop_screen", "Indietro"),
        ("q",      "pop_screen", "Indietro"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="filters"):
            with Horizontal(classes="filter-row"):
                yield Label("Titolo:", classes="flabel")
                yield Input(placeholder="cerca per titolo...", id="title")
                yield Label("Tipo:", classes="flabel")
                yield Select(
                    [(v, v) for v in _FILTER_OPTS["type"] if v],
                    id="type", allow_blank=True, prompt="(tutti)",
                )
                yield Label("Anno:", classes="flabel")
                yield Input(placeholder="es. 2018", id="year")
            with Horizontal(classes="filter-row"):
                yield Label("Stato:", classes="flabel")
                yield Select(
                    [(v, v) for v in _FILTER_OPTS["status"] if v],
                    id="status", allow_blank=True, prompt="(tutti)",
                )
                yield Label("Stagione:", classes="flabel")
                yield Select(
                    [(v, v) for v in _FILTER_OPTS["season"] if v],
                    id="season", allow_blank=True, prompt="(tutti)",
                )
                yield Label("Ordina:", classes="flabel")
                yield Select(
                    [(v, v) for v in _FILTER_OPTS["order"]],
                    id="order", allow_blank=False,
                )
                yield Checkbox("Solo doppiato ITA", id="dubbed")
            yield SelectionList(*[(g, g) for g in _GENRES_LIST], id="genres")
            with Horizontal(id="btn-row"):
                yield Button("Cerca", id="search", variant="primary")
                yield Button("Pulisci filtri", id="clear", variant="default")
        yield DataTable(id="results", cursor_type="row")
        yield Static("", classes="dl-status", id="dl-status")
        yield Footer()

    def on_mount(self) -> None:
        self._history: list[dict] = []
        self._results: list[dict] = []
        table = self.query_one("#results", DataTable)
        table.add_column("#",      width=4)
        table.add_column("Titolo", width=40)
        table.add_column("Tipo",   width=8)
        table.add_column("Anno",   width=6)
        table.add_column("Stato",  width=16)
        self._load_history_rows()
        self.set_interval(1.0, self._refresh_status)

    def _refresh_status(self) -> None:
        self.query_one("#dl-status", Static).update(
            _queue_status_text(getattr(self.app, "_queue", []))
        )

    def _load_history_rows(self) -> None:
        self._history = load_history()
        table = self.query_one("#results", DataTable)
        table.clear()
        for h in self._history[:10]:
            year = (h.get("last_used", "") or "")[:4]
            table.add_row(
                RichText(">>",         style="yellow bold"),
                RichText(h["title"],   style="yellow"),
                RichText("",          style="yellow"),
                RichText(year,        style="yellow"),
                RichText("recente",   style="yellow"),
                key=f"hist_{h['anime_id']}",
            )

    @on(Button.Pressed, "#search")
    def do_search(self) -> None:
        type_val   = self.query_one("#type",   Select).value
        status_val = self.query_one("#status", Select).value
        season_val = self.query_one("#season", Select).value
        order_val  = self.query_one("#order",  Select).value
        filters = {
            "type":   "" if type_val   is Select.BLANK else type_val,
            "year":   self.query_one("#year", Input).value.strip(),
            "status": "" if status_val is Select.BLANK else status_val,
            "season": "" if season_val is Select.BLANK else season_val,
            "order":  "Più visti" if order_val is Select.BLANK else order_val,
            "dubbed": bool(self.query_one("#dubbed", Checkbox).value),
            "genres": list(self.query_one("#genres", SelectionList).selected),
        }
        query = self.query_one("#title", Input).value.strip()
        self._search_worker(query, filters)

    @work(thread=True)
    def _search_worker(self, query: str, filters: dict) -> None:
        results = search_catalog(DEFAULT_BASE, query, filters)
        self.app.call_from_thread(self._populate_results, results)

    def _populate_results(self, results: list[dict]) -> None:
        self._results = results
        history_ids   = {h["anime_id"] for h in self._history}
        table = self.query_one("#results", DataTable)
        table.clear()
        for i, item in enumerate(results[:50], 1):
            anno  = (item.get("year") or "")[:4]
            style = "yellow" if item["anime_id"] in history_ids else ""
            table.add_row(
                RichText(str(i),          style=style),
                RichText(item["title"],   style=style),
                RichText(item["type"],    style=style),
                RichText(anno,            style=style),
                RichText(item["status"],  style=style),
                key=f"res_{item['anime_id']}",
            )

    @on(Button.Pressed, "#clear")
    def clear_filters(self) -> None:
        self.query_one("#title",  Input).value        = ""
        self.query_one("#year",   Input).value        = ""
        self.query_one("#type",   Select).value       = Select.BLANK
        self.query_one("#status", Select).value       = Select.BLANK
        self.query_one("#season", Select).value       = Select.BLANK
        self.query_one("#dubbed", Checkbox).value     = False
        self.query_one("#genres", SelectionList).deselect_all()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key  = str(event.row_key.value or "")
        item: dict | None = None

        if key.startswith("res_"):
            aid  = key[4:]
            item = next((r for r in self._results if r["anime_id"] == aid), None)
        elif key.startswith("hist_"):
            aid  = key[5:]
            h    = next((h for h in self._history if h["anime_id"] == aid), None)
            if h:
                item = {
                    "base_url": h["base_url"],
                    "anime_id": h["anime_id"],
                    "slug":     h["slug"],
                    "title":    h["title"],
                }

        if item:
            base_url = item.get("base_url", DEFAULT_BASE)
            save_history(base_url, item["anime_id"], item["slug"], item["title"])
            out_dir  = Path(_CFG["download_dir"]) / item["title"]
            out_dir.mkdir(parents=True, exist_ok=True)
            self.app.push_screen(
                AnimeMenuScreen(
                    base_url, item["anime_id"], item["slug"],
                    item["title"], out_dir,
                )
            )


class MangaDexSearchScreen(Screen):
    BINDINGS = [
        ("escape", "pop_screen", "Indietro"),
        ("q",      "pop_screen", "Indietro"),
        ("ctrl+d", "app.open_queue", "Coda"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="filters"):
            with Horizontal(classes="filter-row"):
                yield Label("Titolo:", classes="flabel")
                yield Input(placeholder="cerca manga...", id="mdx-title")
                yield Label("Lingua:", classes="flabel")
                yield Select(
                    [(lbl, val) for lbl, val in _MDX_LANG_OPTS],
                    id="mdx-lang", allow_blank=True, prompt="(tutti)",
                )
            with Horizontal(classes="filter-row"):
                yield Label("Tipo:", classes="flabel")
                yield Select(
                    [(lbl, val) for lbl, val in _MDX_ORIGIN_OPTS],
                    id="mdx-origin", allow_blank=True, prompt="(tutti)",
                )
                yield Label("Stato:", classes="flabel")
                yield Select(
                    [(lbl, val) for lbl, val in _MDX_STATUS_OPTS],
                    id="mdx-status", allow_blank=True, prompt="(tutti)",
                )
                yield Label("Target:", classes="flabel")
                yield Select(
                    [(lbl, val) for lbl, val in _MDX_DEMO_OPTS],
                    id="mdx-demo", allow_blank=True, prompt="(tutti)",
                )
            with Horizontal(classes="filter-row"):
                yield Label("Età:", classes="flabel")
                yield Select(
                    [(lbl, val) for lbl, val in _MDX_RATING_OPTS],
                    id="mdx-rating", allow_blank=True, prompt="(tutti)",
                )
                yield Label("Ordina:", classes="flabel")
                yield Select(
                    [(lbl, val) for lbl, val in _MDX_ORDER_OPTS],
                    id="mdx-order", allow_blank=False,
                )
            yield SelectionList(*[(g, tid) for g, tid in _MDX_GENRES], id="mdx-genres")
            with Horizontal(id="btn-row"):
                yield Button("Cerca",         id="mdx-search-btn", variant="primary")
                yield Button("Pulisci filtri", id="mdx-clear-btn",  variant="default")
        yield DataTable(id="results", cursor_type="row")
        yield Static("", classes="dl-status", id="dl-status")
        yield Footer()

    def on_mount(self) -> None:
        self._results: list[dict] = []
        self._selected_lang: str  = "it"
        table = self.query_one("#results", DataTable)
        table.add_column("#",       width=4)
        table.add_column("Titolo",  width=34)
        table.add_column("Tipo",    width=10)
        table.add_column("Stato",   width=12)
        table.add_column("Rating",  width=10)
        table.add_column("Generi",  width=26)
        self.set_interval(1.0, self._refresh_status)

    def _refresh_status(self) -> None:
        self.query_one("#dl-status", Static).update(
            _queue_status_text(getattr(self.app, "_queue", []))
        )

    @on(Button.Pressed, "#mdx-search-btn")
    def do_search(self) -> None:
        lang_val   = self.query_one("#mdx-lang",   Select).value
        origin_val = self.query_one("#mdx-origin", Select).value
        status_val = self.query_one("#mdx-status", Select).value
        demo_val   = self.query_one("#mdx-demo",   Select).value
        rating_val = self.query_one("#mdx-rating", Select).value
        order_val  = self.query_one("#mdx-order",  Select).value
        title_val  = self.query_one("#mdx-title",  Input).value.strip()
        tags       = list(self.query_one("#mdx-genres", SelectionList).selected)

        self._selected_lang = "" if lang_val is Select.BLANK else str(lang_val)
        self._search_worker(
            title       = title_val,
            trans_lang  = "" if lang_val   is Select.BLANK else str(lang_val),
            origin_lang = "" if origin_val is Select.BLANK else str(origin_val),
            status      = "" if status_val is Select.BLANK else str(status_val),
            demographic = "" if demo_val   is Select.BLANK else str(demo_val),
            rating      = "" if rating_val is Select.BLANK else str(rating_val),
            order       = "followedCount" if order_val is Select.BLANK else str(order_val),
            tags        = tags,
        )

    @work(thread=True)
    def _search_worker(
        self, title, trans_lang, origin_lang, status, demographic, rating, order, tags
    ) -> None:
        results = search_mangadex(
            title           = title,
            translated_lang = trans_lang,
            original_lang   = origin_lang,
            status          = status,
            demographic     = demographic,
            content_rating  = rating,
            included_tags   = tags or None,
            order           = order,
        )
        self.app.call_from_thread(self._populate_results, results)

    def _populate_results(self, results: list[dict]) -> None:
        self._results = results
        table = self.query_one("#results", DataTable)
        table.clear()
        type_map = {"ja": "Manga", "ko": "Manhwa", "zh": "Manhua", "zh-hk": "Manhua"}
        for i, item in enumerate(results[:50], 1):
            tipo = type_map.get(item.get("original_lang", ""), item.get("original_lang", ""))
            table.add_row(
                str(i),
                item["title"],
                tipo,
                item.get("status", ""),
                item.get("content_rating", ""),
                item.get("genres", ""),
                key=f"mdx_{item['manga_id']}",
            )

    @on(Button.Pressed, "#mdx-clear-btn")
    def clear_filters(self) -> None:
        self.query_one("#mdx-title",  Input).value = ""
        self.query_one("#mdx-lang",   Select).value = Select.BLANK
        self.query_one("#mdx-origin", Select).value = Select.BLANK
        self.query_one("#mdx-status", Select).value = Select.BLANK
        self.query_one("#mdx-demo",   Select).value = Select.BLANK
        self.query_one("#mdx-rating", Select).value = Select.BLANK
        self.query_one("#mdx-genres", SelectionList).deselect_all()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key = str(event.row_key.value or "")
        if not key.startswith("mdx_"):
            return
        manga_id = key[4:]
        item = next((r for r in self._results if r["manga_id"] == manga_id), None)
        if not item:
            return
        lang    = self._selected_lang or "it"
        out_dir = Path(_CFG["manga_dir"]) / _safe_name(item["title"])
        out_dir.mkdir(parents=True, exist_ok=True)
        self.app.push_screen(
            MangaDexMenuScreen(manga_id, item["title"], out_dir, lang)
        )


class MangaDexMenuScreen(Screen):

    BINDINGS = [
        ("escape", "pop_screen", "Indietro"),
        ("q",      "pop_screen", "Indietro"),
    ]

    def __init__(
        self,
        manga_id: str, title: str, out_dir: Path, lang: str = "it",
    ) -> None:
        super().__init__()
        self._manga_id     = manga_id
        self._title        = title
        self._out_dir      = out_dir
        self._lang         = lang or "it"
        self._ch_map:      dict[str, dict] = {}
        self._missing_ids: set[str]        = set()

    def compose(self) -> ComposeResult:
        lang_label = {
            "it": "Italiano", "en": "Inglese",
            "es": "Spagnolo", "fr": "Francese",
        }.get(self._lang, self._lang)
        yield Header()
        with Vertical(id="series-info"):
            yield Static(f"[bold cyan]{self._title}[/bold cyan]")
            yield Static(f"[dim]Lingua: {lang_label}  |  Output: {self._out_dir}[/dim]")
        yield LoadingIndicator(id="ep-loading")
        yield SelectionList(id="ep-list")
        with Vertical(id="ep-actions"):
            with Horizontal(classes="ep-action-row"):
                yield Button("Mancanti", id="sel-missing", variant="default")
                yield Button("Tutti",    id="sel-all",     variant="default")
                yield Button("Nessuno",  id="desel-all",   variant="default")
                yield Label("", id="sel-count")
            with Horizontal(classes="ep-action-row"):
                yield Button("+ Aggiungi alla coda", id="add-queue", variant="success")
            with Horizontal(classes="ep-action-row"):
                yield Button("<- Indietro", id="back", variant="error")
        yield Static("", classes="dl-status", id="dl-status")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#ep-list", SelectionList).display = False
        self._fetch_chapters()
        self.set_interval(1.0, self._refresh_status)

    def _refresh_status(self) -> None:
        self.query_one("#dl-status", Static).update(
            _queue_status_text(getattr(self.app, "_queue", []))
        )

    @work(thread=True)
    def _fetch_chapters(self) -> None:
        chapters = fetch_manga_chapters(self._manga_id, self._lang)
        have     = local_complete_manga(self._out_dir)
        self.app.call_from_thread(self._populate, chapters, have)

    def _populate(self, chapters: list[dict], have: set[str]) -> None:
        if not self.is_mounted:
            return
        self._ch_map      = {}
        self._missing_ids = set()
        self._all_options: list[tuple[str, str, bool]] = []
        ch_list = self.query_one("#ep-list", SelectionList)

        for ch in chapters:
            ch_id   = ch["id"]
            num     = ch["number"]
            vol     = ch.get("volume", "")
            title   = ch.get("title", "")
            pages   = ch.get("pages", 0)
            is_done = num in have

            parts: list[str] = []
            if vol:
                parts.append(f"Vol {vol}")
            parts.append(f"Ch {num}")
            if title:
                parts.append(f"- {title[:40]}")
            if pages:
                parts.append(f"({pages}p)")
            if is_done:
                parts.append("[OK]")

            label = "  ".join(parts)
            self._ch_map[ch_id] = ch
            if not is_done:
                self._missing_ids.add(ch_id)
            self._all_options.append((label, ch_id, is_done))
            ch_list.add_option((label, ch_id, not is_done))

        self.query_one("#ep-loading", LoadingIndicator).display = False
        ch_list.display = True
        self._update_count()

    def _update_count(self) -> None:
        n = len(self.query_one("#ep-list", SelectionList).selected)
        self.query_one("#sel-count", Label).update(f"  {n} selezionati")

    @on(SelectionList.SelectedChanged)
    def _on_sel_changed(self) -> None:
        self._update_count()

    @on(Button.Pressed, "#sel-missing")
    def sel_missing(self) -> None:
        ch_list = self.query_one("#ep-list", SelectionList)
        ch_list.clear_options()
        for label, ch_id, is_done in self._all_options:
            if not is_done:
                ch_list.add_option((label, ch_id, True))
        self._update_count()

    @on(Button.Pressed, "#sel-all")
    def sel_all(self) -> None:
        ch_list = self.query_one("#ep-list", SelectionList)
        ch_list.clear_options()
        for label, ch_id, is_done in self._all_options:
            ch_list.add_option((label, ch_id, True))
        self._update_count()

    @on(Button.Pressed, "#desel-all")
    def desel_all(self) -> None:
        ch_list = self.query_one("#ep-list", SelectionList)
        ch_list.clear_options()
        for label, ch_id, is_done in self._all_options:
            ch_list.add_option((label, ch_id, False))
        self._update_count()

    @on(Button.Pressed, "#add-queue")
    def add_to_queue(self) -> None:
        selected_ids = list(self.query_one("#ep-list", SelectionList).selected)
        if not selected_ids:
            self.notify("Nessun capitolo selezionato", severity="warning")
            return
        items = [
            QueueItem(
                uid       = str(uuid.uuid4()),
                base_url  = MANGADEX_API,
                anime_id  = self._manga_id,
                slug      = "",
                title     = self._title,
                out_dir   = self._out_dir,
                episode   = self._ch_map[cid],
                item_type = "manga",
            )
            for cid in selected_ids
            if cid in self._ch_map
        ]
        self.app.add_episodes_to_queue(items)
        ch_list = self.query_one("#ep-list", SelectionList)
        for cid in selected_ids:
            ch_list.deselect(cid)
        self._update_count()
        self.notify(f"{len(items)} capitoli aggiunti alla coda", severity="information")

    @on(Button.Pressed, "#back")
    def go_back(self) -> None:
        self.app.pop_screen()


class SettingsScreen(Screen):
    BINDINGS = [
        ("escape", "pop_screen", "Annulla"),
        ("q",      "pop_screen", "Annulla"),
    ]

    def compose(self) -> ComposeResult:
        from textual.widgets import Input, Label
        yield Header()
        with Vertical(id="settings-form"):
            yield Static("[bold cyan]Impostazioni[/bold cyan]", id="settings-title")
            with Vertical(classes="sfield"):
                yield Label("Cartella download anime")
                yield Input(_CFG["download_dir"], id="s-download-dir")
            with Vertical(classes="sfield"):
                yield Label("Cartella download manga")
                yield Input(_CFG["manga_dir"], id="s-manga-dir")
            with Vertical(classes="sfield"):
                yield Label("Server SSH  (utente@host)")
                yield Input(_CFG["ssh_host"], id="s-ssh-host")
            with Vertical(classes="sfield"):
                yield Label("Percorso remoto base")
                yield Input(_CFG["ssh_remote_base"], id="s-ssh-remote")
            with Vertical(classes="sfield"):
                yield Label("URL AnimeUnity")
                yield Input(_CFG["animeunity_base"], id="s-au-base")
            with Vertical(classes="sfield"):
                yield Label("Download paralleli (1–8)")
                yield Input(str(_CFG["max_concurrent"]), id="s-max-dl")
            with Horizontal(id="settings-btns"):
                yield Button("Salva", id="save-settings", variant="primary")
                yield Button("Annulla", id="cancel-settings", variant="default")
        yield Footer()

    @on(Button.Pressed, "#save-settings")
    def do_save(self) -> None:
        from textual.widgets import Input
        def _val(wid: str) -> str:
            return self.query_one(f"#{wid}", Input).value.strip()

        try:
            mc = int(_val("s-max-dl"))
            if not (1 <= mc <= 8):
                raise ValueError
        except ValueError:
            self.notify("Download paralleli deve essere un numero tra 1 e 8", severity="error")
            return

        _CFG["download_dir"]    = _val("s-download-dir")
        _CFG["manga_dir"]       = _val("s-manga-dir")
        _CFG["ssh_host"]        = _val("s-ssh-host")
        _CFG["ssh_remote_base"] = _val("s-ssh-remote")
        _CFG["animeunity_base"] = _val("s-au-base")
        _CFG["max_concurrent"]  = mc
        save_settings(_CFG)
        self.notify("Impostazioni salvate", severity="information")
        self.app.pop_screen()

    @on(Button.Pressed, "#cancel-settings")
    def do_cancel(self) -> None:
        self.app.pop_screen()


class MainMenuScreen(Screen):
    BINDINGS = [
        ("q",      "app.quit",       "Esci"),
        ("ctrl+d", "app.open_queue", "Coda"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="main-menu"):
            yield Static(
                "[bold cyan]Scegli sorgente[/bold cyan]",
                id="main-title",
            )
            yield Button(
                "Anime / Film  ·  AnimeUnity",
                id="go-anime", variant="primary",
            )
            yield Button(
                "Manga / Manhwa  ·  MangaDex",
                id="go-manga", variant="success",
            )
            yield Button(
                "Coda download  (Ctrl+D)",
                id="go-queue", variant="default",
            )
            yield Button(
                "Impostazioni",
                id="go-settings", variant="default",
            )
        yield Footer()

    @on(Button.Pressed, "#go-anime")
    def go_anime(self) -> None:
        self.app.push_screen(SearchScreen())

    @on(Button.Pressed, "#go-manga")
    def go_manga(self) -> None:
        self.app.push_screen(MangaDexSearchScreen())

    @on(Button.Pressed, "#go-queue")
    def go_queue(self) -> None:
        self.app.push_screen(QueueScreen())

    @on(Button.Pressed, "#go-settings")
    def go_settings(self) -> None:
        self.app.push_screen(SettingsScreen())


class AnimeUnityApp(App):
    TITLE        = "Downloader"
    CSS          = _APP_CSS
    BINDINGS     = [
        ("ctrl+d", "open_queue", "Coda download"),
        # q is handled per-screen: quit on MainMenuScreen, pop_screen on sub-screens
    ]
    MAX_CONCURRENT = _CFG["max_concurrent"]

    def on_mount(self) -> None:
        from concurrent.futures import ThreadPoolExecutor
        self._queue:    list[QueueItem]    = []
        self._executor: "ThreadPoolExecutor" = ThreadPoolExecutor(
            max_workers=self.MAX_CONCURRENT,
            thread_name_prefix="dl-worker",
        )
        self.push_screen(MainMenuScreen())

    def action_open_queue(self) -> None:
        self.push_screen(QueueScreen())

    def add_episodes_to_queue(self, items: list[QueueItem]) -> None:
        self._queue.extend(items)
        for item in items:
            self._executor.submit(self._process_item, item)

    def _process_item(self, item: QueueItem) -> None:
        item.status   = "downloading"
        log_path      = item.out_dir / f"queue_{item.uid[:6]}.log"
        item.log_path = log_path
        try:
            with open(log_path, "w", encoding="utf-8", errors="replace") as lf:
                if item.item_type == "manga":
                    ok = _download_manga_chapter(item, log_fd=lf)
                else:
                    ok = _download_one_episode(
                        item.episode, item.base_url, item.anime_id,
                        item.slug, item.title, item.out_dir, [],
                        log_fd=lf,
                    )
            item.status = "done" if ok else "error"
        except Exception as exc:
            item.status = "error"
            try:
                log_path.write_text(str(exc), encoding="utf-8")
            except Exception:
                pass

    def on_unmount(self) -> None:
        if executor := getattr(self, "_executor", None):
            executor.shutdown(wait=False, cancel_futures=True)

# ── sync su server SSH ────────────────────────────────────────────────────────


_SSH_OPTS = ["-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10"]

def _ssh(host: str, cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["ssh", *_SSH_OPTS, host, cmd],
        stdout=subprocess.PIPE, text=True,
    )

def _ensure_ssh_key(host: str) -> None:
    """Crea chiave SSH locale se mancante e la copia sul server."""
    key_path = Path.home() / ".ssh" / "id_ed25519"
    pub_path = key_path.with_suffix(".pub")

    if not key_path.exists():
        print("  Chiave SSH non trovata — la genero...")
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(key_path)],
            check=True,
        )
        print(f"  Chiave creata: {key_path}")

    # Test silenzioso: la chiave funziona già?
    r = subprocess.run(
        ["ssh", *_SSH_OPTS, "-o", "BatchMode=yes", host, "exit"],
        capture_output=True,
    )
    if r.returncode == 0:
        return

    pub_key = pub_path.read_text(encoding="utf-8").strip()
    escaped = pub_key.replace("'", "'\\''")
    print("  Chiave SSH non configurata sul server.")
    print("  Inserire la password una sola volta per copiarla:")
    r2 = subprocess.run(
        ["ssh", *_SSH_OPTS, host,
         f"mkdir -p ~/.ssh && chmod 700 ~/.ssh && grep -qF '{escaped}' ~/.ssh/authorized_keys 2>/dev/null"
         f" || echo '{escaped}' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"],
    )
    if r2.returncode == 0:
        print("  Chiave copiata — i prossimi accessi non richiederanno la password.")
    else:
        print("  [ATTENZIONE] Copia chiave fallita — verrà richiesta la password ad ogni operazione.")

def cmd_sync(local_dir: Path, host: str, remote_base: str) -> None:
    if not local_dir.is_dir():
        sys.exit(f"[ERRORE] Cartella locale non trovata: {local_dir}")

    _ensure_ssh_key(host)

    local_files = sorted(f.name for f in local_dir.glob("*.mp4"))
    if not local_files:
        print("  Nessun file .mp4 nella cartella locale.")
        return

    print(f"  File locali  : {len(local_files)}")

    remote_dir = f"{remote_base}/{local_dir.name}"

    r = _ssh(host, f"mkdir -p '{remote_dir}'")
    if r.returncode != 0:
        sys.exit("[ERRORE] Impossibile creare cartella remota su Gengar (vedi errore sopra)")

    r = _ssh(host, f"ls '{remote_dir}' 2>/dev/null")
    remote_files = set(r.stdout.strip().splitlines()) if r.stdout.strip() else set()
    print(f"  File remoti  : {len(remote_files)}  ({remote_dir})")

    missing = [f for f in local_files if f not in remote_files]

    if not missing:
        print("\n  Tutti gli episodi sono già presenti su Gengar!")
        return

    print(f"\n  Mancanti: {len(missing)}")
    for fname in missing:
        size_mb = (local_dir / fname).stat().st_size / (1024 * 1024)
        print(f"    - {fname}  ({size_mb:.1f} MB)")

    print()
    import time
    errors = 0
    for i, fname in enumerate(missing, 1):
        local_path  = local_dir / fname
        remote_path = f"{host}:{remote_dir}/{fname}"
        size_mb     = local_path.stat().st_size / (1024 * 1024)
        print(f"  [{i}/{len(missing)}] {fname}  ({size_mb:.1f} MB) ...", end="", flush=True)
        t0 = time.monotonic()
        r  = subprocess.run(["scp", *_SSH_OPTS, str(local_path), remote_path])
        elapsed = time.monotonic() - t0
        if r.returncode == 0:
            speed = size_mb / elapsed if elapsed > 0 else 0
            print(f"  OK  ({elapsed:.0f}s, {speed:.1f} MB/s)")
        else:
            print(f"  [ERRORE]")
            errors += 1

    if errors:
        print(f"\n  Completato con {errors} errore/i.")
    else:
        print("\n  Sincronizzazione completata.")

# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="AnimeUnity downloader + sync",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="cmd")

    # ── subcomando: download ──
    dl = sub.add_parser("download", help="Scarica episodi da AnimeUnity")
    dl.add_argument("url")
    dl.add_argument("start",  nargs="?", type=int, default=1)
    dl.add_argument("end",    nargs="?", type=int, default=None)
    dl.add_argument("--out",  default=None)
    dl.add_argument("--ytdlp-args", nargs=argparse.REMAINDER, default=[])

    # ── subcomando: missing ──
    ms = sub.add_parser("missing", help="Scarica episodi mancanti o parziali")
    ms.add_argument("url")
    ms.add_argument("--start", type=int, default=1,    help="Primo episodio da controllare (default: 1)")
    ms.add_argument("--end",   type=int, default=9999, help="Ultimo episodio da controllare (default: tutti)")
    ms.add_argument("--out",   default=None)
    ms.add_argument("--ytdlp-args", nargs=argparse.REMAINDER, default=[])

    # ── subcomando: sync ──
    sy = sub.add_parser("sync", help="Verifica e copia episodi mancanti su Gengar")
    sy.add_argument("--local",        default=None,                    help="Cartella locale")
    sy.add_argument("--host",         default=_CFG["ssh_host"],        help=f"SSH host (default da settings)")
    sy.add_argument("--remote-base",  default=_CFG["ssh_remote_base"], help=f"Percorso base remoto (default da settings)")

    args = parser.parse_args()

    # ── nessun subcomando → menu interattivo ──
    if not args.cmd:
        AnimeUnityApp().run()
        return

    # ════════════════════════════════════════
    if args.cmd == "missing":
        base_url, anime_id, slug = parse_anime_url(args.url)
        title   = slug.replace("-", " ").title()
        out_dir = Path(args.out) if args.out else Path(_CFG["download_dir"]) / title
        out_dir.mkdir(parents=True, exist_ok=True)

        print(f"\nAnime  : {title}")
        print(f"Sito   : {base_url}")
        print(f"Output : {out_dir}")

        print("\nScansione episodi locali...")
        have = local_complete_eps(out_dir, title)
        print(f"  Completi in locale : {sorted(have) or 'nessuno'}")

        print("\nFetch lista episodi da AnimeUnity...")
        all_eps = fetch_episodes(base_url, anime_id, args.start, args.end)
        if not all_eps:
            print("[ATTENZIONE] Nessun episodio restituito dall'API.")
            sys.exit(1)

        # Filtra solo quelli assenti o parziali
        to_dl = [
            ep for ep in all_eps
            if str(ep.get("number", "")).isdigit()
            and int(ep["number"]) not in have
        ]

        if not to_dl:
            print("\nNessun episodio mancante — tutto aggiornato!")
            return

        missing_nums = sorted(int(ep["number"]) for ep in to_dl)
        print(f"\nEpisodi mancanti ({len(to_dl)}): {missing_nums}\n")

        run_episode_list(to_dl, base_url, anime_id, slug, title, out_dir, args.ytdlp_args)
        return

    # ════════════════════════════════════════
    if args.cmd == "sync":
        local_dir = Path(args.local) if args.local else Path(_CFG["download_dir"])
        print(f"\nSync: {local_dir}")
        print(f"  → {args.host}:{args.remote_base}\n")
        cmd_sync(local_dir, args.host, args.remote_base)
        return

    # ════════════════════════════════════════
    # download
    start_ep = args.start
    end_ep   = args.end if args.end is not None else start_ep + 9

    base_url, anime_id, slug = parse_anime_url(args.url)
    title = slug.replace("-", " ").title()

    print(f"\nAnime  : {title}")
    print(f"Sito   : {base_url}")
    print(f"Range  : episodi {start_ep} – {end_ep}")

    print("\nRecupero lista episodi...")
    episodes = fetch_episodes(base_url, anime_id, start_ep, end_ep)
    if not episodes:
        print("[ATTENZIONE] Nessun episodio trovato.")
        sys.exit(1)
    print(f"Trovati {len(episodes)} episodi")

    out_dir = Path(args.out) if args.out else Path(_CFG["download_dir"]) / title
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output : {out_dir}\n")

    run_episode_list(episodes, base_url, anime_id, slug, title, out_dir, args.ytdlp_args)


if __name__ == "__main__":
    main()
