#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Launch real App Capsules on this machine and record what they could reach.

Everything in the capsule phase up to now has been a property of a *value* — a
plan, an argument vector, a store record. This is the harness that turns those
into measurements, by starting an actual confined process and asking it.

Four rules, and each one is a way this kind of harness produces a false pass.

**No mock, no fake executor, no non-confining backend.** The runtime is the
production :class:`~capsules.runtime.CapsuleRuntime` with
:class:`~capsules.runtime.SubprocessExecutor` and a probe of the real machine. If
this host cannot confine, the harness reports ``BLOCKED`` and stops. It never
falls back.

**The negative control is not optional.** Every isolation section runs the same
probe outside the sandbox, and :func:`compare` requires the control to have
reached at least one thing the capsule could not. Without that, a host with no
camera scores as a working camera restriction and a host with no network scores
as network isolation.

**A missing thing is not a denied thing.** The probe distinguishes ``DENIED``
from ``ABSENT``, and this harness only counts a check as isolation when the
control says ``AVAILABLE`` and the capsule says ``DENIED``.

**Nothing is inferred from a configuration file.** The verdict for every row
comes from the probe's own result, produced inside the environment being tested.

Sections are independent so a partial run is legible as a partial run:

``host``       what this machine is, recorded before anything runs
``isolation``  one capsule, one probe, one negative control
``crossapp``   two capsules, a secret marker, and one authorised export
``filegrant``  no grant, one grant, a neighbour, a revocation, a restart
``failclosed`` replay, expiry, corruption, a broken surface, a dead policy
``crash``      the companion, the surface and the supervisor, killed
``resources``  the cgroup limits, exceeded on purpose
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import contextlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import capsules  # noqa: E402
import trust  # noqa: E402
from capsules.backends import MachineProbe, available_backends  # noqa: E402
from capsules.exchange import describe_import  # noqa: E402
from capsules.manifest import CapsuleManifest, ResourceLimits  # noqa: E402
from capsules.runtime import CapsuleRuntime, SubprocessExecutor  # noqa: E402
from companion.trust_surface import AutomationSurface  # noqa: E402
from trust.audit import TrustAudit  # noqa: E402
from trust.gate import TrustGate  # noqa: E402
from trust.store import TrustStore  # noqa: E402

PROBE = ROOT / "qualification/capsules/probe.py"

#: Where a section's evidence lands. One directory per run, named by the commit
#: it was taken at, because evidence that is not bound to a commit is evidence
#: about nothing.
EVIDENCE_ROOT = ROOT / "qualification/capsules/evidence"

VERDICTS = ("PASS", "FAIL", "BLOCKED", "NOT_RUN")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _commit() -> str:
    """The commit this run measures.

    ``$BUNNY_QUALIFY_COMMIT`` wins, because inside a booted guest there is no
    git checkout to ask — the harness is injected into a disk and the commit it
    belongs to is a fact the injector knows and the guest does not. Falling back
    to "unknown" there would produce evidence bound to nothing.
    """
    stated = os.environ.get("BUNNY_QUALIFY_COMMIT", "").strip()
    if stated:
        return stated
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _command_output(argv: Sequence[str]) -> tuple[int, str]:
    try:
        result = subprocess.run(list(argv), capture_output=True, text=True, timeout=30, check=False)
        return result.returncode, (result.stdout + result.stderr).strip()
    except (OSError, subprocess.SubprocessError) as error:
        return -1, f"{type(error).__name__}: {error}"


# -- host ----------------------------------------------------------------


def host_record() -> Mapping[str, Any]:
    """Everything about this machine that could change a result."""
    probe = MachineProbe.measure()
    versions: dict[str, str] = {}
    for name, argv in (
        ("python", [sys.executable, "--version"]),
        ("bubblewrap", ["bwrap", "--version"]),
        ("flatpak", ["flatpak", "--version"]),
        ("systemd", ["systemctl", "--version"]),
        ("kernel", ["uname", "-r"]),
    ):
        code, output = _command_output(argv)
        versions[name] = output.splitlines()[0] if code == 0 and output else "ABSENT"
    selinux = _selinux_facts()
    _, virt = _command_output(["systemd-detect-virt"])
    filesystem = "unknown"
    code, output = _command_output(["stat", "-fc", "%T", str(Path.home())])
    if code == 0:
        filesystem = output.strip()
    return {
        "schemaVersion": 1,
        "recordedAt": _now(),
        "commit": _commit(),
        "user": {
            "name": os.environ.get("USER") or os.environ.get("LOGNAME") or "unknown",
            "uid": _uid(),
        },
        "isRoot": _uid() == 0,
        "versions": versions,
        "selinux": selinux,
        "virtualization": virt.strip() or "unknown",
        "homeFilesystem": filesystem,
        "cgroupVersion": _cgroup_version(),
        "kernelUserNamespaces": {
            "nsFilePresent": Path("/proc/self/ns/user").exists(),
            "maxUserNamespaces": _read_int("/proc/sys/user/max_user_namespaces"),
        },
        "machineProbe": {
            "programs": sorted(probe.programs),
            "userNamespaces": probe.user_namespaces,
            "portal": probe.portal,
            "graphicalSession": probe.graphical_session,
        },
        "availableBackends": list(available_backends(probe)),
        "image": _image_identity(),
        "graphical": {
            "waylandDisplay": os.environ.get("WAYLAND_DISPLAY", ""),
            "display": os.environ.get("DISPLAY", ""),
        },
    }


def _selinux_facts() -> Mapping[str, Any]:
    """Mode, policy version and type — the three that decide what a result means.

    The host qualification ran with SELinux Disabled and said so everywhere. A
    guest run has it enforcing, and the difference is the whole reason the guest
    run exists, so the facts are recorded as a structure rather than a word.
    """
    code, mode = _command_output(["getenforce"])
    # A platform with no getenforce is not "Permissive" and not "Disabled"; it
    # has no answer, and the difference matters because Disabled is a real
    # SELinux state a reader would draw a conclusion from.
    facts: dict[str, Any] = {
        "mode": mode.strip() if code == 0 and mode.strip() else "unavailable",
        "probeError": None if code == 0 else mode.strip()[:200],
    }
    try:
        facts["policyVersion"] = Path("/sys/fs/selinux/policyvers").read_text(encoding="utf-8").strip()
    except OSError:
        facts["policyVersion"] = None
    code, output = _command_output(["sestatus"])
    if code == 0:
        for line in output.splitlines():
            key, _, value = line.partition(":")
            key = key.strip().lower()
            if key == "loaded policy name":
                facts["policyName"] = value.strip()
            elif key == "policy from config file":
                facts["policyFromConfig"] = value.strip()
    facts["fsMounted"] = Path("/sys/fs/selinux").is_dir()
    try:
        facts["selfContext"] = Path("/proc/self/attr/current").read_text(encoding="utf-8").strip().rstrip(chr(0))
    except OSError:
        facts["selfContext"] = None
    return facts


def _image_identity() -> Mapping[str, Any]:
    """What image this is, when the run is inside one.

    Read from the release file the image build writes and from bootc's own view
    of the deployment. Absent on a developer host, which is itself the answer to
    "was this measured in the product or beside it".
    """
    identity: dict[str, Any] = {}
    for path in (Path("/usr/lib/bunny-os/release.json"), Path("/etc/bunny-os/release.json")):
        if path.is_file():
            try:
                identity["release"] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                identity["releaseError"] = str(error)
            break
    code, output = _command_output(["bootc", "status", "--json"])
    if code == 0 and output:
        try:
            status = json.loads(output)
            booted = (status.get("status") or {}).get("booted") or {}
            image = (booted.get("image") or {}).get("image") or {}
            identity["bootc"] = {
                "image": image.get("image"),
                "transport": image.get("transport"),
                "digest": (booted.get("image") or {}).get("imageDigest"),
                "version": (booted.get("image") or {}).get("version"),
            }
        except (json.JSONDecodeError, AttributeError):
            identity["bootcRaw"] = output[:400]
    try:
        identity["osRelease"] = dict(
            line.split("=", 1) for line in
            Path("/etc/os-release").read_text(encoding="utf-8").splitlines() if "=" in line
        )
    except OSError:
        pass
    return identity


def _uid() -> int:
    """The POSIX uid, or -1 where the platform has none.

    -1 rather than 0: a record that reported uid 0 on a platform with no uids
    would read as "this ran as root", and `require_confinement` refuses to
    qualify anything as root.
    """
    getuid = getattr(os, "getuid", None)
    return getuid() if getuid is not None else -1


def _cgroup_version() -> str:
    code, output = _command_output(["stat", "-fc", "%T", "/sys/fs/cgroup"])
    return output.strip() if code == 0 else "unknown"


def _read_int(path: str) -> int | None:
    try:
        return int(Path(path).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


# -- the world -----------------------------------------------------------


@dataclass
class Harness:
    """A throwaway Bunny world on this machine, using the production runtime."""

    base: Path
    home: Path
    store: TrustStore
    audit: TrustAudit
    surface: AutomationSurface
    gate: TrustGate
    runtime: CapsuleRuntime
    executor: SubprocessExecutor

    @classmethod
    def build(cls, *, session_id: str = "qualify-1") -> "Harness":
        base = Path(tempfile.mkdtemp(prefix="bunny-qualify-"))
        home = base / "home"
        for name in ("Documents", "Downloads", "Pictures", "Music", "Videos", "Desktop"):
            (home / name).mkdir(parents=True, exist_ok=True)
        os.environ["BUNNY_TRUST_ROOT"] = str(base / "trust")
        os.environ["BUNNY_CAPSULE_ROOT"] = str(base / "capsules")
        for name in ("DOCUMENTS", "DOWNLOAD", "PICTURES", "MUSIC", "VIDEOS", "DESKTOP"):
            folder = {"DOWNLOAD": "Downloads"}.get(name, name.capitalize())
            os.environ[f"XDG_{name}_DIR"] = str(home / folder)

        store = TrustStore(trust.default_store_path(), session_id=session_id).load()
        audit = TrustAudit(trust.default_audit_path(), names={})
        surface = AutomationSurface(answers=())
        gate = TrustGate(store=store, audit=audit, surface=surface, names={})
        executor = SubprocessExecutor()
        runtime = CapsuleRuntime(
            store=store, audit=audit, gate=gate, session_id=session_id,
            root=capsules.default_capsule_root(), probe=MachineProbe.measure(), executor=executor,
        )
        return cls(base=base, home=home, store=store, audit=audit, surface=surface,
                   gate=gate, runtime=runtime, executor=executor)

    def install_probe_app(self, application_id: str, display_name: str, *, optional=("gpu", "network")):
        manifest = CapsuleManifest(
            identity=capsules.capsule_identity(application_id),
            display_name=display_name,
            package_source="fedora-rpm",
            package_reference=sys.executable,
            preferred_backend="bubblewrap",
            required_permissions=frozenset({"files"}),
            optional_permissions=frozenset(optional),
            permission_reasons={"files": "to read the file you choose"},
            network_ceiling="internet" if "network" in optional else "none",
            limits=ResourceLimits(),
        )
        capsule = self.runtime.install(manifest)
        shutil.copy2(PROBE, capsule.layout.directory("data") / "probe.py")
        return capsule

    def seed_credentials(self) -> Mapping[str, Path]:
        """Put a credential-shaped file in each directory the probe checks.

        Without this the control cannot read ``~/.ssh`` either — the qualification
        account has none — and every credential row comes back INCONCLUSIVE,
        which is the negative control correctly refusing to call an absent file a
        working restriction. The fixtures are inside the harness's own throwaway
        home; the real account is never written to.
        """
        seeded: dict[str, Path] = {}
        for directory, name, content in (
            (".ssh", "id_ed25519", "-----BEGIN OPENSSH PRIVATE KEY-----\nFIXTURE-NOT-A-REAL-KEY\n"),
            (".gnupg", "pubring.kbx", "FIXTURE"),
            (".mozilla", "profiles.ini", "[Profile0]\nPath=fixture\n"),
            (".config", "bunny-fixture.conf", "FIXTURE"),
        ):
            target = self.home / directory / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            seeded[directory] = target
        return seeded

    def configure_probe(self, capsule, **values: str) -> None:
        configuration = {"BUNNY_PROBE_HOME": str(self.home), "BUNNY_PROBE_ENVIRONMENT": "capsule"}
        configuration.update(values)
        (capsule.layout.directory("data") / "probe-config.json").write_text(
            json.dumps(configuration, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    @staticmethod
    def probe_path() -> Path:
        """The probe fixture, for a section that installs a capsule of its own."""
        return PROBE

    @staticmethod
    @contextlib.contextmanager
    def listening_socket():
        """A real TCP listener on loopback, for the duration of one probe pair.

        Without something actually listening, a connect to 127.0.0.1 is refused
        in both environments and the row says nothing. With it, the control
        connects and the capsule — whose network namespace is its own — cannot,
        which is the measurement.
        """
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(8)
        try:
            yield server.getsockname()[1]
        finally:
            server.close()

    @staticmethod
    def sandbox_path(path: Path, *, writable: bool = False) -> str:
        """Where a granted host path appears *inside* a capsule.

        The probe reads whatever it is pointed at, and pointing it at the host
        path from inside the sandbox tests nothing: that path is not in the
        namespace, so the answer is always ENOENT whether or not the grant
        worked. This is the same function the trust prompt uses to tell a person
        where their file will appear.
        """
        return describe_import(trust.path_resource(path), writable=writable).sandbox_path

    def run_probe(self, capsule, *, timeout: float = 180.0) -> Mapping[str, Any]:
        """Launch the capsule, wait for the probe, and read what it wrote."""
        result_path = capsule.layout.directory("data") / "probe-result.json"
        if result_path.exists():
            result_path.unlink()
        capsule = self.runtime.open(capsule.identity.application_id)
        record = self.runtime.launch(
            capsule, command=(sys.executable, "/run/bunny/app/data/probe.py")
        )
        exit_code = None
        if record.pid is not None:
            try:
                exit_code = self.executor.wait(record.pid, timeout=timeout)
            except subprocess.TimeoutExpired:
                exit_code = "TIMEOUT"
        deadline = time.monotonic() + 10
        while not result_path.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        document: Mapping[str, Any] = {}
        if result_path.exists():
            document = json.loads(result_path.read_text(encoding="utf-8"))
        return {
            "argv": list(record.argv),
            "backend": record.backend,
            "started": record.started,
            "pid": record.pid,
            "exitCode": exit_code,
            "planRefusals": [{"grantId": g, "reason": r} for g, r in record.plan.refusals],
            "unenforced": list(record.plan.unenforced),
            "reachablePaths": list(record.plan.reachable_paths()),
            "probe": document,
        }

    def run_control(self, capsule, **values: str) -> Mapping[str, Any]:
        """The same probe, outside the sandbox, on the same machine.

        This is the mandatory negative control. It runs as the same user with the
        same interpreter, and its only difference is the absence of a capsule
        around it.
        """
        workspace = self.base / "control"
        workspace.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROBE, workspace / "probe.py")
        configuration = {
            "BUNNY_PROBE_HOME": str(self.home),
            "BUNNY_PROBE_ENVIRONMENT": "control",
            "BUNNY_PROBE_OUTPUT": str(workspace / "probe-result.json"),
        }
        configuration.update(values)
        (workspace / "probe-config.json").write_text(
            json.dumps(configuration, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        environment = dict(os.environ)
        environment["XDG_DATA_HOME"] = str(workspace)
        result = subprocess.run(  # noqa: S603
            [sys.executable, str(workspace / "probe.py")],
            capture_output=True, text=True, timeout=180, check=False, env=environment,
        )
        document: Mapping[str, Any] = {}
        target = workspace / "probe-result.json"
        if target.exists():
            document = json.loads(target.read_text(encoding="utf-8"))
        return {"exitCode": result.returncode, "stderr": result.stderr.strip()[:400], "probe": document}

    def close(self) -> None:
        shutil.rmtree(self.base, ignore_errors=True)


def _by_check(document: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
    return {check["check"]: check for check in document.get("checks", [])}


def compare(capsule_probe: Mapping[str, Any], control_probe: Mapping[str, Any]) -> Mapping[str, Any]:
    """Score the capsule against the control, check by check.

    ``ISOLATED`` requires *both* halves: the control reached the thing and the
    capsule did not. Everything else is reported for what it is, so that a row
    nobody can draw a conclusion from looks like one.

    **A capsule reports absence, not refusal, and that is what isolation looks
    like.** A path that is not in a mount namespace produces ``ENOENT``, not
    ``EACCES`` — there is no file to be refused access to. So ``ABSENT`` inside
    counts as isolated *when the control reached it*, and only then. That
    condition is the whole reason the control is mandatory: without it, absence
    inside would be indistinguishable from a host that never had the file, which
    is the false pass this function exists to prevent. The capsule's raw result
    is kept in every row so a reader can see which of the two it was.
    """
    inside = _by_check(capsule_probe)
    outside = _by_check(control_probe)
    rows = []
    isolated = 0
    for name in sorted(set(inside) | set(outside)):
        capsule_result = inside.get(name, {}).get("result", "NOT_RUN")
        control_result = outside.get(name, {}).get("result", "NOT_RUN")
        if control_result == "AVAILABLE" and capsule_result in ("DENIED", "ABSENT"):
            verdict = "ISOLATED"
            isolated += 1
        elif control_result == "AVAILABLE" and capsule_result == "AVAILABLE":
            verdict = "SHARED"
        elif control_result in ("ABSENT", "ERROR", "NOT_RUN"):
            verdict = "INCONCLUSIVE"
        elif capsule_result == "AVAILABLE" and control_result in ("DENIED", "ABSENT"):
            verdict = "WIDER-INSIDE"
        else:
            verdict = "BOTH-DENIED"
        rows.append({
            "check": name,
            "category": inside.get(name, outside.get(name, {})).get("category", ""),
            "capsule": capsule_result,
            "control": control_result,
            "verdict": verdict,
            "capsuleDetail": inside.get(name, {}).get("detail", "")[:200],
            "controlDetail": outside.get(name, {}).get("detail", "")[:200],
        })
    return {
        "rows": rows,
        "isolatedCount": isolated,
        "widerInside": [row["check"] for row in rows if row["verdict"] == "WIDER-INSIDE"],
        "controlProvedSomething": isolated > 0,
    }


# -- evidence ------------------------------------------------------------


@dataclass
class Evidence:
    """One section's record. Written whole, and never partly."""

    section: str
    started_at: str = field(default_factory=_now)
    verdict: str = "NOT_RUN"
    explanation: str = ""
    measurements: dict[str, Any] = field(default_factory=dict)
    findings: list[str] = field(default_factory=list)

    def settle(self, verdict: str, explanation: str) -> "Evidence":
        if verdict not in VERDICTS:
            raise ValueError(f"unknown verdict: {verdict!r}")
        self.verdict = verdict
        self.explanation = explanation
        return self

    def as_record(self, *, host: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "schemaVersion": 1,
            "section": self.section,
            "commit": host.get("commit"),
            "startedAt": self.started_at,
            "finishedAt": _now(),
            "host": {
                "user": host.get("user"),
                "kernel": host.get("versions", {}).get("kernel"),
                "selinux": host.get("selinux"),
                "virtualization": host.get("virtualization"),
                "homeFilesystem": host.get("homeFilesystem"),
                "backends": host.get("availableBackends"),
            },
            "verdict": self.verdict,
            "explanation": self.explanation,
            "findings": list(self.findings),
            "measurements": self.measurements,
        }


def write_evidence(evidence: Evidence, host: Mapping[str, Any], directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{evidence.section}.json"
    path.write_text(
        json.dumps(evidence.as_record(host=host), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def require_confinement(host: Mapping[str, Any], evidence: Evidence) -> bool:
    """Refuse to run an isolation section on a host that cannot isolate.

    Reports ``BLOCKED``, not ``FAIL`` and never ``PASS``: a machine without user
    namespaces has not failed the sandbox, it has not run it.
    """
    backends = [name for name in host.get("availableBackends", []) if name != "systemd-scope"]
    if not backends:
        evidence.settle(
            "BLOCKED",
            "no confining backend is available on this host; "
            f"machineProbe={host.get('machineProbe')}",
        )
        return False
    if host.get("isRoot"):
        evidence.settle("BLOCKED", "this harness must not run as root; the sandbox it tests is unprivileged")
        return False
    return True
