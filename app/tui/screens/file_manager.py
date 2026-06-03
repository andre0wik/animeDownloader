from dataclasses import dataclass

from textual.app        import ComposeResult
from textual.binding    import Binding
from textual.screen     import Screen
from textual.widgets    import Button, DataTable, Footer, Header, Label, Static
from textual.containers import Horizontal
from textual            import on, work

from ...config import _CFG
from ...sync.ssh import _ssh_fm
from .modals import ConfirmModal, InputModal


@dataclass
class RemoteEntry:
    name:     str
    is_dir:   bool
    size:     int
    modified: str


def _parse_ls_output(output: str) -> list[RemoteEntry]:
    entries: list[RemoteEntry] = []
    for line in output.splitlines():
        if not line or line.startswith("total"):
            continue
        parts = line.split(None, 7)
        if len(parts) < 8:
            continue
        perms, _, _, _, size_s, date, time_, name = parts
        if name in (".", ".."):
            continue
        is_dir = perms[0] in ("d", "l")
        try:
            size = -1 if is_dir else int(size_s)
        except ValueError:
            size = -1
        entries.append(RemoteEntry(name=name, is_dir=is_dir, size=size, modified=f"{date} {time_}"))
    entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
    return entries


def _fmt_size(size: int) -> str:
    if size < 0:
        return "<DIR>"
    for unit, div in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if size >= div:
            return f"{size / div:.1f} {unit}"
    return f"{size} B"


class RemoteFileManagerScreen(Screen):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Indietro",      priority=True),
        Binding("ctrl+b", "app.pop_screen", "Indietro",      priority=True),
        ("x",      "toggle_select", "Seleziona"),
        ("a",      "select_all",    "Sel. tutto"),
        ("u",      "go_up",         "Su"),
        ("r",      "refresh",       "Aggiorna"),
        ("f5",     "refresh",       "Aggiorna"),
        ("delete", "delete_sel",    "Elimina"),
        ("m",      "move_sel",      "Sposta"),
        ("n",      "new_folder",    "Nuova cartella"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._path:     str               = _CFG["ssh_remote_base"]
        self._entries:  list[RemoteEntry] = []
        self._selected: set[str]          = set()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="fm-diskinfo")
        yield Static("", id="fm-path")
        yield DataTable(id="fm-table", cursor_type="row")
        with Horizontal(id="fm-actions"):
            yield Label("0 selezionati", id="fm-selcount")
            yield Button("Elimina  [Del]", id="fm-btn-del",     variant="error")
            yield Button("Sposta  [M]",    id="fm-btn-move",    variant="warning")
            yield Button("Nuova cartella", id="fm-btn-mkdir",   variant="default")
            yield Button("Aggiorna  [R]",  id="fm-btn-refresh", variant="default")
            yield Button("← Indietro",     id="fm-btn-back",    variant="default")
        yield Footer()

    def on_mount(self) -> None:
        tbl = self.query_one("#fm-table", DataTable)
        tbl.add_column("",           key="sel",  width=3)
        tbl.add_column("Nome",       key="name")
        tbl.add_column("Dimensione", key="size", width=12)
        tbl.add_column("Modificato", key="mod",  width=18)
        self._load()

    @work(thread=True)
    def _load(self) -> None:
        host = _CFG["ssh_host"]
        path = self._path
        df_out, _  = _ssh_fm(host, f"df -h '{path}' 2>/dev/null | tail -1")
        ls_out, rc = _ssh_fm(host, f"ls -la --time-style=long-iso '{path}' 2>&1")
        self.app.call_from_thread(self._populate, df_out, ls_out, rc)

    def _populate(self, df_out: str, ls_out: str, ls_rc: int) -> None:
        if not self.is_mounted:
            return

        disk = self.query_one("#fm-diskinfo", Static)
        parts = df_out.strip().split()
        if len(parts) >= 5:
            disk.update(
                f" Disco  totale [cyan]{parts[1]}[/cyan]  "
                f"usato [yellow]{parts[2]}[/yellow] [dim]({parts[4]})[/dim]  "
                f"libero [green]{parts[3]}[/green]"
            )
        else:
            disk.update("[dim] Spazio disco non disponibile[/dim]")

        self.query_one("#fm-path", Static).update(
            f" [dim]Percorso:[/dim]  [bold white]{self._path}[/bold white]"
        )

        tbl = self.query_one("#fm-table", DataTable)
        tbl.clear()
        self._selected.clear()
        self._update_count()

        if ls_rc != 0:
            self.notify(f"SSH errore: {ls_out[:120]}", severity="error", timeout=10)
            return

        self._entries = _parse_ls_output(ls_out)

        path_stripped = self._path.rstrip("/")
        if "/" in path_stripped and path_stripped:
            tbl.add_row("", "[dim]↑  ..[/dim]", "", "", key="__parent__")

        for e in self._entries:
            label = f"[bold]{e.name}/[/bold]" if e.is_dir else e.name
            tbl.add_row("", label, _fmt_size(e.size), e.modified, key=e.name)

    def _entry(self, name: str) -> RemoteEntry | None:
        return next((e for e in self._entries if e.name == name), None)

    def _update_count(self) -> None:
        n = len(self._selected)
        self.query_one("#fm-selcount", Label).update(
            f"[bold cyan]{n}[/bold cyan] selezionati" if n else "[dim]0 selezionati[/dim]"
        )

    def _mark_row(self, key: str, selected: bool) -> None:
        try:
            self.query_one("#fm-table", DataTable).update_cell(
                key, "sel", "[green]✓[/green]" if selected else ""
            )
        except Exception:
            pass

    def _current_row_key(self) -> str | None:
        tbl = self.query_one("#fm-table", DataTable)
        try:
            cell = tbl.coordinate_to_cell_key(tbl.cursor_coordinate)
            return cell.row_key.value
        except Exception:
            return None

    def _full_path(self, name: str) -> str:
        return f"{self._path.rstrip('/')}/{name}"

    def _reload(self) -> None:
        self._selected.clear()
        self._update_count()
        self._load()

    def _parent_path(self) -> str:
        path = self._path.rstrip("/")
        if "/" not in path:
            return path
        parent = path.rsplit("/", 1)[0]
        return parent or "/"

    def action_toggle_select(self) -> None:
        key = self._current_row_key()
        if not key or key == "__parent__":
            return
        if key in self._selected:
            self._selected.discard(key)
            self._mark_row(key, False)
        else:
            self._selected.add(key)
            self._mark_row(key, True)
        self._update_count()

    def action_select_all(self) -> None:
        for e in self._entries:
            self._selected.add(e.name)
            self._mark_row(e.name, True)
        self._update_count()

    def action_go_up(self) -> None:
        parent = self._parent_path()
        if parent != self._path:
            self._path = parent
            self._load()

    def action_refresh(self) -> None:
        self._reload()

    def action_delete_sel(self) -> None:
        if not self._selected:
            self.notify("Nessun elemento selezionato", severity="warning")
            return
        names = sorted(self._selected)
        preview = "\n".join(f"  • {n}" for n in names[:6])
        if len(names) > 6:
            preview += f"\n  … e altri {len(names) - 6}"
        msg = f"[bold red]Eliminare {len(names)} elemento/i?[/bold red]\n\n{preview}"

        def _on_confirm(ok: bool | None) -> None:
            if ok:
                self._do_delete(list(self._selected))

        self.app.push_screen(ConfirmModal(msg), _on_confirm)

    def action_move_sel(self) -> None:
        if not self._selected:
            self.notify("Nessun elemento selezionato", severity="warning")
            return

        def _on_dest(dest: str | None) -> None:
            if dest:
                self._do_move(list(self._selected), dest)

        self.app.push_screen(
            InputModal("Destinazione (percorso assoluto remoto):", self._path + "/"),
            _on_dest,
        )

    def action_new_folder(self) -> None:
        def _on_name(name: str | None) -> None:
            if name:
                self._do_mkdir(name)

        self.app.push_screen(InputModal("Nome nuova cartella:"), _on_name)

    @on(Button.Pressed, "#fm-btn-back")
    def btn_back(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#fm-btn-del")
    def btn_delete(self) -> None:
        self.action_delete_sel()

    @on(Button.Pressed, "#fm-btn-move")
    def btn_move(self) -> None:
        self.action_move_sel()

    @on(Button.Pressed, "#fm-btn-mkdir")
    def btn_mkdir(self) -> None:
        self.action_new_folder()

    @on(Button.Pressed, "#fm-btn-refresh")
    def btn_refresh(self) -> None:
        self.action_refresh()

    @on(DataTable.RowSelected)
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        key = event.row_key.value
        if key == "__parent__":
            self.action_go_up()
            return
        entry = self._entry(key)
        if entry and entry.is_dir:
            self._path = self._full_path(entry.name)
            self._load()

    @work(thread=True)
    def _do_delete(self, names: list[str]) -> None:
        host  = _CFG["ssh_host"]
        paths = " ".join(f"'{self._full_path(n)}'" for n in names)
        out, rc = _ssh_fm(host, f"rm -rf {paths}")
        if rc == 0:
            self.app.call_from_thread(
                self.notify, f"{len(names)} elemento/i eliminati", severity="information"
            )
        else:
            self.app.call_from_thread(
                self.notify, f"Errore eliminazione: {out[:100]}", severity="error", timeout=10
            )
        self.app.call_from_thread(self._reload)

    @work(thread=True)
    def _do_move(self, names: list[str], dest: str) -> None:
        host  = _CFG["ssh_host"]
        srcs  = " ".join(f"'{self._full_path(n)}'" for n in names)
        out, rc = _ssh_fm(host, f"mv {srcs} '{dest}'")
        if rc == 0:
            self.app.call_from_thread(
                self.notify, f"{len(names)} elemento/i spostati", severity="information"
            )
        else:
            self.app.call_from_thread(
                self.notify, f"Errore spostamento: {out[:100]}", severity="error", timeout=10
            )
        self.app.call_from_thread(self._reload)

    @work(thread=True)
    def _do_mkdir(self, name: str) -> None:
        host = _CFG["ssh_host"]
        path = self._full_path(name)
        out, rc = _ssh_fm(host, f"mkdir -p '{path}'")
        if rc == 0:
            self.app.call_from_thread(
                self.notify, f"Cartella '{name}' creata", severity="information"
            )
        else:
            self.app.call_from_thread(
                self.notify, f"Errore mkdir: {out[:100]}", severity="error", timeout=10
            )
        self.app.call_from_thread(self._reload)
