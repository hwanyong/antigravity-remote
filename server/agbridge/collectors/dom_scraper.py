"""
agbridge.collectors.dom_scraper — CDP DOM-based UI data extraction

Replaces ax_scraper.py entirely. All functions are async and take
a CDPBridge instance. Return structures are 100% compatible with
the former AX version, ensuring zero TUI client changes.

Design:
  - Each function executes a single JS snippet via CDPBridge.execute_js()
  - DOM parsing happens inside the Renderer (no multi-roundtrip)
  - Results are JSON-serialized in JS and parsed in Python
"""

import asyncio
import json
import logging

logger = logging.getLogger("agbridge.dom_scraper")


# ── Main Collection ──────────────────────────────────────────

_COLLECT_AGENT_PANEL_JS = """
(function() {
    var conv = document.getElementById('conversation');
    if (!conv) return JSON.stringify({
        state: 'unknown', conversation_title: '', current_model: '',
        current_mode: '', messages: [], error_info: null, permission_info: null,
    });

    // ── HTML to Markdown converter ────────────────────────
    // Recursively walks DOM nodes and produces Markdown text.
    // Skips non-content elements (buttons, style, svg, etc.)

    function h2m(el) {
        if (!el) return '';
        if (el.nodeType === 3) return el.textContent;
        if (el.nodeType !== 1) return '';
        var tag = el.tagName;

        // Skip non-content elements
        if (tag === 'BUTTON' || tag === 'SCRIPT' || tag === 'STYLE' ||
            tag === 'SVG' || tag === 'INPUT' || tag === 'SUMMARY') return '';

        // Code blocks — must be handled before generic recursion
        if (tag === 'PRE') {
            var codeEl = el.querySelector('code');
            var lang = '';
            if (codeEl) {
                var cls = codeEl.className || '';
                var m = cls.match(/language-(\\w+)/);
                if (m) lang = m[1];
                return '\\n```' + lang + '\\n' + codeEl.textContent + '\\n```\\n';
            }
            return '\\n```\\n' + el.textContent + '\\n```\\n';
        }
        if (tag === 'CODE') return '`' + el.textContent + '`';
        if (tag === 'DETAILS') return ''; // Skip collapsible (thinking)

        // Recurse children
        var inner = '';
        for (var i = 0; i < el.childNodes.length; i++) {
            inner += h2m(el.childNodes[i]);
        }

        switch (tag) {
            case 'H1': return '\\n# ' + inner.trim() + '\\n\\n';
            case 'H2': return '\\n## ' + inner.trim() + '\\n\\n';
            case 'H3': return '\\n### ' + inner.trim() + '\\n\\n';
            case 'H4': return '\\n#### ' + inner.trim() + '\\n\\n';
            case 'H5': return '\\n##### ' + inner.trim() + '\\n\\n';
            case 'P': return inner.trim() + '\\n\\n';
            case 'BR': return '\\n';
            case 'STRONG': case 'B': return '**' + inner + '**';
            case 'EM': case 'I': return '*' + inner + '*';
            case 'A':
                var href = el.getAttribute('href') || '';
                if (!href || href === '#') return inner;
                return '[' + inner.trim() + '](' + href + ')';
            case 'BLOCKQUOTE':
                var bLines = inner.trim().split('\\n');
                return '\\n' + bLines.map(function(l) { return '> ' + l; }).join('\\n') + '\\n\\n';
            case 'UL': {
                var uItems = [];
                for (var u = 0; u < el.children.length; u++) {
                    if (el.children[u].tagName === 'LI')
                        uItems.push('- ' + h2m(el.children[u]).trim());
                }
                return '\\n' + uItems.join('\\n') + '\\n\\n';
            }
            case 'OL': {
                var oItems = [];
                for (var o = 0; o < el.children.length; o++) {
                    if (el.children[o].tagName === 'LI')
                        oItems.push((o + 1) + '. ' + h2m(el.children[o]).trim());
                }
                return '\\n' + oItems.join('\\n') + '\\n\\n';
            }
            case 'TABLE': {
                var tRows = el.querySelectorAll('tr');
                if (tRows.length === 0) return inner;
                var tResult = '\\n';
                for (var r = 0; r < tRows.length; r++) {
                    var cells = tRows[r].querySelectorAll('th, td');
                    var row = '|';
                    for (var c = 0; c < cells.length; c++) {
                        row += ' ' + h2m(cells[c]).trim().replace(/\\|/g, '\\\\|') + ' |';
                    }
                    tResult += row + '\\n';
                    if (r === 0) {
                        var sep = '|';
                        for (var c = 0; c < cells.length; c++) sep += '---|';
                        tResult += sep + '\\n';
                    }
                }
                return tResult + '\\n';
            }
            case 'HR': return '\\n---\\n\\n';
            default: return inner;
        }
    }


    // ── 1. State detection ───────────────────────────────
    // Scoped to the input box container to avoid false positives
    // from Cancel buttons in Accept/Reject areas.
    var state = 'unknown';
    var inputBox = document.getElementById('antigravity.agentSidePanelInputBox');
    if (inputBox) {
        // Walk up to the toolbar container (justify-between)
        var toolbar = inputBox;
        for (var up = 0; up < 5 && toolbar; up++) {
            var tcls = (toolbar.className || '').toString();
            if (tcls.indexOf('justify-between') !== -1) break;
            toolbar = toolbar.parentElement;
        }
        if (toolbar) {
            var sendBtn = toolbar.querySelector('button[aria-label="Send message"]');
            if (!sendBtn) {
                var tBtns = toolbar.querySelectorAll('button');
                for (var bi = 0; bi < tBtns.length; bi++) {
                    var btnText = (tBtns[bi].textContent || '').trim();
                    if (btnText === 'Submit') { sendBtn = tBtns[bi]; break; }
                }
            }
            var cancelBtn = toolbar.querySelector('button[aria-label="Cancel generation"]');
            if (!cancelBtn) {
                cancelBtn = toolbar.querySelector('button[aria-label="Cancel"]');
            }
            if (cancelBtn && cancelBtn.offsetParent !== null) {
                state = 'generating';
            } else if (sendBtn && sendBtn.offsetParent !== null) {
                state = 'idle';
            } else if (cancelBtn) {
                // If cancel button is in DOM but hidden, state is idle
                state = 'idle';
            } else if (sendBtn) {
                state = 'idle';
            }
        }
    }

    // ── 2. Error detection ───────────────────────────────
    var errorInfo = null;
    var allHeadings = conv.querySelectorAll('h1, h2, h3, h4');
    for (var h = 0; h < allHeadings.length; h++) {
        if (allHeadings[h].textContent.indexOf('terminated') !== -1 ||
            allHeadings[h].textContent.indexOf('error') !== -1) {
            errorInfo = {heading: allHeadings[h].textContent.trim()};
            if (state !== 'generating') state = 'error';
            break;
        }
    }

    // ── 3. Permission detection ──────────────────────────
    var permInfo = null;
    var allBtns = Array.from(document.querySelectorAll('button'));
    var allowBtn = allBtns.find(function(b) {
        var label = b.getAttribute('aria-label') || b.textContent || '';
        return label.indexOf('Allow') !== -1;
    });
    var denyBtn = allBtns.find(function(b) {
        return (b.textContent || '').trim() === 'Deny';
    });
    if (allowBtn && denyBtn && state !== 'error' && state !== 'generating') {
        state = 'permission_required';
        var permContainer = allowBtn.closest('[class*="permission"], [class*="banner"]');
        var permText = '';
        if (permContainer) {
            permText = permContainer.textContent.substring(0, 500);
        } else {
            var parent = allowBtn.parentElement;
            for (var up = 0; up < 5 && parent; up++) {
                var pText = parent.textContent || '';
                if (pText.length > 50) {
                    permText = pText.substring(0, 500);
                    break;
                }
                parent = parent.parentElement;
            }
        }
        permInfo = {
            description: permText.trim(),
            has_allow: true,
            has_deny: true,
        };
    }

    // ── 4. Model / Mode ─────────────────────────────────
    var modelBtn = document.querySelector('button[aria-label*="Select model"]');
    var currentModel = '';
    var currentMode = '';
    if (modelBtn) {
        var mLabel = modelBtn.getAttribute('aria-label') || '';
        var mMatch = mLabel.match(/current:\\s*(.+)/);
        if (mMatch) currentModel = mMatch[1].trim();
        // Mode is now a chip rendered as a sibling of the model button's wrapper
        var modeContainer = modelBtn.parentElement
            ? modelBtn.parentElement.closest('.flex.items-center.gap-1')
            : null;
        if (modeContainer) {
            var modeChips = modeContainer.querySelectorAll('.group.transition-colors');
            if (modeChips.length > 0) {
                var modeSpan = modeChips[0].querySelector('span.select-none');
                if (modeSpan) currentMode = modeSpan.textContent.trim();
            }
        }
    }

    // ── 5. Conversation title ────────────────────────────
    var convTitle = '';
    var panel = document.querySelector('.antigravity-agent-side-panel');
    if (panel) {
        var candidates = panel.querySelectorAll('div');
        for (var ci = 0; ci < candidates.length; ci++) {
            var cd = candidates[ci];
            if (conv.contains(cd)) continue;
            var ccls = cd.className || '';
            if (ccls.indexOf('overflow-hidden') !== -1 &&
                ccls.indexOf('text-ellipsis') !== -1) {
                var titleText = (cd.textContent || '').trim();
                if (titleText.length > 3 && titleText.length < 150) {
                    convTitle = titleText;
                    break;
                }
            }
        }
    }
    if (!convTitle) {
        var titleEl = conv.querySelector('h1, h2');
        convTitle = titleEl ? titleEl.textContent.trim() : '';
    }

    // ── 6. Messages — Turn-based extraction ──────────────
    // Antigravity DOM structure:
    //   #conversation > div... > div[class*="gap-y-"] (message container)
    //     > div.flex-col.gap-0.5 (individual turn)
    //       > div.sticky (user prompt header)
    //       > div (tool summaries, response content, thinking)
    var messages = [];

    // 6a. Find the message container (div with gap-y-* + px-* classes)
    var msgContainer = null;
    var allDivs = conv.querySelectorAll('div');
    for (var gi = 0; gi < allDivs.length; gi++) {
        var gcls = (allDivs[gi].className || '').toString();
        if (gcls.indexOf('gap-y-') !== -1 && gcls.indexOf('px-') !== -1) {
            // Verify it has turn-like children
            if (allDivs[gi].children.length >= 1) {
                msgContainer = allDivs[gi];
                break;
            }
        }
    }

    // Fallback: walk single-child chain from #conversation
    if (!msgContainer) {
        var walker = conv;
        while (walker && walker.children.length <= 2) {
            var picked = null;
            for (var wi = 0; wi < walker.children.length; wi++) {
                if ((walker.children[wi].textContent || '').trim().length > 100) {
                    picked = walker.children[wi];
                    break;
                }
            }
            if (!picked) break;
            walker = picked;
        }
        if (walker !== conv && walker.children.length > 1) {
            if (walker.querySelector('.sticky')) {
                msgContainer = walker;
            }
        }
    }

    // 6b. Parse each turn
    if (msgContainer) {
        for (var ti = 0; ti < msgContainer.children.length; ti++) {
            var turn = msgContainer.children[ti];
            // New IDE: turn might be wrapped in div.flex.items-start
            if (turn && turn.children && turn.children.length > 0) {
                var innerTurn = turn.querySelector('.group.flex-col') || turn.children[0];
                if (innerTurn && innerTurn.children && innerTurn.children.length >= 1) {
                    turn = innerTurn;
                }
            }
            var turnText = (turn.textContent || '').trim();
            if (turnText.length < 3) continue;

            // Separate sticky header from content blocks
            var stickyEl = null;
            var contentBlocks = [];

            for (var tc = 0; tc < turn.children.length; tc++) {
                var tChild = turn.children[tc];
                var tCls = (tChild.className || '').toString();
                if (tCls.indexOf('sticky') !== -1) {
                    stickyEl = tChild;
                } else {
                    contentBlocks.push(tChild);
                }
            }

            // ── User prompt (from sticky header) ──
            if (stickyEl) {
                var promptText = '';
                // Prefer whitespace-pre-wrap div (exact prompt text)
                var preWrap = stickyEl.querySelector('[class*="pre-wrap"]');
                if (preWrap) {
                    // Clone to avoid mutating the live DOM
                    var pwClone = preWrap.cloneNode(true);
                    // Reconstruct pill syntax from mention spans
                    // Classification: icon present → file/dir mention, no icon → workflow
                    var mentions = pwClone.querySelectorAll('.context-scope-mention');
                    for (var mi = 0; mi < mentions.length; mi++) {
                        var mText = mentions[mi].textContent.trim();
                        var hasIcon = mentions[mi].querySelector('img, svg') !== null;
                        var pill = hasIcon ? ('@[' + mText + ']') : ('@[/' + mText + ']');
                        var replacement = document.createTextNode(pill);
                        mentions[mi].replaceWith(replacement);
                    }
                    promptText = pwClone.textContent.trim();
                } else {
                    // Fallback: clone sticky, remove buttons, get text
                    var sClone = stickyEl.cloneNode(true);
                    var sBtns = sClone.querySelectorAll('button');
                    for (var sb = 0; sb < sBtns.length; sb++) {
                        if (sBtns[sb].parentElement)
                            sBtns[sb].parentElement.removeChild(sBtns[sb]);
                    }
                    promptText = sClone.textContent.trim();
                }
                // Remove trailing "undo" from button text leak
                promptText = promptText.replace(/\\s*undo\\s*$/i, '').trim();

                if (promptText) {
                    messages.push({
                        role: 'user',
                        content: promptText,
                        thinking: null,
                        actions: [],
                        files_modified: [],
                        _ti: ti,
                    });
                }
            }

            // ── Assistant response (from content blocks) ──
            var responseMd = '';
            var thinking = null;
            var filesModified = [];

            for (var cb = 0; cb < contentBlocks.length; cb++) {
                var block = contentBlocks[cb];
                var blockText = (block.textContent || '').trim();

                // Detect thinking block (has "Thought for" + <details>)
                if (blockText.indexOf('Thought for') !== -1 &&
                    block.querySelector('details')) {
                    var detailsEl = block.querySelector('details');
                    if (detailsEl) {
                        var summaryEl = detailsEl.querySelector('summary');
                        var thinkContent = detailsEl.textContent.trim();
                        if (summaryEl) {
                            thinkContent = thinkContent
                                .replace(summaryEl.textContent, '').trim();
                        }
                        if (thinkContent) thinking = thinkContent;
                    }
                    continue;
                }

                // Convert every block to markdown — no filtering.
                // DOM content is the source of truth.
                responseMd += h2m(block);

                // Collect file links
                var fLinks = block.querySelectorAll('a[href*="file://"]');
                for (var fl = 0; fl < fLinks.length; fl++) {
                    var fName = fLinks[fl].textContent.trim();
                    if (fName) filesModified.push(fName);
                }
            }

            if (responseMd.trim()) {
                // Post-process: collapse excessive blank lines (max 2 consecutive)
                var cleaned = responseMd
                    .replace(/\\n{4,}/g, '\\n\\n\\n')
                    .replace(/  +/g, ' ');

                // Strip CSS artifacts that leak from code block wrappers
                cleaned = cleaned.replace(
                    /\\.code-block[\\s\\S]*?\\}[\\s\\S]*?\\}/g, ''
                ).replace(
                    /::selection\\s*\\{[^}]*\\}/g, ''
                ).trim();

                messages.push({
                    role: 'assistant',
                    content: cleaned,
                    thinking: thinking,
                    actions: [],
                    files_modified: filesModified,
                    _ti: ti,
                });
            }
        }
    }
    return JSON.stringify({
        state: state,
        conversation_title: convTitle,
        current_model: currentModel,
        current_mode: currentMode,
        messages: messages,
        error_info: errorInfo,
        permission_info: permInfo,
        _total_turns: msgContainer ? msgContainer.children.length : 0,
    });
})();
"""


async def collect_agent_panel(bridge):
    """Collect full Agent Panel state via CDP DOM query.

    Returns dict identical to the former ax_scraper.collect_agent_panel():
    {
        "state": "idle"|"generating"|"permission_required"|"error"|"unknown",
        "conversation_title": str,
        "current_model": str,
        "current_mode": str,
        "messages": [{role, content, thinking, actions, files_modified}],
        "error_info": dict|None,
        "permission_info": dict|None,
    }
    """
    raw = await bridge.execute_js(_COLLECT_AGENT_PANEL_JS)
    if not raw:
        return {
            "state": "unknown",
            "conversation_title": "",
            "current_model": "",
            "current_mode": "",
            "messages": [],
            "error_info": None,
            "permission_info": None,
        }

    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("DOM scraper: invalid JSON from collect_agent_panel")
        return {
            "state": "unknown",
            "conversation_title": "",
            "current_model": "",
            "current_mode": "",
            "messages": [],
            "error_info": None,
            "permission_info": None,
        }

# ── Scroll Synchronization ───────────────────────────────────

_HEIGHT_MAP_JS = """
(function() {
    var conv = document.getElementById('conversation');
    if (!conv) return '[]';

    var container = null;
    var divs = conv.querySelectorAll('div');
    for (var i = 0; i < divs.length; i++) {
        var cls = (divs[i].className || '').toString();
        if (cls.indexOf('gap-y-') !== -1 && cls.indexOf('px-') !== -1) {
            if (divs[i].children.length >= 1) {
                container = divs[i];
                break;
            }
        }
    }

    if (!container) {
        var walker = conv;
        while (walker && walker.children.length <= 2) {
            var picked = null;
            for (var wi = 0; wi < walker.children.length; wi++) {
                if ((walker.children[wi].textContent || '').trim().length > 100) {
                    picked = walker.children[wi];
                    break;
                }
            }
            if (!picked) break;
            walker = picked;
        }
        if (walker !== conv && walker.children.length > 1) {
            if (walker.querySelector('.sticky')) {
                container = walker;
            } else {
                return '"__EMPTY_PLACEHOLDER__"';
            }
        }
    }

    if (!container) return '[]';

    var heights = [];
    var cumulative = 0;
    for (var i = 0; i < container.children.length; i++) {
        var child = container.children[i];
        var style = child.getAttribute('style') || '';
        var hMatch = style.match(/height:\\s*([\\d.]+)px/);
        var h = hMatch ? parseFloat(hMatch[1]) : child.offsetHeight;
        heights.push({
            idx: i,
            height: Math.round(h),
            scrollStart: Math.round(cumulative),
        });
        cumulative += h;
    }
    return JSON.stringify(heights);
})();
"""


async def get_conversation_height_map(bridge):
    """Retrieve the height map for all conversation turns.

    Returns list of dicts: [{idx, height, scrollStart}, ...]
    Used to calculate scroll position for a specific turn index.
    """
    raw = await bridge.execute_js(_HEIGHT_MAP_JS)
    if not raw:
        return []
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []


async def scroll_conversation_to(bridge, scroll_top):
    """Programmatically scroll the IDE conversation to a specific position.

    The IDE's virtual scroller will mount/unmount turns in response,
    and the existing MutationObserver will automatically fire an "agent"
    section event, triggering re-scraping through the normal pipeline.

    Args:
        bridge: CDPBridge instance.
        scroll_top: Target scrollTop value in pixels.

    Returns:
        True if scroll was executed.
    """
    result = await bridge.execute_js(f"""
        (function() {{
            var conv = document.getElementById('conversation');
            if (!conv) return 'false';
            var s = conv.querySelector('[class*="overflow-y-auto"]');
            if (!s) return 'false';
            s.scrollTop = {scroll_top};
            return 'true';
        }})();
    """)
    return result == "true"


async def full_scan_conversation(bridge, settle_ms=150):
    """Scroll through the entire IDE conversation and collect all turns.

    Performs a background scan from top to bottom, scraping visible
    turns at each scroll position. Returns a complete, deduplicated,
    ordered list of all messages with their turn indices.

    Args:
        bridge: CDPBridge instance.
        settle_ms: Milliseconds to wait after each scroll for rendering.

    Returns:
        dict with keys:
            messages: Complete ordered list of messages.
            total_turns: Total number of turns.
            conversation_title: Current conversation title.
            state: Current conversation state.
    """
    height_map = await get_conversation_height_map(bridge)
    if not height_map:
        return {"messages": [], "total_turns": 0}

    total_turns = len(height_map)
    turn_data = {}  # ti → list of messages (dedup by replacement)
    conv_title = ""
    state = "unknown"
    settle_s = settle_ms / 1000

    i = 0
    while i < total_turns:
        scroll_pos = height_map[i]["scrollStart"]
        await scroll_conversation_to(bridge, scroll_pos)
        await asyncio.sleep(settle_s)

        data = await collect_agent_panel(bridge)
        msgs = data.get("messages", [])

        if not conv_title:
            conv_title = data.get("conversation_title", "")
        state = data.get("state", state)

        # Group by _ti, replacing any previous data for each turn
        scraped_tis = set()
        for msg in msgs:
            ti = msg.pop("_ti", -1)
            if ti < 0:
                continue
            turn_data.setdefault(ti, [])
            # Only add if role not already present for this turn
            existing_roles = {m["role"] for m in turn_data[ti]}
            if msg["role"] not in existing_roles:
                turn_data[ti].append(msg)
            scraped_tis.add(ti)

        # Jump past the last scraped turn
        if scraped_tis:
            i = max(scraped_tis) + 1
        else:
            i += 1

    # Restore scroll to bottom
    total_height = sum(h["height"] for h in height_map)
    await scroll_conversation_to(bridge, total_height)

    # Flatten into ordered message list
    flat = []
    for ti in sorted(turn_data.keys()):
        for msg in turn_data[ti]:
            flat.append({**msg, "_turn_idx": ti})

    return {
        "messages": flat,
        "total_turns": total_turns,
        "conversation_title": conv_title,
        "state": state,
    }


# ── Individual Queries ───────────────────────────────────────

_CONVERSATION_STATE_JS = """
(function() {
    var cancelBtn = document.querySelector('button[aria-label="Cancel generation"]');
    // New IDE: Cancel aria-label
    if (!cancelBtn) {
        cancelBtn = document.querySelector('button[aria-label="Cancel"]');
    }
    if (cancelBtn) return 'generating';

    var headings = document.querySelectorAll('h1, h2, h3, h4');
    for (var i = 0; i < headings.length; i++) {
        if (headings[i].textContent.indexOf('terminated') !== -1 ||
            headings[i].textContent.indexOf('error') !== -1) {
            return 'error';
        }
    }

    var btns = Array.from(document.querySelectorAll('button'));
    var allow = btns.find(function(b) {
        return (b.getAttribute('aria-label') || b.textContent || '').indexOf('Allow') !== -1;
    });
    var deny = btns.find(function(b) { return (b.textContent || '').trim() === 'Deny'; });
    if (allow && deny) return 'permission_required';

    var sendBtn = document.querySelector('button[aria-label="Send message"]');
    // New IDE: Mic button when empty
    if (!sendBtn) {
        sendBtn = document.querySelector('button[aria-label="Record voice memo"]');
    }
    // New IDE: Submit text button
    if (!sendBtn) {
        var allBtns2 = document.querySelectorAll('button');
        for (var bi2 = 0; bi2 < allBtns2.length; bi2++) {
            if ((allBtns2[bi2].textContent || '').trim() === 'Submit') {
                sendBtn = allBtns2[bi2]; break;
            }
        }
    }
    if (sendBtn) return 'idle';

    return 'unknown';
})();
"""


async def get_conversation_state(bridge):
    """Detect idle/generating/error/permission_required."""
    result = await bridge.execute_js(_CONVERSATION_STATE_JS)
    return result or "unknown"


_EDIT_ACTIONS_JS = """
(function() {
    var result = {has_accept: false, has_reject: false, files: []};
    var btns = Array.from(document.querySelectorAll('button'));

    var accept = btns.find(function(b) {
        return (b.textContent || '').trim() === 'Accept all';
    });
    var reject = btns.find(function(b) {
        return (b.textContent || '').trim() === 'Reject all';
    });

    result.has_accept = !!accept;
    result.has_reject = !!reject;

    // Find modified files list near accept/reject buttons
    if (accept) {
        var container = accept.closest('[class*="edit"], [class*="changes"]');
        if (container) {
            var fileEls = container.querySelectorAll('[class*="file"], li, a');
            for (var i = 0; i < fileEls.length; i++) {
                var text = fileEls[i].textContent.trim();
                if (text && text.indexOf('/') !== -1) {
                    result.files.push(text);
                }
            }
        }
    }

    return JSON.stringify(result);
})();
"""


async def collect_edit_actions(bridge):
    """Find Accept all / Reject all buttons and file change list."""
    raw = await bridge.execute_js(_EDIT_ACTIONS_JS)
    if not raw:
        return {"has_accept": False, "has_reject": False, "files": []}

    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"has_accept": False, "has_reject": False, "files": []}


_ACTIVE_EDITOR_JS = """
(function() {
    // Find active editor tab
    var tabs = document.querySelectorAll('[role="tab"][aria-selected="true"]');
    if (tabs.length === 0) return JSON.stringify({filename: '', path: '', language: ''});

    var tab = tabs[0];
    var label = tab.getAttribute('aria-label') || tab.textContent || '';
    var filename = label.split(',')[0].trim();

    return JSON.stringify({
        filename: filename,
        path: '',
        language: '',
    });
})();
"""


async def get_active_editor_info(bridge):
    """Extract current editor tab information."""
    raw = await bridge.execute_js(_ACTIVE_EDITOR_JS)
    if not raw:
        return {"filename": "", "path": "", "language": ""}

    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"filename": "", "path": "", "language": ""}


_MODELS_AND_MODES_JS = """
(function() {
    var modelBtn = document.querySelector('button[aria-label*="Select model"]');
    var currentModel = '';
    var currentMode = '';
    if (modelBtn) {
        var mLabel = modelBtn.getAttribute('aria-label') || '';
        var mMatch = mLabel.match(/current:\\s*(.+)/);
        if (mMatch) currentModel = mMatch[1].trim();
        // Mode is now a chip rendered as a sibling of the model button's wrapper
        var modeContainer = modelBtn.parentElement
            ? modelBtn.parentElement.closest('.flex.items-center.gap-1')
            : null;
        if (modeContainer) {
            var modeChips = modeContainer.querySelectorAll('.group.transition-colors');
            if (modeChips.length > 0) {
                var modeSpan = modeChips[0].querySelector('span.select-none');
                if (modeSpan) currentMode = modeSpan.textContent.trim();
            }
        }
    }
    return JSON.stringify({current_model: currentModel, current_mode: currentMode});
})();
"""


async def collect_models_and_modes(bridge):
    """Read current model and mode from aria-label attributes."""
    raw = await bridge.execute_js(_MODELS_AND_MODES_JS)
    if not raw:
        return {"current_model": "", "current_mode": ""}

    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"current_model": "", "current_mode": ""}


_CONFIRM_UNDO_DIALOG_JS = """
(function() {
    var dialogs = document.querySelectorAll('div.fixed.inset-0, [role="dialog"], [class*="modal"], [class*="overlay"]');
    var targetDialog = null;
    for (var i = 0; i < dialogs.length; i++) {
        var headings = dialogs[i].querySelectorAll('h1, h2, h3, h4');
        for (var j = 0; j < headings.length; j++) {
            if (headings[j].textContent.indexOf('Confirm Undo') !== -1) {
                targetDialog = dialogs[i];
                break;
            }
        }
        if (targetDialog) break;
    }
    
    if (targetDialog) {
        var btns = targetDialog.querySelectorAll('button, [role="button"]');
        var hasConfirm = false;
        var hasCancel = false;
        for (var b = 0; b < btns.length; b++) {
            var btnText = (btns[b].textContent || '').trim();
            if (btnText === 'Confirm' || btnText.indexOf('Confirm') !== -1) hasConfirm = true;
            if (btnText === 'Cancel') hasCancel = true;
        }

        if (hasConfirm) {
            var file_changes = [];
            var fileRows = targetDialog.querySelectorAll('div[class*="group/file-summary"]');
            for (var r=0; r<fileRows.length; r++) {
                var container = fileRows[r].querySelector('span.flex.items-baseline');
                if (container) {
                    var spans = container.querySelectorAll('span');
                    if (spans.length >= 2) {
                        var fName = spans[0].textContent.trim();
                        var fAction = spans[1].textContent.trim();
                        file_changes.push({
                            file: fName,
                            detail: fName + " (" + fAction + ")"
                        });
                    }
                }
            }

            return JSON.stringify({
                visible: true,
                description: "The following files will be affected:",
                file_changes: file_changes,
                has_confirm: hasConfirm,
                has_cancel: hasCancel,
            });
        }
    }
    return null;
})();
"""


async def detect_confirm_undo_dialog(bridge):
    """Detect Confirm Undo modal overlay.

    Returns dict if present, None otherwise.
    """
    raw = await bridge.execute_js(_CONFIRM_UNDO_DIALOG_JS)
    if not raw:
        return None

    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
