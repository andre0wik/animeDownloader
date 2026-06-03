import uuid
from pathlib import Path

from textual.app        import ComposeResult
from textual.binding    import Binding
from textual.screen     import Screen
from textual.widgets    import (
    Button, Footer, Header, Label, LoadingIndicator, SelectionList, Static,
)
from textual.containers import Horizontal, Vertical
from textual            import on, work

from ...manga.base       import MangaPlatform
from ...models           import QueueItem
from ...mangadex.download import local_manga_status
from ..helpers            import _queue_status_text


class MangaMenuScreen(Screen):

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Indietro", priority=True),
        Binding("ctrl+b", "app.pop_screen", "Indietro", priority=True),
    ]

    def __init__(
        self,
        platform: MangaPlatform,
        manga_id: str,
        title:    str,
        out_dir:  Path,
        lang:     str = "",
    ) -> None:
        super().__init__()
        self._platform = platform
        self._manga_id = manga_id
        self._title    = title
        self._out_dir  = out_dir
        self._lang     = lang or ""
        self._ch_map:      dict[str, dict] = {}
        self._missing_ids: set[str]        = set()
        self._all_options: list[tuple[str, str, bool]] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="series-info"):
            yield Static(f"[bold cyan]{self._title}[/bold cyan]")
            yield Static(
                f"[dim]{self._platform.name}"
                + (f"  |  Lingua: {self._lang}" if self._lang else "")
                + f"  |  Output: {self._out_dir}[/dim]"
            )
        yield LoadingIndicator(id="ep-loading")
        yield SelectionList(id="ep-list")
        with Vertical(id="ep-actions"):
            with Horizontal(classes="ep-action-row"):
                yield Button("Mancanti", id="sel-missing", variant="default")
                yield Button("Tutti",    id="sel-all",     variant="default")
                yield Button("Nessuno",  id="desel-all",   variant="default")
                yield Label("", id="sel-count")
            with Horizontal(classes="ep-action-row"):
                yield Button("+ Aggiungi alla coda", id="add-queue", variant="success")
            with Horizontal(classes="ep-action-row"):
                yield Button("<- Indietro", id="back", variant="error")
        yield Static("", classes="dl-status", id="dl-status")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#ep-list", SelectionList).display = False
        self._fetch_chapters()
        self.set_interval(1.0, self._refresh_status)

    def _refresh_status(self) -> None:
        self.query_one("#dl-status", Static).update(
            _queue_status_text(getattr(self.app, "_queue", []))
        )

    @work(thread=True)
    def _fetch_chapters(self) -> None:
        chapters          = self._platform.get_chapters(self._manga_id, self._lang)
        complete, partial = local_manga_status(self._out_dir)
        self.app.call_from_thread(self._populate, chapters, complete, partial)

    def _populate(
        self,
        chapters: list[dict],
        have:     set[str],
        partial:  set[str],
    ) -> None:
        if not self.is_mounted:
            return
        self._ch_map      = {}
        self._missing_ids = set()
        self._all_options = []
        ch_list = self.query_one("#ep-list", SelectionList)

        for ch in chapters:
            ch_id      = ch["id"]
            num        = ch["number"]
            vol        = ch.get("volume", "")
            title      = ch.get("title", "")
            pages      = ch.get("pages", 0)
            is_done    = num in have
            is_partial = (not is_done) and (num in partial)

            parts: list[str] = []
            if vol:
                parts.append(f"Vol {vol}")
            parts.append(f"Ch {num}")
            if title:
                parts.append(f"- {title[:40]}")
            if pages:
                parts.append(f"({pages}p)")
            if is_done:
                parts.append("[OK]")
            elif is_partial:
                parts.append("[~]")

            label = "  ".join(parts)
            self._ch_map[ch_id] = ch
            if not is_done:
                self._missing_ids.add(ch_id)
            self._all_options.append((label, ch_id, is_done))
            ch_list.add_option((label, ch_id, not is_done))

        self.query_one("#ep-loading", LoadingIndicator).display = False
        ch_list.display = True
        self._update_count()

    def _update_count(self) -> None:
        n = len(self.query_one("#ep-list", SelectionList).selected)
        self.query_one("#sel-count", Label).update(f"  {n} selezionati")

    @on(SelectionList.SelectedChanged)
    def _on_sel_changed(self) -> None:
        self._update_count()

    @on(Button.Pressed, "#sel-missing")
    def sel_missing(self) -> None:
        ch_list = self.query_one("#ep-list", SelectionList)
        ch_list.clear_options()
        for label, ch_id, is_done in self._all_options:
            if not is_done:
                ch_list.add_option((label, ch_id, True))
        self._update_count()

    @on(Button.Pressed, "#sel-all")
    def sel_all(self) -> None:
        ch_list = self.query_one("#ep-list", SelectionList)
        ch_list.clear_options()
        for label, ch_id, is_done in self._all_options:
            ch_list.add_option((label, ch_id, True))
        self._update_count()

    @on(Button.Pressed, "#desel-all")
    def desel_all(self) -> None:
        ch_list = self.query_one("#ep-list", SelectionList)
        ch_list.clear_options()
        for label, ch_id, is_done in self._all_options:
            ch_list.add_option((label, ch_id, False))
        self._update_count()

    @on(Button.Pressed, "#add-queue")
    def add_to_queue(self) -> None:
        selected_ids = list(self.query_one("#ep-list", SelectionList).selected)
        if not selected_ids:
            self.notify("Nessun capitolo selezionato", severity="warning")
            return
        items = []
        for cid in selected_ids:
            if cid not in self._ch_map:
                continue
            ch = dict(self._ch_map[cid])
            ch["platform"] = self._platform.id   # routing download
            items.append(QueueItem(
                uid       = str(uuid.uuid4()),
                base_url  = "",
                anime_id  = self._manga_id,
                slug      = "",
                title     = self._title,
                out_dir   = self._out_dir,
                episode   = ch,
                item_type = "manga",
            ))
        self.app.add_episodes_to_queue(items)
        ch_list = self.query_one("#ep-list", SelectionList)
        for cid in selected_ids:
            ch_list.deselect(cid)
        self._update_count()
        self.notify(f"{len(items)} capitoli aggiunti alla coda", severity="information")

    @on(Button.Pressed, "#back")
    def go_back(self) -> None:
        self.app.pop_screen()
