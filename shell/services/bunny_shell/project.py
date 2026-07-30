# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded read-only Git projection for the project dashboard."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
from typing import Any


MAX_CHANGED_FILES = 200


def _git(root: Path, *arguments: str) -> str:
    executable = shutil.which("git")
    if not executable:
        raise RuntimeError("git is unavailable")
    result = subprocess.run(
        [executable, "-C", str(root), *arguments],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=5,
        env={"PATH": str(Path(executable).parent), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"},
    )
    if result.returncode:
        raise RuntimeError("project is not an available Git worktree")
    if len(result.stdout.encode("utf-8")) > 256 * 1024:
        raise RuntimeError("Git status exceeded the dashboard limit")
    return result.stdout


def project_status(path: str) -> dict[str, Any]:
    root = Path(path).expanduser()
    if not root.exists() or not root.is_dir():
        raise ValueError("project root must be an existing directory")
    root = root.resolve()
    try:
        branch = _git(root, "symbolic-ref", "--short", "HEAD").strip()
    except RuntimeError:
        try:
            branch = f"detached:{_git(root, 'rev-parse', '--short', 'HEAD').strip()}"
        except RuntimeError:
            branch = "unborn"
    changed = [line for line in _git(root, "status", "--porcelain=v1", "--untracked-files=normal").splitlines() if line]
    return {
        "projectRoot": str(root),
        "branch": branch[:256],
        "changedFiles": changed[:MAX_CHANGED_FILES],
        "changedFileCount": len(changed),
        "truncated": len(changed) > MAX_CHANGED_FILES,
        "scriptsExecuted": False,
        "networkUsed": False,
    }
