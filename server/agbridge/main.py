"""
agbridge.main — Daemon server entrypoint (multi-workspace)

Runs FastAPI (uvicorn), WorkspaceSupervisor, and InputQueue concurrently.
The daemon starts with zero workspaces and discovers running Antigravity
instances automatically via the Supervisor's reconciliation loop.
"""

import argparse
import asyncio
import logging
import os
import signal
import socket
import subprocess
import sys
import time
from contextlib import asynccontextmanager

import uvicorn

from agbridge.config import DEFAULT_HOST, DEFAULT_PORT, AUTH_ENABLED
from agbridge.auth import load_or_create_token, get_local_ip


def _check_native_deps():
    """
    Verify that macOS native dependencies are available.
    Must be called before any module that imports pyobjc.
    """
    try:
        import AppKit  # noqa: F401
        import ApplicationServices  # noqa: F401
    except ImportError:
        print("\n  ✗ 필수 의존성 누락: pyobjc-framework-Cocoa / pyobjc-framework-ApplicationServices")
        print()
        print("  이 서버는 macOS 네이티브 API에 의존합니다.")
        print("  올바른 가상 환경에서 실행해주세요:")
        print()
        print("    .venv/bin/python3 -m agbridge.main")
        print()
        print("  또는 pip install로 의존성을 설치하세요:")
        print()
        print("    pip install pyobjc-framework-Cocoa pyobjc-framework-ApplicationServices")
        print()
        sys.exit(1)

    import time
    from ApplicationServices import AXIsProcessTrustedWithOptions

    print(f"\n  Checking permissions for Python: {sys.executable}")

    # Accessibility 권한 체크 (Screen Recording은 더 이상 불필요)
    if not AXIsProcessTrustedWithOptions({"AXTrustedCheckOptionPrompt": True}):
        print("  WAITING: Please grant Accessibility permissions to this process in System Settings.")
        while not AXIsProcessTrustedWithOptions({"AXTrustedCheckOptionPrompt": False}):
            time.sleep(3)
    print("  ✓ Accessibility permissions verified.\n")


def _configure_logging(log_level_name):
    """Set up dual logging: console (user level) + file (DEBUG).

    Console output matches the original behavior.
    File output captures everything for post-mortem analysis.
    """
    from logging.handlers import RotatingFileHandler
    from agbridge.config import LOG_DIR, LOG_FILE, LOG_MAX_BYTES, LOG_BACKUP_COUNT

    os.makedirs(LOG_DIR, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Console handler — user-specified level (unchanged behavior)
    console = logging.StreamHandler()
    console.setLevel(getattr(logging, log_level_name))
    console.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    root.addHandler(console)

    # File handler — DEBUG (captures everything)
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s [%(threadName)s]: %(message)s",
    ))
    root.addHandler(file_handler)

    # Disable overly verbose third-party loggers
    logging.getLogger("watchdog").setLevel(logging.WARNING)
    logging.getLogger("fsevents").setLevel(logging.WARNING)
    logging.getLogger("watchdog.observers.fsevents").setLevel(logging.WARNING)

    logging.info("File logging enabled: %s (max %dMB × %d)",
                 LOG_FILE, LOG_MAX_BYTES // (1024 * 1024), LOG_BACKUP_COUNT)


def run():
    _check_native_deps()

    # Lazy imports — only after native deps are verified
    from agbridge.workspace_supervisor import WorkspaceSupervisor
    from agbridge.input_queue import InputQueue
    from agbridge.api import create_app
    from agbridge.actions.registry import build_default_registry

    parser = argparse.ArgumentParser(
        description="Antigravity Remote Bridge — Daemon Server"
    )
    parser.add_argument(
        "--host", default=DEFAULT_HOST,
        help=f"Bind host (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT,
        help=f"Bind port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    _configure_logging(args.log_level)

    # Disable system display sleep as long as this server daemon is running
    try:
        subprocess.Popen(
            ["caffeinate", "-d", "-w", str(os.getpid())],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        logging.info("Display sleep conditionally disabled (attached to PID %s).", os.getpid())
    except Exception as e:
        logging.warning("Failed to start caffeinate daemon to prevent display sleep: %s", e)

    # Initialize authentication token
    token = load_or_create_token()

    # Create multi-workspace infrastructure
    supervisor = WorkspaceSupervisor()
    action_registry = build_default_registry()
    input_queue = InputQueue(supervisor, action_registry)

    @asynccontextmanager
    async def lifespan(app):
        """Server lifecycle: startup → yield → shutdown."""
        await supervisor.initial_reconcile()
        supervisor_task = asyncio.create_task(supervisor.run())
        input_task = asyncio.create_task(input_queue.run())
        heartbeat_task = asyncio.create_task(supervisor._heartbeat_loop())
        yield
        supervisor_task.cancel()
        input_task.cancel()
        heartbeat_task.cancel()

    app = create_app(supervisor, input_queue, lifespan=lifespan)

    # Startup banner
    lan_ip = get_local_ip()
    print()
    print("╔══════════════════════════════════════════════════╗")
    print("║       Antigravity Remote Bridge  v0.3.0         ║")
    print("╚══════════════════════════════════════════════════╝")
    print(f"  Mode      : Multi-workspace (auto-discovery)")
    print(f"  Listen    : http://{args.host}:{args.port}")

    if AUTH_ENABLED and token:
        from agbridge.config import AUTH_TOKEN_FILE
        print(f"  Token     : {token}")
        print(f"  Token File: {AUTH_TOKEN_FILE}")
        print(f"  Connect   : http://{lan_ip}:{args.port}?token={token}")
    else:
        print("  Auth      : DISABLED")
        print(f"  Connect   : http://{lan_ip}:{args.port}")

    print()

    _ensure_port_available(args.port)

    from agbridge.config import KEEP_ALIVE_TIMEOUT

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level=args.log_level.lower(),
        timeout_keep_alive=KEEP_ALIVE_TIMEOUT,
    )


def _ensure_port_available(port):
    """
    Check if the port is already in use. If so, terminate the
    occupying process before proceeding.

    IMPORTANT: Only target processes that are LISTENING on the port.
    Connected clients (e.g. TUI WebSocket connections) must NOT be
    killed — they share the same port number but are in ESTABLISHED
    state, not LISTEN.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("", port))
        sock.close()
        return  # Port is free
    except OSError:
        sock.close()

    # Port is occupied — find only LISTEN-state PIDs
    pids = _find_listen_pids(port)

    if not pids:
        # No PIDs found but port is busy — likely TIME_WAIT.
        # Try SO_REUSEADDR and let uvicorn handle it.
        print(f"  ⚠ Port {port} is busy (no identifiable process — likely TIME_WAIT)")
        return

    my_pid = os.getpid()
    for pid in pids:
        if pid == my_pid:
            continue
        print(f"  ⚠ Port {port} occupied by PID {pid} — terminating...")
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            continue

    # Wait for port to become available
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("", port))
            sock.close()
            print(f"  ✓ Port {port} is now available.")
            return
        except OSError:
            sock.close()
            time.sleep(0.2)

    # Force kill as last resort
    for pid in pids:
        if pid == my_pid:
            continue
        print(f"  ⚠ PID {pid} did not terminate — sending SIGKILL...")
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    time.sleep(0.5)
    print(f"  ✓ Port {port} force-freed.")


def _find_listen_pids(port):
    """
    Find PIDs that are LISTENING on the given port.

    Uses ``lsof -i :PORT -sTCP:LISTEN`` to exclude connected clients
    (ESTABLISHED state) that happen to use the same port number.
    Returns a list of integer PIDs, or empty list if none found.
    """
    # Strategy 1: lsof with TCP state filter (most precise)
    try:
        out = subprocess.check_output(
            ["lsof", "-i", f":{port}", "-sTCP:LISTEN", "-t"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        if out:
            return [int(p.strip()) for p in out.split("\n") if p.strip().isdigit()]
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        pass

    # Strategy 2: lsof -i :PORT (parse output, filter LISTEN manually)
    try:
        out = subprocess.check_output(
            ["lsof", "-i", f":{port}"],
            stderr=subprocess.DEVNULL,
        ).decode()
        result = set()
        for line in out.strip().split("\n")[1:]:  # skip header
            parts = line.split()
            # lsof columns: COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME
            # NAME column contains "(LISTEN)" for listening sockets
            if len(parts) >= 2 and "(LISTEN)" in line:
                try:
                    result.add(int(parts[1]))
                except ValueError:
                    pass
        if result:
            return list(result)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    return []


if __name__ == "__main__":
    run()
