"""
Settings Panel — ModalScreen for daemon/workspace diagnostics.

Shows: connection info, workspace status, recent command results.
Accessed via F10.
"""

import time

from rich.text import Text

from textual.screen import ModalScreen
from textual.widgets import Static
from textual.containers import Vertical, VerticalScroll
from rich.markup import escape as rich_escape


MAX_RESULTS = 10


class SettingsPanel(ModalScreen[None]):
    """Settings and diagnostics modal. Layer 1: always fullscreen."""

    BINDINGS = [
        ("escape", "dismiss_panel", "Close"),
    ]

    DEFAULT_CSS = """
    SettingsPanel {
        layout: vertical;
        align: center middle;
        background: transparent;
    }

    SettingsPanel #settings-container {
        width: 95%;
        height: 80%;
        background: $surface;
        border: tall $primary;
        padding: 1 2;
    }

    SettingsPanel #settings-title {
        text-align: center;
        text-style: bold;
        padding: 0 0 1 0;
    }

    SettingsPanel #settings-info {
        padding: 0 0 1 0;
    }

    SettingsPanel #settings-results {
        height: auto;
        max-height: 50%;
        padding: 0;
    }
    """

    def __init__(self, conn_info, workspace_info, results):
        """
        Args:
            conn_info: dict with host, port, conn_state.
            workspace_info: dict with active workspace details.
            results: list of result strings.
        """
        super().__init__()
        self._conn_info = conn_info
        self._workspace_info = workspace_info
        self._results = results

    def compose(self):
        with Vertical(id="settings-container"):
            yield Static("⚙  Settings & Diagnostics", id="settings-title")
            yield Static(self._render_info(), id="settings-info")
            yield Static(self._render_results(), id="settings-results")

    def _render_info(self):
        ci = self._conn_info
        wi = self._workspace_info

        conn_color = "green" if ci.get("state") == "connected" else "red"
        lines = [
            "[bold]Connection[/]",
            f"  Host     : {ci.get('host', '?')}:{ci.get('port', '?')}",
            f"  State    : [{conn_color}]{ci.get('state', '?')}[/]",
            "",
        ]

        if wi:
            state_color = "green" if wi.get("state") == "IDLE" else "yellow"
            lines += [
                "[bold]Active Workspace[/]",
                f"  ID       : {rich_escape(wi.get('workspace_id', '—'))}",
                f"  Path     : {rich_escape(wi.get('path', '—'))}",
                f"  State    : [{state_color}]{wi.get('state', '—')}[/]",
                f"  PID      : {wi.get('pid', '—')}",
            ]
        else:
            lines += [
                "[bold]Active Workspace[/]",
                "  [dim]No workspace selected[/]",
            ]

        return "\n".join(lines)

    def _render_results(self):
        lines = ["", "[bold]Recent Command Results[/]"]
        if self._results:
            for entry in self._results[-MAX_RESULTS:]:
                lines.append(f"  {entry}")
        else:
            lines.append("  [dim]No results yet[/]")
        return "\n".join(lines)

    def action_dismiss_panel(self):
        self.dismiss(None)

    def on_click(self, event):
        """Click outside the dialog → dismiss."""
        try:
            main_content = self.query_one("#settings-container")
            if event.screen_offset not in main_content.region:
                self.dismiss(None)
        except Exception:
            pass
