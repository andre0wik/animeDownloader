from .base import MangaPlatform
from ..mangadex.api import (
    search_mangadex, fetch_manga_chapters,
    _MDX_LANG_OPTS, _MDX_ORIGIN_OPTS, _MDX_STATUS_OPTS,
    _MDX_DEMO_OPTS, _MDX_RATING_OPTS, _MDX_ORDER_OPTS, _MDX_GENRES,
)
from ..mangadex.download import _download_manga_chapter


class MangaDexPlatform(MangaPlatform):
    id       = "mangadex"
    name     = "MangaDex"
    dl_subdir = "MangaDex"

    supported_filters     = {"lang", "origin", "status", "demographic", "rating", "order", "genres"}
    supports_empty_search = True
    lang_opts        = _MDX_LANG_OPTS
    origin_opts      = _MDX_ORIGIN_OPTS
    status_opts      = _MDX_STATUS_OPTS
    demographic_opts = _MDX_DEMO_OPTS
    rating_opts      = _MDX_RATING_OPTS
    order_opts       = _MDX_ORDER_OPTS
    genres           = _MDX_GENRES

    def search(self, title: str, filters: dict) -> list[dict]:
        results = search_mangadex(
            title           = title,
            translated_lang = filters.get("lang", "it"),
            original_lang   = filters.get("origin", ""),
            status          = filters.get("status", ""),
            demographic     = filters.get("demographic", ""),
            content_rating  = filters.get("rating", ""),
            included_tags   = filters.get("genres") or None,
            order           = filters.get("order", "followedCount"),
        )
        for r in results:
            r["platform"] = self.id
        return results

    def get_chapters(self, manga_id: str, lang: str) -> list[dict]:
        return fetch_manga_chapters(manga_id, lang)

    def download_chapter(self, item, log_fd=None) -> bool:
        return _download_manga_chapter(item, log_fd)
