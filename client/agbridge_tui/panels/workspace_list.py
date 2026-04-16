"""
Workspace List — persistent sidebar panel showing all registered workspaces.

Displays each workspace with active indicator, state color, and path.
Click or Enter to switch the active workspace.
Data-driven: apply_data(workspaces, active_id) updates the entire list.
"""

import os

from textual.binding import Binding
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static, ListView, ListItem, Label, Button


class WorkspaceListView(ListView):
    """ListView subclass that owns the delete keybinding (ListView is focusable)."""

    BINDINGS = [
        Binding("delete", "close_selected", "Close", show=False),
    ]

    def action_close_selected(self):
        """Key binding action: close the highlighted workspace."""
        item = self.highlighted_child
        if isinstance(item, WorkspaceItem):
            self.post_message(WorkspaceList.WorkspaceCloseRequest(item.ws_id))


class WorkspaceItem(ListItem):
    """A row in the workspace list."""

    def __init__(self, ws_id, basename, is_active, window_state, **kwargs):
        super().__init__(**kwargs)
        self.ws_id = ws_id
        self.basename = basename
        self.is_active = is_active
        self.is_active = is_active
        self.window_state = window_state

    def compose(self):
        indicator = "●" if self.is_active else "○"
        indicator_style = "[green bold]" if self.is_active else "[dim]"

        state_colors = {
            "ACTIVE": "[green]",
            "OPEN": "[cyan]",
            "MINIMIZED": "[dim]",
            "CLOSED": "[red dim]",
            "PENDING": "[yellow]",
        }
        state_style = state_colors.get(self.window_state, "[dim]")

        # Prepare rich text
        name_part = f"[bold]{self.basename}[/]" if self.is_active else self.basename
        left_text = f"{indicator_style} {indicator} [/]{name_part}"
        right_text = f"{state_style}{self.window_state}[/]"

        yield Label(left_text, classes="ws-name")
        yield Label(right_text, classes="ws-state")
        yield Button("✕", classes="ws-close-btn")

    def on_button_pressed(self, event: Button.Pressed):
        """Intercept button press and ask WorkspaceList to handle it."""
        event.stop()
        self.post_message(WorkspaceList.WorkspaceCloseRequest(self.ws_id))


class OpenActionItem(ListItem):
    """The bottom item to open a new workspace."""
    
    def compose(self):
        yield Label(" + Open Workspace...", classes="ws-open-label")


class WorkspaceList(Static):
    """Permanent workspace list panel in the left column."""

    _active_id = reactive("")

    class WorkspaceCloseRequest(Message):
        """Fired when a user requests to close a workspace."""
        def __init__(self, workspace_id: str) -> None:
            self.workspace_id = workspace_id
            super().__init__()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._workspaces = []
        self._switch_callback = None
        self.border_title = "Workspaces"

    def compose(self):
        yield Static("[bold]🖥 Workspaces[/]", id="ws-list-title")
        yield WorkspaceListView(id="ws-list-view")

    def on_mount(self):
        self._rebuild()

    def set_switch_callback(self, callback):
        """
        Set callback for workspace switching.

        Args:
            callback: async def on_switch(workspace_id: str)
        """
        self._switch_callback = callback

    def apply_data(self, workspaces, active_id=None):
        """
        Update the workspace list display.

        Args:
            workspaces: list of workspace metadata dicts, or empty list.
            active_id: currently active workspace_id (or None).
        """
        self._workspaces = workspaces or []
        self._active_id = active_id or ""
        self._rebuild()

    def _rebuild(self):
        """Rebuild the ListView from current data."""
        from textual.css.query import NoMatches

        try:
            lv = self.query_one("#ws-list-view", WorkspaceListView)
        except NoMatches:
            return

        lv.clear()

        items = []
        if not self._workspaces:
            items.append(ListItem(Label(" No open workspaces", classes="ws-empty"), disabled=True))

        for ws in self._workspaces:
            ws_id = ws.get("workspace_id", "?")
            path = ws.get("path", "")
            window_state = ws.get("window_state", "OPEN")
            is_active = ws_id == self._active_id
            basename = os.path.basename(path) if path else ws_id

            items.append(WorkspaceItem(ws_id, basename, is_active, window_state))

        items.append(OpenActionItem())

        lv.extend(items)

    def on_list_view_selected(self, event: ListView.Selected):
        """Handle workspace selection or open action."""
        item = event.item
        app = self.app

        # Early return guards
        if not item or not app:
            return

        # Open workspace action
        if isinstance(item, OpenActionItem):
            app.run_worker(app.action_cmd_open_workspace())
            return

        # Workspace switch
        if isinstance(item, WorkspaceItem):
            ws_id = item.ws_id
            if ws_id == self._active_id:
                return

            if self._switch_callback:
                app.run_worker(self._switch_callback(ws_id))


