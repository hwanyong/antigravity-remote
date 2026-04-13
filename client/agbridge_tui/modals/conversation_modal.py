"""
ConversationModal — Rich conversation browser matching Antigravity IDE layout.

Layer 2: MODAL — translucent overlay with categorized, searchable list.

Features:
  - Category headers (Current / Recent in <ws>)
  - Timestamp display (right-aligned, dim)
  - Active conversation highlight
  - Client-side search filtering
  - Delete action (d key → confirmation)
  - "Show N more..." expansion

Dismisses with:
  - ("select", title)    — user selected a conversation
  - ("delete", title)    — user confirmed deletion
  - ("show_more", text)  — user clicked Show N more
  - None                 — cancelled
"""

from rich.markup import escape as rich_escape
from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListView, ListItem


class ConversationModal(ModalScreen):
    """Conversation browser with search, categories, and delete support."""

    CSS = """
    ConversationModal {
        layout: vertical;
        align: center middle;
        background: transparent;
    }
    #conv-dialog {
        width: 90%;
        max-width: 70;
        min-width: 40;
        max-height: 80%;
        background: $surface;
        border: thick $secondary;
        padding: 1 2;
    }
    #conv-search {
        margin-bottom: 0;
    }
    ConversationModal .conv-title-bar {
        height: 1;
        margin: 0;
        padding: 0;
    }
    ConversationModal .conv-title {
        text-style: bold;
    }
    ConversationModal .conv-hint {
        color: $text-muted;
        text-style: italic;
    }
    ConversationModal ListView {
        height: auto;
        max-height: 40;
        border: none;
        background: transparent;
        margin: 0;
        padding: 0;
    }
    ConversationModal .conv-category {
        padding: 0 1;
        height: 1;
        color: $text-muted;
        text-style: bold italic;
    }
    ConversationModal .conv-item {
        padding: 0 1;
        height: 1;
    }
    ConversationModal .conv-item-active {
        background: $accent 20%;
    }
    ConversationModal .conv-show-more {
        padding: 0 1;
        height: 1;
        color: $accent;
        text-style: italic;
    }
    ConversationModal .conv-count {
        height: 1;
        color: $text-muted;
        margin: 0;
        padding: 0;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Close"),
    ]

    def __init__(self, conversations, on_delete=None, **kwargs):
        """
        Args:
            conversations: list[dict] — mixed items:
                {type: "conversation", title, time, workspace, category, is_active}
                {type: "show_more", text: "Show 33 more..."}
            on_delete: truthy to enable delete (d key).
        """
        super().__init__(**kwargs)
        self._conversations = conversations or []
        self._on_delete = on_delete
        self._filter = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="conv-dialog"):
            yield Input(
                placeholder="Search conversations...",
                id="conv-search",
            )
            with Horizontal(classes="conv-title-bar"):
                yield Label("[bold]Past Conversations[/]", classes="conv-title")
                hint = "  [dim italic]d:delete[/]" if self._on_delete else ""
                yield Label(hint, classes="conv-hint")
            yield ListView(*self._build_items(self._conversations), id="conv-list")
            conv_count = self._count_conversations(self._conversations)
            yield Label(
                f"[dim]{conv_count} conversations[/]",
                id="conv-count",
                classes="conv-count",
            )

    def _count_conversations(self, convs):
        """Count only conversation-type entries."""
        return sum(1 for c in convs if c.get("type") != "show_more")

    def _build_items(self, convs):
        """Build ListItem list with category headers and show-more entries."""
        items = []
        last_category = None

        for conv in convs:
            item_type = conv.get("type", "conversation")

            if item_type == "show_more":
                items.append(_ShowMoreItem(conv.get("text", "Show more...")))
                continue

            category = conv.get("category", "")
            if category and category != last_category:
                items.append(_CategoryHeader(category))
                last_category = category

            items.append(_ConversationItem(conv))

        return items

    def _refresh_list(self, filter_text=""):
        """Rebuild the list with optional text filter."""
        lv = self.query_one("#conv-list", ListView)
        lv.clear()

        needle = filter_text.lower()
        filtered = []
        for conv in self._conversations:
            if conv.get("type") == "show_more":
                if not needle:
                    filtered.append(conv)
                continue
            if needle:
                title = (conv.get("title") or "").lower()
                ws = (conv.get("workspace") or "").lower()
                if needle not in title and needle not in ws:
                    continue
            filtered.append(conv)

        for item in self._build_items(filtered):
            lv.append(item)

        # Update count
        count_label = self.query_one("#conv-count", Label)
        conv_count = self._count_conversations(filtered)
        total = self._count_conversations(self._conversations)
        if needle:
            count_label.update(f"[dim]{conv_count}/{total} matched[/]")
        else:
            count_label.update(f"[dim]{total} conversations[/]")

    def on_input_changed(self, event: Input.Changed):
        if event.input.id == "conv-search":
            self._filter = event.value
            self._refresh_list(self._filter)

    def on_list_view_selected(self, event: ListView.Selected):
        item = event.item
        if isinstance(item, _ConversationItem):
            self.dismiss(("select", item.title))
        elif isinstance(item, _ShowMoreItem):
            self.dismiss(("show_more", item.text))

    def on_key(self, event):
        if event.key == "d" and self._on_delete:
            lv = self.query_one("#conv-list", ListView)
            if lv.highlighted_child and isinstance(lv.highlighted_child, _ConversationItem):
                title = lv.highlighted_child.title
                self.dismiss(("delete", title))
                event.prevent_default()

    def action_cancel(self):
        self.dismiss(None)

    def on_click(self, event):
        """Click outside the dialog → dismiss."""
        try:
            dialog = self.query_one("#conv-dialog")
            if event.screen_offset not in dialog.region:
                self.dismiss(None)
        except Exception:
            pass

    def update_conversations(self, conversations):
        """Replace the conversation list (e.g. after expand/delete)."""
        self._conversations = conversations or []
        self._refresh_list(self._filter)


class _CategoryHeader(ListItem):
    """Non-selectable category separator."""

    def __init__(self, text, **kwargs):
        super().__init__(**kwargs)
        self._text = text
        self.disabled = True

    def compose(self) -> ComposeResult:
        yield Label(f"[bold dim]── {rich_escape(self._text)} ──[/]")
        self.add_class("conv-category")


class _ConversationItem(ListItem):
    """A single conversation entry: title + time on one line."""

    def __init__(self, conv, **kwargs):
        super().__init__(**kwargs)
        self.title = conv.get("title", "")
        self._time = conv.get("time", "")
        self._is_active = conv.get("is_active", False)

    def compose(self) -> ComposeResult:
        prefix = "● " if self._is_active else "  "
        title_text = f"{prefix}{rich_escape(self.title)}"
        time_text = f" [dim]{rich_escape(self._time)}[/]" if self._time else ""
        yield Label(f"{title_text}{time_text}")

        self.add_class("conv-item")
        if self._is_active:
            self.add_class("conv-item-active")


class _ShowMoreItem(ListItem):
    """Clickable 'Show N more...' expansion trigger."""

    def __init__(self, text, **kwargs):
        super().__init__(**kwargs)
        self.text = text

    def compose(self) -> ComposeResult:
        yield Label(f"  [italic]{rich_escape(self.text)}[/]")
        self.add_class("conv-show-more")
