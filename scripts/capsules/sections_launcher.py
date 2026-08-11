# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Can the process that is supposed to launch a capsule actually launch one?

Every other section in this suite launches capsules from a plain login shell.
That is the right place to measure what a capsule can reach, and it is the wrong
place to measure whether a capsule can be *started*, because in the product
nothing starts one from a login shell. The Companion does, and the Companion is
a systemd user unit with a sandbox of its own.

``bunny-companion.service`` and ``bunny-companion-window.service`` both carry
``RestrictNamespaces=yes``. Bubblewrap's entire mechanism is ``unshare(2)``.
Those two facts had never been put in the same room, and when they were, the
answer was that the Companion could not launch a capsule at all — not on a
degraded host, not intermittently, but always and on every machine.

So this section measures the launch **from inside a unit carrying the shipped
Companion's own properties**, read out of the unit files rather than copied into
this one, so that relaxing a property in the unit relaxes it here too and adding
one is measured without anybody remembering to.

Four shapes, three of which are controls:

``direct``     the argument vector from a plain process. If this fails the host
               cannot run capsules at all and nothing else here means anything.
``permissive`` the same vector nested inside a transient unit with no sandbox
               properties. Separates "nesting broke it" from "the sandbox did".
``hardened``   the same vector nested inside a transient unit carrying the
               Companion's properties. This is the product's real shape.
``manager``    the capsule started as a transient unit of its own, which the
               user manager spawns, so the launcher's seccomp filter and mount
               namespace are not inherited. This is the shape the fix uses.

A section that only ran ``hardened`` could report a failure and not say whether
the cause was the property, the nesting or the machine. Three controls is not
thoroughness for its own sake; it is the difference between a finding and a
guess.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Sequence

from capsules.command import render
from capsules.runtime import _default_command  # noqa: PLC2701 - the runtime's own choice

from .harness import Evidence, Harness, require_confinement

__all__ = ["LAUNCHER_UNITS", "SANDBOX_DIRECTIVES", "section_launcher", "unit_properties"]

_REPOSITORY = Path(__file__).resolve().parents[2]

#: The units that launch capsules in the product. Both, because they carry
#: different properties and either could be the one that starts an application.
LAUNCHER_UNITS = ("bunny-companion.service", "bunny-companion-window.service")

#: The ``[Service]`` directives that can stop a sandbox being built. Everything
#: here is a restriction; none of them is a resource limit or a logging choice,
#: because those cannot refuse a namespace and including them would make the
#: transient unit fail to start for reasons that have nothing to do with the
#: question.
SANDBOX_DIRECTIVES = (
    "CapabilityBoundingSet",
    "LockPersonality",
    "MemoryDenyWriteExecute",
    "NoNewPrivileges",
    "PrivateDevices",
    "PrivateTmp",
    "PrivateUsers",
    "ProtectClock",
    "ProtectControlGroups",
    "ProtectHome",
    "ProtectHostname",
    "ProtectKernelLogs",
    "ProtectKernelModules",
    "ProtectKernelTunables",
    "ProtectProc",
    "ProtectSystem",
    "RestrictAddressFamilies",
    "RestrictNamespaces",
    "RestrictRealtime",
    "RestrictSUIDSGID",
    "SystemCallArchitectures",
    "SystemCallErrorNumber",
    "SystemCallFilter",
)

_DIRECTIVE = re.compile(r"^\s*([A-Za-z]+)\s*=\s*(.*?)\s*$")


def unit_properties(path: Path) -> tuple[str, ...]:
    """The sandboxing directives of a unit file, in the order they appear.

    Read rather than copied. A directive added to the unit and not to this list
    is a directive this section does not test, which is a gap somebody can see;
    a directive copied into this file and later changed in the unit is a section
    that passes for a machine that no longer exists, which is a gap nobody can.
    """
    if not path.is_file():
        return ()
    found: list[str] = []
    section = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1]
            continue
        if section != "Service" or stripped.startswith("#") or not stripped:
            continue
        match = _DIRECTIVE.match(stripped)
        if match and match.group(1) in SANDBOX_DIRECTIVES:
            found.append(f"{match.group(1)}={match.group(2)}")
    return tuple(found)


def _renamed(argv: Sequence[str], suffix: str) -> tuple[str, ...]:
    """The same vector with a distinct unit name.

    The vector names a transient unit derived from the application id, and the
    four shapes run the same application. Without this the second shape collides
    with the first and the collision looks exactly like the sandbox refusing.
    """
    return tuple(
        f"{argument}-{suffix}" if argument.startswith("--unit=") else argument
        for argument in argv
    )


def _nested(argv: Sequence[str], properties: Sequence[str], unit: str) -> tuple[str, ...]:
    """``argv`` run inside a transient unit carrying ``properties``.

    ``--wait`` because the question is what happened to the launch, and a
    fire-and-forget start answers "systemd accepted the job", which is not it.
    ``--collect`` so a failed unit does not stay in the manager and make the next
    shape fail for a reason that is this section's own fault.
    """
    prefix = [
        "systemd-run", "--user", "--wait", "--collect", "--quiet",
        f"--unit={unit}",
        "--property=Type=oneshot",
    ]
    for prop in properties:
        prefix.extend(["--property", prop])
    return tuple(prefix) + tuple(argv)


def _manager_shape(argv: Sequence[str], properties: Sequence[str], unit: str) -> tuple[str, ...]:
    """The capsule asked for as a unit of its own, from inside the hardened unit.

    The outer unit is hardened exactly as before; the difference is that the
    inner command is not forked from it. ``systemd-run`` without ``--scope``
    hands the job to the user manager, which spawns the process itself, so the
    caller's seccomp filter and mount namespace do not reach it.
    """
    inner = " ".join(_shell_quote(argument) for argument in argv)
    request = (
        f"systemd-run --user --wait --collect --quiet --unit={unit}-inner "
        f"--property=Type=oneshot {inner}"
    )
    return _nested(["/bin/sh", "-c", request], properties, f"{unit}-outer")


def _shell_quote(argument: str) -> str:
    """Single-quote for ``sh -c``. The only place in this suite a shell is used.

    It is used because the manager shape is *about* a process asking the manager
    for another process, and there is no way to express that without a command
    that itself runs a command. Every argument is quoted; a vector element
    containing a quote is escaped rather than trusted.
    """
    return "'" + argument.replace("'", "'\\''") + "'"


def _run(argv: Sequence[str], environment: Mapping[str, str], *, timeout: float = 120.0) -> Mapping[str, Any]:
    try:
        completed = subprocess.run(  # noqa: S603 - argv is a list; no shell except the manager shape
            list(argv),
            capture_output=True, text=True, timeout=timeout, check=False,
            env=dict(environment),
        )
    except subprocess.TimeoutExpired:
        return {"ran": True, "exitCode": "TIMEOUT", "started": False, "stderr": ""}
    except OSError as error:
        return {"ran": False, "exitCode": None, "started": False, "stderr": f"{type(error).__name__}: {error}"}
    stderr = (completed.stderr or "").strip()
    return {
        "ran": True,
        "exitCode": completed.returncode,
        "started": completed.returncode == 0,
        # Enough to name the mechanism, not enough to paste a home directory
        # into an evidence file.
        "stderr": stderr[:400],
    }


def _blames_namespaces(outcome: Mapping[str, Any]) -> bool:
    """Whether the failure is the one this section exists to find.

    bwrap says so in as many words when the filter refuses the call, and the
    wording is stable enough to match on. It is a *hint* recorded beside the exit
    code, never the verdict: the verdict is the difference between the shapes.
    """
    text = str(outcome.get("stderr", "")).lower()
    return any(phrase in text for phrase in ("unshare", "namespace", "operation not permitted"))


def section_launcher(harness: Harness, host: Mapping[str, Any]) -> Evidence:
    """Launch one capsule four ways and report which of them a Companion could do."""
    evidence = Evidence(section="launcher")
    if not require_confinement(host, evidence):
        return evidence

    units = {name: unit_properties(_REPOSITORY / "systemd/user" / name) for name in LAUNCHER_UNITS}
    evidence.measurements["units"] = {name: list(props) for name, props in units.items()}
    missing = [name for name, props in units.items() if not props]
    if missing:
        return evidence.settle(
            "BLOCKED",
            f"no sandboxing directives found for {missing}; the unit files are the input to this section",
        )

    capsule = harness.install_probe_app("launcher-probe", "Launcher Probe")
    plan = harness.runtime.build_plan(capsule)
    argv = render(plan, _default_command(capsule.manifest))
    environment = dict(plan.launcher_environment)
    evidence.measurements["backend"] = plan.backend
    evidence.measurements["unshare"] = list(plan.unshare)

    # Per unit rather than as a union. Two units that both set
    # RestrictAddressFamilies= with different lists cannot be merged into one
    # transient unit without inventing a third policy that neither ships, and a
    # failure under an invented policy is attributable to nobody.
    shapes: dict[str, Mapping[str, Any]] = {}
    shapes["direct"] = _run(_renamed(argv, "direct"), environment)
    shapes["permissive"] = _run(
        _nested(_renamed(argv, "permissive"), (), "bunny-launcher-permissive"), environment
    )
    for index, (name, properties) in enumerate(units.items()):
        stem = name.removesuffix(".service").replace("bunny-", "")
        shapes[f"hardened:{name}"] = _run(
            _nested(_renamed(argv, f"h{index}"), properties, f"bunny-launcher-h{index}-{stem}"),
            environment,
        )
        shapes[f"manager:{name}"] = _run(
            _manager_shape(_renamed(argv, f"m{index}"), properties, f"bunny-launcher-m{index}"),
            environment,
        )
    for name, outcome in shapes.items():
        shapes[name] = {**outcome, "blamesNamespaces": _blames_namespaces(outcome)}
    evidence.measurements["shapes"] = shapes

    if not shapes["direct"]["started"]:
        return evidence.settle(
            "BLOCKED",
            f"the capsule could not be launched from a plain process either "
            f"(exit {shapes['direct']['exitCode']}); this host cannot answer the question",
        )
    if not shapes["permissive"]["started"]:
        return evidence.settle(
            "BLOCKED",
            f"nesting alone broke the launch (exit {shapes['permissive']['exitCode']}); "
            f"the hardened shape cannot be attributed to the sandbox properties",
        )

    refused = [name for name in units if not shapes[f"hardened:{name}"]["started"]]
    if refused:
        for name in refused:
            outcome = shapes[f"hardened:{name}"]
            restrict = [p for p in units[name] if p.startswith("RestrictNamespaces=")]
            evidence.findings.append(
                f"{name} cannot launch a capsule: the same vector that succeeds from a plain "
                f"process (exit 0) and from an unhardened transient unit (exit 0) fails inside a "
                f"unit carrying that unit's own properties (exit {outcome['exitCode']}"
                + (", and the error names the namespace call" if outcome["blamesNamespaces"] else "")
                + f"). The directive that does it is {restrict or 'among those listed above'}: "
                f"bubblewrap's mechanism is unshare(2), and the filter is inherited by anything the "
                f"unit forks — including a systemd scope, which is what the renderer produces."
            )
        recovered = [name for name in refused if shapes[f"manager:{name}"]["started"]]
        if recovered:
            evidence.findings.append(
                f"the same capsule started under {recovered} when the user manager spawned it as a "
                f"transient unit instead of a scope forked from the launcher. That is the narrow "
                f"fix, and it is a change of shape rather than a relaxation: the capsule's "
                f"confinement then comes from its own declared plan, which this suite measures, "
                f"rather than from inheriting the launcher's, which nothing did."
            )
        return evidence.settle(
            "FAIL",
            f"the capsule launches from a plain process and from an unhardened unit, and not from "
            f"{refused}; the manager-spawned shape recovered {recovered or 'none of them'}",
        )

    measured = sum(len(props) for props in units.values())
    return evidence.settle(
        "PASS",
        f"the capsule launched in every shape, including inside units carrying {measured} "
        f"sandboxing directives across {len(units)} shipped Companion unit(s)",
    )
