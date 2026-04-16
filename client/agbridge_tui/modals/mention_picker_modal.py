"""
MentionPickerModal — 2-phase mention selection modal.

Mirrors the Antigravity IDE's @ mention typeahead UX:
  Phase 1: Category selection (Files, Directories, Workflows, Conversations, Rules)
  Phase 2: Item search and selection within the chosen category

Layer 2: MODAL — translucent overlay with centered list.
Dismisses with (category, selected_item) tuple, or None if cancelled.
"""

from rich.markup import escape as rich_escape
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ListView, ListItem


# ── Category definitions ─────────────────────────────────────

MENTION_CATEGORIES = [
    {"id": "files", "label": "Files", "icon": "📄"},
    {"id": "directories", "label": "Directories", "icon": "📁"},
    {"id": "workflows", "label": "Workflows", "icon": "⚡"},
    {"id": "conversations", "label": "Conversations", "icon": "💬"},
    {"id": "rules", "label": "Rules", "icon": "📋"},
]


# ── Phase 1: Category Picker ─────────────────────────────────

class MentionCategoryModal(ModalScreen):
    """Phase 1 — Select a mention category."""

    CSS = """
    MentionCategoryModal {
        layout: vertical;
        align: center middle;
        background: transparent;
    }
    #mention-cat-dialog {
        width: 90%;
        max-width: 50;
        min-width: 30;
        max-height: 16;
        background: $surface;
        border: thick $secondary;
        padding: 1 2;
    }
    MentionCategoryModal .mention-title {
        text-style: bold;
        margin-bottom: 1;
    }
    MentionCategoryModal ListView {
        height: auto;
        max-height: 10;
        border: none;
        background: transparent;
    }
    MentionCategoryModal .mention-cat-item {
        padding: 0 1;
        height: 1;
    }
    MentionCategoryModal .mention-cancel {
        margin-top: 1;
        width: 100%;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="mention-cat-dialog"):
            yield Label("[bold]@ Add Context[/]", classes="mention-title")
            children = [
                _CategoryItem(cat)
                for cat in MENTION_CATEGORIES
            ]
            yield ListView(*children, id="mention-cat-list")
            yield Button("Cancel", variant="default", classes="mention-cancel", id="mention-cat-cancel")

    def on_list_view_selected(self, event: ListView.Selected):
        item = event.item
        if isinstance(item, _CategoryItem):
            self.dismiss(item.category_id)

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "mention-cat-cancel":
            self.dismiss(None)

    def on_click(self, event):
        """Click outside the dialog -> dismiss."""
        try:
            dialog = self.query_one("#mention-cat-dialog")
            if event.screen_offset not in dialog.region:
                self.dismiss(None)
        except Exception:
            pass


class _CategoryItem(ListItem):
    """A single category item in MentionCategoryModal."""

    def __init__(self, cat, **kwargs):
        super().__init__(**kwargs)
        self.category_id = cat["id"]
        self._label = cat["label"]
        self._icon = cat["icon"]

    def compose(self) -> ComposeResult:
        yield Label(f"  {self._icon}  {self._label}")
        self.add_class("mention-cat-item")


# ── Phase 2: Item Picker ─────────────────────────────────────

class MentionItemModal(ModalScreen):
    """Phase 2 — Search and select an item within a category."""

    CSS = """
    MentionItemModal {
        layout: vertical;
        align: center middle;
        background: transparent;
    }
    #mention-item-dialog {
        width: 90%;
        max-width: 60;
        min-width: 30;
        max-height: 22;
        background: $surface;
        border: thick $secondary;
        padding: 1 2;
    }
    MentionItemModal .mention-title {
        text-style: bold;
        margin-bottom: 1;
    }
    MentionItemModal Input {
        margin-bottom: 1;
    }
    MentionItemModal ListView {
        height: auto;
        max-height: 14;
        border: none;
        background: transparent;
    }
    MentionItemModal .mention-item {
        padding: 0 1;
        height: 1;
    }
    MentionItemModal .mention-cancel {
        margin-top: 1;
        width: 100%;
    }
    """

    def __init__(self, category_label, items, icon="", **kwargs):
        """
        Args:
            category_label: Display name for the category header.
            items: list[str] — selectable items.
            icon: Emoji icon for the header.
        """
        super().__init__(**kwargs)
        self._category_label = category_label
        self._all_items = items or []
        self._icon = icon

    def compose(self) -> ComposeResult:
        with Vertical(id="mention-item-dialog"):
            yield Label(
                f"[bold]{self._icon}  {self._category_label}[/]",
                classes="mention-title",
            )
            yield Input(
                placeholder="Search...",
                id="mention-search",
            )
            children = [
                _MentionItem(item) for item in self._all_items
            ]
            yield ListView(*children, id="mention-item-list")
            yield Button(
                "Cancel", variant="default",
                classes="mention-cancel", id="mention-item-cancel",
            )

    def on_input_changed(self, event: Input.Changed):
        """Filter items as user types in the search box."""
        query = event.value.strip().lower()
        lv = self.query_one("#mention-item-list", ListView)
        lv.clear()

        filtered = self._all_items if not query else [
            item for item in self._all_items
            if query in item.lower()
        ]
        for item_text in filtered:
            lv.append(_MentionItem(item_text))

    def on_list_view_selected(self, event: ListView.Selected):
        item = event.item
        if isinstance(item, _MentionItem):
            self.dismiss(item.value)

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "mention-item-cancel":
            self.dismiss(None)

    def on_click(self, event):
        """Click outside the dialog -> dismiss."""
        try:
            dialog = self.query_one("#mention-item-dialog")
            if event.screen_offset not in dialog.region:
                self.dismiss(None)
        except Exception:
            pass


class _MentionItem(ListItem):
    """A single selectable item in MentionItemModal."""

    def __init__(self, value, **kwargs):
        super().__init__(**kwargs)
        self.value = value

    def compose(self) -> ComposeResult:
        yield Label(f"  {rich_escape(str(self.value))}")
        self.add_class("mention-item")
