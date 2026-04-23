"""
Agent Panel — full interactive conversation panel.

Architecture: Vertical container with compose()-based widget tree.
  AgentHeader — state indicator + conversation title + Accept/Reject
  VerticalScroll — scrollable message history (MessageItem widgets)
  AgentInputBar — prompt input + Send/Cancel button
  AgentBottomBar — mode + model selection buttons

Data flow (Cache Architecture):
  Server events → update_from_agent / update_from_edit_actions /
                  update_from_editor / update_from_models
  User actions  → Message classes bubbled to app.py

  The server independently collects data in the background.
  TUI scrolling is purely local — it never triggers IDE scrolling.
"""

from rich.markup import escape as rich_escape

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Button, Label, Static, TextArea


_MIN_INPUT_HEIGHT = 3
_MAX_INPUT_HEIGHT = 10


# ── Prompt TextArea (multiline input) ────────────────────────

class PromptTextArea(TextArea):
    """Multiline prompt input with Enter-to-submit and auto-grow.

    Key bindings:
        Enter       → submit prompt (bubbles PromptSubmitRequest)
        Shift+Enter → insert newline (default TextArea behaviour)

    Auto-grow:
        Height adjusts from _MIN_INPUT_HEIGHT to _MAX_INPUT_HEIGHT
        based on document.line_count. Excess lines scroll internally.
    """

    class SubmitRequest(Message):
        """Bubbled when Enter is pressed to submit the prompt."""
        pass

    class TriggerDetected(Message):
        """Bubbled when a trigger character (/ or @) is typed."""
        def __init__(self, trigger):
            self.trigger = trigger
            super().__init__()

    def on_key(self, event: events.Key):
        if event.key == "enter":
            # Check for line continuation ('\' right before cursor)
            row, col = self.cursor_location
            line = self.document.get_line(row)
            
            if col > 0 and line[col - 1] == "\\":
                # Remove the '\' and insert a newline
                self.replace("\n", start=(row, col - 1), end=(row, col))
                event.prevent_default()
                event.stop()
                return

            # Plain Enter without '\' → submit prompt
            event.prevent_default()
            event.stop()
            self.post_message(self.SubmitRequest())
            return

        # Detect trigger characters for workflow/mention typeahead
        if event.character in ("/", "@"):
            text = self.text
            row, col = self.cursor_location
            # Trigger if it's the first char on the line, or preceded by whitespace
            if col == 0:
                self.post_message(self.TriggerDetected(event.character))
            elif col > 0:
                line = self.document.get_line(row)
                if col <= len(line) and line[col - 1].isspace():
                    self.post_message(self.TriggerDetected(event.character))

    def on_text_area_changed(self, event: TextArea.Changed):
        """Auto-grow height based on line count."""
        line_count = self.document.line_count
        new_height = max(_MIN_INPUT_HEIGHT, min(_MAX_INPUT_HEIGHT, line_count + 2))
        self.styles.height = new_height


# ── Message Item ─────────────────────────────────────────────

# ── Agent Messages (scroll container) ────────────────────────


class AgentMessages(VerticalScroll):
    """Scrollable message container.

    In the cache architecture, scrolling is purely local.
    The server independently collects data in the background
    and pushes updates — TUI never triggers IDE scrolling.
    """
    pass


class MessageItem(Static):
    """A single user or assistant message block.

    Supports in-place content updates via update_content() to avoid
    widget destruction/recreation during streaming updates.
    """

    def __init__(self, role, content, thinking=None, actions=None,
                 files_modified=None, msg_index=0, has_undo=False,
                 turn_idx=-1, **kwargs):
        super().__init__(**kwargs)
        self.role = role
        self.msg_content = content
        self.msg_thinking = thinking
        self.msg_actions = actions or []
        self.msg_files = files_modified or []
        self.msg_index = msg_index
        self.has_undo = has_undo
        self._turn_idx = turn_idx
        self._body_widget = None  # Reference for in-place updates

    def compose(self) -> ComposeResult:
        cls = "agent-msg-user" if self.role == "user" else "agent-msg-assistant"
        self.add_class(cls)

        from textual.widgets import Markdown

        if self.role == "user":
            with Horizontal(classes="agent-user-header"):
                yield Static("You", classes="agent-user-label")
                if self.has_undo:
                    yield Button(
                        "↩",
                        id=f"agent-undo-btn-{self.msg_index}",
                        classes="agent-undo-btn",
                    )
            body = Static(rich_escape(self.msg_content), classes="agent-msg-body")
            self._body_widget = body
            yield body
            return

        # Assistant thinking
        if self.msg_thinking:
            short = self.msg_thinking[:200]
            yield Static(f"[dim italic]💭 {rich_escape(short)}[/]", classes="agent-msg-body")

        # Assistant core content using proper Markdown
        if self.msg_content:
            safe_content = self.msg_content.replace("[/", "\\[/").replace("[@", "\\[@")
            body = Markdown(safe_content, classes="agent-msg-body")
            self._body_widget = body
            yield body

        # Assistant actions
        parts = []
        for act in self.msg_actions:
            act_type = act.get("type", "")
            if act_type == "file_edit":
                fname = rich_escape(act.get("file", "?"))
                parts.append(f"  [yellow]📄 Edited {fname}[/]")
            elif act_type == "command":
                detail = rich_escape(act.get("detail", "?"))
                parts.append(f"  [blue]▶ {detail}[/]")

        # Files modified
        if self.msg_files:
            flist = ", ".join(rich_escape(f) for f in self.msg_files[:5])
            parts.append(f"  [dim]Files: {flist}[/]")

        if parts:
            yield Static("\n".join(parts), classes="agent-msg-body")

    def on_button_pressed(self, event: Button.Pressed):
        """Handle button presses originated within this message block."""
        if event.button.has_class("agent-undo-btn"):
            event.stop()
            from agbridge_tui.panels.agent_panel import AgentPanel
            self.post_message(
                AgentPanel.UndoToPromptRequest(
                    message_index=self.msg_index,
                    turn_idx=self._turn_idx,
                    prompt_text=self.msg_content,
                )
            )

    def update_content(self, new_content):
        """Update message content in-place without widget destruction.

        For user messages, updates the Static body text.
        For assistant messages, updates the Markdown body.
        Skips update if content is identical.
        """
        if new_content == self.msg_content:
            return
        self.msg_content = new_content

        if not self._body_widget:
            return

        if self.role == "user":
            self._body_widget.update(rich_escape(new_content))
        else:
            safe = new_content.replace("[/", "\\[/").replace("[@", "\\[@")
            self._body_widget.update(safe)


# ── Agent Panel ──────────────────────────────────────────────

class AgentPanel(Vertical):
    """Full interactive Agent Panel with compose()-based widget tree."""

    # ── Message classes (bubbled to app.py) ───────────────

    class PromptSubmitRequest(Message):
        def __init__(self, content):
            self.content = content
            super().__init__()

    class AcceptAllRequest(Message):
        pass

    class RejectAllRequest(Message):
        pass

    class CancelRequest(Message):
        pass

    class SelectModelRequest(Message):
        def __init__(self, model):
            self.model = model
            super().__init__()

    class SelectModeRequest(Message):
        def __init__(self, mode):
            self.mode = mode
            super().__init__()

    class NewConversationRequest(Message):
        pass

    class RetryRequest(Message):
        pass

    class EditRetryRequest(Message):
        pass

    class DismissErrorRequest(Message):
        pass

    class DenyPermissionRequest(Message):
        pass

    class AllowPermissionRequest(Message):
        pass

    class PermissionMenuRequest(Message):
        pass

    class SelectWorkflowRequest(Message):
        pass

    class SelectMentionRequest(Message):
        pass

    class PastConversationsRequest(Message):
        pass

    class UndoToPromptRequest(Message):
        def __init__(self, message_index, turn_idx, prompt_text):
            self.message_index = message_index
            self.turn_idx = turn_idx
            self.prompt_text = prompt_text
            super().__init__()

    # ── Reactive state ───────────────────────────────────

    agent_state = reactive("unknown")
    conversation_title = reactive("Agent")
    current_model = reactive("")
    current_mode = reactive("")
    workspace_name = reactive("")
    accept_available = reactive(False)
    reject_available = reactive(False)
    error_info = reactive(None)
    _has_data = reactive(True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.border_title = "Agent"
        self._messages_data = []
        self._total_turns = 0
        self._cached_turns = 0
        self.permission_info = None
        self._initial_load = True  # First data → always scroll to bottom

    # ── Compose ──────────────────────────────────────────

    def compose(self) -> ComposeResult:
        # Header
        with Horizontal(classes="agent-header"):
            yield Label("●", id="agent-state-dot", classes="agent-state-dot")
            yield Label(rich_escape(self.conversation_title), id="agent-title", classes="agent-title")
            with Horizontal(classes="agent-header-actions"):
                yield Button("+", id="agent-new-conv-btn", classes="agent-icon-btn")
                yield Button("⏱", id="agent-history-btn", classes="agent-icon-btn")
            with Horizontal(classes="agent-edit-actions"):
                yield Button("✓", id="agent-accept-btn", classes="agent-accept-btn")
                yield Button("✗", id="agent-reject-btn", classes="agent-reject-btn")

        # Conversation messages
        yield AgentMessages(id="agent-messages")

        # Workspace label
        yield Label("", id="agent-ws-label", classes="agent-workspace-label")

        # Input container swaps between Prompt Bar and Error Recovery Hub
        with Vertical(id="agent-input-container"):
            # Normal input bar
            with Horizontal(id="agent-input-bar", classes="agent-input-bar"):
                yield Button("+", id="agent-attachment-btn", classes="agent-attachment-btn")
                yield PromptTextArea(id="agent-input", show_line_numbers=False)
                yield Button("➤", id="agent-send-btn", classes="agent-send-btn")

            # Error recovery hub (hidden by default)
            with Horizontal(id="agent-error-recovery-hub", classes="agent-error-recovery-hub"):
                yield Label("⚠ Agent terminated due to error", classes="agent-error-label")
                yield Button("↻ 동일하게 재시도", id="agent-retry-btn", classes="agent-retry-btn")
                yield Button("✏️ 프롬프트를 수정하여 재시도", id="agent-edit-retry-btn", classes="agent-edit-retry-btn")
                yield Button("✕ 무시", id="agent-dismiss-btn", classes="agent-dismiss-btn")

            # Permission auth hub (hidden by default)
            with Vertical(id="agent-permission-auth-hub", classes="agent-permission-auth-hub"):
                yield Label("🔒 Permission Required", classes="agent-permission-label")
                with Horizontal(classes="agent-permission-buttons"):
                    yield Button("Deny", id="agent-deny-btn", classes="agent-deny-btn")
                    yield Button("Allow", id="agent-allow-btn", classes="agent-allow-btn")
                    yield Button("▲", id="agent-perm-chevron-btn", classes="agent-perm-chevron-btn")

        # Bottom bar — mode / model
        with Horizontal(classes="agent-bottom-bar"):
            yield Button("+ Mode", id="agent-mode-btn", classes="agent-mode-btn")
            yield Button("▽ —", id="agent-model-btn", classes="agent-model-btn")

    # ── Watchers ─────────────────────────────────────────

    def watch_agent_state(self, new_state):
        try:
            dot = self.query_one("#agent-state-dot", Label)
        except Exception:
            return
        state_map = {
            "idle": ("●", "green"),
            "generating": ("◉", "yellow"),
            "error": ("✖", "red"),
            "unknown": ("○", "dim"),
        }
        symbol, color = state_map.get(new_state, ("○", "dim"))
        dot.update(f"[{color}]{symbol}[/]")

        # Toggle Send/Cancel label
        try:
            send_btn = self.query_one("#agent-send-btn", Button)
        except Exception:
            return
        if new_state == "generating":
            send_btn.label = "■"
            send_btn.add_class("agent-cancel-mode")
        else:
            send_btn.label = "➤"
            send_btn.remove_class("agent-cancel-mode")

        # Toggle input bar vs hubs
        try:
            input_bar = self.query_one("#agent-input-bar")
            error_hub = self.query_one("#agent-error-recovery-hub")
            perm_hub = self.query_one("#agent-permission-auth-hub")
        except Exception:
            return

        if new_state == "error":
            input_bar.display = False
            error_hub.display = True
            perm_hub.display = False
        elif new_state == "permission_required":
            input_bar.display = False
            error_hub.display = False
            perm_hub.display = True
            # Update label with permission description
            try:
                perm_label = self.query_one(".agent-permission-label", Label)
                desc = ""
                if self.permission_info:
                    desc = self.permission_info.get("description", "")
                if desc:
                    short = desc[:120] + "\u2026" if len(desc) > 120 else desc
                    perm_label.update(f"\U0001f512 {rich_escape(short)}")
                else:
                    perm_label.update("\U0001f512 Permission Required")
            except Exception:
                pass
        else:
            input_bar.display = True
            error_hub.display = False
            perm_hub.display = False

    def watch_conversation_title(self, new_title):
        try:
            self.query_one("#agent-title", Label).update(rich_escape(new_title or "Agent"))
        except Exception:
            pass

    def watch_accept_available(self, available):
        try:
            btn = self.query_one("#agent-accept-btn", Button)
        except Exception:
            return
        if available:
            btn.add_class("agent-btn-active")
        else:
            btn.remove_class("agent-btn-active")

    def watch_reject_available(self, available):
        try:
            btn = self.query_one("#agent-reject-btn", Button)
        except Exception:
            return
        if available:
            btn.add_class("agent-btn-active")
        else:
            btn.remove_class("agent-btn-active")

    def watch_current_model(self, model):
        try:
            btn = self.query_one("#agent-model-btn", Button)
        except Exception:
            return
        btn.label = f"▽ {model}" if model else "▽ —"

    def watch_current_mode(self, mode):
        try:
            btn = self.query_one("#agent-mode-btn", Button)
        except Exception:
            return
        if mode:
            btn.label = f"[ {mode} ✕ ]"
        else:
            btn.label = "+ Mode"

    def watch_workspace_name(self, name):
        try:
            self.query_one("#agent-ws-label", Label).update(rich_escape(name or ""))
        except Exception:
            pass

    # ── Event handlers ───────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed):
        btn_id = event.button.id

        if btn_id == "agent-attachment-btn":
            from agbridge_tui.modals.select_modal import SelectModal
            def on_selected(action_id):
                if action_id == "Mentions":
                    self.post_message(self.SelectMentionRequest())
                elif action_id == "Workflows":
                    self.post_message(self.SelectWorkflowRequest())
                elif action_id == "Media":
                    pass
            self.app.push_screen(
                SelectModal(title="Add Attachment", items=["Media", "Mentions", "Workflows"]),
                on_selected
            )
            return

        if btn_id == "agent-send-btn":
            if self.agent_state == "generating":
                self.post_message(self.CancelRequest())
            else:
                self._submit_prompt()
            return

        if btn_id == "agent-accept-btn":
            if self.accept_available:
                self.post_message(self.AcceptAllRequest())
            return

        if btn_id == "agent-reject-btn":
            if self.reject_available:
                self.post_message(self.RejectAllRequest())
            return

        if btn_id == "agent-mode-btn":
            # Bubble to app for modal handling
            self.post_message(self.SelectModeRequest(self.current_mode))
            return

        if btn_id == "agent-retry-btn":
            self.post_message(self.RetryRequest())
            return

        if btn_id == "agent-edit-retry-btn":
            self.post_message(self.EditRetryRequest())
            return

        if btn_id == "agent-dismiss-btn":
            self.post_message(self.DismissErrorRequest())
            return

        if btn_id == "agent-deny-btn":
            self.post_message(self.DenyPermissionRequest())
            return

        if btn_id == "agent-allow-btn":
            self.post_message(self.AllowPermissionRequest())
            return

        if btn_id == "agent-perm-chevron-btn":
            self.post_message(self.PermissionMenuRequest())
            return

        if btn_id == "agent-model-btn":
            self.post_message(self.SelectModelRequest(self.current_model))
            return

        if btn_id == "agent-new-conv-btn":
            self.post_message(self.NewConversationRequest())
            return

        if btn_id == "agent-history-btn":
            self.post_message(self.PastConversationsRequest())
            return



    def _submit_prompt(self):
        """Extract text from TextArea, submit, and reset."""
        try:
            ta = self.query_one("#agent-input", TextArea)
        except Exception:
            return
        text = ta.text.strip()
        if not text:
            return
        self.post_message(self.PromptSubmitRequest(text))
        ta.clear()
        ta.styles.height = _MIN_INPUT_HEIGHT

    def on_prompt_text_area_submit_request(self, event: PromptTextArea.SubmitRequest):
        """Handle Enter key in TextArea → submit prompt."""
        event.stop()
        self._submit_prompt()

    def on_prompt_text_area_trigger_detected(self, event: PromptTextArea.TriggerDetected):
        """Handle '/' or '@' trigger for typeahead."""
        event.stop()
        if event.trigger == "/":
            self.post_message(self.SelectWorkflowRequest())
        elif event.trigger == "@":
            self.post_message(self.SelectMentionRequest())

    # ── Data update methods (server event handlers) ──────

    def apply_data(self, data):
        """Apply workspace data or None (empty state)."""
        if data is None:
            self._has_data = False
            self.agent_state = "unknown"
            self.conversation_title = "Agent"
            self.current_model = ""
            self.current_mode = ""
            self.workspace_name = ""
            self.accept_available = False
            self.reject_available = False
            self._messages_data = []
            self._rebuild_messages()
            return

        self._has_data = True

    def set_scan_loading(self, scanning):
        """Show/hide loading indicator during background conversation scan."""
        try:
            scroll = self.query_one("#agent-messages", AgentMessages)
        except Exception:
            return

        if scanning:
            self._initial_load = True  # Next data arrival scrolls to bottom
            scroll.loading = True
            scroll.remove_children()
            scroll.mount(Static(
                "\n  [dim]Loading conversation...[/]",
                classes="agent-empty-state",
            ))
        else:
            scroll.loading = False

    def update_from_agent(self, data):
        """Update from UI_AGENT_UPDATE event."""
        if not data:
            return
        self._has_data = True

        # Permission info — set BEFORE agent_state so watcher can read it
        self.permission_info = data.get("permission_info")

        self.agent_state = data.get("state", "unknown")
        self.conversation_title = data.get("conversation_title", "") or "Agent"

        # Model/mode from agent panel data
        model = data.get("current_model", "")
        mode = data.get("current_mode", "")
        if model:
            self.current_model = model
        if mode:
            self.current_mode = mode

        # Error info
        self.error_info = data.get("error_info")

        # Structured messages
        messages = data.get("messages")
        self._total_turns = data.get("_total_turns", 0)
        self._cached_turns = data.get("_cached_turns", 0)
        if messages is not None:
            self._messages_data = messages
            self._rebuild_messages()

    def update_from_edit_actions(self, data):
        """Update from UI_EDIT_ACTIONS_UPDATE event."""
        if not data:
            return
        self._has_data = True
        self.accept_available = data.get("accept_all_available", False)
        self.reject_available = data.get("reject_all_available", False)

    def update_from_editor(self, data):
        """Update from UI_ACTIVE_EDITOR_UPDATE event."""
        if not data:
            return
        self._has_data = True
        ws_name = data.get("workspace", "")
        self.workspace_name = ws_name

    def update_from_models(self, data):
        """Update from UI_MODELS_UPDATE event."""
        if not data:
            return
        self._has_data = True
        self.current_model = data.get("current_model", "")
        self.current_mode = data.get("current_mode", "")

    # ── Message list management ──────────────────────────

    @staticmethod
    def _msg_identity(msg):
        """Return identity key for a message dict.

        Used to determine if two messages represent the same turn.
        """
        return (msg.get("role", "assistant"), msg.get("_turn_idx", -1))

    def _make_message_widget(self, msg, user_idx=0):
        """Create a MessageItem widget from message data."""
        role = msg.get("role", "assistant")
        is_user = role == "user"
        return MessageItem(
            role=role,
            content=msg.get("content", ""),
            thinking=msg.get("thinking"),
            actions=msg.get("actions", []),
            files_modified=msg.get("files_modified", []),
            msg_index=user_idx if is_user else 0,
            has_undo=is_user,
            turn_idx=msg.get("_turn_idx", -1),
        )

    def _rebuild_messages(self):
        """Incremental message list update.

        Three strategies to avoid full widget teardown:
          1. Update-in-place: same structure, only last content differs
             → MessageItem.update_content() on the last widget
          2. Append: new messages added at the end
             → mount() only the new widgets
          3. Full rebuild: structural change (conversation switch, undo)
             → remove_children() + mount() all, wrapped in batch_update()
        """
        try:
            scroll = self.query_one("#agent-messages", AgentMessages)
        except Exception:
            return

        # Empty state
        if not self._messages_data:
            scroll.remove_children()
            scroll.mount(Static(
                "\n  [dim]No conversation yet.[/]\n"
                "  Type a message below to start.",
                classes="agent-empty-state",
            ))
            return

        was_at_bottom = scroll.max_scroll_y <= 0 or scroll.scroll_y >= scroll.max_scroll_y - 2

        # Collect existing MessageItem widgets
        existing = list(scroll.query(MessageItem))
        new_data = self._messages_data

        # Determine update strategy
        can_incremental = len(existing) > 0 and len(new_data) >= len(existing)

        if can_incremental:
            # Check identity match for all existing messages
            for i, widget in enumerate(existing):
                expected = self._msg_identity(new_data[i])
                actual = (widget.role, widget._turn_idx)
                if expected != actual:
                    can_incremental = False
                    break

        if can_incremental:
            # Update-in-place: refresh the last existing message if content changed
            last_idx = len(existing) - 1
            last_widget = existing[last_idx]
            last_data = new_data[last_idx]
            new_content = last_data.get("content", "")
            if new_content != last_widget.msg_content:
                last_widget.update_content(new_content)

            # Append: mount any new messages beyond existing count
            if len(new_data) > len(existing):
                user_idx = sum(1 for w in existing if w.role == "user")
                for msg in new_data[len(existing):]:
                    widget = self._make_message_widget(msg, user_idx)
                    scroll.mount(widget)
                    if msg.get("role") == "user":
                        user_idx += 1

            if was_at_bottom:
                self.call_after_refresh(self._scroll_to_bottom)
            return

        # Full rebuild: structural change (conversation switch, undo, etc.)
        with self.app.batch_update():
            scroll.remove_children()
            user_idx = 0
            for msg in new_data:
                widget = self._make_message_widget(msg, user_idx)
                scroll.mount(widget)
                if msg.get("role") == "user":
                    user_idx += 1

        if self._initial_load:
            self._initial_load = False
            self.call_after_refresh(self._scroll_to_bottom)
        elif was_at_bottom:
            self.call_after_refresh(self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        try:
            scroll = self.query_one("#agent-messages", AgentMessages)
            scroll.scroll_end(animate=False)
        except Exception:
            pass
