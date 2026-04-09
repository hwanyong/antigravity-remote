"""
agbridge_tui.workspace_manager — Client-side multi-workspace orchestrator

Manages a local cache of workspace data and handles workspace switching.
Uses Observer pattern to notify UI components when data changes.

Data-driven design: all panels receive data from this manager.
active_data returns dict | None — None represents the empty state.
"""

import logging
import time

logger = logging.getLogger("agbridge_tui.workspace_manager")


class WorkspaceManager:
    """Client-side workspace cache, routing, and switching."""

    def __init__(self, conn):
        """
        Args:
            conn: Connection instance for HTTP/WS communication.
        """
        self.conn = conn
        self.active_id = None               # None = no workspace selected
        self._cache = {}                     # workspace_id → snapshot dict
        self._workspaces = {}                # workspace_id → metadata dict
        self._observers = []                 # UI callback functions

    # ── Data-driven properties ───────────────────────────────

    @property
    def active_data(self):
        """
        Current workspace snapshot data.
        Returns None when no workspace is selected (empty state).
        """
        if not self.active_id:
            return None
        return self._cache.get(self.active_id)

    @property
    def active_metadata(self):
        """Current workspace metadata (path, state, pid, etc.)."""
        if not self.active_id:
            return None
        return self._workspaces.get(self.active_id)

    @property
    def workspace_list(self):
        """List of all known workspaces."""
        return list(self._workspaces.values())

    @property
    def is_empty(self):
        """True when no workspaces exist."""
        return len(self._workspaces) == 0

    # ── Observer pattern ─────────────────────────────────────

    def add_observer(self, callback):
        """
        Register a UI observer.

        Args:
            callback: async def on_workspace_event(event_type, data, ts, workspace_id)
        """
        self._observers.append(callback)

    async def _notify_observers(self, event_type, data, ts, workspace_id=None):
        """Notify all observers of a workspace event."""
        for callback in self._observers:
            try:
                await callback(event_type, data, ts, workspace_id)
            except Exception as e:
                logger.error("Observer notification error: %s", e)

    # ── WS event routing ────────────────────────────────────

    async def on_ws_event(self, event_type, data, ts, workspace_id):
        """
        Route incoming WS events to the correct cache slot and notify observers.
        Called by Connection.set_event_handler().
        """
        # System-level events (no workspace_id)
        if event_type == "SYS_WORKSPACE_REGISTERED":
            await self._on_workspace_added(data)
            await self._notify_observers(event_type, data, ts, workspace_id)
            return

        if event_type == "SYS_WORKSPACE_UNREGISTERED":
            await self._on_workspace_removed(data)
            await self._notify_observers(event_type, data, ts, workspace_id)
            return

        # Per-workspace events → update cache
        if workspace_id and workspace_id in self._cache:
            self._update_cache(workspace_id, event_type, data)

        # Notify observers for all events
        await self._notify_observers(event_type, data, ts, workspace_id)

    # ── Workspace lifecycle ──────────────────────────────────

    async def _on_workspace_added(self, data):
        """Handle SYS_WORKSPACE_REGISTERED event."""
        if not data:
            return

        ws_id = data.get("workspace_id")
        if not ws_id:
            return

        self._workspaces[ws_id] = {
            "workspace_id": ws_id,
            "path": data.get("path", ""),
            "pid": data.get("pid"),
            "state": "IDLE",
            "ide_connected": True,
        }

        # Initialize empty cache slot
        self._cache[ws_id] = {}

        # Auto-switch to first workspace, or newly opened workspace
        if self.active_id is None or len(self._workspaces) == 1:
            await self.switch(ws_id)

        logger.info("Workspace added: %s", ws_id)

    async def _on_workspace_removed(self, data):
        """Handle SYS_WORKSPACE_UNREGISTERED event."""
        if not data:
            return

        ws_id = data.get("workspace_id")
        if not ws_id:
            return

        self._workspaces.pop(ws_id, None)
        self._cache.pop(ws_id, None)

        # If the active workspace was removed, switch to another or empty
        if self.active_id == ws_id:
            if self._workspaces:
                next_id = next(iter(self._workspaces))
                await self.switch(next_id)
            else:
                self.active_id = None
                await self._notify_observers(
                    "WORKSPACE_SWITCHED", None, time.time(), None
                )

        logger.info("Workspace removed: %s", ws_id)

    # ── Operations ───────────────────────────────────────────

    async def switch(self, workspace_id):
        """
        Switch active workspace. Loads snapshot from cache or network.
        """
        if workspace_id not in self._workspaces:
            logger.warning("Cannot switch to unknown workspace: %s", workspace_id)
            return

        self.active_id = workspace_id

        # Load snapshot if cache is empty
        if not self._cache.get(workspace_id):
            try:
                snapshot = await self.conn.get_snapshot(workspace_id)
                self._cache[workspace_id] = snapshot
            except Exception as e:
                logger.error("Failed to load snapshot for %s: %s", workspace_id, e)

        await self._notify_observers(
            "WORKSPACE_SWITCHED", self.active_data, time.time(), workspace_id
        )
        logger.info("Switched to workspace: %s", workspace_id)

    async def open_workspace(self, path):
        """
        Launch a new IDE for the given path.
        ProcessScanner will auto-discover and trigger SYS_WORKSPACE_REGISTERED.
        """
        try:
            result = await self.conn.open_workspace(path)
            return result
        except Exception as e:
            logger.error("Failed to open workspace: %s", e)
            return {"ok": False, "error": str(e)}

    async def close_workspace(self, workspace_id):
        """Close IDE and remove workspace."""
        try:
            result = await self.conn.close_workspace(workspace_id)
            return result
        except Exception as e:
            logger.error("Failed to close workspace: %s", e)
            return {"ok": False, "error": str(e)}

    async def refresh_list(self):
        """Fetch workspace list from daemon and sync local state."""
        try:
            workspaces = await self.conn.get_workspaces()
            self._workspaces = {
                ws["workspace_id"]: ws for ws in workspaces
            }
            return workspaces
        except Exception as e:
            logger.error("Failed to refresh workspace list: %s", e)
            # Preserve existing cache — don't wipe on transient failure
            return list(self._workspaces.values())

    # ── Cache management ─────────────────────────────────────

    def _update_cache(self, workspace_id, event_type, data):
        """Update the local cache for a workspace based on event type."""
        cache = self._cache.get(workspace_id, {})

        if event_type == "UI_AGENT_UPDATE":
            cache["agent_panel"] = data
        elif event_type == "UI_EDIT_ACTIONS_UPDATE":
            cache["edit_actions"] = data
        elif event_type == "UI_ACTIVE_EDITOR_UPDATE":
            cache["active_editor"] = data
        elif event_type == "UI_MODELS_UPDATE":
            cache["models_info"] = data
        elif event_type == "GIT_STATUS_UPDATE":
            cache["git_status"] = data
        elif event_type in ("SYS_IDE_CONNECTED", "SYS_IDE_DISCONNECTED"):
            cache["ide_connected"] = event_type == "SYS_IDE_CONNECTED"

        # Update workspace metadata state
        ws_meta = self._workspaces.get(workspace_id, {})
        if event_type == "UI_AGENT_UPDATE" and data:
            state = data.get("state", "")
            if state == "generating":
                ws_meta["state"] = "ACTIVE"
            elif state == "idle":
                ws_meta["state"] = "IDLE"

        self._cache[workspace_id] = cache
