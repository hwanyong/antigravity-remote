"""
NavBar — bottom panel switcher for mobile-only layout.

Provides 3 buttons to switch between WorkspaceList, AgentPanel, and Explorer.
Posts NavBar.PanelSwitch message when a button is clicked.
Active panel is tracked via reactive `active` property.
"""

from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Button


class NavBar(Horizontal):
    """Bottom navigation bar for panel switching."""

    DEFAULT_CSS = """
    NavBar {
        dock: bottom;
        height: 3;
        background: $surface;
        padding: 0;
    }

    NavBar Button {
        width: 1fr;
        margin: 0;
        padding: 0;
        content-align: center middle;
    }

    NavBar Button:hover {
        background: $primary 30%;
    }
    """

    active = reactive("workspace")

    class PanelSwitch(Message):
        """Posted when user clicks a nav button."""
        def __init__(self, panel: str) -> None:
            self.panel = panel
            super().__init__()

    def compose(self):
        yield Button("^A Agent", id="nav-agent")
        yield Button("^E Files", id="nav-explorer")
        yield Button("^G Git", id="nav-git")
        yield Button("^W Workspaces", id="nav-workspace")
    def on_button_pressed(self, event: Button.Pressed):
        panel_map = {
            "nav-agent": "agent",
            "nav-explorer": "explorer",
            "nav-git": "git",
            "nav-workspace": "workspace",
        }
        panel = panel_map.get(event.button.id)
        if panel:
            self.post_message(self.PanelSwitch(panel))

    def watch_active(self, panel_name: str):
        """Update button visuals to highlight the active panel."""
        highlight_map = {
            "agent": "nav-agent",
            "explorer": "nav-explorer",
            "git": "nav-git",
            "workspace": "nav-workspace",
        }
        for name, btn_id in highlight_map.items():
            try:
                btn = self.query_one(f"#{btn_id}", Button)
                btn.variant = "primary" if name == panel_name else "default"
            except Exception:
                pass
