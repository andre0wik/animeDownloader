import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

from curl_cffi import requests as _cf

from .api import _log, download_zlib_book, get_annas_download_url
from ..config import IMPERSONATE

if TYPE_CHECKING:
    from ..models import QueueItem


def _safe_name(s: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", s).strip()


def _stream_download(url: str, dest: Path, log_fd=None) -> bool:
    """Stream-download url → dest con curl_cffi (bypassa Cloudflare)."""
    tmp = dest.with_suffix(".tmp" + dest.suffix)
    tmp.unlink(missing_ok=True)
    try:
        with _cf.Session() as session, session.stream(
            "GET", url, impersonate=IMPERSONATE, timeout=120, verify=False
        ) as resp:
            resp.raise_for_status()
            total_raw = resp.headers.get("Content-Length", "0")
            total     = int(total_raw) if total_raw.isdigit() else 0
            written   = 0
            t0        = time.monotonic()
            with open(tmp, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    f.write(chunk)
                    written  += len(chunk)
                    elapsed   = time.monotonic() - t0 or 0.001
                    speed     = written / elapsed / 1_048_576
                    pct       = written / total * 100 if total else 0.0
                    remaining = (total - written) / (written / elapsed) if written > 0 and total > written else 0
                    mm, ss    = divmod(int(remaining), 60)
                    if log_fd:
                        log_fd.write(
                            f"[download]  {pct:.1f}% at {speed:.2f} MiB/s ETA {mm:02d}:{ss:02d}\n"
                        )
                        log_fd.flush()
        tmp.rename(dest)
        return True
    except Exception as e:
        _log(f"[download] Errore stream: {e}")
        if log_fd:
            log_fd.write(f"[ERROR] {e}\n")
        tmp.unlink(missing_ok=True)
        return False


def download_ebook(item: "QueueItem", log_fd=None) -> bool:
    ep     = item.episode
    source = ep.get("source", "")
    fmt    = ep.get("format", "epub")
    title  = _safe_name(item.title)[:80]
    author = _safe_name(ep.get("author", ""))[:40]
    year   = ep.get("year", "")

    name_parts = [title]
    if author:
        name_parts.append(f"- {author}")
    if year:
        name_parts.append(f"({year})")
    dest = item.out_dir / (" ".join(name_parts) + f".{fmt}")

    if dest.exists():
        if log_fd:
            log_fd.write(f"[skip] già presente: {dest.name}\n")
        return True

    if log_fd:
        log_fd.write(f"[ebook] {source}  {title}.{fmt}\n")
        log_fd.flush()

    dl_url = ep.get("download_url", "")

    if source == "annas":
        md5 = ep.get("md5", "")
        if not md5:
            if log_fd:
                log_fd.write("[ERROR] md5 mancante\n")
            return False
        if not dl_url:
            if log_fd:
                log_fd.write("[annas] recupero link download dalla pagina md5...\n")
                log_fd.flush()
            dl_url = get_annas_download_url(md5)
        if not dl_url:
            if log_fd:
                log_fd.write("[ERROR] nessun link trovato sulla pagina md5\n")
            return False

    elif source == "zlib":
        book_page = dl_url
        if not book_page:
            if log_fd:
                log_fd.write("[ERROR] URL pagina libro mancante\n")
            return False
        if log_fd:
            log_fd.write(f"[zlib] download da {book_page}...\n")
            log_fd.flush()
        return download_zlib_book(book_page, dest, log_fd=log_fd)
    else:
        if log_fd:
            log_fd.write(f"[ERROR] sorgente sconosciuta: {source}\n")
        return False

    item.out_dir.mkdir(parents=True, exist_ok=True)
    return _stream_download(dl_url, dest, log_fd=log_fd)
