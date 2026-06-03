from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import QueueItem

_SAFE_CHARS = str.maketrans('<>:"/\\|?*', '_________')


def _safe_name(s: str) -> str:
    return s.translate(_SAFE_CHARS).strip()


class MangaPlatform(ABC):
    id: str = ""
    name: str = ""
    dl_subdir: str = "Manga"

    # Which filters this platform supports (subset of keys below)
    supported_filters: set[str] = set()

    # Per-platform filter options (empty = not supported)
    lang_opts:        list[tuple[str, str]] = []
    origin_opts:      list[tuple[str, str]] = []
    status_opts:      list[tuple[str, str]] = []
    demographic_opts: list[tuple[str, str]] = []
    rating_opts:      list[tuple[str, str]] = []
    order_opts:       list[tuple[str, str]] = []
    genres:           list[tuple[str, str]] = []

    needs_credentials:    bool = False
    supports_empty_search: bool = False

    def out_dir(self, title: str) -> Path:
        from ..config import _CFG
        return Path(_CFG["download_dir"]) / self.dl_subdir / _safe_name(title)[:80]

    @abstractmethod
    def search(self, title: str, filters: dict) -> list[dict]:
        """
        Returns list of manga dicts with standard keys:
          manga_id, title, status, content_rating, original_lang,
          genres, languages, platform
        """

    @abstractmethod
    def get_chapters(self, manga_id: str, lang: str) -> list[dict]:
        """
        Returns list of chapter dicts:
          id, number, volume, title, pages, lang
        """

    @abstractmethod
    def download_chapter(self, item: "QueueItem", log_fd=None) -> bool:
        """Downloads a chapter, returns True on success."""
