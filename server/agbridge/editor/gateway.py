"""
agbridge.editor.gateway — Deterministic prompt pipeline

Single entry point for all editor interactions:
  inject_and_send(text) → inject → verify → send (3-step pipeline)
  inject_only(text)     → inject only (for undo restore)
  clear()               → clear editor content
  read_text()           → read current editor text

Replaces:
  - cdp_actions.inject_prompt (execCommand trick → editor.update API)
  - cdp_actions.inject_advanced_prompt
  - cdp_actions.press_send (MutationObserver → deterministic polling)
  - cdp_actions.clear_message_input
  - cdp_actions.read_input_text
"""

import base64
import json
import logging

from agbridge.actions.registry import ActionResult
from agbridge.editor.tokenizer import (
    tokenize_prompt,
    tokens_to_lexical_children,
    build_lexical_state,
)

logger = logging.getLogger("agbridge.editor.gateway")


class EditorGateway:
    """Deterministic prompt injection and send pipeline.

    All operations use window.__agbridge API injected by
    runtime_bootstrap.js, guaranteeing React onChange via
    Lexical's editor.update() instead of deprecated execCommand.
    """

    def __init__(self, context):
        """
        Args:
            context: WorkspaceContext instance.
        """
        self._ctx = context

    # ── Public API ───────────────────────────────────────────

    async def inject_and_send(self, text):
        """Complete prompt pipeline: inject → verify → send.

        Args:
            text: Full prompt text (may contain @[/workflow] tokens).

        Returns:
            ActionResult
        """
        # 1. Pre-conditions
        if not self._ctx.can_inject:
            return ActionResult.fail("workspace not ready for injection")

        # 2. Tokenize + build Lexical state
        tokens = tokenize_prompt(text)
        children = tokens_to_lexical_children(
            tokens, workspace_root=self._ctx.workspace_root
        )
        state_dict = build_lexical_state(children)

        # 3. Inject via __agbridge.setContent
        inject_result = await self._inject_lexical(state_dict)
        if not inject_result.ok:
            return inject_result

        # 4. Verify content is actually in the editor (NEW step)
        verified = await self._verify_content()
        if not verified:
            logger.error("Content verification failed after injection")
            return ActionResult.fail("content_not_reflected")

        # 5. Press Send (deterministic polling, no MutationObserver)
        send_result = await self._press_send()
        if not send_result.ok:
            return send_result

        # 6. Record
        self._ctx.state_machine.transition("inject_started")
        self._ctx.prompt_history.record_sent(text)

        return ActionResult.success()

    async def inject_only(self, text):
        """Inject text without pressing Send.

        Used for restoring prompts after undo, allowing user to
        edit before sending again.

        Args:
            text: Prompt text to inject.

        Returns:
            ActionResult
        """
        tokens = tokenize_prompt(text)
        children = tokens_to_lexical_children(
            tokens, workspace_root=self._ctx.workspace_root
        )
        state_dict = build_lexical_state(children)
        return await self._inject_lexical(state_dict)

    async def clear(self):
        """Clear editor content.

        Returns:
            ActionResult
        """
        result = await self._ctx.cdp.execute_js(
            "window.__agbridge && window.__agbridge.clearContent()"
        )
        if result == True:
            return ActionResult.success()

        # Fallback: if __agbridge not available, use direct approach
        result = await self._ctx.cdp.execute_js(_JS_CLEAR_FALLBACK)
        if result == True:
            return ActionResult.success()
        return ActionResult.fail("clear failed")

    async def read_text(self):
        """Read current text content from the editor.

        Returns:
            str: Current editor text, or empty string.
        """
        result = await self._ctx.cdp.execute_js(
            "window.__agbridge ? window.__agbridge.getTextContent() : "
            "(document.querySelector('[data-lexical-editor=\"true\"]') || {}).textContent || ''"
        )
        return result or ""

    # ── Internal Pipeline Steps ──────────────────────────────

    async def _inject_lexical(self, state_dict):
        """Inject a Lexical EditorState via __agbridge.setContent.

        Falls back to direct setEditorState + editor.update() if
        __agbridge is not yet installed.
        """
        state_json = json.dumps(state_dict, ensure_ascii=False)
        b64 = base64.b64encode(state_json.encode("utf-8")).decode("ascii")

        # Try __agbridge API first (installed by runtime_bootstrap.js)
        result = await self._ctx.cdp.execute_js(
            f"window.__agbridge && window.__agbridge.setContent('{b64}')"
        )

        if result == True:
            return ActionResult.success()

        # Fallback: direct injection if __agbridge not installed yet
        # This uses the same logic as runtime_bootstrap.js but inline
        result = await self._ctx.cdp.execute_js(f"""
            (function() {{
                var btns = Array.from(document.querySelectorAll('button, [role="button"], .submit, .send, .generate'));
                var btn = btns.find(function(b) {{
                    var aria = (b.getAttribute('aria-label') || '').toLowerCase();
                    var title = (b.title || '').toLowerCase();
                    var text = (b.textContent || '').trim().toLowerCase();
                    if (aria.includes('send') || aria.includes('submit') || aria.includes('generate') || aria.includes('start')) return true;
                    if (title.includes('send') || title.includes('submit') || title.includes('generate')) return true;
                    if (text === 'submit' || text === 'send' || text === 'generate' || text === 'start') return true;
                    if (b.querySelector('svg.fa-paper-plane') || b.querySelector('svg[class*="submit"]') || b.querySelector('svg[class*="send"]')) return true;
                    return false;
                }});
                
                var editor = null;
                if (btn) {{
                    var w = btn.parentElement;
                    while (w && !editor) {{ editor = w.querySelector('[data-lexical-editor="true"]'); w = w.parentElement; }}
                }}
                if (!editor) editor = document.querySelector('[data-lexical-editor="true"]');
                if (!editor || !editor.__lexicalEditor) return 'no editor';
                var lex = editor.__lexicalEditor;
                var bin = atob('{b64}');
                var bytes = new Uint8Array(bin.length);
                for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
                var stateJSON = new TextDecoder().decode(bytes);
                var newState = lex.parseEditorState(stateJSON);
                lex.setEditorState(newState);
                lex.update(function() {{}}, {{ tag: 'agbridge-inject' }});
                editor.focus();
                return true;
            }})();
        """)

        if result == True:
            return ActionResult.success()

        logger.error("Lexical injection failed: %s", result)
        return ActionResult.fail(f"injection failed: {result}")

    async def _verify_content(self):
        """Verify that injected content is actually in the editor.

        This is the KEY missing step in the original code that caused
        empty message submissions.

        Returns:
            bool: True if editor has non-empty content.
        """
        result = await self._ctx.cdp.execute_js("""
            (function() {
                if (window.__agbridge) {
                    return window.__agbridge.getTextContent().length > 0;
                }
                var editor = document.querySelector('[data-lexical-editor="true"]');
                return (editor && editor.textContent.trim().length > 0);
            })();
        """)
        return result == True

    async def _press_send(self):
        """Press Send button with deterministic polling.

        Replaces the 5-second MutationObserver approach with a
        simple polling loop that returns structured diagnostics on failure.

        Returns:
            ActionResult: with diagnostic data on failure.
        """
        result = await self._ctx.cdp.execute_js(_JS_PRESS_SEND)

        if isinstance(result, dict):
            if result.get("ok"):
                return ActionResult.success(attempts=result.get("attempts", 0))
            return ActionResult.fail(
                result.get("reason", "send_failed"),
                editor_has_content=result.get("editor_has_content", False),
                attempts=result.get("attempts", 0),
            )

        if result == True:
            return ActionResult.success()

        return ActionResult.fail("send button not found")


# ── JS Snippets ──────────────────────────────────────────────

_JS_PRESS_SEND = """
(async function() {
    var maxAttempts = 40;  // 100ms × 40 = max 4 seconds
    var editor = null;
    if (typeof window.__agbridge !== 'undefined' && typeof window.__agbridge.getActiveEditor === 'function') {
        editor = window.__agbridge.getActiveEditor();
    }
    if (!editor) editor = document.querySelector('[data-lexical-editor="true"]');
    
    function getSpecificBtn() {
        var btn = null;
        if (editor) {
            var walker = editor;
            var limit = 7;
            while(walker && limit > 0) {
                btn = walker.querySelector('button[aria-label="Send message"], [role="button"][aria-label="Send message"]');
                if (btn) return btn;
                walker = walker.parentElement;
                limit--;
            }
        }
        return document.querySelector('button[aria-label="Send message"]') || document.querySelector('[role="button"][aria-label="Send message"]');
    }

    for (var i = 0; i < maxAttempts; i++) {
        var btn = getSpecificBtn();
        
        if (btn) {
            // Wake up React components regardless of disabled state
            if (editor) {
                editor.dispatchEvent(new InputEvent('input', { bubbles: true, cancelable: true }));
            }
            
            // Critical Fix: forcefully break the React-imposed disabled lock unconditionally
            btn.removeAttribute('disabled');
            btn.setAttribute('aria-disabled', 'false');
            
            btn.click();
            return { ok: true, attempts: i + 1, hack_used: true };
        }
        
        await new Promise(function(r) { setTimeout(r, 100); });
    }
    
    var finalBtn = getSpecificBtn();
    return {
        ok: false,
        reason: !finalBtn ? 'button_not_found' : 'button_disabled',
        editor_has_content: !!(editor || {}).textContent,
        attempts: maxAttempts,
    };
})();
"""

_JS_CLEAR_FALLBACK = """
(function() {
    var btns = Array.from(document.querySelectorAll('button, [role="button"], .submit, .send, .generate'));
    var btn = btns.find(function(b) {
        var aria = (b.getAttribute('aria-label') || '').toLowerCase();
        var title = (b.title || '').toLowerCase();
        var text = (b.textContent || '').trim().toLowerCase();
        if (aria.includes('send') || aria.includes('submit') || aria.includes('generate') || aria.includes('start')) return true;
        if (title.includes('send') || title.includes('submit') || title.includes('generate')) return true;
        if (text === 'submit' || text === 'send' || text === 'generate' || text === 'start') return true;
        if (b.querySelector('svg.fa-paper-plane') || b.querySelector('svg[class*="submit"]') || b.querySelector('svg[class*="send"]')) return true;
        return false;
    });
    
    var editor = null;
    if (btn) {
        var w = btn.parentElement;
        while (w && !editor) { editor = w.querySelector('[data-lexical-editor="true"]'); w = w.parentElement; }
    }
    if (!editor) editor = document.querySelector('[data-lexical-editor="true"]');
    if (!editor || !editor.__lexicalEditor) return false;
    var lex = editor.__lexicalEditor;

    var selectAllCmd = null;
    var deleteCmd = null;
    lex._commands.forEach(function(v, k) {
        if (k.type === 'SELECT_ALL_COMMAND') selectAllCmd = k;
        if (k.type === 'DELETE_CHARACTER_COMMAND') deleteCmd = k;
    });

    if (!selectAllCmd) return false;
    editor.focus();
    lex.dispatchCommand(selectAllCmd);

    if (deleteCmd) {
        lex.dispatchCommand(deleteCmd, true);
    }
    return true;
})();
"""
