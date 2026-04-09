"""
agbridge.config — Daemon server configuration constants

All constants support environment variable overrides.
When UI identifiers change, only this file needs to be modified.
"""

import os


# ── Antigravity Process ──────────────────────────────────────

BUNDLE_ID = "com.google.antigravity"
ANTIGRAVITY_CMD = "antigravity"


# ── AX UI Identifiers ────────────────────────────────────────

AX_SEND_BUTTON_DESC = "Send message"
AX_CANCEL_BUTTON_DESC = "Cancel"
AX_MESSAGE_INPUT_DESC = "Message input"
AX_MESSAGE_INPUT_ROLE = "AXTextArea"

# Model / Mode popup selectors (AXPopUpButton title prefix)
AX_MODEL_POPUP_TITLE_PREFIX = "Select model"
AX_MODE_POPUP_TITLE_PREFIX = "Select conversation mode"

# Error banner markers (AXHeading title + AXButton titles)
AX_ERROR_HEADING_TEXT = "Agent terminated due to error"
AX_RETRY_BUTTON_TITLE = "Retry"
AX_DISMISS_BUTTON_TITLE = "Dismiss"

# Semantic selectors (stable class / DOM id set by Antigravity itself)
AX_AGENT_PANEL_CLASS = "antigravity-agent-side-panel"
AX_CONVERSATION_DOM_ID = "conversation"
AX_INPUT_BOX_DOM_ID = "antigravity.agentSidePanelInputBox"


# ── Polling Intervals (seconds) ──────────────────────────────

POLL_ACTIVE_INTERVAL = float(os.environ.get("AGBRIDGE_POLL_ACTIVE", "0.5"))
POLL_IDLE_INTERVAL = float(os.environ.get("AGBRIDGE_POLL_IDLE", "5.0"))
POLL_AWAIT_IDE_INTERVAL = float(os.environ.get("AGBRIDGE_POLL_AWAIT", "3.0"))

# FS event debouncing: batch events within this window before processing
FS_DEBOUNCE_SECONDS = 0.3


# ── Server ────────────────────────────────────────────────────

DEFAULT_HOST = os.environ.get("AGBRIDGE_HOST", "0.0.0.0")
DEFAULT_PORT = int(os.environ.get("AGBRIDGE_PORT", "18080"))

# StateStore persistence file
CACHE_DIR_NAME = ".agbridge_cache"
CACHE_FILE_NAME = "state_snapshot.json"


# ── Authentication ────────────────────────────────────────────

AUTH_ENABLED = os.environ.get("AGBRIDGE_AUTH_ENABLED", "true").lower() == "true"
AUTH_TOKEN = os.environ.get("AGBRIDGE_TOKEN", "")  # empty = auto-generate
AUTH_TOKEN_FILE = os.path.expanduser("~/.agbridge/token")


# ── WebSocket ─────────────────────────────────────────────────

MAX_WS_CLIENTS = int(os.environ.get("AGBRIDGE_MAX_CLIENTS", "3"))
WS_HEARTBEAT_INTERVAL = int(os.environ.get("AGBRIDGE_HEARTBEAT_INTERVAL", "30"))
WS_HEARTBEAT_TIMEOUT = int(os.environ.get("AGBRIDGE_HEARTBEAT_TIMEOUT", "60"))


# ── AX Error Recovery ─────────────────────────────────────────

AX_MAX_CONSECUTIVE_FAILURES = 3



# ── Window Discovery ─────────────────────────────────────

OWNER_NAME = "Antigravity"
TITLE_SEPARATOR = " \u2014 "   # em dash — Antigravity window title format: "workspace — file"
WORKSPACE_STORAGE_DIR = os.path.expanduser(
    "~/Library/Application Support/Antigravity/User/workspaceStorage"
)


# ── AX Write Operations ──────────────────────────────────

FOCUS_STABILIZE_SECONDS = 0.2   # wait time after focus switch before AX write
NS_ACTIVATE_OPTIONS = 1 << 1    # NSApplicationActivateIgnoringOtherApps
