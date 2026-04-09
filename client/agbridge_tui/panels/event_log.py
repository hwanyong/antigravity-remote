"""
Event Log — ModalScreen popup showing real-time WS event stream.

Color-coded by event type:
  SYS_* → yellow, FS_* → blue, GIT_* → green, UI_* → magenta, PING → dim

Opened via View → Event Log. Escape to close.
Events continue to be collected even while the modal is closed.
"""

import time

from textual.screen import ModalScreen
from textual.widgets import RichLog, Static
from textual.containers import Vertical
from rich.markup import escape as rich_escape


# Event type → color mapping
EVENT_COLORS = {
    "SYS_": "yellow",
    "FS_": "dodger_blue",
    "GIT_": "green",
    "UI_": "magenta",
    "PING": "dim",
    "PONG": "dim",
    "CMD_": "cyan",
}

MAX_LOG_LINES = 500


class EventLogModal(ModalScreen[None]):
    """Popup modal for viewing the event stream. Layer 1: always fullscreen."""

    BINDINGS = [
        ("escape", "dismiss_panel", "Close"),
    ]

    DEFAULT_CSS = """
    EventLogModal {
        layout: vertical;
        align: center middle;
        background: transparent;
    }

    EventLogModal #eventlog-container {
        width: 95%;
        height: 80%;
        background: $surface;
        border: tall $primary;
        padding: 0;
    }

    EventLogModal #eventlog-title {
        text-align: center;
        text-style: bold;
        padding: 0 0 0 0;
        dock: top;
        height: 1;
    }

    EventLogModal #eventlog-richlog {
        height: 1fr;
        padding: 0 1;
    }
    """

    def __init__(self, entries):
        """
        Args:
            entries: list of pre-formatted Rich markup strings.
        """
        super().__init__()
        self._entries = entries

    def compose(self):
        with Vertical(id="eventlog-container"):
            yield Static("📋 Event Log  [dim](ESC to close)[/]", id="eventlog-title")
            yield RichLog(highlight=True, markup=True, wrap=True, id="eventlog-richlog")

    def on_mount(self):
        log = self.query_one("#eventlog-richlog", RichLog)
        for entry in self._entries:
            log.write(entry)

    def action_dismiss_panel(self):
        self.dismiss(None)

    def on_click(self, event):
        """Click outside the dialog → dismiss."""
        try:
            main_content = self.query_one("#eventlog-container")
            if event.screen_offset not in main_content.region:
                self.dismiss(None)
        except Exception:
            pass


class EventLogBuffer:
    """
    Headless event buffer that collects events regardless of modal state.
    The modal reads from this buffer when opened.
    """

    def __init__(self, max_lines=MAX_LOG_LINES):
        self._entries = []
        self._max_lines = max_lines

    @property
    def entries(self):
        return self._entries

    def log_event(self, event_type, data=None, ts=None):
        """Add an event entry to the buffer."""
        ts_str = time.strftime("%H:%M:%S", time.localtime(ts)) if ts else time.strftime("%H:%M:%S")

        color = "white"
        for prefix, c in EVENT_COLORS.items():
            if event_type.startswith(prefix):
                color = c
                break

        line = f"[dim]{ts_str}[/] [{color}]{event_type}[/]"

        if data and isinstance(data, dict):
            summary = self._summarize(event_type, data)
            if summary:
                line += f"\n       {summary}"

        self._entries.append(line)

        if len(self._entries) > self._max_lines:
            self._entries = self._entries[-self._max_lines:]

    def log_result(self, cmd_type, result):
        """Log a command result."""
        ts_str = time.strftime("%H:%M:%S")
        ok = result.get("ok", False) if isinstance(result, dict) else False
        icon = "✅" if ok else "❌"
        error = result.get("error", "") if isinstance(result, dict) else str(result)

        line = f"[dim]{ts_str}[/] {icon} [cyan]{cmd_type}_RESULT[/]"
        if not ok and error:
            line += f"\n       [red]{rich_escape(error)}[/]"

        self._entries.append(line)

    def _summarize(self, event_type, data):
        """Create a short summary of event payload."""
        if "path" in data:
            return f"path: {rich_escape(data['path'])}"
        if "state" in data:
            return f"state: {data['state']}"
        if "branch" in data:
            mod_count = len(data.get("modified", []))
            return f"branch: {data['branch']} modified: {mod_count}"
        if "has_pending_edits" in data:
            return f"pending: {data['has_pending_edits']}"
        return ""
