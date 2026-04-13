"""
Menu System — ModalScreen-based dropdown menus triggered by F-keys.

Uses Textual's ModalScreen for proper floating overlay.
Supports dynamic X offset for menu-bar-style positioning.
"""

from rich.text import Text

from textual.screen import ModalScreen
from textual.widgets import OptionList
from textual.widgets.option_list import Option


MENU_WIDTH = 34


def _item(label, shortcut="", *, id):
    """Build an Option with right-aligned shortcut hint."""
    t = Text()
    t.append(f" {label}")
    if shortcut:
        padding = MENU_WIDTH - len(label) - len(shortcut) - 3
        t.append(" " * max(padding, 2))
        t.append(shortcut, style="dim")
    return Option(t, id=id)


# ── Menu definitions ──────────────────────────────────────

FILE_MENU_ITEMS = [
    _item("Open Workspace...", id="cmd_open_workspace"),
    None,
    _item("Refresh", "^R", id="refresh_snapshot"),
    _item("Quit", "^Q", id="quit"),
]

VIEW_MENU_ITEMS = [
    _item("Event Log", id="toggle_event_log"),
    None,
    _item("Status", id="cmd_status"),
    _item("Snapshot", id="cmd_snapshot"),
    None,
    _item("File Read", id="cmd_file_read"),
]

AGENT_MENU_ITEMS = [
    _item("Accept All", id="cmd_accept_all"),
    _item("Reject All", id="cmd_reject_all"),
    None,
    _item("Cancel Generation", id="cmd_cancel_generation"),
    _item("New Conversation", id="cmd_new_conversation"),
    None,
    _item("Retry (on error)", id="cmd_retry"),
    _item("Dismiss Error", id="cmd_dismiss_error"),
    None,
    _item("Refresh Models", id="cmd_refresh_models"),
    _item("Clear Conv. Cache", id="cmd_clear_cache"),
]

GIT_MENU_ITEMS = [
    _item("Git Status", id="cmd_git_status"),
    _item("Git Commit", id="cmd_git_commit"),
]


# ── Generic menu screen ──────────────────────────────────

class MenuScreen(ModalScreen[str]):
    """Reusable floating menu — positioned at bottom with dynamic X offset."""

    BINDINGS = [
        ("escape", "dismiss_menu", "Close"),
    ]

    DEFAULT_CSS = """
    MenuScreen {
        layout: vertical;
        align: left bottom;
        background: transparent;
    }

    MenuScreen #menu-list {
        width: 36;
        height: auto;
        max-height: 70%;
        margin: 0 0 1 0;
        background: $surface;
        border: tall $primary;
    }

    MenuScreen #menu-list > .option-list--option-highlighted {
        background: $accent;
        color: $text;
    }

    MenuScreen #menu-list > .option-list--separator {
        color: $primary-darken-2;
    }
    """

    def __init__(self, items, x_offset=0, align_right=False):
        super().__init__()
        self._items = items
        self._x_offset = x_offset
        self._align_right = align_right

    def compose(self):
        yield OptionList(*self._items, id="menu-list")

    def on_mount(self):
        ol = self.query_one("#menu-list")
        if self._align_right:
            self.styles.align = ("right", "bottom")
            ol.styles.margin = (0, self._x_offset, 1, 0)
        elif self._x_offset > 0:
            ol.styles.margin = (0, 0, 1, self._x_offset)
        ol.focus()

    def on_option_list_option_selected(self, event):
        self.dismiss(event.option_id)

    def on_click(self, event):
        """Click outside the menu → dismiss."""
        ol = self.query_one("#menu-list")
        if event.screen_offset not in ol.region:
            self.dismiss(None)

    def action_dismiss_menu(self):
        self.dismiss(None)
