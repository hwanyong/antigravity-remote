"""
agbridge.cdp.selectors — DOM selector Single Source of Truth

Every DOM selector used by the system is declared here. Both Python
code and injected JS snippets reference this module, ensuring that
an IDE UI change only requires editing this one file.

Usage (Python):
    from agbridge.cdp.selectors import SELECTORS, build_js_header
    sel = SELECTORS["send_button"]

Usage (JS injection):
    header = build_js_header()
    full_js = header + "\n" + my_snippet
    # Inside my_snippet: document.querySelector(SEL_SEND_BUTTON)
"""


# ── Selector Table ───────────────────────────────────────────

SELECTORS = {
    # Editor
    "editor":               '[data-lexical-editor="true"]',
    "input_box":            "#antigravity\\.agentSidePanelInputBox",

    # Conversation
    "conversation":         "#conversation",
    "agent_panel":          ".antigravity-agent-side-panel",

    # Buttons — primary actions
    "send_button":          'button[aria-label="Send message"]',
    "cancel_button":        'button[aria-label="Cancel generation"]',
    "cancel_button_alt":    'button[aria-label="Cancel"]',

    # Buttons — edit actions
    "accept_all_button":    None,   # matched by textContent "Accept all"
    "reject_all_button":    None,   # matched by textContent "Reject all"

    # Buttons — error / retry
    "retry_button":         None,   # matched by textContent "Retry"
    "dismiss_button":       None,   # matched by textContent "Dismiss"

    # Buttons — permission
    "deny_button":          None,   # matched by textContent "Deny"

    # Navigation
    "new_conversation":     '[data-tooltip-id="new-conversation-tooltip"]',

    # Dropdowns
    "model_dropdown":       'button[aria-label*="Select model"]',
    "mode_dropdown":        'button[aria-label="Add context"]',

    # Conversation panel
    "past_conversations":   '[data-tooltip-id="past-conversations-tooltip"]',
}


# ── JS Header Builder ────────────────────────────────────────

def build_js_header():
    """Generate JS variable declarations for all selectors.

    Selectors with None are declared as null so JS code can
    use textContent matching fallback.

    Returns:
        str: JavaScript variable declarations block.
    """
    lines = []
    for key, selector in SELECTORS.items():
        var_name = f"SEL_{key.upper()}"
        if selector is None:
            lines.append(f"var {var_name} = null;")
        else:
            escaped = selector.replace("'", "\\'")
            lines.append(f"var {var_name} = '{escaped}';")
    return "\n".join(lines)


def get(key):
    """Retrieve a selector by key.

    Args:
        key: Selector name from the SELECTORS table.

    Returns:
        str or None: CSS selector string.

    Raises:
        KeyError: If key is not in the table.
    """
    return SELECTORS[key]


def js_query(key):
    """Build a JS querySelector expression for the given key.

    Args:
        key: Selector name.

    Returns:
        str: e.g. "document.querySelector('[data-lexical-editor=\"true\"]')"
             or None if selector is text-match based.
    """
    sel = SELECTORS.get(key)
    if sel is None:
        return None
    escaped = sel.replace("'", "\\'")
    return f"document.querySelector('{escaped}')"
