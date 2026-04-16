"""
agbridge.window_discovery — Stateless AX-based window discovery and path resolution

Pure functions for discovering Antigravity IDE windows via macOS AX API
and resolving workspace names to filesystem paths via workspaceStorage.

No dependency on CGWindowListCopyWindowInfo — requires only Accessibility
permission (no Screen Recording).

No mutable state — every call reconstructs the full picture from OS APIs.
Used by WorkspaceSupervisor in its reconciliation loop.
"""

import json
import logging
import os
import subprocess
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

from AppKit import NSWorkspace
from ApplicationServices import (
    AXUIElementCreateApplication,
    AXUIElementSetAttributeValue,
    AXUIElementCopyAttributeValue,
    kAXWindowsAttribute,
)

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
    pid: int
    workspace_name: str
    workspace_path: str


def discover_windows(fallback_paths=None) -> list[DiscoveredWindow]:
    """
    Scan AX windows and resolve each to a workspace path.

    Uses NSWorkspace for PID discovery and AX API for window titles.
    Requires only Accessibility permission — no Screen Recording.

    Args:
        fallback_paths: Optional dict of basename → path mappings to supplement
                        the workspaceStorage cache (resolves IDE launch race conditions).

    Returns:
        List of discovered workspace windows with resolved paths.
        Non-workspace windows (e.g. "Launchpad") are excluded.
    """
    path_cache = _build_path_cache()
    if fallback_paths:
        path_cache.update(fallback_paths)

    ax_windows = _scan_ax_windows(known_workspaces=set(path_cache.keys()))

    results = []
    for key, info in ax_windows.items():
        path = path_cache.get(info["workspace_name"])
        if not path:
            continue
        results.append(DiscoveredWindow(
            pid=info["pid"],
            workspace_name=info["workspace_name"],
            workspace_path=path,
        ))

    logger.debug(
        "Discovery: AX=%d, resolved=%d",
        len(ax_windows), len(results),
    )
    return results


def get_window_states(known_workspaces=None):
    """
    Query AX API for current window visual states.

    Uses AXMinimized and AXMain attributes — requires only Accessibility
    permission, no Screen Recording.

    Returns:
        dict: {workspace_name → "ACTIVE" | "OPEN" | "MINIMIZED"}
    """
    from agbridge.config import OWNER_NAME, TITLE_SEPARATOR
    states = {}

    for pid in _get_ag_pids():
        ax_app = AXUIElementCreateApplication(pid)
        AXUIElementSetAttributeValue(ax_app, "AXManualAccessibility", True)

        err, wins = AXUIElementCopyAttributeValue(
            ax_app, kAXWindowsAttribute, None
        )
        if err != 0 or not wins:
            continue

        for ax_win in wins:
            _, title = AXUIElementCopyAttributeValue(ax_win, "AXTitle", None)
            if not title:
                continue

            _, is_main = AXUIElementCopyAttributeValue(ax_win, "AXMain", None)
            _, is_minimized = AXUIElementCopyAttributeValue(
                ax_win, "AXMinimized", None
            )

            ws_name = _parse_workspace_name(title, known_workspaces)

            if is_minimized:
                states[ws_name] = "MINIMIZED"
            elif is_main:
                states[ws_name] = "ACTIVE"
            else:
                states[ws_name] = "OPEN"

    return states


def launch_ide(path, port=None):
    """
    Launch a new Antigravity IDE instance with CDP enabled.

    Args:
        path: Workspace directory path.
        port: CDP debugging port. If None, uses CDP_DIRECT_PORT.

    Returns:
        int | None: PID of the launched process, or None on failure.
    """
    from agbridge.config import CDP_LAUNCH_FLAGS_TEMPLATE, CDP_DIRECT_PORT

    if port is None:
        port = CDP_DIRECT_PORT

    flags = [f.format(port=port) for f in CDP_LAUNCH_FLAGS_TEMPLATE]
    cmd = [ANTIGRAVITY_CMD, "--disable-workspace-trust"] + flags + [path]
    try:
        proc = subprocess.Popen(cmd)
        logger.info("IDE launched (CDP port=%d): PID=%d path=%s", port, proc.pid, path)
        return proc.pid
    except FileNotFoundError:
        logger.error("Antigravity command not found: %s", ANTIGRAVITY_CMD)
        return None


# ── Internal helpers ─────────────────────────────────────────

def _get_ag_pids():
    """Stateless lookup of target process PIDs via WindowServer.
    Bypasses NSWorkspace which requires an active NSRunLoop to update."""
    from Quartz import CGWindowListCopyWindowInfo, kCGWindowListOptionAll, kCGNullWindowID
    wins = CGWindowListCopyWindowInfo(kCGWindowListOptionAll, kCGNullWindowID)
    pids = set()
    for w in wins:
        if w.get("kCGWindowOwnerName") == OWNER_NAME:
            pids.add(w.get("kCGWindowOwnerPID"))
    return pids

def _parse_workspace_name(title: str, known_workspaces: set = None) -> str:
    """Extract workspace name from window title, prioritizing known bases."""
    parts = [p.strip() for p in title.split(TITLE_SEPARATOR)]
    if known_workspaces:
        for part in reversed(parts):
            if part in known_workspaces:
                return part
    # Default VS Code title format ends with "— AppName", so workspace is second-to-last
    if len(parts) >= 2:
        return parts[-2]
    return parts[0]


def _scan_ax_windows(known_workspaces: set = None):
    """
    Discover all titled Antigravity windows via AX API.

    Uses NSWorkspace for PID discovery and AXUIElement for window
    attribute access.  Requires only Accessibility permission.

    Returns:
        dict: {(pid, workspace_name) → {"pid": int, "title": str, "workspace_name": str}}
    """
    result = {}

    for pid in _get_ag_pids():
        ax_app = AXUIElementCreateApplication(pid)
        AXUIElementSetAttributeValue(ax_app, "AXManualAccessibility", True)

        err, wins = AXUIElementCopyAttributeValue(
            ax_app, kAXWindowsAttribute, None
        )
        if err != 0 or not wins:
            continue

        for ax_win in wins:
            _, title = AXUIElementCopyAttributeValue(ax_win, "AXTitle", None)
            if not title:
                continue

            workspace_name = _parse_workspace_name(title, known_workspaces)

            result[(pid, workspace_name)] = {
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
