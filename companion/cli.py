# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Command-line and service entry points for the Bunny Companion."""
"""The ``bunny-os companion`` command group.

Every command returns a JSON-serialisable document and none of them prints. The
UX shell is going to consume this, and a shell that parsed human-formatted text
would break the first time somebody improved a sentence — so the structure *is*
the interface, and the human rendering is
:func:`bunny_os.cli._emit`'s problem rather than this module's.

Two conventions are load-bearing.

**Mutating commands say so, in the document.** Every result carries an
``effect`` field: ``"read-only"``, or a sentence naming what changed. A UX shell
can therefore tell a user what a command did without knowing which commands
mutate, and a transcript of a support session can be read years later by
somebody who does not.

**Nothing here reaches the network or a provider.** The runtime it builds has
one local executor and one local reviewer, and the approval source is the
refusing default unless the caller explicitly asks otherwise. ``run-demo`` is
the only command that supplies consent, and it says which consent it supplied.
"""

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
import os
from pathlib import Path
from typing import Any

from capability.model import inventory_from_json
from capability.policy import PolicyError, load_policy
from capability.registry import load_registry
from capability.runtime import Assessment, assess, assess_current_machine
from capability.simulate import MACHINES, describe, simulate

from .approvals import CompanionApprovalStore, RefusingConsent
from .privacy import AUDIENCES
from .cancellation import cancel_task
from .clock import SystemClock
from .coordination import CoordinationPolicy
from .demo import DEMO_REQUEST, run_demo
from .errors import CompanionError
from .executor import DeterministicLocalExecutor
from .ids import RandomIds
from .recovery import recover
from .reviewer import DeterministicLocalReviewer
from .runtime import CompanionRuntime, RuntimeOptions
from .session import CostPolicy, LOCALITY_PREFERENCES, PrivacyPolicy
from .store import CompanionStore
from .task import CANCELLATION_CAUSES
from .tools import ToolBroker
from .character.diagnostics import (
    registry_for as character_registry_for,
    renderer_projection,
    run_diagnostic_demo,
)
from .character.errors import CharacterError
from .character.importer import CharacterPackageImporter
from .character.package import validate_package_directory
from .character.schema import PackageTrustState

__all__ = ["add_arguments", "default_root", "dispatch"]

_SIMULATION_BANNER = (
    "SIMULATED HARDWARE - {name}: {description}. "
    "The capability decisions below are the policy engine's answers for a synthetic "
    "inventory. They are not a measurement of any physical machine."
)


def default_root() -> Path:
    """Where the companion keeps its store.

    ``BUNNY_COMPANION_ROOT`` first, then the XDG state directory. Under the user
    rather than under ``/var``: a companion session is one person's
    conversation, and putting it somewhere system-wide would make it readable by
    every account on a shared machine.
    """
    override = os.environ.get("BUNNY_COMPANION_ROOT")
    if override:
        return Path(override)
    state = os.environ.get("XDG_STATE_HOME")
    base = Path(state) if state else Path.home() / ".local" / "state"
    return base / "bunny-os" / "companion"


def add_arguments(subparsers: argparse._SubParsersAction) -> None:
    """Attach ``companion`` to the ``bunny-os`` command tree."""
    root = subparsers.add_parser("companion", help="the headless Bunny Companion runtime")
    root.add_argument("--root", type=Path, default=None, help="companion store directory")
    root.add_argument("--simulate", choices=sorted(MACHINES), help="decide against simulated hardware")
    root.add_argument("--inventory", type=Path, help="decide against a saved capability inventory")
    root.add_argument("--policy", type=Path, help="capability policy file")
    root.add_argument("--services", type=Path, help="service manifest directory")
    group = root.add_subparsers(dest="companion_command", required=True)

    group.add_parser("sessions", help="list sessions (read-only)")

    session = group.add_parser("session", help="session operations")
    session_group = session.add_subparsers(dest="session_command", required=True)
    create = session_group.add_parser("create", help="CREATES a new session")
    create.add_argument("--title", default="Companion session")
    create.add_argument("--locality", choices=LOCALITY_PREFERENCES, default="device-only")
    create.add_argument("--allow-remote", action="store_true", help="permit remote execution from this session")
    create.add_argument("--task-limit-units", type=int, default=0)
    create.add_argument("--session-limit-units", type=int, default=0)
    inspect = session_group.add_parser("inspect", help="show one session (read-only)")
    inspect.add_argument("session_id")
    for name, help_text in (("pause", "PAUSES"), ("resume", "RESUMES"), ("close", "CLOSES")):
        parser = session_group.add_parser(name, help=f"{help_text} a session")
        parser.add_argument("session_id")

    task = group.add_parser("task", help="task operations")
    task_group = task.add_subparsers(dest="task_command", required=True)
    submit = task_group.add_parser("submit", help="CREATES a task, and runs it with --run")
    submit.add_argument("--session", required=True, dest="session_id")
    submit.add_argument("--request", required=True)
    submit.add_argument("--run", action="store_true", help="RUNS the task immediately")
    submit.add_argument("--classification", default=None)
    submit.add_argument("--cost-limit-units", type=int, default=None)
    task_inspect = task_group.add_parser("inspect", help="show one task (read-only)")
    task_inspect.add_argument("task_id")
    task_inspect.add_argument("--audience", default="ui", choices=AUDIENCES,
                              help="render for this audience")
    task_events = task_group.add_parser("events", help="show one task's events (read-only)")
    task_events.add_argument("task_id")
    task_events.add_argument("--audience", default="ui", choices=AUDIENCES)
    task_run = task_group.add_parser("run", help="RUNS an existing task")
    task_run.add_argument("task_id")
    task_cancel = task_group.add_parser("cancel", help="CANCELS a task")
    task_cancel.add_argument("task_id")
    task_cancel.add_argument("--cause", choices=[item for item in CANCELLATION_CAUSES if item], default="user")
    task_cancel.add_argument("--detail", default="")

    approvals = group.add_parser("approvals", help="approval questions and answers")
    approvals.add_argument("--grant", dest="grant_id", help="RECORDS a grant for one request id")
    approvals.add_argument("--deny", dest="deny_id", help="RECORDS a denial for one request id")

    recovery = group.add_parser("recover", help="RECOVERS incomplete tasks after a restart")
    recovery.add_argument("--dry-run", action="store_true", help="validate only; change nothing")

    demo = group.add_parser("run-demo", help="RUNS the headless vertical slice in a scratch directory")
    demo.add_argument("--demo-root", type=Path, default=None, help="where the demo store is written")
    demo.add_argument("--refuse-approval", action="store_true", help="run with nobody answering the approval")

    # -- the integrated half ------------------------------------------------

    health = group.add_parser("health", help="report the runtime's health (read-only)")
    health.add_argument("--endpoint", type=Path, default=None,
                        help="ask a running companion service over its socket instead")

    presentation = group.add_parser(
        "presentation", help="project one task's events into presentation state (read-only)"
    )
    presentation.add_argument("task_id", nargs="?", default=None)
    presentation.add_argument("--session", dest="session_id", default=None)
    presentation.add_argument("--endpoint", type=Path, default=None,
                              help="ask a running companion service over its socket instead")

    serve = group.add_parser("serve", help="RUNS the canonical companion service in the foreground")
    serve.add_argument("--endpoint", type=Path, default=None, help="socket path to bind")
    serve.add_argument("--no-recover", action="store_true", help="skip the start-up recovery pass")
    serve.add_argument("--once", action="store_true",
                       help="bind, report, and stop; for checking the endpoint without holding it")

    shell = group.add_parser("shell", help="RUNS the GTK client against a companion service")
    shell.add_argument("--endpoint", type=Path, default=None, help="socket path to connect to")
    shell.add_argument("--text-only", action="store_true", help="prefer the text-only presentation")

    migrate = group.add_parser(
        "migrate-ux-store", help="inspect, IMPORT or roll back a UX-prototype SQLite store"
    )
    migrate.add_argument("--source", type=Path, default=None, help="path to companion.sqlite3")
    migrate.add_argument("--apply", action="store_true",
                         help="PERFORMS the archive import; without it this is a dry run")
    migrate.add_argument("--rollback", action="store_true", help="REMOVES a previous archive import")
    migrate.add_argument("--name", default="ux-shell-sqlite", help="archive directory name")

    character = group.add_parser("character", help="character package diagnostics and selection")
    character_group = character.add_subparsers(dest="character_command", required=True)
    character_group.add_parser("list", help="list built-in and imported packages (read-only)")
    character_inspect = character_group.add_parser("inspect", help="inspect every installed version of a package")
    character_inspect.add_argument("package_id")
    character_validate = character_group.add_parser("validate", help="validate a package directory (read-only)")
    character_validate.add_argument("path", type=Path)
    character_import = character_group.add_parser("import", help="IMPORTS a package directory or .zip archive")
    character_import.add_argument("path", type=Path)
    character_select = character_group.add_parser("select", help="SELECTS an installed character package")
    character_select.add_argument("package_id")
    character_select.add_argument("--digest", default=None, help="select one exact installed package digest")
    character_trust = character_group.add_parser(
        "trust", help="SETS a package's trust state (disable or quarantine a package)"
    )
    character_trust.add_argument("package_digest")
    character_trust.add_argument("state", choices=[
        # Only the states a person may assert. `built-in` is a property of
        # where a package came from and `verified-integrity` is a property of
        # its bytes; neither is somebody's opinion, so neither is settable here.
        PackageTrustState.DISABLED.value,
        PackageTrustState.QUARANTINED.value,
        PackageTrustState.IMPORTED_UNVERIFIED.value,
    ])

    renderer = group.add_parser("renderer", help="character renderer diagnostics")
    renderer_group = renderer.add_subparsers(dest="renderer_command", required=True)
    renderer_group.add_parser("status", help="show effective renderer status (read-only)")
    renderer_group.add_parser("explain", help="explain package, plan and fallback selection (read-only)")
    renderer_demo = renderer_group.add_parser("demo", help="RUNS the provider-free renderer demonstration")
    renderer_demo.add_argument("--demo-root", type=Path, default=None)
    # §31's six operations, and no seventh. The name of each subcommand is the
    # operation name with underscores turned into a word, so the CLI cannot
    # reach an operation the table does not carry.
    renderer_3d = group.add_parser(
        "renderer-3d",
        help="3D renderer diagnostics (read-only; six named operations)",
    )
    renderer_3d_group = renderer_3d.add_subparsers(dest="renderer_3d_command", required=True)
    for _name, _help in (
        ("health", "report whether this machine can create a 3D context (read-only)"),
        ("status", "describe a renderer built from the selected package (read-only)"),
        ("model", "describe the validated model descriptor (read-only)"),
        ("metrics", "draw a bounded number of offscreen frames and time them"),
        ("explain", "explain what this machine would draw, and why (read-only)"),
        ("reload", "re-validate and re-upload the selected package"),
    ):
        _parser = renderer_3d_group.add_parser(_name, help=_help)
        _parser.add_argument("--package-id", default=None, help="an installed package id")
        if _name == "metrics":
            _parser.add_argument("--frames", type=int, default=120)
    renderer_demo.add_argument("--performance", action="store_true",
                               help="include development-host microbenchmarks")

    character_slice = group.add_parser(
        "run-character-slice",
        help="RUNS the installed character vertical slice against a real companion service",
    )
    character_slice.add_argument("--slice-root", type=Path, default=None)

    voice_slice = group.add_parser(
        "run-voice-slice",
        help="RUNS the installed voice vertical slice against a real companion service",
    )
    voice_slice.add_argument("--slice-root", type=Path, default=None)

    voice_renderer_slice = group.add_parser(
        "run-voice-renderer-slice",
        help=(
            "RUNS the installed voice-to-renderer slice: voice-produced visemes driving a "
            "real character presenter, with the widget recorded rather than drawn"
        ),
    )
    voice_renderer_slice.add_argument("--slice-root", type=Path, default=None)

    voice_health = group.add_parser(
        "voice-health",
        help="report which local voices and audio backends this machine has (read-only)",
    )
    voice_health.add_argument("--language", default="", help="only voices for this language")

    speech_slice = group.add_parser(
        "run-speech-slice",
        help=(
            "RUNS the installed speech-input vertical slice against a real companion "
            "service: push-to-talk, indicator, capture, recognition, confirmation, one task"
        ),
    )
    speech_slice.add_argument("--slice-root", type=Path, default=None)

    speech_health = group.add_parser(
        "speech-input-health",
        help="report which capture devices and local recognisers this machine has (read-only)",
    )

    agent_slice = group.add_parser(
        "run-agent-slice",
        help=(
            "RUNS the installed agent-provider vertical slice against a real companion "
            "service: local model discovery, one generated task with a mediated tool, "
            "streaming, cancellation mid-stream, a worker restart, no remote dispatch"
        ),
    )
    agent_slice.add_argument("--slice-root", type=Path, default=None)

    agents_health = group.add_parser(
        "agents-health",
        help="report which model providers this machine has, with reasons (read-only)",
    )

    integration = group.add_parser(
        "run-integration-slice",
        help="RUNS the full service-plus-client vertical slice in a scratch directory",
    )
    integration.add_argument("--slice-root", type=Path, default=None)
    integration.add_argument("--no-speech", action="store_true",
                             help="do not attempt the local system voice")

    # -- the Public Alpha surfaces ------------------------------------------
    #
    # Every one of these has a graphical equivalent — the diagnostics window,
    # the first-run wizard, the settings page — because §1 says the normal path
    # needs no terminal. They are here as well because a machine that cannot
    # open a window is exactly when somebody needs them, and because a surface
    # with a command form is a surface a gate can measure.
    group.add_parser("identity", help="the build identity of this system (read-only)")
    group.add_parser(
        "capability-record",
        help="hardware facts and, measured separately, what actually works (read-only)",
    )
    group.add_parser("diagnose", help="the recovery report: what is wrong and what may be pressed")

    export = group.add_parser("export-diagnostics", help="WRITES a diagnostics file. Nothing is uploaded")
    export.add_argument("path", type=Path, nargs="?", default=None,
                        help="where to write; defaults to your Downloads directory")

    safe = group.add_parser("safe-mode", help="inspect or change Bunny Safe Mode")
    safe_group = safe.add_subparsers(dest="safe_command", required=True)
    safe_group.add_parser("status", help="whether the next start is reduced (read-only)")
    safe_on = safe_group.add_parser("on", help="ENABLES safe mode for the next start")
    safe_on.add_argument("--sticky", action="store_true", help="stay in safe mode until turned off")
    safe_on.add_argument("--reason", default="requested from the command line")
    safe_group.add_parser("off", help="DISABLES safe mode, including a sticky one")

    onboarding = group.add_parser(
        "onboarding", help="what the first-run wizard would show on this machine (read-only)",
    )
    onboarding.add_argument("--step", default="", help="one step id, or all of them")

    settings = group.add_parser("settings", help="the user settings surface")
    settings_group = settings.add_subparsers(dest="settings_command", required=True)
    settings_group.add_parser("show", help="print every setting (read-only, never a credential)")
    settings_set = settings_group.add_parser("set", help="CHANGES one setting and persists it")
    settings_set.add_argument("section", choices=(
        "character", "voice", "speechInput", "ai", "privacy", "accessibility",
    ))
    settings_set.add_argument("field")
    settings_set.add_argument("value")

    character_policy = group.add_parser(
        "character-policy",
        help="the default-character decision for this machine; APPLIES it without --dry-run",
    )
    character_policy.add_argument("--dry-run", action="store_true",
                                  help="decide and print, changing nothing")
    character_policy.add_argument("--eligible", default="",
                                  help="override the presentation the machine permits")
    character_policy.add_argument("--restore", action="store_true",
                                  help="RESTORES the package the user chose, when capability permits")


def _assessment(args: argparse.Namespace) -> tuple[Assessment, str]:
    """Build the capability assessment the runtime decides against."""
    try:
        registry = load_registry(getattr(args, "services", None))
        policy = load_policy(getattr(args, "policy", None))
    except (PolicyError, Exception) as exc:  # ManifestError is not exported here
        raise CompanionError(f"the capability configuration could not be read: {exc}") from exc

    if getattr(args, "simulate", None):
        name = args.simulate
        return (
            assess(simulate(name), policy=policy, registry=registry),
            _SIMULATION_BANNER.format(name=name, description=describe(name)),
        )
    if getattr(args, "inventory", None):
        import json

        try:
            document = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
            inventory = inventory_from_json(document)
        except (OSError, ValueError) as exc:
            raise CompanionError(f"{args.inventory} is not a readable capability inventory: {exc}") from exc
        return (
            assess(inventory, policy=policy, registry=registry),
            f"Capability decisions were made against the inventory in {args.inventory}, "
            f"detected {inventory.detected_at}.",
        )
    return assess_current_machine(policy_path=getattr(args, "policy", None)), ""


def build_runtime(args: argparse.Namespace) -> tuple[CompanionRuntime, str]:
    """Assemble the runtime a command will act through.

    One local executor, one local reviewer, the refusing consent source and no
    providers. There is no flag that adds a remote provider, because there is no
    provider adapter in this build to add.
    """
    root = args.root or default_root()
    assessment, banner = _assessment(args)
    options = RuntimeOptions(
        store=CompanionStore(root / "store"),
        assessment=assessment,
        executors=(DeterministicLocalExecutor(),),
        reviewers=(DeterministicLocalReviewer(),),
        broker=ToolBroker(),
        approvals=CompanionApprovalStore.load(root / "approvals.json"),
        consent=RefusingConsent(),
        policy=CoordinationPolicy(),
        clock=SystemClock(),
        ids=RandomIds(),
    )
    return CompanionRuntime(options).start(), banner


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    """Run one companion command and return its document."""
    if args.companion_command == "run-demo":
        return _run_demo(args)
    if args.companion_command == "run-integration-slice":
        return _run_integration_slice(args)
    if args.companion_command == "run-character-slice":
        return _run_character_slice(args)
    if args.companion_command == "run-voice-slice":
        return _run_voice_slice(args)
    if args.companion_command == "run-voice-renderer-slice":
        return _run_voice_renderer_slice(args)
    if args.companion_command == "voice-health":
        return _voice_health(args)
    if args.companion_command == "run-speech-slice":
        return _run_speech_slice(args)
    if args.companion_command == "run-agent-slice":
        return _run_agent_slice(args)
    if args.companion_command == "agents-health":
        return _agents_health(args)
    if args.companion_command == "speech-input-health":
        return _speech_input_health(args)
    if args.companion_command == "character":
        return _character_command(args)
    if args.companion_command == "renderer":
        return _renderer_command(args)
    if args.companion_command == "renderer-3d":
        return _renderer_3d_command(args)
    if args.companion_command == "serve":
        return _serve(args)
    if args.companion_command == "shell":
        return _shell(args)
    if args.companion_command == "migrate-ux-store":
        return _migrate(args)
    if args.companion_command in _ALPHA_COMMANDS:
        return _ALPHA_COMMANDS[args.companion_command](args)
    # `health` and `presentation` can be answered either by a running service —
    # which is the authority while it holds the store — or by reading the store
    # directly. The socket is preferred when one was named or is present: asking
    # the process that is running is always a better answer than asking the
    # files underneath it.
    if args.companion_command in ("health", "presentation"):
        served = _via_socket(args)
        if served is not None:
            return served

    runtime, banner = build_runtime(args)
    try:
        document = _dispatch_with_runtime(runtime, args)
    finally:
        runtime.stop()
    if banner:
        document["simulationBanner"] = banner
    return document


def _dispatch_with_runtime(runtime: CompanionRuntime, args: argparse.Namespace) -> dict[str, Any]:
    command = args.companion_command

    if command == "sessions":
        return {
            "effect": "read-only",
            "sessions": [item.to_json() for item in runtime.sessions()],
        }

    if command == "session":
        return _session_command(runtime, args)

    if command == "task":
        return _task_command(runtime, args)

    if command == "approvals":
        return _approvals_command(runtime, args)

    if command == "health":
        return _health(runtime)

    if command == "presentation":
        return _presentation(runtime, args)

    if command == "recover":
        if args.dry_run:
            return {
                "effect": "read-only",
                "reports": [
                    runtime.store.validate(session_id).to_json()
                    for session_id in runtime.store.session_ids()
                ],
            }
        report = recover(runtime)
        return {
            "effect": (
                f"RECOVERED {len(report.decisions)} task(s) across {len(report.sessions)} session(s); "
                "incomplete tasks were parked or returned to planning and nothing was repeated"
            ),
            **report.to_json(),
        }

    raise CompanionError(f"unknown companion command: {command!r}")


def _session_command(runtime: CompanionRuntime, args: argparse.Namespace) -> dict[str, Any]:
    if args.session_command == "create":
        session = runtime.create_session(
            args.title,
            privacy_policy=PrivacyPolicy(allow_remote=bool(args.allow_remote)),
            cost_policy=CostPolicy(
                task_limit_units=args.task_limit_units,
                session_limit_units=args.session_limit_units,
            ),
            locality_preference=args.locality,
        )
        return {
            "effect": f"CREATED session {session.session_id}",
            "session": session.to_json(),
        }
    if args.session_command == "inspect":
        session = runtime.session(args.session_id)
        return {
            "effect": "read-only",
            "session": session.to_json(),
            "tasks": [task.to_json() for task in runtime.store.tasks(args.session_id)],
            "store": runtime.store.validate(args.session_id).to_json(),
        }
    if args.session_command == "pause":
        session = runtime.pause_session(args.session_id)
        return {"effect": f"PAUSED session {session.session_id}", "session": session.to_json()}
    if args.session_command == "resume":
        session = runtime.resume_session(args.session_id)
        return {"effect": f"RESUMED session {session.session_id}", "session": session.to_json()}
    if args.session_command == "close":
        session = runtime.close_session(args.session_id)
        return {"effect": f"CLOSED session {session.session_id}", "session": session.to_json()}
    raise CompanionError(f"unknown session command: {args.session_command!r}")


def _task_command(runtime: CompanionRuntime, args: argparse.Namespace) -> dict[str, Any]:
    if args.task_command == "submit":
        task = runtime.submit_task(
            args.session_id,
            args.request,
            classification=args.classification,
            cost_limit_units=args.cost_limit_units,
        )
        effect = f"CREATED task {task.task_id}"
        if args.run:
            task = runtime.run_task(args.session_id, task.task_id)
            effect += f" and RAN it to {task.state}"
        return {"effect": effect, "task": task.to_json()}

    if args.task_command == "run":
        session_id, task = runtime.find_task(args.task_id)
        task = runtime.run_task(session_id, task.task_id)
        return {"effect": f"RAN task {task.task_id} to {task.state}", "task": task.to_json()}

    if args.task_command == "inspect":
        session_id, task = runtime.find_task(args.task_id)
        return {
            "effect": "read-only",
            "sessionId": session_id,
            "audience": args.audience,
            "task": task.view(args.audience),
        }

    if args.task_command == "events":
        session_id, task = runtime.find_task(args.task_id)
        events = runtime.events(session_id, task_id=task.task_id)
        return {
            "effect": "read-only",
            "sessionId": session_id,
            "taskId": task.task_id,
            "audience": args.audience,
            "events": [event.view(args.audience) for event in events],
        }

    if args.task_command == "cancel":
        session_id, task = runtime.find_task(args.task_id)
        outcome = cancel_task(
            runtime, session_id, task.task_id, cause=args.cause, detail=args.detail
        )
        return {
            "effect": (
                f"CANCELLED task {task.task_id}; new operations were stopped, "
                f"{len(outcome.withdrawn_approvals)} approval(s) withdrawn and "
                f"{len(outcome.unknown_operations)} operation(s) recorded as unknown"
            ),
            "cancellation": outcome.to_json(),
            "task": outcome.task.to_json(),
        }
    raise CompanionError(f"unknown task command: {args.task_command!r}")


def _approvals_command(runtime: CompanionRuntime, args: argparse.Namespace) -> dict[str, Any]:
    effect = "read-only"
    if args.grant_id:
        runtime.approvals.grant(
            args.grant_id, plan_id=_plan_for(runtime, args.grant_id),
            now=runtime.clock.monotonic(), responder="user",
            detail="granted from the command line",
        )
        effect = (
            f"RECORDED a grant for {args.grant_id}. Note that consent does not survive a "
            "restart: expiry is measured on a monotonic clock, so this grant is expired "
            "when the next process loads the file. It is a record of what you decided, "
            "not a standing permission."
        )
    if args.deny_id:
        runtime.approvals.deny(
            args.deny_id, plan_id=_plan_for(runtime, args.deny_id),
            responder="user", detail="declined from the command line",
        )
        effect = f"RECORDED a denial for {args.deny_id}"
    return {
        "effect": effect,
        "pending": [item.to_json() for item in runtime.approvals.pending()],
        "answered": [
            {"request": runtime.approvals.requests[key].to_json(),
             "response": runtime.approvals.responses[key].to_json()}
            for key in sorted(runtime.approvals.responses)
            if key in runtime.approvals.requests
        ],
        "warnings": list(runtime.approvals.warnings),
    }


def _plan_for(runtime: CompanionRuntime, request_id: str) -> str:
    request = runtime.approvals.requests.get(request_id)
    if request is None:
        raise CompanionError(f"no approval request with id {request_id!r} was raised")
    return request.plan_id


def _health(runtime: CompanionRuntime) -> dict[str, Any]:
    """The runtime's own account of itself, read straight from the store.

    Used when no service is running. It reports the same shape the socket's
    ``health`` returns so a caller does not have to know which answered, with
    ``servedBy`` naming which did — because "the service says it is healthy" and
    "the files look healthy" are different claims.
    """
    from .characters import CharacterError, load_static_character
    from .protocol import PROTOCOL_SCHEMA_VERSION
    from .voice import SystemVoice

    reports = []
    for session_id in runtime.store.session_ids():
        reports.append(runtime.store.validate(session_id).to_json())
    voice = SystemVoice()
    try:
        character = load_static_character()
        character_detail = character.to_json() if character is not None else None
        character_problem = ""
    except CharacterError as exc:
        character_detail = None
        character_problem = str(exc)
    return {
        "effect": "read-only",
        "servedBy": "store",
        "ok": all(item["consistent"] for item in reports),
        "protocolSchemaVersion": PROTOCOL_SCHEMA_VERSION,
        "storeRoot": str(runtime.store.root),
        "sessions": len(reports),
        "storeReports": reports,
        "executors": sorted(runtime._executors),
        "reviewers": list(runtime.reviewer_ids()),
        "approvalWarnings": list(runtime.approvals.warnings),
        "pendingApprovals": [item.request_id for item in runtime.approvals.pending()],
        "voice": voice.describe(),
        "character": character_detail,
        "characterProblem": character_problem,
        "microphoneActive": False,
        "microphonePolicy": "explicit activation only; never at start-up",
        "remoteProviders": [],
    }


def _presentation(runtime: CompanionRuntime, args: argparse.Namespace) -> dict[str, Any]:
    """Fold a task's events into the state a surface would draw."""
    from .presentation import project_presentation

    task_id = getattr(args, "task_id", None)
    session_id = getattr(args, "session_id", None)
    if task_id:
        session_id, task = runtime.find_task(task_id)
        events = runtime.events(session_id, task_id=task.task_id)
    elif session_id:
        events = runtime.events(session_id)
    else:
        identifiers = runtime.store.session_ids()
        if not identifiers:
            return {"effect": "read-only", "servedBy": "store", "state": None,
                    "detail": "this store holds no sessions"}
        session_id = identifiers[-1]
        events = runtime.events(session_id)
    state = project_presentation(events)
    return {
        "effect": "read-only",
        "servedBy": "store",
        "sessionId": session_id,
        "taskId": task_id or state.task_id,
        "state": state.to_json(),
        "events": len(events),
    }


def _via_socket(args: argparse.Namespace) -> dict[str, Any] | None:
    """Ask a running service, or return ``None`` if there is not one.

    A named endpoint that cannot be reached is an error rather than a silent
    fall-through to the store: the caller asked a specific service a question
    and deserves to be told it was not there.
    """
    from .protocol import CompanionClient, CompanionClientError, default_endpoint_path

    named = getattr(args, "endpoint", None)
    endpoint = Path(named) if named else default_endpoint_path()
    if named is None and not endpoint.exists():
        return None
    client = CompanionClient(endpoint, timeout=10.0)
    try:
        if args.companion_command == "health":
            return {"effect": "read-only", "servedBy": "service", **dict(client.health())}
        answer = client.get_presentation_state(
            getattr(args, "task_id", None) or None,
            session_id=getattr(args, "session_id", None) or None,
        )
        return {"effect": "read-only", "servedBy": "service", **dict(answer)}
    except (CompanionClientError, OSError) as exc:
        if named is None:
            # An endpoint file left behind by a service that died. Fall back to
            # reading the store, which is what the user wanted anyway.
            return None
        raise CompanionError(f"the companion service at {endpoint} could not be reached: {exc}") from exc


def _serve(args: argparse.Namespace) -> dict[str, Any]:
    """Run the canonical service. Blocks until stopped, unless ``--once``."""
    from .service import CompanionService, ServiceOptions

    root = args.root or default_root()
    service = CompanionService(ServiceOptions(
        root=root,
        endpoint=args.endpoint,
        machine=getattr(args, "simulate", None),
        recover_on_start=not args.no_recover,
    )).start()
    document = {
        "effect": (
            f"STARTED the canonical companion service on {service.server.describe()['endpoint']}. "
            "It owns the sessions, the tasks and the event stream; clients are views onto it."
        ),
        **service.describe(),
    }
    if args.once:
        service.close()
        document["effect"] += " The endpoint was released immediately because --once was given."
        return document
    try:
        service.serve_forever()
    finally:
        service.close()
    return document


def _shell(args: argparse.Namespace) -> dict[str, Any]:
    """Launch the GTK client. Never a runtime — always a client of one."""
    from .gtk_shell import run as run_shell
    from .presentation import AccessibilityPreferences

    preferences = accessibility_from_environment(prefer_text_only=bool(args.text_only))
    try:
        code = run_shell(args.endpoint, preferences=preferences)
    except RuntimeError as exc:
        raise CompanionError(str(exc)) from exc
    return {
        "effect": "RAN the Bunny Companion window; the runtime it connected to is unaffected by its exit",
        "exitCode": code,
        "preferences": preferences.to_json(),
    }


def _identity(_args: argparse.Namespace) -> dict[str, Any]:
    from .identity import build_identity

    identity = build_identity()
    return {
        "effect": "READ the build identity of this system",
        "identity": identity.to_json(),
        "lines": list(identity.lines()),
    }


def _capability_record(_args: argparse.Namespace) -> dict[str, Any]:
    from .hardware import capability_record

    return {
        "effect": "MEASURED this machine's hardware and, separately, what works on it",
        **capability_record(),
    }


def _diagnose(args: argparse.Namespace) -> dict[str, Any]:
    from .support.diagnose import diagnose

    report = diagnose(root=args.root or default_root())
    return {
        "effect": "READ the recovery report; nothing was changed and nothing was uploaded",
        "report": report.to_json(),
        "lines": list(report.lines()),
    }


def _export_diagnostics(args: argparse.Namespace) -> dict[str, Any]:
    from .support.export import default_destination, export_diagnostics

    root = args.root or default_root()
    destination = args.path or default_destination(root)
    try:
        written = export_diagnostics(destination, root=root)
    except OSError as exc:
        raise CompanionError(f"the diagnostics file could not be written: {exc}") from exc
    return {
        "effect": "WROTE a diagnostics file. It has not been sent anywhere; read it before you share it",
        "path": str(written),
        "uploaded": False,
    }


def _safe_mode(args: argparse.Namespace) -> dict[str, Any]:
    from .support.safemode import clear_safe_mode, read_safe_mode, request_safe_mode

    root = args.root or default_root()
    if args.safe_command == "status":
        state = read_safe_mode(root)
        return {
            "effect": "READ the safe-mode state",
            "safeMode": state.to_json(),
            "lines": list(state.lines()),
        }
    if args.safe_command == "on":
        state = request_safe_mode(
            reason=args.reason, origin="cli", sticky=bool(args.sticky), root=root,
        )
        return {
            "effect": "ENABLED Bunny Safe Mode. It applies to the next start of the companion",
            "safeMode": state.to_json(),
            "lines": list(state.lines()),
        }
    state = clear_safe_mode(root)
    return {
        "effect": "DISABLED Bunny Safe Mode. The next start is a normal one",
        "safeMode": state.to_json(),
    }


def _onboarding(args: argparse.Namespace) -> dict[str, Any]:
    """What the first-run wizard would show, without opening it.

    The gate reads this: a wizard that only exists as a window can only be
    tested by a human looking at one.
    """
    import sys as _sys

    installed = Path("/usr/lib/bunny-installer")
    for candidate in (installed, Path(__file__).resolve().parents[1]):
        if candidate.is_dir() and str(candidate) not in _sys.path:
            _sys.path.append(str(candidate))
    from installer.first_run.alpha import build_model  # noqa: PLC0415

    model = build_model(root=args.root or default_root())
    views = []
    for step in model.steps:
        if args.step and step.step_id != args.step:
            continue
        model.go_to(step.step_id)
        views.append(model.view().to_json())
    if args.step and not views:
        raise CompanionError(f"unknown onboarding step {args.step!r}")
    return {
        "effect": "READ what the first-run experience would show on this machine",
        "steps": views,
        "offlineCompletable": all(
            not view["step"]["required"] or not view["step"]["survey"] for view in views
        ),
    }


def _settings(args: argparse.Namespace) -> dict[str, Any]:
    from .settings import SettingsError, load_settings, update_settings

    root = args.root or default_root()
    if args.settings_command == "show":
        return {
            "effect": "READ the user settings. A setting is never a credential",
            "settings": load_settings(root).to_json(),
        }
    raw = args.value
    value: Any
    if raw.lower() in ("true", "false"):
        value = raw.lower() == "true"
    else:
        try:
            value = int(raw) if raw.lstrip("-").isdigit() else float(raw)
        except ValueError:
            value = raw
    try:
        settings = update_settings(root, args.section, {args.field: value})
    except SettingsError as exc:
        raise CompanionError(str(exc)) from exc
    return {
        "effect": f"CHANGED {args.section}.{args.field} and wrote it to disk",
        "settings": settings.to_json(),
    }


def _character_policy(args: argparse.Namespace) -> dict[str, Any]:
    from .character.defaults import default_character_paths
    from .character.importer import PackageRegistry
    from .character.policy import apply_default_character_policy, restore_selected_package

    root = args.root or default_root()
    registry = PackageRegistry(root / "characters", built_in_paths=default_character_paths())
    eligible = args.eligible
    if not eligible:
        assessment, _banner = _assessment(args)
        eligible = _eligible_from_assessment(assessment)
    if args.restore:
        decision = restore_selected_package(registry, eligible=eligible)
        effect = (
            "RESTORED the character package the user chose"
            if decision.applied else "READ the restore decision; nothing was changed"
        )
    else:
        decision = apply_default_character_policy(
            registry, eligible=eligible, dry_run=bool(args.dry_run),
        )
        effect = (
            "SELECTED the default character package for this machine"
            if decision.applied and not args.dry_run
            else "READ the default-character decision; nothing was changed"
        )
    return {"effect": effect, "eligible": eligible, "decision": decision.to_json()}


def _eligible_from_assessment(assessment: Any) -> str:
    """The presentation the machine permits, from the capability assessment.

    Falls back to measuring the graphics environment when the assessment does
    not carry a companion decision — a machine with no capability plan still has
    a graphics stack, and refusing to choose a character because a plan was
    missing would leave it on whatever the tuple order gave it.
    """
    from .presentation import AccessibilityPreferences, PresentationSignals, select_presentation

    try:
        from .character.three_d.diagnostics import three_d_environment

        environment = three_d_environment()
    except Exception:
        environment = {"windowedThreeDAvailable": False, "graphicalSession": False}
    signals = PresentationSignals(
        gpu_available=bool(environment.get("windowedThreeDAvailable")),
        display_available=bool(environment.get("graphicalSession")),
        headless=not environment.get("graphicalSession"),
    )
    return select_presentation(signals, AccessibilityPreferences()).eligible


#: The Alpha surfaces, dispatched by name. A table rather than another run of
#: ``if`` statements: this dispatcher already had twenty branches and a
#: twenty-first would have been the point at which nobody could see the shape.
_ALPHA_COMMANDS: dict[str, Any] = {
    "identity": _identity,
    "capability-record": _capability_record,
    "diagnose": _diagnose,
    "export-diagnostics": _export_diagnostics,
    "safe-mode": _safe_mode,
    "onboarding": _onboarding,
    "settings": _settings,
    "character-policy": _character_policy,
}


def _migrate(args: argparse.Namespace) -> dict[str, Any]:
    """Inspect, archive or roll back a UX-prototype SQLite store."""
    from .migration import (
        default_donor_paths,
        import_donor_store,
        inspect_donor_store,
        rollback_donor_import,
    )

    root = args.root or default_root()
    if args.rollback:
        outcome = rollback_donor_import(root, name=args.name)
        return {
            "effect": (
                f"REMOVED the donor archive at {outcome['destination']}"
                if outcome["removed"] else "read-only"
            ),
            **outcome,
        }
    source = args.source
    if source is None:
        source = next((item for item in default_donor_paths() if item.is_file()), None)
    if source is None:
        return {
            "effect": "read-only",
            "found": False,
            "searched": [str(item) for item in default_donor_paths()],
            "detail": "no UX-prototype SQLite store was found; there is nothing to migrate",
        }
    inspection = inspect_donor_store(Path(source))
    report = import_donor_store(Path(source), root, name=args.name, dry_run=not args.apply)
    return {
        "effect": (
            f"ARCHIVED {source} under {report.destination}; the canonical event store was not written"
            if report.performed else "read-only (dry run; pass --apply to perform the archive)"
        ),
        "inspection": inspection,
        "report": report.to_json(),
    }


def _run_integration_slice(args: argparse.Namespace) -> dict[str, Any]:
    import tempfile

    from .vertical_slice import SLICE_REQUEST, run_slice

    root = args.slice_root or Path(tempfile.mkdtemp(prefix="bunny-companion-slice-"))
    report = run_slice(root, speak=not args.no_speech)
    return {
        "effect": (
            f"RAN the integrated vertical slice in {root}: a service, a socket, a client, an "
            "approval, two restarts and a replay. No network, provider or credential was used."
        ),
        "root": str(root),
        "request": SLICE_REQUEST,
        **report.to_json(),
    }


def _character_command(args: argparse.Namespace) -> dict[str, Any]:
    """Package diagnostics and selection. Reads unless it says otherwise."""
    root = args.root or default_root()
    registry = character_registry_for(root)
    command = args.character_command
    if command == "list":
        selected = registry.selected()
        return {
            "effect": "read-only",
            "selectedDigest": selected.package_digest if selected else None,
            "packages": [item.to_json() for item in registry.list()],
        }
    if command == "inspect":
        selected = registry.selected()
        packages = []
        for record in registry.inspect(args.package_id):
            trust = (
                PackageTrustState.BUILT_IN
                if record.trust_state is PackageTrustState.BUILT_IN
                else PackageTrustState.VERIFIED_INTEGRITY
            )
            value = record.to_json()
            try:
                validated = validate_package_directory(record.path, trust_state=trust)
                value["validation"] = validated.to_json()
                value["validationError"] = None
            except CharacterError as exc:
                # Reported, not raised: inspecting a set of packages must not
                # stop at the first damaged one, which is precisely the one the
                # user is inspecting them to find.
                value["validation"] = None
                value["validationError"] = {"type": type(exc).__name__, "message": str(exc)}
            value["selected"] = selected is not None and selected.package_digest == record.package_digest
            packages.append(value)
        return {"effect": "read-only", "packageId": args.package_id, "packages": packages}
    if command == "validate":
        package = validate_package_directory(
            args.path, trust_state=PackageTrustState.IMPORTED_UNVERIFIED
        )
        return {
            "effect": "read-only",
            "validation": package.to_json(),
            "manifest": package.manifest.to_json(),
            # Said on every path that reports a successful validation. §4:
            # integrity does not establish creator trust, and the one place a
            # user is most likely to conclude otherwise is the moment they are
            # told the package is valid.
            "warning": "Integrity verification does not establish creator trust.",
        }
    if command == "import":
        record = CharacterPackageImporter(registry).import_package(args.path)
        return {
            "effect": f"IMPORTED character package {record.package_id} without activating it",
            "package": record.to_json(),
            "warning": "The bytes match the manifest; the creator remains untrusted.",
        }
    if command == "select":
        record = registry.select(args.package_id, package_digest=args.digest)
        return {
            "effect": f"SELECTED character package {record.package_id}",
            "package": record.to_json(),
        }
    if command == "trust":
        record = registry.set_trust_state(args.package_digest, PackageTrustState(args.state))
        return {
            "effect": f"SET the trust state of {record.package_digest[:16]} to {args.state}",
            "package": record.to_json(),
        }
    raise CompanionError(f"unknown character command: {command!r}")


def _renderer_command(args: argparse.Namespace) -> dict[str, Any]:
    if args.renderer_command == "demo":
        value = run_diagnostic_demo(args.demo_root, performance=bool(args.performance))
        return {
            "effect": (
                f"RAN the provider-free character renderer demonstration in {value['root']}; "
                "no task record was created and no runtime was started"
            ),
            **value,
        }
    assessment, banner = _assessment(args)
    value = renderer_projection(args.root or default_root(), assessment)
    result: dict[str, Any] = {"effect": "read-only", **value}
    if args.renderer_command == "explain":
        mapped = value.get("mappedState") or {}
        result["explanation"] = {
            "characterState": mapped.get("characterState"),
            "resolvedPackageState": mapped.get("resolvedPackageState"),
            "fallbackChain": mapped.get("fallbackChain", []),
            "priorityReason": mapped.get("priorityReason"),
            "degradationExplanation": mapped.get("degradationExplanation"),
            "trustState": value.get("selectedPackage", {}).get("trustState"),
            "creatorTrusted": value.get("selectedPackage", {}).get("creatorTrusted"),
            "integrityVerified": value.get("selectedPackage", {}).get("integrityVerified"),
            "note": (
                "Integrity verification does not establish creator trust. Every rung of "
                "the presentation ladder is implemented in this build; which one is drawn "
                "is decided by the capability projection and the selected package."
            ),
        }
    if banner:
        result["simulationBanner"] = banner
    return result


def _renderer_3d_command(args: argparse.Namespace) -> dict[str, Any]:
    """Dispatch one §31 operation. The name is built, never taken from input."""
    from .character.three_d.diagnostics import run_operation

    name = f"renderer_3d_{args.renderer_3d_command}"
    frames = getattr(args, "frames", None)
    value = run_operation(
        name,
        root=args.root or default_root(),
        package_id=getattr(args, "package_id", None),
        frames=frames,
    )
    mutating = name == "renderer_3d_reload"
    return {
        "effect": (
            "RELOADED the selected 3D character into a fresh graphics context; "
            "no package on disk was changed"
            if mutating else "read-only"
        ),
        **value,
    }


def _run_character_slice(args: argparse.Namespace) -> dict[str, Any]:
    import tempfile

    from .character.vertical_slice import run_character_slice

    root = args.slice_root or Path(tempfile.mkdtemp(prefix="bunny-character-slice-"))
    report = run_character_slice(root)
    return {
        "effect": (
            f"RAN the installed character vertical slice in {root}: a companion service, a "
            "validated package, an approval, lip-sync, degradation and a renderer restart. "
            "No network, provider or credential was used."
        ),
        "root": str(root),
        **report.to_json(),
    }


def _run_voice_renderer_slice(args: argparse.Namespace) -> dict[str, Any]:
    import tempfile

    from .character.voice_slice import run_voice_renderer_slice

    root = args.slice_root or Path(tempfile.mkdtemp(prefix="bunny-voice-renderer-slice-"))
    report = run_voice_renderer_slice(root)
    return {
        "effect": (
            f"RAN the installed voice-to-renderer slice in {root}: a canonical caption, a "
            "local synthesiser, the worker's own viseme timeline, the lip-sync controller "
            "and the mouth shapes a renderer would have been handed. The pixels need a "
            "display and are proved separately by scripts/gtk_voice_viseme_probe.py; the "
            "steps that need one are reported NOT_RUN here rather than omitted."
        ),
        "root": str(root),
        **report.to_json(),
    }


def _run_speech_slice(args: argparse.Namespace) -> dict[str, Any]:
    import tempfile

    from .speech.vertical_slice import run_speech_slice

    root = args.slice_root or Path(tempfile.mkdtemp(prefix="bunny-speech-slice-"))
    report = run_speech_slice(root)
    return {
        "effect": (
            f"RAN the installed speech-input vertical slice in {root}: a companion service, "
            "push-to-talk over the protocol, the listening indicator, a real capture where "
            "this host has one, recognition, an edited confirmation, exactly one task, a "
            "cancelled second capture, a simulated device loss and a worker restart. No "
            "network or remote provider was used, no audio was retained, and no capture "
            "resumed on its own."
        ),
        "root": str(root),
        **report.to_json(),
    }


def _run_agent_slice(args: argparse.Namespace) -> dict[str, Any]:
    import tempfile

    from .agents.vertical_slice import run_agent_slice

    root = args.slice_root or Path(tempfile.mkdtemp(prefix="bunny-agent-slice-"))
    report = run_agent_slice(root)
    return {
        "effect": (
            f"RAN the installed agent-provider vertical slice in {root}: a companion "
            "service, discovery of a real local model provider, one generated task with "
            "a broker-mediated tool, protocol-visible streaming, the remote option "
            "displayed without dispatching, a cancellation caught mid-stream and a "
            "provider-worker restart. No remote provider was dispatched to, no paid "
            "provider was required, and nothing interrupted was repeated."
        ),
        "root": str(root),
        **report.to_json(),
    }


def _agents_health(args: argparse.Namespace) -> dict[str, Any]:
    """What this machine could generate with. Dispatches nothing.

    Read-only in the sense that matters: probes reach loopback endpoints and
    the trusted model directories, never a remote host, and no generation is
    started.
    """
    import tempfile

    from .agents.service import AgentProviderService, AgentServiceOptions

    root = Path(tempfile.mkdtemp(prefix="bunny-agents-health-"))
    service = AgentProviderService(AgentServiceOptions(root=root, start_worker=False))
    try:
        status = service.providers_status()
    finally:
        service.close()
    return {
        "effect": (
            "REPORTED the configured model providers, their standing ladders and "
            "health; probed loopback endpoints only; started no generation"
        ),
        **status,
    }


def _speech_input_health(args: argparse.Namespace) -> dict[str, Any]:
    """What this machine could listen with. Opens nothing.

    Read-only in the §4 sense that matters: constructing the service opens no
    device and loads no model, and this command asks for health and returns.
    """
    import tempfile

    from .speech.service import SpeechInputService, SpeechInputServiceOptions

    service = SpeechInputService(SpeechInputServiceOptions(
        runtime_directory=Path(tempfile.mkdtemp(prefix="bunny-speech-health-")),
    ))
    try:
        service.refresh()
        return {
            "effect": "read capture and recogniser health; no microphone was opened",
            **service.speech_input_health(),
            "devices": service.speech_input_devices(),
        }
    finally:
        service.close()


def _run_voice_slice(args: argparse.Namespace) -> dict[str, Any]:
    import tempfile

    from .voice.vertical_slice import run_voice_slice

    root = args.slice_root or Path(tempfile.mkdtemp(prefix="bunny-voice-slice-"))
    report = run_voice_slice(root)
    return {
        "effect": (
            f"RAN the installed voice vertical slice in {root}: a companion service, a task, "
            "an approval, a local synthesiser, generic visemes, a cancellation, an audio loss "
            "and a worker restart. No network, remote provider or credential was used, and "
            "nothing about the task was changed by any of it."
        ),
        "root": str(root),
        **report.to_json(),
    }


def _voice_health(args: argparse.Namespace) -> dict[str, Any]:
    """What can speak here, and why anything that cannot, cannot.

    Read-only and cheap: it builds a voice runtime with its worker stopped, asks
    every provider and backend, and closes. A user whose companion has gone
    quiet runs this, and the answer is a list of reasons rather than a silence.
    """
    import tempfile

    from .voice.service import VoiceService, VoiceServiceOptions

    service = VoiceService(VoiceServiceOptions(
        runtime_directory=Path(tempfile.mkdtemp(prefix="bunny-voice-health-")),
        start_worker=False,
    ))
    try:
        health = service.voice_health()
        voices = service.voice_list(language=args.language, limit=64)
        return {
            "effect": "REPORTED the local voice inventory and audio backends. Nothing was spoken.",
            **health,
            "voices": voices,
        }
    finally:
        service.close()


def _run_demo(args: argparse.Namespace) -> dict[str, Any]:
    import tempfile

    root = args.demo_root or Path(tempfile.mkdtemp(prefix="bunny-companion-demo-"))
    report = run_demo(root, grant_approval=not args.refuse_approval)
    return {
        "effect": (
            f"RAN the headless vertical slice in {root}; a session, a task and its whole event "
            "history were written there. No network, provider or credential was used."
        ),
        "root": str(root),
        "request": DEMO_REQUEST,
        "consent": "refused (nobody answered)" if args.refuse_approval else "granted by a scripted stand-in for the user",
        **report.to_json(),
    }
