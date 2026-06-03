import subprocess
import urllib.request
import zipfile
from pathlib import Path

from .config import FFMPEG_DIR, FFMPEG_EXE, FFPROBE_EXE


def _ensure_ffmpeg() -> str | None:
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
    try:
        r = subprocess.run(["ffprobe", "-version"], capture_output=True)
        if r.returncode == 0:
            return "ffprobe"
    except FileNotFoundError:
        pass
    return str(FFPROBE_EXE) if FFPROBE_EXE.exists() else None


def _is_complete(path: Path) -> bool:
    if not path.exists():
        return False
    size = path.stat().st_size
    if size < 1_000_000:
        return False

    probe = _ffprobe()
    if not probe:
        return size > 10_000_000

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
