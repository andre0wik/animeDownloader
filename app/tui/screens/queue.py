from textual.app        import ComposeResult
from textual.binding    import Binding
from textual.screen     import Screen
from textual.widgets    import Button, DataTable, Footer, Header, Static
from textual.containers import Horizontal
from textual            import on
from rich.text          import Text as RichText

from ..helpers import _parse_last_progress, _queue_status_text


class QueueScreen(Screen):

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Chiudi", priority=True),
        Binding("ctrl+b", "app.pop_screen", "Chiudi", priority=True),
    ]

    _STATUS = {
        "pending":     ("dim",    "..."),
        "downloading": ("yellow", " >> "),
        "done":        ("green",  " OK "),
        "error":       ("red",    " !! "),
    }

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="queue-summary")
        yield DataTable(id="queue-table", cursor_type="row")
        with Horizontal(id="queue-actions"):
            yield Button("Pulisci completati / errori", id="clear-done", variant="default")
            yield Button("← Chiudi", id="queue-back", variant="default")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#queue-table", DataTable)
        table.add_column("Serie + Episodio", width=55, key="label-col")
        table.add_column("Stato",            width=12, key="status-col")
        self._known: set[str] = set()
        self.set_interval(0.5, self._refresh)

    def _refresh(self) -> None:
        items = getattr(self.app, "_queue", [])
        table = self.query_one("#queue-table", DataTable)

        for item in items:
            style, text = self._STATUS.get(item.status, ("", item.status))
            if item.status == "downloading" and item.log_path:
                mib, lbl, pct, eta = _parse_last_progress(item.log_path)
                if mib > 0:
                    short = lbl.replace("MiB/s", "M/s").replace("KiB/s", "K/s")
                    text  = f"{pct:3.0f}% {short}"
            cell = RichText(text, style=style)
            if item.uid not in self._known:
                table.add_row(item.label, cell, key=item.uid)
                self._known.add(item.uid)
            else:
                table.update_cell(item.uid, "status-col", cell, update_width=False)

        self.query_one("#queue-summary", Static).update(
            _queue_status_text(items)
        )

    @on(Button.Pressed, "#queue-back")
    def close_queue(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#clear-done")
    def clear_done(self) -> None:
        to_remove = {i.uid for i in self.app._queue if i.status in ("done", "error")}
        self.app._queue = [i for i in self.app._queue if i.uid not in to_remove]
        table = self.query_one("#queue-table", DataTable)
        for uid in to_remove:
            if uid in self._known:
                table.remove_row(uid)
                self._known.discard(uid)
