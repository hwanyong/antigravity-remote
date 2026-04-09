"""
TextViewerModal — scrollable read-only text viewer.

Used for: CMD_FILE_READ results, CMD_GIT_OP diff/log output.

Layer 1: MODAL — always fullscreen.
"""

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import TextArea, Label
from textual.containers import Vertical


class TextViewerModal(ModalScreen):
    """Full-screen scrollable text viewer modal."""

    CSS = """
    TextViewerModal {
        layout: vertical;
        align: center middle;
        background: transparent;
    }
    #dialog {
        width: 95%;
        height: 80%;
        background: $surface;
        border: tall $primary;
        padding: 0;
    }
    TextViewerModal Label {
        height: 1;
        padding: 0 2;
        background: $accent;
        color: $text;
    }
    TextViewerModal TextArea {
        height: 1fr;
    }
    """

    BINDINGS = [
        ("escape", "dismiss_modal", "Close"),
        ("q", "dismiss_modal", "Close"),
    ]

    def __init__(self, title="", content="", **kwargs):
        super().__init__(**kwargs)
        self._title = title
        self._content = content

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(f"  📄 {self._title}    [dim][q/Esc] Close[/]")
            yield TextArea(
                self._content,
                read_only=True,
                show_line_numbers=True,
                id="viewer-text",
            )

    def action_dismiss_modal(self):
        self.dismiss()

    def on_click(self, event):
        """Click outside the dialog → dismiss."""
        try:
            main_content = self.query_one("#dialog")
            if event.screen_offset not in main_content.region:
                self.dismiss(None)
        except Exception:
            pass
