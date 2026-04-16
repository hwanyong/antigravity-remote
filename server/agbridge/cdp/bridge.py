"""
agbridge.cdp.bridge — CDP WebSocket connection manager

Per-workspace bridge to the Antigravity Renderer process via Chrome
DevTools Protocol. Direct CDP mode only (--remote-debugging-port).

Changes from original collectors/cdp_bridge.py:
  - Constructor accepts `port` parameter (no global CDP_DIRECT_PORT ref)
  - _discover_target fallback ("first page target") REMOVED
  - Only exact workspace title matching is accepted

Architecture:
  - Single _ws_reader_loop task receives ALL WebSocket messages
  - Request-response: msg_id → Future map (_pending)
  - CDP events: routed to _event_handler callback
  - Runtime.addBinding: enables DOM→Python push notifications

Usage:
    bridge = CDPBridge(pid, workspace_name, port=9333)
    bridge.set_event_handler(my_handler)
    await bridge.connect()
    result = await bridge.execute_js("document.title")
    await bridge.disconnect()
"""

import asyncio
import json
import logging
import urllib.request

from websockets.asyncio.client import connect as _ws_connect
from websockets.exceptions import ConnectionClosed as _WSConnectionClosed

from agbridge.config import (
    CDP_CONNECT_TIMEOUT,
    CDP_RECONNECT_MAX,
)

logger = logging.getLogger("agbridge.cdp.bridge")


class CDPBridge:
    """Per-workspace CDP connection (Direct mode only).

    Single WS reader loop dispatches messages to:
    - _pending[msg_id].set_result(data)  for request-response
    - _event_handler(method, params)     for CDP push events
    """

    def __init__(self, pid, workspace_name, port):
        """
        Args:
            pid: OS process ID of the Antigravity IDE.
            workspace_name: Basename of the workspace directory.
            port: CDP debugging port for this workspace.
        """
        self.pid = pid
        self.workspace_name = workspace_name
        self._port = port
        self._ws = None
        self._msg_id = 0
        self._lock = asyncio.Lock()
        self._connected = False

        # Event-driven infrastructure
        self._pending = {}            # msg_id → asyncio.Future
        self._reader_task = None      # _ws_reader_loop task
        self._event_handler = None    # async def handler(method, params)
        self._bindings = set()        # Active binding names

    @property
    def port(self):
        return self._port

    @property
    def is_connected(self):
        return self._connected

    @property
    def mode(self):
        return "direct" if self._connected else None

    # ── Event Handler ────────────────────────────────────────

    def set_event_handler(self, handler):
        """Set CDP event callback.

        Args:
            handler: async def handler(method: str, params: dict)
                Called for every CDP push event (e.g. Runtime.bindingCalled).
        """
        self._event_handler = handler

    # ── Connection ───────────────────────────────────────────

    async def connect(self):
        """Establish Direct CDP connection.

        Connects to the Renderer page target via --remote-debugging-port.
        After connection:
          1. Enables Runtime domain
          2. Starts _ws_reader_loop background task
        """
        ws_url = self._discover_target()
        if not ws_url:
            raise ConnectionError(
                f"CDP connection failed for PID {self.pid} "
                f"(no matching page target on port {self._port})"
            )

        await self._connect_ws(ws_url)

        # Enable Runtime before starting reader loop (synchronous recv)
        await self._enable_runtime_sync()

        # Start background reader — all subsequent recv goes through it
        self._reader_task = asyncio.create_task(
            self._ws_reader_loop()
        )

        logger.info(
            "CDP connected (direct): PID=%d workspace=%s port=%d",
            self.pid, self.workspace_name, self._port,
        )

    async def disconnect(self):
        """Close WebSocket connection and stop reader loop."""
        self._connected = False
        self._bindings.clear()

        # Cancel reader task
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
        self._reader_task = None

        # Fail all pending requests
        for future in self._pending.values():
            if not future.done():
                future.set_exception(
                    ConnectionError("CDP disconnected")
                )
        self._pending.clear()

        # Close WebSocket
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def reconnect(self):
        """Attempt reconnection up to CDP_RECONNECT_MAX times."""
        await self.disconnect()
        for attempt in range(1, CDP_RECONNECT_MAX + 1):
            try:
                await self.connect()
                logger.info("CDP reconnected (attempt %d)", attempt)
                return
            except ConnectionError:
                if attempt < CDP_RECONNECT_MAX:
                    await asyncio.sleep(1.0)
        raise ConnectionError(
            f"CDP reconnection failed after {CDP_RECONNECT_MAX} attempts"
        )

    # ── Runtime.addBinding ───────────────────────────────────

    async def add_binding(self, name):
        """Register a JS→Python binding function.

        Creates window.<name>() in the Renderer. When called from JS,
        triggers Runtime.bindingCalled event received by _event_handler.
        """
        result = await self._send_command(
            "Runtime.addBinding", {"name": name}
        )
        if result is not None:
            self._bindings.add(name)
            logger.info("Binding registered: %s", name)
        return result

    async def remove_binding(self, name):
        """Remove a previously registered binding."""
        result = await self._send_command(
            "Runtime.removeBinding", {"name": name}
        )
        self._bindings.discard(name)
        return result

    # ── JavaScript Execution ─────────────────────────────────

    async def execute_js(self, js_code):
        """Execute JavaScript in the Renderer context.

        Args:
            js_code: JavaScript code string to execute.

        Returns:
            Parsed result value, or None on failure.
        """
        if not self._connected:
            return None

        async with self._lock:
            try:
                return await self._eval_direct(js_code)
            except asyncio.TimeoutError:
                # JS Promise did not resolve — the WebSocket connection
                # is still alive.  Do NOT mark _connected = False.
                logger.warning("CDP execute_js timeout (Promise did not resolve)")
                return None
            except (
                _WSConnectionClosed,
                ConnectionError,
            ) as e:
                logger.warning("CDP execute_js failed: %s", e)
                self._connected = False
                return None

    async def _eval_direct(self, js_code):
        """Runtime.evaluate in Renderer context via Future map."""
        self._msg_id += 1
        msg_id = self._msg_id
        msg = {
            "id": msg_id,
            "method": "Runtime.evaluate",
            "params": {
                "expression": js_code,
                "returnByValue": True,
                "awaitPromise": True,
            },
        }

        future = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = future

        try:
            await self._ws.send(json.dumps(msg))
            data = await asyncio.wait_for(
                future, timeout=CDP_CONNECT_TIMEOUT
            )
            return self._parse_result(data)
        finally:
            self._pending.pop(msg_id, None)

    async def _send_command(self, method, params=None):
        """Send a CDP command and await its result."""
        if not self._connected:
            return None

        async with self._lock:
            self._msg_id += 1
            msg_id = self._msg_id
            msg = {"id": msg_id, "method": method}
            if params:
                msg["params"] = params

            future = asyncio.get_event_loop().create_future()
            self._pending[msg_id] = future

            try:
                await self._ws.send(json.dumps(msg))
                data = await asyncio.wait_for(
                    future, timeout=CDP_CONNECT_TIMEOUT
                )
                if "error" in data:
                    logger.warning(
                        "CDP command %s failed: %s",
                        method, data["error"],
                    )
                    return None
                return data.get("result", {})
            except (asyncio.TimeoutError, ConnectionError) as e:
                logger.warning("CDP command %s timeout: %s", method, e)
                return None
            finally:
                self._pending.pop(msg_id, None)

    async def send_key(self, key, code, key_code=0):
        """Send a keyboard key press (keyDown + keyUp) via CDP.

        Uses Input.dispatchKeyEvent which generates trusted events,
        unlike JavaScript-synthesized KeyboardEvents.
        """
        for event_type in ("keyDown", "keyUp"):
            await self._send_command("Input.dispatchKeyEvent", {
                "type": event_type,
                "key": key,
                "code": code,
                "windowsVirtualKeyCode": key_code,
                "nativeVirtualKeyCode": key_code,
            })

    # ── WebSocket Reader Loop ────────────────────────────────

    async def _ws_reader_loop(self):
        """Single background task: receive all WS messages.

        Routes messages to either:
        - _pending[id] Future (request-response)
        - _event_handler callback (CDP push events)
        """
        try:
            async for raw in self._ws:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                msg_id = data.get("id")

                # Request-response: resolve pending Future
                if msg_id is not None and msg_id in self._pending:
                    future = self._pending[msg_id]
                    if not future.done():
                        future.set_result(data)
                    continue

                # CDP event: route to handler (fire-and-forget)
                # MUST NOT await — handler may call execute_js which
                # needs this reader loop to resolve its Future.
                method = data.get("method")
                if method and self._event_handler:
                    asyncio.create_task(
                        self._safe_handle_event(
                            method, data.get("params", {})
                        )
                    )

        except _WSConnectionClosed as e:
            logger.info("CDP WebSocket closed: %s", e)
        except asyncio.CancelledError:
            logger.debug("CDP reader loop cancelled")
            return
        except Exception as e:
            logger.warning("CDP reader loop error: %s (%s)", e, type(e).__name__)
        finally:
            if self._connected:
                logger.warning("CDP reader loop ended while still connected")
            self._connected = False

    # ── Internal Helpers ─────────────────────────────────────

    async def _safe_handle_event(self, method, params):
        """Wrapper for event handler with error logging."""
        try:
            await self._event_handler(method, params)
        except Exception as e:
            logger.warning("Event handler error for %s: %s", method, e)

    async def _connect_ws(self, ws_url):
        """Establish WebSocket connection with timeout."""
        self._ws = await asyncio.wait_for(
            _ws_connect(
                ws_url,
                max_size=10 * 1024 * 1024,
                ping_interval=None,
            ),
            timeout=CDP_CONNECT_TIMEOUT,
        )
        self._connected = True

    async def _enable_runtime_sync(self):
        """Enable Runtime domain (synchronous recv before reader starts)."""
        self._msg_id += 1
        msg = {"id": self._msg_id, "method": "Runtime.enable"}
        await self._ws.send(json.dumps(msg))
        # Direct recv — reader loop not yet started
        while True:
            raw = await asyncio.wait_for(
                self._ws.recv(), timeout=CDP_CONNECT_TIMEOUT
            )
            data = json.loads(raw)
            if data.get("id") == self._msg_id:
                break

    @staticmethod
    def _parse_result(data):
        """Extract value from CDP Runtime.evaluate response."""
        result_obj = data.get("result", {}).get("result", {})

        # Handle exceptions from Runtime.evaluate
        if "exceptionDetails" in data.get("result", {}):
            exc = data["result"]["exceptionDetails"]
            logger.warning("CDP JS exception: %s", exc.get("text", ""))
            return None

        # Extract value based on type
        val_type = result_obj.get("type")
        if val_type == "string":
            return result_obj.get("value")
        if val_type in ("number", "boolean"):
            return result_obj.get("value")
        if val_type == "undefined":
            return None
        if val_type == "object" and result_obj.get("subtype") == "null":
            return None

        # For objects returned by value
        return result_obj.get("value")

    def _discover_target(self):
        """Discover WebSocket URL from CDP /json endpoint.

        Finds a 'page' target matching workspace title.
        NO FALLBACK — returns None if no match found.
        This prevents cross-workspace prompt injection.

        Returns:
            WebSocket URL string, or None if unavailable.
        """
        url = f"http://localhost:{self._port}/json"
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=2) as resp:
                targets = json.loads(resp.read())
        except Exception:
            return None

        if not targets:
            return None

        # Find page matching workspace name — strict matching only
        from agbridge.config import TITLE_SEPARATOR
        for t in targets:
            if t.get("type") != "page":
                continue
            title = t.get("title", "")
            if (title == self.workspace_name
                    or title.startswith(self.workspace_name + TITLE_SEPARATOR)):
                return t.get("webSocketDebuggerUrl")

        # NO FALLBACK — "first page target" is removed.
        # If no match found, return None to prevent wrong-workspace injection.
        logger.warning(
            "CDP target not found: workspace=%s port=%d (available: %s)",
            self.workspace_name,
            self._port,
            [t.get("title", "")[:40] for t in targets if t.get("type") == "page"],
        )
        return None
