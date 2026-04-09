"""
agbridge.input_queue — Serialized AX write operations

macOS allows only one foreground app at a time. All AX write operations
(inject_prompt, accept_all, reject_all) must be serialized with explicit
focus management to prevent input mis-delivery.

Read operations (AX scraping) bypass this queue entirely — they work
without focus and run in parallel per-Engine.
"""

import asyncio
import logging
import time

logger = logging.getLogger("agbridge.input_queue")


class InputJob:
    """A single AX write operation awaiting execution."""

    __slots__ = ("workspace_id", "action", "params", "result", "created_at")

    def __init__(self, workspace_id, action, params):
        self.workspace_id = workspace_id
        self.action = action
        self.params = params
        self.result = asyncio.get_event_loop().create_future()
        self.created_at = time.monotonic()


class InputQueue:
    """
    Serializes all AX write operations across workspaces.

    Consumer loop: dequeue → focus target window → stabilize → execute → next.
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
        Submit an AX write job and await its result.

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

            if not engine.ide.is_connected:
                job.result.set_result({
                    "ok": False,
                    "error": "IDE not connected",
                })
                self._queue.task_done()
                continue

            try:
                # Focus the target IDE window
                engine.ide.focus_window()
                from agbridge.config import FOCUS_STABILIZE_SECONDS
                await asyncio.sleep(FOCUS_STABILIZE_SECONDS)

                # Execute the action
                result = self._execute(engine, job)
                job.result.set_result(result)

            except Exception as e:
                from agbridge.collectors.ax_polling import PollAborted
                if isinstance(e, PollAborted):
                    logger.info(
                        "InputQueue job aborted (IDE shutdown): ws=%s action=%s",
                        job.workspace_id, job.action,
                    )
                else:
                    logger.error(
                        "InputQueue job failed: ws=%s action=%s error=%s",
                        job.workspace_id, job.action, e,
                    )
                job.result.set_result({"ok": False, "error": str(e)})

            finally:
                self._queue.task_done()

    def _execute(self, engine, job):
        """Dispatch job to the appropriate AX write handler."""
        from agbridge.collectors.ax_scraper import (
            inject_prompt,
            press_edit_action,
            press_cancel_button,
            press_retry_button,
            press_dismiss_button,
            press_button_by_exact_title,
            press_permission_dropdown_item,
            press_undo_for_message,
            press_confirm_undo,
            press_cancel_undo,
            detect_confirm_undo_dialog,
            reconstruct_user_message_text,
            collect_agent_panel,
            get_conversation_state,
            select_model,
            select_mode,
            click_new_conversation,
            list_available_models,
            list_available_modes,
            list_conversations,
            select_conversation_by_title,
        )
        from agbridge.collectors.ax_polling import poll_until

        pc = engine.poll_controller

        if job.action == "inject_prompt":
            text = job.params.get("content", "")
            if not text:
                return {"ok": False, "error": "content is required"}
            if not engine.ide.windows:
                return {"ok": False, "error": "no IDE windows"}
            self._last_prompt_cache[job.workspace_id] = text
            ok = inject_prompt(engine.ide.windows[0], text, pc)
            return {"ok": ok}

        if job.action == "accept_all":
            ok = press_edit_action("accept_all")
            return {"ok": ok, "error": None if ok else "button not available"}

        if job.action == "reject_all":
            ok = press_edit_action("reject_all")
            return {"ok": ok, "error": None if ok else "button not available"}

        if job.action == "cancel":
            if not engine.ide.windows:
                return {"ok": False, "error": "no IDE windows"}
            ok = press_cancel_button(engine.ide.windows[0])
            return {"ok": ok, "error": None if ok else "cancel button not found"}

        if job.action == "select_model":
            model_name = job.params.get("model", "")
            if not model_name:
                return {"ok": False, "error": "model name is required"}
            if not engine.ide.windows:
                return {"ok": False, "error": "no IDE windows"}
            ok = select_model(engine.ide.windows[0], model_name, pc)
            return {"ok": ok}

        if job.action == "select_mode":
            mode_name = job.params.get("mode", "")
            if not mode_name:
                return {"ok": False, "error": "mode name is required"}
            if not engine.ide.windows:
                return {"ok": False, "error": "no IDE windows"}
            ok = select_mode(engine.ide.windows[0], mode_name, pc)
            return {"ok": ok}

        if job.action == "new_conversation":
            if not engine.ide.windows:
                return {"ok": False, "error": "no IDE windows"}
            ok = click_new_conversation(engine.ide.windows[0])
            return {"ok": ok}

        if job.action == "retry":
            if not engine.ide.windows:
                return {"ok": False, "error": "no IDE windows"}
            ok = press_retry_button(engine.ide.windows[0])
            return {"ok": ok, "error": None if ok else "retry button not found"}

        if job.action == "dismiss_error":
            if not engine.ide.windows:
                return {"ok": False, "error": "no IDE windows"}
            ok = press_dismiss_button(engine.ide.windows[0])
            return {"ok": ok, "error": None if ok else "dismiss button not found"}

        if job.action == "press_deny":
            if not engine.ide.windows:
                return {"ok": False, "error": "no IDE windows"}
            ok = press_button_by_exact_title(engine.ide.windows[0], "Deny")
            return {"ok": ok, "error": None if ok else "Deny button not found"}

        if job.action == "press_allow":
            if not engine.ide.windows:
                return {"ok": False, "error": "no IDE windows"}
            ok = press_button_by_exact_title(engine.ide.windows[0], "Allow")
            if not ok:
                ok = press_button_by_exact_title(engine.ide.windows[0], "Allow Once")
            return {"ok": ok, "error": None if ok else "Allow button not found"}

        if job.action == "press_allow_workspace":
            if not engine.ide.windows:
                return {"ok": False, "error": "no IDE windows"}
            ok = press_permission_dropdown_item(engine.ide.windows[0], "Allow for Workspace", pc)
            return {"ok": ok, "error": None if ok else "Allow for Workspace not found"}

        if job.action == "press_allow_globally":
            if not engine.ide.windows:
                return {"ok": False, "error": "no IDE windows"}
            ok = press_permission_dropdown_item(engine.ide.windows[0], "Allow Globally", pc)
            return {"ok": ok, "error": None if ok else "Allow Globally not found"}

        if job.action == "press_run_sandbox":
            if not engine.ide.windows:
                return {"ok": False, "error": "no IDE windows"}
            ok = press_permission_dropdown_item(engine.ide.windows[0], "Run in sandbox", pc)
            return {"ok": ok, "error": None if ok else "Run in sandbox not found"}

        if job.action == "list_models":
            models_info = engine.store.get("models_info") or {}
            models = models_info.get("available_models", [])
            if not models:
                # Cache empty — scrape once and cache
                if not engine.ide.windows:
                    return {"ok": False, "error": "no IDE windows"}
                models = list_available_models(engine.ide.windows[0], pc)
                if models:
                    models_info["available_models"] = models
                    engine.store.update("models_info", models_info)
            return {"ok": True, "models": models}

        if job.action == "list_modes":
            models_info = engine.store.get("models_info") or {}
            modes = models_info.get("available_modes", [])
            if not modes:
                # Cache empty — scrape once and cache
                if not engine.ide.windows:
                    return {"ok": False, "error": "no IDE windows"}
                modes = list_available_modes(engine.ide.windows[0], pc)
                if modes:
                    models_info["available_modes"] = modes
                    engine.store.update("models_info", models_info)
            return {"ok": True, "modes": modes}

        if job.action == "list_conversations":
            if not engine.ide.windows:
                return {"ok": False, "error": "no IDE windows"}
            convs = list_conversations(engine.ide.windows[0], pc)
            return {"ok": True, "conversations": convs}

        if job.action == "select_conversation":
            title = job.params.get("title", "")
            if not title:
                return {"ok": False, "error": "title is required"}
            if not engine.ide.windows:
                return {"ok": False, "error": "no IDE windows"}
            ok = select_conversation_by_title(engine.ide.windows[0], title, pc)
            return {"ok": ok}

        if job.action == "refresh_models":
            if not engine.ide.windows:
                return {"ok": False, "error": "no IDE windows"}
            models = list_available_models(engine.ide.windows[0], pc)
            modes = list_available_modes(engine.ide.windows[0], pc)
            existing = engine.store.get("models_info") or {}
            existing["available_models"] = models
            existing["available_modes"] = modes
            engine.store.update("models_info", existing)
            return {"ok": True, "models": models, "modes": modes}

        if job.action == "undo_to_prompt":
            index = job.params.get("message_index")
            if index is None:
                return {"ok": False, "error": "message_index is required"}
            if not engine.ide.windows:
                return {"ok": False, "error": "no IDE windows"}

            # Pre-cache prompt via AX tree walk BEFORE pressing undo
            cached_prompt = reconstruct_user_message_text(
                engine.ide.windows[0], index,
            )
            self._undo_prompt_cache[job.workspace_id] = cached_prompt

            ok = press_undo_for_message(engine.ide.windows[0], index)
            if not ok:
                self._undo_prompt_cache.pop(job.workspace_id, None)
                return {"ok": False, "error": "undo button not found"}

            # Poll until IDE renders the Confirm Undo dialog
            dialog_data = poll_until(
                lambda: detect_confirm_undo_dialog(engine.ide.windows[0]),
                pc,
                label="undo_dialog",
            )
            return {"ok": True, "dialog": dialog_data}

        if job.action == "confirm_undo":
            if not engine.ide.windows:
                return {"ok": False, "error": "no IDE windows"}
            ok = press_confirm_undo(engine.ide.windows[0])
            if not ok:
                return {"ok": False, "error": "confirm button not found"}

            # Poll until IDE completes undo (state returns to idle)
            poll_until(
                lambda: get_conversation_state(engine.ide.windows[0]) == "idle",
                pc,
                label="confirm_undo_idle",
            )

            # Re-scrape conversation — included in response for instant TUI update
            # NOTE: do NOT call engine.store.update here — let Engine poll
            # handle it naturally to avoid hash collision
            agent_data = collect_agent_panel(engine.ide.windows[0])

            # Use pre-cached prompt (reconstructed with mention syntax)
            restored_prompt = self._undo_prompt_cache.pop(
                job.workspace_id, "",
            )

            return {
                "ok": True,
                "agent_update": agent_data,
                "restored_prompt": restored_prompt,
            }

        if job.action == "cancel_undo":
            if not engine.ide.windows:
                return {"ok": False, "error": "no IDE windows"}
            self._undo_prompt_cache.pop(job.workspace_id, None)
            ok = press_cancel_undo(engine.ide.windows[0])
            return {"ok": ok, "error": None if ok else "cancel button not found"}

        return {"ok": False, "error": f"unknown action: {job.action}"}

    def get_last_prompt(self, workspace_id):
        """Return the last prompt text sent for a workspace."""
        return self._last_prompt_cache.get(workspace_id, "")

    def stop(self):
        """Signal the consumer loop to stop."""
        self._running = False
