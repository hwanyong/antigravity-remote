"""
agbridge_tui.connection — HTTP + WebSocket connection manager (multi-workspace)

Handles:
- Token loading (env → file → CLI arg)
- HTTP requests with workspace-aware routing
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

    def _auth_headers(self):
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return {}

    async def get_workspaces(self):
        """GET /api/workspaces → list of workspace info dicts."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/api/workspaces",
                headers=self._auth_headers(),
                timeout=5,
            )
            resp.raise_for_status()
            return resp.json().get("workspaces", [])

    async def open_workspace(self, path):
        """POST /api/workspaces → launch new IDE."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/api/workspaces",
                headers=self._auth_headers(),
                json={"path": path},
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()

    async def close_workspace(self, workspace_id):
        """DELETE /api/workspaces/{id} → close IDE."""
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{self.base_url}/api/workspaces/{workspace_id}",
                headers=self._auth_headers(),
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()

    # ── HTTP: Per-workspace ──────────────────────────────────

    async def get_snapshot(self, workspace_id):
        """GET /api/workspaces/{id}/snapshot → dict."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/api/workspaces/{workspace_id}/snapshot",
                headers=self._auth_headers(),
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()

    async def get_status(self, workspace_id):
        """GET /api/workspaces/{id}/status → dict."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/api/workspaces/{workspace_id}/status",
                headers=self._auth_headers(),
                timeout=5,
            )
            resp.raise_for_status()
            return resp.json()

    async def post_command(self, workspace_id, cmd_type, data=None):
        """POST /api/workspaces/{id}/command → dict."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/api/workspaces/{workspace_id}/command",
                headers=self._auth_headers(),
                json={"type": cmd_type, "data": data or {}},
                timeout=10,
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
        """Connection loop with exponential backoff reconnection."""
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

            self.ws = None
            self._ws_connected = False
            await self._notify_state("reconnecting")

            logger.info("Reconnecting in %ds...", self._backoff)
            await asyncio.sleep(self._backoff)
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
