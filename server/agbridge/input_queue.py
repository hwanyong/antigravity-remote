"""
agbridge.input_queue — Serialized write operations (Refactored)

All write operations execute via CDPBridge — no OS-level focus needed.
Operations are serialized to prevent concurrent DOM mutations.

After refactoring: _execute_cdp's 250-line if-else chain is replaced by
a single ActionRegistry.dispatch() call.
"""

import asyncio
import logging
import time

logger = logging.getLogger("agbridge.input_queue")


class InputJob:
    """A single write operation awaiting execution."""

    __slots__ = ("workspace_id", "action", "params", "result", "created_at")

    def __init__(self, workspace_id, action, params):
        self.workspace_id = workspace_id
        self.action = action
        self.params = params
        self.result = asyncio.get_event_loop().create_future()
        self.created_at = time.monotonic()


class InputQueue:
    """Serializes all write operations across workspaces.

    Consumer loop: dequeue → dispatch via ActionRegistry → next.
    """

    def __init__(self, supervisor, action_registry):
        """
        Args:
            supervisor: WorkspaceSupervisor — resolves workspace_id → Engine.
            action_registry: ActionRegistry — dispatches actions to handlers.
        """
        self._queue = asyncio.Queue()
        self._supervisor = supervisor
        self._action_registry = action_registry
        self._running = False

    async def enqueue(self, workspace_id, action, params):
        """Submit a write job and await its result.

        Returns:
            dict: {ok: bool, ...} result from the action handler.
        """
        job = InputJob(workspace_id, action, params)
        await self._queue.put(job)
        return await job.result

    async def run(self):
        """Consumer loop — runs as a background asyncio task."""
        self._running = True
        logger.info("InputQueue started")

        while self._running:
            job = await self._queue.get()

            engine = self._supervisor.get(job.workspace_id)
            if not engine:
                job.result.set_result({
                    "ok": False,
                    "error": f"workspace '{job.workspace_id}' no longer exists",
                })
                self._queue.task_done()
                continue

            if not engine.cdp or not engine.cdp.is_connected:
                job.result.set_result({
                    "ok": False,
                    "error": "CDP not connected",
                })
                self._queue.task_done()
                continue

            logger.info(
                "JOB_START ws=%s action=%s params=%s",
                job.workspace_id, job.action, _safe_params(job.params),
            )

            try:
                # Dispatch through ActionRegistry — replaces 250-line if-else
                action_result = await self._action_registry.dispatch(
                    job.action, engine.ctx, job.params,
                )
                result = action_result.to_dict()
                job.result.set_result(result)

                elapsed = time.monotonic() - job.created_at
                if action_result.ok:
                    logger.info(
                        "JOB_OK ws=%s action=%s elapsed=%.2fs",
                        job.workspace_id, job.action, elapsed,
                    )
                else:
                    logger.warning(
                        "JOB_REJECTED ws=%s action=%s elapsed=%.2fs reason=%s",
                        job.workspace_id, job.action, elapsed,
                        action_result.error or "returned false",
                    )

            except Exception as e:
                elapsed = time.monotonic() - job.created_at
                logger.error(
                    "JOB_FAILED ws=%s action=%s elapsed=%.2fs error=%s",
                    job.workspace_id, job.action, elapsed, e,
                )
                _emit_job_diagnostic(job, engine, e, elapsed)
                job.result.set_result({"ok": False, "error": str(e)})

            finally:
                self._queue.task_done()

    def get_last_prompt(self, workspace_id):
        """Return the last prompt text sent for a workspace."""
        engine = self._supervisor.get(workspace_id)
        if engine and hasattr(engine, "ctx"):
            return engine.ctx.prompt_history.last_sent
        return ""

    def stop(self):
        """Signal the consumer loop to stop."""
        self._running = False


# ── Module-level helpers ─────────────────────────────────────

_SENSITIVE_KEYS = frozenset({"token", "password", "secret", "api_key"})


def _safe_params(params):
    """Return params dict with sensitive values masked for logging."""
    if not isinstance(params, dict):
        return params
    result = {}
    for key, value in params.items():
        if key in _SENSITIVE_KEYS:
            result[key] = "***"
        else:
            result[key] = value
    return result


def _emit_job_diagnostic(job, engine, error, elapsed):
    """Emit a diagnostic record for a failed job."""
    from agbridge.diagnostics import get_recorder
    import traceback

    get_recorder().record(
        "job_failed",
        label=job.action,
        job_context={
            "action": job.action,
            "params": job.params,
            "workspace_id": job.workspace_id,
        },
        extra={
            "error": str(error),
            "error_type": type(error).__name__,
            "traceback": traceback.format_exc(),
            "elapsed_seconds": round(elapsed, 3),
            "engine_state": engine.current_state,
            "cdp_connected": engine.cdp.is_connected if engine.cdp else False,
        },
    )
