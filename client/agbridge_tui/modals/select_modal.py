"""
SelectModal — generic single-selection modal.

Used for: model selection, mode selection.

Layer 2: MODAL — translucent overlay with centered list.
Dismisses with the selected value string, or None if cancelled.
"""

from rich.markup import escape as rich_escape
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, ListView, ListItem


class SelectModal(ModalScreen):
    """Single-selection modal with highlighted current item."""

    CSS = """
    SelectModal {
        layout: vertical;
        align: center middle;
        background: transparent;
    }
    #select-dialog {
        width: 90%;
        max-width: 50;
        min-width: 30;
        max-height: 20;
        background: $surface;
        border: thick $secondary;
        padding: 1 2;
    }
    SelectModal .select-title {
        text-style: bold;
        margin-bottom: 1;
    }
    SelectModal ListView {
        height: auto;
        max-height: 12;
        border: none;
        background: transparent;
    }
    SelectModal .select-item {
        padding: 0 1;
        height: 1;
    }
    SelectModal .select-item-current {
        background: $accent;
        color: $text;
    }
    SelectModal .select-cancel {
        margin-top: 1;
        width: 100%;
    }
    """

    def __init__(self, title, items, current_value="", **kwargs):
        """
        Args:
            title: Dialog title text.
            items: list[str] — selectable options.
            current_value: currently selected value (highlighted).
        """
        super().__init__(**kwargs)
        self._title = title
        self._items = items or []
        self._current = current_value

    def compose(self) -> ComposeResult:
        with Vertical(id="select-dialog"):
            yield Label(f"[bold]{self._title}[/]", classes="select-title")
            children = [
                _SelectItem(item_text, item_text == self._current)
                for item_text in self._items
            ]
            yield ListView(*children, id="select-list")
            yield Button("Cancel", variant="default", classes="select-cancel", id="select-cancel")

    def on_list_view_selected(self, event: ListView.Selected):
        item = event.item
        if isinstance(item, _SelectItem):
            self.dismiss(item.value)

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "select-cancel":
            self.dismiss(None)

    def on_click(self, event):
        """Click outside the dialog → dismiss."""
        try:
            dialog = self.query_one("#select-dialog")
            if event.screen_offset not in dialog.region:
                self.dismiss(None)
        except Exception:
            pass


class _SelectItem(ListItem):
    """A single selectable item in the SelectModal."""

    def __init__(self, value, is_current=False, **kwargs):
        super().__init__(**kwargs)
        self.value = value
        self._is_current = is_current

    def compose(self) -> ComposeResult:
        prefix = "● " if self._is_current else "  "
        yield Label(f"{prefix}{rich_escape(str(self.value))}")
        if self._is_current:
            self.add_class("select-item-current")
        self.add_class("select-item")
