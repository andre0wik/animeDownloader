from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from textual.app import App

from ..config import _CFG, _VIDEO_EXT
from ..models import QueueItem
from ..animeunity.download import _download_one_episode
from ..mangadex.download import _download_manga_chapter, _safe_name
from ..ebook.download import download_ebook
from ..manga.registry import PLATFORMS as _MANGA_PLATFORMS
from ..sync.autosync import _try_auto_sync, _sync_stop_event, _start_sync_retry_thread
from .css import APP_CSS
from .screens.main_menu import MainMenuScreen
from .screens.queue import QueueScreen


def _cbz_name_for_item(item: QueueItem) -> str:
    chapter_num = item.episode.get("number", "?")
    volume      = item.episode.get("volume", "")
    ch_title    = item.episode.get("title", "")
    try:
        num_f   = float(chapter_num)
        num_str = f"{num_f:07.1f}" if num_f != int(num_f) else f"{int(num_f):04d}"
    except (ValueError, TypeError):
        num_str = str(chapter_num)
    parts: list[str] = []
    if volume:
        try:
            parts.append(f"Vol {int(float(volume)):02d}")
        except ValueError:
            parts.append(f"Vol {volume}")
    parts.append(f"Ch {num_str}")
    if ch_title:
        parts.append(f"- {_safe_name(ch_title)[:60]}")
    return " ".join(parts) + ".cbz"


def _find_downloaded_file(item: QueueItem) -> Path | None:
    if item.item_type == "manga":
        p = item.out_dir / _cbz_name_for_item(item)
        return p if p.exists() else None
    ep_num_raw = str(item.episode.get("number", "?"))
    ep_num     = int(ep_num_raw) if ep_num_raw.isdigit() else ep_num_raw
    ep_tag     = f"{item.title} - Ep{str(ep_num).zfill(3)}"
    for ext in _VIDEO_EXT:
        p = item.out_dir / f"{ep_tag}{ext}"
        if p.exists():
            return p
    return None


class AnimeUnityApp(App):
    TITLE        = "Downloader"
    CSS          = APP_CSS
    BINDINGS     = [
        ("ctrl+d", "open_queue", "Coda download"),
    ]
    MAX_CONCURRENT = _CFG["max_concurrent"]

    def on_mount(self) -> None:
        self._queue:    list[QueueItem]    = []
        self._executor: ThreadPoolExecutor = ThreadPoolExecutor(
            max_workers=self.MAX_CONCURRENT,
            thread_name_prefix="dl-worker",
        )
        _sync_stop_event.clear()
        self._sync_thread = _start_sync_retry_thread()
        self.push_screen(MainMenuScreen())

    def action_open_queue(self) -> None:
        self.push_screen(QueueScreen())

    def add_episodes_to_queue(self, items: list[QueueItem]) -> None:
        self._queue.extend(items)
        for item in items:
            self._executor.submit(self._process_item, item)

    def _process_item(self, item: QueueItem) -> None:
        item.status   = "downloading"
        log_path      = item.out_dir / f"queue_{item.uid[:6]}.log"
        item.log_path = log_path
        try:
            with open(log_path, "w", encoding="utf-8", errors="replace") as lf:
                if item.item_type == "ebook":
                    ok = download_ebook(item, log_fd=lf)
                elif item.item_type == "manga":
                    platform_id = item.episode.get("platform", "mangadex")
                    platform    = _MANGA_PLATFORMS.get(platform_id)
                    if platform:
                        ok = platform.download_chapter(item, log_fd=lf)
                    else:
                        ok = _download_manga_chapter(item, log_fd=lf)
                else:
                    ok = _download_one_episode(
                        item.episode, item.base_url, item.anime_id,
                        item.slug, item.title, item.out_dir, [],
                        log_fd=lf,
                    )
                if ok and _CFG.get("auto_sync"):
                    try:
                        dl_file = _find_downloaded_file(item)
                        if dl_file:
                            lf.write(f"\n[auto-sync] Avvio: {dl_file.name}\n")
                            lf.flush()
                            synced = _try_auto_sync(
                                dl_file, _CFG["ssh_host"], _CFG["ssh_remote_base"]
                            )
                            lf.write(
                                "[auto-sync] OK\n" if synced
                                else "[auto-sync] Server non raggiungibile — in coda per retry\n"
                            )
                    except Exception as sync_exc:
                        lf.write(f"[auto-sync] Errore: {sync_exc}\n")
            item.status = "done" if ok else "error"
            if ok:
                try:
                    log_path.unlink(missing_ok=True)
                    item.log_path = None
                except Exception:
                    pass
        except Exception as exc:
            item.status = "error"
            try:
                log_path.write_text(str(exc), encoding="utf-8")
            except Exception:
                pass

    def on_unmount(self) -> None:
        _sync_stop_event.set()
        if executor := getattr(self, "_executor", None):
            executor.shutdown(wait=False, cancel_futures=True)
