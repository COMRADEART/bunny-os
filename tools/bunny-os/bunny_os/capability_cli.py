# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The ``bunny-os capability`` command group.

The brief sketches these commands under a ``bunnyctl`` name. This repository's
management CLI is ``bunny-os`` (``tools/bunny-os/bin/bunny-os``), so they are
attached there rather than introducing a second front-end for one subsystem.
The mapping is one-to-one:

    bunnyctl capability inspect        ->  bunny-os capability inspect
    bunnyctl capability scores         ->  bunny-os capability scores
    bunnyctl budget show               ->  bunny-os capability budget
    bunnyctl services plan             ->  bunny-os capability plan
    bunnyctl services explain <id>     ->  bunny-os capability explain <id>
    bunnyctl services status           ->  bunny-os capability status

    bunnyctl plan current              ->  bunny-os capability plan
    bunnyctl plan validate             ->  bunny-os capability plan --validate
    bunnyctl plan diff                 ->  bunny-os capability plan --diff <path>
    bunnyctl plan apply --dry-run      ->  bunny-os capability apply
    bunnyctl reconcile status          ->  bunny-os capability reconcile
    bunnyctl reconcile run --dry-run   ->  bunny-os capability apply
    bunnyctl transitions list          ->  bunny-os capability transitions
    bunnyctl transitions explain <id>  ->  bunny-os capability transitions --explain <id>
    bunnyctl reservations show         ->  bunny-os capability reservations
    bunnyctl monitor status            ->  bunny-os capability monitor

Every command accepts ``--simulate <machine>`` and ``--inventory <path>`` so
that a plan can be produced for hardware that is not the machine running the
command. Simulated output is labelled as simulated wherever it appears: a plan
for ``multi-gpu-ai-server`` produced on a laptop is a statement about the policy
engine and must never read as a statement about hardware.

**Nothing here modifies a host by default.** ``apply`` runs against a dry-run
backend and prints what it would have done. Reaching a real service manager
requires ``--host``, which additionally requires systemd to be present and
refuses outright when the inventory is simulated — a rehearsal against synthetic
hardware must never be able to act on real services. The three modes are
labelled in the output rather than inferred from the flags, so a transcript
cannot be mistaken for the wrong one.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import importlib.util
import sys
from typing import Any

# Installed layout first, then the source tree, matching bin/bunny-os.
# Only when the package is not importable yet.
#
# For a standalone invocation nothing is importable, so this behaves exactly as
# it always has: the installed tree first, the checkout as a fallback.
#
# The guard is for the other case. In a process that already works — a test
# run, another tool that imported this one — the checkout is already on
# ``sys.path``, so the loop skipped it as already-present and inserted the
# *installed* tree in front of it. Every import after that came from whatever
# build happened to be installed, which on a qualification host is a build from
# an earlier phase. It fails loudly when that build is missing a module and
# silently when it is not, and the silent case is a whole test suite passing
# against code nobody changed.
if importlib.util.find_spec("capability") is None:
    for candidate in (Path("/usr/lib/bunny-os/python"), Path(__file__).resolve().parents[3]):
        if candidate.is_dir() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))

from capability import explain as explain_module  # noqa: E402
from capability.apply import applicator as applicator_module  # noqa: E402
from capability.apply import explain as apply_explain  # noqa: E402
from capability.apply.backends import DryRunBackend, InMemoryBackend  # noqa: E402
from capability.apply.identity import PlanIdentity  # noqa: E402
from capability.apply.ledger import InMemoryLedger  # noqa: E402
from capability.apply.monitor import MonitorSettings, RuntimeMonitor, sample_from_inventory  # noqa: E402
from capability.apply.reconcile import reconcile  # noqa: E402
from capability.apply.state import desired_from_plan  # noqa: E402
from capability.apply.systemd import SystemdBackend, authorized_units_for, systemd_available  # noqa: E402
from capability.discovery import DEFAULT_BUDGET_MS  # noqa: E402
from capability.manifest import ManifestError  # noqa: E402
from capability.model import inventory_from_json  # noqa: E402
from capability.policy import PolicyError, load_policy  # noqa: E402
from capability.registry import load_registry  # noqa: E402
from capability.runtime import Assessment, assess, assess_current_machine  # noqa: E402
from capability.simulate import MACHINES, describe, simulate  # noqa: E402

__all__ = ["CapabilityError", "add_arguments", "dispatch"]


class CapabilityError(RuntimeError):
    """Raised when a capability command cannot produce a trustworthy answer."""


_SIMULATION_BANNER = (
    "SIMULATED HARDWARE - {name}: {description}. "
    "This describes the policy engine's decisions for a synthetic inventory. "
    "It is not a measurement of any physical machine."
)


def _assessment(args: argparse.Namespace) -> tuple[Assessment, str]:
    """Build the assessment a command needs, and any banner it must carry."""
    try:
        registry = load_registry(getattr(args, "services", None))
    except ManifestError as exc:
        raise CapabilityError(str(exc)) from exc

    if getattr(args, "simulate", None):
        name = args.simulate
        if name not in MACHINES:
            raise CapabilityError(f"unknown simulated machine {name!r}; known: {', '.join(sorted(MACHINES))}")
        try:
            policy = load_policy(getattr(args, "policy", None))
        except PolicyError as exc:
            raise CapabilityError(str(exc)) from exc
        return (
            assess(simulate(name), policy=policy, registry=registry),
            _SIMULATION_BANNER.format(name=name, description=describe(name)),
        )

    if getattr(args, "inventory", None):
        try:
            document = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
            inventory = inventory_from_json(document)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise CapabilityError(f"{args.inventory} is not a readable capability inventory: {exc}") from exc
        try:
            policy = load_policy(getattr(args, "policy", None))
        except PolicyError as exc:
            raise CapabilityError(str(exc)) from exc
        return (
            assess(inventory, policy=policy, registry=registry),
            f"Inventory loaded from {args.inventory}, detected {inventory.detected_at}. "
            "Decisions below are for that inventory, not for this machine.",
        )

    try:
        return assess_current_machine(
            budget_ms=getattr(args, "budget_ms", DEFAULT_BUDGET_MS),
            policy_path=getattr(args, "policy", None),
            service_directory=getattr(args, "services", None),
        ), ""
    except (PolicyError, ManifestError) as exc:
        raise CapabilityError(str(exc)) from exc


def _text(body: str, banner: str) -> str:
    return f"{banner}\n\n{body}" if banner else body


# --------------------------------------------------------------------------- #
# The applicator commands
# --------------------------------------------------------------------------- #

#: Printed above every applicator command so the mode is stated, never inferred.
_MODE_BANNERS = {
    "simulation": (
        "SIMULATION - the inventory is synthetic and the backend is a model. "
        "No real service was inspected, started or stopped."
    ),
    "dry-run": (
        "DRY RUN - this machine was inspected but not modified. "
        "Every operation below was recorded and not performed."
    ),
    "host": (
        "REAL HOST OPERATION - services on this machine were changed."
    ),
}


def _mode(args: argparse.Namespace, banner: str) -> str:
    """Which of the three modes a command is running in.

    Simulation wins over everything. A ``--host`` flag alongside ``--simulate``
    is a contradiction, and resolving it toward acting on the real machine would
    let a rehearsal against synthetic hardware stop somebody's services.
    """
    if banner or getattr(args, "simulate", None) or getattr(args, "inventory", None):
        return "simulation"
    return "host" if getattr(args, "host", False) else "dry-run"


def _applicator(args: argparse.Namespace, assessment: Assessment, mode: str):
    """Build an applicator whose reach matches the mode, and no further."""
    budget = assessment.budget
    ledger = InMemoryLedger(
        capacity_bytes=budget.currently_allocatable_bytes + budget.essential_services_bytes,
        protected_reserve_bytes=budget.protected_reserve_bytes,
    )

    if mode == "host":
        if not systemd_available():
            raise CapabilityError(
                "--host was requested but /run/systemd/system is absent, so systemd is not the "
                "init system here. Nothing was attempted."
            )
        backend = SystemdBackend(
            authorized_units=authorized_units_for(assessment.registry),
            allow_host_modification=True,
        )
    elif mode == "simulation":
        # A model of a machine, seeded empty. Its transcript is a statement
        # about the applicator, never about hardware.
        backend = InMemoryBackend(name="simulated")
    else:
        # Dry run against the real machine: observe through systemd if it is
        # there, write through nothing. The observer is constructed without the
        # modification opt-in, so even its own mutating methods refuse.
        observer = (
            SystemdBackend(authorized_units=authorized_units_for(assessment.registry))
            if systemd_available() else None
        )
        backend = DryRunBackend(observer=observer)

    return applicator_module.Applicator(
        backend=backend,
        ledger=ledger,
        settings=applicator_module.ApplicatorSettings(dry_run=(mode != "host")),
    )


def _load_plan_identity(path: Path) -> PlanIdentity:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CapabilityError(f"{path} is not a readable execution plan: {exc}") from exc
    identity = document.get("identity") if isinstance(document, dict) else None
    try:
        return PlanIdentity.from_json(identity)
    except (ValueError, TypeError) as exc:
        raise CapabilityError(f"{path} carries no usable plan identity: {exc}") from exc


def _plan_diff(assessment: Assessment, path: Path) -> dict[str, Any]:
    """Compare the current plan against a previously captured one."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CapabilityError(f"{path} is not a readable execution plan: {exc}") from exc

    previous = {
        item.get("serviceId"): item
        for item in document.get("decisions", []) if isinstance(item, dict)
    }
    current = {item["serviceId"]: item for item in assessment.plan.to_json()["decisions"]}

    changes: list[dict[str, Any]] = []
    for service_id in sorted(set(previous) | set(current)):
        before, after = previous.get(service_id), current.get(service_id)
        if before == after:
            continue
        changes.append({
            "serviceId": service_id,
            "before": {
                "action": (before or {}).get("action"),
                "implementationId": (before or {}).get("implementationId"),
                "memoryGrantBytes": (before or {}).get("memoryGrantBytes"),
            } if before else None,
            "after": {
                "action": (after or {}).get("action"),
                "implementationId": (after or {}).get("implementationId"),
                "memoryGrantBytes": (after or {}).get("memoryGrantBytes"),
            } if after else None,
        })

    previous_identity = document.get("identity") if isinstance(document, dict) else None
    return {
        "schemaVersion": 1,
        "previousPlanId": (previous_identity or {}).get("planId"),
        "currentPlanId": assessment.plan.plan_id,
        "sameDesiredState": (
            bool(previous_identity)
            and (previous_identity or {}).get("contentDigest")
            == (assessment.plan.identity.content_digest if assessment.plan.identity else None)
        ),
        "changes": changes,
    }


def add_arguments(subparsers: Any) -> None:
    """Attach the ``capability`` command group to the bunny-os CLI."""
    group = subparsers.add_parser("capability", help="hardware capability, budgets and the execution plan")
    commands = group.add_subparsers(dest="capability_command", required=True)

    def common(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        parser.add_argument(
            "--simulate", metavar="MACHINE",
            help="assess a simulated machine instead of this one (" + ", ".join(sorted(MACHINES)) + ")",
        )
        parser.add_argument("--inventory", type=Path, help="assess a previously captured inventory document")
        parser.add_argument("--policy", type=Path, help="read policy from this file instead of /etc/bunny-os")
        parser.add_argument("--services", type=Path, help="read service manifests from this directory")
        parser.add_argument(
            "--budget-ms", type=int, default=DEFAULT_BUDGET_MS,
            help=f"wall-clock budget for hardware discovery (default {DEFAULT_BUDGET_MS})",
        )
        return parser

    def host_flag(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        """The one flag that lets a command reach a real service manager.

        Named ``--host`` rather than ``--no-dry-run`` so that what it does is
        legible in a shell history, and defaulted off so that the dangerous
        mode is the one that has to be typed.
        """
        parser.add_argument(
            "--host", action="store_true",
            help="operate real services on this machine (requires systemd; refused with --simulate)",
        )
        return parser

    common(commands.add_parser("inspect", help="print the sanitized capability inventory"))
    common(commands.add_parser("scores", help="print the per-dimension capability scores"))
    common(commands.add_parser("budget", help="print the resource budgets"))
    plan = common(commands.add_parser("plan", help="print the execution plan"))
    plan.add_argument(
        "--validate", action="store_true",
        help="check that the plan may still be applied, and print every check",
    )
    plan.add_argument(
        "--diff", type=Path, metavar="PLAN",
        help="compare this plan against a previously captured execution plan document",
    )
    common(commands.add_parser("status", help="print a one-line-per-service summary"))
    common(commands.add_parser(
        "reconcile", help="show the difference between the plan and what is running",
    ))
    apply_parser = host_flag(common(commands.add_parser(
        "apply", help="apply the plan (dry run unless --host is given)",
    )))
    apply_parser.add_argument(
        "--allow-essential-stop", action="store_true",
        help="permit stopping an essential service, which the applicator otherwise refuses",
    )
    transitions = common(commands.add_parser(
        "transitions", help="list the transitions of the last apply, or explain one",
    ))
    transitions.add_argument("--explain", metavar="TRANSITION_ID", help="explain one transition in full")
    host_flag(transitions)
    common(commands.add_parser("reservations", help="print the resource reservation ledger"))
    common(commands.add_parser("monitor", help="print the runtime monitor's state and thresholds"))
    explain = common(commands.add_parser("explain", help="explain one service's decision"))
    explain.add_argument("service_id", help="the service to explain, e.g. bunny.companion")
    common(commands.add_parser("policy", help="print the effective policy and where it came from"))
    commands.add_parser("machines", help="list the simulated machines available to --simulate")


def dispatch(args: argparse.Namespace) -> Any:
    """Handle a ``capability`` subcommand, returning the value to emit."""
    command = args.capability_command
    as_json = bool(getattr(args, "json", False))

    if command == "machines":
        value = {
            "schemaVersion": 1,
            "note": "These are synthetic inventories for testing policy. None describes real hardware.",
            "machines": [{"name": name, "description": describe(name)} for name in sorted(MACHINES)],
        }
        if as_json:
            return value
        lines = ["Simulated machines (synthetic inventories; none describes real hardware)", ""]
        lines.extend(f"  {name:24} {describe(name)}" for name in sorted(MACHINES))
        return "\n".join(lines)

    assessment, banner = _assessment(args)

    if command == "inspect":
        if as_json:
            document = assessment.inventory.to_json()
            if banner:
                document["simulationNotice"] = banner
            return document
        return _text(explain_module.render_inventory(assessment.inventory), banner)

    if command == "scores":
        if as_json:
            return assessment.scores.to_json()
        return _text(explain_module.render_scores(assessment.scores), banner)

    if command == "budget":
        if as_json:
            return assessment.budget.to_json()
        return _text(explain_module.render_budget(assessment.budget), banner)

    if command == "plan":
        if getattr(args, "diff", None):
            difference = _plan_diff(assessment, args.diff)
            if as_json:
                return difference
            lines = [
                f"Plan {difference['previousPlanId'] or 'unknown'} -> {difference['currentPlanId']}",
                "",
            ]
            if difference["sameDesiredState"]:
                lines.append("  Both plans describe the same desired state; nothing would change.")
            elif not difference["changes"]:
                lines.append("  No service decision differs.")
            for change in difference["changes"]:
                before = change["before"] or {}
                after = change["after"] or {}
                lines.append(
                    f"  {change['serviceId']:26} {before.get('action', '-'):<13} -> {after.get('action', '-')}"
                )
                if before.get("implementationId") != after.get("implementationId"):
                    lines.append(
                        f"  {'':26} implementation {before.get('implementationId')} -> "
                        f"{after.get('implementationId')}"
                    )
            return _text("\n".join(lines), banner)

        if getattr(args, "validate", False):
            from capability.apply import SUPPORTED_PLAN_SCHEMA_VERSION
            from capability.apply.revalidate import revalidate_plan

            verdict = revalidate_plan(
                assessment.plan.identity,
                inventory=assessment.inventory, budget=assessment.budget,
                policy=assessment.policy, registry=assessment.registry,
                now=0.0, in_force=None,
                supported_schema_version=SUPPORTED_PLAN_SCHEMA_VERSION,
            )
            if as_json:
                return {"schemaVersion": 1, "planId": assessment.plan.plan_id, **verdict.to_json()}
            lines = [
                f"Plan {assessment.plan.plan_id} "
                + ("may be applied." if verdict.ok else "must NOT be applied."),
                "",
                "Checks:",
            ]
            for check in verdict.checked:
                mark = {True: "ok  ", False: "FAIL", None: "?   "}.get(check.get("satisfied"), "?   ")
                lines.append(f"  {mark} {check['check']}: required {check['required']}, measured {check['measured']}")
            if verdict.problems:
                lines.extend(["", "Problems:"])
                lines.extend(f"  - {problem}" for problem in verdict.problems)
            return _text("\n".join(lines), banner)

        if as_json:
            return assessment.plan.to_json()
        return _text(explain_module.render_plan(assessment.plan, assessment.registry), banner)

    if command in ("reconcile", "apply", "transitions", "reservations", "monitor"):
        return _runtime_command(args, assessment, banner, as_json)

    if command == "status":
        rows = []
        for decision in assessment.plan.decisions:
            service = assessment.registry.get(decision.service_id)
            rows.append({
                "serviceId": decision.service_id,
                "essential": bool(service and service.essential),
                "action": decision.action,
                "implementationId": decision.implementation_id,
                "memoryGrantBytes": decision.memory_grant_bytes,
                "primaryReason": decision.reasons[-1].message if decision.reasons else "",
            })
        if as_json:
            return {"schemaVersion": 1, "services": rows}
        width = max((len(row["serviceId"]) for row in rows), default=10)
        lines = [f"  {'service':{width}}  {'action':<13} {'implementation':<22} reason"]
        for row in rows:
            lines.append(
                f"  {row['serviceId']:{width}}  {row['action']:<13} "
                f"{(row['implementationId'] or '-'):<22} {row['primaryReason'][:70]}"
            )
        return _text("\n".join(lines), banner)

    if command == "policy":
        document = assessment.policy.to_json()
        if as_json:
            return document
        lines = [f"Effective policy (from {assessment.policy.source})", ""]
        lines.extend(
            f"  {key:28} {json.dumps(value) if isinstance(value, (dict, list)) else value}"
            for key, value in document.items() if key not in ("schemaVersion", "warnings", "source")
        )
        if assessment.policy.warnings:
            lines.extend(["", "Warnings:"])
            lines.extend(f"  - {warning}" for warning in assessment.policy.warnings)
        return _text("\n".join(lines), banner)

    if command == "explain":
        decision = assessment.plan.decision(args.service_id)
        if decision is None:
            known = ", ".join(sorted(assessment.registry.services))
            raise CapabilityError(f"no service {args.service_id!r} is declared; known services: {known}")
        if as_json:
            document = decision.to_json()
            document["service"] = (
                assessment.registry.get(args.service_id).to_json()
                if assessment.registry.get(args.service_id) else None
            )
            return document
        return _text(
            explain_module.render_service(decision, assessment.registry, assessment.budget, assessment.inventory),
            banner,
        )

    raise CapabilityError(f"unhandled capability command {command!r}")


def _runtime_command(
    args: argparse.Namespace, assessment: Assessment, banner: str, as_json: bool,
) -> Any:
    """The applicator-facing commands, all of which share one setup.

    Every one of them needs the same four things: a mode, an applicator scoped
    to that mode, an observation of the machine, and the desired state derived
    from the plan. Building them once here is what stops ``reconcile`` and
    ``apply`` from ever disagreeing about what the machine looks like.
    """
    command = args.capability_command
    mode = _mode(args, banner)
    if mode == "simulation" and getattr(args, "host", False):
        raise CapabilityError(
            "--host cannot be combined with --simulate or --inventory. A rehearsal against "
            "synthetic hardware must not be able to act on real services."
        )

    mode_banner = _MODE_BANNERS[mode]
    full_banner = f"{banner}\n\n{mode_banner}" if banner else mode_banner

    if command == "monitor":
        monitor = RuntimeMonitor(settings=MonitorSettings(
            interval_seconds=assessment.policy.monitor_interval_seconds,
        ))
        # One sample, so the output shows real readings against real thresholds
        # rather than an empty table of configured numbers.
        monitor.observe(sample_from_inventory(assessment.inventory, at_monotonic=0.0))
        status = monitor.status()
        if as_json:
            return {"schemaVersion": 1, **status}
        lines = [
            f"Runtime monitor, sampling every {status['settings']['intervalSeconds']:g}s", "",
            "  Signals (entry / recovery thresholds form the hysteresis band):",
        ]
        for signal in status["settings"]["signals"]:
            state = next((item for item in status["signals"] if item["signal"] == signal["signal"]), None)
            reading = "unmeasured" if state is None or state["lastValue"] is None else f"{state['lastValue']:.3g}"
            lines.append(
                f"    {signal['signal']:28} {reading:>12}   enter {signal['enterThreshold']:g} / "
                f"leave {signal['leaveThreshold']:g}   debounce {signal['debounceSeconds']:g}s   "
                f"cooldown {signal['cooldownSeconds']:g}s"
            )
        lines.extend([
            "",
            "  A signal must cross its entry threshold and hold for the debounce period before an",
            "  event is raised, and the same event cannot repeat inside its cooldown. Unmeasured",
            "  signals raise nothing: a reading that was never taken is not a reading of zero.",
        ])
        return _text("\n".join(lines), full_banner)

    applicator = _applicator(args, assessment, mode)
    if getattr(args, "allow_essential_stop", False):
        applicator.settings = applicator_module.ApplicatorSettings(
            dry_run=applicator.settings.dry_run, allow_essential_stop=True,
        )

    if command == "reservations":
        # Reservations only exist once something has been applied, so this runs
        # a pass first. In every mode but --host that pass changes nothing.
        applicator.apply(
            assessment.plan, registry=assessment.registry, inventory=assessment.inventory,
            budget=assessment.budget, policy=assessment.policy, now=0.0,
        )
        document = applicator.ledger.to_json()
        if as_json:
            return document
        lines = [
            "Resource reservation ledger", "",
            f"  capacity            {explain_module.format_bytes(document['capacityBytes'])}",
            f"  protected reserve   {explain_module.format_bytes(document['protectedReserveBytes'])}"
            "  (already excluded from capacity)",
            f"  outstanding         {explain_module.format_bytes(document['outstandingBytes'])}",
            f"  committed           {explain_module.format_bytes(document['committedBytes'])}",
            f"  available           {explain_module.format_bytes(document['availableBytes'])}",
            "",
        ]
        if document["reservations"]:
            lines.append("  Reservations:")
            for entry in document["reservations"]:
                lines.append(
                    f"    {entry['serviceId']:26} {entry['state']:<10} "
                    f"{explain_module.format_bytes(entry['outstanding']):>10}   {entry['reservationId']}"
                )
        else:
            lines.append("  No reservation is held.")
        return _text("\n".join(lines), full_banner)

    actual = applicator.observe(assessment.registry, now=0.0)

    if command == "reconcile":
        desired = desired_from_plan(assessment.plan, assessment.registry)
        settings = applicator._reconciliation_settings(desired, actual, assessment.budget, 0.0)
        result = reconcile(desired, actual, settings=settings, now=0.0)
        if as_json:
            return {"schemaVersion": 1, "mode": mode, **result.to_json()}
        return _text(apply_explain.render_reconciliation(result), full_banner)

    report = applicator.apply(
        assessment.plan, registry=assessment.registry, inventory=assessment.inventory,
        budget=assessment.budget, policy=assessment.policy, now=0.0, actual=actual,
    )

    if command == "apply":
        if as_json:
            return {"schemaVersion": 1, "mode": mode, **report.to_json()}
        return _text(apply_explain.render_report(report), full_banner)

    if command == "transitions":
        wanted = getattr(args, "explain", None)
        if wanted:
            match = next((item for item in report.applied if item.transition_id == wanted), None)
            if match is None:
                known = ", ".join(item.transition_id for item in report.applied) or "none"
                raise CapabilityError(
                    f"no transition {wanted!r} in the last pass; transitions in this pass: {known}"
                )
            if as_json:
                return match.to_json()
            manifest = assessment.registry.get(match.service_id)
            return _text(
                apply_explain.render_transition(
                    match, service_title=manifest.title if manifest else "",
                ),
                full_banner,
            )

        if as_json:
            return {
                "schemaVersion": 1,
                "mode": mode,
                "planId": report.plan_id,
                "transitions": [item.to_json() for item in report.applied],
                "blocked": [item.to_json() for item in report.blocked],
            }
        if not report.applied and not report.blocked:
            return _text("No transition was needed; the machine matches the plan.", full_banner)
        lines = ["Transitions", ""]
        for item in report.applied:
            outcome = item.result.result if item.result is not None else "pending"
            lines.append(
                f"  {item.sequence:>2}. {item.service_id:26} {item.operation:<12} {outcome:<11} "
                f"{item.transition_id}"
            )
        if report.blocked:
            lines.extend(["", "Not attempted:"])
            for item in report.blocked:
                lines.append(f"  {item.service_id:26} {item.reason}")
        lines.extend([
            "",
            "Run 'bunny-os capability transitions --explain <transition-id>' for any line above.",
        ])
        return _text("\n".join(lines), full_banner)

    raise CapabilityError(f"unhandled runtime command {command!r}")
