"""
Command Palette — Result display area.

Shows the last N command execution results with status icons.
"""

import time

from textual.reactive import reactive
from textual.widgets import Static
from rich.markup import escape as rich_escape


MAX_RESULTS = 5


class CommandPalette(Static):
    """Command result display panel."""

    engine_state = reactive("AWAIT_IDE")
    has_pending_edits = reactive(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._results = []

    def render(self):
        lines = ["[bold]📋  Command Results[/]\n"]

        if self._results:
            for entry in self._results[-MAX_RESULTS:]:
                lines.append(f"  {entry}")
        else:
            lines.append("  [dim]No results yet[/]")

        return "\n".join(lines)

    def add_result(self, cmd_type, result):
        """Add a command result to the display."""
        ts_str = time.strftime("%H:%M:%S")
        ok = result.get("ok", False) if isinstance(result, dict) else False
        error = result.get("error", "") if isinstance(result, dict) else ""

        entry = f"{'✅' if ok else '❌'} [dim]{ts_str}[/] [cyan]{cmd_type}[/]"
        if not ok and error:
            entry += f" [red]{rich_escape(error)}[/]"

        self._results.append(entry)
        if len(self._results) > MAX_RESULTS * 2:
            self._results = self._results[-MAX_RESULTS:]

        self.refresh()
