"""
agbridge_tui.modals.file_explorer_modal — System File Explorer Modal

Layer 1: MODAL — always fullscreen.
"""

import os
import shutil
from pathlib import Path
from typing import Iterable

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DirectoryTree, Input, Label, Tree
from textual.widgets.tree import TreeNode

# _directory_tree has DirEntry
from textual.widgets._directory_tree import DirEntry

from agbridge_tui.permissions import has_full_disk_access
from agbridge_tui.modals.input_modal import InputModal
from agbridge_tui.modals.confirm_modal import ConfirmModal


class SafeDirectoryTree(DirectoryTree):
    """A DirectoryTree that gracefully handles PermissionError on macOS."""
    
    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        return [path for path in paths if not path.name.startswith(".") and path.is_dir()]

    def load_directory(self, node: TreeNode[DirEntry]) -> None:
        try:
            super().load_directory(node)
        except PermissionError:
            path = node.data.path if node.data else self.path
            self.app.log(f"Permission denied: {path}")
            if not node.children:
                node.add_leaf("🚫 Permission Denied")


class FileExplorerModal(ModalScreen[str]):
    """Modal for exploring the filesystem and picking a workspace."""

    CSS = """
    FileExplorerModal {
        layout: vertical;
        align: center middle;
        background: transparent;
    }
    #dialog {
        width: 95%;
        height: 80%;
        background: $surface;
        border: tall $primary;
        padding: 1 2;
    }
    .modal-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #fda_warning {
        color: $error;
        text-style: bold;
        margin-bottom: 1;
        display: none;
    }
    #path_input {
        margin-bottom: 1;
    }
    SafeDirectoryTree {
        height: 1fr;
        border: solid $primary;
        margin-bottom: 1;
    }
    FileExplorerModal Horizontal {
        layout: horizontal;
        align: center middle;
        height: auto;
        min-height: 3;
    }
    FileExplorerModal Button {
        width: 1fr;
        min-width: 8;
        margin: 0 1;
    }
    """

    def __init__(self, start_path="~", **kwargs):
        super().__init__(**kwargs)
        self.start_path = os.path.expanduser(start_path)
        self.selected_path = self.start_path

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Open Workspace Explorer", classes="modal-title")
            
            warning = Label("⚠️ Full Disk Access 권한이 필요합니다. 설정 -> 개인정보 보호 및 보안에서 앱을 추가해주세요.", id="fda_warning")
            if not has_full_disk_access():
                warning.display = True
            yield warning

            yield Input(value=self.start_path, id="path_input", placeholder="/path/to/directory")
            yield SafeDirectoryTree(self.start_path, id="file_tree")

            with Horizontal():
                yield Button("New", id="btn_create_folder", variant="default")
                yield Button("Delete", id="btn_delete_entry", variant="error")
                yield Button("Cancel", id="btn_cancel", variant="default")
                yield Button("Open", id="btn_open", variant="primary")

    def on_input_submitted(self, event: Input.Submitted):
        if event.input.id == "path_input":
            path = os.path.expanduser(event.value)
            if os.path.isdir(path):
                tree = self.query_one("#file_tree", SafeDirectoryTree)
                tree.path = path
                tree.reload()
            else:
                if hasattr(self.app, "notify"):
                    self.app.notify("Invalid directory path.", severity="error")

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted):
        node_data = event.node.data
        if node_data:
            self.selected_path = str(node_data.path)
        else:
            self.selected_path = self.start_path

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "btn_cancel":
            self.dismiss(None)
            
        elif event.button.id == "btn_open":
            self.dismiss(self.selected_path)
            
        elif event.button.id == "btn_create_folder":
            def on_create_submit(values):
                if values and values.get("folder_name"):
                    new_path = os.path.join(self.selected_path, values["folder_name"])
                    try:
                        os.makedirs(new_path, exist_ok=True)
                        self.query_one("#file_tree", SafeDirectoryTree).reload()
                    except PermissionError:
                        if hasattr(self.app, "notify"):
                            self.app.notify("Permission Denied.", severity="error")
                    except Exception as e:
                        if hasattr(self.app, "notify"):
                            self.app.notify(f"Error: {e}", severity="error")

            self.app.push_screen(
                InputModal(
                    title="Create Folder",
                    fields=[{"name": "folder_name", "label": "Folder Name:", "placeholder": "new_folder"}],
                ),
                on_create_submit,
            )
            
        elif event.button.id == "btn_delete_entry":
            target = self.selected_path
            
            def on_delete_confirm(confirmed):
                if confirmed:
                    try:
                        if os.path.isdir(target):
                            shutil.rmtree(target)
                        else:
                            os.remove(target)
                        self.query_one("#file_tree", SafeDirectoryTree).reload()
                    except PermissionError:
                        if hasattr(self.app, "notify"):
                            self.app.notify("Permission Denied.", severity="error")
                    except Exception as e:
                        if hasattr(self.app, "notify"):
                            self.app.notify(f"Error: {e}", severity="error")

            self.app.push_screen(
                ConfirmModal(
                    title="Delete Entry",
                    message=f"Delete '{target}'?\nThis cannot be undone.",
                    confirm_label="Delete",
                ),
                on_delete_confirm,
            )

    def on_click(self, event):
        """Click outside the dialog → dismiss."""
        try:
            main_content = self.query_one("#dialog")
            if event.screen_offset not in main_content.region:
                self.dismiss(None)
        except Exception:
            pass
