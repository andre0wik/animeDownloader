from textual.app        import ComposeResult
from textual.screen     import Screen
from textual.widgets    import Button, Footer, Header, Static
from textual.containers import Vertical
from textual            import on

from .search        import SearchScreen
from .manga_search  import MangaSearchScreen
from .ebook_search  import EbookSearchScreen
from .queue         import QueueScreen
from .settings      import SettingsScreen
from .file_manager  import RemoteFileManagerScreen


class MainMenuScreen(Screen):
    BINDINGS = [
        ("q",      "app.quit",       "Esci"),
        ("ctrl+d", "app.open_queue", "Coda"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="main-menu"):
            yield Static(
                "[bold cyan]Scegli sorgente[/bold cyan]",
                id="main-title",
            )
            yield Button("Anime / Film  ·  AnimeUnity",    id="go-anime",       variant="primary")
            yield Button("Manga / Manhwa  ·  6 piattaforme", id="go-manga",      variant="success")
            yield Button("Ebook  ·  Anna's Archive + ZLib", id="go-ebook",    variant="success")
            yield Button("Coda download  (Ctrl+D)",       id="go-queue",       variant="default")
            yield Button("Impostazioni",                  id="go-settings",    variant="default")
            yield Button("File Manager SSH",              id="go-filemanager", variant="warning")
        yield Footer()

    @on(Button.Pressed, "#go-anime")
    def go_anime(self) -> None:
        self.app.push_screen(SearchScreen())

    @on(Button.Pressed, "#go-manga")
    def go_manga(self) -> None:
        self.app.push_screen(MangaSearchScreen())

    @on(Button.Pressed, "#go-ebook")
    def go_ebook(self) -> None:
        self.app.push_screen(EbookSearchScreen())

    @on(Button.Pressed, "#go-queue")
    def go_queue(self) -> None:
        self.app.push_screen(QueueScreen())

    @on(Button.Pressed, "#go-settings")
    def go_settings(self) -> None:
        self.app.push_screen(SettingsScreen())

    @on(Button.Pressed, "#go-filemanager")
    def go_filemanager(self) -> None:
        self.app.push_screen(RemoteFileManagerScreen())
