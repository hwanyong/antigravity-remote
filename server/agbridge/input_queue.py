"""
agbridge.input_queue — Serialized CDP write operations

All write operations execute via CDPBridge — no OS-level focus needed.
Operations are still serialized to prevent concurrent DOM mutations
that could interfere with each other (e.g., dropdown → click).

Event-driven: DOM changes from write operations are automatically
detected by MutationObserver → Runtime.bindingCalled → Engine.
No forced re-scrape needed.
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
    """
    Serializes all write operations across workspaces.

    Consumer loop: dequeue → execute via CDP → next.
    No focus management needed — CDP operations run in the background.
    """

    def __init__(self, supervisor):
        """
        Args:
            supervisor: WorkspaceSupervisor instance — resolves workspace_id → Engine.
        """
        self._queue = asyncio.Queue()
        self._supervisor = supervisor
        self._running = False
        self._undo_prompt_cache = {}
        self._last_prompt_cache = {}   # workspace_id → last sent prompt text

    async def enqueue(self, workspace_id, action, params):
        """
        Submit a write job and await its result.

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
                result = await self._execute_cdp(engine, job)
                job.result.set_result(result)

                elapsed = time.monotonic() - job.created_at
                ok = result.get("ok", False) if isinstance(result, dict) else False
                if ok:
                    logger.info(
                        "JOB_OK ws=%s action=%s elapsed=%.2fs",
                        job.workspace_id, job.action, elapsed,
                    )
                else:
                    error = result.get("error", "") if isinstance(result, dict) else ""
                    logger.warning(
                        "JOB_REJECTED ws=%s action=%s elapsed=%.2fs reason=%s",
                        job.workspace_id, job.action, elapsed, error or "returned false",
                    )

                # Event-driven: DOM changes from write operations are
                # automatically detected by MutationObserver and trigger
                # selective re-scraping via Runtime.bindingCalled.

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

    async def _execute_cdp(self, engine, job):
        """CDP-based action dispatcher."""
        from agbridge.collectors import cdp_actions

        bridge = engine.cdp

        if job.action == "inject_prompt":
            text = job.params.get("content", "")
            if not text:
                return {"ok": False, "error": "content is required"}
            if engine.current_state == engine.ACTIVE:
                return {"ok": False, "error": "agent is currently generating"}
            self._last_prompt_cache[job.workspace_id] = text
            ok = await cdp_actions.inject_prompt(bridge, text)
            return {"ok": ok}

        if job.action == "accept_all":
            ok = await cdp_actions.press_accept_all(bridge)
            return {"ok": ok, "error": None if ok else "button not available"}

        if job.action == "reject_all":
            ok = await cdp_actions.press_reject_all(bridge)
            return {"ok": ok, "error": None if ok else "button not available"}

        if job.action == "cancel":
            ok = await cdp_actions.press_cancel(bridge)
            return {"ok": ok, "error": None if ok else "cancel button not found"}

        if job.action == "select_model":
            model_name = job.params.get("model", "")
            if not model_name:
                return {"ok": False, "error": "model name is required"}
            ok = await cdp_actions.select_model(bridge, model_name)
            return {"ok": ok}

        if job.action == "select_mode":
            mode_name = job.params.get("mode", "")
            if not mode_name:
                return {"ok": False, "error": "mode name is required"}
            ok = await cdp_actions.select_mode(bridge, mode_name)
            return {"ok": ok}

        if job.action == "new_conversation":
            ok = await cdp_actions.click_new_conversation(bridge)
            return {"ok": ok}

        if job.action == "retry":
            ok = await cdp_actions.press_retry(bridge)
            return {"ok": ok, "error": None if ok else "retry button not found"}

        if job.action == "dismiss_error":
            ok = await cdp_actions.press_dismiss(bridge)
            return {"ok": ok, "error": None if ok else "dismiss button not found"}

        if job.action == "press_deny":
            ok = await cdp_actions.press_deny(bridge)
            return {"ok": ok, "error": None if ok else "Deny button not found"}

        if job.action == "press_allow":
            ok = await cdp_actions.press_allow(bridge)
            return {"ok": ok, "error": None if ok else "Allow button not found"}

        if job.action in ("press_allow_workspace", "press_allow_globally", "press_run_sandbox"):
            item_map = {
                "press_allow_workspace": "Allow for Workspace",
                "press_allow_globally": "Allow Globally",
                "press_run_sandbox": "Run in sandbox",
            }
            ok = await cdp_actions.press_permission_dropdown_item(
                bridge, item_map[job.action]
            )
            error_msg = f"{item_map[job.action]} not found"
            return {"ok": ok, "error": None if ok else error_msg}

        if job.action == "list_models":
            models_info = engine.store.get("models_info") or {}
            models = models_info.get("available_models", [])
            if not models:
                models = await cdp_actions.list_available_models(bridge)
                if models:
                    models_info["available_models"] = models
                    engine.store.update("models_info", models_info)
            return {"ok": True, "models": models}

        if job.action == "list_modes":
            models_info = engine.store.get("models_info") or {}
            modes = models_info.get("available_modes", [])
            if not modes:
                modes = await cdp_actions.list_available_modes(bridge)
                if modes:
                    models_info["available_modes"] = modes
                    engine.store.update("models_info", models_info)
            return {"ok": True, "modes": modes}

        if job.action == "list_conversations":
            convs = await cdp_actions.list_conversations(bridge)
            return {"ok": True, "conversations": convs}

        if job.action == "select_conversation":
            title = job.params.get("title", "")
            if not title:
                return {"ok": False, "error": "title is required"}
            ok = await cdp_actions.select_conversation_by_title(bridge, title)
            return {"ok": ok}

        if job.action == "delete_conversation":
            title = job.params.get("title", "")
            if not title:
                return {"ok": False, "error": "title is required"}
            ok = await cdp_actions.delete_conversation(bridge, title)
            if not ok:
                return {"ok": False, "error": "delete icon not found"}
            # Wait briefly for DOM update, then return refreshed list
            await asyncio.sleep(0.3)
            convs = await cdp_actions.list_conversations(bridge)
            return {"ok": True, "conversations": convs}

        if job.action == "expand_conversations":
            await cdp_actions.expand_conversations(bridge)
            convs = await cdp_actions.list_conversations(bridge)
            return {"ok": True, "conversations": convs}

        if job.action == "close_conversation_panel":
            ok = await cdp_actions.close_conversation_panel(bridge)
            return {"ok": ok}

        if job.action == "refresh_models":
            models = await cdp_actions.list_available_models(bridge)
            modes = await cdp_actions.list_available_modes(bridge)
            existing = engine.store.get("models_info") or {}
            existing["available_models"] = models
            existing["available_modes"] = modes
            engine.store.update("models_info", existing)
            return {"ok": True, "models": models, "modes": modes}

        if job.action == "undo_to_prompt":
            index = job.params.get("message_index")
            if index is None:
                return {"ok": False, "error": "message_index is required"}

            # Pre-cache prompt provided straight from TUI widget state
            prompt_text = job.params.get("prompt_text", "")
            turn_idx = job.params.get("turn_idx", -1)
            
            self._undo_prompt_cache[job.workspace_id] = {
                "prompt_text": prompt_text,
                "turn_idx": turn_idx,
            }

            ok = await cdp_actions.press_undo_for_message(bridge, index)
            if not ok:
                self._undo_prompt_cache.pop(job.workspace_id, None)
                return {"ok": False, "error": "undo button not found"}

            # Wait for dialog (CDP: short sleep + check, no poll_until)
            for _ in range(20):
                dialog_data = await cdp_actions.detect_confirm_undo_dialog(bridge)
                if dialog_data:
                    return {"ok": True, "dialog": dialog_data}
                await asyncio.sleep(0.1)
            return {"ok": False, "error": "undo dialog not appeared"}

        if job.action == "confirm_undo":
            ok = await cdp_actions.press_confirm_undo(bridge)
            if not ok:
                return {"ok": False, "error": "confirm button not found"}

            cached_undo = self._undo_prompt_cache.pop(job.workspace_id, {})
            restored_prompt = cached_undo.get("prompt_text", "")
            turn_idx = cached_undo.get("turn_idx", -1)

            # Use pre-cached prompt and inject it back to IDE
            if restored_prompt:
                await cdp_actions.inject_advanced_prompt(bridge, restored_prompt)
            else:
                await cdp_actions.clear_message_input(bridge)

            # Manually truncate cache to instantly reflect deletion
            if turn_idx >= 0 and engine:
                agent_data = engine.truncate_turn_cache(turn_idx)
            else:
                from agbridge.collectors import dom_scraper
                agent_data = await dom_scraper.collect_agent_panel(bridge)

            return {
                "ok": True,
                "agent_update": agent_data,
                "restored_prompt": restored_prompt,
            }

        if job.action == "cancel_undo":
            self._undo_prompt_cache.pop(job.workspace_id, None)
            ok = await cdp_actions.press_cancel_undo(bridge)
            return {"ok": ok, "error": None if ok else "cancel button not found"}

        if job.action == "scroll_conversation":
            from agbridge.collectors import dom_scraper

            direction = job.params.get("direction", "up")

            # Get height map to calculate scroll target
            height_map = await dom_scraper.get_conversation_height_map(bridge)
            if not height_map:
                return {"ok": False, "error": "no conversation container"}

            # Get current active turn indices from fresh scrape
            fresh = await dom_scraper.collect_agent_panel(bridge)
            current_indices = sorted(set(
                m["_ti"] for m in fresh.get("messages", [])
                if "_ti" in m
            ))

            if not current_indices:
                return {"ok": False, "error": "no active turns"}

            # Calculate target index
            if direction == "up":
                target_idx = max(0, min(current_indices) - 3)
            else:
                target_idx = min(
                    len(height_map) - 1, max(current_indices) + 3,
                )

            # Already at the boundary
            if direction == "up" and min(current_indices) == 0:
                return {"ok": True, "at_boundary": True}
            if direction == "down" and max(current_indices) >= len(height_map) - 1:
                return {"ok": True, "at_boundary": True}

            target_scroll = height_map[target_idx]["scrollStart"]
            ok = await dom_scraper.scroll_conversation_to(
                bridge, target_scroll,
            )
            # MutationObserver will auto-fire → _on_dom_change("agent")
            # → collect_agent_panel → _merge_turn_cache → push_event
            return {"ok": ok}

        if job.action == "clear_cache":
            engine.clear_cache()
            return {"ok": True}

        return {"ok": False, "error": f"unknown action: {job.action}"}

    def get_last_prompt(self, workspace_id):
        """Return the last prompt text sent for a workspace."""
        return self._last_prompt_cache.get(workspace_id, "")

    def stop(self):
        """Signal the consumer loop to stop."""
        self._running = False


# ── Module-level helpers ─────────────────────────────────

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
