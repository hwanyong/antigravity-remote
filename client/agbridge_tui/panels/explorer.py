"""
Explorer — file system tree + Git status panel.

Shows: workspace file tree with git markers, branch info, file counts.
Data-driven: apply_data(None) renders empty state.

Server's scan_tree() returns a FLAT dict:
  {"README.md": {"type": "file", "size": 12}, "src/main.py": {"type": "file", ...}}

This module converts it to a NESTED tree before rendering.
"""

from textual.widgets import Static, Tree
from textual.message import Message


class Explorer(Static):
    """File system explorer with Git status markers."""

    class FileSelected(Message):
        """Emitted when a file node is selected."""
        def __init__(self, path: str):
            super().__init__()
            self.path = path

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._git_branch = ""
        self._git_staged = []
        self._git_modified = []
        self._git_untracked = []
        self._git_deleted = []
        self._fs_tree = {}
        self._has_data = True
        self.border_title = "Explorer"

    def compose(self):
        yield Tree("workspace", id="fs-tree")

    def apply_data(self, data):
        """
        Apply workspace data or None (empty state).

        Args:
            data: dict (snapshot with fs_tree/git_status) or None.
        """
        if data is None:
            self._has_data = False
            self._fs_tree = {}
            self._git_branch = ""
            self._git_staged = []
            self._git_modified = []
            self._git_untracked = []
            self._git_deleted = []
            self._render_empty()
            return

        self._has_data = True
        # If data is a full snapshot, extract fs_tree
        if "fs_tree" in data:
            self.update_from_snapshot(data)
        else:
            self._rebuild_tree(data)

    def _render_empty(self):
        """Render empty state in the tree widget."""
        try:
            tree = self.query_one("#fs-tree", Tree)
        except Exception:
            return

        tree.clear()
        tree.root.set_label("[dim]No workspace[/]")
        tree.root.add_leaf("[dim]Open Antigravity to begin[/]")
        tree.root.expand()

    def update_from_snapshot(self, snapshot):
        """Populate tree from full snapshot data."""
        fs_tree = snapshot.get("fs_tree", {})
        git_status = snapshot.get("git_status", {})

        self._fs_tree = fs_tree
        self._has_data = True
        self._update_git(git_status)
        self._rebuild_tree(fs_tree)

    def update_git(self, data):
        """Update Git status display."""
        self._update_git(data)
        if self._fs_tree:
            self._rebuild_tree(self._fs_tree)

    def _update_git(self, data):
        if not data:
            return

        # Support new multi-worktree schema: {"worktrees": [...]}
        worktrees = data.get("worktrees")
        if worktrees is not None:
            # Merge all worktrees into flat lists
            branch_parts = []
            staged = []
            modified = []
            untracked = []
            deleted = []
            for wt in worktrees:
                if wt.get("branch"):
                    branch_parts.append(wt["branch"])
                staged.extend(wt.get("staged", []))
                modified.extend(wt.get("modified", []))
                untracked.extend(wt.get("untracked", []))
                deleted.extend(wt.get("deleted", []))
            self._git_branch = ", ".join(branch_parts) if branch_parts else ""
            self._git_staged = staged
            self._git_modified = modified
            self._git_untracked = untracked
            self._git_deleted = deleted
            return

        # Legacy single-dict fallback
        self._git_branch = data.get("branch", "")
        self._git_staged = data.get("staged", [])
        self._git_modified = data.get("modified", [])
        self._git_untracked = data.get("untracked", [])
        self._git_deleted = data.get("deleted", [])

    def _rebuild_tree(self, flat_tree):
        """Rebuild the Tree widget from flat fs_tree data."""
        try:
            tree = self.query_one("#fs-tree", Tree)
        except Exception:
            return

        tree.clear()

        # Set root label with git info
        git_info = ""
        if self._git_branch:
            staged_count = len(self._git_staged)
            mod_count = len(self._git_modified)
            git_info = f"  [dim]git:{self._git_branch} +{staged_count} ~{mod_count}[/]"

        tree.root.set_label(f"📁 workspace{git_info}")

        # Convert flat → nested, then render
        nested = self._flat_to_nested(flat_tree)
        self._add_nodes(tree.root, nested, "")
        tree.root.expand()

    @staticmethod
    def _flat_to_nested(flat_tree):
        """
        Convert flat-path dict to nested directory tree.

        Input:  {"src": {"type":"dir"}, "src/main.py": {"type":"file","size":15}}
        Output: {"src": {"main.py": {"type":"file","size":15}}}
        """
        root = {}
        for path, info in sorted(flat_tree.items()):
            parts = path.replace("\\", "/").split("/")

            if len(parts) == 1:
                # Top-level entry
                if info.get("type") == "dir":
                    root.setdefault(parts[0], {})
                else:
                    root[parts[0]] = info
                continue

            # Multi-component path — ensure intermediate dirs exist
            current = root
            for part in parts[:-1]:
                if part not in current or not isinstance(current.get(part), dict):
                    current[part] = {}
                # If it was stored as file metadata by mistake, replace
                elif "type" in current.get(part, {}):
                    current[part] = {}
                current = current[part]

            # Leaf
            leaf = parts[-1]
            if info.get("type") == "dir":
                current.setdefault(leaf, {})
            else:
                current[leaf] = info

        return root

    def _add_nodes(self, parent, tree_dict, current_path):
        """Recursively add nodes from the nested tree dict."""
        if not isinstance(tree_dict, dict):
            return

        def sort_key(item):
            name, value = item
            is_dir = isinstance(value, dict) and "type" not in value
            return (0 if is_dir else 1, name)

        for name, value in sorted(tree_dict.items(), key=sort_key):
            
            node_path = f"{current_path}/{name}" if current_path else name
            marker = self._git_marker(name)
            label = f"{name} {marker}" if marker else name

            if isinstance(value, dict) and "type" in value:
                # File metadata leaf: {"type": "file", "size": ...}
                parent.add_leaf(f"📄 {label}", data={"path": node_path})
            elif isinstance(value, dict):
                # Directory container: children dict
                node = parent.add(f"📂 {label}", expand=False)
                self._add_nodes(node, value, node_path)
            else:
                parent.add_leaf(f"📄 {label}", data={"path": node_path})

    def on_tree_node_selected(self, event: Tree.NodeSelected):
        """Handle tree node selection."""
        if getattr(event.node, "data", None) and isinstance(event.node.data, dict):
            path = event.node.data.get("path")
            if path:
                self.post_message(self.FileSelected(path))

    def _git_marker(self, filename):
        """Return git status marker for a file."""
        for path in self._git_staged:
            if path.endswith(filename):
                return "[green](A)[/]"
        for path in self._git_modified:
            if path.endswith(filename):
                return "[yellow](M)[/]"
        for path in self._git_untracked:
            if path.endswith(filename):
                return "[red](?)[/]"
        for path in getattr(self, "_git_deleted", []):
            if path.endswith(filename):
                return "[red](D)[/]"
        return ""
