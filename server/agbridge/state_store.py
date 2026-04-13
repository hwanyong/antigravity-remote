"""
agbridge.state_store — Central cache engine (RAM + JSON Disk Persistence)

Single Source of Truth for all collected data (file tree, Agent chat,
settings, Git status, etc.)

- Read:    Instant return from in-memory dict (O(1))
- Write:   Update RAM, then async flush to JSON file
- Restore: Load JSON from disk into RAM on daemon restart
"""

import json
import hashlib
import os
import time


class StateStore:
    """Single in-memory state store with JSON persistence."""

    def __init__(self, cache_path=None):
        self._state = {
            "fs_tree": {},
            "git_status": {},
            "agent_panel": {},
            "settings": {},
            "active_editor": {},
            "models_info": {
                "current_model": "",
                "current_mode": "",
                "available_models": [],
                "available_modes": [],
            },
            "ide_connected": False,
            "last_updated": 0,
        }
        self._hashes = {}
        self._cache_path = cache_path
        self._dirty = False

        if cache_path and os.path.isfile(cache_path):
            self._load_from_disk()

    # ── Read ─────────────────────────────────────────────────

    def snapshot(self):
        """Return a deep copy of the entire state."""
        return json.loads(json.dumps(self._state))

    def get(self, key):
        """Return a specific state section."""
        return self._state.get(key)

    # ── Write ────────────────────────────────────────────────

    def update(self, key, value, force=False):
        """
        Update a specific section.
        Returns True if the hash changed, signaling a broadcast is needed.
        If force=True, always update regardless of hash comparison.
        """
        serialized = json.dumps(value, sort_keys=True, ensure_ascii=False)
        new_hash = hashlib.sha256(serialized.encode()).hexdigest()
        old_hash = self._hashes.get(key)

        if not force and new_hash == old_hash:
            return False

        self._state[key] = value
        self._state["last_updated"] = time.time()
        self._hashes[key] = new_hash
        self._dirty = True
        return True

    def set_ide_connected(self, connected):
        """Set the IDE connection state."""
        self._state["ide_connected"] = connected
        self._state["last_updated"] = time.time()
        self._dirty = True

    # ── Persistence ──────────────────────────────────────────

    def flush_to_disk(self):
        """Write to disk if there are pending changes."""
        if not self._dirty or not self._cache_path:
            return

        cache_dir = os.path.dirname(self._cache_path)
        os.makedirs(cache_dir, exist_ok=True)

        tmp_path = self._cache_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self._state, f, ensure_ascii=False)
        os.replace(tmp_path, self._cache_path)
        self._dirty = False

    def _load_from_disk(self):
        """Restore state from disk cache."""
        with open(self._cache_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)

        for key, value in loaded.items():
            self._state[key] = value
            serialized = json.dumps(value, sort_keys=True, ensure_ascii=False)
            self._hashes[key] = hashlib.sha256(
                serialized.encode()
            ).hexdigest()
