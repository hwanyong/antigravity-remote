"""
agbridge.actions.model — Model/Mode selection action handlers

SelectModel, SelectMode, ListModels, ListModes, RefreshModels
"""

import re
import json
import logging

from agbridge.actions.registry import ActionResult

logger = logging.getLogger("agbridge.actions.model")


def normalize_label(label):
    """Normalize a UI label for robust matching.
    
    1. Lowercase
    2. Remove 'New', 'Beta', '[New]' etc tags
    3. Remove non-alphanumeric chars
    4. Collapse whitespace
    """
    if not label:
        return ""
    # Strip common badges
    l = label.lower()
    l = re.sub(r"\[?(new|beta|experimental)\]?", "", l)
    # Alphanumeric only
    l = re.sub(r"[^a-z0-9]", "", l)
    return l.strip()


# ── Shared dropdown JS ───────────────────────────────────────

_JS_SELECT_BY_INDEX = """
(async function() {{
    var trigger = document.querySelector('{trigger_selector}');
    if (!trigger) return false;

    trigger.click();
    await new Promise(function(r) {{ setTimeout(r, 200); }});

    var items = Array.from(document.querySelectorAll(
        '[role="option"], [role="menuitem"], [role="menuitemradio"], ' +
        '[role="menuitemcheckbox"], [role="listbox"] [role="option"], ' +
        '[role="menu"] button, [role="dialog"] button'
    )).filter(function(item) {{
        var rect = item.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return false;
        var style = window.getComputedStyle(item);
        if (style.opacity === '0' || style.visibility === 'hidden' || style.pointerEvents === 'none') return false;
        var container = item.closest('[role="dialog"], [role="menu"]');
        if (container) {{
            var cStyle = window.getComputedStyle(container);
            if (cStyle.opacity === '0' || cStyle.visibility === 'hidden' || cStyle.pointerEvents === 'none') return false;
        }}
        return true;
    }});

    var target = items[{index}];
    if (!target) {{
        document.dispatchEvent(new KeyboardEvent('keydown', {{key: 'Escape', bubbles: true}}));
        return false;
    }}

    target.dispatchEvent(new MouseEvent('mousedown', {{bubbles: true, cancelable: true, view: window}}));
    target.dispatchEvent(new MouseEvent('mouseup', {{bubbles: true, cancelable: true, view: window}}));
    target.click();
    return true;
}})();
"""


_JS_SELECT_DROPDOWN_ITEM = """
(async function() {{
    var trigger = document.querySelector('{trigger_selector}');
    if (!trigger) return false;

    // Open dropdown
    trigger.click();
    await new Promise(function(r) {{ setTimeout(r, 200); }});

    // Find item in popup/listbox
    var items = Array.from(document.querySelectorAll(
        '[role="option"], [role="menuitem"], [role="menuitemradio"], ' +
        '[role="menuitemcheckbox"], [role="listbox"] [role="option"], ' +
        '[role="menu"] button, [role="dialog"] button'
    )).filter(function(item) {{
        var rect = item.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return false;
        var style = window.getComputedStyle(item);
        if (style.opacity === '0' || style.visibility === 'hidden' || style.pointerEvents === 'none') return false;
        var container = item.closest('[role="dialog"], [role="menu"]');
        if (container) {{
            var cStyle = window.getComputedStyle(container);
            if (cStyle.opacity === '0' || cStyle.visibility === 'hidden' || cStyle.pointerEvents === 'none') return false;
        }}
        return true;
    }});
    var target = items.find(function(item) {{
        return (item.textContent || '').trim().indexOf({item_name}) !== -1;
    }});

    if (!target) {{
        document.dispatchEvent(new KeyboardEvent('keydown', {{key: 'Escape', bubbles: true}}));
        return false;
    }}

    target.dispatchEvent(new MouseEvent('mousedown', {{bubbles: true, cancelable: true, view: window}}));
    target.dispatchEvent(new MouseEvent('mouseup', {{bubbles: true, cancelable: true, view: window}}));
    target.click();
    return true;
}})();
"""


_JS_LIST_DROPDOWN_ITEMS = """
(async function() {{
    var trigger = document.querySelector('{trigger_selector}');
    if (!trigger) return JSON.stringify([]);

    trigger.click();
    await new Promise(function(r) {{ setTimeout(r, 200); }});

    var items = Array.from(document.querySelectorAll(
        '[role="option"], [role="menuitem"], [role="menuitemradio"], ' +
        '[role="menuitemcheckbox"], [role="listbox"] [role="option"], ' +
        '[role="menu"] button, [role="dialog"] button'
    )).filter(function(item) {{
        var rect = item.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return false;
        var style = window.getComputedStyle(item);
        if (style.opacity === '0' || style.visibility === 'hidden' || style.pointerEvents === 'none') return false;
        var container = item.closest('[role="dialog"], [role="menu"]');
        if (container) {{
            var cStyle = window.getComputedStyle(container);
            if (cStyle.opacity === '0' || cStyle.visibility === 'hidden' || cStyle.pointerEvents === 'none') return false;
        }}
        return true;
    }});
    var names = items.map(function(item) {{
        return (item.textContent || '').trim();
    }}).filter(function(n) {{ return n.length > 0; }});

    // Close dropdown
    document.dispatchEvent(new KeyboardEvent('keydown', {{key: 'Escape', bubbles: true}}));
    await new Promise(function(r) {{ setTimeout(r, 100); }});

    return JSON.stringify(names);
}})();
"""


class SelectModelAction:
    async def execute(self, ctx, params):
        model_name = params.get("model", "")
        if not model_name:
            return ActionResult.fail("model name is required")

        # 1. Fetch current list to identify index via normalization
        list_action = ListModelsAction()
        available = await list_action._fetch(ctx)
        
        target_norm = normalize_label(model_name)
        index = -1
        
        for i, m in enumerate(available):
            if normalize_label(m) == target_norm:
                index = i
                break
        
        from agbridge.cdp.selectors import SELECTORS
        selector = SELECTORS["model_dropdown"]

        if index != -1:
            # Optimal: Select by index
            ok = await ctx.cdp.execute_js(
                _JS_SELECT_BY_INDEX.format(
                    trigger_selector=selector, index=index,
                )
            )
        else:
            # Fallback (mostly for debugging or mismatched cache)
            js_name = json.dumps(model_name)
            ok = await ctx.cdp.execute_js(
                _JS_SELECT_DROPDOWN_ITEM.format(
                    trigger_selector=selector, item_name=js_name,
                )
            )

        if ok == True:
            return ActionResult.success()
        return ActionResult.fail("model not found")


class SelectModeAction:
    async def execute(self, ctx, params):
        mode_name = params.get("mode", "")
        if not mode_name:
            return ActionResult.fail("mode name is required")

        from agbridge.cdp.selectors import SELECTORS
        selector = SELECTORS["mode_dropdown"]

        # Mode is now a menuitem inside the "Add context" popup.
        # Open the menu, find the item by text, and click it.
        js_name = json.dumps(mode_name)
        ok = await ctx.cdp.execute_js(f"""
            (async function() {{
                var trigger = document.querySelector('{selector}');
                if (!trigger) return false;

                trigger.click();
                await new Promise(function(r) {{ setTimeout(r, 300); }});

                var items = Array.from(document.querySelectorAll('[role="menuitem"]'));
                var target = items.find(function(item) {{
                    return (item.textContent || '').trim() === {js_name};
                }});

                if (!target) {{
                    document.dispatchEvent(new KeyboardEvent('keydown', {{key: 'Escape', bubbles: true}}));
                    return false;
                }}

                target.click();
                return true;
            }})();
        """
        )

        if ok == True:
            return ActionResult.success()
        return ActionResult.fail("mode not found")


class ListModelsAction:
    async def execute(self, ctx, params):
        models_info = ctx.store.get("models_info") or {}
        models = models_info.get("available_models", [])
        if not models:
            models = await self._fetch(ctx)
            if models:
                models_info["available_models"] = models
                ctx.store.update("models_info", models_info)
        return ActionResult.success(models=models)

    async def _fetch(self, ctx):
        from agbridge.cdp.selectors import SELECTORS
        selector = SELECTORS["model_dropdown"]
        result = await ctx.cdp.execute_js(
            _JS_LIST_DROPDOWN_ITEMS.format(trigger_selector=selector)
        )
        if not result:
            return []
        try:
            return json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return []


class ListModesAction:
    async def execute(self, ctx, params):
        models_info = ctx.store.get("models_info") or {}
        modes = models_info.get("available_modes", [])
        if not modes:
            modes = await self._fetch(ctx)
            if modes:
                models_info["available_modes"] = modes
                ctx.store.update("models_info", models_info)
        return ActionResult.success(modes=modes)

    async def _fetch(self, ctx):
        from agbridge.cdp.selectors import SELECTORS
        selector = SELECTORS["mode_dropdown"]
        result = await ctx.cdp.execute_js(f"""
            (async function() {{
                var trigger = document.querySelector('{selector}');
                if (!trigger) return JSON.stringify([]);

                trigger.click();
                await new Promise(function(r) {{ setTimeout(r, 300); }});

                var items = Array.from(document.querySelectorAll('[role="menuitem"]'))
                    .map(function(item) {{ return (item.textContent || '').trim(); }})
                    .filter(function(n) {{ return n.length > 0; }});

                document.dispatchEvent(new KeyboardEvent('keydown', {{key: 'Escape', bubbles: true}}));
                await new Promise(function(r) {{ setTimeout(r, 100); }});

                return JSON.stringify(items);
            }})();
        """)
        if not result:
            return []
        try:
            return json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return []


class RefreshModelsAction:
    async def execute(self, ctx, params):
        list_models = ListModelsAction()
        list_modes = ListModesAction()

        models_result = await list_models._fetch(ctx)
        modes_result = await list_modes._fetch(ctx)

        existing = ctx.store.get("models_info") or {}
        existing["available_models"] = models_result
        existing["available_modes"] = modes_result
        ctx.store.update("models_info", existing)

        return ActionResult.success(
            models=models_result, modes=modes_result,
        )
