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

Every command accepts ``--simulate <machine>`` and ``--inventory <path>`` so
that a plan can be produced for hardware that is not the machine running the
command. Simulated output is labelled as simulated wherever it appears: a plan
for ``multi-gpu-ai-server`` produced on a laptop is a statement about the policy
engine and must never read as a statement about hardware.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

# Installed layout first, then the source tree, matching bin/bunny-os.
for candidate in (Path("/usr/lib/bunny-os/python"), Path(__file__).resolve().parents[3]):
    if candidate.is_dir() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from capability import explain as explain_module  # noqa: E402
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

    common(commands.add_parser("inspect", help="print the sanitized capability inventory"))
    common(commands.add_parser("scores", help="print the per-dimension capability scores"))
    common(commands.add_parser("budget", help="print the resource budgets"))
    common(commands.add_parser("plan", help="print the execution plan"))
    common(commands.add_parser("status", help="print a one-line-per-service summary"))
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
        if as_json:
            return assessment.plan.to_json()
        return _text(explain_module.render_plan(assessment.plan, assessment.registry), banner)

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
