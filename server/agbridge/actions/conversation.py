"""
agbridge.actions.conversation — Conversation management action handlers

New/Select/Delete/List/Expand/Close/Scroll/ClearCache
"""

import asyncio
import json
import logging

from agbridge.actions.registry import ActionResult

logger = logging.getLogger("agbridge.actions.conversation")


# ── New Conversation ─────────────────────────────────────────

_JS_NEW_CONVERSATION = """
(function() {
    // Primary: data-tooltip-id attribute (stable Antigravity identifier)
    var btn = document.querySelector('[data-tooltip-id="new-conversation-tooltip"]');
    if (btn) { btn.click(); return true; }

    // Fallback: aria-label
    btn = document.querySelector('[aria-label*="New conversation"], [aria-label*="new conversation"]');
    if (btn) { btn.click(); return true; }

    return false;
})();
"""


class NewConversationAction:
    async def execute(self, ctx, params):
        ok = await ctx.cdp.execute_js(_JS_NEW_CONVERSATION)
        if ok == True:
            return ActionResult.success()
        return ActionResult.fail("new conversation button not found")


# ── List Conversations ───────────────────────────────────────

_JS_LIST_CONVERSATIONS = r"""
(async function() {
    var all = document.querySelectorAll('div.cursor-pointer');
    var convItems = Array.from(all).filter(function(d) {
        var cls = d.className || '';
        return cls.indexOf('justify-between') !== -1 &&
               cls.indexOf('px-2.5') !== -1;
    });

    // If no items visible, toggle history panel to show them
    if (convItems.length === 0) {
        var toggle = document.querySelector('[data-past-conversations-toggle]');
        if (toggle) {
            toggle.click();
            await new Promise(function(r) { setTimeout(r, 400); });
            all = document.querySelectorAll('div.cursor-pointer');
            convItems = Array.from(all).filter(function(d) {
                var cls = d.className || '';
                return cls.indexOf('justify-between') !== -1 &&
                       cls.indexOf('px-2.5') !== -1;
            });
        }
    }
    if (convItems.length === 0) return JSON.stringify([]);

    // Walk up to the scrollable container
    var container = convItems[0];
    for (var i = 0; i < 10; i++) {
        if (!container.parentElement) break;
        container = container.parentElement;
        if ((container.className || '').indexOf('overflow') !== -1) break;
    }

    // Walk container tree — skip "Other Conversations" section
    var sections = [];
    var currentCategory = '';
    var skipSection = false;

    function walk(el) {
        Array.from(el.children).forEach(function(child) {
            var text = (child.textContent || '').trim();
            var cls = child.className || '';

            var isConv = cls.indexOf('cursor-pointer') !== -1 &&
                         cls.indexOf('justify-between') !== -1 &&
                         cls.indexOf('px-2.5') !== -1;

            // "Show N more..." link
            var showMoreMatch = text.match(/^Show (\d+) more/);
            var isShowMore = !!showMoreMatch && text.length < 30;

            var isHeader = child.children.length === 0 &&
                           text.length > 2 && text.length < 50 &&
                           !isConv && !isShowMore;

            if (isHeader) {
                currentCategory = text;
                skipSection = (text === 'Other Conversations');
            } else if (skipSection) {
                // Skip everything in Other Conversations
            } else if (isShowMore) {
                sections.push({
                    type: 'show_more',
                    text: text,
                });
            } else if (isConv) {
                var spans = Array.from(child.querySelectorAll('span'));
                var title = '';
                var workspace = '';
                var time = '';

                for (var s = 0; s < spans.length; s++) {
                    var st = (spans[s].textContent || '').trim();
                    if (!st) continue;
                    if (!title && st.length > 1) { title = st; continue; }
                    if (!workspace && st.indexOf('/') !== -1 && st.length < 60) {
                        workspace = st; continue;
                    }
                    if (!time && /^(now|\d+\s*(min|hr|day|week|month)s?\s*ago)$/.test(st)) {
                        time = st;
                    }
                }

                sections.push({
                    type: 'conversation',
                    title: title,
                    time: time,
                    workspace: workspace,
                    category: currentCategory,
                    is_active: cls.indexOf('focusBackground') !== -1,
                });
            } else if (child.children.length > 0) {
                walk(child);
            }
        });
    }

    walk(container);
    return JSON.stringify(sections);
})();
"""


class ListConversationsAction:
    async def execute(self, ctx, params):
        result = await ctx.cdp.execute_js(_JS_LIST_CONVERSATIONS)
        if not result:
            return ActionResult.success(conversations=[])
        try:
            convs = json.loads(result)
        except (json.JSONDecodeError, TypeError):
            convs = []
        return ActionResult.success(conversations=convs)


# ── Select Conversation ──────────────────────────────────────

class SelectConversationAction:
    async def execute(self, ctx, params):
        title = params.get("title", "")
        if not title:
            return ActionResult.fail("title is required")

        escaped = title.replace("'", "\\'")
        ok = await ctx.cdp.execute_js(f"""
            (function() {{
                var all = document.querySelectorAll('div.cursor-pointer');
                var items = Array.from(all).filter(function(d) {{
                    var cls = d.className || '';
                    return cls.indexOf('justify-between') !== -1 &&
                           cls.indexOf('px-2.5') !== -1;
                }});
                var target = items.find(function(d) {{
                    return (d.textContent || '').indexOf('{escaped}') !== -1;
                }});
                if (!target) return false;
                target.click();
                return true;
            }})();
        """)
        if ok == True:
            return ActionResult.success()
        return ActionResult.fail("conversation not found")


# ── Delete Conversation ──────────────────────────────────────

class DeleteConversationAction:
    async def execute(self, ctx, params):
        title = params.get("title", "")
        if not title:
            return ActionResult.fail("title is required")

        escaped = title.replace("'", "\\'")
        ok = await ctx.cdp.execute_js(f"""
            (function() {{
                var all = document.querySelectorAll('div.cursor-pointer');
                var items = Array.from(all).filter(function(d) {{
                    var cls = d.className || '';
                    return cls.indexOf('justify-between') !== -1 &&
                           cls.indexOf('px-2.5') !== -1;
                }});
                var target = items.find(function(d) {{
                    return (d.textContent || '').indexOf('{escaped}') !== -1;
                }});
                if (!target) return false;
                var svgs = target.querySelectorAll('svg');
                if (svgs.length === 0) return false;
                var trashSvg = svgs[svgs.length - 1];
                var clickable = trashSvg.closest('a, button, [role=button]') || trashSvg.parentElement;
                if (clickable) {{ clickable.click(); return true; }}
                return false;
            }})();
        """)
        if ok != True:
            return ActionResult.fail("delete icon not found")

        # Wait for DOM update, then return refreshed list
        await asyncio.sleep(0.3)
        list_action = ListConversationsAction()
        list_result = await list_action.execute(ctx, {})
        return ActionResult.success(
            conversations=list_result.data.get("conversations", []),
        )


# ── Expand Conversations ─────────────────────────────────────

_JS_EXPAND_CONVERSATIONS = r"""
(async function() {
    var allDivs = document.querySelectorAll('div, a, span, button');
    var showMoreBtns = Array.from(allDivs).filter(function(el) {
        var text = (el.textContent || '').trim();
        return /^Show \d+ more/.test(text) && text.length < 30 &&
               el.children.length === 0;
    });
    if (showMoreBtns.length > 0) {
        showMoreBtns[0].click();
        await new Promise(function(r) { setTimeout(r, 500); });
    }
})();
"""


class ExpandConversationsAction:
    async def execute(self, ctx, params):
        await ctx.cdp.execute_js(_JS_EXPAND_CONVERSATIONS)
        list_action = ListConversationsAction()
        return await list_action.execute(ctx, {})


# ── Close Conversation Panel ─────────────────────────────────

class CloseConversationPanelAction:
    async def execute(self, ctx, params):
        ok = await ctx.cdp.execute_js("""
            (function() {
                document.dispatchEvent(new KeyboardEvent('keydown', {
                    key: 'Escape',
                    code: 'Escape',
                    keyCode: 27,
                    which: 27,
                    bubbles: true,
                    cancelable: true,
                }));
                return true;
            })();
        """)
        if ok == True:
            return ActionResult.success()
        return ActionResult.fail("close failed")


# ── Scroll Conversation ──────────────────────────────────────

class ScrollConversationAction:
    async def execute(self, ctx, params):
        from agbridge.collectors import dom_scraper

        direction = params.get("direction", "up")

        height_map = await dom_scraper.get_conversation_height_map(ctx.cdp)
        if not height_map:
            return ActionResult.fail("no conversation container")

        fresh = await dom_scraper.collect_agent_panel(ctx.cdp)
        current_indices = sorted(set(
            m["_ti"] for m in fresh.get("messages", [])
            if "_ti" in m
        ))

        if not current_indices:
            return ActionResult.fail("no active turns")

        # Calculate target index
        if direction == "up":
            target_idx = max(0, min(current_indices) - 3)
        else:
            target_idx = min(
                len(height_map) - 1, max(current_indices) + 3,
            )

        # Already at the boundary
        if direction == "up" and min(current_indices) == 0:
            return ActionResult.success(at_boundary=True)
        if direction == "down" and max(current_indices) >= len(height_map) - 1:
            return ActionResult.success(at_boundary=True)

        target_scroll = height_map[target_idx]["scrollStart"]
        ok = await dom_scraper.scroll_conversation_to(
            ctx.cdp, target_scroll,
        )
        return ActionResult(ok=ok)


# ── Clear Cache ──────────────────────────────────────────────

class ClearCacheAction:
    async def execute(self, ctx, params):
        from agbridge import protocol

        ctx.conversation.clear()

        # Notify TUI: scanning started + empty state
        ctx.push_event(
            protocol.UI_CONV_SCAN_STATE,
            {"scanning": True, "title": ""},
        )
        ctx.push_event(
            protocol.UI_AGENT_UPDATE,
            {"messages": [], "state": "unknown", "_total_turns": 0, "_cached_turns": 0},
        )

        return ActionResult.success()
