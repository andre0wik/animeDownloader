"""
Tapas.io scraper.
Accesso base senza login per capitoli free.
"""
import re
import time
import urllib.parse
import zipfile
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests

from .base import MangaPlatform
from ..mangadex.download import _archive_to_pdf
from ..config import _CFG

if TYPE_CHECKING:
    from ..models import QueueItem

_SESSION = cffi_requests.Session(impersonate="chrome124")
_BASE    = "https://tapas.io"

_GENRES = [
    ("Action",       "ACTION"),
    ("Adventure",    "ADVENTURE"),
    ("Comedy",       "COMEDY"),
    ("Drama",        "DRAMA"),
    ("Fantasy",      "FANTASY"),
    ("Horror",       "HORROR"),
    ("Romance",      "ROMANCE"),
    ("Sci-Fi",       "SF"),
    ("Slice of Life","SLICE_OF_LIFE"),
    ("Thriller",     "THRILLER"),
]


def _num_key(n: str) -> float:
    try:
        return float(n)
    except (ValueError, TypeError):
        return float("inf")


class TapasPlatform(MangaPlatform):
    id        = "tapas"
    name      = "Tapas"
    dl_subdir = "Tapas"

    supported_filters = set()
    genres            = _GENRES  # solo per display nei risultati, non filtrabile via URL

    # ------------------------------------------------------------------ search

    def search(self, title: str, filters: dict) -> list[dict]:
        if not title:
            return []
        try:
            url  = f"{_BASE}/search?q={urllib.parse.quote(title)}&t=COMIC"
            resp = _SESSION.get(url, timeout=15)
            soup = BeautifulSoup(resp.text, "lxml")
            results = []
            for item in soup.select("li.search-item-wrap"):
                a = item.select_one("a[href*='/series/']")
                if not a:
                    continue
                href     = a.get("href", "")
                slug     = href.strip("/").split("/")[-1]
                title_el = item.select_one(".title")
                t        = title_el.get_text(strip=True) if title_el else slug
                tags     = [tg.get_text(strip=True) for tg in item.select("p.tag a")]
                results.append({
                    "manga_id":       slug,
                    "title":          t,
                    "status":         "",
                    "content_rating": "",
                    "original_lang":  "",
                    "genres":         ", ".join(tags[:3]),
                    "languages":      "en",
                    "platform":       self.id,
                    "_url":           f"{_BASE}{href}" if href.startswith("/") else href,
                })
            return results
        except Exception as e:
            raise RuntimeError(f"Ricerca Tapas fallita: {e}") from e

    # ---------------------------------------------------------------- chapters

    def get_chapters(self, manga_id: str, lang: str) -> list[dict]:
        chapters: list[dict] = []
        page = 1
        while True:
            try:
                url  = f"{_BASE}/series/{manga_id}/episodes?page={page}&sort=OLDEST"
                resp = _SESSION.get(url, timeout=15)
                soup = BeautifulSoup(resp.text, "lxml")
                items = soup.select(".episode-item, li.episode")
                if not items:
                    break
                for item in items:
                    a = item.select_one("a[href*='/episode/']")
                    if not a:
                        continue
                    href  = a.get("href", "")
                    m     = re.search(r"/episode/(\d+)", href)
                    ep_id = m.group(1) if m else href
                    ep_m  = re.search(r"[Ee]p\.?\s*(\d+)|#(\d+)", a.get_text())
                    num   = ep_m.group(1) or ep_m.group(2) if ep_m else ep_id
                    t_el  = item.select_one(".title, .ep-title")
                    ep_t  = t_el.get_text(strip=True) if t_el else ""
                    chapters.append({
                        "id":     ep_id,
                        "number": num,
                        "volume": "",
                        "title":  ep_t,
                        "pages":  0,
                        "lang":   "en",
                        "_url":   f"{_BASE}{href}" if href.startswith("/") else href,
                    })
                if len(items) < 20:
                    break
                page += 1
                time.sleep(0.5)
            except Exception:
                break
        return sorted(chapters, key=lambda c: _num_key(c["number"]))

    # --------------------------------------------------------------- download

    def download_chapter(self, item: "QueueItem", log_fd=None) -> bool:
        chapter_url = item.episode.get("_url", "")
        chapter_num = item.episode.get("number", "?")

        if not chapter_url:
            if log_fd:
                log_fd.write("[ERROR] URL capitolo mancante\n")
            return False

        try:
            num_f   = float(chapter_num)
            num_str = f"{num_f:07.1f}" if num_f != int(num_f) else f"{int(num_f):04d}"
        except (ValueError, TypeError):
            num_str = str(chapter_num)

        cbz_path = item.out_dir / f"Ch {num_str}.cbz"
        if cbz_path.exists():
            return True

        tmp_path = cbz_path.with_suffix(".tmp.cbz")
        tmp_path.unlink(missing_ok=True)

        try:
            resp = _SESSION.get(chapter_url, timeout=20)
            soup = BeautifulSoup(resp.text, "lxml")
            imgs = soup.select(".comic-viewer img, .viewer-img img, .page img")
            img_urls = []
            for img in imgs:
                src = (img.get("data-src") or img.get("src") or "").strip()
                if src.startswith("http"):
                    img_urls.append(src)

            if not img_urls:
                if log_fd:
                    log_fd.write("[ERROR] Nessuna immagine (possibile capitolo a pagamento)\n")
                return False

            total = len(img_urls)
            with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_STORED) as zf:
                for i, img_url in enumerate(img_urls, 1):
                    ext      = img_url.rsplit(".", 1)[-1].split("?")[0].lower() or "jpg"
                    arc_name = f"{i:04d}.{ext}"
                    for attempt in range(3):
                        try:
                            ir = _SESSION.get(img_url, timeout=45,
                                              headers={"Referer": _BASE + "/"})
                            zf.writestr(arc_name, ir.content)
                            break
                        except Exception:
                            if attempt == 2:
                                raise
                            time.sleep(2)
                    pct = i / total * 100
                    if log_fd:
                        log_fd.write(f"[download]  {pct:.1f}% at 0.0 MiB/s ETA 00:00\n")
                        log_fd.flush()

            tmp_path.rename(cbz_path)
            if _CFG.get("cbz_to_pdf"):
                _archive_to_pdf(cbz_path, log_fd)
            return True

        except Exception as e:
            if log_fd:
                log_fd.write(f"[ERROR] download: {e}\n")
            tmp_path.unlink(missing_ok=True)
            return False
