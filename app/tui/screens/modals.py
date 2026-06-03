from textual.app      import ComposeResult
from textual.screen   import Screen
from textual.widgets  import Button, Input, Static
from textual.containers import Horizontal, Vertical
from textual          import on


class ConfirmModal(Screen):
    BINDINGS = [("escape", "cancel", "Annulla")]

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Static(self._message, id="confirm-msg")
            with Horizontal(id="confirm-btns"):
                yield Button("Conferma", id="confirm-ok",     variant="error")
                yield Button("Annulla",  id="confirm-cancel", variant="default")

    @on(Button.Pressed, "#confirm-ok")
    def do_ok(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#confirm-cancel")
    def action_cancel(self) -> None:
        self.dismiss(False)


class InputModal(Screen):
    BINDINGS = [("escape", "cancel", "Annulla")]

    def __init__(self, title: str, placeholder: str = "") -> None:
        super().__init__()
        self._title       = title
        self._placeholder = placeholder

    def compose(self) -> ComposeResult:
        with Vertical(id="input-box"):
            yield Static(self._title, id="input-title")
            yield Input(placeholder=self._placeholder, id="modal-input")
            with Horizontal(id="input-btns"):
                yield Button("OK",      id="input-ok",     variant="primary")
                yield Button("Annulla", id="input-cancel", variant="default")

    def on_mount(self) -> None:
        self.query_one("#modal-input", Input).focus()

    @on(Button.Pressed, "#input-ok")
    def do_ok(self) -> None:
        val = self.query_one("#modal-input", Input).value.strip()
        self.dismiss(val or None)

    @on(Button.Pressed, "#input-cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted)
    def on_submit(self) -> None:
        self.do_ok()
