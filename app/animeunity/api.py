import json
import re
import sys
import html as html_module
import subprocess
from pathlib import Path

from curl_cffi import requests

from ..config import IMPERSONATE

_LOG_AU = Path(__file__).parent.parent.parent / "animeunity_debug.log"

_FILTER_OPTS = {
    "type":   ["", "TV", "Movie", "OVA", "ONA", "Special", "Music"],
    "status": ["", "In corso", "Terminato", "Non ancora uscito"],
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


def unescape(s: str) -> str:
    prev = ""
    while prev != s:
        prev = s
        s = html_module.unescape(s)
    return s.replace("\\/", "/")


def _normalize(value: str, allowed: list[str]) -> str:
    v = value.strip().lower()
    for opt in allowed:
        if opt.lower() == v:
            return opt
    return ""


def parse_anime_url(url: str) -> tuple[str, str, str]:
    m = re.search(r"(https://(?:www\.)?animeunity\.\w+)/anime/(\d+)-([^/?#\s]+)", url)
    if not m:
        sys.exit(
            f"[ERRORE] URL non riconosciuta: {url}\n"
            "Formato atteso: https://www.animeunity.so/anime/<ID>-<nome>"
        )
    return m.group(1), m.group(2), m.group(3)


def fetch_episodes(base_url: str, anime_id: str, start: int, end: int) -> list[dict]:
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
            break
        all_eps.extend(eps)
        if len(eps) < API_CHUNK:
            break
        pos = batch_end + 1

    return all_eps


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

    m = re.search(
        r'<script[^>]+(?:id=["\']__NUXT_DATA__["\']|type=["\']application/json["\'])[^>]*>'
        r'(.*?)</script>', text, re.DOTALL
    )
    if m:
        m2 = re.search(r'https://vixcloud\.co/embed/[^"\'\\<\s]+', m.group(1))
        if m2:
            return unescape(m2.group(0))

    return None


def _ensure_playwright_chromium() -> bool:
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
            for _ in range(20):
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


def search_catalog(base_url: str, query: str, filters: dict | None = None) -> list[dict]:
    body: dict = {
        "title":  query,
        "type":   "",
        "year":   "",
        "order":  "Più visti",
        "status": "",
        "genres": [],
        "offset": 0,
        "dubbed": False,
        "season": "",
    }
    if filters:
        for k, v in filters.items():
            if k in body:
                body[k] = v

    session = requests.Session()
    page = session.get(f"{base_url}/archivio", impersonate=IMPERSONATE, timeout=10)
    page.raise_for_status()
    m = re.search(r'name="csrf-token" content="([^"]+)"', page.text)
    csrf_token = m.group(1) if m else ""

    headers = {
        "Content-Type":     "application/json",
        "Accept":           "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRF-TOKEN":     csrf_token,
        "Referer":          f"{base_url}/archivio",
    }

    try:
        r = session.post(
            f"{base_url}/archivio/get-animes",
            json=body, headers=headers,
            impersonate=IMPERSONATE, timeout=15,
        )
        r.raise_for_status()
        data  = r.json()
        items = data.get("records", data.get("data", data)) if isinstance(data, dict) else data
        if not isinstance(items, list):
            items = []
        result = [
            {
                "anime_id": str(item.get("id", "")),
                "slug":     item.get("slug", ""),
                "title":    item.get("title_eng") or item.get("title") or item.get("slug", ""),
                "type":     item.get("type", ""),
                "year":     str(item.get("date", "") or ""),
                "status":   item.get("status", ""),
                "score":    str(item.get("score", "") or ""),
                "url":      f"{base_url}/anime/{item.get('id', '')}-{item.get('slug', '')}",
            }
            for item in items
            if item.get("id") and item.get("slug")
        ]
        with open(_LOG_AU, "a", encoding="utf-8") as f:
            f.write(f"[OK] POST {base_url}/archivio/get-animes\n")
            f.write(f"     body={json.dumps(body, ensure_ascii=False)}\n")
            f.write(f"     items={len(result)}\n")
        return result
    except Exception as e:
        with open(_LOG_AU, "a", encoding="utf-8") as f:
            f.write(f"[ERR] POST {base_url}/archivio/get-animes\n")
            f.write(f"      body={json.dumps(body, ensure_ascii=False)}\n")
            f.write(f"      {type(e).__name__}: {e}\n")
        raise
