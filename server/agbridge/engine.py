"""
agbridge.engine — Per-workspace lifecycle engine

In the multi-workspace model, each Engine is bound to one workspace and
one IDE process. It drives the IDLE ↔ ACTIVE state machine only.
Discovery and lifecycle management are handled by WorkspaceSupervisor.

The Engine is created when the Supervisor's reconcile() discovers an IDE
window and destroyed when the window is no longer visible in CG.

WS broadcasting is delegated to WorkspaceSupervisor — events include
workspace_id so clients can route them.
"""

import asyncio
import logging
import os

from agbridge.config import (
    POLL_ACTIVE_INTERVAL,
    POLL_IDLE_INTERVAL,
    CACHE_DIR_NAME,
    CACHE_FILE_NAME,
    AX_MAX_CONSECUTIVE_FAILURES,
)
from agbridge.state_store import StateStore
from agbridge.ide_monitor import IDEMonitor
from agbridge.collectors import FSWatcher, scan_tree
from agbridge.collectors.git_tracker import get_all_worktree_status
from agbridge.collectors.ax_scraper import (
    collect_agent_panel,
    collect_edit_actions,
    collect_models_and_modes,
    detect_confirm_undo_dialog,
    get_active_editor_info,
    get_conversation_state,
)
from agbridge import protocol

logger = logging.getLogger("agbridge.engine")


class Engine:
    """Per-workspace lifecycle engine. Exists only while IDE is running."""

    # State constants (AWAIT_IDE removed — handled by Supervisor)
    IDLE = "IDLE"
    ACTIVE = "ACTIVE"

    def __init__(self, workspace_id, workspace_root, pid, target_title=None):
        """
        Args:
            workspace_id: Unique identifier for this workspace.
            workspace_root: Absolute path to the workspace directory.
            pid: PID of the bound Antigravity IDE process.
            target_title: Workspace basename for AX window title matching.
        """
        self.workspace_id = workspace_id
        self.workspace_root = os.path.realpath(workspace_root)
        self.window_id = None     # CG window ID (set by Supervisor)
        self._state = self.IDLE
        self._event_queue = asyncio.Queue()
        self._ax_fail_count = 0
        self._running = False
        self._broadcast_callback = None  # Set by WorkspaceSupervisor

        # Core components
        cache_path = os.path.join(
            self.workspace_root, CACHE_DIR_NAME, CACHE_FILE_NAME
        )
        self.store = StateStore(cache_path=cache_path)
        self.ide = IDEMonitor(pid, target_title=target_title)
        self._fs_watcher = None

        # Per-workspace polling controller
        from agbridge.collectors.ax_polling import PollController
        self.poll_controller = PollController()

    @property
    def current_state(self):
        return self._state

    def set_broadcast_callback(self, callback):
        """
        Set the broadcast function.

        Args:
            callback: async def callback(workspace_id, event_type, payload)
        """
        self._broadcast_callback = callback

    # ── Broadcasting ─────────────────────────────────────────

    async def _broadcast(self, event_type, payload=None):
        """Propagate an event via the registry's broadcast system."""
        if self._broadcast_callback:
            await self._broadcast_callback(
                self.workspace_id, event_type, payload
            )

    # ── Event queue ──────────────────────────────────────────

    def push_event(self, event_type, payload=None):
        """Enqueue an event from a synchronous context."""
        try:
            self._event_queue.put_nowait((event_type, payload))
        except asyncio.QueueFull:
            pass

    async def _drain_events(self):
        """Broadcast all queued events at once."""
        while not self._event_queue.empty():
            event_type, payload = self._event_queue.get_nowait()
            await self._broadcast(event_type, payload)

    # ── FS event callback ────────────────────────────────────

    def _on_fs_batch(self, events):
        """Callback invoked after watchdog debouncing delivers a batch."""
        # Update FS tree
        tree = scan_tree(self.workspace_root)
        changed = self.store.update("fs_tree", tree)
        if changed:
            for ev in events:
                ev_type = {
                    "created": protocol.FS_OP_CREATED,
                    "deleted": protocol.FS_OP_DELETED,
                    "modified": protocol.FS_OP_MODIFIED,
                }.get(ev["event"], protocol.FS_OP_MODIFIED)
                self.push_event(ev_type, {"path": ev["path"]})

        # Update Git status (supports bare repo + worktree layout)
        git_data = get_all_worktree_status(self.workspace_root)
        git_changed = self.store.update("git_status", git_data)
        if git_changed:
            self.push_event(protocol.GIT_STATUS_UPDATE, git_data)

        # FS changes → wake up AX scraper
        if self._state == self.IDLE:
            self._state = self.ACTIVE
            logger.info("[%s] FS change detected → ACTIVE", self.workspace_id)

    # ── Lifecycle loop ───────────────────────────────────────

    async def run(self):
        """Main event loop. Launch via asyncio.create_task()."""
        self._running = True

        # Enable polling for this engine cycle
        self.poll_controller.reset()

        logger.info(
            "[%s] Engine started: path=%s pid=%d",
            self.workspace_id, self.workspace_root, self.ide.pid,
        )

        # FS Watcher — always active
        self._start_fs_watcher()

        # Build initial FS tree
        tree = scan_tree(self.workspace_root)
        self.store.update("fs_tree", tree)

        # Initial Git status (supports bare repo + worktree layout)
        git_data = get_all_worktree_status(self.workspace_root)
        self.store.update("git_status", git_data)

        # IDE is already connected (ProcessScanner confirmed it)
        self.store.set_ide_connected(True)
        self._do_full_ax_scrape()
        self.store.flush_to_disk()

        # Main loop
        while self._running:
            await self._drain_events()

            if self._state == self.IDLE:
                await self._loop_idle()
            elif self._state == self.ACTIVE:
                await self._loop_active()

    async def _loop_idle(self):
        """SlowPoll: parse AX UI every POLL_IDLE_INTERVAL seconds."""
        self._do_ax_poll()
        self.store.flush_to_disk()
        await asyncio.sleep(POLL_IDLE_INTERVAL)

    async def _loop_active(self):
        """FastPoll: parse AX UI every POLL_ACTIVE_INTERVAL seconds."""
        self._do_ax_poll()

        # Detect ACTIVE → IDLE transition: Send button has returned
        if self.ide.windows:
            conv_state = get_conversation_state(self.ide.windows[0])
            if conv_state == "idle":
                self._do_ax_poll()
                self._state = self.IDLE
                logger.info("[%s] AI generation complete → IDLE", self.workspace_id)
                self.store.flush_to_disk()
                return

        await asyncio.sleep(POLL_ACTIVE_INTERVAL)

    # ── AX collection utilities ──────────────────────────────

    def _do_full_ax_scrape(self):
        """Build the initial full AX snapshot."""
        if not self.ide.windows:
            self.ide.refresh_windows()
            if not self.ide.windows:
                return

        win = self.ide.windows[0]

        try:
            agent_data = collect_agent_panel(win)
            self.store.update("agent_panel", agent_data)

            edit_actions = collect_edit_actions(win)
            self.store.update("edit_actions", edit_actions)

            editor_info = get_active_editor_info(win)
            self.store.update("active_editor", editor_info)

            self._ax_fail_count = 0
        except Exception as e:
            logger.warning("[%s] Full AX scrape failed: %s", self.workspace_id, e)
            self._handle_ax_failure()

    def _do_ax_poll(self):
        """Periodic AX parse — enqueue only changed sections."""
        if not self.ide.windows:
            self.ide.refresh_windows()
            if not self.ide.windows:
                return

        win = self.ide.windows[0]

        try:
            agent_data = collect_agent_panel(win)
            if self.store.update("agent_panel", agent_data):
                self.push_event(protocol.UI_AGENT_UPDATE, agent_data)

                if agent_data["state"] == "generating" and self._state == self.IDLE:
                    self._state = self.ACTIVE
                    logger.info("[%s] Agent generating → ACTIVE", self.workspace_id)

            edit_actions = collect_edit_actions(win)
            if self.store.update("edit_actions", edit_actions):
                self.push_event(
                    protocol.UI_EDIT_ACTIONS_UPDATE, edit_actions
                )

            editor_info = get_active_editor_info(win)
            if self.store.update("active_editor", editor_info):
                self.push_event(
                    protocol.UI_ACTIVE_EDITOR_UPDATE, editor_info
                )

            # Model/mode current values — read-only (no popup interaction)
            if self._state == self.IDLE:
                current_info = collect_models_and_modes(win)
                # Merge: preserve cached available_* lists
                existing = self.store.get("models_info") or {}
                merged = {
                    "current_model": current_info.get("current_model", ""),
                    "current_mode": current_info.get("current_mode", ""),
                    "available_models": existing.get("available_models", []),
                    "available_modes": existing.get("available_modes", []),
                }
                if self.store.update("models_info", merged):
                    self.push_event(
                        protocol.UI_MODELS_UPDATE, merged
                    )

            # Confirm Undo dialog — detect modal overlay
            undo_dialog = detect_confirm_undo_dialog(win)
            if self.store.update("confirm_undo_dialog", undo_dialog):
                self.push_event(
                    protocol.UI_CONFIRM_UNDO_DIALOG, undo_dialog
                )

            self._ax_fail_count = 0

        except Exception as e:
            logger.warning("[%s] AX poll failed: %s", self.workspace_id, e)
            self._handle_ax_failure()

    def _handle_ax_failure(self):
        """
        Handle AX polling failure — refresh windows and reset counter.

        Engine never self-terminates. If the IDE process is truly gone,
        the Supervisor's reconcile() will detect the missing CG window
        and stop this Engine externally.
        """
        self._ax_fail_count += 1
        logger.warning(
            "[%s] AX failure count: %d/%d",
            self.workspace_id, self._ax_fail_count, AX_MAX_CONSECUTIVE_FAILURES,
        )

        self.ide.refresh_windows()

        if self._ax_fail_count >= AX_MAX_CONSECUTIVE_FAILURES:
            logger.warning(
                "[%s] AX threshold reached — refreshing windows, continuing",
                self.workspace_id,
            )
            self._ax_fail_count = 0

    def _start_fs_watcher(self):
        """Start watchdog monitoring."""
        self._fs_watcher = FSWatcher(
            self.workspace_root, self._on_fs_batch
        )
        self._fs_watcher.start()
        logger.info("[%s] FS Watcher started", self.workspace_id)

    # ── Shutdown ─────────────────────────────────────────────

    def stop(self):
        """Graceful shutdown: stop loop, stop FS watcher, abort polls."""
        self._running = False

        # Abort all active poll_until() operations for this workspace
        self.poll_controller.shutdown()

        if self._fs_watcher:
            self._fs_watcher.stop()
            self._fs_watcher = None

        self.store.flush_to_disk()
        logger.info("[%s] Engine stopped", self.workspace_id)
