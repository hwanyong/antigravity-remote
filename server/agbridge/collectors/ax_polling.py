"""
agbridge.collectors.ax_polling — Per-workspace AX polling controller

Each Engine owns a PollController instance. poll_until() requires an
explicit controller reference, ensuring workspace isolation:
  - Engine A stop → only Engine A's active polls abort
  - Engine B continues unaffected

Architecture:
    Engine
    └── poll_controller: PollController
        ├── poll_until(pred, controller, ...)  — register, loop, deregister
        ├── shutdown()   — set stop flag, abort all active polls for this engine
        └── reset()      — clear stop flag (on engine start)

HW-level delays (keystroke timing, clipboard prep) are NOT managed here.
"""

import logging
import threading
import time

logger = logging.getLogger("agbridge.ax_polling")


class PollController:
    """Manages lifecycle of all active polling operations for one workspace.

    Thread-safe. Multiple poll_until() calls may run concurrently
    from different threads (InputQueue consumer, Engine poll, etc).
    """

    def __init__(self):
        self._stopped = threading.Event()
        self._active_count = 0
        self._lock = threading.Lock()

    @property
    def is_stopped(self):
        return self._stopped.is_set()

    @property
    def active_count(self):
        with self._lock:
            return self._active_count

    def shutdown(self):
        """Abort all active polling operations for this workspace.

        Called when the IDE window closes or Engine stops.
        Any running poll_until() bound to this controller will raise PollAborted.
        """
        self._stopped.set()
        logger.info(
            "PollController shutdown — aborting %d active poll(s)",
            self.active_count,
        )

    def reset(self):
        """Clear the stop flag, allowing new polling operations.

        Called when the Engine starts or reconnects.
        """
        self._stopped.clear()
        logger.info("PollController reset — polling enabled")

    def _register(self):
        with self._lock:
            self._active_count += 1

    def _deregister(self):
        with self._lock:
            self._active_count -= 1


class PollAborted(Exception):
    """Raised when poll_until() is aborted by PollController.shutdown()."""


class PollTimeout(Exception):
    """Raised when poll_until() exceeds its timeout."""


def poll_until(predicate, controller, interval=0.2, timeout=None, label=""):
    """Run predicate() every *interval* seconds until it returns truthy.

    Args:
        predicate:   callable returning falsy to continue, truthy to stop.
        controller:  PollController instance (workspace-scoped).
        interval:    seconds between polls (default 0.2).
        timeout:     max seconds before giving up (None = no limit).
        label:       human-readable tag for debug logging.

    Returns:
        The truthy value returned by predicate().

    Raises:
        PollAborted:  if controller.shutdown() was called.
        PollTimeout:  if timeout exceeded without predicate returning truthy.
    """
    controller._register()
    poll_count = 0
    start = time.monotonic()

    try:
        while True:
            if controller.is_stopped:
                raise PollAborted(f"[{label}] polling aborted by controller shutdown")

            if timeout is not None and (time.monotonic() - start) >= timeout:
                raise PollTimeout(
                    f"[{label}] polling timed out after {timeout:.1f}s "
                    f"({poll_count} attempts)"
                )

            result = predicate()
            if result:
                if poll_count > 0:
                    logger.debug(
                        "[%s] resolved after %d polls (%.1fs)",
                        label, poll_count, poll_count * interval,
                    )
                return result

            poll_count += 1
            if poll_count % 50 == 0:
                logger.warning(
                    "[%s] still polling after %d attempts (%.1fs)",
                    label, poll_count, poll_count * interval,
                )
            time.sleep(interval)
    finally:
        controller._deregister()
