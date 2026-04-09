"""
SystemAlertScreen — blocking full-screen alert for critical errors.

Layer 3: SYSTEM ALERT — opaque, no ESC dismiss.
Used for: permission errors, connection loss, fatal exceptions.
"""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class SystemAlertScreen(ModalScreen[bool]):
    """Full-screen blocking alert for critical system errors."""

    DEFAULT_CSS = """
    SystemAlertScreen {
        layout: vertical;
        align: center middle;
        background: $error;
    }

    SystemAlertScreen #alert-container {
        width: 80%;
        max-width: 60;
        height: auto;
        background: $surface;
        border: thick $error;
        padding: 2 3;
    }

    SystemAlertScreen #alert-title {
        text-style: bold;
        text-align: center;
        margin-bottom: 1;
    }

    SystemAlertScreen #alert-message {
        margin-bottom: 2;
    }

    SystemAlertScreen #alert-action {
        align: center middle;
        height: 3;
    }
    """

    def __init__(
        self,
        title="System Error",
        message="",
        action_label="OK",
        dismissable=True,
        **kwargs,
    ):
        """
        Args:
            title: Alert title.
            message: Descriptive message.
            action_label: Button label.
            dismissable: If False, button is hidden — must be dismissed
                         programmatically via dismiss().
        """
        super().__init__(**kwargs)
        self._title = title
        self._message = message
        self._action_label = action_label
        self._dismissable = dismissable

    def compose(self) -> ComposeResult:
        with Vertical(id="alert-container"):
            yield Label(f"[bold red]🚨 {self._title}[/]", id="alert-title")
            yield Label(self._message, id="alert-message")
            if self._dismissable:
                yield Button(self._action_label, variant="error", id="alert-ok")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "alert-ok":
            self.dismiss(True)
