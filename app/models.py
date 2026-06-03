from dataclasses import dataclass
from pathlib import Path


@dataclass
class QueueItem:
    uid:       str
    base_url:  str
    anime_id:  str
    slug:      str
    title:     str
    out_dir:   Path
    episode:   dict
    status:    str        = "pending"   # pending | downloading | done | error
    log_path:  Path | None = None
    item_type: str        = "anime"     # "anime" | "manga"

    @property
    def ep_num(self) -> str:
        if self.item_type == "ebook":
            return self.episode.get("format", "?").upper()
        return str(self.episode.get("number", "?"))

    @property
    def label(self) -> str:
        if self.item_type == "ebook":
            fmt = self.episode.get("format", "").upper()
            src = {"annas": "AA", "zlib": "ZLib"}.get(
                self.episode.get("source", ""), "?"
            )
            return f"{self.title}  [{fmt}] {src}"
        tag = "Ch" if self.item_type == "manga" else "Ep"
        return f"{self.title}  {tag} {self.ep_num}"
