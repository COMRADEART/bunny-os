# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Command-line and service entry points for the Bunny Companion."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import signal
import sys
from typing import Any, Mapping

from .model import PresentationKind
from .presentation import CapabilityPresentationPlan
from .protocol import CompanionClient, CompanionClientError, CompanionServer, default_socket_path
from .runtime import (
    CompanionRuntime,
    RuntimePaths,
    conservative_capability_plan,
    current_capability_context,
)
from .store import default_state_directory


def _emit(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))


def _load_plan(path: Path) -> CapabilityPresentationPlan:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, Mapping):
        raise ValueError("capability plan must be an object")
    return CapabilityPresentationPlan.from_execution_plan(document)


def serve(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="bunny-companion-service")
    parser.add_argument("--state-directory", type=Path, default=default_state_directory())
    parser.add_argument("--socket", type=Path, default=default_socket_path())
    parser.add_argument("--capability-plan", type=Path)
    parser.add_argument("--conservative", action="store_true")
    parser.add_argument("--text-only", action="store_true")
    parser.add_argument("--reduced-motion", action="store_true")
    parser.add_argument("--no-animation", action="store_true")
    args = parser.parse_args(argv)

    if args.capability_plan:
        plan = _load_plan(args.capability_plan)
        from .presentation import PresentationSignals
        signals = PresentationSignals()
    elif args.conservative:
        plan = conservative_capability_plan()
        from .presentation import PresentationSignals
        signals = PresentationSignals(display_available=False, audio_output_available=False, headless=True)
    else:
        try:
            plan, signals = current_capability_context()
        except (OSError, RuntimeError, ValueError) as exc:
            print(
                f"bunny-companion-service: capability assessment unavailable ({type(exc).__name__}); using text-only",
                file=sys.stderr,
            )
            plan = conservative_capability_plan()
            from .presentation import PresentationSignals
            signals = PresentationSignals(display_available=False, audio_output_available=False, headless=True)
    if args.text_only:
        signals = replace(signals, user_preference=PresentationKind.TEXT_ONLY)
    if args.reduced_motion:
        signals = replace(signals, reduced_motion=True)
    if args.no_animation:
        signals = replace(signals, no_animation=True)

    runtime = CompanionRuntime(
        paths=RuntimePaths(args.state_directory),
        capability_plan=plan,
        presentation_signals=signals,
    )
    server = CompanionServer(runtime, args.socket)
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True
        # shutdown must not run on serve_forever's thread.
        import threading
        threading.Thread(target=server.close, daemon=True).start()

    for name in ("SIGTERM", "SIGINT"):
        number = getattr(signal, name, None)
        if number is not None:
            try:
                signal.signal(number, stop)
            except (OSError, ValueError):
                pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if not stopping:
            server.close()
        runtime.close()
    return 0


def _approval(snapshot: Mapping[str, Any], request_id: str | None) -> Mapping[str, Any]:
    approvals = snapshot.get("approvals")
    if not isinstance(approvals, list) or not approvals:
        raise ValueError("task has no pending approval")
    if request_id is None:
        if len(approvals) != 1:
            raise ValueError("task has multiple approvals; name --request-id")
        return approvals[0]
    for approval in approvals:
        if isinstance(approval, Mapping) and approval.get("requestId") == request_id:
            return approval
    raise KeyError(f"task has no pending approval {request_id!r}")


def client_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="bunny-companion")
    parser.add_argument("--socket", type=Path, default=default_socket_path())
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("health")
    submit = sub.add_parser("submit")
    submit.add_argument("request")
    submit.add_argument("--session-id")
    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("task_id")
    snapshot.add_argument("--after-sequence", type=int, default=0)
    sub.add_parser("tasks")
    for name in ("approve", "deny", "cancel-task"):
        command = sub.add_parser(name)
        command.add_argument("task_id")
        command.add_argument("--request-id")
    cancel = sub.add_parser("cancel")
    cancel.add_argument("task_id")
    demo = sub.add_parser("vertical-slice")
    demo.add_argument("--request", default="Record a harmless local Bunny Companion demonstration result.")
    demo.add_argument("--auto-approve", action="store_true")
    args = parser.parse_args(argv)

    if not args.command:
        from .gtk_shell import run
        return run(args.socket)
    client = CompanionClient(args.socket)
    if args.command == "health":
        value = client.health()
    elif args.command == "submit":
        value = client.submit(args.request, session_id=args.session_id)
    elif args.command == "snapshot":
        value = client.snapshot(args.task_id, after_sequence=args.after_sequence)
    elif args.command == "tasks":
        value = client.call("tasks")
    elif args.command in {"approve", "deny", "cancel-task"}:
        pending = client.snapshot(args.task_id)
        approval = _approval(pending, args.request_id)
        decision = {"approve": "approve", "deny": "deny", "cancel-task": "cancel_task"}[args.command]
        value = client.resolve_approval(args.task_id, approval, decision)
    elif args.command == "cancel":
        value = client.cancel(args.task_id)
    else:
        value = client.submit(args.request)
        if args.auto_approve:
            approval = _approval(value, None)
            value = client.resolve_approval(value["task"]["taskId"], approval, "approve")
    _emit(value)
    return 0


def main(program: str | None = None, argv: list[str] | None = None) -> int:
    name = program or Path(sys.argv[0]).name
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if name == "bunny-companion-service":
            return serve(arguments)
        return client_main(arguments)
    except (CompanionClientError, KeyError, OSError, PermissionError, ValueError) as exc:
        print(f"{name}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
