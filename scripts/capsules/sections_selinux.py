# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What SELinux does to a capsule, measured on a system where it is enforcing.

The host qualification ran with SELinux Disabled and said so on every page. That
is not a small caveat: the capsule design treats SELinux as one layer among
namespaces, cgroups, portals and Polkit, and a run with it off has measured the
other layers only. This section exists to measure the layer, and it can only
produce a result on a system where the mode is ``Enforcing``.

Three questions, and the order matters because the second is the one that gets
answered wrongly.

**Does the expected work?** A capsule must launch, read the file it was granted,
write its own private storage and export a result — with the policy loaded. A
section that only counted denials would call a completely broken system a
success.

**Is anything denied that should not be?** Every AVC record produced *during the
run* is collected, attributed to the operation that was in flight, and reported.
An AVC is not automatically a failure — the sandbox provokes some by design — so
they are recorded rather than judged, and the ones that coincide with a failed
operation are separated from the ones that did not stop anything.

**Was the policy weakened to get here?** :func:`policy_integrity` records the
mode, whether any local boolean was flipped, and whether any module was loaded
beyond the shipped policy. §5 forbids solving an application denial with a broad
permissive rule, and the way to keep that honest is to record what the policy was
at the moment the other results were taken.

Nothing here changes policy. If a denial blocks a capsule operation, this section
reports it and the finding goes into the report; narrowing a rule is a separate,
reviewed change and not something a qualification run does to itself.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any, Mapping, Sequence

import trust
from capsules.manifest import CapsuleManifest, ResourceLimits

from .harness import Evidence, Harness, _by_check, require_confinement

__all__ = ["section_selinux", "collect_avcs", "policy_integrity"]

#: Fields worth keeping from an AVC line. The raw line is kept too, because an
#: audit record with fields extracted and the original discarded is a record
#: somebody has already interpreted.
_AVC_FIELDS = ("scontext", "tcontext", "tclass", "comm", "path", "name", "permissive", "denied")


def _run(argv: Sequence[str], timeout: int = 30) -> tuple[int, str]:
    try:
        result = subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout, check=False)
        return result.returncode, (result.stdout + result.stderr)
    except (OSError, subprocess.SubprocessError) as error:
        return -1, f"{type(error).__name__}: {error}"


def collect_avcs(since: str) -> Mapping[str, Any]:
    """Every AVC the kernel logged since ``since``, parsed and kept raw.

    ``journalctl`` first because it is present on any systemd system and needs no
    audit daemon; ``ausearch`` second because where auditd *is* running it sees
    records journald may not. Both are attempted and both results are recorded,
    including "this tool was not here", so a reader can tell an empty list caused
    by silence from one caused by an absent tool.
    """
    found: list[dict[str, Any]] = []
    sources: dict[str, Any] = {}

    code, output = _run(["journalctl", "--since", since, "--no-pager", "-o", "cat", "-k"], timeout=60)
    sources["journalctl"] = {"available": code == 0, "lines": len(output.splitlines())}
    if code == 0:
        for line in output.splitlines():
            if "avc:" in line and "denied" in line:
                found.append(_parse_avc(line))

    if shutil.which("ausearch"):
        code, output = _run(["ausearch", "-m", "AVC", "-ts", "recent", "-i"], timeout=60)
        sources["ausearch"] = {"available": code in (0, 1), "lines": len(output.splitlines())}
        if code == 0:
            for line in output.splitlines():
                if "avc:" in line and "denied" in line:
                    parsed = _parse_avc(line)
                    if parsed not in found:
                        found.append(parsed)
    else:
        sources["ausearch"] = {"available": False, "reason": "not installed"}

    return {"sources": sources, "count": len(found), "records": found[:80]}


def _parse_avc(line: str) -> dict[str, Any]:
    record: dict[str, Any] = {"raw": line.strip()[:500]}
    for field in _AVC_FIELDS:
        match = re.search(rf"{field}=(?:\"([^\"]*)\"|(\S+))", line)
        if match:
            record[field] = match.group(1) or match.group(2)
    denied = re.search(r"denied\s+\{([^}]*)\}", line)
    if denied:
        record["permissions"] = denied.group(1).split()
    return record


def policy_integrity() -> Mapping[str, Any]:
    """The state of the policy at the moment the other results were taken.

    Recorded so a later reader can tell whether a passing result was obtained
    honestly. A run that had quietly set the mode to Permissive, flipped a
    boolean or side-loaded a module would look identical in every other field.
    """
    facts: dict[str, Any] = {}
    code, mode = _run(["getenforce"])
    facts["mode"] = mode.strip() if code == 0 else "unavailable"

    code, output = _run(["semodule", "-l"], timeout=60)
    facts["moduleTool"] = code == 0
    if code == 0:
        modules = [line.split()[0] for line in output.splitlines() if line.strip()]
        facts["moduleCount"] = len(modules)
        facts["bunnyModules"] = sorted(name for name in modules if "bunny" in name.lower())

    code, output = _run(["getsebool", "-a"], timeout=60)
    if code == 0:
        facts["booleanCount"] = len(output.splitlines())
    # Local boolean changes are the cheap way to weaken a policy and the easy
    # thing to forget having done.
    local = Path("/etc/selinux/targeted/active/booleans.local")
    facts["localBooleans"] = (
        local.read_text(encoding="utf-8").strip().splitlines()[:20] if local.is_file() else []
    )
    facts["permissiveDomains"] = []
    code, output = _run(["semanage", "permissive", "-l"], timeout=60)
    if code == 0:
        facts["permissiveDomains"] = [
            line.strip() for line in output.splitlines()
            if line.strip() and not line.startswith(("Builtin", "Customized", "-"))
        ][:20]
    return facts


def section_selinux(harness: Harness, host: Mapping[str, Any]) -> Evidence:
    """Launch a capsule with the policy loaded, and record what it said."""
    evidence = Evidence(section="selinux")
    mode = str((host.get("selinux") or {}).get("mode", "unavailable"))

    if mode != "Enforcing":
        evidence.measurements = {"selinux": host.get("selinux"), "policy": policy_integrity()}
        return evidence.settle(
            "BLOCKED",
            f"SELinux mode is {mode!r}; this section can only produce a result where it is "
            f"Enforcing, and reporting anything else would be evidence about a layer that was "
            f"not running",
        )
    if not require_confinement(host, evidence):
        return evidence

    before = policy_integrity()
    started = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 5))

    # The expected operations, in the order a real task performs them.
    capsule = harness.install_probe_app("art.comrade.SelinuxProbe", "SELinux Probe")
    (capsule.layout.directory("data") / "own-marker.txt").write_text("marker\n", encoding="utf-8")
    document = harness.home / "Documents" / "granted.txt"
    document.write_bytes(b"THE DOCUMENT\n")
    harness.surface.answers = (("files", "allow", "always"),)
    decision = harness.runtime.request_permission(
        harness.runtime.open("art.comrade.SelinuxProbe"), category="files",
        resource=trust.path_resource(document), purpose="read",
    )
    harness.configure_probe(
        harness.runtime.open("art.comrade.SelinuxProbe"),
        BUNNY_PROBE_GRANTED_FILE=harness.sandbox_path(document),
        BUNNY_PROBE_CAPSULE_ROOT=str(harness.runtime.root),
    )
    launched = harness.run_probe(harness.runtime.open("art.comrade.SelinuxProbe"))
    checks = _by_check(launched.get("probe", {}))

    # Export, which crosses the capsule boundary and is the operation most likely
    # to meet a label the policy has an opinion about.
    export_result: dict[str, Any]
    try:
        import capsules

        artefact = capsule.layout.directory("exports") / "result.txt"
        artefact.write_text("EXPORTED\n", encoding="utf-8")
        export = capsules.export_artifact(
            capsule.layout, "result.txt",
            destination_root=harness.home / "Documents",
            capsule_root=harness.runtime.root, home=harness.home,
        )
        export_result = {"ok": True, "destination": export.destination, "bytes": export.bytes_written}
    except Exception as error:  # noqa: BLE001
        export_result = {"ok": False, "error": f"{type(error).__name__}: {error}"}

    avcs = collect_avcs(started)
    after = policy_integrity()

    expected = {
        "capsuleLaunched": bool(launched.get("started")),
        "probeProducedResult": bool(launched.get("probe")),
        "ownDataRead": checks.get("own_data_read", {}).get("result") == "AVAILABLE",
        "ownDataWrite": checks.get("own_data_write", {}).get("result") == "AVAILABLE",
        "grantedFileRead": checks.get("granted_file_read", {}).get("result") == "AVAILABLE",
        "subprocess": checks.get("subprocess", {}).get("result") == "AVAILABLE",
        "exported": export_result.get("ok", False),
    }
    unexpected = {
        "homeDenied": checks.get("home_read", {}).get("result") != "AVAILABLE",
        "sshDenied": checks.get("ssh_read", {}).get("result") != "AVAILABLE",
        "peerCapsuleDenied": checks.get("other_capsule_enumerate", {}).get("result") != "AVAILABLE",
    }

    evidence.measurements = {
        "selinux": host.get("selinux"),
        "policyBefore": before,
        "policyAfter": after,
        "grant": {"verdict": decision.verdict, "reason": decision.reason_code},
        "launch": {k: launched.get(k) for k in ("started", "backend", "exitCode", "unenforced")},
        "expectedOperations": expected,
        "unexpectedAccessDenied": unexpected,
        "export": export_result,
        "avc": avcs,
    }

    problems = [name for name, ok in expected.items() if not ok]
    leaks = [name for name, denied in unexpected.items() if not denied]
    if before.get("mode") != "Enforcing" or after.get("mode") != "Enforcing":
        evidence.findings.append("the mode changed during the run; the result is not about enforcing SELinux")
        return evidence.settle("FAIL", "SELinux was not enforcing for the whole run")
    if before.get("permissiveDomains") != after.get("permissiveDomains"):
        evidence.findings.append("a permissive domain was added during the run")
        return evidence.settle("FAIL", "the policy was weakened during the run")
    if leaks:
        evidence.findings.append(f"STOP CONDITION: reachable under enforcing SELinux: {leaks}")
        return evidence.settle("FAIL", f"the capsule reached {leaks}")
    if problems:
        evidence.findings.append(
            f"operations that must work under enforcing SELinux did not: {problems}. "
            f"{avcs['count']} AVC record(s) were logged during the run; see measurements.avc."
        )
        return evidence.settle("FAIL", f"expected capsule operations failed: {problems}")

    note = (
        f"every expected capsule operation worked with the policy loaded "
        f"(mode {before.get('mode')}, {before.get('moduleCount')} modules); "
        f"{avcs['count']} AVC record(s) logged during the run"
    )
    if avcs["count"]:
        evidence.findings.append(
            f"{avcs['count']} AVC record(s) were logged while the capsule ran and none of them "
            f"stopped an expected operation. They are recorded rather than judged; a denial the "
            f"sandbox provokes by design and one that would matter look the same from here."
        )
    if before.get("permissiveDomains"):
        evidence.findings.append(
            f"the policy already carries permissive domains: {before['permissiveDomains']}. "
            f"Nothing here added one, and a result taken beside a permissive domain is weaker "
            f"than one taken without."
        )
    return evidence.settle("PASS", note)
