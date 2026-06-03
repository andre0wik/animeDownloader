from pathlib import Path

from textual.app        import ComposeResult
from textual.binding    import Binding
from textual.screen     import Screen
from textual.widgets    import (
    Button, Checkbox, DataTable, Footer, Header, Input, Label, Select,
    SelectionList, Static,
)
from textual.containers import Horizontal, Vertical
from textual.timer      import Timer
from textual            import on, work
from rich.text          import Text as RichText

from ...config import DEFAULT_BASE, _CFG
from ...config import _anime_dl_dir
from ...animeunity.api import search_catalog, _FILTER_OPTS, _GENRES_LIST

def _sv(val) -> str:
    return str(val) if isinstance(val, str) else ""
from ...animeunity.history import load_history, save_history
from ..helpers import _queue_status_text
from .anime_menu import AnimeMenuScreen


class SearchScreen(Screen):

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Indietro", priority=True),
        Binding("ctrl+b", "app.pop_screen", "Indietro", priority=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="filters"):
            with Horizontal(classes="filter-row"):
                yield Label("Titolo:", classes="flabel")
                yield Input(placeholder="cerca per titolo... (lascia vuoto per sfogliare per filtri)", id="title")
                yield Label("Tipo:", classes="flabel")
                yield Select(
                    [(v, v) for v in _FILTER_OPTS["type"] if v],
                    id="type", allow_blank=True, prompt="(tutti)",
                )
                yield Label("Anno:", classes="flabel")
                yield Input(placeholder="es. 2018", id="year")
            with Horizontal(classes="filter-row"):
                yield Label("Stato:", classes="flabel")
                yield Select(
                    [(v, v) for v in _FILTER_OPTS["status"] if v],
                    id="status", allow_blank=True, prompt="(tutti)",
                )
                yield Label("Stagione:", classes="flabel")
                yield Select(
                    [(v, v) for v in _FILTER_OPTS["season"] if v],
                    id="season", allow_blank=True, prompt="(tutti)",
                )
                yield Label("Ordina:", classes="flabel")
                yield Select(
                    [(v, v) for v in _FILTER_OPTS["order"]],
                    id="order", allow_blank=False,
                )
                yield Checkbox("Solo doppiato ITA", id="dubbed")
            yield SelectionList(*[(g, g) for g in _GENRES_LIST], id="genres")
            with Horizontal(id="btn-row"):
                yield Button("Cerca",          id="search",   variant="primary")
                yield Button("Pulisci filtri", id="clear",    variant="default")
                yield Button("← Indietro",     id="back-btn", variant="error")
        yield Static("", id="search-status")
        yield DataTable(id="results", cursor_type="row")
        yield Static("", classes="dl-status", id="dl-status")
        yield Footer()

    def on_mount(self) -> None:
        self._history: list[dict] = []
        self._results: list[dict] = []
        self._auto_timer: Timer | None = None
        self._searching: bool = False
        table = self.query_one("#results", DataTable)
        table.add_column("#",      width=4)
        table.add_column("Titolo", width=38)
        table.add_column("Tipo",   width=8)
        table.add_column("Anno",   width=6)
        table.add_column("Stato",  width=12)
        table.add_column("Voto",   width=6)
        self._load_history_rows()
        self.set_interval(1.0, self._refresh_status)

    def _refresh_status(self) -> None:
        if not self._searching:
            self.query_one("#dl-status", Static).update(
                _queue_status_text(getattr(self.app, "_queue", []))
            )

    def _load_history_rows(self) -> None:
        self._history = load_history()
        table = self.query_one("#results", DataTable)
        table.clear()
        for h in self._history[:10]:
            year = (h.get("last_used", "") or "")[:4]
            table.add_row(
                RichText(">>",        style="yellow bold"),
                RichText(h["title"],  style="yellow"),
                RichText("",         style="yellow"),
                RichText(year,       style="yellow"),
                RichText("recente",  style="yellow"),
                key=f"hist_{h['anime_id']}",
            )

    def _schedule_auto_search(self) -> None:
        if self.query_one("#title", Input).value.strip():
            return
        if self._auto_timer is not None:
            self._auto_timer.stop()
        self._auto_timer = self.set_timer(0.6, self.do_search)

    @on(Input.Submitted, "#title")
    def _title_submitted(self, _) -> None:
        self.do_search()

    @on(Select.Changed)
    def _filter_select_changed(self, _) -> None:
        self._schedule_auto_search()

    @on(SelectionList.SelectedChanged)
    def _genre_changed(self, _) -> None:
        self._schedule_auto_search()

    @on(Button.Pressed, "#search")
    def do_search(self) -> None:
        type_val       = self.query_one("#type",       Select).value
        status_val     = self.query_one("#status",     Select).value
        season_val     = self.query_one("#season",     Select).value
        order_val      = self.query_one("#order",      Select).value
        filters = {
            "type":   _sv(type_val),
            "year":   self.query_one("#year", Input).value.strip(),
            "status": _sv(status_val),
            "season": _sv(season_val),
            "order":  _sv(order_val) or "Più visti",
            "dubbed": bool(self.query_one("#dubbed", Checkbox).value),
            "genres": list(self.query_one("#genres", SelectionList).selected),
        }
        query = self.query_one("#title", Input).value.strip()
        self._searching = True
        self.query_one("#search-status", Static).update("[yellow]Ricerca in corso...[/yellow]")
        self._search_worker(query, filters)

    @work(thread=True)
    def _search_worker(self, query: str, filters: dict) -> None:
        try:
            results = search_catalog(DEFAULT_BASE, query, filters)
        except Exception as e:
            self.app.call_from_thread(self._show_error, str(e))
            return
        self.app.call_from_thread(self._populate_results, results)

    def _show_error(self, msg: str) -> None:
        self._searching = False
        self.query_one("#search-status", Static).update(f"[red]Errore: {msg}[/red]")

    def _populate_results(self, results: list[dict]) -> None:
        self._searching = False
        self._results = results
        history_ids   = {h["anime_id"] for h in self._history}
        table = self.query_one("#results", DataTable)
        table.clear()
        if not results:
            self.query_one("#search-status", Static).update(
                "[red]Nessun risultato trovato[/red]"
            )
            return
        self.query_one("#search-status", Static).update(
            f"[green]{len(results)} risultati[/green]"
        )
        for i, item in enumerate(results[:50], 1):
            anno  = (item.get("year") or "")[:4]
            style = "yellow" if item["anime_id"] in history_ids else ""
            table.add_row(
                RichText(str(i),              style=style),
                RichText(item["title"],       style=style),
                RichText(item["type"],        style=style),
                RichText(anno,                style=style),
                RichText(item["status"],      style=style),
                RichText(item.get("score",""),style=style),
                key=f"res_{item['anime_id']}",
            )

    @on(Button.Pressed, "#back-btn")
    def go_back(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#clear")
    def clear_filters(self) -> None:
        self.query_one("#title",  Input).value        = ""
        self.query_one("#year",   Input).value        = ""
        self.query_one("#type",   Select).value       = Select.BLANK
        self.query_one("#status", Select).value       = Select.BLANK
        self.query_one("#season", Select).value       = Select.BLANK
        self.query_one("#dubbed", Checkbox).value     = False
        self.query_one("#genres", SelectionList).deselect_all()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key  = str(event.row_key.value or "")
        item: dict | None = None

        if key.startswith("res_"):
            aid  = key[4:]
            item = next((r for r in self._results if r["anime_id"] == aid), None)
        elif key.startswith("hist_"):
            aid  = key[5:]
            h    = next((h for h in self._history if h["anime_id"] == aid), None)
            if h:
                item = {
                    "base_url": h["base_url"],
                    "anime_id": h["anime_id"],
                    "slug":     h["slug"],
                    "title":    h["title"],
                }

        if item:
            base_url = item.get("base_url", DEFAULT_BASE)
            save_history(base_url, item["anime_id"], item["slug"], item["title"])
            out_dir  = _anime_dl_dir() / item["title"]
            out_dir.mkdir(parents=True, exist_ok=True)
            self.app.push_screen(
                AnimeMenuScreen(
                    base_url, item["anime_id"], item["slug"],
                    item["title"], out_dir,
                )
            )
