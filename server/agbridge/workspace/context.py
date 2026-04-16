"""
agbridge.workspace.context — Unified workspace state object

The single source of truth for a workspace's communication state.
Replaces 6 scattered state stores (Engine._state, Engine.store,
Engine._turn_cache, Engine.cdp, InputQueue._last_prompt_cache,
InputQueue._undo_prompt_cache) with one cohesive object.

Engine owns a WorkspaceContext and delegates all state queries to it.
ActionHandlers receive ctx (WorkspaceContext) and operate on it directly.
"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("agbridge.workspace.context")


@dataclass
class PromptHistory:
    """Tracks sent prompts and pending undo state.

    Replaces InputQueue._last_prompt_cache and _undo_prompt_cache.
    """

    last_sent: str = ""
    pending_undo: dict = field(default_factory=lambda: None)

    def record_sent(self, text):
        """Record a successfully sent prompt."""
        self.last_sent = text


class WorkspaceContext:
    """Unified per-workspace state object.

    Owns or references every component needed for workspace interaction.
    """

    def __init__(
        self,
        workspace_id,
        workspace_root,
        state_machine,
        store,
        conversation,
        cdp,
        ide,
    ):
        """
        Args:
            workspace_id: Unique workspace identifier.
            workspace_root: Absolute path to workspace directory.
            state_machine: WorkspaceStateMachine instance.
            store: StateStore instance.
            conversation: ConversationCache instance.
            cdp: CDPBridge instance.
            ide: IDEMonitor instance.
        """
        self.workspace_id = workspace_id
        self.workspace_root = workspace_root
        self.state_machine = state_machine
        self.store = store
        self.conversation = conversation
        self.cdp = cdp
        self.ide = ide
        self.prompt_history = PromptHistory()
        self._push_event_callback = None

        # EditorGateway is set after construction (circular dep resolution)
        self._editor = None

    def set_push_event(self, callback):
        """Set the push_event callback — bridges ctx to Engine.push_event.

        Args:
            callback: def callback(event_type, payload=None)
        """
        self._push_event_callback = callback

    def push_event(self, event_type, payload=None):
        """Emit a TUI event through the Engine's event queue.

        If no callback is set, the event is silently dropped.
        """
        if self._push_event_callback:
            self._push_event_callback(event_type, payload)

    @property
    def editor(self):
        """EditorGateway instance.

        Set via set_editor() after construction.
        """
        if self._editor is None:
            raise RuntimeError(
                "EditorGateway not initialized — call set_editor() first"
            )
        return self._editor

    def set_editor(self, editor):
        """Set the EditorGateway instance.

        Called after WorkspaceContext and EditorGateway are both created.
        """
        self._editor = editor

    @property
    def is_ready(self):
        """Whether the workspace is ready for operations."""
        return (
            self.cdp is not None
            and self.cdp.is_connected
            and not self.state_machine.is_error()
        )

    @property
    def can_inject(self):
        """Whether a prompt can be injected."""
        return (
            self.state_machine.can_inject()
            and self.cdp is not None
            and self.cdp.is_connected
        )
