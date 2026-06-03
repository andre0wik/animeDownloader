from textual.app        import ComposeResult
from textual.binding    import Binding
from textual.screen     import Screen
from textual.widgets    import (
    Button, DataTable, Footer, Header, Input, Label, Select,
    SelectionList, Static,
)
from textual.containers import Horizontal, Vertical
from textual.timer      import Timer
from textual            import on, work
from rich.text          import Text as RichText

from ...manga.registry   import PLATFORMS, PLATFORM_LIST
from ...manga.base       import MangaPlatform
from ...mangadex.download import _safe_name, local_manga_status
from ...mangadex.history  import load_manga_history, save_manga_history
from ..helpers            import _queue_status_text
from .manga_menu          import MangaMenuScreen


def _sv(val) -> str:
    return str(val) if isinstance(val, str) else ""


class MangaSearchScreen(Screen):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Indietro", priority=True),
        Binding("ctrl+b", "app.pop_screen", "Indietro", priority=True),
        Binding("ctrl+d", "app.open_queue", "Coda"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="filters"):
            with Horizontal(classes="filter-row", id="row-platform"):
                yield Label("Piattaforma:", classes="flabel")
                yield Select(
                    [(p.name, p.id) for p in PLATFORM_LIST],
                    id="mg-platform",
                    allow_blank=False,
                    value=PLATFORM_LIST[0].id,
                )
            with Horizontal(classes="filter-row"):
                yield Label("Titolo:", classes="flabel")
                yield Input(placeholder="cerca manga / manhwa...", id="mg-title")
            with Horizontal(classes="filter-row", id="row-lang-origin"):
                with Horizontal(classes="filter-pair", id="pair-lang"):
                    yield Label("Lingua:", classes="flabel")
                    yield Select([], id="mg-lang", allow_blank=True, prompt="(tutte)")
                with Horizontal(classes="filter-pair", id="pair-origin"):
                    yield Label("Tipo:", classes="flabel")
                    yield Select([], id="mg-origin", allow_blank=True, prompt="(tutti)")
            with Horizontal(classes="filter-row", id="row-status-demo"):
                with Horizontal(classes="filter-pair", id="pair-status"):
                    yield Label("Stato:", classes="flabel")
                    yield Select([], id="mg-status", allow_blank=True, prompt="(tutti)")
                with Horizontal(classes="filter-pair", id="pair-demo"):
                    yield Label("Target:", classes="flabel")
                    yield Select([], id="mg-demo", allow_blank=True, prompt="(tutti)")
            with Horizontal(classes="filter-row", id="row-rating-order"):
                with Horizontal(classes="filter-pair", id="pair-rating"):
                    yield Label("Età:", classes="flabel")
                    yield Select([], id="mg-rating", allow_blank=True, prompt="(tutti)")
                with Horizontal(classes="filter-pair", id="pair-order"):
                    yield Label("Ordina:", classes="flabel")
                    yield Select([], id="mg-order", allow_blank=True, prompt="(default)")
            yield SelectionList(id="mg-genres")
            with Horizontal(id="btn-row"):
                yield Button("Cerca",          id="mg-search-btn", variant="primary")
                yield Button("Pulisci filtri", id="mg-clear-btn",  variant="default")
                yield Button("← Indietro",     id="mg-back-btn",   variant="error")
        yield Static("", id="search-status")
        yield DataTable(id="results", cursor_type="row")
        yield Static("", classes="dl-status", id="dl-status")
        yield Footer()

    # ----------------------------------------------------------------- mount

    def on_mount(self) -> None:
        self._results:            list[dict]    = []
        self._history:            list[dict]    = []
        self._auto_timer:         Timer | None  = None
        self._searching:          bool          = False
        self._platform:           MangaPlatform = PLATFORM_LIST[0]
        self._lang:               str           = ""
        self._applying_platform:  bool          = False   # blocca eventi spurii da set_options

        table = self.query_one("#results", DataTable)
        table.add_column("#",       width=4)
        table.add_column("Titolo",  width=34)
        table.add_column("Tipo",    width=10)
        table.add_column("Stato",   width=12)
        table.add_column("Rating",  width=10)
        table.add_column("Lingue",  width=14)
        table.add_column("Generi",  width=20)

        self._apply_platform(self._platform)
        self._load_history_rows()
        self.set_interval(1.0, self._refresh_status)

    # --------------------------------------------------------- platform switch

    def _apply_platform(self, platform: MangaPlatform) -> None:
        self._applying_platform = True
        try:
            sf = platform.supported_filters

            has_lang_origin  = bool({"lang", "origin"} & sf)
            has_status_demo  = bool({"status", "demographic"} & sf)
            has_rating_order = bool({"rating", "order"} & sf)

            self.query_one("#row-lang-origin").display  = has_lang_origin
            self.query_one("#row-status-demo").display  = has_status_demo
            self.query_one("#row-rating-order").display = has_rating_order
            self.query_one("#mg-genres").display        = "genres" in sf

            self.query_one("#pair-lang").display   = "lang" in sf
            self.query_one("#pair-origin").display = "origin" in sf
            self.query_one("#pair-status").display = "status" in sf
            self.query_one("#pair-demo").display   = "demographic" in sf
            self.query_one("#pair-rating").display = "rating" in sf
            self.query_one("#pair-order").display  = "order" in sf

            def _set(wid: str, opts: list[tuple[str, str]]) -> None:
                self.query_one(wid, Select).set_options((lbl, val) for lbl, val in opts)

            _set("#mg-lang",   platform.lang_opts)
            _set("#mg-origin", platform.origin_opts)
            _set("#mg-status", platform.status_opts)
            _set("#mg-demo",   platform.demographic_opts)
            _set("#mg-rating", platform.rating_opts)
            _set("#mg-order",  platform.order_opts)

            if "lang" in sf and platform.lang_opts:
                self.query_one("#mg-lang", Select).value = platform.lang_opts[0][1]

            genres = self.query_one("#mg-genres", SelectionList)
            genres.clear_options()
            for label, value in platform.genres:
                genres.add_option((label, value))
        finally:
            self._applying_platform = False

    @on(Select.Changed, "#mg-platform")
    def _platform_changed(self, event: Select.Changed) -> None:
        pid      = _sv(event.value)
        platform = PLATFORMS.get(pid)
        if not platform:
            return
        self._platform = platform
        self._apply_platform(platform)

        # Annulla qualsiasi auto-search pendente generato dagli eventi di set_options
        if self._auto_timer is not None:
            self._auto_timer.stop()
            self._auto_timer = None

        self.query_one("#results", DataTable).clear()
        self._results = []
        self._history = []
        self._load_history_rows()
        self.query_one("#search-status", Static).update(
            self._idle_hint()
        )

    def _idle_hint(self) -> str:
        if self._platform.supports_empty_search:
            return "[dim]Inserisci un titolo o usa i filtri per sfogliare[/dim]"
        return "[dim]Inserisci un titolo per cercare[/dim]"

    # --------------------------------------------------------------- status

    def _refresh_status(self) -> None:
        if not self._searching:
            self.query_one("#dl-status", Static).update(
                _queue_status_text(getattr(self.app, "_queue", []))
            )

    # --------------------------------------------------------------- history

    def _load_history_rows(self) -> None:
        all_hist = load_manga_history()
        self._history = [
            h for h in all_hist
            if h.get("platform", "mangadex") == self._platform.id
        ]
        table = self.query_one("#results", DataTable)
        table.clear()
        for h in self._history[:10]:
            year = (h.get("last_used", "") or "")[:4]
            complete, partial = local_manga_status(self._platform.out_dir(h["title"]))
            dl_suffix = ""
            if complete:
                dl_suffix = f"  [{len(complete)} cap ✓]"
            elif partial:
                dl_suffix = f"  [{len(partial)} cap ~]"
            table.add_row(
                RichText(">>",                   style="yellow bold"),
                RichText(h["title"] + dl_suffix, style="yellow"),
                RichText("",                     style="yellow"),
                RichText("recente",              style="yellow"),
                RichText("",                     style="yellow"),
                RichText(h.get("lang", ""),      style="yellow"),
                RichText(year,                   style="yellow"),
                key=f"hist_{h['manga_id']}",
            )

    # --------------------------------------------------------------- auto-search

    def _schedule_auto_search(self) -> None:
        """Auto-search solo su piattaforme che lo supportano con titolo vuoto."""
        if self._applying_platform:
            return
        if self.query_one("#mg-title", Input).value.strip():
            return
        if not self._platform.supports_empty_search:
            return
        if self._auto_timer is not None:
            self._auto_timer.stop()
        self._auto_timer = self.set_timer(0.6, self.do_search)

    @on(Input.Submitted, "#mg-title")
    def _title_submitted(self, _) -> None:
        self.do_search()

    @on(Select.Changed)
    def _filter_changed(self, event: Select.Changed) -> None:
        if event.select.id == "mg-platform":
            return
        if self._applying_platform:
            return
        self._schedule_auto_search()

    @on(SelectionList.SelectedChanged)
    def _genre_changed(self, _) -> None:
        self._schedule_auto_search()

    # --------------------------------------------------------------- search

    @on(Button.Pressed, "#mg-search-btn")
    def do_search(self) -> None:
        title = self.query_one("#mg-title", Input).value.strip()
        sf    = self._platform.supported_filters

        # Piattaforme che non supportano ricerca senza titolo
        if not title and not self._platform.supports_empty_search:
            self.query_one("#search-status", Static).update(
                "[dim]Inserisci un titolo per cercare[/dim]"
            )
            return

        filters: dict = {}
        if "lang" in sf:
            filters["lang"] = _sv(self.query_one("#mg-lang", Select).value)
        if "origin" in sf:
            filters["origin"] = _sv(self.query_one("#mg-origin", Select).value)
        if "status" in sf:
            filters["status"] = _sv(self.query_one("#mg-status", Select).value)
        if "demographic" in sf:
            filters["demographic"] = _sv(self.query_one("#mg-demo", Select).value)
        if "rating" in sf:
            filters["rating"] = _sv(self.query_one("#mg-rating", Select).value)
        if "order" in sf:
            filters["order"] = _sv(self.query_one("#mg-order", Select).value)
        if "genres" in sf:
            filters["genres"] = list(self.query_one("#mg-genres", SelectionList).selected)

        self._lang      = filters.get("lang", "")
        self._searching = True
        self.query_one("#search-status", Static).update("[yellow]Ricerca in corso...[/yellow]")
        self._search_worker(title=title, filters=filters)

    @work(thread=True)
    def _search_worker(self, title: str, filters: dict) -> None:
        try:
            results = self._platform.search(title, filters)
        except Exception as e:
            self.app.call_from_thread(self._show_error, str(e))
            return
        self.app.call_from_thread(self._populate_results, results)

    def _show_error(self, msg: str) -> None:
        self._searching = False
        self.query_one("#search-status", Static).update(f"[red]Errore: {msg}[/red]")

    def _populate_results(self, results: list[dict]) -> None:
        self._searching = False
        self._results   = results
        history_ids     = {h["manga_id"] for h in self._history}
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
        type_map = {"ja": "Manga", "ko": "Manhwa", "zh": "Manhua", "zh-hk": "Manhua"}
        for i, item in enumerate(results[:50], 1):
            tipo  = type_map.get(item.get("original_lang", ""), item.get("original_lang", ""))
            style = "yellow" if item["manga_id"] in history_ids else ""
            complete, partial = local_manga_status(self._platform.out_dir(item["title"]))
            dl_suffix = ""
            if complete:
                dl_suffix = f"  [{len(complete)} cap ✓]"
            elif partial:
                dl_suffix = f"  [{len(partial)} cap ~]"
            table.add_row(
                RichText(str(i),                         style=style),
                RichText(item["title"] + dl_suffix,      style=style),
                RichText(tipo,                           style=style),
                RichText(item.get("status", ""),         style=style),
                RichText(item.get("content_rating", ""), style=style),
                RichText(item.get("languages", ""),      style=style),
                RichText(item.get("genres", ""),         style=style),
                key=f"mg_{item['manga_id']}",
            )

    # --------------------------------------------------------------- buttons

    @on(Button.Pressed, "#mg-back-btn")
    def go_back(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#mg-clear-btn")
    def clear_filters(self) -> None:
        self.query_one("#mg-title", Input).value = ""
        for wid in ("#mg-lang", "#mg-origin", "#mg-status",
                    "#mg-demo", "#mg-rating", "#mg-order"):
            self.query_one(wid, Select).value = Select.BLANK
        self.query_one("#mg-genres", SelectionList).deselect_all()
        self.query_one("#results", DataTable).clear()
        self._results = []
        self._load_history_rows()
        self.query_one("#search-status", Static).update(self._idle_hint())

    # --------------------------------------------------------------- row select

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key      = str(event.row_key.value or "")
        manga_id = None
        title    = ""
        lang     = self._lang or ""

        if key.startswith("mg_"):
            manga_id = key[3:]
            item = next((r for r in self._results if r["manga_id"] == manga_id), None)
            if not item:
                return
            title = item["title"]
        elif key.startswith("hist_"):
            manga_id = key[5:]
            h = next((h for h in self._history if h["manga_id"] == manga_id), None)
            if not h:
                return
            title = h["title"]
            lang  = h.get("lang", lang)
        else:
            return

        save_manga_history(manga_id, title, lang, self._platform.id)
        out_dir = self._platform.out_dir(title)
        out_dir.mkdir(parents=True, exist_ok=True)
        self.app.push_screen(
            MangaMenuScreen(self._platform, manga_id, title, out_dir, lang)
        )
