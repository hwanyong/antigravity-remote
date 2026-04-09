"""
agbridge.collectors.git_tracker — Git status tracker

Extracts Modified/Staged/Untracked/Deleted status using native OS git commands.
Supports both normal repositories and bare repo + worktree setups.

In a bare repo layout:
  repo/
    .git         (file → "gitdir: .bare")
    .bare/       (actual git data)
    main/        (worktree, has its own .git file)
    dev/         (worktree, has its own .git file)

get_all_worktree_status() detects this layout and queries each worktree
independently, returning a unified {"worktrees": [...]} schema regardless
of whether the repo is bare or normal.
"""

import logging
import os
import subprocess

logger = logging.getLogger("agbridge.git_tracker")


def is_git_repo(workspace_root):
    """
    Check whether the workspace is a Git repository.
    Handles both normal repos (.git directory) and
    worktrees (.git file containing 'gitdir: ...' pointer).
    """
    git_path = os.path.join(workspace_root, ".git")
    return os.path.isdir(git_path) or os.path.isfile(git_path)


def get_git_status(workspace_root):
    """
    Parse the output of `git status --porcelain -uall`.

    Returns:
        dict: {
            "branch": str,
            "staged": [str],
            "modified": [str],
            "untracked": [str],
        }
    """
    result = {
        "branch": "",
        "staged": [],
        "modified": [],
        "deleted": [],
        "untracked": [],
    }

    try:
        branch_out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=workspace_root,
            capture_output=True, text=True, timeout=5,
        )
        if branch_out.returncode == 0:
            result["branch"] = branch_out.stdout.strip()

        status_out = subprocess.run(
            ["git", "status", "--porcelain", "-uall"],
            cwd=workspace_root,
            capture_output=True, text=True, timeout=10,
        )
        if status_out.returncode != 0:
            return result

        for line in status_out.stdout.splitlines():
            if len(line) < 4:
                continue
            index_status = line[0]
            work_status = line[1]
            filepath = line[3:]

            if index_status in ("A", "M", "D", "R"):
                result["staged"].append(filepath)

            if work_status == "M":
                result["modified"].append(filepath)
            elif work_status == "D":
                result["deleted"].append(filepath)
            elif work_status == "?":
                result["untracked"].append(filepath)

    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return result


def _is_bare_repo_parent(workspace_root):
    """
    Detect whether workspace_root is a bare repo parent directory.

    In this layout, .git is a FILE containing "gitdir: .bare" (or similar),
    and the actual git data lives in a subdirectory. Running git commands
    directly here fails with "fatal: this operation must be run in a work tree".

    Returns the bare gitdir path if detected, or None.
    """
    git_path = os.path.join(workspace_root, ".git")
    if not os.path.isfile(git_path):
        return None

    with open(git_path, "r", encoding="utf-8") as f:
        content = f.read().strip()

    if not content.startswith("gitdir:"):
        return None

    gitdir = content.split(":", 1)[1].strip()
    abs_gitdir = os.path.realpath(os.path.join(workspace_root, gitdir))

    # A bare repo's gitdir typically does NOT contain a "worktrees" pointer
    # back to itself — it IS the main git directory.
    # Check if it has a HEAD file (indicating it's a valid git dir).
    if os.path.isfile(os.path.join(abs_gitdir, "HEAD")):
        # Verify this is truly bare by checking if git status fails here
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=workspace_root,
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0 and "work tree" in result.stderr.lower():
            return abs_gitdir

    return None


def list_worktrees(workspace_root):
    """
    Enumerate all worktrees using `git worktree list --porcelain`.

    Returns:
        list[dict]: [{"path": str, "branch": str}, ...]
        Empty list if git is not available or workspace is not a git repo.
    """
    worktrees = []

    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=workspace_root,
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return worktrees

        current = {}
        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                if current and not current.get("bare"):
                    worktrees.append({
                        "path": current.get("path", ""),
                        "branch": current.get("branch", ""),
                    })
                current = {"path": line[9:]}
            elif line.startswith("branch "):
                # "branch refs/heads/main" → "main"
                ref = line[7:]
                current["branch"] = ref.split("/")[-1] if "/" in ref else ref
            elif line.strip() == "bare":
                current["bare"] = True

        # Flush last entry
        if current and not current.get("bare"):
            worktrees.append({
                "path": current.get("path", ""),
                "branch": current.get("branch", ""),
            })

    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return worktrees


def get_all_worktree_status(workspace_root):
    """
    Unified git status collection supporting both normal and bare+worktree repos.

    Returns a consistent schema regardless of repo type:
        {"worktrees": [{"path": str, "branch": str, "staged": [...], ...}, ...]}

    For normal repos, returns a single-element worktrees array.
    For bare repos, returns one entry per worktree.
    If the workspace is not a git repo at all, returns {"worktrees": []}.
    """
    if not is_git_repo(workspace_root):
        return {"worktrees": []}

    bare_gitdir = _is_bare_repo_parent(workspace_root)

    if bare_gitdir:
        # Bare repo — enumerate worktrees and collect status for each
        wt_list = list_worktrees(workspace_root)
        if not wt_list:
            return {"worktrees": []}

        worktrees = []
        for wt in wt_list:
            status = get_git_status(wt["path"])
            status["path"] = wt["path"]
            # Prefer branch from worktree list (more reliable for detached HEAD)
            if wt.get("branch") and not status.get("branch"):
                status["branch"] = wt["branch"]
            worktrees.append(status)

        return {"worktrees": worktrees}

    # Normal repo — single worktree
    status = get_git_status(workspace_root)
    status["path"] = workspace_root
    return {"worktrees": [status]}


def run_git_command(workspace_root, action, args=None):
    """
    Execute an arbitrary git command within the workspace.

    Args:
        workspace_root: Workspace path
        action: Git subcommand (e.g., "commit", "add", "checkout")
        args: Additional argument list

    Returns:
        dict: {"returncode": int, "stdout": str, "stderr": str}
    """
    cmd = ["git", action]
    if args:
        cmd.extend(args)

    try:
        proc = subprocess.run(
            cmd, cwd=workspace_root,
            capture_output=True, text=True, timeout=30,
        )
        return {
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    except subprocess.TimeoutExpired:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": "Command timed out after 30s",
        }
    except FileNotFoundError:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": "git not found in PATH",
        }
