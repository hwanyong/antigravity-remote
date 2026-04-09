"""
Status Header — top bar reactive widget (multi-workspace).

Displays: connection state, active workspace, engine state, IDE PID, timestamp.
Shows empty state when no workspace is selected.
"""

from textual.reactive import reactive
from textual.widgets import Static


class StatusHeader(Static):
    """Reactive status bar at the top of the TUI."""

    conn_state = reactive("disconnected")
    engine_state = reactive("")
    ide_pid = reactive(0)
    ws_count = reactive(0)
    ws_max = reactive(3)
    last_event_ts = reactive("")
    active_workspace = reactive("")

    def render(self):
        # Connection indicator
        indicators = {
            "connected": ("●", "green"),
            "disconnected": ("●", "red"),
            "connecting": ("◌", "yellow"),
            "reconnecting": ("◌", "yellow"),
        }
        symbol, color = indicators.get(self.conn_state, ("?", "white"))

        # Workspace display
        if self.active_workspace:
            ws_str = f"[bold]{self.active_workspace}[/]"
        else:
            ws_str = "[dim]No workspace[/]"

        # Engine state (may be empty when no workspace)
        engine_str = self.engine_state if self.engine_state else ""

        pid_str = str(self.ide_pid) if self.ide_pid else ""
        pid_display = f"PID:{pid_str}  " if pid_str else ""

        return (
            f"  agbridge TUI v0.3.0   "
            f"[{color}]{symbol}[/] {self.conn_state.upper()}  "
            f"{ws_str}  "
            f"{engine_str}  "
            f"{pid_display}"
            f"{self.last_event_ts}"
        )

    def update_from_status(self, status_data):
        """Update from /api/workspaces/{id}/status response."""
        self.engine_state = status_data.get("state", "")
        self.ide_pid = status_data.get("pid", 0) or 0
        self.ws_count = status_data.get("ws_clients", 0)
        ws_id = status_data.get("workspace_id", "")
        if ws_id:
            self.active_workspace = ws_id
