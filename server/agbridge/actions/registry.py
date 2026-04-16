"""
agbridge.actions.registry — Action dispatch system

Replaces InputQueue's 250-line if-else chain with a registry
of ActionHandler implementations. Each handler is a focused,
testable unit that receives a WorkspaceContext and params dict.
"""

import logging
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

logger = logging.getLogger("agbridge.actions.registry")


@dataclass
class ActionResult:
    """Standardized result from any action handler."""

    ok: bool
    data: dict = field(default_factory=dict)
    error: str = ""

    @classmethod
    def success(cls, **data):
        return cls(ok=True, data=data)

    @classmethod
    def fail(cls, error, **data):
        return cls(ok=False, error=error, data=data)

    def to_dict(self):
        """Convert to wire-format dict for API responses."""
        result = {"ok": self.ok}
        if self.error:
            result["error"] = self.error
        result.update(self.data)
        return result


@runtime_checkable
class ActionHandler(Protocol):
    """Protocol for action handlers."""

    async def execute(self, ctx, params: dict) -> ActionResult:
        """Execute the action.

        Args:
            ctx: WorkspaceContext instance.
            params: Action parameters from the client.

        Returns:
            ActionResult
        """
        ...


class ActionRegistry:
    """Maps action names to handlers and dispatches execution.

    Usage:
        registry = ActionRegistry()
        registry.register("inject_prompt", InjectPromptAction())
        result = await registry.dispatch("inject_prompt", ctx, params)
    """

    def __init__(self):
        self._handlers = {}

    def register(self, action_name, handler):
        """Register an action handler.

        Args:
            action_name: String key (e.g. "inject_prompt").
            handler: Object implementing ActionHandler protocol.
        """
        if not isinstance(handler, ActionHandler):
            raise TypeError(
                f"Handler for '{action_name}' does not implement ActionHandler"
            )
        self._handlers[action_name] = handler
        logger.debug("Action registered: %s", action_name)

    def register_many(self, mapping):
        """Register multiple handlers from a dict.

        Args:
            mapping: {action_name: handler} dict.
        """
        for name, handler in mapping.items():
            self.register(name, handler)

    async def dispatch(self, action_name, ctx, params):
        """Dispatch an action to its registered handler.

        Args:
            action_name: Action to execute.
            ctx: WorkspaceContext instance.
            params: Action parameters.

        Returns:
            ActionResult
        """
        handler = self._handlers.get(action_name)
        if not handler:
            return ActionResult.fail(f"unknown action: {action_name}")
        return await handler.execute(ctx, params)

    def has(self, action_name):
        """Check if an action is registered."""
        return action_name in self._handlers

    @property
    def registered_actions(self):
        """Return list of registered action names."""
        return list(self._handlers.keys())


def build_default_registry():
    """Build and return an ActionRegistry with all standard handlers.

    Called during server startup.
    """
    from agbridge.actions.prompt import (
        InjectPromptAction,
        UndoToPromptAction,
        ConfirmUndoAction,
        CancelUndoAction,
    )
    from agbridge.actions.conversation import (
        NewConversationAction,
        ListConversationsAction,
        SelectConversationAction,
        DeleteConversationAction,
        ExpandConversationsAction,
        CloseConversationPanelAction,
        ScrollConversationAction,
        ClearCacheAction,
    )
    from agbridge.actions.controls import (
        AcceptAllAction,
        RejectAllAction,
        CancelAction,
        RetryAction,
        DismissErrorAction,
    )
    from agbridge.actions.permission import (
        AllowAction,
        DenyAction,
        AllowWorkspaceAction,
        AllowGloballyAction,
        RunSandboxAction,
    )
    from agbridge.actions.model import (
        SelectModelAction,
        SelectModeAction,
        ListModelsAction,
        ListModesAction,
        RefreshModelsAction,
    )

    registry = ActionRegistry()
    registry.register_many({
        # Prompt
        "inject_prompt":            InjectPromptAction(),
        "undo_to_prompt":           UndoToPromptAction(),
        "confirm_undo":             ConfirmUndoAction(),
        "cancel_undo":              CancelUndoAction(),

        # Conversation
        "new_conversation":         NewConversationAction(),
        "list_conversations":       ListConversationsAction(),
        "select_conversation":      SelectConversationAction(),
        "delete_conversation":      DeleteConversationAction(),
        "expand_conversations":     ExpandConversationsAction(),
        "close_conversation_panel": CloseConversationPanelAction(),
        "scroll_conversation":      ScrollConversationAction(),
        "clear_cache":              ClearCacheAction(),

        # Controls
        "accept_all":               AcceptAllAction(),
        "reject_all":               RejectAllAction(),
        "cancel":                   CancelAction(),
        "retry":                    RetryAction(),
        "dismiss_error":            DismissErrorAction(),

        # Permission
        "press_allow":              AllowAction(),
        "press_deny":               DenyAction(),
        "press_allow_workspace":    AllowWorkspaceAction(),
        "press_allow_globally":     AllowGloballyAction(),
        "press_run_sandbox":        RunSandboxAction(),

        # Model / Mode
        "select_model":             SelectModelAction(),
        "select_mode":              SelectModeAction(),
        "list_models":              ListModelsAction(),
        "list_modes":               ListModesAction(),
        "refresh_models":           RefreshModelsAction(),
    })

    logger.info(
        "ActionRegistry built: %d actions", len(registry.registered_actions),
    )
    return registry
