"""
agbridge_tui.connection — HTTP + WebSocket connection manager (multi-workspace)

Handles:
- Token loading (env → file → CLI arg)
- Persistent HTTP client with connection pooling (singleton AsyncClient)
- WebSocket connection with auto-reconnect (exponential backoff)
- Single WS endpoint receiving all workspace events
"""

import asyncio
import json
import logging
import os
import time

import httpx
import websockets

logger = logging.getLogger("agbridge_tui.connection")

DEFAULT_TOKEN_FILE = os.path.expanduser("~/.agbridge/token")


class _TokenAuth(httpx.Auth):
    """Auto-inject Bearer token into every HTTP request.

    References the Connection's token attribute directly,
    so reload_token() updates are picked up automatically.
    """

    def __init__(self, connection):
        self._conn = connection

    def auth_flow(self, request):
        if self._conn.token:
            request.headers["Authorization"] = f"Bearer {self._conn.token}"
        yield request


class Connection:
    """Manages HTTP and WebSocket connections to agbridge daemon."""

    def __init__(self, host="localhost", port=18080, token=None):
        self.host = host
        self.port = port
        self.token = token or ""
        self.ws = None
        self._ws_connected = False
        self._reconnect_task = None
        self._on_event = None
        self._on_state_change = None
        self._backoff = 1
        self._http = None

    @property
    def base_url(self):
        return f"http://{self.host}:{self.port}"

    @property
    def ws_url(self):
        url = f"ws://{self.host}:{self.port}/ws"
        if self.token:
            url += f"?token={self.token}"
        return url

    @property
    def is_ws_connected(self):
        return self._ws_connected

    # ── Lifecycle ────────────────────────────────────────────

    async def start(self):
        """Initialize the persistent HTTP client.

        Must be called from an async context (e.g. App.on_mount).
        Uses connection pooling — all HTTP requests share one TCP connection.
        """
        if self._http:
            return

        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            auth=_TokenAuth(self),
            timeout=10,
        )
        logger.info("HTTP client started: %s", self.base_url)

    async def close(self):
        """Shut down both HTTP client and WebSocket connection.

        Must be called from an async context (e.g. App.on_unmount).
        """
        if self._http:
            await self._http.aclose()
            self._http = None
            logger.info("HTTP client closed")

        await self.ws_close()

    # ── Token ────────────────────────────────────────────────

    def load_token(self, token_file=None):
        """Load token from environment, file, or use existing."""
        env_token = os.environ.get("AGBRIDGE_TOKEN", "")
        if env_token:
            self.token = env_token
            logger.info("Token loaded from environment variable")
            return

        path = token_file or DEFAULT_TOKEN_FILE
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                stored = f.read().strip()
            if stored:
                self.token = stored
                logger.info("Token loaded from %s", path)
                return

        logger.warning("No token found — requests may fail if auth is enabled")

    def reload_token(self, token_file=None):
        """Force reload token from file (for expired token recovery)."""
        path = token_file or DEFAULT_TOKEN_FILE
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                self.token = f.read().strip()
            logger.info("Token reloaded from %s", path)

    # ── HTTP: Workspace CRUD ─────────────────────────────────

    async def get_workspaces(self):
        """GET /api/workspaces → list of workspace info dicts."""
        resp = await self._http.get("/api/workspaces", timeout=5)
        resp.raise_for_status()
        return resp.json().get("workspaces", [])

    async def open_workspace(self, path):
        """POST /api/workspaces → launch new IDE."""
        resp = await self._http.post(
            "/api/workspaces",
            json={"path": path},
        )
        resp.raise_for_status()
        return resp.json()

    async def close_workspace(self, workspace_id):
        """DELETE /api/workspaces/{id} → close IDE."""
        resp = await self._http.delete(
            f"/api/workspaces/{workspace_id}",
        )
        resp.raise_for_status()
        return resp.json()

    # ── HTTP: Per-workspace ──────────────────────────────────

    async def get_snapshot(self, workspace_id):
        """GET /api/workspaces/{id}/snapshot → dict."""
        resp = await self._http.get(
            f"/api/workspaces/{workspace_id}/snapshot",
        )
        resp.raise_for_status()
        return resp.json()

    async def get_status(self, workspace_id):
        """GET /api/workspaces/{id}/status → dict."""
        resp = await self._http.get(
            f"/api/workspaces/{workspace_id}/status",
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()

    async def post_command(self, workspace_id, cmd_type, data=None):
        """POST /api/workspaces/{id}/command → dict."""
        resp = await self._http.post(
            f"/api/workspaces/{workspace_id}/command",
            json={"type": cmd_type, "data": data or {}},
        )
        resp.raise_for_status()
        return resp.json()

    # ── WebSocket ────────────────────────────────────────────

    def set_event_handler(self, handler):
        """Set callback: async def handler(event_type, data, ts, workspace_id)"""
        self._on_event = handler

    def set_state_change_handler(self, handler):
        """Set callback: async def handler(state: str)"""
        self._on_state_change = handler

    async def ws_connect(self):
        """Connect to WebSocket and start listening."""
        self._backoff = 1
        await self._ws_connect_loop()

    async def _ws_connect_loop(self):
        """Connection loop with exponential backoff reconnection.

        This coroutine runs as a Textual Worker.  It must NEVER
        propagate an exception, because Textual's default
        ``exit_on_error=True`` would terminate the entire TUI.
        Every ``await`` is a potential ``CancelledError`` injection
        point, and ``CancelledError`` is a ``BaseException`` — not
        caught by ``except Exception``.
        """
        while True:
            try:
                await self._notify_state("connecting")
                async with websockets.connect(self.ws_url) as ws:
                    self.ws = ws
                    self._ws_connected = True
                    self._backoff = 1
                    await self._notify_state("connected")
                    logger.info("WS connected to %s", self.ws_url)

                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                            msg_type = msg.get("type", "")
                            data = msg.get("data")
                            ts = msg.get("ts", time.time())
                            workspace_id = msg.get("workspace_id")

                            # Auto PONG
                            if msg_type == "PING":
                                await ws.send(json.dumps({"type": "PONG"}))

                            if self._on_event:
                                await self._on_event(
                                    msg_type, data, ts, workspace_id
                                )
                        except json.JSONDecodeError:
                            pass
                        except asyncio.CancelledError:
                            raise
                        except Exception as e:
                            logger.warning("Event handler error: %s", e)

            except asyncio.CancelledError:
                logger.info("WS loop cancelled — stopping reconnect")
                return
            except websockets.exceptions.ConnectionClosedError as e:
                if e.code == 1008:
                    logger.warning("WS auth rejected (1008) — reloading token")
                    self.reload_token()
                elif e.code == 1013:
                    logger.warning("WS rejected: max clients reached")
            except (ConnectionRefusedError, OSError, websockets.exceptions.InvalidURI) as e:
                logger.warning("WS connection failed: %s", e)
            except Exception as e:
                logger.warning("WS unexpected error: %s", e)

            # Cleanup — also protected from exceptions
            self.ws = None
            self._ws_connected = False
            try:
                await self._notify_state("reconnecting")
            except asyncio.CancelledError:
                logger.info("WS loop cancelled during reconnect notify — stopping")
                return
            except Exception as e:
                logger.warning("Failed to notify reconnecting state: %s", e)

            logger.info("Reconnecting in %ds...", self._backoff)
            try:
                await asyncio.sleep(self._backoff)
            except asyncio.CancelledError:
                logger.info("WS loop cancelled during backoff sleep — stopping")
                return
            self._backoff = min(self._backoff * 2, 30)

    async def ws_send_command(self, workspace_id, cmd_type, data=None):
        """Send a command via WebSocket."""
        if not self.ws or not self._ws_connected:
            return None

        msg = json.dumps({
            "type": cmd_type,
            "workspace_id": workspace_id,
            "data": data or {},
        })
        await self.ws.send(msg)
        return True

    async def ws_close(self):
        """Close WebSocket connection."""
        if self.ws:
            await self.ws.close()
            self.ws = None
            self._ws_connected = False

    async def _notify_state(self, state):
        """Notify connection state change."""
        if self._on_state_change:
            await self._on_state_change(state)
