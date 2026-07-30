# SPDX-License-Identifier: GPL-3.0-or-later
"""Command-line interfaces for Bunny Shell components."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import Any

from .core_state import read_snapshot, shell_status
from .launcher import LauncherState, application_search, route_intent
from .search import SearchIndex
from .settings import SettingsStore, parse_value
from .terminal import propose
from .workspaces import WorkspaceStore


def _emit(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))


def _search(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="bunny-search")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("status")
    sub.add_parser("locations")
    add = sub.add_parser("add")
    add.add_argument("path")
    remove = sub.add_parser("remove")
    remove.add_argument("path")
    sub.add_parser("rebuild")
    query = sub.add_parser("query")
    query.add_argument("text")
    query.add_argument("--limit", type=int, default=30)
    args = parser.parse_args(argv)
    if not args.command:
        from .ui import run_surface
        return run_surface("launcher")
    index = SearchIndex()
    if args.command == "status":
        value = index.status()
    elif args.command == "locations":
        value = index.locations()
    elif args.command == "add":
        value = index.add(args.path)
    elif args.command == "remove":
        value = {"removed": index.remove(args.path)}
    elif args.command == "rebuild":
        value = index.rebuild()
    else:
        value = index.query(args.text, args.limit)
    _emit(value)
    return 0


def _workspace(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="bunny-workspace")
    sub = parser.add_subparsers(dest="command")
    listing = sub.add_parser("list")
    listing.add_argument("--archived", action="store_true")
    create = sub.add_parser("create")
    create.add_argument("name")
    create.add_argument("--project")
    show = sub.add_parser("show")
    show.add_argument("id")
    rename = sub.add_parser("rename")
    rename.add_argument("id")
    rename.add_argument("name")
    duplicate = sub.add_parser("duplicate")
    duplicate.add_argument("id")
    duplicate.add_argument("--name")
    for name in ("archive", "restore", "detach-project"):
        command = sub.add_parser(name)
        command.add_argument("id")
    attach = sub.add_parser("attach-project")
    attach.add_argument("id")
    attach.add_argument("path")
    thread = sub.add_parser("attach-thread")
    thread.add_argument("id")
    thread.add_argument("thread_id")
    args = parser.parse_args(argv)
    if not args.command:
        from .ui import run_surface
        return run_surface("workspaces")
    store = WorkspaceStore()
    if args.command == "list":
        value = store.list(args.archived)
    elif args.command == "create":
        value = store.create(args.name, args.project)
    elif args.command == "show":
        value = store.get(args.id)
    elif args.command == "rename":
        value = store.rename(args.id, args.name)
    elif args.command == "duplicate":
        value = store.duplicate(args.id, args.name)
    elif args.command == "archive":
        value = store.archive(args.id)
    elif args.command == "restore":
        value = store.restore(args.id)
    elif args.command == "attach-project":
        value = store.attach_project(args.id, args.path)
    elif args.command == "detach-project":
        value = store.detach_project(args.id)
    else:
        value = store.attach_thread(args.id, args.thread_id)
    _emit(value)
    return 0


def _settings(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="bunny-settings")
    parser.add_argument("--section")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("get")
    schema = sub.add_parser("schema")
    set_value = sub.add_parser("set")
    set_value.add_argument("key")
    set_value.add_argument("value")
    reset = sub.add_parser("reset")
    reset.add_argument("key", nargs="?")
    args = parser.parse_args(argv)
    if not args.command:
        from .ui import run_surface
        return run_surface("settings", args.section)
    store = SettingsStore()
    if args.command == "get":
        value = store.get_all()
    elif args.command == "schema":
        value = store.describe()
    elif args.command == "set":
        value = store.set(args.key, parse_value(args.value))
    else:
        value = store.reset(args.key)
    _emit(value)
    return 0


def _terminal(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="bunny-terminal")
    sub = parser.add_subparsers(dest="command")
    proposal = sub.add_parser("propose")
    proposal.add_argument("--cwd", default=str(Path.cwd()))
    proposal.add_argument("command_text", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if not args.command:
        from .ui import launch_terminal
        return launch_terminal()
    command = " ".join(item for item in args.command_text if item != "--").strip()
    _emit(propose(command, args.cwd).as_dict())
    return 0


def _launcher(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="bunny-launcher")
    parser.add_argument("--query")
    parser.add_argument("--intent")
    parser.add_argument("--pin")
    parser.add_argument("--unpin")
    parser.add_argument("--state", action="store_true")
    args = parser.parse_args(argv)
    if args.intent is not None:
        _emit(route_intent(args.intent).as_dict())
        return 0
    if args.query is not None:
        _emit(application_search(args.query))
        return 0
    launcher_state = LauncherState()
    if args.pin:
        _emit(launcher_state.pin(args.pin))
        return 0
    if args.unpin:
        _emit(launcher_state.unpin(args.unpin))
        return 0
    if args.state:
        _emit(launcher_state.get())
        return 0
    from .ui import run_surface
    return run_surface("launcher")


def _shell(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="bunny-shell")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("status")
    sub.add_parser("core-snapshot")
    args = parser.parse_args(argv)
    if args.command == "status":
        _emit(shell_status())
        return 0
    if args.command == "core-snapshot":
        _emit(read_snapshot() or {"status": "unavailable"})
        return 0
    from .ui import run_surface
    return run_surface("command")


def main(program: str | None = None, argv: list[str] | None = None) -> int:
    name = program or Path(sys.argv[0]).name
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if name == "bunny-search":
            return _search(arguments)
        if name == "bunny-workspace":
            return _workspace(arguments)
        if name == "bunny-settings":
            return _settings(arguments)
        if name == "bunny-terminal":
            return _terminal(arguments)
        if name == "bunny-launcher":
            return _launcher(arguments)
        if name in {"bunny-approvals", "bunny-tasks", "bunny-plans", "bunny-project", "bunny-command", "bunny-privacy", "bunny-notifications", "bunny-quick-settings"}:
            from .ui import run_surface
            return run_surface(name.removeprefix("bunny-").replace("command", "command"))
        return _shell(arguments)
    except (KeyError, OSError, PermissionError, TimeoutError, ValueError) as exc:
        print(f"{name}: {exc}", file=sys.stderr)
        return 2
