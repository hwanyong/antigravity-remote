"""
agbridge.collectors.ax_scraper — Targeted AX UI scraper

Navigation strategy (Antigravity IDE is Electron-based):
  Window → ... → AXWebArea (main IDE content)

  Agent Panel discovery:
    Primary:  AXDOMClassList contains 'antigravity-agent-side-panel'
    Fallback: DFS for chat markers (Send / Cancel button)

  Conversation container:
    Primary:  AXDOMIdentifier == 'conversation'
    Fallback: AXGroup with class=['gap-y-3', 'px-4']

Key markers:
  - Send button:   AXButton desc="Send message" (inside Agent Panel)
  - Cancel button:  AXButton desc="Cancel"        (inside Agent Panel)
  - Message input: AXTextArea desc="Message input" (inside Agent Panel)
"""

import logging

from ApplicationServices import (
    AXUIElementCopyAttributeValue,
    AXUIElementCopyActionNames,
    AXUIElementPerformAction,
    AXUIElementSetAttributeValue,
    kAXChildrenAttribute,
    kAXRoleAttribute,
    kAXDescriptionAttribute,
    kAXTitleAttribute,
    kAXValueAttribute,
    kAXFocusedAttribute,
)

from agbridge.config import (
    AX_SEND_BUTTON_DESC,
    AX_CANCEL_BUTTON_DESC,
    AX_MESSAGE_INPUT_DESC,
    AX_MESSAGE_INPUT_ROLE,
    AX_ERROR_HEADING_TEXT,
    AX_RETRY_BUTTON_TITLE,
    AX_DISMISS_BUTTON_TITLE,
    AX_AGENT_PANEL_CLASS,
    AX_CONVERSATION_DOM_ID,
)

logger = logging.getLogger("agbridge.ax_scraper")

import json
import os

LOCATORS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui_locators.json")
_LOCATORS_CACHE = None

def get_ui_locators():
    global _LOCATORS_CACHE
    if _LOCATORS_CACHE is None:
        try:
            with open(LOCATORS_PATH, 'r', encoding='utf-8') as f:
                _LOCATORS_CACHE = json.load(f)
        except Exception as e:
            logger.error("Failed to load ui_locators.json: %s", e)
            # Default fallback schema
            _LOCATORS_CACHE = {
                "ide_components": {
                    "conversation_container": {
                        "required_classes": ["gap-y-3", "px-4"],
                        "max_dfs_depth": 18
                    },
                    "header_actions": {
                        "expected_link_count": 3,
                        "index_new_conversation": 0,
                        "index_past_conversations": 1
                    },
                    "thinking_section": {
                        "required_classes": ["pl-3", "overflow-hidden"]
                    }
                }
            }
    return _LOCATORS_CACHE


# ── AX helpers ───────────────────────────────────────────────

def _get_attr(el, attr):
    err, val = AXUIElementCopyAttributeValue(el, attr, None)
    if err == 0:
        return val
    return None


def _safe_str(val):
    if val is None:
        return None
    try:
        s = str(val)
        return s[:2000] if len(s) > 2000 else s
    except Exception:
        return None


def _get_children(el):
    children = _get_attr(el, kAXChildrenAttribute)
    return list(children) if children else []


def _find_by_dom_id(el, target_id, max_depth=25):
    """Find an element whose AXDOMIdentifier equals *target_id* via DFS."""
    result = [None]

    def scan(node, depth=0):
        if depth > max_depth or result[0]:
            return
        err, eid = AXUIElementCopyAttributeValue(node, "AXDOMIdentifier", None)
        if err == 0 and eid and str(eid) == target_id:
            result[0] = node
            return
        for c in _get_children(node):
            scan(c, depth + 1)

    scan(el)
    return result[0]


def _find_by_class(el, target_class, max_depth=25):
    """Find the first element whose AXDOMClassList contains *target_class*."""
    result = [None]

    def scan(node, depth=0):
        if depth > max_depth or result[0]:
            return
        classes = _get_class_list(node)
        if target_class in classes:
            result[0] = node
            return
        for c in _get_children(node):
            scan(c, depth + 1)

    scan(el)
    return result[0]


# ── Layout navigation ────────────────────────────────────────

def _find_webarea(window):
    """
    Find the primary AXWebArea inside the window.
    Antigravity is Electron-based, so all content lives inside AXWebArea.
    """
    def _dfs(el, depth=0):
        if depth > 15:
            return None
        role = _safe_str(_get_attr(el, kAXRoleAttribute))
        if role == "AXWebArea":
            return el
        for c in _get_children(el):
            found = _dfs(c, depth + 1)
            if found:
                return found
        return None
    return _dfs(window)


def _find_agent_section(window):
    """
    Find the Agent Panel section via its semantic CSS class.

    Primary: AXDOMClassList contains 'antigravity-agent-side-panel'
    Fallback: DFS for chat markers (Send / Cancel button or Message input)

    Returns:
        AX element for the Agent Panel, or None
    """
    webarea = _find_webarea(window)
    if not webarea:
        return None

    # Primary: semantic class selector (layout-position independent)
    panel = _find_by_class(webarea, AX_AGENT_PANEL_CLASS)
    if panel:
        return panel

    # Fallback: scan all top-level children for chat markers
    logger.warning(
        "Agent Panel class '%s' not found, falling back to marker scan",
        AX_AGENT_PANEL_CLASS,
    )
    for c in _get_children(webarea):
        if _contains_chat_marker(c):
            return c

    return None


def _contains_chat_marker(el, depth=0):
    """Check if an element subtree contains Send/Cancel button or Message input."""
    if depth > 15:
        return False
    role = _safe_str(_get_attr(el, kAXRoleAttribute))
    desc = _safe_str(_get_attr(el, kAXDescriptionAttribute))

    if role == "AXButton" and desc in (AX_SEND_BUTTON_DESC, AX_CANCEL_BUTTON_DESC):
        return True
    if role == AX_MESSAGE_INPUT_ROLE and desc == AX_MESSAGE_INPUT_DESC:
        return True

    for c in _get_children(el):
        if _contains_chat_marker(c, depth + 1):
            return True
    return False


# ── Button state detection ───────────────────────────────────

def _find_button_by_desc(el, desc_target, depth=0, max_depth=20):
    """Find an AXButton with the specified description via DFS."""
    if depth > max_depth:
        return None
    role = _safe_str(_get_attr(el, kAXRoleAttribute))
    desc = _safe_str(_get_attr(el, kAXDescriptionAttribute))
    if role == "AXButton" and desc == desc_target:
        return el

    for c in _get_children(el):
        found = _find_button_by_desc(c, desc_target, depth + 1, max_depth)
        if found:
            return found
    return None


def _find_button_by_title(el, title_target, depth=0, max_depth=20):
    """Find an AXButton with the specified title via DFS."""
    if depth > max_depth:
        return None
    role = _safe_str(_get_attr(el, kAXRoleAttribute))
    title = _safe_str(_get_attr(el, kAXTitleAttribute))
    if role == "AXButton" and title == title_target:
        return el

    for c in _get_children(el):
        found = _find_button_by_title(c, title_target, depth + 1, max_depth)
        if found:
            return found
    return None


def _find_heading_by_title(el, title_target, depth=0, max_depth=20):
    """Find an AXHeading with the specified title via DFS."""
    if depth > max_depth:
        return None
    role = _safe_str(_get_attr(el, kAXRoleAttribute))
    title = _safe_str(_get_attr(el, kAXTitleAttribute))
    if role == "AXHeading" and title == title_target:
        return el

    for c in _get_children(el):
        found = _find_heading_by_title(c, title_target, depth + 1, max_depth)
        if found:
            return found
    return None


def _detect_error_banner(section):
    """
    Detect the "Agent terminated due to error" banner within the Agent section.

    AX structure (from live dump):
        AXGroup <relative,flex,flex-col,gap-1,bg-agent-convo-background,p-2>
          AXHeading T="Agent terminated due to error"
          AXStaticText V="You can prompt the model..."
          AXGroup <flex,justify-between,...>
            AXButton T="Dismiss"
            AXButton T="Copy debug info"
            AXButton T="Retry"

    Returns:
        dict|None: {"message": str, "has_retry": bool, "has_dismiss": bool}
    """
    heading = _find_heading_by_title(section, AX_ERROR_HEADING_TEXT)
    if not heading:
        return None

    # Extract detail message from the parent group
    detail = ""
    parent = heading
    # The heading's siblings contain the detail text
    # Walk the parent's children for AXStaticText after the heading
    # Since we can't get parent via AX easily, just check for Retry/Dismiss
    has_retry = _find_button_by_title(section, AX_RETRY_BUTTON_TITLE) is not None
    has_dismiss = _find_button_by_title(section, AX_DISMISS_BUTTON_TITLE) is not None

    return {
        "message": AX_ERROR_HEADING_TEXT,
        "has_retry": has_retry,
        "has_dismiss": has_dismiss,
    }


def _detect_permission_banner(section):
    """
    Detect if the Agent is waiting for a permission request
    and extract the description of what is being requested.

    Returns:
        dict|None: {"description": str} or None if no permission request.
    """
    allow_btn = _find_button_by_title(section, "Allow")
    if not allow_btn:
        allow_btn = _find_button_by_title(section, "Allow Once")
    if not allow_btn:
        return None

    # Walk up from Allow button to find description context
    parent = _get_attr(allow_btn, "AXParent")
    if not parent:
        return {"description": ""}

    grandparent = _get_attr(parent, "AXParent")
    search_root = grandparent if grandparent else parent

    description = _collect_inner_text(search_root).strip()

    # Strip button label texts from the collected description
    for label in ("Deny", "Allow Once", "Allow This Workspace",
                  "Allow This Conversation", "Allow", "\u25b2"):
        description = description.replace(label, "")

    # Collapse whitespace
    description = " ".join(description.split())

    return {"description": description}


def get_conversation_state(window):
    """
    Return the current conversation state.

    Searches ONLY within the Agent Panel section.

    Returns:
        "idle" | "generating" | "error" | "unknown"
    """
    agent_section = _find_agent_section(window)
    if not agent_section:
        # Fallback: search full window (for compatibility)
        if _find_button_by_desc(window, AX_SEND_BUTTON_DESC):
            return "idle"
        if _find_button_by_desc(window, AX_CANCEL_BUTTON_DESC):
            return "generating"
        return "unknown"

    # Error banner takes priority — Send button coexists with error state
    if _detect_error_banner(agent_section):
        return "error"
        
    if _detect_permission_banner(agent_section) is not None:
        return "permission_required"

    if _find_button_by_desc(agent_section, AX_SEND_BUTTON_DESC):
        return "idle"
    if _find_button_by_desc(agent_section, AX_CANCEL_BUTTON_DESC):
        return "generating"
    return "unknown"


# ── Agent Panel collection ───────────────────────────────────

def _get_class_list(el):
    """Return the AXDOMClassList as a Python list."""
    raw = _get_attr(el, "AXDOMClassList")
    if raw:
        return list(raw)
    return []


def collect_agent_panel(window):
    """
    Collect Agent Panel conversation data with structured messages.

    Uses AXDOMClassList-based pattern matching (benchmarked from
    integrate_antigravity project) to separate User vs Agent messages.

    Returns:
        dict: {
            "state": "idle"|"generating"|"unknown",
            "conversation_title": str,
            "current_model": str,
            "current_mode": str,
            "messages": [
                {
                    "role": "user"|"assistant",
                    "content": str,
                    "thinking": str|None,
                    "actions": [dict],
                    "files_modified": [str],
                },
            ],
        }
    """
    agent_section = _find_agent_section(window)
    state = get_conversation_state(window)

    result = {
        "state": state,
        "conversation_title": "",
        "current_model": "",
        "current_mode": "",
        "messages": [],
        "error_info": None,
        "permission_info": None,
    }

    if not agent_section:
        return result

    # Extract conversation title
    _extract_conversation_title(agent_section, result)

    # Extract current model/mode from PopUpButtons
    model_mode = collect_models_and_modes(window)
    result["current_model"] = model_mode.get("current_model", "")
    result["current_mode"] = model_mode.get("current_mode", "")

    # Detect error banner
    if state == "error":
        result["error_info"] = _detect_error_banner(agent_section)

    # Detect permission info
    if state == "permission_required":
        result["permission_info"] = _detect_permission_banner(agent_section)

    # Find conversation container (gap-y-3, px-4)
    container = _find_conversation_container(agent_section)
    if container:
        result["messages"] = _parse_conversation_messages(container)

    return result


def _find_conversation_container(section):
    """
    Find the conversation thread container inside the Agent section.

    Strategy:
      1. Anchor via AXDOMIdentifier == 'conversation' (stable, narrows scope)
      2. Within that anchor, find the actual message-list container
         (AXGroup with class=['gap-y-3', 'px-4'])
      3. Fallback: scan the full section if DOM ID is absent
    """
    # Narrow scope via stable DOM id anchor
    anchor = _find_by_dom_id(section, AX_CONVERSATION_DOM_ID)
    search_root = anchor if anchor else section

    if not anchor:
        logger.warning(
            "Conversation DOM id '%s' not found, scanning full section",
            AX_CONVERSATION_DOM_ID,
        )

    # Find the actual message-list container within the anchor
    result = [None]

    locators = get_ui_locators()["ide_components"]["conversation_container"]
    req_classes = locators["required_classes"]
    max_depth = locators["max_dfs_depth"]

    def scan(el, depth=0):
        if depth > max_depth or result[0]:
            return
        classes = _get_class_list(el)
        if all(c in classes for c in req_classes):
            result[0] = el
            return
        for c in _get_children(el):
            scan(c, depth + 1)

    scan(search_root)
    return result[0]


def _parse_conversation_messages(container):
    """
    Parse conversation container into structured message list.

    Benchmark pattern:
      - children with 'sticky' class → User message
      - children with 'relative' class → Agent response root
      - 'pl-3' + 'overflow-hidden' → Thinking section
      - Accept/Reject area → skip
      - 'Files Modified' label → file list

    Returns:
        list[dict]
    """
    messages = []
    children = _get_children(container)
    if not children:
        return messages

    current_assistant = None

    for child in children:
        classes = _get_class_list(child)

        # User message (sticky class)
        if "sticky" in classes:
            # Flush any pending assistant message
            if current_assistant:
                messages.append(current_assistant)
                current_assistant = None

            text = _collect_inner_text(child).strip()
            if text:
                has_undo = _detect_undo_button(child) is not None
                messages.append({
                    "role": "user",
                    "content": text,
                    "thinking": None,
                    "actions": [],
                    "files_modified": [],
                    "has_undo": has_undo,
                })
            continue

        # Accept/Reject area — skip
        if _is_accept_reject_area(child):
            continue

        # Files Modified label
        value = _safe_str(_get_attr(child, kAXValueAttribute)) or ""
        if value == "Files Modified":
            if current_assistant:
                current_assistant["files_modified"] = _extract_file_list(
                    container, child
                )
            continue

        # Digit-only (file count) — skip, but NOT AXHeading (level stored in value)
        role = _safe_str(_get_attr(child, kAXRoleAttribute))
        if value.strip().isdigit() and role != "AXHeading":
            continue

        # Agent response root (relative class)
        if "relative" in classes:
            if not current_assistant:
                current_assistant = {
                    "role": "assistant",
                    "content": "",
                    "thinking": None,
                    "actions": [],
                    "files_modified": [],
                }
            _parse_response_subtree(child, current_assistant)
            continue

        # General content — append to assistant if exists
        text = _extract_markdown_from_element(child)
        if text and text.strip():
            if not current_assistant:
                current_assistant = {
                    "role": "assistant",
                    "content": "",
                    "thinking": None,
                    "actions": [],
                    "files_modified": [],
                }
            if current_assistant["content"]:
                current_assistant["content"] += "\n\n"
            current_assistant["content"] += text

    # Flush remaining assistant
    if current_assistant:
        messages.append(current_assistant)

    return messages


def _parse_response_subtree(group, assistant_msg):
    """
    Parse an agent response root (relative class) group.
    Identifies Thinking, Action cards, and body text.
    """
    children = _get_children(group)
    if not children:
        return

    for child in children:
        classes = _get_class_list(child)

        # Thinking section
        if _is_thinking_section(classes):
            thinking = _extract_thinking_text(child)
            if thinking:
                assistant_msg["thinking"] = thinking
            continue

        # Action card (Edited, Explored, Ran command)
        if _is_action_section(child, classes):
            action = _extract_action(child)
            if action:
                assistant_msg["actions"].append(action)
            continue

        # Nested overflow-hidden — recurse
        if "overflow-hidden" in classes:
            _parse_response_subtree(child, assistant_msg)
            continue

        # General text
        text = _extract_markdown_from_element(child)
        if text and text.strip():
            if assistant_msg["content"]:
                assistant_msg["content"] += "\n\n"
            assistant_msg["content"] += text


def _is_thinking_section(classes):
    """Thinking area detected via ui_locators.json schema."""
    req_classes = get_ui_locators()["ide_components"]["thinking_section"]["required_classes"]
    return all(c in classes for c in req_classes)


def _is_action_section(el, classes):
    """Action card: 'relative' class and children contain Edited/Explored/Created buttons."""
    if "relative" not in classes:
        return False
    for c in _get_children(el):
        c_role = _safe_str(_get_attr(c, kAXRoleAttribute))
        if c_role == "AXButton":
            texts = _collect_static_texts(c)
            if any(kw in texts for kw in ("Edited", "Explored", "Created", "Ran")):
                return True
    return False


def _is_accept_reject_area(el):
    """Accept/Reject button area detection."""
    texts = _collect_static_texts(el)
    if "Reject all" in texts or "Accept all" in texts:
        return True
    classes = _get_class_list(el)
    if "cursor-pointer" in classes and "transition-[opacity,transform]" in classes:
        return True
    return False


def _extract_thinking_text(el):
    """Extract thinking text from a Thinking section."""
    texts = []

    def scan(node, depth=0):
        if depth > 10:
            return
        role = _safe_str(_get_attr(node, kAXRoleAttribute))
        if role == "AXStaticText":
            val = (_safe_str(_get_attr(node, kAXValueAttribute)) or "").strip()
            if val and val not in ("Thought for", "Worked for", "undo"):
                texts.append(val)
        for c in _get_children(node):
            scan(c, depth + 1)

    scan(el)
    return " ".join(texts) if texts else None


def _extract_action(el):
    """Extract structured action info from an action card."""
    all_texts = _collect_static_texts(el)
    action = {"type": "unknown", "detail": ""}

    if "Edited" in all_texts or "Created" in all_texts:
        action["type"] = "file_edit"
        # Find file name — typically a text with '.' in it
        for t in all_texts:
            if "." in t and t not in ("Edited", "Created", "+", "-"):
                action["file"] = t
                break
    elif "Ran command" in all_texts or "Explored" in all_texts:
        action["type"] = "command"
        action["detail"] = " ".join(all_texts[:5])
    else:
        action["detail"] = " ".join(all_texts[:5])

    return action


def _extract_file_list(container, files_label_el):
    """Extract file list from the Files Modified section."""
    files = []
    children = _get_children(container)
    if not children:
        return files

    found_marker = False
    for child in children:
        if child == files_label_el:
            found_marker = True
            continue
        if found_marker:
            texts = _collect_static_texts(child)
            for t in texts:
                if "." in t and not t.startswith("+") and not t.startswith("-"):
                    files.append(t)
    return files


def _extract_markdown_from_element(el, depth=0):
    """Reconstruct markdown syntax from the AX accessibility tree.

    Maps AX roles back to their markdown equivalents so that the
    TUI client can render structured content via a Markdown widget.

    Handled:
        AXHeading        → # / ## / ### …
        AXList           → - item  or  1. item
        AXLink           → [text](url)
        AXTable          → | col | col |
        AXCodeStyleGroup → `inline code`
        Block code       → ```lang … ```
        AXSplitter       → ---
        AXStaticText     → plain text
        AXGroup          → recurse, block-join or inline-join
    """
    if depth > 20:
        return ""
    role = _safe_str(_get_attr(el, kAXRoleAttribute))
    subrole = _safe_str(_get_attr(el, "AXSubrole"))

    # ── Leaf: plain text ─────────────────────────────
    if role == "AXStaticText":
        return _safe_str(_get_attr(el, kAXValueAttribute)) or ""

    # ── Inline code (subrole) ────────────────────────
    if subrole == "AXCodeStyleGroup":
        inner = _collect_inner_text(el)
        return f"`{inner}`"

    # ── Bold (subrole) ───────────────────────────────
    if subrole == "AXStrongStyleGroup":
        inner = _md_inline(el, depth + 1)
        return f"**{inner}**"

    # ── Italic (subrole) ─────────────────────────────
    if subrole == "AXEmphasisStyleGroup":
        inner = _md_inline(el, depth + 1)
        return f"*{inner}*"

    classes = _get_class_list(el)

    # ── Block-level fenced code block ────────────────
    if _is_block_code_element(role, subrole, classes, el):
        lang = _detect_code_lang(classes, el)
        inner = _collect_code_text(el)
        return f"```{lang}\n{inner}\n```"

    # ── Inline font-mono (not block code) ────────────
    if "font-mono" in classes:
        inner = _collect_inner_text(el)
        return f"`{inner}`"

    # ── Heading ──────────────────────────────────────
    if role == "AXHeading":
        level = _get_heading_level(el)
        inner = _md_inline(el, depth + 1)
        return f"{'#' * level} {inner}"

    # ── Link ─────────────────────────────────────────
    if role == "AXLink":
        url = _safe_str(_get_attr(el, "AXURL")) or ""
        text = _collect_inner_text(el).strip()
        if url and text:
            return f"[{text}]({url})"
        return text or ""

    # ── List ─────────────────────────────────────────
    if role == "AXList":
        return _md_list(el, depth)

    # ── Horizontal rule ──────────────────────────────
    if role in ("AXSplitter", "AXSeparator"):
        return "---"

    # ── Table ────────────────────────────────────────
    if role == "AXTable":
        return _md_table(el)

    # ── Generic container → recurse ──────────────────
    children = _get_children(el)
    if not children:
        return ""

    _BLOCK_ROLES = ("AXHeading", "AXList", "AXTable", "AXSplitter", "AXSeparator")
    has_blocks = any(
        _safe_str(_get_attr(c, kAXRoleAttribute)) in _BLOCK_ROLES
        or _is_block_code_element(
            _safe_str(_get_attr(c, kAXRoleAttribute)),
            _safe_str(_get_attr(c, "AXSubrole")),
            _get_class_list(c), c,
        )
        for c in children
    )

    if has_blocks:
        parts = []
        for c in children:
            t = _extract_markdown_from_element(c, depth + 1)
            if t and t.strip():
                parts.append(t)
        return "\n\n".join(parts)

    # Inline container
    return _md_inline(el, depth + 1)


# ── Markdown reconstruction helpers ──────────────────────────

def _md_inline(el, depth):
    """Concatenate children inline (no separator)."""
    parts = []
    for c in _get_children(el):
        t = _extract_markdown_from_element(c, depth)
        if t:
            parts.append(t)
    return "".join(parts)


def _get_heading_level(el):
    """Return heading level 1-6 from an AXHeading element."""
    # Electron/Antigravity: heading level stored in AXValue
    val = _safe_str(_get_attr(el, kAXValueAttribute))
    if val is not None:
        try:
            v = int(val)
            if 1 <= v <= 6:
                return v
        except (ValueError, TypeError):
            pass
    # Chromium custom attribute
    level = _get_attr(el, "AXHeadingLevel")
    if level is not None:
        try:
            return max(1, min(6, int(level)))
        except (ValueError, TypeError):
            pass
    # Parse from role description ("heading level 2")
    import re
    rdesc = _safe_str(_get_attr(el, "AXRoleDescription")) or ""
    m = re.search(r"level\s*(\d)", rdesc)
    if m:
        return max(1, min(6, int(m.group(1))))
    return 2  # default to h2


def _is_block_code_element(role, subrole, classes, el):
    """Detect a block-level fenced code block element.

    Antigravity IDE code block AX structure:
        AXGroup cls=['relative', 'whitespace-pre-wrap', 'word-break-all', 'my-2']
          AXGroup cls=['min-h-7', ...]           ← header (lang label + buttons)
          AXGroup cls=['w-full', 'h-full', ...]   ← body (line-content groups)
    """
    _CODE_HINTS = (
        "code-block", "code-block-wrapper", "code-block-widget",
        "interactive-result-code-block", "chat-code-block",
        "monaco-editor", "hljs",
    )
    if any(c in _CODE_HINTS for c in classes):
        return True
    if any(c.startswith("language-") for c in classes):
        return True
    # Antigravity pattern: whitespace-pre-wrap + word-break-all + line-content children
    if role == "AXGroup" and "whitespace-pre-wrap" in classes and "word-break-all" in classes:
        return True
    return False


def _detect_code_lang(classes, el=None):
    """Extract language hint from class list or from child structure."""
    for c in classes:
        if c.startswith("language-"):
            return c[9:]
    # Antigravity: first child group → inner AXStaticText = language label
    if el is not None:
        children = _get_children(el)
        if children:
            header = children[0]
            for hc in _get_children(header):
                for hcc in _get_children(hc):
                    r = _safe_str(_get_attr(hcc, kAXRoleAttribute))
                    if r == "AXStaticText":
                        v = (_safe_str(_get_attr(hcc, kAXValueAttribute)) or "").strip()
                        if v and v.isalpha() and len(v) < 20:
                            return v
    return ""


def _collect_code_text(el):
    """Collect code block text line-by-line from line-content groups."""
    lines = []

    def find_line_groups(node, d=0):
        if d > 6:
            return
        classes = _get_class_list(node)
        if "line-content" in classes:
            line_parts = []
            for c in _get_children(node):
                r = _safe_str(_get_attr(c, kAXRoleAttribute))
                if r == "AXStaticText":
                    v = _safe_str(_get_attr(c, kAXValueAttribute)) or ""
                    line_parts.append(v)
            lines.append("".join(line_parts))
            return
        for c in _get_children(node):
            find_line_groups(c, d + 1)

    find_line_groups(el)
    if lines:
        return "\n".join(lines)
    # Fallback: collect all text skipping buttons/labels
    _SKIP = ("Copy", "copy", "Copy code")
    texts = []
    def scan(node, d=0):
        if d > 15:
            return
        r = _safe_str(_get_attr(node, kAXRoleAttribute))
        if r == "AXButton":
            return
        if r == "AXStaticText":
            v = _safe_str(_get_attr(node, kAXValueAttribute)) or ""
            if v and v.strip() not in _SKIP:
                texts.append(v)
            return
        for c in _get_children(node):
            scan(c, d + 1)
    scan(el)
    return "".join(texts)


def _md_list(el, depth, indent=0):
    """Reconstruct a markdown list from an AXList element.

    Handles nested AXList by recursing with increased indentation.
    Detects ordered vs unordered by inspecting AXListMarker values.
    """
    items = []
    children = _get_children(el)
    ordered = _is_ordered_list(children)
    order_idx = 0

    for child in children:
        text_parts, sub_lists = _md_list_item_parts(child, depth + 1)
        item_text = "".join(text_parts).strip()
        if not item_text and not sub_lists:
            continue
        order_idx += 1
        prefix = " " * (indent * 2) + (f"{order_idx}. " if ordered else "- ")
        items.append(f"{prefix}{item_text}")
        # Append nested sub-lists with increased indent
        for sub in sub_lists:
            nested = _md_list(sub, depth + 1, indent + 1)
            if nested:
                items.append(nested)

    return "\n".join(items)


def _is_ordered_list(children):
    """Detect ordered list by checking AXListMarker value of first item."""
    if not children:
        return False
    for c in _get_children(children[0]):
        sr = _safe_str(_get_attr(c, "AXSubrole"))
        if sr == "AXListMarker":
            v = (_safe_str(_get_attr(c, kAXValueAttribute)) or "").strip()
            if v and v[0].isdigit():
                return True
            return False
    return False


def _md_list_item_parts(el, depth):
    """Extract text and nested sub-lists from a list item.

    Returns:
        (text_parts: list[str], sub_lists: list[AXElement])
    """
    text_parts = []
    sub_lists = []
    for c in _get_children(el):
        r = _safe_str(_get_attr(c, kAXRoleAttribute))
        sr = _safe_str(_get_attr(c, "AXSubrole"))
        # Skip list marker
        if sr == "AXListMarker":
            continue
        # Nested sub-list → collect for separate rendering
        if r == "AXList":
            sub_lists.append(c)
            continue
        t = _extract_markdown_from_element(c, depth)
        if t:
            text_parts.append(t)
    return text_parts, sub_lists


def _md_table(el):
    """Reconstruct a markdown table from an AXTable element.

    Antigravity AX structure:
        AXTable
          AXGroup → AXRow (header row inside wrapper)
          AXRow (data rows)
          AXColumn (duplicate data — skip)
    """
    rows = []

    def find_rows(node, d=0):
        if d > 3:
            return
        r = _safe_str(_get_attr(node, kAXRoleAttribute))
        if r == "AXColumn":
            return  # skip column duplicates
        if r == "AXRow":
            cells = []
            for cell in _get_children(node):
                cr = _safe_str(_get_attr(cell, kAXRoleAttribute))
                if cr == "AXCell":
                    cells.append(_collect_inner_text(cell).strip())
            if cells:
                rows.append(cells)
            return
        for c in _get_children(node):
            find_rows(c, d + 1)

    find_rows(el)
    if not rows:
        return ""
    col_count = max(len(r) for r in rows)
    if col_count == 0:
        return ""
    for row in rows:
        while len(row) < col_count:
            row.append("")
    lines = []
    lines.append("| " + " | ".join(rows[0]) + " |")
    lines.append("| " + " | ".join("---" for _ in range(col_count)) + " |")
    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _collect_inner_text(el):
    """Collect all descendant AXStaticText values concatenated."""
    texts = []

    def scan(node, depth=0):
        if depth > 10:
            return
        role = _safe_str(_get_attr(node, kAXRoleAttribute))
        if role == "AXStaticText":
            val = _safe_str(_get_attr(node, kAXValueAttribute)) or ""
            texts.append(val)
        for c in _get_children(node):
            scan(c, depth + 1)

    scan(el)
    return "".join(texts)


def _collect_static_texts(el):
    """Collect all AXStaticText values as a list."""
    result = []

    def scan(node, depth=0):
        if depth > 10:
            return
        role = _safe_str(_get_attr(node, kAXRoleAttribute))
        if role == "AXStaticText":
            val = (_safe_str(_get_attr(node, kAXValueAttribute)) or "").strip()
            if val:
                result.append(val)
        for c in _get_children(node):
            scan(c, depth + 1)

    scan(el)
    return result


def _extract_conversation_title(section, result):
    """
    Find the conversation title text in the Agent Panel header.
    It's typically the first AXStaticText with meaningful content
    in the top-level children.
    """
    def _find_title(el, depth=0):
        if depth > 5:
            return None
        role = _safe_str(_get_attr(el, kAXRoleAttribute))
        value = _safe_str(_get_attr(el, kAXValueAttribute))

        if role == "AXStaticText" and value:
            if len(value) > 3 and not _is_icon_char(value):
                return value

        for c in _get_children(el):
            found = _find_title(c, depth + 1)
            if found:
                return found
        return None

    title = _find_title(section)
    if title:
        result["conversation_title"] = title


def _is_icon_char(s):
    """Check if string is just icon/emoji characters."""
    if not s:
        return True
    return all(ord(c) > 0xE000 or ord(c) < 0x20 for c in s.strip())


# ── Active editor tab tracking ───────────────────────────────

def get_active_editor_info(window):
    """
    Extract the currently focused editor tab information.

    Parses the window title which has format:
    "workspace-name — filename" or "workspace-name — folder/filename — Description"

    Returns:
        dict: {"title": str, "workspace": str, "filename": str}
    """
    webarea = _find_webarea(window)
    if webarea:
        title = _safe_str(_get_attr(webarea, kAXTitleAttribute))
    else:
        title = _safe_str(_get_attr(window, kAXTitleAttribute))

    ws_name = ""
    filename = ""

    if title and " — " in title:
        parts = title.split(" — ")
        ws_name = parts[0].strip()
        filename = parts[1].strip() if len(parts) > 1 else ""

    return {
        "title": title or "",
        "workspace": ws_name,
        "filename": filename,
    }


# ── Model / Mode detection (AXPopUpButton) ───────────────────

def _find_popup_button(window, title_prefix):
    """
    Find an AXPopUpButton whose title starts with the given prefix.

    Benchmark pattern: depth=16, Agent Panel internal popup.
    Falls back to broader search if not found at exact depth.
    """
    result = [None]

    def scan(el, depth=0):
        if depth > 20 or result[0]:
            return
        role = _safe_str(_get_attr(el, kAXRoleAttribute))
        if role == "AXPopUpButton":
            title = _safe_str(_get_attr(el, kAXTitleAttribute)) or ""
            if title_prefix in title:
                result[0] = el
                return
        for c in _get_children(el):
            scan(c, depth + 1)

    scan(window)
    return result[0]


def _parse_popup_current_value(popup):
    """
    Parse "Select model, current: Claude Opus 4.6 (Thinking)"
    → "Claude Opus 4.6 (Thinking)"
    """
    import re
    title = _safe_str(_get_attr(popup, kAXTitleAttribute)) or ""
    match = re.search(r"current:\s*(.+)$", title)
    if match:
        return match.group(1).strip()
    return ""


def collect_models_and_modes(window):
    """
    Read the current model and mode from their AXPopUpButton titles.
    No popup opening required — reads from the button title directly.

    Returns:
        dict: {"current_model": str, "current_mode": str}
    """
    from agbridge.config import (
        AX_MODEL_POPUP_TITLE_PREFIX,
        AX_MODE_POPUP_TITLE_PREFIX,
    )

    current_model = ""
    current_mode = ""

    model_popup = _find_popup_button(window, AX_MODEL_POPUP_TITLE_PREFIX)
    if model_popup:
        current_model = _parse_popup_current_value(model_popup)

    mode_popup = _find_popup_button(window, AX_MODE_POPUP_TITLE_PREFIX)
    if mode_popup:
        current_mode = _parse_popup_current_value(mode_popup)

    return {
        "current_model": current_model,
        "current_mode": current_mode,
    }


def _scan_popup_items(popup, window, target_role):
    """
    Scan for popup menu items after the popup has been opened.

    Electron renders popup dropdowns as floating overlays that are
    NOT children of the AXPopUpButton or the agent section. The only
    reliable strategy is to scan the full window tree.

    Strategy:
      1. Scan popup element subtree (fast path).
      2. Fallback: scan full window (Electron floating overlay).

    Args:
        popup: The AXPopUpButton that was pressed.
        window: The window element (fallback scan root).
        target_role: "AXButton" or "AXMenuItem".

    Returns:
        list[str]: item titles
    """
    items = []

    def scan(el, depth=0):
        if depth > 25:
            return
        role = _safe_str(_get_attr(el, kAXRoleAttribute))
        if role == target_role:
            title = _safe_str(_get_attr(el, kAXTitleAttribute)) or ""
            if title:
                items.append(title)
        for c in _get_children(el):
            scan(c, depth + 1)

    # Try popup subtree first
    scan(popup)
    if items:
        return items

    # Fallback: scan full window (Electron floating overlay)
    scan(window)
    return items


def _find_popup_target(popup, window, target_role, match_name):
    """
    Find a specific item in an opened popup by name.

    Same strategy as _scan_popup_items: popup subtree first,
    then full window scan for Electron floating overlays.

    Args:
        popup: The AXPopUpButton element.
        window: The window element.
        target_role: "AXButton" or "AXMenuItem".
        match_name: partial match string (case-insensitive).

    Returns:
        AX element or None
    """
    result = [None]

    def scan(el, depth=0):
        if depth > 25 or result[0]:
            return
        role = _safe_str(_get_attr(el, kAXRoleAttribute))
        if role == target_role:
            title = _safe_str(_get_attr(el, kAXTitleAttribute)) or ""
            if match_name.lower() in title.lower():
                result[0] = el
                return
        for c in _get_children(el):
            scan(c, depth + 1)

    # Try popup subtree first
    scan(popup)
    if result[0]:
        return result[0]

    # Fallback: scan full window
    scan(window)
    return result[0]


def list_available_models(window, controller):
    """
    Open the model popup, collect all item titles, then close.
    Requires window focus — must go through InputQueue.

    Returns:
        list[str]: model names
    """
    from agbridge.config import AX_MODEL_POPUP_TITLE_PREFIX
    from agbridge.collectors.ax_polling import poll_until

    popup = _find_popup_button(window, AX_MODEL_POPUP_TITLE_PREFIX)
    if not popup:
        return []

    AXUIElementPerformAction(popup, "AXPress")

    items = poll_until(
        lambda: _scan_popup_items(popup, window, "AXButton"),
        controller,
        label="model_popup",
    )

    _press_escape()
    return items


def list_available_modes(window, controller):
    """
    Open the mode popup, collect all item titles, then close.

    Returns:
        list[str]: mode names
    """
    from agbridge.config import AX_MODE_POPUP_TITLE_PREFIX
    from agbridge.collectors.ax_polling import poll_until

    popup = _find_popup_button(window, AX_MODE_POPUP_TITLE_PREFIX)
    if not popup:
        return []

    AXUIElementPerformAction(popup, "AXPress")

    items = poll_until(
        lambda: _scan_popup_items(popup, window, "AXMenuItem"),
        controller,
        label="mode_popup",
    )

    _press_escape()
    return items


def select_model(window, model_name, controller):
    """
    Change the AI model by opening the popup, finding the matching item,
    and clicking it.

    Args:
        model_name: partial match (case-insensitive)

    Returns:
        bool: success
    """
    from agbridge.config import AX_MODEL_POPUP_TITLE_PREFIX
    from agbridge.collectors.ax_polling import poll_until

    popup = _find_popup_button(window, AX_MODEL_POPUP_TITLE_PREFIX)
    if not popup:
        return False

    # Already on this model?
    current = _parse_popup_current_value(popup)
    if current and model_name.lower() in current.lower():
        return True

    AXUIElementPerformAction(popup, "AXPress")

    target = poll_until(
        lambda: _find_popup_target(popup, window, "AXButton", model_name),
        controller,
        label="select_model",
    )

    if not target:
        _press_escape()
        return False

    AXUIElementPerformAction(target, "AXPress")
    return True


def select_mode(window, mode_name, controller):
    """
    Change the conversation mode.

    Args:
        mode_name: "planning" or "fast" (case-insensitive)

    Returns:
        bool: success
    """
    from agbridge.config import AX_MODE_POPUP_TITLE_PREFIX
    from agbridge.collectors.ax_polling import poll_until

    popup = _find_popup_button(window, AX_MODE_POPUP_TITLE_PREFIX)
    if not popup:
        return False

    current = _parse_popup_current_value(popup)
    if current and mode_name.lower() in current.lower():
        return True

    AXUIElementPerformAction(popup, "AXPress")

    target = poll_until(
        lambda: _find_popup_target(popup, window, "AXMenuItem", mode_name),
        controller,
        label="select_mode",
    )

    if not target:
        _press_escape()
        return False

    AXUIElementPerformAction(target, "AXPress")
    return True


def _press_escape():
    """Press Escape key using CGEvent to close popups."""
    from Quartz import (
        CGEventCreateKeyboardEvent,
        CGEventPost,
        kCGHIDEventTap,
    )
    import time
    # Escape key code = 53
    event_down = CGEventCreateKeyboardEvent(None, 53, True)
    CGEventPost(kCGHIDEventTap, event_down)
    time.sleep(0.02)
    event_up = CGEventCreateKeyboardEvent(None, 53, False)
    CGEventPost(kCGHIDEventTap, event_up)


# ── Cancel / New Conversation ────────────────────────────────

def press_cancel_button(window):
    """
    Find and press the Cancel button in the Agent Panel.

    Returns:
        bool: True if found and pressed
    """
    agent_section = _find_agent_section(window)
    search_root = agent_section if agent_section else window
    cancel_btn = _find_button_by_desc(search_root, AX_CANCEL_BUTTON_DESC)
    if not cancel_btn:
        return False
    AXUIElementPerformAction(cancel_btn, "AXPress")
    return True


def press_button_by_exact_title(window, title):
    """
    Find and press a button by its exact title within the agent section.
    
    Returns:
        bool: True if found and pressed
    """
    agent_section = _find_agent_section(window)
    search_root = agent_section if agent_section else window
    btn = _find_button_by_title(search_root, title)
    if not btn:
        return False
    AXUIElementPerformAction(btn, "AXPress")
    return True


def press_permission_dropdown_item(window, item_title, controller):
    """
    Open the permission dropdown (chevron ▲ next to Allow) and press a menu item.

    2-step AX interaction:
      1. Find and press the chevron button to open the dropdown
      2. Wait for render, then find and press the target menu item

    Args:
        window: AX window element
        item_title: exact title of the dropdown item
                    ("Allow for Workspace", "Allow Globally", "Run in sandbox")
        controller: PollController instance

    Returns:
        bool: True if the item was found and pressed
    """
    from agbridge.collectors.ax_polling import poll_until

    agent_section = _find_agent_section(window)
    search_root = agent_section if agent_section else window

    # The chevron is typically a small button near "Allow" — 
    # look for buttons with known dropdown item titles after opening
    # First, find "Allow" button, then look for adjacent chevron/dropdown trigger
    # In Roo Code, the dropdown trigger may have no title or a generic one.
    # Strategy: find by scanning for a button whose action opens the menu.
    
    # Try direct approach: look for the menu item already visible
    direct = _find_button_by_title(search_root, item_title)
    if direct:
        AXUIElementPerformAction(direct, "AXPress")
        return True

    # 2-step: find and click the chevron/dropdown trigger near Allow
    # Scan for small buttons near the Allow button region
    allow_btn = _find_button_by_title(search_root, "Allow")
    if not allow_btn:
        return False

    # The chevron is typically a sibling or adjacent element
    # Try AXPress with "AXShowMenu" action first (some buttons support it)
    actions = []
    try:
        actions = list(_get_attr(allow_btn, "AXActionNames") or [])
    except Exception:
        pass

    if "AXShowMenu" in actions:
        AXUIElementPerformAction(allow_btn, "AXShowMenu")
        poll_until(
            lambda: _find_button_by_title(window, item_title),
            controller,
            label="permission_dropdown",
        )
    else:
        # Fallback: press the Allow button's parent or look for chevron sibling
        # Scan children near Allow for a small button (the chevron)
        parent_children = _get_children(search_root)
        chevron_found = False

        def find_chevron(el, depth=0):
            nonlocal chevron_found
            if depth > 15 or chevron_found:
                return
            role = _safe_str(_get_attr(el, kAXRoleAttribute))
            if role == "AXButton":
                title = _safe_str(_get_attr(el, kAXTitleAttribute)) or ""
                desc = _safe_str(_get_attr(el, kAXDescriptionAttribute)) or ""
                # Chevron buttons often have no title or a dropdown arrow description
                if title in ("", "More actions", "More Actions") or "dropdown" in desc.lower() or "chevron" in desc.lower():
                    # Verify it's near the Allow button area (heuristic check)
                    AXUIElementPerformAction(el, "AXPress")
                    chevron_found = True
                    return
            for c in _get_children(el):
                find_chevron(c, depth + 1)

        find_chevron(search_root)
        if not chevron_found:
            return False
        poll_until(
            lambda: _find_button_by_title(window, item_title),
            controller,
            label="permission_chevron",
        )

    # Now the dropdown should be open — find the target menu item
    # Menu items in Electron overlays appear in the full window tree
    target = _find_button_by_title(window, item_title)
    if not target:
        # Try AXMenuItem role
        target = _find_popup_target(None, window, "AXMenuItem", item_title)

    if not target:
        _press_escape()
        return False

    AXUIElementPerformAction(target, "AXPress")
    return True


def press_retry_button(window):
    """
    Find and press the Retry button in the error banner.

    Returns:
        bool: True if found and pressed
    """
    agent_section = _find_agent_section(window)
    search_root = agent_section if agent_section else window
    retry_btn = _find_button_by_title(search_root, AX_RETRY_BUTTON_TITLE)
    if not retry_btn:
        return False
    AXUIElementPerformAction(retry_btn, "AXPress")
    return True


def press_dismiss_button(window):
    """
    Find and press the Dismiss button in the error banner.

    Returns:
        bool: True if found and pressed
    """
    agent_section = _find_agent_section(window)
    search_root = agent_section if agent_section else window
    dismiss_btn = _find_button_by_title(search_root, AX_DISMISS_BUTTON_TITLE)
    if not dismiss_btn:
        return False
    AXUIElementPerformAction(dismiss_btn, "AXPress")
    return True


# ── Undo / Rollback ──────────────────────────────────────────

def _detect_undo_button(user_msg_el):
    """
    Detect the undo button inside a user message element.

    AX structure (from live dump):
        AXGroup cls=['sticky', ...]   ← user message root
          AXGroup cls=['bg-gray-500/10', 'border', ...]
            AXGroup   ← prompt text
            AXButton T="undo"   ← target

    Returns:
        AX element or None
    """
    return _find_button_by_title(user_msg_el, "undo", depth=0, max_depth=5)


def reconstruct_user_message_text(window, message_index):
    """Reconstruct user message text with original mention syntax.

    Walks the AX tree of the Nth user message to rebuild the prompt
    including mention wrappers that are lost in plain AXValue reads.

    Identification rules (from antigravity-mention-syntax SKILL):
        AXGroup + AXApplicationGroup + no AXImage  → @[/{text}]   (workflow)
        AXGroup + AXApplicationGroup + AXImage      → @[{text}]    (file/workspace)
        AXGroup + AXCodeStyleGroup + @terminal:     → @[TerminalName: {name}]
        AXGroup + AXCodeStyleGroup + @{title}       → @[conversation:"{title}"]
        AXStaticText                                → literal text

    Args:
        window: AX window element
        message_index: 0-based index of the target user message

    Returns:
        str: Reconstructed prompt text, or empty string if not found.
    """
    agent_section = _find_agent_section(window)
    if not agent_section:
        return ""

    container = _find_conversation_container(agent_section)
    if not container:
        return ""

    # Find the Nth sticky (user) message
    user_idx = 0
    target_sticky = None
    for child in _get_children(container):
        if "sticky" not in _get_class_list(child):
            continue
        if user_idx == message_index:
            target_sticky = child
            break
        user_idx += 1

    if not target_sticky:
        return ""

    # Navigate to the text-sm container inside the sticky message
    text_container = _find_text_sm_container(target_sticky)
    if not text_container:
        # Fallback: plain inner text
        return _collect_inner_text(target_sticky).strip()

    # Walk children and reconstruct with mention syntax
    parts = []
    for child in _get_children(text_container):
        role = _safe_str(_get_attr(child, kAXRoleAttribute)) or ""

        if role == "AXStaticText":
            val = _safe_str(_get_attr(child, kAXValueAttribute)) or ""
            parts.append(val)
            continue

        if role == "AXGroup":
            subrole = _safe_str(_get_attr(child, "AXSubrole")) or ""

            if subrole == "AXApplicationGroup":
                # Workflow / File / Workspace pill
                has_icon = _has_ax_image_child(child)
                text = _collect_inner_text(child).strip()
                if has_icon:
                    parts.append(f"@[{text}]")
                else:
                    parts.append(f"@[/{text}]")

            elif subrole == "AXCodeStyleGroup":
                # Terminal or Conversation mention
                text = _collect_inner_text(child).strip()
                if text.startswith("@terminal:"):
                    name = text[len("@terminal:"):].strip()
                    parts.append(f"@[TerminalName: {name}]")
                elif text.startswith("@"):
                    title = text[1:].strip()
                    parts.append(f'@[conversation:"{title}"]')
                else:
                    parts.append(text)

            else:
                # Unknown group — fallback to inner text
                text = _collect_inner_text(child).strip()
                if text:
                    parts.append(text)

    return "".join(parts).strip()


def _find_text_sm_container(el, depth=0):
    """Find the whitespace-pre-wrap text-sm container inside a user message."""
    if depth > 5:
        return None
    classes = _get_class_list(el)
    if "whitespace-pre-wrap" in classes and "text-sm" in classes:
        return el
    for child in _get_children(el):
        found = _find_text_sm_container(child, depth + 1)
        if found:
            return found
    return None


def _has_ax_image_child(el, depth=0):
    """Check if element has any AXImage descendant (up to 3 levels deep)."""
    if depth > 3:
        return False
    for child in _get_children(el):
        role = _safe_str(_get_attr(child, kAXRoleAttribute)) or ""
        if role == "AXImage":
            return True
        if _has_ax_image_child(child, depth + 1):
            return True
    return False


def press_undo_for_message(window, message_index):
    """
    Click the undo button for the Nth user message in the conversation.

    Args:
        window: AX window element
        message_index: 0-based index of the target user message

    Returns:
        bool: True if the undo button was found and pressed
    """
    agent_section = _find_agent_section(window)
    if not agent_section:
        return False

    container = _find_conversation_container(agent_section)
    if not container:
        return False

    children = _get_children(container)
    user_idx = 0
    for child in children:
        classes = _get_class_list(child)
        if "sticky" not in classes:
            continue
        if user_idx == message_index:
            undo_btn = _detect_undo_button(child)
            if not undo_btn:
                logger.warning(
                    "Undo button not found for user message #%d",
                    message_index,
                )
                return False
            AXUIElementPerformAction(undo_btn, "AXPress")
            return True
        user_idx += 1

    logger.warning(
        "User message #%d not found (only %d user messages)",
        message_index, user_idx,
    )
    return False


def detect_confirm_undo_dialog(window):
    """
    Detect the Confirm Undo dialog overlay.

    AX structure (from live dump):
        AXGroup cls=['fixed','inset-0','z-[2550]','bg-black/40']
          AXGroup cls=['shadow-xl','bg-ide-chat-background',...]
            AXHeading T="Confirm Undo"
            AXButton T="close"
            AXGroup cls=['text-sm','opacity-70']
              AXStaticText V="..."
            AXButton T="Cancel"
            AXButton T="Confirm ↵"

    Returns:
        dict or None: {
            "dialog_type": "confirm_undo",
            "has_code_changes": bool,
            "description": str,
            "file_changes": [{"file": str, "detail": str}],
        }
    """
    agent_section = _find_agent_section(window)
    search_root = agent_section if agent_section else window

    # Find the Confirm Undo heading
    heading = _find_heading_by_title(search_root, "Confirm Undo")
    if not heading:
        return None

    # Walk up to the dialog body (parent of heading)
    dialog_body = _get_attr(heading, "AXParent")
    if not dialog_body:
        return None

    # Extract description text and file changes
    description = ""
    file_changes = []
    for child in _get_children(dialog_body):
        role = _safe_str(_get_attr(child, kAXRoleAttribute))
        classes = _get_class_list(child)

        # Description group: text-sm + opacity-70
        if role == "AXGroup" and "text-sm" in classes and "opacity-70" in classes:
            description = _collect_inner_text(child).strip()
            continue

        # File change entries (emoji + filename + diff counts)
        if role == "AXGroup" and "text-sm" not in classes:
            texts = _collect_static_texts(child)
            if texts:
                joined = " ".join(texts)
                # Look for file-like entries (e.g. "app.py +1 -1")
                if any("." in t for t in texts):
                    file_changes.append({"file": texts[0], "detail": joined})

    has_code_changes = "will not make any code changes" not in description

    return {
        "dialog_type": "confirm_undo",
        "has_code_changes": has_code_changes,
        "description": description,
        "file_changes": file_changes,
    }


def press_confirm_undo(window):
    """
    Press the Confirm button in the Confirm Undo dialog.

    Searches for AXButton T="Confirm ↵" within the dialog.

    Returns:
        bool: True if found and pressed
    """
    agent_section = _find_agent_section(window)
    search_root = agent_section if agent_section else window

    heading = _find_heading_by_title(search_root, "Confirm Undo")
    if not heading:
        return False

    dialog_body = _get_attr(heading, "AXParent")
    if not dialog_body:
        return False

    # Find the Confirm button (T="Confirm ↵")
    confirm_btn = _find_button_by_title(dialog_body, "Confirm ↵")
    if not confirm_btn:
        return False

    AXUIElementPerformAction(confirm_btn, "AXPress")
    return True


def press_cancel_undo(window):
    """
    Press the Cancel button in the Confirm Undo dialog.

    Returns:
        bool: True if found and pressed
    """
    agent_section = _find_agent_section(window)
    search_root = agent_section if agent_section else window

    heading = _find_heading_by_title(search_root, "Confirm Undo")
    if not heading:
        return False

    dialog_body = _get_attr(heading, "AXParent")
    if not dialog_body:
        return False

    cancel_btn = _find_button_by_title(dialog_body, "Cancel")
    if not cancel_btn:
        return False

    AXUIElementPerformAction(cancel_btn, "AXPress")
    return True


def click_new_conversation(window):
    """
    Click the 'New Conversation' link in the Agent Panel header.

    Benchmark pattern: Header AXLink[0] → AXPress.

    Returns:
        bool: True if successful
    """
    agent_section = _find_agent_section(window)
    if not agent_section:
        return False

    links = _find_header_links(agent_section)
    if not links:
        return False

    locators = get_ui_locators()["ide_components"]["header_actions"]
    expected_count = locators["expected_link_count"]
    
    if len(links) != expected_count:
        # TODO: OTA Hotpatch (Fetch remote configured JSON and reload)
        raise RuntimeError(f"IDE Layout Schema Mismatch: Expected {expected_count} links, found {len(links)}.")

    target_idx = locators["index_new_conversation"]
    AXUIElementPerformAction(links[target_idx], "AXPress")
    return True


def _find_header_links(section):
    """
    Find AXLink elements in the Agent Panel header.

    Pattern: a group containing both AXStaticText and AXLink children.
    Depth-agnostic — scans all levels within the section.
    """
    result = [None]

    def search(el, depth=0):
        if depth > 20 or result[0]:
            return
        role = _safe_str(_get_attr(el, kAXRoleAttribute))
        if role == "AXStaticText":
            parent = _get_attr(el, "AXParent")
            if parent:
                siblings = _get_children(parent)
                if any(
                    _safe_str(_get_attr(s, kAXRoleAttribute)) == "AXLink"
                    for s in siblings
                ):
                    result[0] = parent
                    return
        for c in _get_children(el):
            search(c, depth + 1)

    search(section)

    if not result[0]:
        return []

    return [
        c for c in _get_children(result[0])
        if _safe_str(_get_attr(c, kAXRoleAttribute)) == "AXLink"
    ]


# ── Past Conversations ───────────────────────────────────────

_CONVERSATION_EXCLUDE_TEXTS = (
    "AI may make mistakes",
    "Show ",
    "Running in",
    "Recent in",
    "Other Conversation",
    "Current",
)


def click_past_conversations(window):
    """
    Open the Past Conversations overlay (header links[1]).

    Returns:
        bool: True if successful
    """
    agent_section = _find_agent_section(window)
    if not agent_section:
        logger.warning("click_past_conversations: agent_section not found")
        return False

    links = _find_header_links(agent_section)
    logger.info(
        "click_past_conversations: found %d header links", len(links),
    )
    for i, link in enumerate(links):
        role = _safe_str(_get_attr(link, kAXRoleAttribute))
        desc = _safe_str(_get_attr(link, kAXDescriptionAttribute))
        title = _safe_str(_get_attr(link, "AXTitle"))
        logger.info("  link[%d]: role=%s desc=%s title=%s", i, role, desc, title)

    locators = get_ui_locators()["ide_components"]["header_actions"]
    expected_count = locators["expected_link_count"]

    if len(links) != expected_count:
        # TODO: OTA Hotpatch (Fetch remote configured JSON and reload)
        raise RuntimeError(f"IDE Layout Schema Mismatch: Expected {expected_count} links, found {len(links)}.")

    target_idx = locators["index_past_conversations"]
    AXUIElementPerformAction(links[target_idx], "AXPress")
    return True


def _find_overlay_container(window):
    """
    Find the Past Conversations overlay container by locating
    the search AXTextField and returning its parent container.

    AX structure (from dump):
      parent (overlay container)
        ├─ AXGroup → AXTextField (search field)
        ├─ AXGroup → AXStaticText "Current"
        ├─ AXGroup ★PRESS → conversation item
        ├─ ...
    """
    result = [None]

    def scan(el, depth=0):
        if depth > 25 or result[0]:
            return
        role = _safe_str(_get_attr(el, kAXRoleAttribute))
        if role == "AXTextField":
            ph = _safe_str(_get_attr(el, "AXPlaceholderValue"))
            if ph and "conversation" in ph.lower():
                result[0] = el
                return
        for c in _get_children(el):
            scan(c, depth + 1)

    scan(window)

    if not result[0]:
        return None

    # Walk up to find the container that holds both search field and items.
    # From dump: search field → parent(AXGroup) → parent(overlay container)
    current = result[0]
    for _ in range(3):
        parent = _get_attr(current, "AXParent")
        if not parent:
            break
        # Check if this parent has multiple AXGroup children with AXPress
        children = _get_children(parent)
        pressable = sum(
            1 for c in children
            if "AXPress" in (_get_actions_safe(c))
        )
        if pressable >= 2:
            return parent
        current = parent

    return None


def _get_actions_safe(el):
    err, actions = AXUIElementCopyActionNames(el, None)
    if err == 0 and actions:
        return list(actions)
    return []


def _collect_conversation_items(window):
    """
    Collect conversation items from the Past Conversations overlay.

    Strategy:
      1. Find overlay container via search field anchor.
      2. Scan direct children for AXGroup + AXPress.
      3. Extract title from first AXStaticText child.

    Returns:
        list[dict]: [{"title": str, "el": AXUIElement}]
    """
    container = _find_overlay_container(window)
    if not container:
        logger.warning("_collect_conversation_items: overlay container not found")
        return []

    items = []
    for child in _get_children(container):
        if "AXPress" not in _get_actions_safe(child):
            continue

        # Extract text from AXStaticText children
        texts = []
        for gc in _get_children(child):
            role = _safe_str(_get_attr(gc, kAXRoleAttribute))
            if role == "AXStaticText":
                val = _safe_str(_get_attr(gc, kAXValueAttribute))
                if val:
                    texts.append(val)

        if not texts:
            continue

        title = texts[0]

        # Exclude non-conversation entries
        excluded = False
        for exclude in _CONVERSATION_EXCLUDE_TEXTS:
            if exclude in title:
                excluded = True
                break
        if excluded:
            continue

        items.append({"title": title, "el": child})

    logger.debug(
        "_collect_conversation_items: found %d items in overlay", len(items),
    )
    return items



def list_conversations(window, controller):
    """
    Open Past Conversations overlay and return conversation list.

    Returns:
        list[str]: conversation titles
    """
    ok = click_past_conversations(window)
    if not ok:
        logger.warning("click_past_conversations failed")
        return []

    from agbridge.collectors.ax_polling import poll_until

    items = poll_until(
        lambda: _collect_conversation_items(window),
        controller,
        label="list_conversations",
    )
    titles = [item["title"] for item in items]
    logger.info("list_conversations found %d items: %s", len(titles), titles[:5])

    # Close overlay
    _press_escape()

    return titles


def select_conversation_by_title(window, target_title, controller):
    """
    Open Past Conversations, find and click the target conversation.

    Returns:
        bool: True if successful
    """
    ok = click_past_conversations(window)
    if not ok:
        return False

    from agbridge.collectors.ax_polling import poll_until

    items = poll_until(
        lambda: _collect_conversation_items(window),
        controller,
        label="select_conversation",
    )

    target_item = None
    for item in items:
        if target_title in item["title"]:
            target_item = item
            break

    if not target_item:
        _press_escape()
        return False

    AXUIElementPerformAction(target_item["el"], "AXPress")
    return True


# ── Typeahead support (keyboard simulation) ─────────────────

import re
import time as _time

_RE_WORKFLOW = re.compile(r"@\[/(\w+)\]")
_RE_MENTION = re.compile(r"@\[([^\]]+)\]")


def _simulate_keypress(keycode, cmd=False):
    """Press and release a single key via CGEvent."""
    from Quartz import (
        CGEventCreateKeyboardEvent,
        CGEventPost,
        CGEventSetFlags,
        kCGHIDEventTap,
        kCGEventFlagMaskCommand,
    )
    flags = kCGEventFlagMaskCommand if cmd else 0

    event_down = CGEventCreateKeyboardEvent(None, keycode, True)
    event_up = CGEventCreateKeyboardEvent(None, keycode, False)
    if flags:
        CGEventSetFlags(event_down, flags)
        CGEventSetFlags(event_up, flags)

    CGEventPost(kCGHIDEventTap, event_down)
    _time.sleep(0.01)
    CGEventPost(kCGHIDEventTap, event_up)


def _type_unicode_char(ch):
    """Inject a single unicode character via CGEvent (IME-independent)."""
    from Quartz import (
        CGEventCreateKeyboardEvent,
        CGEventPost,
        CGEventKeyboardSetUnicodeString,
        kCGHIDEventTap,
    )
    event_down = CGEventCreateKeyboardEvent(None, 0, True)
    CGEventKeyboardSetUnicodeString(event_down, len(ch), ch)
    CGEventPost(kCGHIDEventTap, event_down)
    _time.sleep(0.01)
    event_up = CGEventCreateKeyboardEvent(None, 0, False)
    CGEventPost(kCGHIDEventTap, event_up)


def _type_text_hw(text):
    """Type text character-by-character via unicode injection."""
    for ch in text:
        _type_unicode_char(ch)
        _time.sleep(0.02)


def _paste_text(text):
    """Paste text via clipboard + Cmd+V."""
    from AppKit import NSPasteboard, NSPasteboardTypeString
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(text, NSPasteboardTypeString)
    _time.sleep(0.05)
    _simulate_keypress(9, cmd=True)  # keycode 9 = V


def _get_ax_value_str(el):
    """Get AXValue as string."""
    err, val = AXUIElementCopyAttributeValue(el, kAXValueAttribute, None)
    if err == 0 and val is not None:
        return str(val)
    return ""


def _find_typeahead(window):
    """Find the typeahead-menu AXList (DOM ID = typeahead-menu)."""
    result = [None]

    def scan(el, depth=0):
        if depth > 12 or result[0]:
            return
        err, eid = AXUIElementCopyAttributeValue(el, "AXDOMIdentifier", None)
        if err == 0 and eid and str(eid) == "typeahead-menu":
            result[0] = el
            return
        for c in _get_children(el):
            scan(c, depth + 1)

    scan(window)
    return result[0]


def _wait_typeahead(window, controller):
    """Wait for typeahead popup to appear."""
    from agbridge.collectors.ax_polling import poll_until
    return poll_until(
        lambda: _find_typeahead(window),
        controller,
        interval=0.05,
        label="typeahead",
    )


def _confirm_typeahead(msg_input, before_value):
    """Confirm typeahead selection with Tab, fallback to Enter."""
    _KC_TAB = 48
    _KC_ENTER = 36

    _simulate_keypress(_KC_TAB)
    _time.sleep(0.2)

    after = _get_ax_value_str(msg_input)
    if after != before_value:
        return after

    _simulate_keypress(_KC_ENTER)
    _time.sleep(0.2)

    after2 = _get_ax_value_str(msg_input)
    if after2 != before_value:
        return after2

    return None


def _apply_workflow_typeahead(window, msg_input, name, controller):
    """Apply workflow via typeahead: type '/' → name → Tab."""
    before = _get_ax_value_str(msg_input)
    _type_unicode_char("/")

    if not _wait_typeahead(window, controller):
        _press_escape()
        return False

    _type_text_hw(name)
    _time.sleep(0.3)

    result = _confirm_typeahead(msg_input, before)
    return result is not None


def _apply_mention_typeahead(window, msg_input, path, controller):
    """Apply @mention via typeahead: type '@' → filter → Tab."""
    before = _get_ax_value_str(msg_input)
    _type_unicode_char("@")

    if not _wait_typeahead(window, controller):
        _press_escape()
        return False

    # Use basename for efficient filtering
    parts = path.rstrip("/").split("/")
    filter_text = parts[-1] if parts else path
    _type_text_hw(filter_text)
    _time.sleep(0.3)

    result = _confirm_typeahead(msg_input, before)
    return result is not None


def _parse_directives(text):
    """
    Extract workflow and mentions from prompt text.

    Returns:
        (workflow, mentions, clean_text)
    """
    workflow = None
    wf_match = _RE_WORKFLOW.search(text)
    if wf_match:
        workflow = wf_match.group(1)
    remaining = _RE_WORKFLOW.sub("", text)

    mentions = [m.group(1).strip() for m in _RE_MENTION.finditer(remaining)]
    remaining = _RE_MENTION.sub("", remaining)

    clean_text = remaining.strip()
    return workflow, mentions, clean_text


# ── Message input injection ─────────────────────────────────

def find_message_input(window, depth=0, max_depth=30):
    """Find the Message Input (AXTextArea desc='Message input')."""
    agent_section = _find_agent_section(window)
    search_root = agent_section if agent_section else window
    return _find_message_input_dfs(search_root, depth=0, max_depth=max_depth)


def _find_message_input_dfs(el, depth=0, max_depth=30):
    if depth > max_depth:
        return None

    role = _safe_str(_get_attr(el, kAXRoleAttribute))
    desc = _safe_str(_get_attr(el, kAXDescriptionAttribute))

    if role == AX_MESSAGE_INPUT_ROLE and desc == AX_MESSAGE_INPUT_DESC:
        return el

    for c in _get_children(el):
        found = _find_message_input_dfs(c, depth + 1, max_depth)
        if found:
            return found
    return None


def read_input_text(window):
    """Read current text from the Message Input AXTextArea.

    Used after undo operations to detect prompt restoration by the IDE.

    Returns:
        str: Current input text, or empty string if not found.
    """
    msg_input = find_message_input(window)
    if not msg_input:
        return ""
    value = _safe_str(_get_attr(msg_input, kAXValueAttribute))
    return value or ""


def _clear_and_refocus(msg_input):
    """Clear all text in the prompt and re-establish focus.

    1. Cmd+A — select all text in the focused input
    2. Backspace — delete the selection
    3. Re-focus — restore focus that may be lost after deletion
    """
    _simulate_keypress(0, cmd=True)   # Cmd+A (select all)
    _time.sleep(0.05)
    _simulate_keypress(51)            # Backspace (delete selection)
    _time.sleep(0.05)

    # Re-focus after deletion — Backspace can cause focus loss
    AXUIElementSetAttributeValue(msg_input, kAXFocusedAttribute, True)
    _time.sleep(0.1)


def inject_prompt(window, text, controller):
    """
    Inject text into the Message Input and press the Send button.

    Clears any existing content first, then applies directives:
        @[/workflow]  → applied via typeahead ('/' trigger)
        @[path]       → applied via typeahead ('@' trigger)
        plain text    → pasted via clipboard

    Returns:
        bool: True if successful
    """
    msg_input = find_message_input(window)
    if not msg_input:
        return False

    AXUIElementSetAttributeValue(msg_input, kAXFocusedAttribute, True)
    _time.sleep(0.1)

    # Clear existing content and re-establish focus
    _clear_and_refocus(msg_input)

    workflow, mentions, clean_text = _parse_directives(text)

    # 1. Apply workflow via typeahead
    if workflow:
        ok = _apply_workflow_typeahead(window, msg_input, workflow, controller)
        if not ok:
            logger.warning("Typeahead failed for workflow '%s', injecting as text", workflow)
            clean_text = f"@[/{workflow}] {clean_text}"

    # 2. Apply mentions via typeahead
    for mention_path in mentions:
        ok = _apply_mention_typeahead(window, msg_input, mention_path, controller)
        if not ok:
            logger.warning("Typeahead failed for mention '%s', injecting as text", mention_path)
            clean_text = f"@[{mention_path}] {clean_text}"

    # 3. Paste remaining clean text
    if clean_text:
        _paste_text(clean_text)
        _time.sleep(0.2)

    # 4. Press Send
    agent_section = _find_agent_section(window)
    search_root = agent_section if agent_section else window
    send_btn = _find_button_by_desc(search_root, AX_SEND_BUTTON_DESC)
    if not send_btn:
        return False
    AXUIElementPerformAction(send_btn, "AXPress")
    return True


# ── Agent edit actions (Accept all / Reject all) ────────────

_edit_action_cache = {
    "accept_all": None,
    "reject_all": None,
}


def _find_edit_action_groups(el, depth=0, max_depth=20, results=None):
    """
    Find AXGroup containers whose child AXStaticText has
    value="Accept all" or value="Reject all".
    """
    if results is None:
        results = {}
    if depth > max_depth:
        return results

    role = _safe_str(_get_attr(el, kAXRoleAttribute))

    if role == "AXGroup":
        for c in _get_children(el):
            c_role = _safe_str(_get_attr(c, kAXRoleAttribute))
            c_value = _safe_str(_get_attr(c, kAXValueAttribute))
            if c_role == "AXStaticText":
                if c_value == "Accept all":
                    err, actions = AXUIElementCopyActionNames(el, None)
                    if err == 0 and actions and "AXPress" in actions:
                        results["accept_all"] = el
                elif c_value == "Reject all":
                    err, actions = AXUIElementCopyActionNames(el, None)
                    if err == 0 and actions and "AXPress" in actions:
                        results["reject_all"] = el

    if "accept_all" in results and "reject_all" in results:
        return results

    for c in _get_children(el):
        _find_edit_action_groups(c, depth + 1, max_depth, results)
        if "accept_all" in results and "reject_all" in results:
            return results
    return results


def collect_edit_actions(window):
    """
    Detect whether Accept all / Reject all buttons are present.

    Returns:
        dict: {
            "has_pending_edits": bool,
            "accept_all_available": bool,
            "reject_all_available": bool,
        }
    """
    agent_section = _find_agent_section(window)
    search_root = agent_section if agent_section else window
    groups = _find_edit_action_groups(search_root)

    _edit_action_cache["accept_all"] = groups.get("accept_all")
    _edit_action_cache["reject_all"] = groups.get("reject_all")

    has_accept = _edit_action_cache["accept_all"] is not None
    has_reject = _edit_action_cache["reject_all"] is not None

    return {
        "has_pending_edits": has_accept or has_reject,
        "accept_all_available": has_accept,
        "reject_all_available": has_reject,
    }


def press_edit_action(action_type):
    """
    Press the cached Accept all or Reject all button.

    Args:
        action_type: "accept_all" or "reject_all"

    Returns:
        bool: True if the button was found and pressed
    """
    el = _edit_action_cache.get(action_type)
    if el is None:
        return False
    AXUIElementPerformAction(el, "AXPress")
    return True
