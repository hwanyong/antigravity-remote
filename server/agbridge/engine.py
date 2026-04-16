"""
agbridge.engine — Per-workspace lifecycle engine (Refactored)

Orchestrator only — owns a WorkspaceContext and delegates:
  - State management → WorkspaceStateMachine
  - Turn cache → ConversationCache
  - CDP connection → cdp.bridge.CDPBridge
  - Editor control → EditorGateway

Data Collection (Cache Architecture):
  The server acts as an independent data collector. A background task
  incrementally scrolls through the IDE conversation and accumulates
  turns into a local cache. The TUI reads from this cache — it never
  triggers IDE scrolling. MutationObserver handles real-time updates
  for the current viewport (e.g. during AI generation).
"""

import asyncio
import logging
import os
import time

from agbridge.config import (
    CACHE_DIR_NAME,
    CACHE_FILE_NAME,
)
from agbridge.state_store import StateStore
from agbridge.ide_monitor import IDEMonitor
from agbridge.collectors import FSWatcher, scan_tree
from agbridge.collectors.git_tracker import get_all_worktree_status
from agbridge.collectors.dom_watcher import DOMWatcher, BINDING_NAME
from agbridge.workspace.state_machine import WorkspaceStateMachine
from agbridge.workspace.conversation_cache import ConversationCache
from agbridge.workspace.context import WorkspaceContext
from agbridge.editor.gateway import EditorGateway
from agbridge import protocol

logger = logging.getLogger("agbridge.engine")


class Engine:
    """Per-workspace lifecycle engine. Exists only while IDE is running.

    After refactoring: Owns a WorkspaceContext that holds all unified state.
    Engine itself is a thin orchestrator (~200 lines).
    """

    def __init__(self, workspace_id, workspace_root, pid, target_title=None, cdp_port=None):
        """
        Args:
            workspace_id: Unique identifier for this workspace.
            workspace_root: Absolute path to the workspace directory.
            pid: PID of the bound Antigravity IDE process.
            target_title: Workspace basename for window title matching.
            cdp_port: CDP debugging port for this workspace (dynamic).
        """
        self.workspace_id = workspace_id
        self.workspace_root = os.path.realpath(workspace_root)
        self._event_queue = asyncio.Queue()
        self._running = False
        self._broadcast_callback = None

        # Core state objects
        cache_path = os.path.join(
            self.workspace_root, CACHE_DIR_NAME, CACHE_FILE_NAME
        )
        store = StateStore(cache_path=cache_path)
        ide = IDEMonitor(pid, target_title=target_title)

        state_machine = WorkspaceStateMachine()
        conversation = ConversationCache(
            workspace_id,
            os.path.join(self.workspace_root, CACHE_DIR_NAME),
        )

        # WorkspaceContext — unified state object
        self.ctx = WorkspaceContext(
            workspace_id=workspace_id,
            workspace_root=self.workspace_root,
            state_machine=state_machine,
            store=store,
            conversation=conversation,
            cdp=None,  # Set in _init_cdp
            ide=ide,
        )
        self.ctx.set_push_event(self.push_event)

        # Convenience aliases (used by supervisor/api/input_queue during migration)
        self.store = store
        self.ide = ide
        self.cdp = None  # Set in _init_cdp

        self._cdp_port = cdp_port
        self._dom_watcher = DOMWatcher()
        self._fs_watcher = None
        self._collector_task = None
        self._collecting = False
        self._last_agent_scrape = 0.0
        self._is_tui_scanning = False

    @property
    def current_state(self):
        return self.ctx.state_machine.current

    @property
    def cdp_port(self):
        return self._cdp_port

    def _set_state(self, event):
        """Apply a state transition via the state machine."""
        self.ctx.state_machine.transition(event)

    def set_broadcast_callback(self, callback):
        self._broadcast_callback = callback

    # ── Broadcasting ─────────────────────────────────────────

    async def _broadcast(self, event_type, payload=None):
        if self._broadcast_callback:
            await self._broadcast_callback(
                self.workspace_id, event_type, payload
            )

    # ── Event queue ──────────────────────────────────────────

    def push_event(self, event_type, payload=None):
        try:
            self._event_queue.put_nowait((event_type, payload))
        except asyncio.QueueFull:
            pass

    async def _drain_events(self):
        while not self._event_queue.empty():
            event_type, payload = self._event_queue.get_nowait()
            await self._broadcast(event_type, payload)

    # ── FS event callback ────────────────────────────────────

    def _on_fs_batch(self, events):
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

        git_data = get_all_worktree_status(self.workspace_root)
        git_changed = self.store.update("git_status", git_data)
        if git_changed:
            self.push_event(protocol.GIT_STATUS_UPDATE, git_data)

    # ── Lifecycle loop ───────────────────────────────────────

    async def run(self):
        """Main event loop. Launch via asyncio.create_task()."""
        self._running = True

        logger.info(
            "[%s] Engine started: path=%s pid=%d",
            self.workspace_id, self.workspace_root, self.ide.pid,
        )

        # FS Watcher
        self._start_fs_watcher()

        tree = scan_tree(self.workspace_root)
        self.store.update("fs_tree", tree)

        git_data = get_all_worktree_status(self.workspace_root)
        self.store.update("git_status", git_data)

        self.store.set_ide_connected(True)

        # Load turn cache from disk (survives restarts)
        self.ctx.conversation.load()

        # Initialize CDP bridge + DOM watcher
        await self._init_cdp()

        # Initialize EditorGateway (requires CDP bridge)
        editor = EditorGateway(self.ctx)
        self.ctx.set_editor(editor)

        # Initial viewport scrape
        await self._do_cdp_poll()
        self.store.flush_to_disk()

        # Start background collector
        self._collector_task = asyncio.create_task(
            self._background_collector()
        )

        # Main loop: drain event queue
        while self._running:
            await self._drain_events()
            await asyncio.sleep(0.05)

    async def _init_cdp(self):
        """Initialize CDP bridge with dynamic port and event handler."""
        from agbridge.cdp.bridge import CDPBridge

        port = self._cdp_port
        if port is None:
            from agbridge.config import CDP_DIRECT_PORT
            port = CDP_DIRECT_PORT

        bridge = CDPBridge(
            self.ide.pid,
            os.path.basename(self.workspace_root),
            port=port,
        )

        # Register event handler BEFORE connect
        bridge.set_event_handler(self._on_cdp_event)

        try:
            await bridge.connect()
            logger.info(
                "[%s] CDP bridge connected (mode=%s port=%d)",
                self.workspace_id, bridge.mode, port,
            )
            self.cdp = bridge
            self.ctx.cdp = bridge

            # Install DOM watcher + runtime_bootstrap.js
            await self._dom_watcher.install(bridge, self.workspace_id)

        except Exception as e:
            logger.warning(
                "[%s] Initial CDP connection delayed (waiting for frontend): %s",
                self.workspace_id, e,
            )
            # Retain self.cdp so _background_collector can self-heal

    # ── CDP event handling ────────────────────────────────────

    async def _on_cdp_event(self, method, params):
        if method == "Runtime.bindingCalled":
            name = params.get("name", "")
            if name == BINDING_NAME:
                event_data = DOMWatcher.parse_event(
                    params.get("payload", "")
                )
                if event_data:
                    await self._on_dom_change(event_data)

        elif method == "Runtime.executionContextCreated":
            if self.cdp and self._dom_watcher.is_installed:
                logger.info(
                    "[%s] Execution context created — reinstalling watcher",
                    self.workspace_id,
                )
                await self._dom_watcher.reinstall(self.cdp, self.workspace_id)

    async def _on_dom_change(self, event_data):
        """Real-time update triggered by MutationObserver.

        During ACTIVE (generating) state, agent section scrapes are
        throttled to 500ms intervals to reduce unnecessary CDP calls.
        """
        if not self.cdp or not self.cdp.is_connected:
            return

        section = event_data.get("section")
        sm = self.ctx.state_machine

        # Fast-path: state change from button observer
        if section == "state":
            new_state = event_data.get("status", "idle")
            if new_state == "generating":
                result = sm.transition("gen_detected")
                if result:
                    self.push_event(protocol.UI_CONV_STATE_CHANGE, {"state": "generating"})
                    logger.info("[%s] Agent generating → ACTIVE", self.workspace_id)
            elif new_state == "idle":
                result = sm.transition("idle_detected")
                if result:
                    self.push_event(protocol.UI_CONV_STATE_CHANGE, {"state": "idle"})
                    logger.info("[%s] AI generation complete → IDLE", self.workspace_id)
                    self.store.flush_to_disk()
            return

        if self._collecting:
            return

        # Generating throttle
        if section == "agent" and sm.is_active():
            now = time.monotonic()
            if now - self._last_agent_scrape < 0.5:
                return
            self._last_agent_scrape = now

        from agbridge.collectors import dom_scraper

        try:
            if section == "agent":
                agent_data = await dom_scraper.collect_agent_panel(self.cdp)
                agent_data = self.ctx.conversation.merge(agent_data)
                self._push_cache_to_tui(agent_data)

            elif section == "controls":
                edit_actions = await dom_scraper.collect_edit_actions(self.cdp)
                if self.store.update("edit_actions", edit_actions):
                    self.push_event(
                        protocol.UI_EDIT_ACTIONS_UPDATE, edit_actions
                    )
                current_info = await dom_scraper.collect_models_and_modes(
                    self.cdp
                )
                existing = self.store.get("models_info") or {}
                merged = {
                    "current_model": current_info.get("current_model", ""),
                    "current_mode": current_info.get("current_mode", ""),
                    "available_models": existing.get("available_models", []),
                    "available_modes": existing.get("available_modes", []),
                }
                if self.store.update("models_info", merged):
                    self.push_event(protocol.UI_MODELS_UPDATE, merged)

            elif section == "editor":
                editor_info = await dom_scraper.get_active_editor_info(
                    self.cdp
                )
                if self.store.update("active_editor", editor_info):
                    self.push_event(
                        protocol.UI_ACTIVE_EDITOR_UPDATE, editor_info
                    )

            elif section == "dialog":
                undo_dialog = await dom_scraper.detect_confirm_undo_dialog(
                    self.cdp
                )
                if self.store.update("confirm_undo_dialog", undo_dialog):
                    self.push_event(
                        protocol.UI_CONFIRM_UNDO_DIALOG, undo_dialog
                    )

        except Exception as e:
            logger.warning(
                "[%s] DOM change handler failed (section=%s): %s",
                self.workspace_id, section, e,
            )

        await self._drain_events()

    # ── Background Collector ──────────────────────────────────

    async def _background_collector(self):
        """Incrementally collect uncached turns in the background."""
        STEP_DELAY = 0.3
        SWEEP_DELAY = 3.0
        SETTLE_MS = 200

        from agbridge.collectors import dom_scraper

        while self._running:
            if not self.cdp or not self.cdp.is_connected:
                if self.cdp:
                    try:
                        logger.info("[%s] Attempting CDP self-healing / reconnect...", self.workspace_id)
                        await self.cdp.reconnect()
                        await self._dom_watcher.reinstall(self.cdp, self.workspace_id)
                        logger.info("[%s] CDP connection restored! Triggering deferred scrape.", self.workspace_id)
                        await self._do_cdp_poll()
                    except Exception as e:
                        logger.debug("[%s] Background reconnect still waiting: %s", self.workspace_id, e)
                await asyncio.sleep(2)
                continue

            try:
                height_map = await dom_scraper.get_conversation_height_map(
                    self.cdp,
                )
                if not height_map or height_map == "__EMPTY_PLACEHOLDER__":
                    sm = self.ctx.state_machine
                    
                    if height_map == "__EMPTY_PLACEHOLDER__" and self.ctx.conversation.turn_count > 0:
                        logger.info("[%s] Definitive empty placeholder detected — clearing cache.", self.workspace_id)
                        self.clear_cache()
                        # Transition to IDLE if we were in another active state
                        if not sm.is_idle():
                            sm.transition("idle_detected")

                    if sm.is_initializing():
                        sm.transition("empty_conversation")
                        logger.info(
                            "[%s] No conversation turns — INITIALIZING → IDLE",
                            self.workspace_id,
                        )
                    if self._is_tui_scanning:
                        self._is_tui_scanning = False
                        self.push_event(
                            protocol.UI_CONV_SCAN_STATE,
                            {"scanning": False},
                        )
                    await asyncio.sleep(SWEEP_DELAY)
                    continue

                total_turns = len(height_map)
                turn_cache = self.ctx.conversation

                needs_scan = any(
                    ti not in turn_cache._turns for ti in range(total_turns)
                )
                if needs_scan and not self._is_tui_scanning:
                    self._is_tui_scanning = True
                    self.push_event(
                        protocol.UI_CONV_SCAN_STATE,
                        {"scanning": True, "title": ""},
                    )

                collected_any = False

                for ti in range(total_turns):
                    if not self._running:
                        break
                    if ti in turn_cache._turns:
                        continue

                    self._collecting = True
                    scroll_pos = height_map[ti]["scrollStart"]
                    await dom_scraper.scroll_conversation_to(
                        self.cdp, scroll_pos,
                    )
                    await asyncio.sleep(SETTLE_MS / 1000)

                    data = await dom_scraper.collect_agent_panel(self.cdp)
                    self._collecting = False

                    data = turn_cache.merge(data)
                    self._push_cache_to_tui(data)
                    collected_any = True

                    await asyncio.sleep(STEP_DELAY)

                if collected_any and height_map:
                    self._collecting = True
                    total_height = sum(h["height"] for h in height_map)
                    await dom_scraper.scroll_conversation_to(
                        self.cdp, total_height,
                    )
                    self._collecting = False
                    self.store.flush_to_disk()
                    logger.info(
                        "[%s] Background collector: %d/%d turns cached",
                        self.workspace_id,
                        turn_cache.turn_count, total_turns,
                    )

                if self._is_tui_scanning:
                    self._is_tui_scanning = False
                    self.push_event(
                        protocol.UI_CONV_SCAN_STATE,
                        {"scanning": False},
                    )

            except Exception as e:
                self._collecting = False
                if self._is_tui_scanning:
                    self._is_tui_scanning = False
                    self.push_event(
                        protocol.UI_CONV_SCAN_STATE,
                        {"scanning": False},
                    )
                logger.warning(
                    "[%s] Background collector error: %s",
                    self.workspace_id, e,
                )

            await asyncio.sleep(SWEEP_DELAY)

    # ── CDP poll (viewport scrape) ────────────────────────────

    async def _do_cdp_poll(self):
        """Quick viewport scrape — used for initial load only."""
        if not self.cdp or not self.cdp.is_connected:
            if self.cdp:
                try:
                    await self.cdp.reconnect()
                    await self._dom_watcher.reinstall(self.cdp, self.workspace_id)
                except ConnectionError:
                    pass
            return

        from agbridge.collectors import dom_scraper

        try:
            agent_data = await dom_scraper.collect_agent_panel(self.cdp)
            agent_data = self.ctx.conversation.merge(agent_data)
            self._push_cache_to_tui(agent_data)

            # Notify TUI that scanning starts
            self._is_tui_scanning = True
            self.push_event(
                protocol.UI_CONV_SCAN_STATE,
                {"scanning": True, "title": ""},
            )

            # Transition out of INITIALIZING
            sm = self.ctx.state_machine
            scraped_state = agent_data.get("state", "unknown")
            if scraped_state == "generating":
                sm.transition("gen_detected")
                self.push_event(protocol.UI_CONV_STATE_CHANGE, {"state": "generating"})
                logger.info("[%s] Agent generating → ACTIVE", self.workspace_id)
            elif sm.is_initializing() and scraped_state != "unknown":
                sm.transition("idle_detected")
                logger.info("[%s] Initial scrape done (state=%s) → IDLE", self.workspace_id, scraped_state)

            edit_actions = await dom_scraper.collect_edit_actions(self.cdp)
            if self.store.update("edit_actions", edit_actions):
                self.push_event(
                    protocol.UI_EDIT_ACTIONS_UPDATE, edit_actions
                )

            editor_info = await dom_scraper.get_active_editor_info(self.cdp)
            if self.store.update("active_editor", editor_info):
                self.push_event(
                    protocol.UI_ACTIVE_EDITOR_UPDATE, editor_info
                )

            current_info = await dom_scraper.collect_models_and_modes(self.cdp)
            existing = self.store.get("models_info") or {}
            merged = {
                "current_model": current_info.get("current_model", ""),
                "current_mode": current_info.get("current_mode", ""),
                "available_models": existing.get("available_models", []),
                "available_modes": existing.get("available_modes", []),
            }
            if self.store.update("models_info", merged):
                self.push_event(protocol.UI_MODELS_UPDATE, merged)

            undo_dialog = await dom_scraper.detect_confirm_undo_dialog(self.cdp)
            if self.store.update("confirm_undo_dialog", undo_dialog):
                self.push_event(
                    protocol.UI_CONFIRM_UNDO_DIALOG, undo_dialog
                )

        except Exception as e:
            logger.warning("[%s] CDP poll failed: %s", self.workspace_id, e)

    # ── TUI push helpers ──────────────────────────────────────

    def _push_cache_to_tui(self, agent_data):
        """Flatten turn cache and push to TUI if data changed."""
        flat = self.ctx.conversation.flatten()
        agent_data["messages"] = flat
        agent_data["_total_turns"] = agent_data.get("_total_turns", 0)
        agent_data["_cached_turns"] = self.ctx.conversation.turn_count

        if self.store.update("agent_panel", agent_data):
            self.push_event(protocol.UI_AGENT_UPDATE, agent_data)

    def clear_cache(self):
        """Clear turn cache and restart background collection."""
        self.ctx.conversation.clear()
        logger.info("[%s] Cache cleared by user request", self.workspace_id)

        self._is_tui_scanning = True
        self.push_event(
            protocol.UI_CONV_SCAN_STATE,
            {"scanning": True, "title": ""},
        )
        self.push_event(
            protocol.UI_AGENT_UPDATE,
            {"messages": [], "state": "unknown", "_total_turns": 0, "_cached_turns": 0},
        )

    def truncate_turn_cache(self, turn_idx):
        """Truncate the turn cache from the given turn index onwards."""
        agent_data = self.ctx.conversation.truncate(turn_idx)
        self._push_cache_to_tui(agent_data)
        return agent_data

    # ── Backward compatibility ────────────────────────────────

    async def wait_for_idle(self, timeout=15.0):
        """Wait until state is IDLE or ACTIVE."""
        return await self.ctx.state_machine.wait_for_idle(timeout)

    # ── FS watcher ────────────────────────────────────────────

    def _start_fs_watcher(self):
        self._fs_watcher = FSWatcher(
            self.workspace_root, self._on_fs_batch
        )
        self._fs_watcher.start()
        logger.info("[%s] FS Watcher started", self.workspace_id)

    # ── Shutdown ─────────────────────────────────────────────

    def stop(self):
        """Graceful shutdown: stop loop, stop FS watcher, disconnect CDP."""
        self._running = False

        if self._collector_task and not self._collector_task.done():
            self._collector_task.cancel()
        self._collector_task = None

        if self.cdp:
            asyncio.ensure_future(self.cdp.disconnect())

        if self._fs_watcher:
            self._fs_watcher.stop()
            self._fs_watcher = None

        self.store.flush_to_disk()
        logger.info("[%s] Engine stopped", self.workspace_id)
