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
        import Quartz  # noqa: F401
        import AppKit  # noqa: F401
        import ApplicationServices  # noqa: F401
    except ImportError:
        print("\n  ✗ 필수 의존성 누락: pyobjc-framework-Quartz")
        print()
        print("  이 서버는 macOS 네이티브 API에 의존합니다.")
        print("  올바른 가상 환경에서 실행해주세요:")
        print()
        print("    .venv/bin/python3 -m agbridge.main")
        print()
        print("  또는 pip install로 의존성을 설치하세요:")
        print()
        print("    pip install pyobjc-framework-Quartz pyobjc-framework-Cocoa pyobjc-framework-ApplicationServices")
        print()
        sys.exit(1)

    import time
    from ApplicationServices import AXIsProcessTrustedWithOptions
    import Quartz

    print(f"\n  Checking permissions for Python: {sys.executable}")

    # 1. Accessibility 권한 체크
    if not AXIsProcessTrustedWithOptions({"AXTrustedCheckOptionPrompt": True}):
        print("  WAITING: Please grant Accessibility permissions to this process in System Settings.")
        while not AXIsProcessTrustedWithOptions({"AXTrustedCheckOptionPrompt": False}):
            time.sleep(3)
    print("  ✓ Accessibility permissions verified.")

    # 2. Screen Recording 권한 체크
    def check_screen_recording():
        if hasattr(Quartz, "CGPreflightScreenCaptureAccess"):
            return Quartz.CGPreflightScreenCaptureAccess()
            
        # Fallback for old macOS: 윈도우 타이틀 휴리스틱
        windows = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionAll | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID,
        )
        if not windows:
            return False
            
        import os
        my_pid = os.getpid()
        system_apps = ("WindowServer", "Dock", "ControlCenter", "SystemUIServer", "Spotlight", "loginwindow", "NotificationCenter")
        
        visible = 0
        titled = 0
        ag_visible = 0
        ag_titled = 0
        
        for w in windows:
            if w.get("kCGWindowOwnerPID") == my_pid:
                continue
            if w.get("kCGWindowOwnerName", "") in system_apps:
                continue
                
            visible += 1
            if w.get("kCGWindowName"):
                titled += 1
                
            if w.get("kCGWindowOwnerName") == "Antigravity":
                ag_visible += 1
                if w.get("kCGWindowName"):
                    ag_titled += 1
                    
        # Antigravity 창이 켜져있는데도 타이틀을 하나도 못 읽어온다면 권한 차단됨
        if ag_visible > 0 and ag_titled == 0:
            return False
        # Antigravity는 없지만 타사 창이 있는데 전부 제목이 없다면 권한 차단 의심
        if visible > 0 and titled == 0:
            return False
            
        return True

    if not check_screen_recording():
        if hasattr(Quartz, "CGRequestScreenCaptureAccess"):
            Quartz.CGRequestScreenCaptureAccess()
            
        print("  WAITING: Please grant Screen Recording permissions to this process in System Settings.")
        while not check_screen_recording():
            time.sleep(3)
    print("  ✓ Screen Recording permissions verified.\n")

def run():
    _check_native_deps()

    # Lazy imports — only after native deps are verified
    from agbridge.workspace_supervisor import WorkspaceSupervisor
    from agbridge.input_queue import InputQueue
    from agbridge.api import create_app

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

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

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
    input_queue = InputQueue(supervisor)

    @asynccontextmanager
    async def lifespan(app):
        """Server lifecycle: startup → yield → shutdown."""
        await supervisor.initial_reconcile()
        supervisor_task = asyncio.create_task(supervisor.run())
        input_task = asyncio.create_task(input_queue.run())
        yield
        supervisor_task.cancel()
        input_task.cancel()

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

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level=args.log_level.lower(),
    )


def _ensure_port_available(port):
    """
    Check if the port is already in use. If so, terminate the
    occupying process before proceeding.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("", port))
        sock.close()
        return  # Port is free
    except OSError:
        sock.close()

    # Port is occupied — try multiple strategies to find PIDs
    pids = _find_port_pids(port)

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


def _find_port_pids(port):
    """
    Find PIDs occupying the given port using multiple strategies.
    Returns a list of integer PIDs, or empty list if none found.
    """
    # Strategy 1: lsof -ti :PORT
    pids = _try_lsof(["-ti", f":{port}"])
    if pids:
        return pids

    # Strategy 2: lsof -ti TCP:PORT
    pids = _try_lsof(["-ti", f"TCP:{port}"])
    if pids:
        return pids

    # Strategy 3: lsof -i :PORT (parse PID column)
    try:
        out = subprocess.check_output(
            ["lsof", "-i", f":{port}"],
            stderr=subprocess.DEVNULL,
        ).decode()
        result = set()
        for line in out.strip().split("\n")[1:]:  # skip header
            parts = line.split()
            if len(parts) >= 2:
                try:
                    result.add(int(parts[1]))
                except ValueError:
                    pass
        if result:
            return list(result)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    return []


def _try_lsof(args):
    """Run lsof with given args, return list of PIDs or empty list."""
    try:
        out = subprocess.check_output(
            ["lsof"] + args,
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        if not out:
            return []
        return [int(p.strip()) for p in out.split("\n") if p.strip().isdigit()]
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        return []


if __name__ == "__main__":
    run()
