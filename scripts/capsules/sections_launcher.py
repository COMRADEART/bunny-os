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
import sys
import time
from typing import Any, Mapping, Sequence

from capsules.command import render

from .harness import Evidence, Harness, require_confinement

__all__ = [
    "LAUNCHER_UNITS",
    "SANDBOX_DIRECTIVES",
    "UNIT_SEARCH_PATHS",
    "find_unit",
    "section_launcher",
    "unit_properties",
]

_REPOSITORY = Path(__file__).resolve().parents[2]

#: Where to look for a unit, nearest-to-the-running-system first. In a booted
#: guest the answer that matters is the unit *as installed*, not as authored: a
#: directive dropped between the checkout and the image would otherwise be
#: measured from the file that still has it. The checkout is last, so a
#: developer host with no installed units can still answer the question.
UNIT_SEARCH_PATHS = (
    Path("/etc/systemd/user"),
    Path("/usr/lib/systemd/user"),
    Path("/usr/local/lib/systemd/user"),
    _REPOSITORY / "systemd/user",
)

#: The units that launch capsules in the product. Both, because they carry
#: different properties and either could be the one that starts an application.
LAUNCHER_UNITS = ("bunny-companion.service", "bunny-companion-window.service")


def find_unit(name: str) -> Path | None:
    """The first readable copy of ``name``, in :data:`UNIT_SEARCH_PATHS` order."""
    for directory in UNIT_SEARCH_PATHS:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None

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

#: How long to wait for the probe to write its file. The launch is asynchronous
#: now, so this is the only thing there is to wait for.
_PROBE_SECONDS = 60.0

_DIRECTIVE = re.compile(r"^\s*([A-Za-z]+)\s*=\s*(.*?)\s*$")


def unit_properties(path: Path | None) -> tuple[str, ...]:
    """The sandboxing directives of a unit file, in the order they appear.

    Read rather than copied. A directive added to the unit and not to this list
    is a directive this section does not test, which is a gap somebody can see;
    a directive copied into this file and later changed in the unit is a section
    that passes for a machine that no longer exists, which is a gap nobody can.
    """
    if path is None or not path.is_file():
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


def _as_scope(argv: Sequence[str]) -> tuple[str, ...]:
    """The vector the renderer produced *before* the fix: a forked scope.

    This section's own negative control. The renderer now asks the manager for a
    transient service, and under the Companion's properties that works — which
    is the result the section exists to confirm and also exactly what it would
    report if it had quietly stopped being able to detect anything. So the old
    shape is run alongside, and it must still fail: a section in which every
    shape passes cannot tell a fixed system from a broken measurement.
    """
    return tuple(
        argument for argument in _replace_first(argv, "--quiet", ("--scope", "--quiet"))
        if argument != "--collect"
    )


def _replace_first(argv: Sequence[str], needle: str, replacement: Sequence[str]) -> tuple[str, ...]:
    out: list[str] = []
    done = False
    for argument in argv:
        if argument == needle and not done:
            out.extend(replacement)
            done = True
        else:
            out.append(argument)
    return tuple(out)


def _run(argv: Sequence[str], environment: Mapping[str, str], *, timeout: float = 120.0) -> Mapping[str, Any]:
    try:
        completed = subprocess.run(  # noqa: S603 - argv is a list; no shell anywhere
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

    sources = {name: find_unit(name) for name in LAUNCHER_UNITS}
    units = {name: unit_properties(path) for name, path in sources.items() if path is not None}
    evidence.measurements["units"] = {name: list(props) for name, props in units.items()}
    evidence.measurements["unitSources"] = {
        name: str(path) if path is not None else None for name, path in sources.items()
    }
    absent = [name for name, path in sources.items() if path is None]
    if absent:
        return evidence.settle(
            "BLOCKED",
            f"no copy of {absent} under {[str(p) for p in UNIT_SEARCH_PATHS]}; the unit files are "
            f"the input to this section and it will not invent a policy to test",
        )
    bare = [name for name, props in units.items() if not props]
    if bare:
        return evidence.settle(
            "BLOCKED",
            f"{bare} carry no sandboxing directive at all, which is either a unit that lost its "
            f"hardening or a parser that stopped recognising it; neither is a result",
        )

    capsule = harness.install_probe_app("art.comrade.LauncherProbe", "Launcher Probe")
    harness.configure_probe(capsule)
    plan = harness.runtime.build_plan(capsule)
    # The probe, not the manifest's default command. The default for this fixture
    # is a bare interpreter, which reads stdin and never exits, and a shape that
    # hangs is indistinguishable from a shape the sandbox refused.
    argv = render(plan, (sys.executable, "/run/bunny/app/data/probe.py"))
    environment = dict(plan.launcher_environment)
    result_path = capsule.layout.directory("data") / "probe-result.json"
    evidence.measurements["backend"] = plan.backend
    evidence.measurements["unshare"] = list(plan.unshare)

    # Per unit rather than as a union. Two units that both set
    # RestrictAddressFamilies= with different lists cannot be merged into one
    # transient unit without inventing a third policy that neither ships, and a
    # failure under an invented policy is attributable to nobody.
    def shape(vector: Sequence[str]) -> Mapping[str, Any]:
        """Run one shape and say whether the *probe* ran, not whether systemd did.

        A zero from ``systemd-run`` means the manager accepted the job, which a
        job that then started nothing also produces. The file is written from
        inside the sandbox by the process the sandbox was built for, so its
        presence is the only thing here that a failed launch cannot fake.

        The wait is why this is a closure and not a one-liner: asking the manager
        for a transient unit returns as soon as the job is enqueued, so there is
        no exit code to wait on and the file is the only thing to wait for.
        """
        if result_path.exists():
            result_path.unlink()
        outcome = dict(_run(vector, environment))
        deadline = time.monotonic() + _PROBE_SECONDS
        while not result_path.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        outcome["probeWroteResult"] = result_path.exists()
        outcome["secondsWaited"] = round(_PROBE_SECONDS - max(0.0, deadline - time.monotonic()), 1)
        outcome["started"] = bool(outcome["ran"] and outcome["probeWroteResult"])
        outcome["blamesNamespaces"] = _blames_namespaces(outcome)
        return outcome

    shapes: dict[str, Mapping[str, Any]] = {}
    shapes["direct"] = shape(_renamed(argv, "direct"))
    shapes["permissive"] = shape(
        _nested(_renamed(argv, "permissive"), (), "bunny-launcher-permissive")
    )
    for index, (name, properties) in enumerate(units.items()):
        stem = name.removesuffix(".service").replace("bunny-", "")
        shapes[f"hardened:{name}"] = shape(
            _nested(_renamed(argv, f"h{index}"), properties, f"bunny-launcher-h{index}-{stem}")
        )
        # The pre-fix shape, under the same properties. It must still fail, or
        # this section has stopped being able to see the thing it was written
        # for and its PASS above means nothing.
        shapes[f"scope:{name}"] = shape(
            _nested(_as_scope(_renamed(argv, f"s{index}")), properties, f"bunny-launcher-s{index}-{stem}")
        )
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
                f"process and from an unhardened transient unit fails inside a unit carrying that "
                f"unit's own properties (exit {outcome['exitCode']}, probe wrote nothing"
                + (", and the error names the namespace call" if outcome["blamesNamespaces"] else "")
                + f"). Look first at {restrict or 'the directives listed above'}: bubblewrap's "
                f"mechanism is unshare(2), and a seccomp filter is inherited by anything the unit "
                f"forks."
            )
        return evidence.settle(
            "FAIL",
            f"the capsule launches from a plain process and from an unhardened unit, and not from "
            f"{refused}",
        )

    # The regression control. Everything above passing is the intended result and
    # is also what a section that had stopped measuring anything would report.
    still_detected = [name for name in units if not shapes[f"scope:{name}"]["started"]]
    if len(still_detected) != len(units):
        blind = [name for name in units if name not in still_detected]
        evidence.findings.append(
            f"the pre-fix shape — the capsule as a scope forked from the launcher — also started "
            f"under {blind}. That was the defect, so either this machine does not enforce the "
            f"directive the finding rests on, or this section can no longer detect it. Its PASS "
            f"is not evidence either way until that is resolved."
        )
        return evidence.settle(
            "BLOCKED",
            f"every shape started, including the one that must not: the scope shape is this "
            f"section's control and it did not fail under {blind}",
        )

    measured = sum(len(props) for props in units.values())
    return evidence.settle(
        "PASS",
        f"the capsule launched inside units carrying {measured} sandboxing directives across "
        f"{len(units)} shipped Companion unit(s), and the pre-fix scope shape still failed under "
        f"all {len(units)} of them",
    )
