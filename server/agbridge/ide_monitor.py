"""
agbridge.ide_monitor — Antigravity IDE per-window lifecycle management

In the multi-window model, each IDEMonitor is bound to one specific
workspace window via AXTitle matching. The same PID may host multiple
IDEMonitor instances (one per workspace window).

Provides:
- AX window access for the bound workspace window
- Process liveness checking
- Window focusing for InputQueue write operations
- IDE window closing (not full process termination)
"""

import signal
import time

from AppKit import NSRunningApplication
from ApplicationServices import (
    AXUIElementCreateApplication,
    AXUIElementSetAttributeValue,
    AXUIElementCopyAttributeValue,
    AXUIElementPerformAction,
    kAXWindowsAttribute,
)

import logging

logger = logging.getLogger("agbridge.ide_monitor")


class IDEMonitor:
    """Manages a single Antigravity workspace window identified by PID + title."""

    def __init__(self, pid, target_title=None):
        """
        Initialize with a known PID and optional target window title.

        Args:
            pid: Process ID of the running Antigravity instance.
            target_title: Workspace basename to match AXTitle prefix.
                         If None, binds to the first available window.
        """
        self.pid = pid
        self.target_title = target_title
        self.app = None           # NSRunningApplication
        self.ax_app = None        # AXUIElement
        self.window = None        # Single AX window (not list)
        self.windows = []         # Compat: list with single window

        self._connect(pid)

    @property
    def is_connected(self):
        """Return whether the IDE AX connection is active."""
        return self.ax_app is not None

    def _connect(self, pid):
        """
        Set up AX pointers for the given PID and bind to the target window.

        Filters AX windows by AXTitle prefix matching against target_title.
        """
        ns_app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if not ns_app:
            logger.warning("PID %d: NSRunningApplication not found", pid)
            return

        ax_app = AXUIElementCreateApplication(pid)
        AXUIElementSetAttributeValue(
            ax_app, "AXManualAccessibility", True
        )

        err, wins = AXUIElementCopyAttributeValue(
            ax_app, kAXWindowsAttribute, None
        )
        if err != 0 or not wins or len(wins) == 0:
            logger.warning("PID %d: no AX windows found (err=%d)", pid, err)
            self.app = ns_app
            self.ax_app = ax_app
            return

        self.app = ns_app
        self.ax_app = ax_app

        # Find the target window by AXTitle prefix match
        matched = self._find_target_window(wins)
        if matched:
            self.window = matched
            self.windows = [matched]
            logger.info(
                "IDEMonitor connected: PID=%d target='%s' (matched)",
                pid, self.target_title,
            )
        else:
            # Fallback: use first window
            self.window = wins[0]
            self.windows = [wins[0]]
            logger.warning(
                "IDEMonitor: PID=%d target='%s' not found, using first window",
                pid, self.target_title,
            )

    def _find_target_window(self, ax_windows):
        """
        Find the AX window whose title starts with target_title.

        Args:
            ax_windows: List of AX window elements.

        Returns:
            AX window element, or None if not found.
        """
        if not self.target_title:
            return None

        for w in ax_windows:
            _, title = AXUIElementCopyAttributeValue(w, "AXTitle", None)
            if title and title.startswith(self.target_title):
                return w

        return None

    def disconnect(self):
        """Release the IDE connection."""
        self.app = None
        self.ax_app = None
        self.window = None
        self.windows = []

    def check_alive(self):
        """
        Verify that the captured PID is still running.

        Returns:
            bool: True if the process is alive.
        """
        if self.pid is None:
            return False
        try:
            import os as _os
            _os.kill(self.pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False

    def refresh_windows(self):
        """Refresh the bound window from the AX window list."""
        if not self.ax_app:
            return

        err, wins = AXUIElementCopyAttributeValue(
            self.ax_app, kAXWindowsAttribute, None
        )
        if err != 0 or not wins:
            return

        matched = self._find_target_window(wins)
        if matched:
            self.window = matched
            self.windows = [matched]

    def focus_window(self):
        """
        Bring the target workspace window to the foreground.

        Uses NSRunningApplication.activateWithOptions() for reliable
        foreground activation, then AXRaise on the bound window.
        """
        if self.app:
            from agbridge.config import NS_ACTIVATE_OPTIONS
            self.app.activateWithOptions_(NS_ACTIVATE_OPTIONS)

        if self.window:
            try:
                AXUIElementPerformAction(self.window, "AXRaise")
            except Exception:
                pass

    def close_ide(self):
        """
        Close the workspace window (not terminate the entire process).

        Uses AXPress on the close button, or falls back to SIGTERM.
        """
        if self.window:
            try:
                _, close_btn = AXUIElementCopyAttributeValue(
                    self.window, "AXCloseButton", None
                )
                if close_btn:
                    AXUIElementPerformAction(close_btn, "AXPress")
                    logger.info("Window close button pressed for '%s'", self.target_title)
                    return
            except Exception:
                pass

        # Fallback: terminate process (legacy behavior)
        if self.pid is None:
            return

        import os as _os
        try:
            _os.kill(self.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass

        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if not self.check_alive():
                break
            time.sleep(0.2)

        if self.check_alive():
            try:
                _os.kill(self.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

        self.disconnect()
