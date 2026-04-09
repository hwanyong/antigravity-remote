"""
agbridge.collectors — watchdog-based file system event collector

Receives native OS FSEvents and updates the StateStore file tree.
Operates independently of IDE lifecycle (always active).
"""

import os
import time
import threading
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from agbridge.config import FS_DEBOUNCE_SECONDS


# Directories to ignore during scanning and monitoring
_IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv",
    ".agbridge_cache", ".DS_Store",
}


def _should_ignore(path):
    """Return True if the path contains any ignored directory component."""
    parts = Path(path).parts
    return any(p in _IGNORE_DIRS for p in parts)


def scan_tree(root):
    """
    Walk the entire workspace via os.walk and return a file tree dict.

    Returns:
        dict: {relative_path: {"type": "file"|"dir", "size": int, "mtime": float}}
    """
    tree = {}
    root = os.path.realpath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune ignored directories from the walk itself
        dirnames[:] = [d for d in dirnames if d not in _IGNORE_DIRS]

        rel_dir = os.path.relpath(dirpath, root)
        if rel_dir != ".":
            tree[rel_dir] = {"type": "dir", "size": 0, "mtime": 0}

        for fname in filenames:
            if fname in _IGNORE_DIRS:
                continue
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, root)
            try:
                st = os.stat(full)
                tree[rel] = {
                    "type": "file",
                    "size": st.st_size,
                    "mtime": st.st_mtime,
                }
            except OSError:
                pass

    return tree


class _DebouncedHandler(FileSystemEventHandler):
    """Debounces FS events and delivers them as a batch to the callback."""

    def __init__(self, root, on_batch):
        super().__init__()
        self._root = os.path.realpath(root)
        self._on_batch = on_batch
        self._pending = []
        self._lock = threading.Lock()
        self._timer = None

    def _schedule_flush(self):
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(
            FS_DEBOUNCE_SECONDS, self._flush
        )
        self._timer.daemon = True
        self._timer.start()

    def _flush(self):
        with self._lock:
            batch = list(self._pending)
            self._pending.clear()
        if batch:
            self._on_batch(batch)

    def _enqueue(self, event_type, src_path):
        if _should_ignore(src_path):
            return
        rel = os.path.relpath(src_path, self._root)
        with self._lock:
            self._pending.append({
                "event": event_type,
                "path": rel,
                "time": time.time(),
            })
        self._schedule_flush()

    def on_created(self, event):
        self._enqueue("created", event.src_path)

    def on_deleted(self, event):
        self._enqueue("deleted", event.src_path)

    def on_modified(self, event):
        if event.is_directory:
            return
        self._enqueue("modified", event.src_path)

    def on_moved(self, event):
        self._enqueue("deleted", event.src_path)
        self._enqueue("created", event.dest_path)


class FSWatcher:
    """Monitors a workspace directory using watchdog."""

    def __init__(self, root, on_batch):
        """
        Args:
            root: Workspace root path to watch
            on_batch: Callback receiving list[dict] of debounced events
        """
        self._root = os.path.realpath(root)
        self._handler = _DebouncedHandler(root, on_batch)
        self._observer = Observer()

    def start(self):
        """Start watching."""
        self._observer.schedule(
            self._handler, self._root, recursive=True
        )
        self._observer.daemon = True
        self._observer.start()

    def stop(self):
        """Stop watching."""
        self._observer.stop()
        self._observer.join(timeout=3)
