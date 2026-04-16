"""
agbridge.workspace.state_machine — Declarative workspace state machine

Replaces the scattered string-comparison state transitions in engine.py
with a single, declarative transition table.

States:
    INITIALIZING  — CDP connecting, first scrape pending
    IDLE          — Ready to accept prompts
    ACTIVE        — AI is generating a response
    ERROR         — Unrecoverable error detected

Events:
    idle_detected, gen_detected, empty_conversation,
    inject_started, error_detected, retry, dismiss
"""

import asyncio
import logging

logger = logging.getLogger("agbridge.workspace.state_machine")


# ── State Constants ──────────────────────────────────────────

INITIALIZING = "INITIALIZING"
IDLE = "IDLE"
ACTIVE = "ACTIVE"
ERROR = "ERROR"


# ── Transition Table ─────────────────────────────────────────

_TRANSITIONS = {
    (INITIALIZING, "idle_detected"):       IDLE,
    (INITIALIZING, "gen_detected"):        ACTIVE,
    (INITIALIZING, "empty_conversation"):  IDLE,

    (IDLE,         "gen_detected"):        ACTIVE,
    (IDLE,         "inject_started"):      ACTIVE,

    (ACTIVE,       "idle_detected"):       IDLE,
    (ACTIVE,       "error_detected"):      ERROR,

    (ERROR,        "retry"):               IDLE,
    (ERROR,        "dismiss"):             IDLE,
    (ERROR,        "idle_detected"):       IDLE,
}


class WorkspaceStateMachine:
    """Declarative state machine for workspace lifecycle.

    All valid transitions are declared in the transition table.
    Invalid transitions are logged and rejected.
    """

    def __init__(self):
        self._current = INITIALIZING
        self._listeners = []
        self._cv = None  # Lazy init — created on first wait_for_idle()

    @property
    def current(self):
        return self._current

    # ── Guard Methods ────────────────────────────────────────

    def can_inject(self):
        """Whether the workspace can accept a prompt injection."""
        return self._current == IDLE

    def can_cancel(self):
        """Whether generation can be cancelled."""
        return self._current == ACTIVE

    def can_retry(self):
        """Whether a retry is valid."""
        return self._current == ERROR

    def is_initializing(self):
        return self._current == INITIALIZING

    def is_idle(self):
        return self._current == IDLE

    def is_active(self):
        return self._current == ACTIVE

    def is_error(self):
        return self._current == ERROR

    # ── Transitions ──────────────────────────────────────────

    def transition(self, event):
        """Attempt a state transition.

        Args:
            event: Transition event name (e.g. "idle_detected").

        Returns:
            str or None: New state if transition succeeded, None if rejected.
        """
        key = (self._current, event)
        new_state = _TRANSITIONS.get(key)

        if new_state is None:
            logger.debug(
                "Transition rejected: %s + %s (no mapping)",
                self._current, event,
            )
            return None

        if new_state == self._current:
            return self._current

        old_state = self._current
        self._current = new_state
        logger.info(
            "State transition: %s → %s (event=%s)",
            old_state, new_state, event,
        )

        # Notify listeners
        for listener in self._listeners:
            try:
                listener(old_state, new_state, event)
            except Exception as e:
                logger.warning("State listener error: %s", e)

        # Notify CV waiters (for wait_for_idle)
        if new_state == IDLE:
            try:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    asyncio.create_task(self._notify_cv())
            except RuntimeError:
                pass  # No running event loop (e.g. test context)

        return new_state

    # ── Listener Registration ────────────────────────────────

    def on_change(self, callback):
        """Register a state change listener.

        Args:
            callback: def callback(old_state, new_state, event)
                Synchronous callback invoked on each transition.
        """
        self._listeners.append(callback)

    def remove_listener(self, callback):
        """Remove a previously registered listener."""
        self._listeners = [
            l for l in self._listeners if l is not callback
        ]

    # ── Wait Support ─────────────────────────────────────────

    async def wait_for_idle(self, timeout=15.0):
        """Wait until state is IDLE or ACTIVE.

        Args:
            timeout: Maximum wait time in seconds.

        Returns:
            bool: True if reached IDLE/ACTIVE within timeout.
        """
        if self._current in (IDLE, ACTIVE):
            return True

        if self._cv is None:
            self._cv = asyncio.Condition()

        import time
        start = time.monotonic()
        async with self._cv:
            while self._current == INITIALIZING:
                remaining = timeout - (time.monotonic() - start)
                if remaining <= 0:
                    return False
                try:
                    await asyncio.wait_for(
                        self._cv.wait(), timeout=remaining,
                    )
                except asyncio.TimeoutError:
                    return False
        return self._current in (IDLE, ACTIVE)

    async def _notify_cv(self):
        if self._cv is None:
            return
        async with self._cv:
            self._cv.notify_all()
