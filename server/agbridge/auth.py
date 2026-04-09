"""
agbridge.auth — Token-based authentication

Handles token lifecycle (generate / load / persist / verify)
and LAN IP detection for the startup connect URL.
"""

import hmac
import logging
import os
import secrets
import socket

from agbridge.config import AUTH_ENABLED, AUTH_TOKEN, AUTH_TOKEN_FILE

logger = logging.getLogger("agbridge.auth")

# Module-level active token (set once at startup)
_active_token = ""


def load_or_create_token():
    """
    Resolve the authentication token using priority order:
      1. AGBRIDGE_TOKEN environment variable
      2. Persisted token file (~/.agbridge/token)
      3. Auto-generate a new token

    Returns:
        str: The resolved token
    """
    global _active_token

    if not AUTH_ENABLED:
        _active_token = ""
        logger.info("Authentication disabled")
        return ""

    # Priority 1: environment variable
    if AUTH_TOKEN:
        _active_token = AUTH_TOKEN
        logger.info("Token loaded from environment variable")
        _save_token(_active_token)
        return _active_token

    # Priority 2: persisted file
    if os.path.isfile(AUTH_TOKEN_FILE):
        with open(AUTH_TOKEN_FILE, "r", encoding="utf-8") as f:
            stored = f.read().strip()
        if stored:
            _active_token = stored
            logger.info("Token loaded from %s", AUTH_TOKEN_FILE)
            return _active_token

    # Priority 3: auto-generate
    _active_token = secrets.token_hex(32)
    logger.info("New token generated")
    _save_token(_active_token)
    return _active_token


def _save_token(token):
    """Persist token to ~/.agbridge/token."""
    token_dir = os.path.dirname(AUTH_TOKEN_FILE)
    os.makedirs(token_dir, exist_ok=True)
    with open(AUTH_TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(token)
    # Restrict file permissions to owner only
    os.chmod(AUTH_TOKEN_FILE, 0o600)


def verify_token(candidate):
    """
    Verify a candidate token against the active token.
    Uses constant-time comparison to prevent timing attacks.

    Returns:
        bool: True if the token matches (or auth is disabled)
    """
    if not AUTH_ENABLED:
        return True
    if not _active_token:
        return True
    return hmac.compare_digest(candidate or "", _active_token)


def get_active_token():
    """Return the current active token string."""
    return _active_token


def get_local_ip():
    """
    Detect the primary LAN IP address of this machine.
    Falls back to 127.0.0.1 if detection fails.
    """
    try:
        # Connect to an external address (no actual data sent)
        # to determine which local interface is used for routing
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
