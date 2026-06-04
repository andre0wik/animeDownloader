"""
MangaWorld (mangaworld.mx) — sito italiano di manga scan.
"""
import re
import time
import zipfile
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests

from .base import MangaPlatform
from ..mangadex.download import _archive_to_pdf
from ..config import _CFG

if TYPE_CHECKING:
    from ..models import QueueItem

_SESSION  = cffi_requests.Session(impersonate="chrome124")
_BASE_URL = "https://www.mangaworld.mx"
_CDN_URL  = "https://cdn.mangaworld.mx"

_STATUS_OPTS = [
    ("In corso",  "ongoing"),
    ("Finito",    "completed"),
    ("In pausa",  "paused"),
    ("Droppato",  "dropped"),
    ("Upcoming",  "upcoming"),
]

_GENRES = [
    ("Azione",          "azione"),
    ("Avventura",       "avventura"),
    ("Commedia",        "commedia"),
    ("Drammatico",      "drammatico"),
    ("Ecchi",           "ecchi"),
    ("Fantasy",         "fantasy"),
    ("Gender Bender",   "gender-bender"),
    ("Horror",          "horror"),
    ("Josei",           "josei"),
    ("Mecha",           "mecha"),
    ("Mistero",         "mistero"),
    ("Psicologico",     "psicologico"),
    ("Romantico",       "romantico"),
    ("Sci-Fi",          "sci-fi"),
    ("Seinen",          "seinen"),
    ("Shojo",           "shojo"),
    ("Shonen",          "shonen"),
    ("Slice of Life",   "slice-of-life"),
    ("Soprannaturale",  "soprannaturale"),
    ("Sportivo",        "sportivo"),
    ("Storico",         "storico"),
    ("Surrealista",     "surrealista"),
    ("Thriller",        "thriller"),
    ("Tragico",         "tragico"),
    ("Yaoi",            "yaoi"),
    ("Yuri",            "yuri"),
]

_SORT_OPTS = [
    ("Meno recenti",    "less_recent"),
    ("Più recenti",     "most_recent"),
    ("Più letti",       "most_read"),
    ("Meno letti",      "less_read"),
    ("A-Z",             "a-z"),
    ("Z-A",             "z-a"),
    ("Aggiornato",      "newest"),
    ("Voto alto",       "high_rating"),
    ("Voto basso",      "low_rating"),
]


def _num_key(n: str) -> float:
    try:
        return float(n)
    except (ValueError, TypeError):
        return float("inf")


def _extract_manga_id(href: str) -> str | None:
    """Returns '{numeric_id}/{slug}' from a /manga/ID/slug URL, or None."""
    m = re.search(r"/manga/(\d+)/([^/?#]+)", href)
    return f"{m.group(1)}/{m.group(2)}" if m else None


class MangaWorldPlatform(MangaPlatform):
    id        = "mangaworld"
    name      = "MangaWorld"
    dl_subdir = "MangaWorld"

    supported_filters     = {"status", "genres", "order"}
    supports_empty_search = True

    status_opts = _STATUS_OPTS
    genres      = _GENRES
    order_opts  = _SORT_OPTS

    # ------------------------------------------------------------------ search

    def search(self, title: str, filters: dict) -> list[dict]:
        params: dict = {}
        if title:
            params["keyword"] = title
        if filters.get("status"):
            params["status"] = filters["status"]
        if filters.get("order"):
            params["sort"] = filters["order"]
        genre_list = filters.get("genres") or []
        if genre_list:
            params["genre"] = genre_list[0]

        try:
            resp = _SESSION.get(
                f"{_BASE_URL}/archive",
                params=params,
                timeout=20,
            )
            soup = BeautifulSoup(resp.text, "lxml")
            return self._parse_archive(soup)
        except Exception as e:
            raise RuntimeError(f"Ricerca MangaWorld fallita: {e}") from e

    def _parse_archive(self, soup: BeautifulSoup) -> list[dict]:
        seen:    set[str]   = set()
        results: list[dict] = []

        # Find all manga links by URL pattern; deduplicate by manga_id
        for a in soup.find_all("a", href=re.compile(r"/manga/\d+/[^/?#]+")):
            href     = a.get("href", "")
            manga_id = _extract_manga_id(href)
            if not manga_id or manga_id in seen:
                continue

            # Title: prefer <a title="..."> attribute, then text
            title = (a.get("title") or a.get_text(strip=True)).strip()
            if not title:
                continue

            # Walk up to the card container to extract status and genres
            card = a
            for _ in range(6):
                card = card.parent
                if card is None:
                    break
                card_text = card.get_text(" ", strip=True)
                if any(s[0] in card_text for s in _STATUS_OPTS):
                    break

            status = ""
            genres = ""
            if card is not None:
                card_text = card.get_text(" ", strip=True)
                for label, val in _STATUS_OPTS:
                    if label in card_text:
                        status = label
                        break
                genre_links = card.find_all("a", href=re.compile(r"[?&]genre="))
                genres = ", ".join(g.get_text(strip=True) for g in genre_links[:4])

            seen.add(manga_id)
            results.append({
                "manga_id":       manga_id,
                "title":          title,
                "status":         status,
                "content_rating": "",
                "original_lang":  "ja",
                "genres":         genres,
                "languages":      "it",
                "platform":       self.id,
                "_url":           href if href.startswith("http") else f"{_BASE_URL}{href}",
            })

        return results

    # ------------------------------------------------------------- get_chapters

    def get_chapters(self, manga_id: str, lang: str) -> list[dict]:
        url = f"{_BASE_URL}/manga/{manga_id}"
        try:
            resp = _SESSION.get(url, timeout=20)
            soup = BeautifulSoup(resp.text, "lxml")
        except Exception as e:
            raise RuntimeError(f"Impossibile caricare la pagina manga: {e}") from e

        chapters:    list[dict] = []
        current_vol: str       = ""
        seen_ids:    set[str]  = set()

        for node in soup.find_all(["h5", "a"]):
            if node.name == "h5":
                vol_m = re.search(r"[Vv]olume\s*([\d.]+)", node.get_text())
                current_vol = vol_m.group(1) if vol_m else ""
                continue

            href = node.get("href", "")
            id_m = re.search(r"/read/([a-f0-9]{24})", href)
            if not id_m:
                continue

            ch_id = id_m.group(1)
            if ch_id in seen_ids:
                continue
            seen_ids.add(ch_id)

            text  = node.get_text(" ", strip=True)
            num_m = re.search(r"[Cc]apitolo\s+([\d.]+)", text)
            num   = num_m.group(1) if num_m else re.sub(r"\s+", " ", text)

            full_url = href if href.startswith("http") else f"{_BASE_URL}{href}"

            chapters.append({
                "id":     ch_id,
                "number": num,
                "volume": current_vol,
                "title":  "",
                "pages":  0,
                "lang":   "it",
                "_url":   full_url,
            })

        chapters.sort(key=lambda c: _num_key(c["number"]))
        return chapters

    # ------------------------------------------------------------- download

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
            img_urls = self._get_page_urls(chapter_url, log_fd)
            if not img_urls:
                return False

            total = len(img_urls)
            item.out_dir.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_STORED) as zf:
                for i, img_url in enumerate(img_urls, 1):
                    ext      = img_url.rsplit(".", 1)[-1].split("?")[0].lower() or "jpg"
                    arc_name = f"{i:04d}.{ext}"
                    for attempt in range(3):
                        try:
                            ir = _SESSION.get(
                                img_url, timeout=45,
                                headers={"Referer": chapter_url},
                            )
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

    def _get_page_urls(self, chapter_url: str, log_fd=None) -> list[str]:
        """
        Fetches the chapter reader page and returns URLs for all pages.
        MangaWorld shows one page at a time; images are on a CDN at
        .../N.jpg  where N increments from 1.
        Strategy:
          1. Fetch page 1, extract the first CDN image URL.
          2. Derive the base CDN path (everything before /N.jpg).
          3. Read the total page count from the navigation (e.g. "1 / 10").
          4. Construct all URLs.
        """
        try:
            resp = _SESSION.get(chapter_url, timeout=20)
            soup = BeautifulSoup(resp.text, "lxml")
        except Exception as e:
            if log_fd:
                log_fd.write(f"[ERROR] Caricamento pagina capitolo: {e}\n")
            return []

        # -- Find the first page image
        first_img_url = ""
        for img in soup.find_all("img"):
            src = (img.get("src") or img.get("data-src") or "").strip()
            if "cdn.mangaworld" in src and re.search(r"/\d+\.(jpg|png|webp)", src):
                first_img_url = src
                break

        if not first_img_url:
            if log_fd:
                log_fd.write("[ERROR] Nessuna immagine CDN trovata nella pagina\n")
            return []

        # -- Extract CDN base path and extension
        m = re.match(r"(https://cdn\.mangaworld\.[^/]+/chapters/.+?/)(\d+)\.(jpg|png|webp)",
                     first_img_url)
        if not m:
            if log_fd:
                log_fd.write(f"[ERROR] URL CDN non riconosciuto: {first_img_url}\n")
            return []

        base_path = m.group(1)   # e.g. https://cdn.mangaworld.mx/chapters/.../
        ext       = m.group(3)   # e.g. jpg

        # -- Extract total page count
        total = self._parse_total_pages(soup)

        # -- Fallback: probe pages until 404
        if total <= 0:
            total = self._probe_page_count(base_path, ext, log_fd)

        if total <= 0:
            if log_fd:
                log_fd.write("[ERROR] Impossibile determinare il numero di pagine\n")
            return []

        return [f"{base_path}{i}.{ext}" for i in range(1, total + 1)]

    @staticmethod
    def _parse_total_pages(soup: BeautifulSoup) -> int:
        """
        Tries various patterns to extract total page count:
          - "1 / 10" or "1/10" in text
          - Page navigation links with the highest page number
        """
        text = soup.get_text(" ")

        # "X / Y" pattern (current page / total)
        m = re.search(r"\b1\s*/\s*(\d+)\b", text)
        if m:
            return int(m.group(1))

        # Links labelled "N/total" — find the max total
        totals = re.findall(r"\b\d+\s*/\s*(\d+)\b", text)
        if totals:
            return max(int(t) for t in totals)

        # Fallback: count page navigation links pointing to the same chapter
        page_links = soup.find_all("a", href=re.compile(r"/read/[a-f0-9]{24}/\d+$"))
        if page_links:
            nums = []
            for a in page_links:
                pm = re.search(r"/(\d+)$", a.get("href", ""))
                if pm:
                    nums.append(int(pm.group(1)))
            if nums:
                return max(nums)

        return 0

    def _probe_page_count(self, base_path: str, ext: str, log_fd=None) -> int:
        """Binary-search style probe to find the last valid page."""
        lo, hi = 1, 1
        # Quick upper-bound scan
        while True:
            url  = f"{base_path}{hi}.{ext}"
            try:
                r = _SESSION.head(url, timeout=10)
                if r.status_code >= 400:
                    break
                hi *= 2
                if hi > 512:
                    break
            except Exception:
                break

        # Binary search between lo and hi
        while lo < hi:
            mid = (lo + hi + 1) // 2
            url = f"{base_path}{mid}.{ext}"
            try:
                r = _SESSION.head(url, timeout=10)
                if r.status_code < 400:
                    lo = mid
                else:
                    hi = mid - 1
            except Exception:
                hi = mid - 1

        return lo
