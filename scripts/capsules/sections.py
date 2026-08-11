# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The qualification sections: each one a question the host is asked directly.

A section takes a live :class:`~scripts.capsules.harness.Harness` and returns an
:class:`~scripts.capsules.harness.Evidence` record. It never prints a verdict it
did not derive from a measurement, and it never returns ``PASS`` for something it
could not run — ``BLOCKED`` exists for that and is used.

The sections are independent on purpose. A partial run is legible as a partial
run, and a section that fails does not prevent the others from producing their
own answers.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Mapping

import capsules
import trust
from trust.gate import TrustGate
from trust.store import TrustStore

from .harness import Evidence, Harness, _by_check, compare, require_confinement

__all__ = [
    "SECTIONS",
    "section_crash",
    "section_crossapp",
    "section_failclosed",
    "section_filegrant",
    "section_host",
    "section_isolation",
    "section_launcher",
    "section_network",
    "section_resources",
    "section_selinux",
]


def section_host(harness: Harness | None, host: Mapping[str, Any]) -> Evidence:
    """What this machine is, and whether it can answer the other sections."""
    evidence = Evidence(section="host")
    evidence.measurements = dict(host)
    backends = [name for name in host.get("availableBackends", []) if name != "systemd-scope"]
    if host.get("isRoot"):
        return evidence.settle("BLOCKED", "running as root; the sandbox under test is the unprivileged one")
    if not backends:
        return evidence.settle("BLOCKED", "no confining backend on this host")

    note = f"confining backends: {backends}"
    programs = host.get("machineProbe", {}).get("programs", [])
    absent = [name for name in ("flatpak",) if name not in programs]
    if absent:
        note += f"; absent, so its backend is NOT_RUN rather than PASS: {absent}"
        evidence.findings.append(
            f"{absent} is not installed on this host. Every result below is the bubblewrap "
            "backend only; the Flatpak backend has not been exercised."
        )
    if str(host.get("selinux", "")).strip().lower() in ("disabled", "", "unknown"):
        note += "; SELinux is not enforcing"
        evidence.findings.append(
            "SELinux is Disabled on this host. The capsule design treats SELinux as one layer "
            "among namespaces, cgroups, portals and Polkit; every isolation result recorded here "
            "is the namespace and cgroup layer alone, and none of it is evidence about SELinux."
        )
    if str(host.get("virtualization", "")).strip() == "wsl":
        evidence.findings.append(
            "The host is WSL2. Its kernel is Microsoft's, not Fedora's stock kernel, so a "
            "namespace or cgroup behaviour measured here should be re-measured on the shipped "
            "kernel before it is called a property of Bunny OS."
        )
    return evidence.settle("PASS", note)


def section_isolation(harness: Harness, host: Mapping[str, Any]) -> Evidence:
    """One capsule, one probe, one negative control."""
    evidence = Evidence(section="isolation")
    if not require_confinement(host, evidence):
        return evidence

    # Fixtures first. Without them the control cannot read ~/.ssh either, every
    # credential row is INCONCLUSIVE, and the run proves nothing about the thing
    # it most needs to prove.
    seeded = harness.seed_credentials()
    capsule = harness.install_probe_app("art.comrade.ProbeA", "Probe A")
    (capsule.layout.directory("data") / "own-marker.txt").write_text("A's own data\n", encoding="utf-8")
    neighbour = harness.home / "Pictures" / "neighbour.png"
    neighbour.write_bytes(b"NEIGHBOUR")
    parameters = {
        "BUNNY_PROBE_NEIGHBOUR_FILE": str(neighbour),
        "BUNNY_PROBE_CAPSULE_ROOT": str(harness.runtime.root),
        # A *file*, not a directory: reading a directory fails for a reason that
        # has nothing to do with the sandbox, so the control would report ABSENT
        # and the row would tell us nothing.
        "BUNNY_PROBE_SYMLINK_TARGET": str(seeded[".ssh"]),
    }
    with harness.listening_socket() as port:
        parameters["BUNNY_PROBE_LOCALHOST_PORT"] = str(port)
        harness.configure_probe(capsule, **parameters)
        inside = harness.run_probe(capsule)
        outside = harness.run_control(capsule, **parameters)
    comparison = compare(inside.get("probe", {}), outside.get("probe", {}))
    evidence.measurements = {"capsule": inside, "control": outside, "comparison": comparison}

    if not inside.get("probe"):
        return evidence.settle(
            "FAIL", f"the probe produced no result inside the capsule; exit={inside.get('exitCode')!r}"
        )
    if not outside.get("probe"):
        return evidence.settle("BLOCKED", "the negative control produced no result")
    if not comparison["controlProvedSomething"]:
        return evidence.settle(
            "BLOCKED",
            "the control reached nothing the capsule could not; this run cannot tell isolation "
            "from an absent resource",
        )
    if comparison["widerInside"]:
        evidence.findings.append(f"reachable inside and not outside: {comparison['widerInside']}")
        return evidence.settle("FAIL", "the capsule reached something the unconfined control could not")

    #: The checks whose availability inside a capsule is a stop condition. Named
    #: rather than derived, so adding a probe check cannot silently widen what
    #: this section is willing to accept.
    must_be_denied = (
        "home_read", "ssh_read", "ssh_key_read", "gnupg_read", "browser_profile_read",
        "other_capsule_enumerate", "neighbour_file_read", "write_outside_home",
        "traversal_etc_passwd", "symlink_escape_home",
    )
    rows = {row["check"]: row for row in comparison["rows"]}
    leaked = sorted(name for name in must_be_denied if rows.get(name, {}).get("capsule") == "AVAILABLE")
    if leaked:
        evidence.findings.append(f"STOP CONDITION: reachable from inside the capsule: {leaked}")
        return evidence.settle("FAIL", f"the capsule reached {leaked}")

    # Positive controls. A sandbox that denied everything would pass every row
    # above and be useless, so the capsule is also required to reach the things
    # it is supposed to reach.
    capsule_checks = _by_check(inside["probe"])
    positive = {
        "own_data_read": "a capsule could not read its own private data",
        "own_data_write": "a capsule could not write its own private data",
        "subprocess": "a capsule could not start a subprocess",
        "tmp": "a capsule had no usable /tmp",
    }
    broken = [message for name, message in positive.items() if capsule_checks.get(name, {}).get("result") != "AVAILABLE"]
    if broken:
        evidence.findings.extend(broken)
        return evidence.settle("FAIL", "; ".join(broken))

    # Three checks are AVAILABLE in both environments and say nothing until the
    # *contents* are compared. A capsule that can read /proc/self/mountinfo is
    # not a problem; a capsule that can see the host's mounts is.
    control_checks = _by_check(outside["probe"])
    structural = _structural(capsule_checks, control_checks, harness.runtime.build_plan(capsule))
    evidence.measurements["structural"] = structural
    for problem in structural["problems"]:
        evidence.findings.append(problem)
    if structural["problems"]:
        return evidence.settle("FAIL", "; ".join(structural["problems"]))

    inconclusive = sorted(
        name for name in must_be_denied if rows.get(name, {}).get("verdict") == "INCONCLUSIVE"
    )
    note = (
        f"{comparison['isolatedCount']} checks isolated, each reached by the control; "
        f"mounts {structural['mounts']['inside']} inside against {structural['mounts']['outside']} outside, "
        f"all under {structural['mounts']['allowedPrefixes']}; "
        f"processes {structural['processes']['inside']} against {structural['processes']['outside']}; "
        f"environment exactly the {structural['environment']['declared']} the plan declares"
    )
    if inconclusive:
        note += f"; inconclusive: {inconclusive}"
        evidence.findings.append(
            f"no conclusion available for {inconclusive}: absent on this host rather than denied"
        )
    return evidence.settle("PASS", note)


def _structural(
    inside: Mapping[str, Mapping[str, Any]],
    outside: Mapping[str, Mapping[str, Any]],
    plan: Any,
) -> dict[str, Any]:
    """What the capsule could see, checked against what the plan said it would.

    Counting was the first attempt and it was the wrong shape: a ceiling on the
    number of mounts is a magic number that fails when a bind is added and passes
    when the wrong thing is mounted. These are the properties instead.

    **Every mount point inside is one Bunny asked for.** Compared against a
    prefix set derived from the plan, so adding a bind cannot break this check
    and mounting the user's home would.

    **The environment is exactly what the plan declared**, plus two named
    exceptions that are not leaks and are named rather than tolerated: the
    probe's own ``BUNNY_PROBE_*`` configuration, which the probe itself puts
    there, and ``PWD``, which bwrap sets from ``--chdir``. Anything else that the
    unconfined control also had is a variable that crossed the boundary.

    **The process table is the capsule's own.** A PID namespace that was not
    applied shows up here as the host's process count.
    """
    problems: list[str] = []

    def data(source: Mapping[str, Mapping[str, Any]], check: str) -> Mapping[str, Any]:
        return source.get(check, {}).get("data", {}) or {}

    inside_mounts = data(inside, "mounts")
    outside_mounts = data(outside, "mounts")
    allowed_prefixes = sorted({"/", "/dev", "/proc", "/tmp", "/usr"} | {
        bind.target.rstrip("/") or "/" for bind in plan.binds
    })
    unexpected = [
        point for point in inside_mounts.get("points", [])
        if not any(point == prefix or point.startswith(prefix.rstrip("/") + "/") for prefix in allowed_prefixes)
    ]
    if unexpected:
        problems.append(f"mount points the plan never asked for: {unexpected}")

    inside_environment = set(data(inside, "environment").get("keys", []))
    outside_environment = set(data(outside, "environment").get("keys", []))
    declared = set(plan.environment)
    permitted = declared | {"PWD"} | {key for key in inside_environment if key.startswith("BUNNY_PROBE_")}
    crossed = sorted((inside_environment - permitted) & outside_environment)
    if crossed:
        problems.append(f"environment variables crossed the sandbox boundary: {crossed}")
    missing = sorted(declared - inside_environment)
    if missing:
        problems.append(f"the plan declared variables the capsule did not receive: {missing}")
    dangerous = data(inside, "environment").get("dangerous", [])
    if dangerous:
        problems.append(f"dangerous environment variables reached the capsule: {dangerous}")

    inside_processes = data(inside, "process_visibility").get("visible")
    outside_processes = data(outside, "process_visibility").get("visible")
    if isinstance(inside_processes, int) and isinstance(outside_processes, int):
        if inside_processes >= outside_processes:
            problems.append(
                f"the capsule saw {inside_processes} processes and the control saw "
                f"{outside_processes}; the PID namespace did not apply"
            )

    return {
        "mounts": {
            "inside": inside_mounts.get("count"),
            "outside": outside_mounts.get("count"),
            "points": inside_mounts.get("points", []),
            "allowedPrefixes": allowed_prefixes,
            "unexpected": unexpected,
        },
        "environment": {
            "declared": sorted(declared),
            "inside": sorted(inside_environment),
            "crossed": crossed,
            "dangerous": dangerous,
        },
        "processes": {"inside": inside_processes, "outside": outside_processes},
        "problems": problems,
    }


def section_crossapp(harness: Harness, host: Mapping[str, Any]) -> Evidence:
    """Two capsules, a secret marker, and one authorised transfer."""
    evidence = Evidence(section="crossapp")
    if not require_confinement(host, evidence):
        return evidence

    app_a = harness.install_probe_app("art.comrade.ProbeA", "Probe A")
    secret = app_a.layout.directory("data") / "a-secret.txt"
    secret.write_text("MARKER-c0ffee-A-PRIVATE\n", encoding="utf-8")

    app_b = harness.install_probe_app("art.comrade.ProbeB", "Probe B")
    (app_b.layout.directory("data") / "own-marker.txt").write_text("B's own data\n", encoding="utf-8")
    parameters = {
        "BUNNY_PROBE_PEER_SECRET": str(secret),
        "BUNNY_PROBE_CAPSULE_ROOT": str(harness.runtime.root),
    }
    harness.configure_probe(app_b, **parameters)
    before = harness.run_probe(app_b)

    # One authorised transfer. A puts an artefact in its exports directory, Bunny
    # copies it to a folder the user keeps files in, and B is granted that one
    # file. A's private directory is never mounted anywhere.
    artefact = app_a.layout.directory("exports") / "shared-result.txt"
    artefact.write_text("EXPORTED-BY-A\n", encoding="utf-8")
    export = capsules.export_artifact(
        app_a.layout, "shared-result.txt",
        destination_root=harness.home / "Documents",
        capsule_root=harness.runtime.root, home=harness.home,
    )
    harness.surface.answers = (("files", "allow", "always"),)
    decision = harness.runtime.request_permission(
        harness.runtime.open("art.comrade.ProbeB"),
        category="files",
        resource=trust.path_resource(Path(export.destination)),
        purpose="read",
    )
    harness.configure_probe(
        harness.runtime.open("art.comrade.ProbeB"),
        BUNNY_PROBE_GRANTED_FILE=harness.sandbox_path(Path(export.destination)),
        **parameters,
    )
    after = harness.run_probe(harness.runtime.open("art.comrade.ProbeB"))

    evidence.measurements = {
        "beforeTransfer": before,
        "afterTransfer": after,
        "export": dict(export.as_record()),
        "grant": {"verdict": decision.verdict, "reason": decision.reason_code, "scope": decision.scope},
    }
    if not before.get("probe") or not after.get("probe"):
        return evidence.settle("FAIL", "a probe produced no result")

    first, second = _by_check(before["probe"]), _by_check(after["probe"])
    problems: list[str] = []
    if first.get("other_capsule_secret_read", {}).get("result") == "AVAILABLE":
        problems.append("B read A's private marker before any transfer")
    if first.get("other_capsule_enumerate", {}).get("result") == "AVAILABLE":
        problems.append("B enumerated the capsule root")
    if second.get("other_capsule_secret_read", {}).get("result") == "AVAILABLE":
        problems.append("B read A's private marker after the authorised transfer")
    if second.get("other_capsule_enumerate", {}).get("result") == "AVAILABLE":
        problems.append("B enumerated the capsule root after the authorised transfer")
    granted = second.get("granted_file_read", {})
    if granted.get("result") != "AVAILABLE":
        problems.append(
            f"B could not read the artefact it was granted: {granted.get('result')} {granted.get('detail')}"
        )
    if problems:
        evidence.findings.extend(problems)
        return evidence.settle("FAIL", "; ".join(problems))
    return evidence.settle(
        "PASS",
        "B could neither read nor enumerate A's private storage before or after the transfer, "
        "and could read exactly the one artefact it was granted",
    )


def section_filegrant(harness: Harness, host: Mapping[str, Any]) -> Evidence:
    """No grant, one grant, a neighbour, a reuse, a restart, a revocation."""
    evidence = Evidence(section="filegrant")
    if not require_confinement(host, evidence):
        return evidence

    capsule = harness.install_probe_app("art.comrade.ProbeA", "Probe A", optional=("gpu",))
    target = harness.home / "Documents" / "report.odt"
    target.write_bytes(b"THE DOCUMENT\n")
    neighbour = harness.home / "Documents" / "other.odt"
    neighbour.write_bytes(b"SOMEBODY ELSE\n")
    # Inside a capsule a granted file appears at its sandbox path, not at the
    # one the person picked; pointing the probe at the host path would test
    # nothing, because that path is absent from the namespace whether or not the
    # grant worked.
    harness.configure_probe(
        capsule,
        BUNNY_PROBE_GRANTED_FILE=harness.sandbox_path(target),
        BUNNY_PROBE_NEIGHBOUR_FILE=harness.sandbox_path(neighbour),
        BUNNY_PROBE_CAPSULE_ROOT=str(harness.runtime.root),
    )

    stages: dict[str, Any] = {"noGrant": harness.run_probe(capsule)}

    harness.surface.answers = (("files", "allow", "once"),)
    once = harness.runtime.request_permission(
        harness.runtime.open("art.comrade.ProbeA"), category="files",
        resource=trust.path_resource(target), purpose="read",
    )
    stages["onceDecision"] = {
        "verdict": once.verdict, "reason": once.reason_code, "scope": once.scope, "grantId": once.grant_id
    }
    stages["afterOnce"] = harness.run_probe(harness.runtime.open("art.comrade.ProbeA"))

    harness.surface.answers = (("files", "allow", "always"),)
    always = harness.runtime.request_permission(
        harness.runtime.open("art.comrade.ProbeA"), category="files",
        resource=trust.path_resource(target), purpose="read",
    )
    stages["alwaysDecision"] = {
        "verdict": always.verdict, "reason": always.reason_code, "scope": always.scope,
        "grantId": always.grant_id,
    }
    stages["afterAlways"] = harness.run_probe(harness.runtime.open("art.comrade.ProbeA"))

    grants_before = len(harness.store.for_application("art.comrade.ProbeA"))
    harness.surface.answers = ()
    repeat = harness.runtime.request_permission(
        harness.runtime.open("art.comrade.ProbeA"), category="files",
        resource=trust.path_resource(target), purpose="read",
    )
    stages["standingGrantReuse"] = {
        "verdict": repeat.verdict, "reason": repeat.reason_code,
        "grantsBefore": grants_before,
        "grantsAfter": len(harness.store.for_application("art.comrade.ProbeA")),
    }

    restarted = TrustStore(trust.default_store_path(), session_id="qualify-restarted").load()
    stages["afterRestart"] = {
        "standingGrants": len(restarted.for_application("art.comrade.ProbeA")),
        "droppedSessionGrants": restarted.dropped_session_grants,
    }

    if always.grant_id:
        stages["revoked"] = harness.gate.revoke(always.grant_id, application_id="art.comrade.ProbeA")
    stages["afterRevoke"] = harness.run_probe(harness.runtime.open("art.comrade.ProbeA"))
    evidence.measurements = stages

    def result(stage: str, check: str) -> str:
        return _by_check(stages[stage].get("probe", {})).get(check, {}).get("result", "NOT_RUN")

    problems: list[str] = []
    if result("noGrant", "granted_file_read") == "AVAILABLE":
        problems.append("the document was readable with no grant")
    if result("afterAlways", "granted_file_read") != "AVAILABLE":
        problems.append(f"the granted document was not readable: {result('afterAlways', 'granted_file_read')}")
    if result("afterAlways", "neighbour_file_read") == "AVAILABLE":
        problems.append("a neighbouring file in the same folder was readable")
    if result("afterRevoke", "granted_file_read") == "AVAILABLE":
        problems.append("the document was still readable after the grant was revoked")
    if once.grant_id is not None:
        problems.append("an allow-once decision wrote a standing grant")
    if stages["standingGrantReuse"]["grantsAfter"] != grants_before:
        problems.append("a standing grant was rewritten when it was reused")
    if repeat.reason_code != "granted-previously":
        problems.append(f"a standing grant was not reused: {repeat.reason_code}")
    if stages["afterRestart"]["standingGrants"] != 1:
        problems.append(f"the always grant did not survive a restart: {stages['afterRestart']}")
    if problems:
        evidence.findings.extend(problems)
        return evidence.settle("FAIL", "; ".join(problems))
    return evidence.settle(
        "PASS",
        "no grant denied; granted readable; neighbour denied; revoked denied; allow-once left "
        "no grant; a standing grant was reused without being rewritten and survived a restart",
    )


def section_failclosed(harness: Harness, host: Mapping[str, Any]) -> Evidence:
    """Every way the permission path can break, and what it does when it does."""
    evidence = Evidence(section="failclosed")
    capsule = harness.install_probe_app("art.comrade.ProbeA", "Probe A")
    declaration = capsule.manifest.declaration()
    target = harness.home / "Documents" / "sensitive.odt"
    target.write_bytes(b"x")

    def request(request_id: str, category: str = "files", resource: Any = ..., purpose: str = "read"):
        if resource is ...:
            resource = trust.path_resource(target)
        return trust.PermissionRequest.build(
            request_id=request_id, application_id="art.comrade.ProbeA", category=category,
            session_id=harness.runtime.session_id, resource=resource, purpose=purpose,
        )

    class Broken:
        def ask(self, prompt, ticket):
            raise RuntimeError("the permission window crashed")

    class Silent:
        def ask(self, prompt, ticket):
            return None

    class Slow:
        def __init__(self, clock):
            self.clock = clock

        def ask(self, prompt, ticket):
            self.clock["now"] += 10_000
            return trust.UserAnswer(ticket_id=ticket.ticket_id, verdict="allow", scope="always")

    class Greedy:
        def ask(self, prompt, ticket):
            return trust.UserAnswer(ticket_id=ticket.ticket_id, verdict="allow", scope="always")

    def gate_with(surface, clock=None) -> TrustGate:
        extra = {"clock": (lambda: clock["now"])} if clock else {}
        return TrustGate(store=harness.store, audit=harness.audit, surface=surface, names={}, **extra)

    outcomes: dict[str, Any] = {}

    def record(name: str, decision) -> None:
        outcomes[name] = {
            "verdict": decision.verdict, "reason": decision.reason_code, "grant": decision.grant_id
        }

    record("uiCrash", gate_with(Broken()).check(request("fc-1"), declaration=declaration))
    record("noAnswer", gate_with(Silent()).check(request("fc-2"), declaration=declaration))
    clock = {"now": 0.0}
    record("expired", gate_with(Slow(clock), clock).check(request("fc-3"), declaration=declaration))
    record(
        "undeclaredCategory",
        gate_with(Greedy()).check(request("fc-4", category="camera", resource=None, purpose="use"),
                                  declaration=declaration),
    )

    # Replay. The answer has to be captured from a decision that leaves *no
    # standing grant*, or the second request never reaches a surface at all and
    # the section reports a replay it never performed. An allow-once is exactly
    # that decision — this cost a run to find, and the run that found it is the
    # reason the harness compares reason codes rather than verdicts.
    captured: dict[str, Any] = {}

    class CapturingOnce:
        def ask(self, prompt, ticket):
            captured["ticket"] = ticket
            return trust.UserAnswer(ticket_id=ticket.ticket_id, verdict="allow", scope="once")

    gate = gate_with(CapturingOnce())
    first = gate.check(request("fc-5"), declaration=declaration)
    outcomes["replaySetup"] = {
        "verdict": first.verdict, "reason": first.reason_code, "grant": first.grant_id,
    }

    class Replaying:
        def ask(self, prompt, ticket):
            # A surface that answers with an id it was given earlier, which is
            # what a captured or recorded approval looks like.
            return trust.UserAnswer(ticket_id=captured["ticket"].ticket_id, verdict="allow", scope="once")

    gate.surface = Replaying()
    record("replayedApproval", gate.check(request("fc-6"), declaration=declaration))

    store_path = Path(trust.default_store_path())
    saved = store_path.read_text(encoding="utf-8") if store_path.exists() else ""
    store_path.write_text("{ this is not a permission store", encoding="utf-8")
    try:
        corrupt = TrustStore(store_path, session_id=harness.runtime.session_id)
        try:
            corrupt.load()
            outcomes["malformedStore"] = {"verdict": "allow", "reason": "the corrupt store loaded"}
        except trust.TrustStoreUnreadable as error:
            record(
                "malformedStore",
                TrustGate(store=corrupt, audit=harness.audit, surface=Greedy(), names={}).check(
                    request("fc-7"), declaration=declaration
                ),
            )
            outcomes["malformedStore"]["loadError"] = str(error)[:160]
    finally:
        if saved:
            store_path.write_text(saved, encoding="utf-8")
            harness.store.load()

    # A resource that changed type between the approval and the launch.
    changed = harness.home / "Documents" / "changed.odt"
    changed.write_bytes(b"before")
    harness.surface.answers = (("files", "allow", "always"),)
    granted = harness.runtime.request_permission(
        harness.runtime.open("art.comrade.ProbeA"), category="files",
        resource=trust.path_resource(changed), purpose="read",
    )
    changed.unlink()
    changed.mkdir()
    plan = harness.runtime.build_plan(harness.runtime.open("art.comrade.ProbeA"))
    outcomes["resourceChangedAfterApproval"] = {
        "grant": granted.grant_id,
        "refusals": [{"grantId": g, "reason": r} for g, r in plan.refusals],
        "boundAnyway": [b.source for b in plan.binds if b.origin == "grant" and str(changed) in b.source],
    }

    evidence.measurements = outcomes
    expected = {
        "uiCrash": "surface-failed",
        "noAnswer": "unanswered",
        "expired": "expired",
        "undeclaredCategory": "not-declared",
        "replayedApproval": "replayed",
        "malformedStore": "store-unreadable",
    }
    problems: list[str] = []
    for name, reason in expected.items():
        row = outcomes.get(name, {})
        if row.get("verdict") != "deny":
            problems.append(f"{name}: verdict was {row.get('verdict')!r}, not deny")
        elif row.get("reason") != reason:
            problems.append(f"{name}: reason was {row.get('reason')!r}, expected {reason!r}")
        if row.get("grant"):
            problems.append(f"{name}: a fail-closed denial wrote a grant")
    changed_row = outcomes["resourceChangedAfterApproval"]
    if changed_row["boundAnyway"]:
        problems.append("a resource that changed type after approval was bound anyway")
    if not changed_row["refusals"]:
        problems.append("a resource that changed type after approval produced no refusal")
    distinct = sorted({row["reason"] for name, row in outcomes.items() if name in expected})
    if len(distinct) != len(expected):
        problems.append(f"fail-closed reasons collapsed into {distinct}")
    if problems:
        evidence.findings.extend(problems)
        return evidence.settle("FAIL", "; ".join(problems))
    return evidence.settle(
        "PASS", f"every failure path denied, wrote no grant, and produced its own reason: {distinct}"
    )


from .sections_network import section_network  # noqa: E402
from .sections_selinux import section_selinux  # noqa: E402
from .sections_launcher import section_launcher  # noqa: E402
from .sections_runtime import section_crash, section_resources  # noqa: E402

#: Section name to function. The order is the order a failure is cheapest to
#: read in: the host first, then what one capsule can reach, then what two can
#: reach of each other, then the permission lifecycle, then the failure paths,
#: then what happens when the parts holding a permission open are killed, and
#: last the limits — which take minutes because they are measured by exceeding
#: them.
SECTIONS = {
    "host": section_host,
    "isolation": section_isolation,
    "crossapp": section_crossapp,
    "filegrant": section_filegrant,
    "failclosed": section_failclosed,
    "network": section_network,
    # SELinux before the crash and resource sections: it is the layer the host
    # qualification could not measure at all, and on a guest it is the reason
    # the run exists.
    "selinux": section_selinux,
    "crash": section_crash,
    # Last but one, because it is the only section that asks whether a capsule
    # can be *started* by the thing that starts capsules in the product. Every
    # other section launches from a login shell, which nothing does.
    "launcher": section_launcher,
    "resources": section_resources,
}
