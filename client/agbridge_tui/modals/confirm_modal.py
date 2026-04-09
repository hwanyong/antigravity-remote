"""
ConfirmModal — dangerous command confirmation dialog.

Used for: IDE_CLOSE during ACTIVE, WORKSPACE_DELETE.

Layer 2: ALERT — translucent overlay with centered dialog.
"""

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class ConfirmModal(ModalScreen):
    """Confirmation dialog for dangerous operations."""

    CSS = """
    ConfirmModal {
        layout: vertical;
        align: center middle;
        background: transparent;
    }
    #dialog {
        width: 90%;
        max-width: 50;
        min-width: 30;
        max-height: 14;
        background: $surface;
        border: thick $error;
        padding: 1 2;
    }
    ConfirmModal .warning-text {
        margin: 1 0;
    }
    ConfirmModal Horizontal {
        align: right middle;
        height: 3;
    }
    ConfirmModal Button {
        margin-left: 1;
    }
    """

    def __init__(self, title="Confirm", message="", confirm_label="Confirm", **kwargs):
        super().__init__(**kwargs)
        self._title = title
        self._message = message
        self._confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(f"[bold red]⚠️  {self._title}[/]")
            yield Label(self._message, classes="warning-text")
            with Horizontal():
                yield Button("Cancel", variant="default", id="cancel")
                yield Button(self._confirm_label, variant="error", id="confirm")

    def on_button_pressed(self, event: Button.Pressed):
        self.dismiss(event.button.id == "confirm")

    def on_click(self, event):
        """Click outside the dialog → dismiss."""
        try:
            main_content = self.query_one("#dialog")
            if event.screen_offset not in main_content.region:
                self.dismiss(False)
        except Exception:
            pass
