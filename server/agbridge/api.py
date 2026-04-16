"""
agbridge.api — FastAPI router (multi-workspace)

Implements the hybrid HTTP REST + WebSocket protocol with workspace routing.

Endpoints:
- GET  /api/workspaces                      → list all workspaces
- POST /api/workspaces                      → open new workspace (launch IDE)
- DELETE /api/workspaces/{workspace_id}     → close workspace (terminate IDE)
- GET  /api/workspaces/{workspace_id}/snapshot  → workspace state snapshot
- GET  /api/workspaces/{workspace_id}/status    → workspace status
- POST /api/workspaces/{workspace_id}/command   → workspace command
- GET  /api/diagnostics                     → list recent diagnostic records
- GET  /api/diagnostics/{filename}          → individual diagnostic JSON
- WS   /ws                                  → all events, workspace_id tagged
"""

import asyncio
import json
import logging
import os
import shutil
import time

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

from agbridge import protocol
from agbridge.config import AUTH_ENABLED, MAX_WS_CLIENTS
from agbridge.auth import verify_token
from agbridge.collectors.git_tracker import run_git_command, get_git_status

logger = logging.getLogger("agbridge.api")


# ── Authentication helpers ───────────────────────────────────

def _extract_token(request):
    """Extract token from Authorization header or query parameter."""
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return request.query_params.get("token", "")


def _check_auth(request):
    """
    Validate request authentication.
    Returns None if auth passes, or a JSONResponse with 401 if it fails.
    """
    if not AUTH_ENABLED:
        return None

    token = _extract_token(request)
    if verify_token(token):
        return None

    return JSONResponse(
        status_code=401,
        content={"error": "Unauthorized: invalid or missing token"},
    )


# ── Safe command execution wrapper ───────────────────────────

def _safe_execute(handler, engine, data, **kwargs):
    """
    Execute a command handler with exception protection.
    Prevents server crashes from handler-level errors.
    """
    try:
        return handler(engine, data, **kwargs)
    except Exception as e:
        logger.exception("Command handler error: %s", type(e).__name__)
        return {"ok": False, "error": str(e)}


# ── App factory ──────────────────────────────────────────────

def create_app(supervisor, input_queue, lifespan=None):
    """
    Create a FastAPI app bound to multi-workspace infrastructure.

    Args:
        supervisor: WorkspaceSupervisor — unified lifecycle manager.
        input_queue: InputQueue — serializes AX write operations.
        lifespan: Optional async context manager for startup/shutdown.
    """

    app = FastAPI(
        title="Antigravity Remote Bridge",
        version="0.3.0",
        lifespan=lifespan,
    )

    # ── Middleware ─────────────────────────────────────────
    app.add_middleware(GZipMiddleware, minimum_size=500)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Workspace CRUD ────────────────────────────────────

    @app.get("/api/workspaces")
    async def list_workspaces(request: Request):
        """Return all registered workspaces."""
        auth_error = _check_auth(request)
        if auth_error:
            return auth_error
        res = await supervisor.list_all()
        return JSONResponse(content={"workspaces": res})

    @app.post("/api/workspaces")
    async def open_workspace(request: Request):
        """Launch a new Antigravity IDE for the given path."""
        auth_error = _check_auth(request)
        if auth_error:
            return auth_error

        body = await request.json()
        path = body.get("path", "")
        if not path:
            return JSONResponse(
                status_code=400,
                content={"ok": False, "error": "path is required"},
            )

        if not os.path.isdir(path):
            return JSONResponse(
                status_code=400,
                content={"ok": False, "error": "path does not exist"},
            )

        pid = supervisor.launch_workspace(path)
        if pid is None:
            return JSONResponse(
                status_code=500,
                content={"ok": False, "error": "failed to launch IDE"},
            )

        # Supervisor's reconcile() will discover the CG window automatically
        return JSONResponse(content={"ok": True, "pid": pid, "path": path})

    @app.delete("/api/workspaces/{workspace_id}")
    async def close_workspace(workspace_id: str, request: Request):
        """Close the IDE and unregister the workspace."""
        auth_error = _check_auth(request)
        if auth_error:
            return auth_error

        closed = await supervisor.close_workspace(workspace_id)
        if not closed:
            return JSONResponse(
                status_code=404,
                content={"ok": False, "error": f"workspace '{workspace_id}' not found"},
            )

        return JSONResponse(content={"ok": True})

    # ── Diagnostics ───────────────────────────────────────

    @app.get("/api/diagnostics")
    async def list_diagnostics(request: Request):
        """Return recent diagnostic records."""
        auth_error = _check_auth(request)
        if auth_error:
            return auth_error

        from agbridge.diagnostics import get_recorder
        limit = int(request.query_params.get("limit", "20"))
        records = get_recorder().list_recent(limit=limit)
        return JSONResponse(content={"diagnostics": records})

    @app.get("/api/diagnostics/{filename}")
    async def get_diagnostic(filename: str, request: Request):
        """Return a specific diagnostic record."""
        auth_error = _check_auth(request)
        if auth_error:
            return auth_error

        from agbridge.diagnostics import get_recorder
        record = get_recorder().get_record(filename)
        if record is None:
            return JSONResponse(
                status_code=404,
                content={"error": f"diagnostic '{filename}' not found"},
            )
        return JSONResponse(content=record)

    # ── Per-workspace endpoints ───────────────────────────

    @app.get("/api/workspaces/{workspace_id}/snapshot")
    async def workspace_snapshot(workspace_id: str, request: Request):
        """Return the full state snapshot for a specific workspace."""
        auth_error = _check_auth(request)
        if auth_error:
            return auth_error

        engine = supervisor.get(workspace_id)
        if not engine:
            return JSONResponse(
                status_code=404,
                content={"error": f"workspace '{workspace_id}' not found"},
            )
        return JSONResponse(content=engine.store.snapshot())

    @app.get("/api/workspaces/{workspace_id}/status")
    async def workspace_status(workspace_id: str, request: Request):
        """Return the status of a specific workspace."""
        auth_error = _check_auth(request)
        if auth_error:
            return auth_error

        engine = supervisor.get(workspace_id)
        if not engine:
            return JSONResponse(
                status_code=404,
                content={"error": f"workspace '{workspace_id}' not found"},
            )

        return JSONResponse(content={
            "workspace_id": workspace_id,
            "state": engine.current_state,
            "ide_connected": engine.ide.is_connected,
            "pid": engine.ide.pid if engine.ide else None,
            "workspace": engine.workspace_root,
            "ws_clients": len(supervisor._ws_clients),
        })

    @app.post("/api/workspaces/{workspace_id}/command")
    async def workspace_command(workspace_id: str, request: Request):
        """Process a command for a specific workspace."""
        auth_error = _check_auth(request)
        if auth_error:
            return auth_error

        engine = supervisor.get(workspace_id)
        if not engine:
            return JSONResponse(
                status_code=404,
                content={"ok": False, "error": f"workspace '{workspace_id}' not found"},
            )

        body = await request.json()
        cmd_type = body.get("type", "")
        data = body.get("data", {})

        # Route AX write operations through InputQueue
        if cmd_type in _WRITE_COMMANDS:
            result = await input_queue.enqueue(
                workspace_id, _WRITE_COMMANDS[cmd_type], data,
            )
            return JSONResponse(content=result)

        handler = _COMMAND_HANDLERS.get(cmd_type)
        if not handler:
            return JSONResponse(
                status_code=400,
                content={"error": f"Unknown command: {cmd_type}"},
            )

        result = _safe_execute(handler, engine, data)
        return JSONResponse(content=result)

    # ── WebSocket ─────────────────────────────────────────

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        """
        Single WS endpoint — all workspace events tagged with workspace_id.
        Clients receive everything and filter locally.
        """
        # Auth check
        if AUTH_ENABLED:
            token = ws.query_params.get("token", "")
            if not verify_token(token):
                await ws.close(code=1008, reason="Unauthorized")
                return

        # Client limit check
        if len(supervisor._ws_clients) >= MAX_WS_CLIENTS:
            await ws.accept()
            await ws.close(code=1013, reason="Max clients reached")
            logger.warning("WS client rejected: max clients (%d) reached", MAX_WS_CLIENTS)
            return

        await ws.accept()
        supervisor.register_ws(ws)
        logger.info("WS client connected (total: %d)", len(supervisor._ws_clients))

        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                    msg_type = msg.get("type", "")

                    # Heartbeat response
                    if msg_type == "PONG":
                        supervisor.record_pong(ws)
                        continue

                    # Command handling — requires workspace_id
                    ws_id = msg.get("workspace_id", "")
                    data = msg.get("data", {})
                    engine = supervisor.get(ws_id) if ws_id else None

                    if not engine:
                        await ws.send_text(json.dumps({
                            "type": f"{msg_type}_FAIL",
                            "workspace_id": ws_id,
                            "data": {"ok": False, "error": "workspace not found"},
                            "ts": time.time(),
                        }))
                        continue

                    # Prompt history — direct read from InputQueue (no AX)
                    if msg_type == protocol.CMD_GET_LAST_PROMPT:
                        result = {
                            "ok": True,
                            "last_prompt": input_queue.get_last_prompt(ws_id),
                        }
                    # Route AX writes through InputQueue — ACK first
                    elif msg_type in _WRITE_COMMANDS:
                        await ws.send_text(json.dumps({
                            "type": f"{msg_type}_ACK",
                            "workspace_id": ws_id,
                            "data": {},
                            "ts": time.time(),
                        }))
                        result = await input_queue.enqueue(
                            ws_id, _WRITE_COMMANDS[msg_type], data,
                        )
                    else:
                        handler = _COMMAND_HANDLERS.get(msg_type)
                        if handler:
                            result = _safe_execute(handler, engine, data)
                        else:
                            result = {"ok": False, "error": f"unknown command: {msg_type}"}

                    suffix = "_DONE" if result.get("ok") else "_FAIL"
                    await ws.send_text(json.dumps({
                        "type": f"{msg_type}{suffix}",
                        "workspace_id": ws_id,
                        "data": result,
                        "ts": time.time(),
                    }))

                except json.JSONDecodeError:
                    pass
        except WebSocketDisconnect:
            pass
        finally:
            supervisor.unregister_ws(ws)
            logger.info("WS client disconnected (total: %d)", len(supervisor._ws_clients))

    return app


# ── Write commands (routed through InputQueue) ───────────────

_WRITE_COMMANDS = {
    protocol.CMD_INJECT_PROMPT: "inject_prompt",
    protocol.CMD_ACCEPT_ALL: "accept_all",
    protocol.CMD_REJECT_ALL: "reject_all",
    protocol.CMD_CANCEL: "cancel",
    protocol.CMD_SELECT_MODEL: "select_model",
    protocol.CMD_SELECT_MODE: "select_mode",
    protocol.CMD_NEW_CONVERSATION: "new_conversation",
    protocol.CMD_RETRY: "retry",
    protocol.CMD_DISMISS_ERROR: "dismiss_error",
    protocol.CMD_PRESS_DENY: "press_deny",
    protocol.CMD_PRESS_ALLOW: "press_allow",
    protocol.CMD_PRESS_ALLOW_WORKSPACE: "press_allow_workspace",
    protocol.CMD_PRESS_ALLOW_GLOBALLY: "press_allow_globally",
    protocol.CMD_PRESS_RUN_SANDBOX: "press_run_sandbox",
    protocol.CMD_LIST_MODELS: "list_models",
    protocol.CMD_LIST_MODES: "list_modes",
    protocol.CMD_LIST_CONVERSATIONS: "list_conversations",
    protocol.CMD_SELECT_CONVERSATION: "select_conversation",
    protocol.CMD_DELETE_CONVERSATION: "delete_conversation",
    protocol.CMD_EXPAND_CONVERSATIONS: "expand_conversations",
    protocol.CMD_CLOSE_CONVERSATION_PANEL: "close_conversation_panel",
    protocol.CMD_REFRESH_MODELS: "refresh_models",
    protocol.CMD_SCROLL_CONVERSATION: "scroll_conversation",
    protocol.CMD_CLEAR_CACHE: "clear_cache",
    protocol.CMD_UNDO_TO_PROMPT: "undo_to_prompt",
    protocol.CMD_CONFIRM_UNDO: "confirm_undo",
    protocol.CMD_CANCEL_UNDO: "cancel_undo",
}


# ── Read-only command handlers ───────────────────────────────

def _handle_file_read(engine, data):
    path = data.get("path", "")
    if not path:
        return {"ok": False, "error": "path is required"}

    full_path = os.path.join(engine.workspace_root, path)
    full_path = os.path.realpath(full_path)

    if not full_path.startswith(engine.workspace_root):
        return {"ok": False, "error": "path outside workspace"}

    if not os.path.isfile(full_path):
        return {"ok": False, "error": "file not found"}

    try:
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return {"ok": True, "content": content}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _handle_workspace_create(engine, data):
    path = data.get("path", "")
    entry_type = data.get("type", "directory")
    if not path:
        return {"ok": False, "error": "path is required"}

    full_path = os.path.join(engine.workspace_root, path)
    full_path = os.path.realpath(full_path)

    if not full_path.startswith(engine.workspace_root):
        return {"ok": False, "error": "path outside workspace"}

    try:
        if entry_type == "directory":
            os.makedirs(full_path, exist_ok=True)
        else:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w") as f:
                f.write("")
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _handle_workspace_delete(engine, data):
    path = data.get("path", "")
    if not path:
        return {"ok": False, "error": "path is required"}

    full_path = os.path.join(engine.workspace_root, path)
    full_path = os.path.realpath(full_path)

    if not full_path.startswith(engine.workspace_root):
        return {"ok": False, "error": "path outside workspace"}

    if full_path == engine.workspace_root:
        return {"ok": False, "error": "cannot delete workspace root"}

    try:
        if os.path.isdir(full_path):
            shutil.rmtree(full_path)
        elif os.path.exists(full_path):
            os.remove(full_path)
        else:
            return {"ok": False, "error": "path not found"}
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _handle_git_op(engine, data):
    action = data.get("action", "")
    args = data.get("args", [])
    if not action:
        return {"ok": False, "error": "action is required"}

    # Worktree routing: execute in specific worktree if specified
    cwd = engine.workspace_root
    worktree = data.get("worktree")
    if worktree:
        real_worktree = os.path.realpath(worktree)
        real_root = os.path.realpath(engine.workspace_root)
        if not real_worktree.startswith(real_root):
            return {"ok": False, "error": "worktree path outside workspace"}
        cwd = real_worktree

    result = run_git_command(cwd, action, args)
    return {"ok": result["returncode"] == 0, **result}


def _handle_list_workflows(engine, data):
    import glob
    global_dir = os.path.expanduser("~/.gemini/antigravity/global_workflows")
    project_dir = os.path.join(engine.workspace_root, ".gemini", "antigravity", "global_workflows")

    wfs = []
    if os.path.isdir(global_dir):
        for f in glob.glob(os.path.join(global_dir, "*.md")):
            wfs.append(os.path.basename(f)[:-3])
    if os.path.isdir(project_dir):
        for f in glob.glob(os.path.join(project_dir, "*.md")):
            wfs.append(os.path.basename(f)[:-3])

    return {"ok": True, "workflows": sorted(list(set(wfs)))}


def _handle_list_rules(engine, data):
    """List available rule files from global and project directories."""
    import glob

    global_dir = os.path.expanduser("~/.gemini/antigravity")
    project_dir = os.path.join(engine.workspace_root, ".gemini")

    rules = []

    # Global rules (excluding subdirectories like global_workflows, skills, etc.)
    if os.path.isdir(global_dir):
        for f in glob.glob(os.path.join(global_dir, "*.md")):
            rules.append(os.path.basename(f)[:-3])

    # Project-level rules
    if os.path.isdir(project_dir):
        for f in glob.glob(os.path.join(project_dir, "*.md")):
            rules.append(os.path.basename(f)[:-3])

    return {"ok": True, "rules": sorted(list(set(rules)))}


_COMMAND_HANDLERS = {
    protocol.CMD_FILE_READ: _handle_file_read,
    protocol.CMD_WORKSPACE_CREATE: _handle_workspace_create,
    protocol.CMD_WORKSPACE_DELETE: _handle_workspace_delete,
    protocol.CMD_GIT_OP: _handle_git_op,
    protocol.CMD_LIST_WORKFLOWS: _handle_list_workflows,
    protocol.CMD_LIST_RULES: _handle_list_rules,
}
