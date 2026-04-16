"""
agbridge.actions.controls — IDE control action handlers

Accept/Reject/Cancel/Retry/Dismiss — simple button-click actions.
"""

import logging

from agbridge.actions.registry import ActionResult

logger = logging.getLogger("agbridge.actions.controls")


# ── Shared JS helpers ────────────────────────────────────────

_JS_CLICK_BY_TEXT = """
(function() {{
    var btns = Array.from(document.querySelectorAll('button'));
    var btn = btns.find(function(b) {{
        return (b.textContent || '').trim() === '{text}';
    }});
    if (btn && !btn.disabled) {{ btn.click(); return true; }}
    return false;
}})();
"""

_JS_CLICK_CANCEL = """
(function() {
    var btn = document.querySelector('button[aria-label="Cancel generation"]');
    if (!btn) btn = document.querySelector('button[aria-label="Cancel"]');
    if (!btn) btn = document.querySelector('[role="button"][aria-label="Cancel generation"]');
    if (!btn) btn = document.querySelector('[role="button"][aria-label="Cancel"]');

    if (btn && !btn.disabled) {
        btn.click();
        return true;
    }
    return false;
})();
"""


class AcceptAllAction:
    async def execute(self, ctx, params):
        ok = await ctx.cdp.execute_js(
            _JS_CLICK_BY_TEXT.format(text="Accept all")
        )
        if ok == True:
            return ActionResult.success()
        return ActionResult.fail("button not available")


class RejectAllAction:
    async def execute(self, ctx, params):
        ok = await ctx.cdp.execute_js(
            _JS_CLICK_BY_TEXT.format(text="Reject all")
        )
        if ok == True:
            return ActionResult.success()
        return ActionResult.fail("button not available")


class CancelAction:
    async def execute(self, ctx, params):
        ok = await ctx.cdp.execute_js(_JS_CLICK_CANCEL)
        if ok == True:
            return ActionResult.success()
        return ActionResult.fail("cancel button not found")


class RetryAction:
    async def execute(self, ctx, params):
        ok = await ctx.cdp.execute_js(
            _JS_CLICK_BY_TEXT.format(text="Retry")
        )
        if ok == True:
            ctx.state_machine.transition("retry")
            return ActionResult.success()
        return ActionResult.fail("retry button not found")


class DismissErrorAction:
    async def execute(self, ctx, params):
        ok = await ctx.cdp.execute_js(
            _JS_CLICK_BY_TEXT.format(text="Dismiss")
        )
        if ok == True:
            ctx.state_machine.transition("dismiss")
            return ActionResult.success()
        return ActionResult.fail("dismiss button not found")
