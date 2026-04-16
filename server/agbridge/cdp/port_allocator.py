"""
agbridge.cdp.port_allocator — Dynamic CDP port allocation

Allocates unique --remote-debugging-port values per workspace,
resolving the single-port (9333) limitation that prevented
multi-window CDP connections.

Design:
  - Port range: [base_port, base_port + range)
  - Allocation: first-available with OS-level availability check
  - Existing IDE detection: probes /json endpoint on each port
"""

import logging
import socket
import urllib.request

logger = logging.getLogger("agbridge.cdp.port_allocator")


class PortAllocator:
    """Manages CDP port assignments for workspace instances."""

    def __init__(self, base_port=9333, port_range=10):
        """
        Args:
            base_port: Starting port number.
            port_range: Number of ports in the pool.
        """
        self._base_port = base_port
        self._range = port_range
        self._allocated = {}     # workspace_id → port
        self._port_to_ws = {}    # port → set of workspace_ids

    @property
    def base_port(self):
        return self._base_port

    def allocate(self, workspace_id):
        """Allocate a port for a workspace.

        If the workspace already has a port, returns it.
        Otherwise finds the first available port in the range.

        Args:
            workspace_id: Unique workspace identifier.

        Returns:
            int: Allocated port number.

        Raises:
            RuntimeError: If no ports are available.
        """
        if workspace_id in self._allocated:
            return self._allocated[workspace_id]

        for offset in range(self._range):
            port = self._base_port + offset
            if port in self._port_to_ws and len(self._port_to_ws[port]) > 0:
                continue
            # Port is free in our registry — allocate it
            self._allocated[workspace_id] = port
            if port not in self._port_to_ws:
                self._port_to_ws[port] = set()
            self._port_to_ws[port].add(workspace_id)
            logger.info(
                "Port allocated: ws=%s port=%d", workspace_id, port,
            )
            return port

        raise RuntimeError(
            f"No CDP ports available in range "
            f"[{self._base_port}, {self._base_port + self._range})"
        )

    def register_reuse(self, workspace_id, port):
        """Explicitly register a workspace to an already-active port.

        Args:
            workspace_id: Unique workspace identifier.
            port: Port number to reuse.
        """
        self._allocated[workspace_id] = port
        if port not in self._port_to_ws:
            self._port_to_ws[port] = set()
        self._port_to_ws[port].add(workspace_id)
        logger.info(
            "Port reused: ws=%s port=%d", workspace_id, port,
        )

    def release(self, workspace_id):
        """Release a previously allocated port.

        Args:
            workspace_id: Workspace to release port for.
        """
        port = self._allocated.pop(workspace_id, None)
        if port is not None:
            if port in self._port_to_ws:
                self._port_to_ws[port].discard(workspace_id)
                if not self._port_to_ws[port]:
                    self._port_to_ws.pop(port, None)
                    logger.info("Port released completely: port=%d", port)
            logger.info(
                "Port unmapped: ws=%s port=%d", workspace_id, port,
            )

    def get(self, workspace_id):
        """Get the currently allocated port for a workspace.

        Returns:
            int or None
        """
        return self._allocated.get(workspace_id)

    def discover_existing_port(self, workspace_name):
        """Probe the port range for an already-running IDE.

        Checks each port's /json endpoint for a page target whose
        title matches the workspace name.

        Args:
            workspace_name: Basename of the workspace directory.

        Returns:
            int or None: Port number if found.
        """
        from agbridge.config import TITLE_SEPARATOR

        for offset in range(self._range):
            port = self._base_port + offset
            try:
                url = f"http://localhost:{port}/json"
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=0.5) as resp:
                    import json
                    targets = json.loads(resp.read())
                for t in targets:
                    if t.get("type") != "page":
                        continue
                    title = t.get("title", "")
                    if (title == workspace_name
                            or title.startswith(workspace_name + TITLE_SEPARATOR)):
                        logger.info(
                            "Discovered existing IDE: ws=%s port=%d title=%s",
                            workspace_name, port, title[:60],
                        )
                        return port
            except Exception:
                continue
        return None

    @staticmethod
    def is_port_available(port):
        """Check if a port is available for binding.

        Args:
            port: Port number to test.

        Returns:
            bool: True if available.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("localhost", port))
            return True
        except OSError:
            return False
        finally:
            sock.close()
