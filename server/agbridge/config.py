"""
agbridge.config — Daemon server configuration constants

All constants support environment variable overrides.
When UI identifiers change, only this file needs to be modified.
"""

import os


# ── Antigravity Process ──────────────────────────────────────

BUNDLE_ID = "com.google.antigravity"
ANTIGRAVITY_CMD = "antigravity"


# ── DOM Selectors ─────────────────────────────────────────────
#
# Stable identifiers used by CDP DOM queries.
# Migrated from AX UI identifiers to standard DOM selectors.

DOM_SEND_BUTTON_LABEL = "Send message"
DOM_CANCEL_BUTTON_LABEL = "Cancel generation"
DOM_CONVERSATION_ID = "conversation"
DOM_INPUT_BOX_ID = "antigravity.agentSidePanelInputBox"
DOM_AGENT_PANEL_CLASS = "antigravity-agent-side-panel"

# Model / Mode selectors (aria-label prefix)
DOM_MODEL_SELECTOR_PREFIX = "Select model"
DOM_MODE_SELECTOR_PREFIX = "Select conversation mode"

# Error banner markers
DOM_ERROR_HEADING_TEXT = "Agent terminated due to error"
DOM_RETRY_BUTTON_TEXT = "Retry"
DOM_DISMISS_BUTTON_TEXT = "Dismiss"


# ── Supervisor Reconciliation ─────────────────────────────────

POLL_AWAIT_IDE_INTERVAL = float(os.environ.get("AGBRIDGE_POLL_AWAIT", "3.0"))

# FS event debouncing: batch events within this window before processing
FS_DEBOUNCE_SECONDS = 0.3


# ── Server ────────────────────────────────────────────────────

DEFAULT_HOST = os.environ.get("AGBRIDGE_HOST", "0.0.0.0")
DEFAULT_PORT = int(os.environ.get("AGBRIDGE_PORT", "18080"))
KEEP_ALIVE_TIMEOUT = int(os.environ.get("AGBRIDGE_KEEP_ALIVE", "120"))

# StateStore persistence file
CACHE_DIR_NAME = ".agbridge_cache"
CACHE_FILE_NAME = "state_snapshot.json"


# ── Authentication ────────────────────────────────────────────

AUTH_ENABLED = os.environ.get("AGBRIDGE_AUTH_ENABLED", "true").lower() == "true"
AUTH_TOKEN = os.environ.get("AGBRIDGE_TOKEN", "")  # empty = auto-generate
AUTH_TOKEN_FILE = os.path.expanduser("~/.agbridge/token")


# ── WebSocket ─────────────────────────────────────────────────

MAX_WS_CLIENTS = int(os.environ.get("AGBRIDGE_MAX_CLIENTS", "10"))
WS_HEARTBEAT_INTERVAL = int(os.environ.get("AGBRIDGE_WS_HEARTBEAT", "60"))


# ── CDP Settings ─────────────────────────────────────────────

CDP_DIRECT_PORT = int(os.environ.get("AGBRIDGE_CDP_PORT", "9333"))
CDP_BASE_PORT = CDP_DIRECT_PORT       # Base port for dynamic allocation
CDP_PORT_RANGE = int(os.environ.get("AGBRIDGE_CDP_PORT_RANGE", "10"))
CDP_CONNECT_TIMEOUT = float(os.environ.get("AGBRIDGE_CDP_TIMEOUT", "5.0"))
CDP_RECONNECT_MAX = 3
# CDP_LAUNCH_FLAGS: port is injected dynamically by supervisor
CDP_LAUNCH_FLAGS_TEMPLATE = [
    "--remote-debugging-port={port}",
    "--remote-allow-origins=http://localhost:*",
]

# Event-driven: heartbeat full scrape interval (safety net)
CDP_HEARTBEAT_INTERVAL = int(os.environ.get("AGBRIDGE_CDP_HEARTBEAT", "30"))

# MutationObserver debounce delay (ms, injected into JS)
CDP_DEBOUNCE_MS = int(os.environ.get("AGBRIDGE_CDP_DEBOUNCE_MS", "100"))



# ── Window Discovery ─────────────────────────────────────

OWNER_NAME = "Antigravity"
TITLE_SEPARATOR = " \u2014 "   # em dash — Antigravity window title format: "workspace — file"
WORKSPACE_STORAGE_DIR = os.path.expanduser(
    "~/Library/Application Support/Antigravity/User/workspaceStorage"
)


# ── IDE Window Management ────────────────────────────────

NS_ACTIVATE_OPTIONS = 1 << 1    # NSApplicationActivateIgnoringOtherApps (close_ide fallback)


# ── Diagnostics & Logging ────────────────────────────────
#
# File-based logging with rotation + JSON diagnostic records
# for post-mortem tracking of polling anomalies and job failures.

LOG_DIR = os.path.expanduser("~/.agbridge/logs")
LOG_FILE = os.path.join(LOG_DIR, "agbridge.log")
LOG_MAX_BYTES = 5 * 1024 * 1024          # 5MB per file
LOG_BACKUP_COUNT = 5                      # keep 5 rotated files → max 25MB

DIAG_DIR = os.path.join(LOG_DIR, "diagnostics")
DIAG_POLL_THRESHOLD = 50                  # 50 polls → emit diagnostic record
DIAG_MAX_FILES = 100                      # FIFO cleanup of diagnostic files
