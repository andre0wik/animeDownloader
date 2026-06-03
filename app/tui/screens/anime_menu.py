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

from ...config import _CFG
from ...models import QueueItem
from ...animeunity.api import fetch_episodes
from ...animeunity.download import local_complete_eps
from ...sync.ssh import cmd_sync
from ..helpers import _queue_status_text


class AnimeMenuScreen(Screen):

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Indietro", priority=True),
        Binding("ctrl+b", "app.pop_screen", "Indietro", priority=True),
    ]

    def __init__(
        self,
        base_url: str, anime_id: str, slug: str,
        title: str, out_dir: Path,
    ) -> None:
        super().__init__()
        self._base_url     = base_url
        self._anime_id     = anime_id
        self._slug         = slug
        self._title        = title
        self._out_dir      = out_dir
        self._ep_map:      dict[str, dict] = {}
        self._missing_ids: set[str]        = set()

    def compose(self) -> ComposeResult:
        url = f"{self._base_url}/anime/{self._anime_id}-{self._slug}"
        yield Header()
        with Vertical(id="series-info"):
            yield Static(f"[bold cyan]{self._title}[/bold cyan]")
            yield Static(f"[dim]{url}[/dim]")
            yield Static(f"[dim]Output: {self._out_dir}[/dim]")
        yield LoadingIndicator(id="ep-loading")
        yield SelectionList(id="ep-list")
        with Vertical(id="ep-actions"):
            with Horizontal(classes="ep-action-row"):
                yield Button("Mancanti",             id="sel-missing", variant="default")
                yield Button("Tutti",                id="sel-all",     variant="default")
                yield Button("Nessuno",              id="desel-all",   variant="default")
                yield Label("", id="sel-count")
            with Horizontal(classes="ep-action-row"):
                yield Button("+ Aggiungi alla coda", id="add-queue",   variant="success")
            with Horizontal(classes="ep-action-row"):
                yield Button("Sincronizza su Gengar", id="sync",       variant="default")
                yield Button("<- Indietro",            id="back",      variant="error")
        yield Static("", classes="dl-status", id="dl-status")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#ep-list", SelectionList).display = False
        self._fetch_episodes()
        self.set_interval(1.0, self._refresh_status)

    def _refresh_status(self) -> None:
        self.query_one("#dl-status", Static).update(
            _queue_status_text(getattr(self.app, "_queue", []))
        )

    @work(thread=True)
    def _fetch_episodes(self) -> None:
        all_eps = fetch_episodes(self._base_url, self._anime_id, 1, 9999)
        have    = local_complete_eps(self._out_dir, self._title)
        self.app.call_from_thread(self._populate, all_eps, have)

    def _populate(self, episodes: list[dict], have: set[int]) -> None:
        if not self.is_mounted:
            return
        self._ep_map      = {}
        self._missing_ids = set()
        self._all_options: list[tuple[str, str, bool]] = []
        ep_list = self.query_one("#ep-list", SelectionList)

        for ep in episodes:
            ep_id      = str(ep.get("id", ""))
            ep_num_raw = str(ep.get("number", "?"))
            if not ep_id:
                continue
            ep_num_int = int(ep_num_raw) if ep_num_raw.isdigit() else None
            is_done    = ep_num_int is not None and ep_num_int in have
            label      = f"Ep {ep_num_raw}  [OK]" if is_done else f"Ep {ep_num_raw}"
            self._ep_map[ep_id] = ep
            if not is_done:
                self._missing_ids.add(ep_id)
            self._all_options.append((label, ep_id, is_done))
            ep_list.add_option((label, ep_id, not is_done))

        self.query_one("#ep-loading", LoadingIndicator).display = False
        ep_list.display = True
        self._update_count()

    def _update_count(self) -> None:
        n = len(self.query_one("#ep-list", SelectionList).selected)
        self.query_one("#sel-count", Label).update(f"  {n} selezionati")

    @on(SelectionList.SelectedChanged)
    def _on_sel_changed(self) -> None:
        self._update_count()

    @on(Button.Pressed, "#sel-missing")
    def sel_missing(self) -> None:
        ep_list = self.query_one("#ep-list", SelectionList)
        ep_list.clear_options()
        for label, ep_id, is_done in self._all_options:
            if not is_done:
                ep_list.add_option((label, ep_id, True))
        self._update_count()

    @on(Button.Pressed, "#sel-all")
    def sel_all(self) -> None:
        ep_list = self.query_one("#ep-list", SelectionList)
        ep_list.clear_options()
        for label, ep_id, is_done in self._all_options:
            ep_list.add_option((label, ep_id, True))
        self._update_count()

    @on(Button.Pressed, "#desel-all")
    def desel_all(self) -> None:
        ep_list = self.query_one("#ep-list", SelectionList)
        ep_list.clear_options()
        for label, ep_id, is_done in self._all_options:
            ep_list.add_option((label, ep_id, False))
        self._update_count()

    @on(Button.Pressed, "#add-queue")
    def add_to_queue(self) -> None:
        selected_ids = list(self.query_one("#ep-list", SelectionList).selected)
        if not selected_ids:
            self.notify("Nessun episodio selezionato", severity="warning")
            return
        items = [
            QueueItem(
                uid      = str(uuid.uuid4()),
                base_url = self._base_url,
                anime_id = self._anime_id,
                slug     = self._slug,
                title    = self._title,
                out_dir  = self._out_dir,
                episode  = self._ep_map[eid],
            )
            for eid in selected_ids
            if eid in self._ep_map
        ]
        self.app.add_episodes_to_queue(items)
        ep_list = self.query_one("#ep-list", SelectionList)
        for eid in selected_ids:
            ep_list.deselect(eid)
        self._update_count()
        self.notify(f"{len(items)} episodi aggiunti alla coda", severity="information")

    @on(Button.Pressed, "#back")
    def go_back(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#sync")
    def on_sync(self) -> None:
        self._do_sync()

    @work(thread=True)
    def _do_sync(self) -> None:
        with self.app.suspend():
            cmd_sync(self._out_dir, _CFG["ssh_host"], _CFG["ssh_remote_base"])
            input("\nPremi Invio per continuare...")
