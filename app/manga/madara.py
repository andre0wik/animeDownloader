"""
Shared base for WordPress Madara-theme manga sites
(Toonily, Manhwatop, etc.)
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

_STATUS_OPTS = [
    ("In corso",   "on-going"),
    ("Completato", "end"),
    ("Hiatus",     "on-hold"),
    ("Abbandonato","canceled"),
]


def _num_key(n: str) -> float:
    try:
        return float(n)
    except (ValueError, TypeError):
        return float("inf")


class MadaraPlatform(MangaPlatform):
    base_url:   str = ""
    manga_path: str = "manga"   # Toonily overrides with "serie"

    supported_filters = {"status", "genres"}
    status_opts       = _STATUS_OPTS

    # ------------------------------------------------------------------ search

    def search(self, title: str, filters: dict) -> list[dict]:
        if not title:
            return self._browse_filtered(filters)
        headers = {
            "Referer": self.base_url + "/",
            "X-Requested-With": "XMLHttpRequest",
        }
        try:
            resp = _SESSION.post(
                f"{self.base_url}/wp-admin/admin-ajax.php",
                data={"action": "wp-manga-search-manga", "title": title},
                headers=headers,
                timeout=15,
            )
            data = resp.json()
            if data.get("success") and data.get("data"):
                results = []
                for item in data["data"]:
                    url  = item.get("url", "")
                    slug = url.rstrip("/").split("/")[-1]
                    # Madara AJAX uses "label" on some sites, "title" on others
                    t = item.get("label") or item.get("title") or item.get("value") or ""
                    results.append({
                        "manga_id":       slug,
                        "title":          t,
                        "status":         "",
                        "content_rating": "",
                        "original_lang":  "ko",
                        "genres":         "",
                        "languages":      "",
                        "platform":       self.id,
                        "_url":           url,
                    })
                return results
        except Exception:
            pass
        return self._search_html(title, filters)

    def _browse_filtered(self, filters: dict, max_pages: int = 5) -> list[dict]:
        """Browse manga archive by genre/status when no title is given (paginated)."""
        status = filters.get("status", "")
        genres = filters.get("genres", [])

        base_qs = ["post_type=wp-manga"]
        if status:
            base_qs.append(f"status={urllib.parse.quote(status)}")
        for g in genres:
            base_qs.append(f"genre[]={urllib.parse.quote(g)}")
        base_qs_str = "&".join(base_qs)

        results: list[dict] = []
        seen:    set[str]   = set()

        for page in range(1, max_pages + 1):
            paged = f"&paged={page}" if page > 1 else ""
            url   = f"{self.base_url}/?{base_qs_str}{paged}"
            try:
                resp  = _SESSION.get(url, timeout=15)
                soup  = BeautifulSoup(resp.text, "lxml")
                items = soup.select(".c-tabs-item__content, .page-item-detail")
                if not items:
                    break
                for item in items:
                    a = item.select_one("h3.h4 a, .post-title h3 a, .post-title a")
                    if not a:
                        continue
                    href = a.get("href", "")
                    slug = href.rstrip("/").split("/")[-1]
                    if slug in seen:
                        continue
                    seen.add(slug)
                    t       = a.get_text(strip=True)
                    st_el   = item.select_one(".mg_status .summary-content")
                    g_texts = ", ".join(
                        g.get_text(strip=True)
                        for g in item.select(".mg_genres .summary-content a")[:3]
                    )
                    results.append({
                        "manga_id":       slug,
                        "title":          t,
                        "status":         st_el.get_text(strip=True) if st_el else "",
                        "content_rating": "",
                        "original_lang":  "ko",
                        "genres":         g_texts,
                        "languages":      "",
                        "platform":       self.id,
                        "_url":           href,
                    })
                if page > 1:
                    time.sleep(0.3)
            except Exception as e:
                if not results:
                    raise RuntimeError(f"Sfoglia fallita: {e}") from e
                break

        return results

    def _search_html(self, title: str, filters: dict) -> list[dict]:
        qs = urllib.parse.urlencode({"s": title, "post_type": "wp-manga"})
        try:
            resp = _SESSION.get(f"{self.base_url}/?{qs}", timeout=15)
            soup = BeautifulSoup(resp.text, "lxml")
            results = []
            for item in soup.select(".c-tabs-item__content, .page-item-detail"):
                a = item.select_one("h3.h4 a, .post-title h3 a, .post-title a")
                if not a:
                    continue
                href   = a.get("href", "")
                slug   = href.rstrip("/").split("/")[-1]
                t      = a.get_text(strip=True)
                st_el  = item.select_one(".mg_status .summary-content")
                status = st_el.get_text(strip=True) if st_el else ""
                genres = ", ".join(
                    g.get_text(strip=True)
                    for g in item.select(".mg_genres .summary-content a")[:3]
                )
                results.append({
                    "manga_id":       slug,
                    "title":          t,
                    "status":         status,
                    "content_rating": "",
                    "original_lang":  "ko",
                    "genres":         genres,
                    "languages":      "",
                    "platform":       self.id,
                    "_url":           href,
                })
            return results
        except Exception as e:
            raise RuntimeError(f"Ricerca fallita: {e}") from e

    # ------------------------------------------------------------ chapters

    def _get_page_soup(self, slug: str) -> tuple[str, "BeautifulSoup | None"]:
        """Returns (post_id, soup). post_id may be "" if not found."""
        url  = f"{self.base_url}/{self.manga_path}/{slug}/"
        try:
            resp = _SESSION.get(url, timeout=15)
            soup = BeautifulSoup(resp.text, "lxml")
        except Exception:
            return "", None

        # Try #manga-chapters-holder[data-id]
        el = soup.select_one("#manga-chapters-holder[data-id]")
        if el and el.get("data-id"):
            return el["data-id"], soup

        # Try body class postid-\d+
        body = soup.find("body")
        if body:
            for cls in (body.get("class") or []):
                m = re.match(r"postid-(\d+)", cls)
                if m:
                    return m.group(1), soup

        return "", soup

    def get_chapters(self, manga_id: str, lang: str) -> list[dict]:
        post_id, soup = self._get_page_soup(manga_id)
        referer = f"{self.base_url}/{self.manga_path}/{manga_id}/"
        chapters: list[dict] = []

        # Attempt 1: manga_get_chapters AJAX (requires post_id)
        if post_id:
            try:
                resp = _SESSION.post(
                    f"{self.base_url}/wp-admin/admin-ajax.php",
                    data={"action": "manga_get_chapters", "manga": post_id},
                    headers={"Referer": referer},
                    timeout=15,
                )
                ch_soup = BeautifulSoup(resp.text, "lxml")
                chapters = self._parse_chapter_list(ch_soup, lang)
            except Exception:
                pass

        # Attempt 2: ajax/chapters/ POST on the manga page
        if not chapters:
            try:
                resp2 = _SESSION.post(
                    f"{self.base_url}/{self.manga_path}/{manga_id}/ajax/chapters/",
                    data={},
                    headers={"Referer": referer},
                    timeout=15,
                )
                ch_soup2 = BeautifulSoup(resp2.text, "lxml")
                chapters = self._parse_chapter_list(ch_soup2, lang)
            except Exception:
                pass

        # Attempt 3: parse directly from manga page HTML
        if not chapters and soup:
            chapters = self._parse_chapter_list(soup, lang)

        return sorted(chapters, key=lambda c: _num_key(c["number"]))

    @staticmethod
    def _parse_chapter_list(soup: "BeautifulSoup", lang: str) -> list[dict]:
        chapters = []
        for li in soup.select("li.wp-manga-chapter"):
            a = li.select_one("a")
            if not a:
                continue
            href = a.get("href", "")
            text = a.get_text(strip=True)
            m    = re.search(r'[Cc]hapter\s*([\d.]+)', text)
            num  = m.group(1) if m else re.sub(r'\s+', ' ', text)
            chapters.append({
                "id":     href,
                "number": num,
                "volume": "",
                "title":  "",
                "pages":  0,
                "lang":   lang,
                "_url":   href,
            })
        # Madara lists chapters newest-first; reverse to get ascending order
        chapters.reverse()
        return chapters

    # ------------------------------------------------------------ download

    def download_chapter(self, item: "QueueItem", log_fd=None) -> bool:
        chapter_url = item.episode.get("_url") or item.episode.get("id", "")
        chapter_num = item.episode.get("number", "?")

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

            imgs = soup.select(
                "div.reading-content img, div.page-break img, "
                "div#readerarea img, .wp-manga-chapter-img img"
            )
            img_urls = []
            for img in imgs:
                src = (img.get("data-src") or img.get("src") or "").strip()
                if src.startswith("http"):
                    img_urls.append(src)

            if not img_urls:
                if log_fd:
                    log_fd.write("[ERROR] Nessuna immagine trovata nel capitolo\n")
                return False

            total = len(img_urls)
            with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_STORED) as zf:
                for i, img_url in enumerate(img_urls, 1):
                    ext      = img_url.rsplit(".", 1)[-1].split("?")[0].lower() or "jpg"
                    arc_name = f"{i:04d}.{ext}"
                    for attempt in range(3):
                        try:
                            img_resp = _SESSION.get(
                                img_url, timeout=45,
                                headers={"Referer": chapter_url},
                            )
                            zf.writestr(arc_name, img_resp.content)
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
