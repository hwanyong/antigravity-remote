"""
agbridge.collectors.cdp_actions — CDP-based write operations

All actions execute via CDPBridge.execute_js() — no OS-level focus needed.
Prompt injection uses Lexical's parseEditorState + setEditorState API
to construct the entire editor state deterministically.
Button clicks use DOM element.click() or dispatchEvent(MouseEvent).

Replaces all AX write functions from ax_scraper.py.
"""

import asyncio
import base64
import json
import logging
import os
import re

logger = logging.getLogger("agbridge.cdp_actions")


# ── Lexical Editor Operations ────────────────────────────────

async def inject_prompt(bridge, text):
    """Inject text into Lexical editor and press Send.

    Strategy:
    1. Tokenize: split into text/workflow/mention segments
    2. Build a complete Lexical editor state JSON with proper
       contextScopeItemMention nodes for workflows and text nodes
    3. Apply via parseEditorState + setEditorState (deterministic,
       no clipboard, no typeahead, no timing dependencies)
    4. Click Send button

    Returns:
        bool: True if successful.
    """
    tokens = _tokenize_prompt(text)
    children = _tokens_to_lexical_children(tokens)

    state_dict = {
        "root": {
            "children": [{
                "children": children,
                "direction": "ltr",
                "format": "",
                "indent": 0,
                "type": "paragraph",
                "version": 1,
                "textFormat": 0,
                "textStyle": "",
            }],
            "direction": "ltr",
            "format": "",
            "indent": 0,
            "type": "root",
            "version": 1,
        }
    }

    state_json = json.dumps(state_dict, ensure_ascii=False)
    b64 = base64.b64encode(state_json.encode("utf-8")).decode("ascii")

    result = await bridge.execute_js(f"""
        (function() {{
            var editor = document.querySelector('[data-lexical-editor="true"]');
            if (!editor || !editor.__lexicalEditor) return 'no editor';
            var lex = editor.__lexicalEditor;
            var bin = atob('{b64}');
            var bytes = new Uint8Array(bin.length);
            for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
            var stateJSON = new TextDecoder().decode(bytes);
            var newState = lex.parseEditorState(stateJSON);
            lex.setEditorState(newState);
            return true;
        }})();
    """)

    if result != True:
        logger.error("setEditorState failed: %s", result)
        return False

    # Press Send
    return await press_send(bridge)


async def inject_advanced_prompt(bridge, text):
    """Inject text into Lexical editor WITHOUT pressing Send.
    Used for restoring prompts after an undo action so the user
    can edit their prompt before sending again.
    """
    tokens = _tokenize_prompt(text)
    children = _tokens_to_lexical_children(tokens)

    state_dict = {
        "root": {
            "children": [{
                "children": children,
                "direction": "ltr",
                "format": "",
                "indent": 0,
                "type": "paragraph",
                "version": 1,
                "textFormat": 0,
                "textStyle": "",
            }],
            "direction": "ltr",
            "format": "",
            "indent": 0,
            "type": "root",
            "version": 1,
        }
    }

    state_json = json.dumps(state_dict, ensure_ascii=False)
    b64 = base64.b64encode(state_json.encode("utf-8")).decode("ascii")

    result = await bridge.execute_js(f"""
        (function() {{
            var editor = document.querySelector('[data-lexical-editor="true"]');
            if (!editor || !editor.__lexicalEditor) return 'no editor';
            var lex = editor.__lexicalEditor;
            var bin = atob('{b64}');
            var bytes = new Uint8Array(bin.length);
            for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
            var stateJSON = new TextDecoder().decode(bytes);
            var newState = lex.parseEditorState(stateJSON);
            lex.setEditorState(newState);
            return true;
        }})();
    """)

    if result != True:
        logger.error("setEditorState failed: %s", result)
        return False

    return True


async def clear_message_input(bridge):
    """Clear Lexical editor content.

    Uses select-all + delete approach since Lexical's $getRoot()
    and $createParagraphNode() are module-scoped and unavailable
    from CDP Runtime.evaluate context.
    """
    result = await bridge.execute_js("""
        (function() {
            var editor = document.querySelector('[data-lexical-editor="true"]');
            if (!editor || !editor.__lexicalEditor) return false;
            var lex = editor.__lexicalEditor;

            // Find SELECT_ALL and DELETE_CHARACTER commands
            var selectAllCmd = null;
            var deleteCmd = null;
            lex._commands.forEach(function(v, k) {
                if (k.type === 'SELECT_ALL_COMMAND') selectAllCmd = k;
                if (k.type === 'DELETE_CHARACTER_COMMAND') deleteCmd = k;
            });

            if (!selectAllCmd) return false;
            editor.focus();
            lex.dispatchCommand(selectAllCmd);

            // Delete selected content
            if (deleteCmd) {
                lex.dispatchCommand(deleteCmd, true);
            }
            return true;
        })();
    """)
    return result == True


async def read_input_text(bridge):
    """Read current text from Lexical editor."""
    result = await bridge.execute_js("""
        (function() {
            var editor = document.querySelector('[data-lexical-editor="true"]');
            if (!editor) return '';
            return editor.textContent || '';
        })();
    """)
    return result or ""


# ── Button Click Operations ──────────────────────────────────

async def click_button_by_label(bridge, aria_label):
    """Click button by aria-label. Returns True if found and clicked."""
    result = await bridge.execute_js(f"""
        (function() {{
            var btn = document.querySelector('button[aria-label="{aria_label}"]');
            if (btn && !btn.disabled) {{ btn.click(); return true; }}
            return false;
        }})();
    """)
    return result == True


async def click_button_by_text(bridge, text):
    """Click button by innerText exact match."""
    escaped = text.replace("'", "\\'")
    result = await bridge.execute_js(f"""
        (function() {{
            var btns = Array.from(document.querySelectorAll('button'));
            var btn = btns.find(function(b) {{
                return (b.textContent || '').trim() === '{escaped}';
            }});
            if (btn && !btn.disabled) {{ btn.click(); return true; }}
            return false;
        }})();
    """)
    return result == True


async def press_accept_all(bridge):
    """Click 'Accept all' button."""
    return await click_button_by_text(bridge, "Accept all")


async def press_reject_all(bridge):
    """Click 'Reject all' button."""
    return await click_button_by_text(bridge, "Reject all")


async def press_cancel(bridge):
    """Click Cancel generation button."""
    result = await bridge.execute_js("""
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
    """)
    return result == True


async def press_retry(bridge):
    """Click Retry button."""
    return await click_button_by_text(bridge, "Retry")


async def press_dismiss(bridge):
    """Click Dismiss button."""
    return await click_button_by_text(bridge, "Dismiss")


async def press_allow(bridge):
    """Click Allow or Allow Once button."""
    ok = await click_button_by_text(bridge, "Allow")
    if not ok:
        ok = await click_button_by_text(bridge, "Allow Once")
    return ok


async def press_deny(bridge):
    """Click Deny button."""
    return await click_button_by_text(bridge, "Deny")


async def press_send(bridge):
    """Click Send message button."""
    result = await bridge.execute_js("""
        new Promise((resolve) => {
            function findBtn() {
                var btn = document.querySelector('button[aria-label="Send message"]');
                if (!btn) btn = document.querySelector('[role="button"][aria-label="Send message"]');
                if (!btn) {
                    var btns = Array.from(document.querySelectorAll('button, [role="button"]'));
                    btn = btns.find(function(b) {
                        var text = (b.textContent || '').trim();
                        return text === 'Submit' || text === 'Send' || b.title === 'Send';
                    });
                }
                return btn;
            }

            var btn = findBtn();
            if (btn && !btn.disabled) {
                btn.click();
                resolve(true);
                return;
            }

            var observer = new MutationObserver((mutations) => {
                var b = findBtn();
                if (b && !b.disabled) {
                    observer.disconnect();
                    if (typeof fallbackTimer !== 'undefined') clearTimeout(fallbackTimer);
                    b.click();
                    resolve(true);
                }
            });

            observer.observe(document.body, { 
                childList: true, 
                subtree: true, 
                attributes: true, 
                attributeFilter: ['disabled'] 
            });

            var fallbackTimer = setTimeout(() => {
                observer.disconnect();
                var b = findBtn();
                if (b && !b.disabled) {
                    b.click();
                    resolve(true);
                } else {
                    resolve(false);
                }
            }, 5000);
        });
    """)
    return result == True


# ── Dropdown Operations ──────────────────────────────────────

async def select_model(bridge, model_name):
    """Open model dropdown → find item → click → close."""
    return await _select_dropdown_item(
        bridge, 'button[aria-label*="Select model"]', model_name
    )


async def select_mode(bridge, mode_name):
    """Open mode dropdown → find item → click → close."""
    return await _select_dropdown_item(
        bridge, 'button[aria-label*="conversation mode"]', mode_name
    )


async def list_available_models(bridge):
    """Open model dropdown → read all items → close → return list."""
    return await _list_dropdown_items(
        bridge, 'button[aria-label*="Select model"]'
    )


async def list_available_modes(bridge):
    """Open mode dropdown → read all items → close → return list."""
    return await _list_dropdown_items(
        bridge, 'button[aria-label*="conversation mode"]'
    )


async def _select_dropdown_item(bridge, trigger_selector, item_name):
    """Generic dropdown: open → find item → click → verify."""
    escaped_selector = trigger_selector.replace("'", "\\'")
    js_name = json.dumps(item_name)

    result = await bridge.execute_js(f"""
        (async function() {{
            var trigger = document.querySelector('{escaped_selector}');
            if (!trigger) return false;

            // Open dropdown
            trigger.click();
            await new Promise(function(r) {{ setTimeout(r, 200); }});

            // Find item in popup/listbox
            var items = Array.from(document.querySelectorAll(
                '[role="option"], [role="menuitem"], [role="menuitemradio"], [role="menuitemcheckbox"], [role="listbox"] [role="option"], [role="menu"] button, [role="dialog"] button'
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
                return (item.textContent || '').trim().indexOf({js_name}) !== -1;
            }});

            if (!target) {{
                // Close dropdown by pressing Escape
                document.dispatchEvent(new KeyboardEvent('keydown', {{key: 'Escape', bubbles: true}}));
                return false;
            }}

            target.dispatchEvent(new MouseEvent('mousedown', {{bubbles: true, cancelable: true, view: window}}));
            target.dispatchEvent(new MouseEvent('mouseup', {{bubbles: true, cancelable: true, view: window}}));
            target.click();
            return true;
        }})();
    """)
    return result == True


async def _list_dropdown_items(bridge, trigger_selector):
    """Generic dropdown: open → read items → close → return list."""
    escaped_selector = trigger_selector.replace("'", "\\'")

    result = await bridge.execute_js(f"""
        (async function() {{
            var trigger = document.querySelector('{escaped_selector}');
            if (!trigger) return JSON.stringify([]);

            trigger.click();
            await new Promise(function(r) {{ setTimeout(r, 200); }});

            var items = Array.from(document.querySelectorAll(
                '[role="option"], [role="menuitem"], [role="menuitemradio"], [role="menuitemcheckbox"], [role="listbox"] [role="option"], [role="menu"] button, [role="dialog"] button'
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
    """)

    if not result:
        return []
    try:
        return json.loads(result)
    except (json.JSONDecodeError, TypeError):
        return []


async def press_permission_dropdown_item(bridge, item_text):
    """Open permission chevron → click specific item."""
    escaped = item_text.replace("'", "\\'")

    result = await bridge.execute_js(f"""
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
                return (item.textContent || '').trim().indexOf('{escaped}') !== -1;
            }});

            if (!target) {{
                document.dispatchEvent(new KeyboardEvent('keydown', {{key: 'Escape', bubbles: true}}));
                return false;
            }}

            target.click();
            return true;
        }})();
    """)
    return result == True


# ── Conversation Management ──────────────────────────────────

async def click_new_conversation(bridge):
    """Click new conversation button.

    Antigravity uses <a data-tooltip-id="new-conversation-tooltip">
    which is an <a> tag, not a <button>.
    """
    result = await bridge.execute_js("""
        (function() {
            // Primary: data-tooltip-id attribute (stable Antigravity identifier)
            var btn = document.querySelector('[data-tooltip-id="new-conversation-tooltip"]');
            if (btn) { btn.click(); return true; }

            // Fallback: aria-label
            btn = document.querySelector('[aria-label*="New conversation"], [aria-label*="new conversation"]');
            if (btn) { btn.click(); return true; }

            return false;
        })();
    """)
    return result == True


async def list_conversations(bridge):
    """Read conversation list with rich metadata from Agent Panel sidebar.

    Returns list[dict] with keys:
        title      — conversation title
        time       — relative timestamp (e.g. "2 hrs ago", "now")
        workspace  — workspace path (if different from current)
        category   — section header (Current / Recent in X / Other Conversations)
        is_active  — True if this is the current conversation

    Conversation items reside in the DOM as cursor-pointer divs
    grouped under category headers inside a scrollable container.

    Returns a mixed list:
      - {type: "conversation", title, time, workspace, category, is_active}
      - {type: "show_more", text: "Show 33 more..."}
    """
    result = await bridge.execute_js("""
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
                    var showMoreMatch = text.match(/^Show (\\d+) more/);
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
                            if (!time && /^(now|\\d+\\s*(min|hr|day|week|month)s?\\s*ago)$/.test(st)) {
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
    """)
    if not result:
        return []
    try:
        return json.loads(result)
    except (json.JSONDecodeError, TypeError):
        return []


async def expand_conversations(bridge):
    """Click 'Show N more...' in the current workspace section, then re-scrape.

    Returns the updated conversation list with all items visible.
    """
    await bridge.execute_js("""
        (async function() {
            // Find all "Show N more..." clickable elements
            var allDivs = document.querySelectorAll('div, a, span, button');
            var showMoreBtns = Array.from(allDivs).filter(function(el) {
                var text = (el.textContent || '').trim();
                return /^Show \\d+ more/.test(text) && text.length < 30 &&
                       el.children.length === 0;
            });

            // Click only the first one (current workspace section)
            if (showMoreBtns.length > 0) {
                showMoreBtns[0].click();
                await new Promise(function(r) { setTimeout(r, 500); });
            }
        })();
    """)


async def close_conversation_panel(bridge):
    """Close the conversation history panel/modal in Antigravity IDE.

    Dispatches Escape key to dismiss the 'Select a conversation' overlay.
    Called when TUI's ConversationModal is dismissed so the IDE stays in sync.
    """
    result = await bridge.execute_js("""
        (function() {
            // Dispatch Escape to close any modal/overlay
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
    return result == True


async def select_conversation_by_title(bridge, title):
    """Click a conversation item by title.

    Items are always-present <div> elements — no toggle needed.
    """
    escaped = title.replace("'", "\\'")

    result = await bridge.execute_js(f"""
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
    return result == True


async def delete_conversation(bridge, title):
    """Click the delete (trash) icon for a conversation by title.

    Each conversation item contains an <svg> trash icon that becomes
    visible on hover. We locate the item by title, then click the SVG
    parent (the clickable wrapper).
    """
    escaped = title.replace("'", "\\'")

    result = await bridge.execute_js(f"""
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

            // Find the delete icon (SVG) and its clickable parent
            var svgs = target.querySelectorAll('svg');
            if (svgs.length === 0) return false;

            // The last SVG is typically the trash icon
            var trashSvg = svgs[svgs.length - 1];
            var clickable = trashSvg.closest('a, button, [role=button]') || trashSvg.parentElement;
            if (clickable) {{
                clickable.click();
                return true;
            }}
            return false;
        }})();
    """)
    return result == True


# ── Undo Operations ──────────────────────────────────────────

async def press_undo_for_message(bridge, message_index):
    """Click undo button for specific message by index."""
    result = await bridge.execute_js(f"""
        (function() {{
            var conv = document.getElementById('conversation');
            if (!conv) return false;

            // Find all undo buttons - new UI uses div[role="button"] with data-tooltip-id
            var undoBtns = Array.from(conv.querySelectorAll(
                'button[aria-label*="undo"], button[aria-label*="Undo"], div[role="button"][data-tooltip-id*="undo"]'
            ));

            // Also try icon-based or text-based undo buttons as fallback
            if (undoBtns.length === 0) {{
                var allBtns = Array.from(conv.querySelectorAll('button, div[role="button"]'));
                undoBtns = allBtns.filter(function(b) {{
                    return (b.textContent || '').indexOf('↩') !== -1 ||
                           (b.getAttribute('title') || '').indexOf('undo') !== -1 ||
                           (b.getAttribute('title') || '').indexOf('Undo') !== -1;
                }});
            }}

            var idx = {message_index};
            if (idx < 0 || idx >= undoBtns.length) return false;

            undoBtns[idx].click();
            return true;
        }})();
    """)
    return result == True


async def detect_confirm_undo_dialog(bridge):
    """Check if Confirm Undo modal is present."""
    from agbridge.collectors.dom_scraper import detect_confirm_undo_dialog as _detect
    return await _detect(bridge)


async def press_confirm_undo(bridge):
    """Click Confirm button in undo dialog."""
    result = await bridge.execute_js("""
        (function() {
            var dialogs = document.querySelectorAll('div.fixed.inset-0, [role="dialog"], [class*="modal"], [class*="overlay"]');
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
    return result == True


async def press_cancel_undo(bridge):
    """Click Cancel button in undo dialog."""
    result = await bridge.execute_js("""
        (function() {
            var dialogs = document.querySelectorAll('div.fixed.inset-0, [role="dialog"], [class*="modal"], [class*="overlay"]');
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
    return result == True



# ── Lexical State Builder ─────────────────────────────────────

_GLOBAL_WORKFLOWS_DIR = os.path.expanduser(
    "~/.gemini/antigravity/global_workflows"
)

_FM_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)
_DESC_RE = re.compile(r"description:\s*(.+)")


def _resolve_workflow_recipe(name):
    """Read workflow file and construct recipe data.

    Returns:
        dict with recipeId, title, description, systemPrompt, uri.
        None if workflow file not found.
    """
    path = os.path.join(_GLOBAL_WORKFLOWS_DIR, f"{name}.md")
    if not os.path.isfile(path):
        return None

    with open(path, encoding="utf-8") as f:
        content = f.read()

    description = ""
    system_prompt = content

    fm_match = _FM_RE.match(content)
    if fm_match:
        fm_block = fm_match.group(1)
        desc_match = _DESC_RE.search(fm_block)
        if desc_match:
            description = desc_match.group(1).strip()
        system_prompt = content[fm_match.end():].strip()

    return {
        "recipeId": path,
        "title": name,
        "description": description,
        "systemPrompt": system_prompt,
        "uri": f"file://{path}",
    }


def _tokens_to_lexical_children(tokens):
    """Convert token list to Lexical paragraph children nodes.

    Returns:
        list[dict]: Lexical node JSON objects.
    """
    children = []

    for token_type, token_value in tokens:
        if token_type == "text":
            children.append({
                "detail": 0,
                "format": 0,
                "mode": "normal",
                "style": "",
                "text": token_value,
                "type": "text",
                "version": 1,
            })

        elif token_type == "workflow":
            recipe = _resolve_workflow_recipe(token_value)
            if not recipe:
                logger.warning(
                    "Workflow not found, inserting as text: %s",
                    token_value,
                )
                children.append({
                    "detail": 0, "format": 0, "mode": "normal",
                    "style": "", "type": "text", "version": 1,
                    "text": f"@[/{token_value}]",
                })
                continue

            children.append({
                "type": "contextScopeItemMention",
                "trigger": "@",
                "value": "contextScopeItemMention",
                "version": 1,
                "data": {
                    "mentionText": token_value,
                    "data": json.dumps(
                        {"recipe": recipe}, ensure_ascii=False,
                    ),
                },
            })

        elif token_type == "mention":
            # File/path mentions — insert as plain text for now.
            # TODO: implement file mention node creation when needed.
            children.append({
                "detail": 0, "format": 0, "mode": "normal",
                "style": "", "type": "text", "version": 1,
                "text": f"@[{token_value}]",
            })

    return children


# ── Prompt Tokenizer ─────────────────────────────────────────

_DIRECTIVE_RE = re.compile(r"@\[(/[^\]]+)\]|@\[([^\]]+)\]")


def _tokenize_prompt(text):
    """Split prompt text into (type, value) tokens.

    Recognizes:
        @[/workflow_name] → ("workflow", "workflow_name")
        @[path/to/file]   → ("mention", "path/to/file")
        plain text         → ("text", "the text")

    All text segments are preserved including whitespace-only tokens,
    since the Lexical state builder needs them as explicit text nodes.

    Returns:
        list[tuple[str, str]]
    """
    tokens = []
    last_end = 0

    for match in _DIRECTIVE_RE.finditer(text):
        start = match.start()

        if start > last_end:
            tokens.append(("text", text[last_end:start]))

        if match.group(1):
            tokens.append(("workflow", match.group(1).lstrip("/")))
        elif match.group(2):
            tokens.append(("mention", match.group(2)))

        last_end = match.end()

    if last_end < len(text):
        tokens.append(("text", text[last_end:]))

    if not tokens:
        tokens.append(("text", text))

    return tokens
