import uuid

from textual.app        import ComposeResult
from textual.binding    import Binding
from textual.screen     import Screen
from textual.widgets    import Button, DataTable, Footer, Header, Input, Label, Select, Static
from textual.containers import Horizontal, Vertical
from textual.timer      import Timer
from textual            import on, work

from ...config import _CFG, _ebook_dl_dir
from ...models import QueueItem
from ...ebook.api import (
    search_ebooks,
    EBOOK_LANG_OPTS, EBOOK_FORMAT_OPTS, EBOOK_SOURCE_OPTS,
)
from ...ebook.download import _safe_name
from ..helpers import _queue_status_text


class EbookSearchScreen(Screen):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Indietro", priority=True),
        Binding("ctrl+b", "app.pop_screen", "Indietro", priority=True),
        Binding("ctrl+d", "app.open_queue", "Coda"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="eb-filters"):
            with Horizontal(classes="filter-row"):
                yield Label("Titolo / Autore:", classes="flabel")
                yield Input(placeholder="cerca ebook...", id="eb-query")
            with Horizontal(classes="filter-row"):
                yield Label("Lingua:", classes="flabel")
                yield Select(
                    [(lbl, val) for lbl, val in EBOOK_LANG_OPTS],
                    id="eb-lang", allow_blank=True, prompt="(tutte)",
                )
                yield Label("Formato:", classes="flabel")
                yield Select(
                    [(lbl, val) for lbl, val in EBOOK_FORMAT_OPTS],
                    id="eb-fmt", allow_blank=True, prompt="(tutti)",
                )
                yield Label("Sorgente:", classes="flabel")
                yield Select(
                    [(lbl, val) for lbl, val in EBOOK_SOURCE_OPTS],
                    id="eb-source", allow_blank=False,
                )
            with Horizontal(id="eb-btn-row"):
                yield Button("Cerca",          id="eb-search-btn", variant="primary")
                yield Button("Pulisci filtri", id="eb-clear-btn",  variant="default")
                yield Button("← Indietro",     id="eb-back-btn",   variant="error")
        yield Static("", id="eb-status")
        yield DataTable(id="eb-results", cursor_type="row")
        yield Static("", classes="dl-status", id="eb-dl-status")
        yield Footer()

    def on_mount(self) -> None:
        self._results:    list[dict]    = []
        self._searching:  bool          = False
        self._auto_timer: Timer | None  = None
        table = self.query_one("#eb-results", DataTable)
        table.add_column("#",          width=4)
        table.add_column("Titolo",     width=32)
        table.add_column("Autore",     width=22)
        table.add_column("Anno",       width=6)
        table.add_column("Formato",    width=7)
        table.add_column("Lingua",     width=6)
        table.add_column("Dimensione", width=10)
        table.add_column("Fonte",      width=6)
        self.set_interval(1.0, self._refresh_dl_status)

    def _refresh_dl_status(self) -> None:
        if not self._searching:
            self.query_one("#eb-dl-status", Static).update(
                _queue_status_text(getattr(self.app, "_queue", []))
            )

    @staticmethod
    def _sv(val) -> str:
        return str(val) if isinstance(val, str) else ""

    def _schedule_auto_search(self) -> None:
        if self.query_one("#eb-query", Input).value.strip():
            return
        if self._auto_timer is not None:
            self._auto_timer.stop()
        self._auto_timer = self.set_timer(0.6, self.do_search)

    @on(Input.Submitted, "#eb-query")
    def _query_submitted(self, _) -> None:
        self.do_search()

    @on(Select.Changed)
    def _filter_changed(self, _) -> None:
        self._schedule_auto_search()

    @on(Button.Pressed, "#eb-search-btn")
    def _search_btn(self) -> None:
        self.do_search()

    def do_search(self) -> None:
        query  = self.query_one("#eb-query",  Input).value.strip()
        lang   = self._sv(self.query_one("#eb-lang",   Select).value)
        fmt    = self._sv(self.query_one("#eb-fmt",    Select).value)
        source = self._sv(self.query_one("#eb-source", Select).value) or "all"

        if not query:
            self.query_one("#eb-status", Static).update(
                "[dim]Inserisci un titolo o autore per cercare[/dim]"
            )
            return

        self._searching = True
        self.query_one("#eb-status", Static).update("[yellow]Ricerca in corso...[/yellow]")
        self._search_worker(query=query, lang=lang, fmt=fmt, source=source)

    @work(thread=True)
    def _search_worker(self, query: str, lang: str, fmt: str, source: str) -> None:
        try:
            results = search_ebooks(query=query, lang=lang, fmt=fmt, source=source)
        except Exception as e:
            self.app.call_from_thread(self._show_error, str(e))
            return
        self.app.call_from_thread(self._populate, results)

    def _show_error(self, msg: str) -> None:
        self._searching = False
        self.query_one("#eb-status", Static).update(f"[red]Errore: {msg}[/red]")

    def _populate(self, results: list[dict]) -> None:
        self._searching = False
        self._results   = results
        table = self.query_one("#eb-results", DataTable)
        table.clear()
        if not results:
            self.query_one("#eb-status", Static).update(
                "[red]Nessun risultato trovato[/red]"
            )
            return
        self.query_one("#eb-status", Static).update(
            f"[green]{len(results)} risultati[/green]  "
            "[dim]— click per aggiungere alla coda[/dim]"
        )
        src_label = {"annas": "AA", "zlib": "ZLib"}
        for i, r in enumerate(results, 1):
            table.add_row(
                str(i),
                r.get("title",    ""),
                r.get("author",   ""),
                r.get("year",     ""),
                r.get("format",   "").upper(),
                r.get("language", ""),
                r.get("filesize", ""),
                src_label.get(r.get("source", ""), r.get("source", "")),
                key=f"eb_{i - 1}",
            )

    @on(Button.Pressed, "#eb-clear-btn")
    def _clear_filters(self) -> None:
        self.query_one("#eb-query",  Input).value  = ""
        self.query_one("#eb-lang",   Select).value = Select.BLANK
        self.query_one("#eb-fmt",    Select).value = Select.BLANK
        self.query_one("#eb-source", Select).value = "all"
        table = self.query_one("#eb-results", DataTable)
        table.clear()
        self.query_one("#eb-status", Static).update("")

    @on(Button.Pressed, "#eb-back-btn")
    def _go_back(self) -> None:
        self.app.pop_screen()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key = str(event.row_key.value or "")
        if not key.startswith("eb_"):
            return
        idx = int(key[3:])
        if idx >= len(self._results):
            return
        r = self._results[idx]
        self._add_to_queue(r)

    def _add_to_queue(self, r: dict) -> None:
        title   = r.get("title", "Sconosciuto")
        out_dir = _ebook_dl_dir() / _safe_name(title)[:80]
        out_dir.mkdir(parents=True, exist_ok=True)

        item = QueueItem(
            uid       = str(uuid.uuid4()),
            base_url  = "",
            anime_id  = r.get("md5", "") or r.get("book_id", ""),
            slug      = "",
            title     = title,
            out_dir   = out_dir,
            episode   = dict(r),
            item_type = "ebook",
        )
        self.app.add_episodes_to_queue([item])
        self.notify(
            f"«{title[:40]}» aggiunto alla coda",
            severity="information",
        )
