"""
agbridge.engine — Per-workspace lifecycle engine (Cache Architecture)

In the multi-workspace model, each Engine is bound to one workspace and
one IDE process. It drives the IDLE ↔ ACTIVE state machine.
Discovery and lifecycle management are handled by WorkspaceSupervisor.

Data Collection (Cache Architecture):
  The server acts as an independent data collector. A background task
  incrementally scrolls through the IDE conversation and accumulates
  turns into a local cache. The TUI reads from this cache — it never
  triggers IDE scrolling. MutationObserver handles real-time updates
  for the current viewport (e.g. during AI generation).

  Cache invalidation: CMD_CLEAR_CACHE resets the turn cache and
  restarts the background collector.
"""

import asyncio
import json
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
            target_title: Workspace basename for window title matching.
        """
        self.workspace_id = workspace_id
        self.workspace_root = os.path.realpath(workspace_root)
        self.window_id = None     # CG window ID (set by Supervisor)
        self._state = self.IDLE
        self._event_queue = asyncio.Queue()
        self._running = False
        self._broadcast_callback = None  # Set by WorkspaceSupervisor

        # Core components
        cache_path = os.path.join(
            self.workspace_root, CACHE_DIR_NAME, CACHE_FILE_NAME
        )
        self.store = StateStore(cache_path=cache_path)
        self.ide = IDEMonitor(pid, target_title=target_title)
        self._fs_watcher = None

        # CDP bridge + DOM watcher
        self.cdp = None           # CDPBridge (initialized in run())
        self._dom_watcher = DOMWatcher()
        self._collector_task = None

        # Turn cache — the source of truth for TUI data
        self._turn_cache = {}          # {turn_index: [messages]}
        self._cached_conv_title = ""   # invalidate on conversation switch
        self._collecting = False       # True during background scroll+scrape
        self._last_agent_scrape = 0.0  # monotonic timestamp for generating throttle
        self._turn_cache_path = os.path.join(
            self.workspace_root, CACHE_DIR_NAME, "turn_cache.json",
        )

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

    # ── Lifecycle loop ───────────────────────────────────────

    async def run(self):
        """Main event loop. Launch via asyncio.create_task()."""
        self._running = True

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

        # Load turn cache from disk (survives restarts)
        self._load_turn_cache()

        # Initialize CDP bridge + DOM watcher
        await self._init_cdp()

        # Initial viewport scrape (quick — current visible turns only)
        await self._do_cdp_poll()
        self.store.flush_to_disk()

        # Start background collector for incremental cache fill
        self._collector_task = asyncio.create_task(
            self._background_collector()
        )

        # Main loop: drain event queue
        while self._running:
            await self._drain_events()
            await asyncio.sleep(0.05)

    async def _init_cdp(self):
        """Initialize CDP bridge with event handler and DOM watcher.

        On failure, logs warning and sets self.cdp = None.
        The Engine continues running (FS/Git still works) but
        Agent Panel features are disabled.
        """
        from agbridge.collectors.cdp_bridge import CDPBridge

        self.cdp = CDPBridge(
            self.ide.pid, os.path.basename(self.workspace_root)
        )

        # Register event handler BEFORE connect so reader loop routes events
        self.cdp.set_event_handler(self._on_cdp_event)

        try:
            await self.cdp.connect()
            logger.info(
                "[%s] CDP bridge connected (mode=%s)",
                self.workspace_id, self.cdp.mode,
            )

            # Install DOM watcher (MutationObserver injection)
            await self._dom_watcher.install(self.cdp)

        except Exception as e:
            logger.warning(
                "[%s] CDP init failed: %s — Agent Panel disabled",
                self.workspace_id, e,
            )
            self.cdp = None

    # ── CDP event handling ────────────────────────────────────

    async def _on_cdp_event(self, method, params):
        """Handle CDP push events from the reader loop.

        Routes:
        - Runtime.bindingCalled → parse section → selective re-scrape
        - Runtime.executionContextCreated → re-inject DOM watcher
        """
        if method == "Runtime.bindingCalled":
            name = params.get("name", "")
            if name == BINDING_NAME:
                event_data = DOMWatcher.parse_event(
                    params.get("payload", "")
                )
                if event_data:
                    await self._on_dom_change(event_data)

        elif method == "Runtime.executionContextCreated":
            # Page reload detected — re-inject observers
            if self.cdp and self._dom_watcher.is_installed:
                logger.info(
                    "[%s] Execution context created — reinstalling watcher",
                    self.workspace_id,
                )
                await self._dom_watcher.reinstall(self.cdp)

    async def _on_dom_change(self, event_data):
        """Real-time update triggered by MutationObserver.

        Scrapes the current viewport and merges into the turn cache.
        Does NOT scroll the IDE — only processes what is visible.
        The background collector handles uncached turns separately.

        During ACTIVE (generating) state, agent section scrapes are
        throttled to 500ms intervals to reduce unnecessary CDP calls
        and WS pushes. Idle state retains full 100ms responsiveness.
        """
        if not self.cdp or not self.cdp.is_connected:
            return
        
        section = event_data.get("section")
        
        # 0. Fast-path independent state management
        if section == "state":
            new_state = event_data.get("status", "idle")
            if new_state == "generating" and self._state == self.IDLE:
                self._state = self.ACTIVE
                self.push_event(protocol.UI_CONV_STATE_CHANGE, {"state": "generating"})
                logger.info("[%s] Agent generating → ACTIVE", self.workspace_id)
            elif new_state == "idle" and self._state == self.ACTIVE:
                self._state = self.IDLE
                self.push_event(protocol.UI_CONV_STATE_CHANGE, {"state": "idle"})
                logger.info("[%s] AI generation complete → IDLE", self.workspace_id)
                self.store.flush_to_disk()
            return

        if self._collecting:
            return  # Skip while background collector is scrolling

        # Generating throttle: limit agent scrapes to 500ms intervals
        if section == "agent" and self._state == self.ACTIVE:
            now = time.monotonic()
            if now - self._last_agent_scrape < 0.5:
                return
            self._last_agent_scrape = now

        from agbridge.collectors import dom_scraper

        try:
            if section == "agent":
                agent_data = await dom_scraper.collect_agent_panel(self.cdp)
                agent_data = self._merge_turn_cache(agent_data)
                self._push_cache_to_tui(agent_data)

            elif section == "controls":
                edit_actions = await dom_scraper.collect_edit_actions(self.cdp)
                if self.store.update("edit_actions", edit_actions):
                    self.push_event(
                        protocol.UI_EDIT_ACTIONS_UPDATE, edit_actions
                    )

                # Models/modes also live in the controls area
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
        """Incrementally collect uncached turns in the background.

        Runs continuously. Each sweep:
        1. Gets the height map (all turn positions)
        2. Finds the first uncached turn
        3. Scrolls to it, waits for render, scrapes
        4. Merges into cache and pushes to TUI
        5. Waits before the next step

        When all turns are cached, waits longer before re-checking
        (new turns may appear during AI generation).
        """
        STEP_DELAY = 0.3    # seconds between scroll steps
        SWEEP_DELAY = 3.0   # seconds between full sweeps when complete
        SETTLE_MS = 200     # milliseconds to wait after scroll

        from agbridge.collectors import dom_scraper

        while self._running:
            if not self.cdp or not self.cdp.is_connected:
                await asyncio.sleep(2)
                continue

            try:
                height_map = await dom_scraper.get_conversation_height_map(
                    self.cdp,
                )
                if not height_map:
                    await asyncio.sleep(SWEEP_DELAY)
                    continue

                total_turns = len(height_map)
                collected_any = False

                for ti in range(total_turns):
                    if not self._running:
                        break
                    if ti in self._turn_cache:
                        continue

                    # Scroll to uncached turn
                    self._collecting = True
                    scroll_pos = height_map[ti]["scrollStart"]
                    await dom_scraper.scroll_conversation_to(
                        self.cdp, scroll_pos,
                    )
                    await asyncio.sleep(SETTLE_MS / 1000)

                    # Scrape visible turns
                    data = await dom_scraper.collect_agent_panel(self.cdp)
                    self._collecting = False

                    # Merge into cache
                    data = self._merge_turn_cache(data)
                    self._push_cache_to_tui(data)
                    collected_any = True

                    await asyncio.sleep(STEP_DELAY)

                # Restore scroll to bottom after sweep
                if collected_any and height_map:
                    self._collecting = True
                    total_height = sum(h["height"] for h in height_map)
                    await dom_scraper.scroll_conversation_to(
                        self.cdp, total_height,
                    )
                    self._collecting = False

                    self.push_event(
                        protocol.UI_CONV_SCAN_STATE,
                        {"scanning": False},
                    )
                    self.store.flush_to_disk()
                    logger.info(
                        "[%s] Background collector: %d/%d turns cached",
                        self.workspace_id,
                        len(self._turn_cache), total_turns,
                    )

            except Exception as e:
                self._collecting = False
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
                    await self._dom_watcher.reinstall(self.cdp)
                except ConnectionError:
                    pass
            return

        from agbridge.collectors import dom_scraper

        try:
            # Scrape current viewport (fast)
            agent_data = await dom_scraper.collect_agent_panel(self.cdp)
            agent_data = self._merge_turn_cache(agent_data)
            self._push_cache_to_tui(agent_data)

            # Notify TUI that background collection is starting
            self.push_event(
                protocol.UI_CONV_SCAN_STATE,
                {"scanning": True, "title": ""},
            )

            if agent_data.get("state") == "generating" and self._state == self.IDLE:
                self._state = self.ACTIVE
                self.push_event(protocol.UI_CONV_STATE_CHANGE, {"state": "generating"})
                logger.info("[%s] Agent generating → ACTIVE", self.workspace_id)

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
                self.push_event(
                    protocol.UI_MODELS_UPDATE, merged
                )

            # Confirm Undo dialog — detect modal overlay
            undo_dialog = await dom_scraper.detect_confirm_undo_dialog(self.cdp)
            if self.store.update("confirm_undo_dialog", undo_dialog):
                self.push_event(
                    protocol.UI_CONFIRM_UNDO_DIALOG, undo_dialog
                )

        except Exception as e:
            logger.warning("[%s] CDP poll failed: %s", self.workspace_id, e)

    def _start_fs_watcher(self):
        """Start watchdog monitoring."""
        self._fs_watcher = FSWatcher(
            self.workspace_root, self._on_fs_batch
        )
        self._fs_watcher.start()
        logger.info("[%s] FS Watcher started", self.workspace_id)
    # ── Turn cache (file-backed) ───────────────────────────────

    def _load_turn_cache(self):
        """Load turn cache from disk file."""
        if not os.path.isfile(self._turn_cache_path):
            return
        try:
            with open(self._turn_cache_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            self._cached_conv_title = payload.get("title", "")
            raw = payload.get("turns", {})
            # JSON keys are strings — convert back to int
            self._turn_cache = {int(k): v for k, v in raw.items()}
            logger.info(
                "[%s] Turn cache loaded: %d turns (conv='%s')",
                self.workspace_id, len(self._turn_cache),
                self._cached_conv_title[:40],
            )
        except (json.JSONDecodeError, ValueError, OSError) as e:
            logger.warning("[%s] Turn cache load failed: %s", self.workspace_id, e)
            self._turn_cache.clear()

    def _save_turn_cache(self):
        """Persist turn cache to disk file."""
        cache_dir = os.path.dirname(self._turn_cache_path)
        os.makedirs(cache_dir, exist_ok=True)

        payload = {
            "title": self._cached_conv_title,
            "turns": self._turn_cache,
        }
        tmp = self._turn_cache_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, self._turn_cache_path)

    def _delete_turn_cache_file(self):
        """Remove turn cache file from disk."""
        try:
            os.remove(self._turn_cache_path)
        except FileNotFoundError:
            pass

    def _merge_turn_cache(self, agent_data):
        """Merge scraped messages into the turn cache.

        Groups incoming messages by _ti (turn index) and replaces
        the cache entry for each scraped turn. Auto-invalidates
        on conversation title change. Persists to disk after merge.
        """
        conv_title = agent_data.get("conversation_title", "")
        if conv_title and conv_title != self._cached_conv_title:
            self._turn_cache.clear()
            self._cached_conv_title = conv_title
            self._delete_turn_cache_file()
            logger.info(
                "[%s] Conversation changed to '%s' — cache cleared",
                self.workspace_id, conv_title[:40],
            )

        messages = agent_data.get("messages", [])

        turn_groups: dict[int, list] = {}
        for msg in messages:
            ti = msg.pop("_ti", -1)
            if ti >= 0:
                turn_groups.setdefault(ti, []).append(msg)

        if turn_groups:
            for ti, msgs in turn_groups.items():
                self._turn_cache[ti] = msgs
            self._save_turn_cache()

        return agent_data

    def _push_cache_to_tui(self, agent_data):
        """Flatten turn cache and push to TUI if data changed."""
        flat = []
        for ti in sorted(self._turn_cache.keys()):
            for msg in self._turn_cache[ti]:
                flat.append({**msg, "_turn_idx": ti})

        agent_data["messages"] = flat
        agent_data["_total_turns"] = agent_data.get("_total_turns", 0)
        agent_data["_cached_turns"] = len(self._turn_cache)

        if self.store.update("agent_panel", agent_data):
            self.push_event(protocol.UI_AGENT_UPDATE, agent_data)

    def clear_cache(self):
        """Clear turn cache and restart background collection.

        Called by CMD_CLEAR_CACHE from TUI.
        """
        self._turn_cache.clear()
        self._cached_conv_title = ""
        self._delete_turn_cache_file()
        logger.info("[%s] Cache cleared by user request", self.workspace_id)

        # Push empty state to TUI
        self.push_event(
            protocol.UI_CONV_SCAN_STATE,
            {"scanning": True, "title": ""},
        )
        self.push_event(
            protocol.UI_AGENT_UPDATE,
            {"messages": [], "state": "unknown", "_total_turns": 0, "_cached_turns": 0},
        )

    def truncate_turn_cache(self, turn_idx):
        """Truncate the turn cache from the given turn index onwards.
        
        Slices the collection locally and immediately pushes the updated
        state to the TUI to eliminate DOM scraping delays during destructive
        actions like undo.
        """
        keys_to_delete = [k for k in self._turn_cache.keys() if k >= turn_idx]
        for k in keys_to_delete:
            del self._turn_cache[k]
        self._save_turn_cache()

        agent_data = self.store.get("agent_panel") or {}
        self._push_cache_to_tui(agent_data)
        logger.info(
            "[%s] Turn cache truncated at index %d (deleted %d turns)",
            self.workspace_id, turn_idx, len(keys_to_delete)
        )
        return agent_data

    # ── Shutdown ─────────────────────────────────────────────

    def stop(self):
        """Graceful shutdown: stop loop, stop FS watcher, disconnect CDP."""
        self._running = False

        # Cancel background collector
        if self._collector_task and not self._collector_task.done():
            self._collector_task.cancel()
        self._collector_task = None

        # Disconnect CDP bridge
        if self.cdp:
            asyncio.ensure_future(self.cdp.disconnect())

        if self._fs_watcher:
            self._fs_watcher.stop()
            self._fs_watcher = None

        self.store.flush_to_disk()
        logger.info("[%s] Engine stopped", self.workspace_id)
