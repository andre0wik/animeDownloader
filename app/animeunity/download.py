import re
import subprocess
import contextlib
from pathlib import Path

from ..config import _CFG, _VIDEO_EXT, _TEMP_EXT
from ..ffmpeg import _ensure_ffmpeg, _is_complete
from .api import get_embed_url, get_video_url


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
            mb = existing.stat().st_size // 1_048_576
            print(f"  File .part trovato ({mb} MB) — yt-dlp riprende da qui")

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
        cmd.insert(-1, "--newline")
    print(f"  yt-dlp → {video_url[:90]}{'…' if len(video_url) > 90 else ''}")
    sp_kw = {"stdout": log_fd, "stderr": log_fd} if log_fd is not None else {}
    return subprocess.run(cmd, **sp_kw).returncode == 0


def local_complete_eps(out_dir: Path, title: str) -> set[int]:
    pat = re.compile(r" - Ep(\d+)\.", re.IGNORECASE)
    found = set()
    for f in out_dir.glob("*.*"):
        if f.suffix.lower() not in _VIDEO_EXT:
            continue
        m = pat.search(f.name)
        if m and _is_complete(f):
            found.add(int(m.group(1)))
    return found


def _download_one_episode(
    episode: dict,
    base_url: str, anime_id: str, slug: str,
    title: str, out_dir: Path, extra_args: list[str],
    log_fd=None,
) -> bool:
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


def run_episode_list(
    episodes: list[dict],
    base_url: str,
    anime_id: str,
    slug: str,
    title: str,
    out_dir: Path,
    extra_args: list[str],
    auto_sync: bool = False,
) -> None:
    from ..sync.autosync import _try_auto_sync

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
            if auto_sync:
                ep_tag = f"{title} - Ep{str(ep_num).zfill(3)}"
                for ext in _VIDEO_EXT:
                    p = out_dir / f"{ep_tag}{ext}"
                    if p.exists():
                        print(f"  [auto-sync] {p.name}...", end="", flush=True)
                        synced = _try_auto_sync(p, _CFG["ssh_host"], _CFG["ssh_remote_base"])
                        print("  OK" if synced else "  (in coda per retry)")
                        break
        else:
            fail += 1; failed_eps.append(ep_num)

    print(f"\n{'='*64}")
    print(f"Completato: {ok} OK  |  {fail} falliti  |  {skip} saltati")
    if failed_eps:
        print(f"Episodi falliti: {failed_eps}")
    print(f"File in: {out_dir}")
