"""
agbridge.actions.permission — Permission-related action handlers

Allow/Deny/AllowWorkspace/AllowGlobally/RunSandbox
"""

import json
import logging

from agbridge.actions.registry import ActionResult

logger = logging.getLogger("agbridge.actions.permission")


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


_JS_PERMISSION_DROPDOWN = """
(async function() {{
    // Find chevron button near Allow/Deny
    var btns = Array.from(document.querySelectorAll('button'));
    var chevron = btns.find(function(b) {{
        var label = b.getAttribute('aria-label') || '';
        return label.indexOf('permission') !== -1 ||
               label.indexOf('more') !== -1 ||
               (b.textContent || '').trim() === '▲' ||
               (b.textContent || '').trim() === '▼';
    }});

    if (!chevron) {{
        // Try position-based: find button next to Allow/Deny
        var allowBtn = btns.find(function(b) {{
            return (b.textContent || '').trim() === 'Allow' ||
                   (b.textContent || '').trim() === 'Allow Once';
        }});
        if (allowBtn && allowBtn.nextElementSibling &&
            allowBtn.nextElementSibling.tagName === 'BUTTON') {{
            chevron = allowBtn.nextElementSibling;
        }}
    }}

    if (!chevron) return false;

    chevron.click();
    await new Promise(function(r) {{ setTimeout(r, 200); }});

    // Find menu item
    var menuItems = Array.from(document.querySelectorAll(
        '[role="menuitem"], [role="option"], [class*="dropdown"] li, [class*="menu"] li'
    ));
    var target = menuItems.find(function(item) {{
        return (item.textContent || '').trim().indexOf('{item_text}') !== -1;
    }});

    if (!target) {{
        document.dispatchEvent(new KeyboardEvent('keydown', {{key: 'Escape', bubbles: true}}));
        return false;
    }}

    target.click();
    return true;
}})();
"""


class AllowAction:
    async def execute(self, ctx, params):
        # Try "Allow" first, then "Allow Once"
        ok = await ctx.cdp.execute_js(
            _JS_CLICK_BY_TEXT.format(text="Allow")
        )
        if ok != True:
            ok = await ctx.cdp.execute_js(
                _JS_CLICK_BY_TEXT.format(text="Allow Once")
            )
        if ok == True:
            return ActionResult.success()
        return ActionResult.fail("Allow button not found")


class DenyAction:
    async def execute(self, ctx, params):
        ok = await ctx.cdp.execute_js(
            _JS_CLICK_BY_TEXT.format(text="Deny")
        )
        if ok == True:
            return ActionResult.success()
        return ActionResult.fail("Deny button not found")


class AllowWorkspaceAction:
    async def execute(self, ctx, params):
        ok = await ctx.cdp.execute_js(
            _JS_PERMISSION_DROPDOWN.format(item_text="Allow for Workspace")
        )
        if ok == True:
            return ActionResult.success()
        return ActionResult.fail("Allow for Workspace not found")


class AllowGloballyAction:
    async def execute(self, ctx, params):
        ok = await ctx.cdp.execute_js(
            _JS_PERMISSION_DROPDOWN.format(item_text="Allow Globally")
        )
        if ok == True:
            return ActionResult.success()
        return ActionResult.fail("Allow Globally not found")


class RunSandboxAction:
    async def execute(self, ctx, params):
        ok = await ctx.cdp.execute_js(
            _JS_PERMISSION_DROPDOWN.format(item_text="Run in sandbox")
        )
        if ok == True:
            return ActionResult.success()
        return ActionResult.fail("Run in sandbox not found")
