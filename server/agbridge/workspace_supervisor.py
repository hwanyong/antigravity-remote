"""
agbridge.workspace_supervisor — Unified workspace lifecycle manager

Merges the former ProcessScanner and WorkspaceRegistry into a single
Supervisor using a Kubernetes-style reconciliation loop.

Key design decisions:
- No intermediate state cache — AX API + NSWorkspace is the single
  source of truth, queried every reconcile cycle.
- Engines never self-terminate — only the Supervisor spawns/stops them.
- _engines dict is the only authoritative record of managed workspaces.

Reconciliation pattern:
  desired = discover_windows()   (from AX API, stateless)
  actual  = self._engines        (Supervisor's managed state)
  diff    = desired ⊕ actual     (spawn / stop)
"""

import asyncio
import json
import logging
import os
import time

from agbridge import protocol
from agbridge.config import (
    OWNER_NAME,
    POLL_AWAIT_IDE_INTERVAL,
    CDP_BASE_PORT,
    CDP_PORT_RANGE,
)
from agbridge.engine import Engine
from agbridge.cdp.port_allocator import PortAllocator
from agbridge.window_discovery import (
    discover_windows,
    get_window_states,
    launch_ide,
)

logger = logging.getLogger("agbridge.workspace_supervisor")


class WorkspaceSupervisor:
    """
    Unified supervisor for workspace Engine lifecycle.

    Responsibilities:
    - Periodically reconcile CG windows with Engine instances
    - Spawn/stop Engines based on window presence
    - Manage WS client connections and event broadcasting
    - Provide workspace query API for HTTP/WS handlers
    - Allocate/release CDP ports per workspace
    """

    # Timeout for pending close entries (seconds)
    _CLOSE_TIMEOUT = 30

    def __init__(self):
        self._engines = {}          # workspace_id → Engine
        self._tasks = {}            # workspace_id → asyncio.Task
        self._ws_clients = set()    # Connected WebSocket clients
        self._ws_last_pong = {}     # ws → timestamp
        self._launched_paths = {}   # basename → full_path (from launch_ide)
        self._pending_closes = {}   # workspace_path → close_timestamp
        self._reconcile_interval = POLL_AWAIT_IDE_INTERVAL
        self._port_allocator = PortAllocator(
            base_port=CDP_BASE_PORT,
            port_range=CDP_PORT_RANGE,
        )

    # ── Lifecycle ────────────────────────────────────────────

    async def initial_reconcile(self):
        """
        Synchronous initialization — called before HTTP server starts.

        Runs one reconcile cycle to populate the engine registry with
        any pre-existing Antigravity windows.
        """
        await self._reconcile()
        count = len(self._engines)
        logger.info("Initial reconcile complete: %d workspace(s)", count)

        if count == 0:
            self._log_diagnostics()

    async def run(self):
        """
        Main reconciliation loop — runs as a background asyncio task.

        Every cycle: discover current CG windows → compare with managed
        engines → spawn/stop as needed.
        """
        logger.info(
            "Supervisor started (interval=%.1fs)", self._reconcile_interval,
        )
        while True:
            try:
                await self._reconcile()
            except Exception as e:
                logger.error("Reconcile error: %s", e)

            await asyncio.sleep(self._reconcile_interval)

    # ── Reconciliation core ──────────────────────────────────

    async def _reconcile(self):
        """
        Compare CG reality with managed Engines and resolve differences.

        No intermediate cache — every call reconstructs desired state
        from the OS, making zombie states structurally impossible.
        """
        # 1. Desired state: what CG API says exists right now
        discovered = await asyncio.to_thread(
            discover_windows, fallback_paths=self._launched_paths
        )

        desired_by_id = {}
        for win in discovered:
            ws_id = self._derive_id(win.workspace_path)
            desired_by_id[ws_id] = win

        # 2. Current state: what we manage
        actual_ids = set(self._engines.keys())
        desired_ids = set(desired_by_id.keys())

        # 3. Spawn: in desired but not in actual
        #    Skip windows that were intentionally closed (pending_closes)
        for ws_id in desired_ids - actual_ids:
            win = desired_by_id[ws_id]
            real_path = os.path.realpath(win.workspace_path)
            if real_path in self._pending_closes:
                continue
            await self._spawn_engine(ws_id, win)

        # 4. Stop: in actual but not in desired (window gone)
        for ws_id in actual_ids - desired_ids:
            await self._stop_engine(ws_id)

        # 5. Cleanup pending_closes: remove entries whose window
        #    has actually disappeared, or that have timed out
        active_paths = {
            os.path.realpath(w.workspace_path) for w in discovered
        }
        now = time.time()
        expired = [
            p for p, ts in self._pending_closes.items()
            if p not in active_paths or (now - ts) > self._CLOSE_TIMEOUT
        ]
        for p in expired:
            del self._pending_closes[p]
            logger.debug("Pending close cleared: %s", p)

    # ── Engine spawn / stop ──────────────────────────────────

    async def _spawn_engine(self, ws_id, win):
        """Create, start, and register a new Engine with dynamic CDP port."""
        workspace_title = os.path.basename(
            os.path.realpath(win.workspace_path)
        )

        # 1. Lookup existing engine sharing the same PID (N:1 multiplexing)
        existing_port = None
        for eng in self._engines.values():
            if eng.ide and eng.ide.pid == win.pid:
                existing_port = eng.cdp_port
                break

        if existing_port:
            cdp_port = existing_port
            self._port_allocator.register_reuse(ws_id, cdp_port)
            logger.info("PID %d is shared; reusing existing CDP port %d for workspace %s", win.pid, cdp_port, ws_id)
        else:
            # Allocate a new CDP port for this workspace
            cdp_port = self._port_allocator.allocate(ws_id)

        engine = Engine(
            ws_id, win.workspace_path, win.pid,
            target_title=workspace_title,
            cdp_port=cdp_port,
        )
        engine.set_broadcast_callback(self.broadcast)

        self._engines[ws_id] = engine

        task = asyncio.create_task(self._engine_runner(ws_id, engine))
        self._tasks[ws_id] = task

        logger.info(
            "Engine spawned: id=%s path=%s pid=%d cdp_port=%d",
            ws_id, win.workspace_path, win.pid, cdp_port,
        )

        await self._broadcast_global(protocol.SYS_WORKSPACE_REGISTERED, {
            "workspace_id": ws_id,
            "path": win.workspace_path,
            "pid": win.pid,
        })

    async def _engine_runner(self, ws_id, engine):
        """
        Wrapper for Engine.run() — Engine no longer self-terminates.

        If Engine.run() exits unexpectedly, the next reconcile cycle
        will detect the missing CG window and clean up.
        """
        try:
            await engine.run()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("[%s] Engine crashed: %s", ws_id, e)

    async def _stop_engine(self, ws_id):
        """Stop and unregister an Engine, releasing its CDP port."""
        engine = self._engines.pop(ws_id, None)
        if not engine:
            return

        task = self._tasks.pop(ws_id, None)

        engine.stop()

        # Release CDP port back to the pool
        self._port_allocator.release(ws_id)

        if task and not task.done():
            task.cancel()

        path = engine.workspace_root
        pid = engine.ide.pid if engine.ide else 0
        logger.info("Engine stopped: id=%s", ws_id)

        await self._broadcast_global(protocol.SYS_WORKSPACE_UNREGISTERED, {
            "workspace_id": ws_id,
            "path": path,
            "pid": pid,
        })

    # ── Query API ────────────────────────────────────────────

    def get(self, workspace_id):
        """Return Engine by workspace_id, or None."""
        return self._engines.get(workspace_id)

    async def list_all(self):
        """Return summary of all managed workspaces with window state."""
        window_states = await asyncio.to_thread(
            get_window_states, known_workspaces=set(self._engines.keys())
        )  # {workspace_name → state}

        result = []
        for ws_id, engine in self._engines.items():
            window_state = window_states.get(ws_id, "CLOSED")

            result.append({
                "workspace_id": ws_id,
                "path": engine.workspace_root,
                "state": engine.current_state,
                "window_state": window_state,
                "pid": engine.ide.pid if engine.ide else None,
                "ide_connected": engine.ide.is_connected if engine.ide else False,
            })
        return result

    @property
    def is_empty(self):
        return len(self._engines) == 0

    async def close_workspace(self, workspace_id):
        """
        Imperative close: immediately stop an engine upon user request.

        Registers the workspace path in _pending_closes so the reconcile
        loop won't re-spawn it while the CG window lingers. The entry
        is auto-cleaned when the CG window actually disappears or after
        _CLOSE_TIMEOUT seconds (allowing recovery if close was cancelled).
        """
        engine = self._engines.get(workspace_id)
        if not engine:
            return False

        real_path = os.path.realpath(engine.workspace_root)
        self._pending_closes[real_path] = time.time()

        engine.ide.close_ide()
        await self._stop_engine(workspace_id)
        return True

    # ── IDE launch ───────────────────────────────────────────

    def launch_workspace(self, path):
        """
        Launch a new IDE for the given path.

        Pre-registers basename → path so the next reconcile cycle
        can resolve the CG window even before workspaceStorage updates.
        Allocates a CDP port for the new workspace.

        Returns:
            int | None: PID of launched process.
        """
        basename = os.path.basename(os.path.realpath(path))
        self._launched_paths[basename] = os.path.realpath(path)

        # Pre-allocate CDP port for the workspace being launched
        cdp_port = self._port_allocator.allocate(basename)

        return launch_ide(path, port=cdp_port)

    # ── WebSocket client management ──────────────────────────

    def register_ws(self, ws):
        """Register a WS client to receive events from all workspaces."""
        self._ws_clients.add(ws)
        self._ws_last_pong[ws] = time.time()

    def unregister_ws(self, ws):
        """Remove a WS client."""
        self._ws_clients.discard(ws)
        self._ws_last_pong.pop(ws, None)

    def record_pong(self, ws):
        self._ws_last_pong[ws] = time.time()

    async def broadcast(self, workspace_id, event_type, payload=None):
        """
        Broadcast a workspace-scoped event to all WS clients.

        Called by individual Engines via their broadcast callback.
        """
        msg = json.dumps({
            "type": event_type,
            "workspace_id": workspace_id,
            "data": payload,
            "ts": time.time(),
        })
        await self._send_to_all(msg)

    async def _broadcast_global(self, event_type, payload=None):
        """Broadcast a system-level event (workspace_id = null)."""
        msg = json.dumps({
            "type": event_type,
            "workspace_id": None,
            "data": payload,
            "ts": time.time(),
        })
        await self._send_to_all(msg)

    async def _send_to_all(self, msg):
        """Send a message to all WS clients, evicting stale ones.

        Uses a list snapshot of _ws_clients to prevent RuntimeError
        when concurrent coroutines modify the set during await yields.
        """
        snapshot = list(self._ws_clients)
        stale = []
        for ws in snapshot:
            try:
                await ws.send_text(msg)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self._ws_clients.discard(ws)
            self._ws_last_pong.pop(ws, None)

    async def _heartbeat_loop(self):
        """Send PING to all WS clients at regular intervals.

        Prevents Cloudflare Tunnel's 100-second idle timeout from
        terminating WebSocket connections. Harmless for direct LAN clients.
        """
        from agbridge.config import WS_HEARTBEAT_INTERVAL

        logger.info("WS heartbeat started (interval=%ds)", WS_HEARTBEAT_INTERVAL)
        while True:
            await asyncio.sleep(WS_HEARTBEAT_INTERVAL)
            if not self._ws_clients:
                continue
            msg = json.dumps({"type": "PING", "ts": time.time()})
            await self._send_to_all(msg)

    # ── Internal ─────────────────────────────────────────────

    def _derive_id(self, path):
        """
        Generate a workspace_id from path.

        Uses exact path matching to reuse existing workspace_ids,
        otherwise uses basename with numeric suffix for deduplication.
        """
        real_path = os.path.realpath(os.path.expanduser(path))

        for existing_id, engine in self._engines.items():
            if os.path.realpath(
                os.path.expanduser(engine.workspace_root)
            ) == real_path:
                return existing_id

        base = os.path.basename(real_path)
        if not base:
            base = "workspace"

        candidate = base
        counter = 1
        while candidate in self._engines:
            counter += 1
            candidate = f"{base}_{counter}"

        return candidate

    def _log_diagnostics(self):
        """Log diagnostic info when no workspaces found."""
        from agbridge.window_discovery import _get_ag_pids
        ag_apps_len = len(_get_ag_pids())

        logger.warning(
            "Zero workspaces found. Diagnostics: "
            "Antigravity processes=%d",
            ag_apps_len,
        )
        for pid in _get_ag_pids():
            try:
                from ApplicationServices import (
                    AXUIElementCreateApplication,
                    AXUIElementCopyAttributeValue,
                    kAXWindowsAttribute,
                )
                ax_app = AXUIElementCreateApplication(pid)
                err, wins = AXUIElementCopyAttributeValue(ax_app, kAXWindowsAttribute, None)
                if not wins:
                    logger.debug("  PID %d: 0 windows (err=%s)", pid, err)
                else:
                    titles = []
                    for w in wins:
                        _, t = AXUIElementCopyAttributeValue(w, "AXTitle", None)
                        if t: titles.append(t)
                    logger.debug("  PID %d: %d windows, titles=%s", pid, len(wins), titles)
            except Exception as e:
                logger.debug("  PID %d: AX lookup failed: %s", pid, e)
