# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Crash boundaries and resource enforcement, measured on a running system.

Two sections that cannot be answered by reading anything. §11 asks what happens
when the parts of Bunny that hold a permission open are killed; §12 asks whether
a resource limit is a limit or a line in a unit file. Both are questions about a
kernel, and both are answered here by doing the thing and recording what the
kernel did.

The rule both sections follow: **the intervention is observed from outside the
capsule.** A process that reports "I was limited" is a process that survived to
report it; a process killed by a cgroup reports nothing at all, and the exit
signal is the evidence.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping

import trust
from capsules.manifest import CapsuleManifest, ResourceLimits
from capsules.runtime import CapsuleRuntime, SubprocessExecutor

from .harness import Evidence, Harness, require_confinement

__all__ = ["section_crash", "section_network", "section_resources"]

STRESS = Path(__file__).resolve().parents[2] / "qualification/capsules/stress.py"


def _install_stress(harness: Harness, application_id: str, limits: ResourceLimits, mode: str):
    """A capsule whose application is the stress fixture, with stated limits."""
    import capsules

    manifest = CapsuleManifest(
        identity=capsules.capsule_identity(application_id),
        display_name=application_id.rsplit(".", 1)[-1],
        package_source="fedora-rpm",
        package_reference=sys.executable,
        preferred_backend="bubblewrap",
        required_permissions=frozenset({"files"}),
        optional_permissions=frozenset(),
        permission_reasons={"files": "to read the file you choose"},
        limits=limits,
    )
    capsule = harness.runtime.install(manifest)
    shutil.copy2(STRESS, capsule.layout.directory("data") / "stress.py")
    (capsule.layout.directory("data") / "probe-config.json").write_text(
        json.dumps({"BUNNY_PROBE_ENVIRONMENT": "capsule"}), encoding="utf-8"
    )
    return capsule


def _launch_stress(harness: Harness, capsule, mode: str):
    """Start the stress fixture inside its capsule.

    The mode reaches the fixture through the capsule's own storage rather than
    the environment, for the same reason the probe's configuration does: the
    capsule environment is a fixed key set and a test fixture must not be the
    reason it grows.
    """
    (capsule.layout.directory("data") / "stress-mode").write_text(mode, encoding="utf-8")
    launcher = capsule.layout.directory("data") / "run-stress.py"
    launcher.write_text(
        "import os, runpy, pathlib\n"
        "base = pathlib.Path(__file__).resolve().parent\n"
        "os.environ['BUNNY_STRESS_MODE'] = (base / 'stress-mode').read_text().strip()\n"
        "os.environ['BUNNY_STRESS_OUTPUT'] = str(base / 'stress-result.json')\n"
        "runpy.run_path(str(base / 'stress.py'), run_name='__main__')\n",
        encoding="utf-8",
    )
    return harness.runtime.launch(
        harness.runtime.open(capsule.identity.application_id),
        command=(sys.executable, "/run/bunny/app/data/run-stress.py"),
    )


def _stress_result(capsule) -> Mapping[str, Any]:
    path = capsule.layout.directory("data") / "stress-result.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _namespace_of(pid: int, kind: str = "mnt") -> str | None:
    try:
        return os.readlink(f"/proc/{pid}/ns/{kind}")
    except OSError:
        return None


def _alive(pid: int) -> bool:
    return Path(f"/proc/{pid}").exists()


def _descendants(pid: int) -> list[int]:
    """Every process whose parent chain reaches ``pid``, from /proc alone."""
    parents: dict[int, int] = {}
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            fields = Path(f"/proc/{name}/stat").read_text(encoding="utf-8").rsplit(")", 1)[-1].split()
            parents[int(name)] = int(fields[1])
        except (OSError, ValueError, IndexError):
            continue
    found: list[int] = []
    for child in parents:
        walker, depth = child, 0
        while walker > 1 and depth < 32:
            walker = parents.get(walker, 0)
            depth += 1
            if walker == pid:
                found.append(child)
                break
    return sorted(found)


def _cgroup_memory_events(unit_name: str) -> Mapping[str, Any]:
    """The cgroup's own account of what it did to the process.

    §27 asks for the distinction that a exit code cannot make: a process killed
    by *its* memory limit, and a process killed because the whole machine ran
    out. The kernel keeps the counters that separate them, and they are the only
    place the answer exists.

    ``memory.events`` carries ``max`` — how many times the limit was hit — and
    ``oom_kill`` — how many processes the cgroup killed. A run where ``max`` is
    non-zero and ``oom_kill`` is zero was *throttled*: it hit the ceiling and was
    made to reclaim rather than being killed, which is what MemoryHigh does and
    is a different sentence from "it was killed".

    Read while the scope is still alive. Once it exits the directory is gone and
    with it every counter, so a reader who wanted this afterwards would have
    nothing.
    """
    code, output = _run_command(["systemctl", "--user", "show", unit_name, "-p", "ControlGroup"])
    path = ""
    if code == 0 and "=" in output:
        path = output.split("=", 1)[1].strip()
    if not path:
        return {"available": False, "reason": f"no ControlGroup for {unit_name}"}
    base = Path("/sys/fs/cgroup") / path.lstrip("/")
    if not base.is_dir():
        return {"available": False, "reason": f"{base} is not present"}
    facts: dict[str, Any] = {"available": True, "cgroup": str(base)}
    for name in ("memory.max", "memory.high", "memory.current", "memory.peak", "pids.max", "pids.peak"):
        try:
            facts[name] = (base / name).read_text(encoding="utf-8").strip()
        except OSError:
            facts[name] = None
    try:
        for line in (base / "memory.events").read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition(" ")
            facts[f"events.{key}"] = int(value) if value.strip().isdigit() else value
    except OSError:
        facts["events"] = None
    return facts


def _run_command(argv: Sequence[str], timeout: int = 30) -> tuple[int, str]:
    try:
        result = subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout, check=False)
        return result.returncode, (result.stdout + result.stderr).strip()
    except (OSError, subprocess.SubprocessError) as error:
        return -1, f"{type(error).__name__}: {error}"


def _memory_control(ceiling: int) -> Mapping[str, Any]:
    """Allocate past ``ceiling`` in a plain user scope, with no capsule involved.

    The resource-limit equivalent of the isolation section's negative control,
    and it exists for the same reason: a limit that does not bite tells you
    nothing until you know whether it bites for anybody.
    """
    workspace = Path(tempfile.mkdtemp(prefix="bunny-memory-control-"))
    output = workspace / "control-result.json"
    environment = dict(os.environ)
    environment["BUNNY_STRESS_MODE"] = "memory"
    environment["BUNNY_STRESS_OUTPUT"] = str(output)
    environment["BUNNY_STRESS_CEILING"] = str(ceiling)
    try:
        result = subprocess.run(  # noqa: S603 - the same fixture the capsule runs
            [
                "systemd-run", "--user", "--scope", "--quiet",
                "--unit=bunny-memory-control",
                f"--property=MemoryMax={ceiling}",
                sys.executable, str(STRESS),
            ],
            capture_output=True, text=True, timeout=300, check=False, env=environment,
        )
    except (OSError, subprocess.SubprocessError) as error:
        shutil.rmtree(workspace, ignore_errors=True)
        return {"ran": False, "error": f"{type(error).__name__}: {error}", "enforced": None}
    document: Mapping[str, Any] = {}
    if output.exists():
        try:
            document = json.loads(output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            document = {}
    shutil.rmtree(workspace, ignore_errors=True)
    allocated = document.get("allocatedBytes")
    return {
        "ran": True,
        "ceiling": ceiling,
        "exitCode": result.returncode,
        "allocatedBytes": allocated,
        "stderr": result.stderr.strip()[:300],
        "outcome": document.get("outcome"),
        # Enforced means the allocation stopped *near the ceiling*. A kill is
        # deliberately not sufficient on its own: the first version of this
        # counted any SIGKILL as enforcement, and on a host that ignores
        # MemoryMax the process was duly killed — at 4.5 GB, by the machine's own
        # out-of-memory killer, against a 256 MB ceiling. That reads as the
        # cgroup working and is the opposite of the truth.
        "enforced": isinstance(allocated, int) and allocated <= ceiling * 2,
    }


def _intervention(events: Mapping[str, Any], exit_code: Any, result: Mapping[str, Any]) -> str:
    """Which mechanism stopped the allocation, named from the counters.

    ``cgroup-oom-kill``  the cgroup killed it: oom_kill is non-zero.
    ``cgroup-throttle``  it hit the ceiling and was made to reclaim: max is
                         non-zero, nothing was killed. This is MemoryHigh, and it
                         is enforcement — the process could not get past the
                         limit — but it is not a kill and must not be reported
                         as one.
    ``allocation-error`` the allocator refused, which the process saw itself.
    ``external-kill``    something killed it and the cgroup counted nothing;
                         on a machine that ignores the limit this is the whole
                         system's out-of-memory killer.
    ``none``             nothing intervened.
    """
    if not events.get("available"):
        if result.get("outcome") == "MemoryError":
            return "allocation-error"
        if isinstance(exit_code, int) and exit_code < 0:
            return "external-kill"
        return "unknown-no-counters"
    if int(events.get("events.oom_kill", 0) or 0) > 0:
        return "cgroup-oom-kill"
    if int(events.get("events.max", 0) or 0) > 0 or int(events.get("events.high", 0) or 0) > 0:
        return "cgroup-throttle"
    if result.get("outcome") == "MemoryError":
        return "allocation-error"
    if isinstance(exit_code, int) and exit_code < 0:
        return "external-kill"
    return "none"


def section_crash(harness: Harness, host: Mapping[str, Any]) -> Evidence:
    """Kill the things that hold a permission open, and see what survives."""
    evidence = Evidence(section="crash")
    if not require_confinement(host, evidence):
        return evidence

    measurements: dict[str, Any] = {}
    capsule = _install_stress(harness, "art.comrade.Idler", ResourceLimits(), "idle")
    record = _launch_stress(harness, capsule, "idle")
    if not record.started or record.pid is None:
        return evidence.settle("FAIL", "the capsule did not start")

    time.sleep(2.0)
    launcher_pid = record.pid
    sandboxed = _descendants(launcher_pid)
    host_namespace = _namespace_of(os.getpid())
    sandbox_namespaces = {pid: _namespace_of(pid) for pid in sandboxed}
    measurements["beforeKill"] = {
        "launcherPid": launcher_pid,
        "descendants": sandboxed,
        "hostMountNamespace": host_namespace,
        "descendantMountNamespaces": sandbox_namespaces,
    }
    confined_before = [pid for pid, ns in sandbox_namespaces.items() if ns and ns != host_namespace]
    if not confined_before:
        evidence.findings.append("no descendant was in a mount namespace of its own before the kill")
        evidence.measurements = measurements
        return evidence.settle("FAIL", "the running capsule was not confined to begin with")

    # 1. The companion dies while the capsule runs. The launcher is the
    #    companion's child, so this is the same event from the kernel's side.
    os.kill(launcher_pid, signal.SIGKILL)
    time.sleep(2.0)
    after = {
        "launcherAlive": _alive(launcher_pid),
        "survivors": {},
    }
    for pid in confined_before:
        after["survivors"][str(pid)] = {
            "alive": _alive(pid),
            "mountNamespace": _namespace_of(pid),
            "escapedToHostNamespace": _alive(pid) and _namespace_of(pid) == host_namespace,
        }
    measurements["afterCompanionKill"] = after
    escaped = [pid for pid, row in after["survivors"].items() if row["escapedToHostNamespace"]]
    if escaped:
        evidence.findings.append(f"STOP CONDITION: {escaped} re-entered the host mount namespace")
        evidence.measurements = measurements
        return evidence.settle("FAIL", "a capsule process left its namespace when the launcher died")

    # 2. Stopping the scope terminates the tree, leaving no orphan.
    second = _install_stress(harness, "art.comrade.Idler2", ResourceLimits(), "idle")
    second_record = _launch_stress(harness, second, "idle")
    time.sleep(2.0)
    tree = _descendants(second_record.pid) if second_record.pid else []
    stopped = harness.executor.stop(second_record.unit_name)
    time.sleep(2.0)
    orphans = [pid for pid in tree if _alive(pid)]
    measurements["afterScopeStop"] = {
        "unit": second_record.unit_name,
        "stopReported": stopped,
        "treeBefore": tree,
        "orphansAfter": orphans,
        "orphanNamespaces": {str(pid): _namespace_of(pid) for pid in orphans},
    }
    unconfined_orphans = [
        pid for pid in orphans if _namespace_of(pid) == host_namespace
    ]
    if unconfined_orphans:
        evidence.findings.append(
            f"STOP CONDITION: {unconfined_orphans} survived the scope stop in the host namespace"
        )
        evidence.measurements = measurements
        return evidence.settle("FAIL", "stopping the capsule left an unconfined process behind")

    # 3. The policy store becomes unreadable while the system is running: a new
    #    permission request must deny rather than proceed.
    (harness.home / "Documents" / "crash-probe.odt").write_bytes(b"x")
    store_path = Path(trust.default_store_path())
    saved = store_path.read_text(encoding="utf-8") if store_path.exists() else ""
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text("{ corrupted while running", encoding="utf-8")
    try:
        broken_store = trust.TrustStore(store_path, session_id=harness.runtime.session_id)
        try:
            broken_store.load()
            outcome = {"verdict": "allow", "reason": "the corrupt store loaded"}
        except trust.TrustStoreUnreadable:
            gate = trust.TrustGate(store=broken_store, audit=harness.audit, surface=harness.surface, names={})
            decision = gate.check(
                trust.PermissionRequest.build(
                    request_id="crash-1", application_id="art.comrade.Idler", category="files",
                    session_id=harness.runtime.session_id,
                    resource=trust.path_resource(harness.home / "Documents" / "crash-probe.odt"),
                    purpose="read",
                ),
                declaration=capsule.manifest.declaration(),
            )
            outcome = {"verdict": decision.verdict, "reason": decision.reason_code}
    finally:
        if saved:
            store_path.write_text(saved, encoding="utf-8")
            harness.store.load()
    measurements["policyStoreCorruptedWhileRunning"] = outcome
    evidence.measurements = measurements
    if outcome["verdict"] != "deny":
        evidence.findings.append("a corrupt policy store did not deny a live request")
        return evidence.settle("FAIL", "the policy path did not fail closed at runtime")

    return evidence.settle(
        "PASS",
        f"killing the launcher left no process in the host namespace "
        f"({len(after['survivors'])} checked); stopping the scope left "
        f"{len(orphans)} orphan(s), none unconfined; a policy store corrupted "
        f"mid-run denied with {outcome['reason']}",
    )


def section_resources(harness: Harness, host: Mapping[str, Any]) -> Evidence:
    """Exceed the declared limits on purpose and record what intervened."""
    evidence = Evidence(section="resources")
    if not require_confinement(host, evidence):
        return evidence

    measurements: dict[str, Any] = {}

    # Launch latency, cold and warm. Cold is the first launch of a capsule that
    # has just been provisioned; warm is the second.
    latency_capsule = _install_stress(harness, "art.comrade.Latency", ResourceLimits(), "idle")
    timings = []
    for attempt in range(3):
        started = time.monotonic()
        record = _launch_stress(harness, latency_capsule, "idle")
        elapsed = (time.monotonic() - started) * 1000
        timings.append(round(elapsed, 1))
        if record.pid:
            harness.executor.stop(record.unit_name)
            try:
                harness.executor.wait(record.pid, timeout=10)
            except Exception:  # noqa: BLE001
                pass
        harness.runtime.stop(harness.runtime.open("art.comrade.Latency"))
    measurements["launchLatencyMs"] = {"cold": timings[0], "subsequent": timings[1:]}

    # Steady-state overhead: what the sandbox itself costs while idle.
    idle_capsule = _install_stress(harness, "art.comrade.Steady", ResourceLimits(), "idle")
    idle_record = _launch_stress(harness, idle_capsule, "idle")
    time.sleep(4.0)
    inside_rss = _stress_result(idle_capsule).get("rssBytes")
    tree = _descendants(idle_record.pid) if idle_record.pid else []
    total_rss = 0
    for pid in [idle_record.pid, *tree]:
        if pid is None:
            continue
        try:
            for line in Path(f"/proc/{pid}/status").read_text(encoding="utf-8").splitlines():
                if line.startswith("VmRSS:"):
                    total_rss += int(line.split()[1]) * 1024
        except (OSError, ValueError, IndexError):
            continue
    measurements["steadyState"] = {
        "applicationRssBytes": inside_rss,
        "treeRssBytes": total_rss,
        "treeSize": len(tree) + 1,
        "capsuleDiskBytes": dict(idle_capsule.layout.usage()).get("total"),
    }
    if idle_record.pid:
        harness.executor.stop(idle_record.unit_name)

    # Memory ceiling. 256 MiB, and the fixture allocates past it.
    memory_limits = ResourceLimits(
        memory_high=192 * 1024 * 1024, memory_max=256 * 1024 * 1024, tasks_max=64, cpu_weight=100
    )
    memory_capsule = _install_stress(harness, "art.comrade.Hungry", memory_limits, "memory")
    (memory_capsule.layout.directory("data") / "stress-ceiling").write_text(
        str(memory_limits.memory_max), encoding="utf-8"
    )
    memory_record = _launch_stress(harness, memory_capsule, "memory")
    exit_code = None
    cgroup_events: Mapping[str, Any] = {"available": False, "reason": "not read"}
    if memory_record.pid:
        try:
            exit_code = harness.executor.wait(memory_record.pid, timeout=180)
            # The scope is gone the moment the process exits, so anything the
            # kernel counted has to be read before that. A clean exit means the
            # counters are already unreadable and the record says so.
            cgroup_events = _cgroup_memory_events(memory_record.unit_name)
        except Exception:  # noqa: BLE001
            exit_code = "TIMEOUT"
            # Still running, which is the case where the counters exist.
            cgroup_events = _cgroup_memory_events(memory_record.unit_name)
            harness.executor.stop(memory_record.unit_name)
    memory_result = _stress_result(memory_capsule)
    measurements["memory"] = {
        "declaredMax": memory_limits.memory_max,
        "declaredHigh": memory_limits.memory_high,
        "exitCode": exit_code,
        "allocatedBytes": memory_result.get("allocatedBytes"),
        "outcome": memory_result.get("outcome"),
        "cgroup": memory_result.get("cgroup"),
        "cgroupEvents": cgroup_events,
        # What actually intervened, in one word, derived from the counters rather
        # than from the exit code. An exit code cannot tell a cgroup kill from a
        # machine running out of memory; these can.
        "intervention": _intervention(cgroup_events, exit_code, memory_result),
    }

    # Task ceiling. 64 tasks, and the fixture spawns past it.
    task_limits = ResourceLimits(
        memory_high=512 * 1024 * 1024, memory_max=1024 * 1024 * 1024, tasks_max=48, cpu_weight=100
    )
    task_capsule = _install_stress(harness, "art.comrade.Busy", task_limits, "tasks")
    task_record = _launch_stress(harness, task_capsule, "tasks")
    task_exit = None
    if task_record.pid:
        try:
            task_exit = harness.executor.wait(task_record.pid, timeout=180)
        except Exception:  # noqa: BLE001
            task_exit = "TIMEOUT"
            harness.executor.stop(task_record.unit_name)
    task_result = _stress_result(task_capsule)
    measurements["tasks"] = {
        "declaredMax": task_limits.tasks_max,
        "exitCode": task_exit,
        "threadsStarted": task_result.get("threadsStarted"),
        "outcome": task_result.get("outcome"),
    }
    # The negative control for a resource limit. The same ceiling, the same
    # allocation, in a plain systemd user scope with no capsule and no bwrap. If
    # this also runs past the limit, the host does not enforce it and nothing
    # Bunny does could have; if it stops and the capsule does not, the wrapper is
    # the defect. Without this row the section cannot tell those apart, and would
    # report a kernel limitation as a Bunny failure.
    measurements["hostControl"] = _memory_control(memory_limits.memory_max)
    evidence.measurements = measurements

    problems: list[str] = []
    unenforced_by_host: list[str] = []
    allocated = memory_result.get("allocatedBytes")
    memory_overran = (
        memory_result.get("outcome") == "ceiling-reached-without-intervention"
        or (isinstance(allocated, int) and allocated > memory_limits.memory_max * 2)
    )
    if memory_overran:
        if measurements["hostControl"]["enforced"] is False:
            unenforced_by_host.append(
                f"MemoryMax is accepted and not enforced by this kernel: a plain systemd user "
                f"scope with no capsule and no bwrap allocated "
                f"{measurements['hostControl']['allocatedBytes']} bytes against the same "
                f"{memory_limits.memory_max}-byte ceiling. The limit was applied correctly "
                f"(memory.max read back as set); the kernel does not act on it. This is a "
                f"property of the host, not of the capsule wrapper."
            )
        else:
            problems.append(
                f"the memory limit did not intervene inside a capsule ({allocated} bytes against "
                f"{memory_limits.memory_max}) although a plain scope on this host does enforce it"
            )
    threads = task_result.get("threadsStarted")
    if task_result.get("outcome") == "ceiling-reached-without-intervention":
        problems.append(f"the task limit did not intervene: {threads} threads started")
    elif isinstance(threads, int) and threads > task_limits.tasks_max * 4:
        problems.append(
            f"{threads} threads started against a declared maximum of {task_limits.tasks_max}"
        )

    if problems:
        evidence.findings.extend(problems)
        return evidence.settle("FAIL", "; ".join(problems))
    if unenforced_by_host:
        # Not a FAIL: Bunny applied the limit and the kernel ignored it. Not a
        # PASS either, because nothing was enforced. BLOCKED is the verdict for
        # "this host cannot answer the question", and this host cannot.
        evidence.findings.extend(unenforced_by_host)
        return evidence.settle(
            "BLOCKED",
            f"tasks enforced at {threads} against {task_limits.tasks_max} declared; memory not "
            f"enforced by this kernel (see findings); cold launch {timings[0]} ms; steady state "
            f"{measurements['steadyState']['treeRssBytes']} bytes over "
            f"{measurements['steadyState']['treeSize']} processes",
        )

    return evidence.settle(
        "PASS",
        f"cold launch {timings[0]} ms, then {timings[1:]}; steady state "
        f"{measurements['steadyState']['treeRssBytes']} bytes over "
        f"{measurements['steadyState']['treeSize']} processes; memory intervened at "
        f"{allocated} bytes against {memory_limits.memory_max} declared "
        f"(exit {exit_code}, {measurements['memory']['intervention']}); "
        f"tasks intervened at {threads} against {task_limits.tasks_max}",
    )
