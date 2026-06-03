"""
LINE Webtoon scraper.
Search via HTML, episodes via series list page (server-side rendered).
No login needed for free/canvas content.
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
_BASE    = "https://www.webtoons.com"

_LANG_OPTS = [
    ("Inglese",  "en"),
    ("Coreano",  "ko"),
    ("Spagnolo", "es"),
    ("Francese", "fr"),
    ("Cinese",   "zh-hant"),
]

_GENRES = [
    ("Romance",       "ROMANCE"),
    ("Fantasy",       "FANTASY"),
    ("Comedy",        "COMEDY"),
    ("Action",        "ACTION"),
    ("Drama",         "DRAMA"),
    ("Slice of Life", "SLICE_OF_LIFE"),
    ("Thriller",      "THRILLER"),
    ("Horror",        "HORROR"),
    ("Supernatural",  "SUPERNATURAL"),
    ("Sports",        "SPORTS"),
    ("Sci-Fi",        "SF"),
    ("Historical",    "HISTORICAL"),
]

# Short badge strings to skip when extracting title from card text
_SKIP_TOKENS = {"UP", "NEW", "AD", "HOT", "END"}


def _num_key(n: str) -> float:
    try:
        return float(n)
    except (ValueError, TypeError):
        return float("inf")


class WebtoonPlatform(MangaPlatform):
    id        = "webtoon"
    name      = "LINE Webtoon"
    dl_subdir = "Webtoon"

    supported_filters = {"lang", "genres"}
    lang_opts         = _LANG_OPTS
    genres            = _GENRES

    # ------------------------------------------------------------------ search

    def search(self, title: str, filters: dict) -> list[dict]:
        lang    = filters.get("lang") or "en"
        results = []
        if not title:
            return results
        try:
            url  = f"{_BASE}/{lang}/search?keyword={urllib.parse.quote(title)}"
            resp = _SESSION.get(url, timeout=15)
            soup = BeautifulSoup(resp.text, "lxml")

            seen: set[str] = set()
            for card in soup.select("a[data-title-no]"):
                title_no = card.get("data-title-no", "")
                if not title_no or title_no in seen:
                    continue
                seen.add(title_no)

                href = card.get("href", "")
                # Extract path like "en/fantasy/tower-of-god" from full href
                m    = re.match(r"https://www\.webtoons\.com/(.+)/list", href)
                path = m.group(1) if m else f"{lang}/_/_"

                # Card text: "UP|Tower of God|SIU|1B Views" — skip short/badge tokens
                raw      = card.get_text(separator="|", strip=True)
                segments = [s for s in raw.split("|") if len(s) > 2 and s not in _SKIP_TOKENS]
                t        = segments[0] if segments else ""
                if not t:
                    continue

                results.append({
                    "manga_id":       f"{lang}:{title_no}:{path}",
                    "title":          t,
                    "status":         "",
                    "content_rating": "safe",
                    "original_lang":  "ko",
                    "genres":         "",
                    "languages":      lang,
                    "platform":       self.id,
                    "_title_no":      title_no,
                    "_path":          path,
                })
        except Exception as e:
            raise RuntimeError(f"Ricerca Webtoon fallita: {e}") from e
        return results

    # ---------------------------------------------------------------- chapters

    def get_chapters(self, manga_id: str, lang: str) -> list[dict]:
        # manga_id = "lang:title_no:path"  (or legacy "lang:title_no")
        parts    = manga_id.split(":", 2)
        wt_lang  = parts[0] if len(parts) >= 1 else "en"
        title_no = parts[1] if len(parts) >= 2 else manga_id
        path     = parts[2] if len(parts) >= 3 else f"{wt_lang}/_/_"

        chapters: list[dict] = []
        page = 1
        while True:
            try:
                list_url = f"{_BASE}/{path}/list?title_no={title_no}&page={page}"
                resp     = _SESSION.get(list_url, timeout=15)
                soup     = BeautifulSoup(resp.text, "lxml")

                # Episodes are in ul#_listUl > li._episodeItem
                lis = soup.select("ul#_listUl li._episodeItem, li._episodeItem[id^='episode_']")
                if not lis:
                    break

                for li in lis:
                    a = li.select_one("a")
                    if not a:
                        continue
                    href  = a.get("href", "")
                    ep_m  = re.search(r"episode_no=(\d+)", href)
                    ep_no = ep_m.group(1) if ep_m else re.search(r"episode_(\d+)", li.get("id",""))
                    if not ep_no:
                        continue
                    if hasattr(ep_no, "group"):
                        ep_no = ep_no.group(1)
                    # Title: find .subj span or take first segment of text
                    subj = li.select_one(".subj span, .subj")
                    ep_t = subj.get_text(strip=True) if subj else ""
                    chapters.append({
                        "id":     f"{title_no}:{ep_no}",
                        "number": ep_no,
                        "volume": "",
                        "title":  ep_t,
                        "pages":  0,
                        "lang":   wt_lang,
                        "_url":   href,
                        "_path":  path,
                    })

                if not lis or page >= 200:   # 200 pagine * 10 ep = 2000 cap max
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
            imgs = soup.select("div#_imageList img, .viewer_lst img, .viewer_img img")
            img_urls = []
            for img in imgs:
                src = (img.get("data-url") or img.get("data-src") or img.get("src") or "").strip()
                if src.startswith("http"):
                    img_urls.append(src)

            if not img_urls:
                if log_fd:
                    log_fd.write("[ERROR] Nessuna immagine trovata\n")
                return False

            total = len(img_urls)
            with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_STORED) as zf:
                for i, img_url in enumerate(img_urls, 1):
                    ext      = img_url.rsplit(".", 1)[-1].split("?")[0].lower() or "jpg"
                    arc_name = f"{i:04d}.{ext}"
                    for attempt in range(3):
                        try:
                            ir = _SESSION.get(
                                img_url, timeout=45,
                                headers={"Referer": "https://www.webtoons.com/"},
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
