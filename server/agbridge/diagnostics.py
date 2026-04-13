"""
agbridge.diagnostics — JSON-based diagnostic record system

Generates individual JSON files for post-mortem tracking of:
  - Long-running polls (exceeding DIAG_POLL_THRESHOLD)
  - Aborted polls (PollAborted)
  - Failed InputQueue jobs

Diagnostic records capture the full context at the moment of anomaly:
  - Poll info (label, attempts, elapsed)
  - Scheduler state (all active polls)
  - Job context (action, params, workspace_id)
  - Caller-provided extra data (AXValue, etc.)

Storage: ~/.agbridge/logs/diagnostics/
Rotation: FIFO, max DIAG_MAX_FILES files
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

logger = logging.getLogger("agbridge.diagnostics")


class DiagnosticRecorder:
    """Generates and manages JSON diagnostic records.

    Thread-safe. May be called from InputQueue thread, poll_until thread,
    or the main asyncio thread.
    """

    def __init__(self):
        from agbridge.config import DIAG_DIR, DIAG_MAX_FILES
        self._diag_dir = DIAG_DIR
        self._max_files = DIAG_MAX_FILES
        self._lock = threading.Lock()
        os.makedirs(self._diag_dir, exist_ok=True)

    def record(self, event_type, label, poll_info=None,
               scheduler=None, job_context=None, extra=None):
        """Write a single JSON diagnostic record to disk.

        Args:
            event_type: "long_poll" | "poll_aborted" | "job_failed"
            label:      Human-readable tag (poll label or job action)
            poll_info:  {"attempts": int, "elapsed_seconds": float}
            scheduler:  PollScheduler instance (for list_active snapshot)
            job_context: {"action": str, "params": dict, "workspace_id": str}
            extra:      Caller-provided context (e.g. {"ax_value": "..."})
        """
        now = datetime.now(timezone.utc)
        timestamp_str = now.strftime("%Y%m%d_%H%M%S")
        safe_label = _sanitize_label(label)

        record = {
            "timestamp": now.isoformat(),
            "event_type": event_type,
            "label": label,
            "poll_info": poll_info,
            "scheduler_state": scheduler.list_active() if scheduler else None,
            "job_context": _mask_sensitive(job_context) if job_context else None,
            "extra": extra,
            "system": {
                "pid": os.getpid(),
                "thread": threading.current_thread().name,
            },
        }

        filename = f"diag_{timestamp_str}_{safe_label}.json"
        filepath = os.path.join(self._diag_dir, filename)

        with self._lock:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, indent=2, default=str)

            logger.info(
                "Diagnostic recorded: %s [%s] %s",
                event_type, label, filename,
            )

            self._cleanup_if_needed()

    def list_recent(self, limit=20):
        """Return most recent diagnostic file summaries.

        Returns:
            list[dict]: [{"filename": str, "timestamp": str, "event_type": str, "label": str}]
        """
        if not os.path.isdir(self._diag_dir):
            return []

        files = sorted(
            (f for f in os.listdir(self._diag_dir) if f.endswith(".json")),
            reverse=True,
        )[:limit]

        results = []
        for fname in files:
            fpath = os.path.join(self._diag_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                results.append({
                    "filename": fname,
                    "timestamp": data.get("timestamp", ""),
                    "event_type": data.get("event_type", ""),
                    "label": data.get("label", ""),
                })
            except (json.JSONDecodeError, OSError):
                results.append({
                    "filename": fname,
                    "timestamp": "",
                    "event_type": "unknown",
                    "label": "",
                })

        return results

    def get_record(self, filename):
        """Read a specific diagnostic record.

        Returns:
            dict or None
        """
        if not _is_safe_filename(filename):
            return None

        fpath = os.path.join(self._diag_dir, filename)
        if not os.path.isfile(fpath):
            return None

        with open(fpath, "r", encoding="utf-8") as f:
            return json.load(f)

    def _cleanup_if_needed(self):
        """Delete oldest files if count exceeds DIAG_MAX_FILES."""
        files = sorted(
            f for f in os.listdir(self._diag_dir) if f.endswith(".json")
        )
        excess = len(files) - self._max_files
        if excess <= 0:
            return

        for fname in files[:excess]:
            fpath = os.path.join(self._diag_dir, fname)
            os.remove(fpath)
            logger.debug("Diagnostic cleanup: removed %s", fname)


# ── Module-level singleton ───────────────────────────────

_recorder = None
_recorder_lock = threading.Lock()


def get_recorder():
    """Get or create the module-level DiagnosticRecorder singleton."""
    global _recorder
    if _recorder is None:
        with _recorder_lock:
            if _recorder is None:
                _recorder = DiagnosticRecorder()
    return _recorder


# ── Helpers ──────────────────────────────────────────────

_SENSITIVE_KEYS = frozenset({"token", "password", "secret", "api_key"})


def _mask_sensitive(data):
    """Deep-copy dict with sensitive keys masked."""
    if not isinstance(data, dict):
        return data

    result = {}
    for key, value in data.items():
        if key in _SENSITIVE_KEYS:
            result[key] = "***"
        elif isinstance(value, dict):
            result[key] = _mask_sensitive(value)
        else:
            result[key] = value
    return result


def _sanitize_label(label):
    """Sanitize label for use in filename."""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)
    return safe[:50] or "unknown"


def _is_safe_filename(filename):
    """Validate filename to prevent path traversal."""
    return (
        filename.endswith(".json")
        and "/" not in filename
        and "\\" not in filename
        and ".." not in filename
    )
