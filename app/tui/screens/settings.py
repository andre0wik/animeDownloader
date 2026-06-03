from textual.app        import ComposeResult
from textual.binding    import Binding
from textual.screen     import Screen
from textual.widgets    import Button, Checkbox, Footer, Header, Input, Label, Static
from textual.containers import Horizontal, Vertical
from textual            import on

from ...config import _CFG, save_settings


class SettingsScreen(Screen):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Annulla", priority=True),
        Binding("ctrl+b", "app.pop_screen", "Annulla", priority=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="settings-form"):
            yield Static("[bold cyan]Impostazioni[/bold cyan]", id="settings-title")
            with Vertical(classes="sfield"):
                yield Label("Cartella download (AnimeUnity/ e MangaDex/ al suo interno)")
                yield Input(_CFG["download_dir"], id="s-download-dir")
            with Vertical(classes="sfield"):
                yield Label("Server SSH  (utente@host)")
                yield Input(_CFG["ssh_host"], id="s-ssh-host")
            with Vertical(classes="sfield"):
                yield Label("Percorso remoto base")
                yield Input(_CFG["ssh_remote_base"], id="s-ssh-remote")
            with Vertical(classes="sfield"):
                yield Label("URL AnimeUnity")
                yield Input(_CFG["animeunity_base"], id="s-au-base")
            with Vertical(classes="sfield"):
                yield Label("Download paralleli (1–8)")
                yield Input(str(_CFG["max_concurrent"]), id="s-max-dl")
            with Vertical(classes="sfield"):
                yield Label("Auto-sync su SSH dopo ogni download")
                yield Checkbox("Abilitato", value=bool(_CFG.get("auto_sync")), id="s-auto-sync")
            yield Static("[bold cyan]Manga[/bold cyan]", classes="sfield-header")
            with Vertical(classes="sfield"):
                yield Label("Converti archivio in PDF dopo il download (.cbz/.zip/.cbt → PDF ordinato per pagina)")
                yield Checkbox("Abilitato", value=bool(_CFG.get("cbz_to_pdf")), id="s-cbz-to-pdf")
            with Vertical(classes="sfield"):
                yield Label("Toonily — Username (per contenuti adult, opzionale)")
                yield Input(_CFG.get("toonily_user", ""), id="s-toonily-user")
            with Vertical(classes="sfield"):
                yield Label("Toonily — Password")
                yield Input(_CFG.get("toonily_pass", ""), password=True, id="s-toonily-pass")
            yield Static("[bold cyan]Z-Library[/bold cyan]", classes="sfield-header")
            with Vertical(classes="sfield"):
                yield Label("Email account Z-Library")
                yield Input(_CFG.get("zlib_email", ""), id="s-zlib-email")
            with Vertical(classes="sfield"):
                yield Label("Password Z-Library")
                yield Input(_CFG.get("zlib_password", ""), password=True, id="s-zlib-password")
            yield Static("[bold cyan]Manutenzione[/bold cyan]", classes="sfield-header")
            with Vertical(classes="sfield"):
                yield Label("Elimina tutti i file .log nella cartella download")
                yield Button("Cancella tutti i log", id="clear-logs", variant="warning")
            with Horizontal(id="settings-btns"):
                yield Button("Salva",    id="save-settings",   variant="primary")
                yield Button("Annulla",  id="cancel-settings", variant="default")
        yield Footer()

    @on(Button.Pressed, "#save-settings")
    def do_save(self) -> None:
        def _val(wid: str) -> str:
            return self.query_one(f"#{wid}", Input).value.strip()

        try:
            mc = int(_val("s-max-dl"))
            if not (1 <= mc <= 8):
                raise ValueError
        except ValueError:
            self.notify("Download paralleli deve essere un numero tra 1 e 8", severity="error")
            return

        _CFG["download_dir"]    = _val("s-download-dir")
        _CFG["ssh_host"]        = _val("s-ssh-host")
        _CFG["ssh_remote_base"] = _val("s-ssh-remote")
        _CFG["animeunity_base"] = _val("s-au-base")
        _CFG["max_concurrent"]  = mc
        _CFG["auto_sync"]       = self.query_one("#s-auto-sync", Checkbox).value
        _CFG["cbz_to_pdf"]      = self.query_one("#s-cbz-to-pdf", Checkbox).value
        _CFG["toonily_user"]    = _val("s-toonily-user")
        _CFG["toonily_pass"]    = _val("s-toonily-pass")
        _CFG["zlib_email"]      = _val("s-zlib-email")
        _CFG["zlib_password"]   = _val("s-zlib-password")
        save_settings(_CFG)
        self.notify("Impostazioni salvate", severity="information")
        self.app.pop_screen()

    @on(Button.Pressed, "#clear-logs")
    def do_clear_logs(self) -> None:
        from pathlib import Path
        dl_dir = Path(_CFG.get("download_dir", "."))
        logs = list(dl_dir.rglob("*.log"))
        for f in logs:
            try:
                f.unlink()
            except Exception:
                pass
        self.notify(
            f"{len(logs)} file .log eliminati" if logs else "Nessun file .log trovato",
            severity="information",
        )

    @on(Button.Pressed, "#cancel-settings")
    def do_cancel(self) -> None:
        self.app.pop_screen()
