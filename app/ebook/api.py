import re
import threading
import urllib.parse
from pathlib import Path

from bs4 import BeautifulSoup
from curl_cffi import requests as _cf

from ..config import _CFG, IMPERSONATE

_LOG         = Path(__file__).parent.parent.parent / "ebook_debug.log"
_PROFILE_DIR = Path(__file__).parent.parent.parent / ".playwright_profile"
_ZLIB_BASE   = "https://z-library.sk"

# Un solo Chromium alla volta (contesto persistente non ammette accessi paralleli)
_pw_lock = threading.Lock()

EBOOK_LANG_OPTS = [
    ("Italiano",  "it"),
    ("Inglese",   "en"),
    ("Spagnolo",  "es"),
    ("Francese",  "fr"),
    ("Tedesco",   "de"),
]

EBOOK_FORMAT_OPTS = [
    ("EPUB",  "epub"),
    ("PDF",   "pdf"),
    ("MOBI",  "mobi"),
    ("FB2",   "fb2"),
]

EBOOK_SOURCE_OPTS = [
    ("Entrambe",       "all"),
    ("Anna's Archive", "annas"),
    ("Z-Library",      "zlib"),
]

_ZLIB_LANG = {
    "it": "italian",
    "en": "english",
    "es": "spanish",
    "fr": "french",
    "de": "german",
}


def _log(msg: str) -> None:
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


# ── Playwright helper (bypassa Cloudflare JS challenge) ───────────────────────

def _pw_html(url: str, extra_cookies: list[dict] | None = None) -> str:
    """
    Naviga url in un Chromium reale con contesto persistente.
    Risolve automaticamente Cloudflare Under Attack / JS challenge.
    I cookie (incluso cf_clearance) vengono salvati in .playwright_profile
    e riusati nelle chiamate successive — la prima volta è lenta (~15s),
    poi è rapida.
    """
    _PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _log("[pw] playwright non installato — eseguire: uv run playwright install chromium")
        return ""

    with _pw_lock:
        try:
            with sync_playwright() as pw:
                ctx = pw.chromium.launch_persistent_context(
                    str(_PROFILE_DIR),
                    headless=True,
                    locale="it-IT",
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                if extra_cookies:
                    ctx.add_cookies(extra_cookies)
                page = ctx.new_page()
                _log(f"[pw] → {url}")
                page.goto(url, wait_until="networkidle", timeout=30000)
                html = page.content()
                ctx.close()
                return html
        except Exception as e:
            _log(f"[pw] Errore: {type(e).__name__}: {e}")
            return ""


# ── Anna's Archive ─────────────────────────────────────────────────────────────

def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


def _search_annas(query: str, lang: str = "", fmt: str = "", limit: int = 25) -> list[dict]:
    params: dict[str, str] = {"q": query, "sort": ""}
    if lang:
        params["lang"] = lang
    if fmt:
        params["ext"] = fmt
    url  = "https://annas-archive.li/search?" + urllib.parse.urlencode(params)
    html = _pw_html(url)
    if not html:
        return []
    try:
        items = re.findall(
            r'href="(/md5/([a-f0-9A-F]{32}))"[^>]*>(.*?)</a>',
            html, re.DOTALL | re.IGNORECASE,
        )
        _log(f"[annas] blocchi md5 trovati: {len(items)}")
        if not items:
            _log(f"[annas] HTML snippet: {html[:1500].replace(chr(10), ' ')}")

        out:  list[dict] = []
        seen: set[str]   = set()
        for _, md5, inner in items:
            if md5 in seen:
                continue
            seen.add(md5)
            text   = re.sub(r"\s+", " ", _strip_tags(inner)).strip()
            parts  = [p.strip() for p in text.split("  ") if p.strip()]
            title  = parts[0] if parts else ""
            author = parts[1] if len(parts) > 1 else ""
            meta   = parts[2] if len(parts) > 2 else ""

            meta_parts    = [x.strip() for x in meta.split(",")]
            detected_lang = lang
            detected_fmt  = fmt
            year = size = ""
            for p in meta_parts:
                pl = p.lower()
                if re.match(r"^\d{4}$", p):
                    year = p
                elif re.search(r"\d+(\.\d+)?\s*(mb|kb|gb)", pl):
                    size = p
                elif pl in ("epub", "pdf", "mobi", "fb2", "djvu", "azw3"):
                    detected_fmt = pl
                elif re.match(r"^[a-z]{2}(-[a-z]{2})?$", pl):
                    detected_lang = pl

            if not title:
                continue
            out.append({
                "source":       "annas",
                "title":        title,
                "author":       author,
                "year":         year,
                "format":       detected_fmt or "epub",
                "language":     detected_lang or lang,
                "filesize":     size,
                "md5":          md5,
                "book_id":      "",
                "dl_hash":      "",
                "download_url": "",
            })
            if len(out) >= limit:
                break

        _log(f"[annas] '{query}' → {len(out)} risultati")
        return out
    except Exception as e:
        _log(f"[annas] Errore parsing: {type(e).__name__}: {e}")
        return []


# ── Z-Library ──────────────────────────────────────────────────────────────────

def _zlib_login_cookies() -> list[dict]:
    """Login via curl_cffi, restituisce cookie per Playwright."""
    email    = _CFG.get("zlib_email",    "").strip()
    password = _CFG.get("zlib_password", "").strip()
    if not email or not password:
        _log("[zlib] Credenziali mancanti — configurarle in Impostazioni")
        return []
    try:
        resp = _cf.post(
            f"{_ZLIB_BASE}/rpc.php",
            data={
                "isModal": True, "email": email, "password": password,
                "site_mode": "books", "action": "login",
                "isSingleLogin": 1, "redirectUrl": "", "gg_json_mode": 1,
            },
            impersonate=IMPERSONATE, verify=False, timeout=20,
        )
        _log(f"[zlib] login status={resp.status_code}")
        js = resp.json()
        if js.get("response", {}).get("validationError"):
            _log(f"[zlib] Login fallito: {js['response']}")
            return []
        cookies = [
            {
                "name": k, "value": v,
                "domain": "z-library.sk", "path": "/",
                "sameSite": "Lax",
            }
            for k, v in resp.cookies.items()
        ]
        _log(f"[zlib] login ok, {len(cookies)} cookie")
        return cookies
    except Exception as e:
        _log(f"[zlib] Errore login: {type(e).__name__}: {e}")
        return []


def _search_zlib(query: str, lang: str = "", fmt: str = "", limit: int = 25) -> list[dict]:
    cookies = _zlib_login_cookies()
    if not cookies:
        return []
    try:
        url = f"{_ZLIB_BASE}/s/{urllib.parse.quote(query)}?"
        if lang and lang in _ZLIB_LANG:
            url += f"&languages%5B%5D={_ZLIB_LANG[lang]}"
        if fmt:
            url += f"&extensions%5B%5D={fmt}"

        html = _pw_html(url, extra_cookies=cookies)
        if not html:
            return []

        soup = BeautifulSoup(html, "lxml")
        box  = soup.find("div", {"id": "searchResultBox"})
        if not box:
            _log(f"[zlib] searchResultBox non trovato. snippet: {html[:500].replace(chr(10), ' ')}")
            return []

        out: list[dict] = []
        for book_div in box.find_all("div", {"class": "book-item"})[:limit]:
            card = book_div.find("z-bookcard")
            if not card:
                continue
            title_el  = card.find("div", {"slot": "title"})
            author_el = card.find("div", {"slot": "author"})
            title     = title_el.text.strip()  if title_el  else ""
            author    = author_el.text.strip() if author_el else ""
            if not title:
                continue
            book_href = card.get("href", "")
            out.append({
                "source":       "zlib",
                "title":        title,
                "author":       "; ".join(a.strip() for a in author.split(";") if a.strip()),
                "year":         card.get("year",      ""),
                "format":       (card.get("extension", fmt) or fmt).lower(),
                "language":     card.get("language",  lang),
                "filesize":     card.get("filesize",  ""),
                "md5":          "",
                "book_id":      card.get("id",        ""),
                "dl_hash":      "",
                "download_url": f"{_ZLIB_BASE}{book_href}" if book_href else "",
            })

        _log(f"[zlib] '{query}' → {len(out)} risultati")
        return out
    except Exception as e:
        _log(f"[zlib] Errore ricerca: {type(e).__name__}: {e}")
        return []


# ── Combined search ────────────────────────────────────────────────────────────

def search_ebooks(
    query:  str,
    lang:   str = "it",
    fmt:    str = "epub",
    source: str = "all",
    limit:  int = 25,
) -> list[dict]:
    results: list[dict] = []
    if source in ("all", "annas"):
        results.extend(_search_annas(query, lang, fmt, limit))
    if source in ("all", "zlib"):
        results.extend(_search_zlib(query, lang, fmt, limit))

    seen:    set[tuple[str, str]] = set()
    deduped: list[dict]           = []
    for r in results:
        key = (r["title"].lower()[:60], r["author"].lower()[:30])
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    return deduped


# ── Download URL resolution ────────────────────────────────────────────────────

def get_annas_download_url(md5: str) -> str:
    _log(f"[annas] get_download_url md5={md5}")
    html = _pw_html(f"https://annas-archive.li/md5/{md5}")
    if not html:
        return ""
    for pat in (
        r'href="(/slow_download/[^"]+)"',
        r'href="(/fast_download/[^"]+)"',
    ):
        m = re.search(pat, html)
        if m:
            return "https://annas-archive.li" + m.group(1)
    _log(f"[annas] nessun link download per md5={md5}")
    return ""


def get_zlib_download_url(book_page_url: str) -> str:
    _log(f"[zlib] get_download_url page={book_page_url}")
    cookies = _zlib_login_cookies()
    html    = _pw_html(book_page_url, extra_cookies=cookies)
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "lxml")
        btn  = soup.find("a", {"class": lambda c: c and "addDownloadedBook" in c})
        if btn:
            href = btn.get("href", "")
            if href:
                url = href if href.startswith("http") else f"{_ZLIB_BASE}{href}"
                _log(f"[zlib] download URL: {url}")
                return url
        _log(f"[zlib] pulsante download non trovato")
    except Exception as e:
        _log(f"[zlib] get_download_url errore: {e}")
    return ""


def download_zlib_book(book_page_url: str, dest: Path, log_fd=None) -> bool:
    """Scarica un libro Z-Library interamente tramite Playwright (bypassa Cloudflare)."""
    cookies = _zlib_login_cookies()
    if not cookies:
        if log_fd:
            log_fd.write("[ERROR] Login Z-Library fallito — controllare credenziali in Impostazioni\n")
        return False

    _PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp" + dest.suffix)
    tmp.unlink(missing_ok=True)

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
    except ImportError:
        if log_fd:
            log_fd.write("[ERROR] playwright non installato\n")
        return False

    with _pw_lock:
        try:
            with sync_playwright() as pw:
                ctx = pw.chromium.launch_persistent_context(
                    str(_PROFILE_DIR),
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                    accept_downloads=True,
                )
                ctx.add_cookies(cookies)
                page = ctx.new_page()
                _log(f"[pw][zlib] → {book_page_url}")
                page.goto(book_page_url, wait_until="networkidle", timeout=30000)

                btn = page.query_selector("a.addDownloadedBook")
                if not btn:
                    _log("[pw][zlib] pulsante download non trovato")
                    if log_fd:
                        log_fd.write("[ERROR] pulsante download non trovato sulla pagina\n")
                    ctx.close()
                    return False

                with page.expect_download(timeout=120000) as dl_info:
                    btn.click()

                download = dl_info.value
                suggested = download.suggested_filename or dest.name
                _log(f"[pw][zlib] download: {suggested}")
                if log_fd:
                    log_fd.write(f"[download] {suggested}\n")
                    log_fd.flush()

                download.save_as(str(tmp))
                ctx.close()

            tmp.rename(dest)
            _log(f"[pw][zlib] salvato: {dest}")
            return True
        except Exception as e:
            _log(f"[pw][zlib] errore: {type(e).__name__}: {e}")
            if log_fd:
                log_fd.write(f"[ERROR] {e}\n")
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            return False
