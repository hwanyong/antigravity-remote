"""
agbridge.editor.tokenizer — Prompt tokenization and Lexical state builder

Converts user prompt text into Lexical EditorState JSON.
Handles mentions: workflow (@[/name]), file (@[path]),
conversation (@[conversation:"title"]), rule (@[rule:name]).

Extracted from cdp_actions.py for Single Source of Truth.
"""

import json
import logging
import os
import re

logger = logging.getLogger("agbridge.editor.tokenizer")


# ── Workflow Resolution ──────────────────────────────────────

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


# ── Tokenizer ────────────────────────────────────────────────

_DIRECTIVE_RE = re.compile(r"@\[(/[^\]]+)\]|@\[([^\]]+)\]")


def _classify_mention(value):
    """Classify a non-workflow mention by its prefix.

    Returns:
        tuple[str, str]: (type, cleaned_value)
    """
    if value.startswith('conversation:'):
        # @[conversation:"title"] → strip prefix and quotes
        title = value[len('conversation:'):].strip().strip('"').strip("'")
        return ("conversation", title)

    if value.startswith('rule:'):
        return ("rule", value[len('rule:'):])

    # Default: file/directory mention
    return ("file", value)


def tokenize_prompt(text):
    """Split prompt text into (type, value) tokens.

    Recognizes:
        @[/workflow_name]         → ("workflow", "workflow_name")
        @[conversation:"title"]   → ("conversation", "title")
        @[rule:name]              → ("rule", "name")
        @[path/to/file]           → ("file", "path/to/file")
        plain text                → ("text", "the text")

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
            tokens.append(_classify_mention(match.group(2)))

        last_end = match.end()

    if last_end < len(text):
        tokens.append(("text", text[last_end:]))

    if not tokens:
        tokens.append(("text", text))

    return tokens


# ── Lexical Node Builder ─────────────────────────────────────

def tokens_to_lexical_children(tokens, workspace_root=None):
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

        elif token_type in ("file", "conversation", "rule"):
            data_payload = {}
            if token_type == "file":
                # EXACT IDE native mapping discovered via CDP tracing
                # Eliminates @[scope-item] UI fallback completely
                abs_path = token_value
                if workspace_root and not os.path.isabs(abs_path):
                    abs_path = os.path.join(workspace_root, abs_path)
                uri = abs_path if abs_path.startswith("file://") else f"file://{abs_path}"

                data_payload = {
                    "file": {
                        "absoluteUri": uri,
                    }
                }
            elif token_type == "conversation":
                data_payload = {
                    "recipe": {
                        "title": token_value,
                        "uri": f"conversation://{token_value}",
                    }
                }
            elif token_type == "rule":
                data_payload = {
                    "recipe": {
                        "title": token_value,
                        "uri": f"rule://{token_value}",
                    }
                }

            children.append({
                "type": "contextScopeItemMention",
                "trigger": "@",
                "value": "contextScopeItemMention",
                "version": 1,
                "data": {
                    "mentionText": token_value,
                    "data": json.dumps(data_payload, ensure_ascii=False),
                },
            })

    return children


# ── Lexical State Builder ────────────────────────────────────

def build_lexical_state(children):
    """Construct a complete Lexical EditorState dict.

    Args:
        children: List of Lexical child node dicts (from tokens_to_lexical_children).

    Returns:
        dict: Complete EditorState JSON-serializable dict.
    """
    return {
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
