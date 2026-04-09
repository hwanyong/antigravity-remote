"""
Git Panel — Multi-Worktree Source Control

Provides per-worktree independent UI sections matching the VS Code/Antigravity
Source Control pattern. Each worktree (branch) gets its own staged changes
list and unstaged changes list.

Data schema from server:
    {"worktrees": [{"path": str, "branch": str, "staged": [...], ...}, ...]}
"""

import os
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Collapsible, Label, ListItem, ListView, Static
from textual.message import Message


class GitFileItem(ListItem):
    """A single file item in the Git list."""

    def __init__(self, filename, filepath, status, worktree_path, is_staged=False, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.filepath = filepath
        self.status = status
        self.worktree_path = worktree_path
        self.is_staged = is_staged

    def compose(self) -> ComposeResult:
        with Horizontal(classes="git-file-row"):
            yield Label(self.status, classes=f"git-status git-status-{self.status}")
            yield Label(self.filename, classes="git-filename")
            path_dir = os.path.dirname(self.filepath)
            yield Label(f" {path_dir}" if path_dir else "", classes="git-filepath")
            with Horizontal(classes="git-actions"):
                if self.is_staged:
                    # Staged → can unstage
                    yield Button("-", classes="git-action-btn git-btn-unstage", tooltip="Unstage")
                else:
                    # Unstaged → can stage or discard
                    yield Button("+", classes="git-action-btn git-btn-stage", tooltip="Stage")
                    yield Button("🗑", classes="git-action-btn git-btn-discard", tooltip="Discard")


class WorktreeSection(Vertical):
    """Self-contained source control section for a single worktree."""

    def __init__(self, worktree_path, branch, **kwargs):
        super().__init__(**kwargs)
        self.worktree_path = worktree_path
        self.branch = branch
        self.staged = []
        self.modified = []
        self.deleted = []
        self.untracked = []

    def compose(self) -> ComposeResult:
        dir_name = os.path.basename(self.worktree_path)
        with Collapsible(title=f"📂 {dir_name} — {self.branch}", classes="wt-section"):
            with Collapsible(title="Staged Changes (0)", classes="wt-col-staged"):
                yield ListView(classes="wt-list-staged")
            with Collapsible(title="Changes (0)", classes="wt-col-changes"):
                yield ListView(classes="wt-list-changes")

    def update_status(self, data):
        """Update this worktree's status data and rebuild lists."""
        self.branch = data.get("branch", self.branch)
        self.staged = data.get("staged", [])
        self.modified = data.get("modified", [])
        self.deleted = data.get("deleted", [])
        self.untracked = data.get("untracked", [])
        self._rebuild_lists()

    def _rebuild_lists(self):
        try:
            list_staged = self.query_one(".wt-list-staged", ListView)
            list_changes = self.query_one(".wt-list-changes", ListView)
            col_staged = self.query_one(".wt-col-staged", Collapsible)
            col_changes = self.query_one(".wt-col-changes", Collapsible)
        except Exception:
            return

        list_staged.clear()
        list_changes.clear()

        for path in self.staged:
            list_staged.append(
                GitFileItem(os.path.basename(path), path, "S", self.worktree_path, is_staged=True)
            )

        for path in self.modified:
            list_changes.append(
                GitFileItem(os.path.basename(path), path, "M", self.worktree_path)
            )
        for path in self.deleted:
            list_changes.append(
                GitFileItem(os.path.basename(path), path, "D", self.worktree_path)
            )
        for path in self.untracked:
            list_changes.append(
                GitFileItem(os.path.basename(path), path, "U", self.worktree_path)
            )

        col_staged.title = f"Staged Changes ({len(self.staged)})"
        changes_count = len(self.modified) + len(self.deleted) + len(self.untracked)
        col_changes.title = f"Changes ({changes_count})"


class GitPanel(Vertical):
    """Multi-worktree Source Control panel."""

    class GitStageRequest(Message):
        def __init__(self, path, worktree_path):
            self.path = path
            self.worktree_path = worktree_path
            super().__init__()

    class GitUnstageRequest(Message):
        def __init__(self, path, worktree_path):
            self.path = path
            self.worktree_path = worktree_path
            super().__init__()

    class GitDiscardRequest(Message):
        def __init__(self, path, worktree_path):
            self.path = path
            self.worktree_path = worktree_path
            super().__init__()

    class GitCommitRequest(Message):
        def __init__(self, message, worktree_path):
            self.commit_message = message
            self.worktree_path = worktree_path
            super().__init__()

    class GitRefreshStatusRequest(Message):
        pass

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.border_title = "Source Control"

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="git-scroll-area")

    def update_git(self, data):
        """Update Git status from server data."""
        if not data:
            return

        worktrees = data.get("worktrees", [])
        try:
            scroll = self.query_one("#git-scroll-area", VerticalScroll)
        except Exception:
            return

        existing = {
            section.worktree_path: section
            for section in scroll.query(WorktreeSection)
        }

        seen_paths = set()
        for wt_data in worktrees:
            wt_path = wt_data.get("path", "")
            if not wt_path:
                continue
            seen_paths.add(wt_path)

            if wt_path in existing:
                existing[wt_path].update_status(wt_data)
            else:
                section = WorktreeSection(
                    worktree_path=wt_path,
                    branch=wt_data.get("branch", ""),
                )
                scroll.mount(section)
                self.call_after_refresh(section.update_status, wt_data)

        for wt_path, section in existing.items():
            if wt_path not in seen_paths:
                section.remove()

    def on_button_pressed(self, event: Button.Pressed):
        btn = event.button

        if btn.has_class("git-action-btn"):
            # Walk ancestors to find the owning GitFileItem
            file_item = None
            for ancestor in btn.ancestors_with_self:
                if isinstance(ancestor, GitFileItem):
                    file_item = ancestor
                    break
            if not file_item:
                return

            path = file_item.filepath
            wt_path = file_item.worktree_path

            if btn.has_class("git-btn-stage"):
                self.post_message(self.GitStageRequest(path, wt_path))
            elif btn.has_class("git-btn-unstage"):
                self.post_message(self.GitUnstageRequest(path, wt_path))
            elif btn.has_class("git-btn-discard"):
                self.post_message(self.GitDiscardRequest(path, wt_path))
