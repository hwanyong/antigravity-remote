"""
agbridge.workspace.conversation_cache — Turn cache management

Extracted from engine.py (L571-697). Manages the file-backed
conversation turn cache for incremental DOM scraping.

The cache groups messages by _ti (turn index) and persists to
disk after each merge. Auto-invalidates on conversation title change.
"""

import json
import logging
import os

logger = logging.getLogger("agbridge.workspace.conversation_cache")


class ConversationCache:
    """File-backed conversation turn cache.

    Stores scraped messages indexed by turn number, enabling
    incremental DOM scraping without losing previously-scrolled content.
    """

    def __init__(self, workspace_id, cache_dir):
        """
        Args:
            workspace_id: Unique workspace identifier.
            cache_dir: Directory for the cache file.
        """
        self._workspace_id = workspace_id
        self._cache_path = os.path.join(
            cache_dir, f"turn_cache_{workspace_id}.json",
        )
        self._turns = {}          # int(turn_index) → list[dict]
        self._title = ""

    @property
    def title(self):
        return self._title

    @property
    def turn_count(self):
        return len(self._turns)

    # ── Load / Save / Delete ─────────────────────────────────

    def load(self):
        """Load turn cache from disk file."""
        if not os.path.isfile(self._cache_path):
            return
        try:
            with open(self._cache_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            self._title = payload.get("title", "")
            raw = payload.get("turns", {})
            # JSON keys are strings — convert back to int
            self._turns = {int(k): v for k, v in raw.items()}
            logger.info(
                "[%s] Turn cache loaded: %d turns (conv='%s')",
                self._workspace_id, len(self._turns),
                self._title[:40],
            )
        except (json.JSONDecodeError, ValueError, OSError) as e:
            logger.warning(
                "[%s] Turn cache load failed: %s",
                self._workspace_id, e,
            )
            self._turns.clear()

    def save(self):
        """Persist turn cache to disk file."""
        cache_dir = os.path.dirname(self._cache_path)
        os.makedirs(cache_dir, exist_ok=True)

        payload = {
            "title": self._title,
            "turns": self._turns,
        }
        tmp = self._cache_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, self._cache_path)

    def delete_file(self):
        """Remove cache file from disk."""
        try:
            os.remove(self._cache_path)
        except FileNotFoundError:
            pass

    # ── Merge / Flatten ──────────────────────────────────────

    def merge(self, agent_data):
        """Merge scraped messages into the turn cache.

        Groups incoming messages by _ti (turn index) and replaces
        the cache entry for each scraped turn. Auto-invalidates
        on conversation title change.

        Args:
            agent_data: dict from dom_scraper.collect_agent_panel().

        Returns:
            dict: The agent_data dict (modified in-place).
        """
        conv_title = agent_data.get("conversation_title", "")
        if conv_title and conv_title != self._title:
            self._turns.clear()
            self._title = conv_title
            self.delete_file()
            logger.info(
                "[%s] Conversation changed to '%s' — cache cleared",
                self._workspace_id, conv_title[:40],
            )

        messages = agent_data.get("messages", [])

        turn_groups = {}
        for msg in messages:
            ti = msg.pop("_ti", -1)
            if ti >= 0:
                turn_groups.setdefault(ti, []).append(msg)

        if turn_groups:
            for ti, msgs in turn_groups.items():
                self._turns[ti] = msgs
            self.save()

        return agent_data

    def flatten(self):
        """Flatten turn cache into a list of messages.

        Returns:
            list[dict]: Messages ordered by turn index, each with _turn_idx.
        """
        flat = []
        for ti in sorted(self._turns.keys()):
            for msg in self._turns[ti]:
                flat.append({**msg, "_turn_idx": ti})
        return flat

    # ── Clear / Truncate ─────────────────────────────────────

    def clear(self):
        """Clear all cached turns and delete the cache file."""
        self._turns.clear()
        self._title = ""
        self.delete_file()
        logger.info(
            "[%s] Cache cleared", self._workspace_id,
        )

    def truncate(self, turn_idx):
        """Truncate the turn cache from the given turn index onwards.

        Args:
            turn_idx: First turn index to delete (inclusive).

        Returns:
            dict: Empty agent_data placeholder with updated cache state.
        """
        keys_to_delete = [
            k for k in self._turns.keys() if k >= turn_idx
        ]
        for k in keys_to_delete:
            del self._turns[k]
        self.save()

        logger.info(
            "[%s] Turn cache truncated at index %d (deleted %d turns)",
            self._workspace_id, turn_idx, len(keys_to_delete),
        )
        return {
            "messages": self.flatten(),
            "_total_turns": 0,
            "_cached_turns": self.turn_count,
        }
