"""
agbridge.window_discovery — Stateless CG window discovery and path resolution

Pure functions for discovering Antigravity IDE windows via macOS CG API
and resolving workspace names to filesystem paths via workspaceStorage.

No mutable state — every call reconstructs the full picture from OS APIs.
Used by WorkspaceSupervisor in its reconciliation loop.
"""

import json
import logging
import os
import subprocess
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

import Quartz

from agbridge.config import (
    ANTIGRAVITY_CMD,
    OWNER_NAME,
    TITLE_SEPARATOR,
    WORKSPACE_STORAGE_DIR,
)

logger = logging.getLogger("agbridge.window_discovery")


@dataclass(frozen=True)
class DiscoveredWindow:
    """Immutable snapshot of a single Antigravity workspace window."""
    window_id: int
    pid: int
    workspace_name: str
    workspace_path: str


def discover_windows() -> list[DiscoveredWindow]:
    """
    Scan CG windows and resolve each to a workspace path.

    Returns:
        List of discovered workspace windows with resolved paths.
        Non-workspace windows (e.g. "Launchpad") are excluded.
    """
    path_cache = _build_path_cache()
    cg_windows = _scan_cg_windows()

    results = []
    for wid, info in cg_windows.items():
        path = path_cache.get(info["workspace_name"])
        if not path:
            continue
        results.append(DiscoveredWindow(
            window_id=wid,
            pid=info["pid"],
            workspace_name=info["workspace_name"],
            workspace_path=path,
        ))

    logger.debug(
        "Discovery: CG=%d, resolved=%d",
        len(cg_windows), len(results),
    )
    return results


def get_window_states():
    """
    Query CG + AX APIs for current window visual states.

    Returns:
        dict: {cg_window_id → "ACTIVE" | "OPEN" | "MINIMIZED"}
    """
    from ApplicationServices import (
        AXUIElementCreateApplication,
        AXUIElementCopyAttributeValue,
        kAXWindowsAttribute,
    )

    states = {}
    windows = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionAll | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID,
    )
    if not windows:
        return states

    ag_windows = {}
    ag_pid = None
    for w in windows:
        if w.get("kCGWindowOwnerName") != OWNER_NAME:
            continue
        title = w.get("kCGWindowName", "")
        if not title:
            continue
        wid = w["kCGWindowNumber"]
        ag_pid = w["kCGWindowOwnerPID"]
        on_screen = w.get("kCGWindowIsOnscreen", False)
        ag_windows[wid] = {"title": title, "on_screen": on_screen}
        states[wid] = "OPEN" if on_screen else "MINIMIZED"

    if ag_pid:
        try:
            ax_app = AXUIElementCreateApplication(ag_pid)
            err, wins = AXUIElementCopyAttributeValue(ax_app, kAXWindowsAttribute, None)
            if err == 0 and wins:
                for ax_win in wins:
                    _, ax_title = AXUIElementCopyAttributeValue(ax_win, "AXTitle", None)
                    _, is_main = AXUIElementCopyAttributeValue(ax_win, "AXMain", None)
                    if is_main and ax_title:
                        for wid, info in ag_windows.items():
                            if info["title"] == ax_title:
                                states[wid] = "ACTIVE"
                                break
        except Exception:
            pass

    return states


def launch_ide(path):
    """
    Launch a new Antigravity IDE instance for the given workspace path.

    Returns:
        int | None: PID of the launched process, or None on failure.
    """
    try:
        proc = subprocess.Popen([ANTIGRAVITY_CMD, "--disable-workspace-trust", path])
        logger.info("IDE launched: PID=%d path=%s", proc.pid, path)
        return proc.pid
    except FileNotFoundError:
        logger.error("Antigravity command not found: %s", ANTIGRAVITY_CMD)
        return None


# ── Internal helpers ─────────────────────────────────────────


def _scan_cg_windows():
    """
    Discover all titled Antigravity windows via CG Window API.

    Returns:
        dict: {cg_window_id → {"pid": int, "title": str, "workspace_name": str}}
    """
    result = {}
    windows = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionAll | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID,
    )
    if not windows:
        return result

    for w in windows:
        if w.get("kCGWindowOwnerName") != OWNER_NAME:
            continue
        title = w.get("kCGWindowName", "")
        if not title:
            continue

        wid = w["kCGWindowNumber"]
        pid = w["kCGWindowOwnerPID"]
        workspace_name = title.split(TITLE_SEPARATOR)[0]

        result[wid] = {
            "pid": pid,
            "title": title,
            "workspace_name": workspace_name,
        }

    return result


def _build_path_cache():
    """
    Build basename → full_path mapping from Antigravity's workspaceStorage.

    Reads ~/Library/Application Support/Antigravity/User/workspaceStorage/*/workspace.json
    Each file contains: {"folder": "file:///Users/..."}

    Returns:
        dict: {workspace_basename → absolute_path}
    """
    cache = {}
    if not os.path.isdir(WORKSPACE_STORAGE_DIR):
        return cache

    for entry in os.listdir(WORKSPACE_STORAGE_DIR):
        ws_json = os.path.join(WORKSPACE_STORAGE_DIR, entry, "workspace.json")
        if not os.path.isfile(ws_json):
            continue

        try:
            with open(ws_json, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        folder_uri = data.get("folder", "")
        if not folder_uri:
            continue

        parsed = urlparse(folder_uri)
        full_path = unquote(parsed.path)
        basename = os.path.basename(full_path)

        if basename:
            cache[basename] = full_path

    return cache
