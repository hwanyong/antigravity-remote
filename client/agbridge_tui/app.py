"""
agbridge_tui.app — Main Textual application (multi-workspace)

Layout: Mobile-only, single panel at a time.
  NavBar at bottom to switch between WorkspaceList / AgentPanel / Explorer.
  4-tier layer system: Main Screen → Modal → Alert → System Alert.
"""

import argparse
import asyncio
import logging
import os
import sys
import time

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import Footer, Header, TextArea
from rich.markup import escape as rich_escape

from agbridge_tui.connection import Connection
from agbridge_tui.workspace_manager import WorkspaceManager

from agbridge_tui.panels.event_log import EventLogBuffer, EventLogModal
from agbridge_tui.panels.agent_panel import AgentPanel
from agbridge_tui.panels.explorer import Explorer
from agbridge_tui.panels.git_panel import GitPanel
from agbridge_tui.panels.workspace_list import WorkspaceList
from agbridge_tui.panels.nav_bar import NavBar
from agbridge_tui.panels.file_menu import (
    MenuScreen,
    FILE_MENU_ITEMS,
    VIEW_MENU_ITEMS,
    AGENT_MENU_ITEMS,
    GIT_MENU_ITEMS,
)
from agbridge_tui.panels.settings_panel import SettingsPanel
from agbridge_tui.modals.input_modal import InputModal
from agbridge_tui.modals.text_viewer import TextViewerModal
from agbridge_tui.modals.confirm_modal import ConfirmModal
from agbridge_tui.modals.file_explorer_modal import FileExplorerModal
from agbridge_tui.modals.select_modal import SelectModal

logger = logging.getLogger("agbridge_tui")


class AgbridgeTUI(App):
    """Antigravity Remote Bridge — TUI Client (multi-workspace)."""

    TITLE = "agbridge TUI"
    CSS_PATH = "styles.tcss"

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=False),
        Binding("ctrl+r", "refresh_snapshot", "Refresh", show=False),
        Binding("ctrl+w", "switch_panel_workspace", "Workspaces", show=False, priority=True),
        Binding("ctrl+a", "switch_panel_agent", "Agent", show=False, priority=True),
        Binding("ctrl+e", "switch_panel_explorer", "Files", show=False, priority=True),
        Binding("ctrl+g", "switch_panel_git", "Git", show=False, priority=True),
        Binding("f1", "open_file_menu", "File"),
        Binding("f2", "open_view_menu", "View"),
        Binding("f3", "open_agent_menu", "Agent"),
        Binding("f4", "open_git_menu", "Git"),
        Binding("f10", "open_settings", "Settings"),
    ]

    active_panel = reactive("workspace")

    def __init__(self, conn, **kwargs):
        super().__init__(**kwargs)
        self.conn = conn
        self.ws_mgr = WorkspaceManager(conn)
        self._fs_debounce_handle = None
        self._has_pending_edits = False
        self._cmd_results = []
        self._event_log = EventLogBuffer()
        self._pending_select = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield WorkspaceList(id="workspace-list")
        yield AgentPanel(id="agent-panel")
        yield Explorer(id="explorer-panel")
        yield GitPanel(id="git-panel")
        yield NavBar()
        yield Footer(show_command_palette=False)

    # ── Panel switching ──────────────────────────────────

    def watch_active_panel(self, panel_name: str):
        """Show only the active panel, hide the rest."""
        panels = {
            "workspace": "#workspace-list",
            "agent": "#agent-panel",
            "explorer": "#explorer-panel",
            "git": "#git-panel",
        }
        for name, selector in panels.items():
            try:
                self.query_one(selector).display = (name == panel_name)
            except Exception:
                pass
        try:
            self.query_one(NavBar).active = panel_name
        except Exception:
            pass

    def on_nav_bar_panel_switch(self, event: NavBar.PanelSwitch):
        """Handle NavBar button clicks."""
        self._dismiss_modals()
        self.active_panel = event.panel

    def _dismiss_modals(self):
        """Dismiss active modal screens when switching panels or pushing new ones."""
        while len(self.screen_stack) > 1:
            try:
                self.pop_screen()
            except Exception:
                break

    def action_switch_panel_workspace(self):
        """Ctrl+1: Switch to Workspaces panel."""
        self._dismiss_modals()
        self.active_panel = "workspace"

    def action_switch_panel_agent(self):
        """Ctrl+2: Switch to Agent panel."""
        self._dismiss_modals()
        self.active_panel = "agent"

    def action_switch_panel_explorer(self):
        """Ctrl+E: Switch to Explorer panel."""
        self._dismiss_modals()
        self.active_panel = "explorer"

    def action_switch_panel_git(self):
        """Ctrl+G: Switch to Git panel."""
        self._dismiss_modals()
        self.active_panel = "git"

    async def on_mount(self):
        """Initialize connection and start WS listener."""
        ws_list = self.query_one("#workspace-list", WorkspaceList)

        # Wire workspace list switch callback
        ws_list.set_switch_callback(self.ws_mgr.switch)

        # Register as observer for workspace events
        self.ws_mgr.add_observer(self._on_workspace_event)

        # Set up WS event handler → routes through WorkspaceManager
        self.conn.set_event_handler(self.ws_mgr.on_ws_event)
        self.conn.set_state_change_handler(self._on_conn_state_change)

        # Initial workspace list fetch — fail gracefully
        workspaces = []
        try:
            workspaces = await self.ws_mgr.refresh_list()
            if workspaces:
                first_id = workspaces[0]["workspace_id"]
                await self.ws_mgr.switch(first_id)
        except Exception:
            pass  # daemon not running — normal on first start

        # Apply initial data (None when no workspaces)
        self._apply_data(self.ws_mgr.active_data)
        self._update_workspace_list()
        self._update_title()

        # Start WS connection in background
        self.run_worker(self.conn.ws_connect())

    # ── Result tracking ──────────────────────────────────────

    def _add_result(self, cmd_type, result):
        """Track command result internally (visible in Settings panel)."""
        ts_str = time.strftime("%H:%M:%S")
        ok = result.get("ok", False) if isinstance(result, dict) else False
        error = result.get("error", "") if isinstance(result, dict) else ""

        entry = f"{'✅' if ok else '❌'} [dim]{ts_str}[/] [cyan]{cmd_type}[/]"
        if not ok and error:
            entry += f" [red]{rich_escape(error)}[/]"

        self._cmd_results.append(entry)
        if len(self._cmd_results) > 20:
            self._cmd_results = self._cmd_results[-10:]

    # ── Observer callback ────────────────────────────────────

    async def _on_workspace_event(self, event_type, data, ts, workspace_id):
        """
        Observe workspace events from WorkspaceManager.
        Only update UI for active workspace events or system events.
        """
        agent = self.query_one("#agent-panel", AgentPanel)

        # Always log all events to buffer
        log_data = data.copy() if data else {}
        if workspace_id:
            log_data["_ws"] = workspace_id
        self._event_log.log_event(event_type, log_data, ts or time.time())

        # System-level events — update workspace list + active data
        if event_type in ("SYS_WORKSPACE_REGISTERED", "SYS_WORKSPACE_UNREGISTERED", "WORKSPACE_SWITCHED"):
            self._update_workspace_list()
            self._apply_data(self.ws_mgr.active_data)
            self._update_title()
            return

        # Per-workspace events — only update if active
        if workspace_id != self.ws_mgr.active_id:
            return

        if event_type == "SYS_IDE_CONNECTED":
            pass

        elif event_type == "SYS_IDE_DISCONNECTED":
            pass

        elif event_type.startswith("FS_OP_"):
            await self._refresh_snapshot_debounced()

        elif event_type == "GIT_STATUS_UPDATE":
            explorer = self.query_one("#explorer-panel", Explorer)
            explorer.update_git(data)
            try:
                git_panel = self.query_one("#git-panel", GitPanel)
                git_panel.update_git(data)
            except Exception:
                pass

        elif event_type == "UI_AGENT_UPDATE":
            agent.update_from_agent(data)
            new_state = data.get("state", "") if data else ""
            if new_state == "generating":
                pass
            elif new_state == "idle":
                pass

        elif event_type == "UI_EDIT_ACTIONS_UPDATE":
            agent.update_from_edit_actions(data)
            self._has_pending_edits = data.get("has_pending_edits", False) if data else False

        elif event_type == "UI_CONFIRM_UNDO_DIALOG":
            self._handle_confirm_undo_dialog(data, workspace_id)

        elif event_type == "UI_ACTIVE_EDITOR_UPDATE":
            agent.update_from_editor(data)

        elif event_type == "UI_MODELS_UPDATE":
            agent.update_from_models(data)

        elif event_type.endswith("_RESULT"):
            self._event_log.log_result(event_type.replace("_RESULT", ""), data)
            self._add_result(event_type.replace("_RESULT", ""), data)

            if event_type == "CMD_FILE_READ_RESULT" and data and data.get("ok"):
                self.push_screen(TextViewerModal(
                    title="File Content",
                    content=data.get("content", ""),
                ))

            if event_type == "CMD_UNDO_TO_PROMPT_RESULT":
                if data and data.get("ok"):
                    dialog = data.get("dialog")
                    if dialog:
                        self._handle_confirm_undo_dialog(dialog, workspace_id)

            if event_type == "CMD_CONFIRM_UNDO_RESULT":
                self._event_log.log_event("DEBUG_UNDO", {
                    "ok": data.get("ok") if data else None,
                    "has_agent_update": "agent_update" in data if data else False,
                    "restored_prompt": repr((data.get("restored_prompt", "") or "")[:80]) if data else "N/A",
                })
                if data and data.get("ok"):
                    agent_update = data.get("agent_update")
                    if agent_update:
                        agent = self.query_one("#agent-panel", AgentPanel)
                        agent.update_from_agent(agent_update)
                        self._event_log.log_event("DEBUG_UNDO", {
                            "step": "update_from_agent done",
                            "msg_count": len(agent_update.get("messages", [])),
                        })
                    # Restore prompt to TUI input
                    restored = data.get("restored_prompt", "")
                    if restored:
                        self._set_agent_input_text(restored)

            if event_type == "CMD_GIT_OP_RESULT" and data:
                stdout = data.get("stdout", "")
                if stdout and len(stdout) > 100:
                    self.push_screen(TextViewerModal(
                        title="Git Output",
                        content=stdout,
                    ))

            if event_type == "CMD_LIST_MODELS_RESULT":
                self._handle_list_result(data, "model", "models")

            if event_type == "CMD_LIST_MODES_RESULT":
                self._handle_list_result(data, "mode", "modes")
                
            if event_type == "CMD_LIST_WORKFLOWS_RESULT":
                pending = self._pending_select
                if pending and pending["type"] == "workflow":
                    self._pending_select = None
                    if data and data.get("ok"):
                        wfs = data.get("workflows", [])
                        def on_selected(selected_name):
                            if selected_name:
                                self._inject_into_agent_input(f"@[/{selected_name}]", replace_char="/")
                        self.push_screen(
                            SelectModal(
                                title="Select Workflow",
                                items=wfs,
                            ),
                            on_selected,
                        )

            if event_type == "CMD_LIST_CONVERSATIONS_RESULT":
                pending = self._pending_select
                if pending and pending["type"] == "conversation":
                    ws_id = pending["ws_id"]
                    self._pending_select = None
                    if data and data.get("ok"):
                        convs = data.get("conversations", [])
                        def on_conv_selected(selected_title):
                            if selected_title:
                                self.run_worker(self.conn.ws_send_command(
                                    ws_id, "CMD_SELECT_CONVERSATION",
                                    {"title": selected_title},
                                ))
                        self.push_screen(
                            SelectModal(
                                title="Past Conversations",
                                items=convs,
                            ),
                            on_conv_selected,
                        )

    async def _on_conn_state_change(self, state):
        """Handle connection state changes."""
        self.sub_title = state.upper()

        if state == "connected":
            try:
                await self.ws_mgr.refresh_list()
                self._update_workspace_list()
                self._apply_data(self.ws_mgr.active_data)
            except Exception:
                pass

    # ── Data-driven UI update ────────────────────────────────

    def _apply_data(self, data):
        """
        Apply workspace data (or None for empty state) to all panels.
        """
        agent = self.query_one("#agent-panel", AgentPanel)
        explorer = self.query_one("#explorer-panel", Explorer)

        if data is None:
            agent.apply_data(None)
            explorer.apply_data(None)
            try:
                self.query_one("#git-panel", GitPanel).update_git(None)
            except Exception:
                pass
            self._has_pending_edits = False
            return

        explorer.update_from_snapshot(data)
        try:
            self.query_one("#git-panel", GitPanel).update_git(data.get("git_status", {}))
        except Exception:
            pass

        agent_data = data.get("agent_panel", {})
        if agent_data:
            agent.update_from_agent(agent_data)

        edit_data = data.get("edit_actions", {})
        if edit_data:
            agent.update_from_edit_actions(edit_data)
            self._has_pending_edits = edit_data.get("has_pending_edits", False)

        editor_data = data.get("active_editor", {})
        if editor_data:
            agent.update_from_editor(editor_data)

        models_data = data.get("models_info", {})
        if models_data:
            agent.update_from_models(models_data)

    def _update_workspace_list(self):
        """Update the WorkspaceList panel from WorkspaceManager."""
        ws_list = self.query_one("#workspace-list", WorkspaceList)
        ws_list.apply_data(self.ws_mgr.workspace_list, self.ws_mgr.active_id)

    def _update_title(self):
        """Update app title from active workspace."""
        meta = self.ws_mgr.active_metadata
        if meta:
            self.title = os.path.basename(meta.get("path", ""))
            self.sub_title = meta.get("path", "")
        else:
            self.title = "agbridge TUI"
            self.sub_title = "No workspace"

    async def _refresh_snapshot_debounced(self):
        """Refresh snapshot with 500ms debounce."""
        if self._fs_debounce_handle:
            self._fs_debounce_handle.cancel()

        async def _do_refresh():
            await asyncio.sleep(0.5)
            ws_id = self.ws_mgr.active_id
            if not ws_id:
                return
            try:
                snapshot = await self.conn.get_snapshot(ws_id)
                self.ws_mgr._cache[ws_id] = snapshot
                self._apply_data(snapshot)
            except Exception:
                pass

        self._fs_debounce_handle = asyncio.create_task(_do_refresh())

    # ── Menu actions ─────────────────────────────────────────

    def action_open_file_menu(self):
        """F1: Open the File dropdown menu."""
        self._dismiss_modals()
        self.push_screen(MenuScreen(FILE_MENU_ITEMS, x_offset=0), self._on_menu_result)

    def action_open_view_menu(self):
        """F2: Open the View dropdown menu."""
        self._dismiss_modals()
        self.push_screen(MenuScreen(VIEW_MENU_ITEMS, x_offset=8), self._on_menu_result)

    def action_open_agent_menu(self):
        """F3: Open the Agent dropdown menu."""
        self._dismiss_modals()
        self.push_screen(MenuScreen(AGENT_MENU_ITEMS, x_offset=17), self._on_menu_result)

    def action_open_git_menu(self):
        """F4: Open the Git dropdown menu."""
        self._dismiss_modals()
        self.push_screen(MenuScreen(GIT_MENU_ITEMS, x_offset=27), self._on_menu_result)

    def _on_menu_result(self, action_id):
        """Callback from MenuScreen — dispatch selected action."""
        if not action_id:
            return
        handler = getattr(self, f"action_{action_id}", None)
        if handler:
            self.run_worker(handler())

    async def action_toggle_event_log(self):
        """Open EventLog as a popup modal."""
        self.push_screen(EventLogModal(self._event_log.entries))

    async def action_open_settings(self):
        """F10: Open settings & diagnostics panel."""
        self._dismiss_modals()
        conn_info = {
            "host": self.conn.host,
            "port": self.conn.port,
            "state": "connected" if self.conn.is_ws_connected else "disconnected",
        }
        workspace_info = self.ws_mgr.active_metadata
        self.push_screen(SettingsPanel(conn_info, workspace_info, self._cmd_results))

    # ── Key actions ──────────────────────────────────────────

    async def action_refresh_snapshot(self):
        ws_id = self.ws_mgr.active_id
        if not ws_id:
            return
        try:
            snapshot = await self.conn.get_snapshot(ws_id)
            self.ws_mgr._cache[ws_id] = snapshot
            self._apply_data(snapshot)
        except Exception as e:
            self._event_log.log_event(
                "ERROR", {"msg": str(e)}, time.time()
            )

    async def action_cmd_status(self):
        """GET workspace status."""
        ws_id = self.ws_mgr.active_id
        if not ws_id:
            return
        try:
            status = await self.conn.get_status(ws_id)
            self._add_result("GET status", {"ok": True, **status})
        except Exception as e:
            self._add_result("GET status", {"ok": False, "error": str(e)})

    async def action_cmd_snapshot(self):
        """GET workspace snapshot."""
        ws_id = self.ws_mgr.active_id
        if not ws_id:
            return
        try:
            snapshot = await self.conn.get_snapshot(ws_id)
            self.ws_mgr._cache[ws_id] = snapshot
            self._apply_data(snapshot)
            self._add_result("GET snapshot", {"ok": True})
        except Exception as e:
            self._add_result("GET snapshot", {"ok": False, "error": str(e)})



    async def action_cmd_file_read(self):
        """CMD_FILE_READ via WS."""
        ws_id = self.ws_mgr.active_id
        if not ws_id:
            return

        def on_result(values):
            if values and values.get("path"):
                self.run_worker(self.conn.ws_send_command(
                    ws_id, "CMD_FILE_READ", {"path": values["path"]}
                ))

        self.push_screen(
            InputModal(
                title="Read File",
                fields=[{"name": "path", "label": "File path (relative):", "placeholder": "src/main.py"}],
            ),
            on_result,
        )

    async def action_cmd_accept_all(self):
        """CMD_ACCEPT_ALL via WS."""
        ws_id = self.ws_mgr.active_id
        if not ws_id:
            return
        if not self._has_pending_edits:
            self._add_result("CMD_ACCEPT_ALL", {"ok": False, "error": "No pending edits"})
            return
        await self.conn.ws_send_command(ws_id, "CMD_ACCEPT_ALL")

    async def action_cmd_reject_all(self):
        """CMD_REJECT_ALL via WS."""
        ws_id = self.ws_mgr.active_id
        if not ws_id:
            return
        if not self._has_pending_edits:
            self._add_result("CMD_REJECT_ALL", {"ok": False, "error": "No pending edits"})
            return
        await self.conn.ws_send_command(ws_id, "CMD_REJECT_ALL")

    async def action_cmd_cancel_generation(self):
        """CMD_CANCEL via WS (menu triggered)."""
        ws_id = self.ws_mgr.active_id
        if not ws_id:
            return
        await self.conn.ws_send_command(ws_id, "CMD_CANCEL")

    async def action_cmd_new_conversation(self):
        """CMD_NEW_CONVERSATION via WS (menu triggered)."""
        ws_id = self.ws_mgr.active_id
        if not ws_id:
            return
        await self.conn.ws_send_command(ws_id, "CMD_NEW_CONVERSATION")

    async def action_cmd_retry(self):
        """CMD_RETRY via WS (menu triggered)."""
        ws_id = self.ws_mgr.active_id
        if not ws_id:
            return
        await self.conn.ws_send_command(ws_id, "CMD_RETRY")

    async def action_cmd_dismiss_error(self):
        """CMD_DISMISS_ERROR via WS (menu triggered)."""
        ws_id = self.ws_mgr.active_id
        if not ws_id:
            return
        await self.conn.ws_send_command(ws_id, "CMD_DISMISS_ERROR")

    async def action_cmd_refresh_models(self):
        """CMD_REFRESH_MODELS via WS — force re-scrape available models/modes."""
        ws_id = self.ws_mgr.active_id
        if not ws_id:
            return
        await self.conn.ws_send_command(ws_id, "CMD_REFRESH_MODELS")

    async def action_cmd_git_status(self):
        """CMD_GIT_OP status via WS."""
        ws_id = self.ws_mgr.active_id
        if not ws_id:
            return
        await self.conn.ws_send_command(ws_id, "CMD_GIT_OP", {"action": "status"})

    async def action_cmd_git_commit(self):
        """CMD_GIT_OP commit via WS (menu triggered)."""
        ws_id = self.ws_mgr.active_id
        if not ws_id:
            return

        def on_result(values):
            if values and values.get("message"):
                self.run_worker(self.conn.ws_send_command(
                    ws_id, "CMD_GIT_OP",
                    {"action": "commit", "args": ["-m", values["message"]]},
                ))

        self.push_screen(
            InputModal(
                title="Git Commit",
                fields=[{"name": "message", "label": "Commit message:", "placeholder": "feat: ..."}],
            ),
            on_result,
        )

    # ── AgentPanel Event Handlers ─────────────────────────────

    def on_agent_panel_prompt_submit_request(self, event: AgentPanel.PromptSubmitRequest):
        event.stop()
        ws_id = self.ws_mgr.active_id
        if not ws_id:
            return
        self.run_worker(self.conn.ws_send_command(
            ws_id, "CMD_INJECT_PROMPT", {"content": event.content},
        ))

    def on_agent_panel_accept_all_request(self, event: AgentPanel.AcceptAllRequest):
        event.stop()
        self.run_worker(self.action_cmd_accept_all())

    def on_agent_panel_reject_all_request(self, event: AgentPanel.RejectAllRequest):
        event.stop()
        self.run_worker(self.action_cmd_reject_all())

    def on_agent_panel_cancel_request(self, event: AgentPanel.CancelRequest):
        event.stop()
        ws_id = self.ws_mgr.active_id
        if not ws_id:
            return
        self.run_worker(self.conn.ws_send_command(ws_id, "CMD_CANCEL"))

    def on_agent_panel_new_conversation_request(self, event: AgentPanel.NewConversationRequest):
        event.stop()
        ws_id = self.ws_mgr.active_id
        if not ws_id:
            return
        self.run_worker(self.conn.ws_send_command(ws_id, "CMD_NEW_CONVERSATION"))

    def on_agent_panel_retry_request(self, event: AgentPanel.RetryRequest):
        event.stop()
        ws_id = self.ws_mgr.active_id
        if not ws_id:
            return
        self.run_worker(self.conn.ws_send_command(ws_id, "CMD_RETRY"))

    def on_agent_panel_edit_retry_request(self, event: AgentPanel.EditRetryRequest):
        event.stop()
        ws_id = self.ws_mgr.active_id
        if not ws_id:
            return
            
        try:
            from textual.widgets import TextArea
            panel = self.query_one("AgentPanel")
            
            # 1. Force UI swap back to input bar
            try:
                input_bar = panel.query_one("#agent-input-bar")
                error_hub = panel.query_one("#agent-error-recovery-hub")
                input_bar.display = True
                error_hub.display = False
            except Exception:
                pass

            # 2. Focus the TextArea
            ta = panel.query_one("#agent-input", TextArea)
            ta.focus()
            
            # 3. Restore last sent prompt from server cache
            self.run_worker(self._fetch_last_prompt(ws_id, ta))
            
        except Exception:
            pass

    async def _fetch_last_prompt(self, ws_id, ta):
        """Fetch the last sent prompt from server and populate TextArea."""
        from textual.widgets import TextArea
        result = await self.conn.ws_send_command(ws_id, "CMD_GET_LAST_PROMPT")
        if result and result.get("ok"):
            last_prompt = result.get("last_prompt", "")
            if last_prompt:
                self._set_agent_input_text(last_prompt)


    def on_agent_panel_dismiss_error_request(self, event: AgentPanel.DismissErrorRequest):
        event.stop()
        ws_id = self.ws_mgr.active_id
        if not ws_id:
            return
        self.run_worker(self.conn.ws_send_command(ws_id, "CMD_DISMISS_ERROR"))

    def on_agent_panel_deny_permission_request(self, event: AgentPanel.DenyPermissionRequest):
        event.stop()
        ws_id = self.ws_mgr.active_id
        if not ws_id:
            return
        self.run_worker(self.conn.ws_send_command(ws_id, "CMD_PRESS_DENY"))

    def on_agent_panel_allow_permission_request(self, event: AgentPanel.AllowPermissionRequest):
        event.stop()
        ws_id = self.ws_mgr.active_id
        if not ws_id:
            return
        self.run_worker(self.conn.ws_send_command(ws_id, "CMD_PRESS_ALLOW"))

    def on_agent_panel_permission_menu_request(self, event: AgentPanel.PermissionMenuRequest):
        event.stop()
        from agbridge_tui.panels.file_menu import MenuScreen, _item
        items = [
            _item("Allow for Workspace", id="cmd_perm_allow_workspace"),
            _item("Allow Globally", id="cmd_perm_allow_globally"),
            _item("Run in sandbox", id="cmd_perm_run_sandbox"),
        ]
        self.push_screen(MenuScreen(items, x_offset=1, align_right=True), self._on_permission_menu_result)

    def _on_permission_menu_result(self, action_id):
        if not action_id:
            return
        ws_id = self.ws_mgr.active_id
        if not ws_id:
            return
        cmd_map = {
            "cmd_perm_allow_workspace": "CMD_PRESS_ALLOW_WORKSPACE",
            "cmd_perm_allow_globally": "CMD_PRESS_ALLOW_GLOBALLY",
            "cmd_perm_run_sandbox": "CMD_PRESS_RUN_SANDBOX",
        }
        cmd = cmd_map.get(action_id)
        if cmd:
            self.run_worker(self.conn.ws_send_command(ws_id, cmd))

    def on_agent_panel_select_model_request(self, event: AgentPanel.SelectModelRequest):
        event.stop()
        ws_id = self.ws_mgr.active_id
        if not ws_id:
            return
        # Store pending context — modal opens when CMD_LIST_MODELS_RESULT arrives
        self._pending_select = {
            "type": "model",
            "ws_id": ws_id,
            "current_value": event.model,
        }
        self.run_worker(self.conn.ws_send_command(ws_id, "CMD_LIST_MODELS"))

    def on_agent_panel_select_mode_request(self, event: AgentPanel.SelectModeRequest):
        event.stop()
        ws_id = self.ws_mgr.active_id
        if not ws_id:
            return
        self._pending_select = {
            "type": "mode",
            "ws_id": ws_id,
            "current_value": event.mode,
        }
        self.run_worker(self.conn.ws_send_command(ws_id, "CMD_LIST_MODES"))

    def on_agent_panel_select_workflow_request(self, event: AgentPanel.SelectWorkflowRequest):
        event.stop()
        ws_id = self.ws_mgr.active_id
        if not ws_id:
            return
        self._pending_select = {
            "type": "workflow",
            "ws_id": ws_id,
        }
        self.run_worker(self.conn.ws_send_command(ws_id, "CMD_LIST_WORKFLOWS"))

    def on_agent_panel_past_conversations_request(self, event: AgentPanel.PastConversationsRequest):
        event.stop()
        ws_id = self.ws_mgr.active_id
        if not ws_id:
            return
        self._pending_select = {
            "type": "conversation",
            "ws_id": ws_id,
        }
        self.run_worker(self.conn.ws_send_command(ws_id, "CMD_LIST_CONVERSATIONS"))

    def on_agent_panel_undo_to_prompt_request(self, event: AgentPanel.UndoToPromptRequest):
        event.stop()
        ws_id = self.ws_mgr.active_id
        if not ws_id:
            return
        self.run_worker(self.conn.ws_send_command(
            ws_id, "CMD_UNDO_TO_PROMPT",
            {"message_index": event.message_index},
        ))

    def on_agent_panel_select_mention_request(self, event: AgentPanel.SelectMentionRequest):
        event.stop()
        ws_id = self.ws_mgr.active_id
        if not ws_id:
            return
        
        # Build file list from fs_tree cache
        cache = self.ws_mgr._cache.get(ws_id, {})
        fs_tree = cache.get("fs_tree", {})
        
        items = []
        def _traverse(node, prefix=""):
            for k, v in node.items():
                path = f"{prefix}/{k}" if prefix else k
                if v == "directory":
                    items.append(path + "/")
                else:
                    items.append(path)
                if isinstance(v, dict):
                    _traverse(v, path)
        _traverse(fs_tree)

        def on_selected(selected_name):
            if selected_name:
                self._inject_into_agent_input(f"@[{selected_name}]", replace_char="@")

        self.push_screen(
            SelectModal(
                title="Select Mention",
                items=sorted(items),
            ),
            on_selected,
        )

    def _inject_into_agent_input(self, text: str, replace_char: str):
        """Inject text into the AgentPanel's TextArea widget, optionally replacing the trigger char."""
        try:
            from textual.widgets import TextArea
            panel = self.query_one("AgentPanel")
            ta = panel.query_one("#agent-input", TextArea)
            
            row, col = ta.cursor_location
            line = ta.document.get_line(row)
            
            replace_len = len(replace_char)
            if col >= replace_len and line[col - replace_len:col] == replace_char:
                ta.replace(text + " ", start=(row, col - replace_len), end=(row, col))
            else:
                ta.replace(text + " ", start=(row, col), end=(row, col))
                
            ta.focus()
        except Exception:
            pass

    def _handle_confirm_undo_dialog(self, data, workspace_id):
        """Handle Confirm Undo dialog — show ConfirmModal in TUI.

        Called from both CMD_UNDO_TO_PROMPT_RESULT (instant) and
        UI_CONFIRM_UNDO_DIALOG (polling fallback). Guard prevents
        duplicate modals.
        """
        if not data:
            return

        # Prevent duplicate modal
        if getattr(self, "_undo_modal_active", False):
            return
        self._undo_modal_active = True

        ws_id = workspace_id or self.ws_mgr.active_id
        if not ws_id:
            self._undo_modal_active = False
            return

        # Build message from dialog data
        description = data.get("description", "")
        file_changes = data.get("file_changes", [])

        msg_parts = ["Confirm Undo\n"]
        if description:
            msg_parts.append(description)
        if file_changes:
            msg_parts.append("")
            for fc in file_changes:
                msg_parts.append(f"  \u2022 {fc.get('detail', fc.get('file', ''))}")

        def on_confirm(confirmed):
            self._undo_modal_active = False
            cmd = "CMD_CONFIRM_UNDO" if confirmed else "CMD_CANCEL_UNDO"
            self.run_worker(self.conn.ws_send_command(ws_id, cmd))

        self.push_screen(
            ConfirmModal(
                title="Confirm Undo",
                message="\n".join(msg_parts),
                confirm_label="Confirm",
            ),
            on_confirm,
        )

    def _set_agent_input_text(self, text):
        """Set text in the Agent Panel's input TextArea.

        Used to restore the undone prompt after Confirm Undo.
        """
        agent = self.query_one("#agent-panel", AgentPanel)
        ta = agent.query_one("#agent-input", TextArea)
        ta.clear()
        ta.insert(text)
        self._event_log.log_event("DEBUG_UNDO", {
            "step": "_set_agent_input_text done",
            "text_len": len(text),
            "ta_text": repr(ta.text[:80]),
        })

    def _handle_list_result(self, data, select_type, items_key):
        """Handle CMD_LIST_MODELS_RESULT or CMD_LIST_MODES_RESULT."""
        pending = self._pending_select
        if not pending or pending["type"] != select_type:
            return
        self._pending_select = None

        if not data or not data.get("ok"):
            return

        items = data.get(items_key, [])
        ws_id = pending["ws_id"]
        current = pending["current_value"]

        if select_type == "model":
            title = "Select Model"
            cmd = "CMD_SELECT_MODEL"
            param_key = "model"
        else:
            title = "Select Mode"
            cmd = "CMD_SELECT_MODE"
            param_key = "mode"

        def on_selected(selected_name):
            if selected_name:
                self.run_worker(self.conn.ws_send_command(
                    ws_id, cmd, {param_key: selected_name},
                ))

        self.push_screen(
            SelectModal(
                title=title,
                items=items,
                current_value=current,
            ),
            on_selected,
        )

    # ── GitPanel Event Handlers ──────────────────────────────

    def on_git_panel_git_refresh_status_request(self, event: GitPanel.GitRefreshStatusRequest):
        event.stop()
        self.run_worker(self.action_cmd_git_status())

    def on_git_panel_git_commit_request(self, event: GitPanel.GitCommitRequest):
        event.stop()
        ws_id = self.ws_mgr.active_id
        if not ws_id:
            return
        self.run_worker(self.conn.ws_send_command(
            ws_id, "CMD_GIT_OP",
            {"action": "commit", "args": ["-m", event.commit_message], "worktree": event.worktree_path},
        ))

    def on_git_panel_git_stage_request(self, event: GitPanel.GitStageRequest):
        event.stop()
        ws_id = self.ws_mgr.active_id
        if not ws_id:
            return
        self.run_worker(self.conn.ws_send_command(
            ws_id, "CMD_GIT_OP",
            {"action": "add", "args": [event.path], "worktree": event.worktree_path},
        ))

    def on_git_panel_git_unstage_request(self, event: GitPanel.GitUnstageRequest):
        event.stop()
        ws_id = self.ws_mgr.active_id
        if not ws_id:
            return
        self.run_worker(self.conn.ws_send_command(
            ws_id, "CMD_GIT_OP",
            {"action": "restore", "args": ["--staged", event.path], "worktree": event.worktree_path},
        ))

    def on_git_panel_git_discard_request(self, event: GitPanel.GitDiscardRequest):
        event.stop()
        ws_id = self.ws_mgr.active_id
        if not ws_id:
            return

        def on_confirm(confirmed):
            if confirmed:
                self.run_worker(self.conn.ws_send_command(
                    ws_id, "CMD_GIT_OP",
                    {"action": "restore", "args": [event.path], "worktree": event.worktree_path},
                ))

        self.push_screen(
            ConfirmModal(
                title="Discard Changes",
                message=f"Are you sure you want to discard changes in '{event.path}'?\nThis cannot be undone.",
                confirm_label="Discard",
            ),
            on_confirm,
        )

    async def action_cmd_open_workspace(self):
        """Open new IDE workspace via File Explorer."""
        def on_result(path):
            if path:
                self.run_worker(self.ws_mgr.open_workspace(path))

        self.push_screen(FileExplorerModal(start_path="~"), on_result)

    def on_workspace_list_workspace_close_request(self, event: WorkspaceList.WorkspaceCloseRequest):
        """Handle request to close an entire workspace."""
        ws_id = event.workspace_id
        if not ws_id:
            return

        def on_confirm(confirmed):
            if confirmed:
                self.run_worker(self.ws_mgr.close_workspace(ws_id))

        self.push_screen(
            ConfirmModal(
                title="Close Workspace",
                message=f"Are you sure you want to close workspace '{ws_id}'?\nThis will terminate the IDE process.",
                confirm_label="Close",
            ),
            on_confirm,
        )


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="agbridge TUI Client")
    parser.add_argument("--host", default="localhost", help="Daemon host (default: localhost)")
    parser.add_argument("--port", type=int, default=18080, help="Daemon port (default: 18080)")
    parser.add_argument("--token", default=None, help="Auth token (default: load from ~/.agbridge/token)")
    parser.add_argument("--log-level", default="WARNING", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        filename=os.path.expanduser("~/.agbridge/tui.log"),
        filemode="a",
    )

    conn = Connection(host=args.host, port=args.port, token=args.token)
    if not args.token:
        conn.load_token()

    app = AgbridgeTUI(conn)
    app.run()


if __name__ == "__main__":
    main()
