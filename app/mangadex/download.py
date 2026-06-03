import io
import json
import re
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

from ..config import MANGADEX_API, _CFG

_HEADERS = {"User-Agent": "downloader/1.0"}

if TYPE_CHECKING:
    from ..models import QueueItem


def _safe_name(s: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '_', s).strip()


_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
_ARCHIVE_EXTS = {".cbz", ".zip", ".cbt", ".tar", ".cbr", ".cb7"}


def local_manga_status(out_dir: Path) -> tuple[set[str], set[str]]:
    """Returns (complete_chapter_nums, partial_chapter_nums)."""
    complete: set[str] = set()
    partial:  set[str] = set()
    if not out_dir.exists():
        return complete, partial
    for p in out_dir.iterdir():
        if p.name.lower().endswith(".tmp.cbz"):
            m = re.search(r'Ch\s+([\d.]+)', p.name)
            if m:
                partial.add(m.group(1))
        elif p.suffix.lower() in (*_ARCHIVE_EXTS, ".pdf") or p.is_dir():
            m = re.search(r'Ch\s+([\d.]+)', p.stem)
            if m:
                complete.add(m.group(1))
    return complete, partial


def local_complete_manga(out_dir: Path) -> set[str]:
    complete, _ = local_manga_status(out_dir)
    return complete


def _archive_to_pdf(archive_path: Path, log_fd=None) -> bool:
    suffix = archive_path.suffix.lower()
    raw_pages: list[tuple[str, bytes]] = []

    try:
        if suffix in (".cbz", ".zip"):
            with zipfile.ZipFile(archive_path) as zf:
                names = [n for n in zf.namelist() if Path(n).suffix.lower() in _IMAGE_EXTS]
                if not names:
                    return False
                for name in sorted(names):
                    raw_pages.append((name, zf.read(name)))
        elif suffix in (".cbt", ".tar"):
            with tarfile.open(archive_path) as tf:
                members = [m for m in tf.getmembers() if Path(m.name).suffix.lower() in _IMAGE_EXTS]
                if not members:
                    return False
                for m in sorted(members, key=lambda x: x.name):
                    f = tf.extractfile(m)
                    if f:
                        raw_pages.append((m.name, f.read()))
        else:
            if log_fd:
                log_fd.write(f"[pdf] formato {suffix} non supportato (serve rarfile/py7zr)\n")
            return False
    except Exception as e:
        if log_fd:
            log_fd.write(f"[ERROR] apertura archivio: {e}\n")
        return False

    if not raw_pages:
        if log_fd:
            log_fd.write("[pdf] nessuna immagine trovata nell'archivio\n")
        return False

    pdf_path = archive_path.with_suffix(".pdf")
    try:
        images = [Image.open(io.BytesIO(data)).convert("RGB") for _, data in raw_pages]
        images[0].save(pdf_path, "PDF", save_all=True, append_images=images[1:])
        archive_path.unlink()
        if log_fd:
            log_fd.write(f"[pdf] creato {pdf_path.name} ({len(images)} pagine)\n")
        return True
    except Exception as e:
        if log_fd:
            log_fd.write(f"[ERROR] creazione PDF: {e}\n")
        pdf_path.unlink(missing_ok=True)
        return False


def _download_manga_chapter(item: "QueueItem", log_fd=None) -> bool:
    chapter_id  = item.episode["id"]
    chapter_num = item.episode.get("number", "?")
    volume      = item.episode.get("volume", "")
    ch_title    = item.episode.get("title", "")

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

    try:
        req  = urllib.request.Request(
            f"{MANGADEX_API}/at-home/server/{chapter_id}", headers=_HEADERS
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
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
                        req_img = urllib.request.Request(img_url, headers=_HEADERS)
                        with urllib.request.urlopen(req_img, timeout=45) as ir:
                            img_bytes = ir.read()
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

        if _CFG.get("cbz_to_pdf"):
            _archive_to_pdf(cbz_path, log_fd)

        return True
    except Exception as e:
        if log_fd:
            log_fd.write(f"[ERROR] download: {e}\n")
        tmp_path.unlink(missing_ok=True)
        return False
