"""
agbridge.actions.prompt — Prompt injection action handlers

InjectPrompt, UndoToPrompt, ConfirmUndo, CancelUndo

The core InjectPromptAction delegates to EditorGateway for the
actual inject → verify → send pipeline.
"""

import asyncio
import logging

from agbridge.actions.registry import ActionResult

logger = logging.getLogger("agbridge.actions.prompt")


class InjectPromptAction:
    """Inject prompt text and press Send.

    Delegates to EditorGateway.inject_and_send() which handles:
    1. Lexical state construction
    2. editor.update() injection (no execCommand trick)
    3. Content verification
    4. Deterministic Send button polling
    """

    async def execute(self, ctx, params):
        # Wait for initialization if needed
        if ctx.state_machine.is_initializing():
            ready = await ctx.state_machine.wait_for_idle(timeout=15.0)
            if not ready:
                return ActionResult.fail("IDE initialization timed out")

        text = params.get("content", "")
        if not text:
            return ActionResult.fail("content is required")

        if not ctx.state_machine.can_inject():
            return ActionResult.fail("agent is currently generating")

        result = await ctx.editor.inject_and_send(text)
        return result


class UndoToPromptAction:
    """Click undo button for a specific message, then wait for dialog."""

    async def execute(self, ctx, params):
        index = params.get("message_index")
        if index is None:
            return ActionResult.fail("message_index is required")

        # Pre-cache prompt provided from TUI widget state
        prompt_text = params.get("prompt_text", "")
        turn_idx = params.get("turn_idx", -1)

        ctx.prompt_history.pending_undo = {
            "prompt_text": prompt_text,
            "turn_idx": turn_idx,
        }

        # 1. Scroll to the turn to ensure it is mounted (handling React virtualization)
        if turn_idx >= 0:
            try:
                from agbridge.collectors.dom_scraper import get_conversation_height_map, scroll_conversation_to
                height_map = await get_conversation_height_map(ctx.cdp)
                if height_map and turn_idx < len(height_map):
                    scroll_pos = height_map[turn_idx].get("scrollStart", 0)
                    await scroll_conversation_to(ctx.cdp, scroll_pos)
                    import asyncio
                    await asyncio.sleep(0.3)  # Allow DOM to render
            except Exception:
                pass  # Fallback to naive execution if scrolling fails

        import json
        safe_prompt = json.dumps(prompt_text)

        result = await ctx.cdp.execute_js(f"""
            (function() {{
                var conv = document.getElementById('conversation');
                if (!conv) return false;

                var undoBtns = Array.from(conv.querySelectorAll(
                    'button[aria-label*="undo"], button[aria-label*="Undo"], ' +
                    'div[role="button"][data-tooltip-id*="undo"]'
                ));

                if (undoBtns.length === 0) {{
                    var allBtns = Array.from(conv.querySelectorAll('button, div[role="button"]'));
                    undoBtns = allBtns.filter(function(b) {{
                        return (b.textContent || '').indexOf('↩') !== -1 ||
                               (b.getAttribute('title') || '').indexOf('undo') !== -1 ||
                               (b.getAttribute('title') || '').indexOf('Undo') !== -1;
                    }});
                }}

                var targetText = {safe_prompt}.trim().toLowerCase();
                if (targetText && targetText.length > 3) {{
                    for (var i = 0; i < undoBtns.length; i++) {{
                        var btn = undoBtns[i];
                        var sticky = btn.closest('.sticky');
                        if (sticky) {{
                            var text = sticky.textContent.trim().toLowerCase();
                            if (text.indexOf(targetText) !== -1 || targetText.indexOf(text.substring(0,20)) !== -1) {{
                                btn.click();
                                return true;
                            }}
                        }}
                    }}
                }}

                // Fallback: use raw index (brittle if fake messages exist or virtualization unmounted earlier msgs)
                var idx = {index};
                if (idx >= 0 && idx < undoBtns.length) {{
                    undoBtns[idx].click();
                    return true;
                }}

                return false;
            }})();
        """)

        if result != True:
            ctx.prompt_history.pending_undo = None
            return ActionResult.fail("undo button not found")

        # Wait for dialog to appear
        for _ in range(20):
            from agbridge.collectors.dom_scraper import detect_confirm_undo_dialog
            dialog_data = await detect_confirm_undo_dialog(ctx.cdp)
            if dialog_data:
                return ActionResult.success(dialog=dialog_data)
            await asyncio.sleep(0.1)

        return ActionResult.fail("undo dialog not appeared")


class ConfirmUndoAction:
    """Click Confirm in undo dialog, restore prompt, truncate cache."""

    async def execute(self, ctx, params):
        ok = await ctx.cdp.execute_js("""
            (function() {
                var dialogs = document.querySelectorAll(
                    'div.fixed.inset-0, [role="dialog"], [class*="modal"], [class*="overlay"]'
                );
                for (var i = 0; i < dialogs.length; i++) {
                    var btns = dialogs[i].querySelectorAll('button, [role="button"]');
                    for (var b = 0; b < btns.length; b++) {
                        var text = (btns[b].textContent || '').trim();
                        if (text === 'Confirm' || text.indexOf('Confirm') !== -1) {
                            btns[b].click();
                            return true;
                        }
                    }
                }
                return false;
            })();
        """)

        if ok != True:
            return ActionResult.fail("confirm button not found")

        cached_undo = ctx.prompt_history.pending_undo or {}
        ctx.prompt_history.pending_undo = None

        restored_prompt = cached_undo.get("prompt_text", "")
        turn_idx = cached_undo.get("turn_idx", -1)

        # Restore prompt in editor (inject only, no send)
        if restored_prompt:
            await ctx.editor.inject_only(restored_prompt)
        else:
            await ctx.editor.clear()

        # Truncate cache to reflect deletion immediately
        agent_data = {}
        if turn_idx >= 0:
            agent_data = ctx.conversation.truncate(turn_idx)
        else:
            from agbridge.collectors import dom_scraper
            agent_data = await dom_scraper.collect_agent_panel(ctx.cdp)

        # Push updated state to TUI immediately
        if agent_data:
            from agbridge import protocol
            flat = ctx.conversation.flatten()
            agent_data["messages"] = flat
            agent_data["_cached_turns"] = ctx.conversation.turn_count
            ctx.push_event(protocol.UI_AGENT_UPDATE, agent_data)

        return ActionResult.success(
            agent_update=agent_data,
            restored_prompt=restored_prompt,
        )


class CancelUndoAction:
    """Click Cancel in undo dialog."""

    async def execute(self, ctx, params):
        ctx.prompt_history.pending_undo = None

        ok = await ctx.cdp.execute_js("""
            (function() {
                var dialogs = document.querySelectorAll(
                    'div.fixed.inset-0, [role="dialog"], [class*="modal"], [class*="overlay"]'
                );
                for (var i = 0; i < dialogs.length; i++) {
                    var btns = dialogs[i].querySelectorAll('button, [role="button"]');
                    for (var b = 0; b < btns.length; b++) {
                        if ((btns[b].textContent || '').trim() === 'Cancel') {
                            btns[b].click();
                            return true;
                        }
                    }
                }
                return false;
            })();
        """)
        if ok == True:
            return ActionResult.success()
        return ActionResult.fail("cancel button not found")
