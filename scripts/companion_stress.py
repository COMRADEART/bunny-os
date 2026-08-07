#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Repeat a companion target and record what the process owns each time.

A development tool, not shipped: ``install-root.py`` copies named scripts and
this is not one of them.

The intermittent companion-suite failure had resisted diagnosis because it never
appeared in isolation — only inside the full in-process suite, and only
sometimes. That shape says the fault is *accumulated state in the interpreter*
rather than anything a single test does, so this harness measures exactly that:
what threads, file descriptors, sockets, temporary directories and runtime locks
exist before and after each iteration, and how those inventories trend.

It deliberately reports raw inventories rather than a verdict. A leak is a line
that goes up; a race is a failure with a flat inventory. Those need different
fixes, and a harness that printed "leak detected" would be guessing which.

Usage::

    companion_stress.py --target service --runs 100
    companion_stress.py --target suite --runs 50 --order random
    companion_stress.py --target slice --runs 20 --isolate
"""

from __future__ import annotations

import argparse
import gc
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from typing import Any

# Where the code under test comes from, and the order is the whole of it.
#
# The checkout this script lives in wins, always. The installed tree is a
# fallback for running the harness on a machine that has no checkout.
#
# The obvious version of this loop was wrong in a way that produced a *silent
# wrong answer* rather than an error. It inserted each candidate at the front
# only if it was not already in ``sys.path`` — so with ``PYTHONPATH`` pointing at
# the checkout, the checkout was skipped as already-present and the installed
# tree went in ahead of it. Every gate then measured
# ``/usr/lib/bunny-os/python``: a build from some earlier phase, without the
# package under test in it. A hundred iterations reported
# ``ModuleNotFoundError`` and, had the module happened to exist there, would
# have reported a hundred clean passes for code nobody had changed.
#
# So the checkout is *moved* to the front rather than conditionally inserted.
_REPOSITORY = Path(__file__).resolve().parents[1]
_INSTALLED = Path("/usr/lib/bunny-os/python")
for _candidate in (_INSTALLED, _REPOSITORY):
    if not _candidate.is_dir():
        continue
    name = str(_candidate)
    while name in sys.path:
        sys.path.remove(name)
    sys.path.insert(0, name)

#: The service-driven subset — every module that starts a real runtime, binds a
#: socket or drives a slice. These are the tests the flake lives in; the other
#: ~350 are pure and have never failed.
SERVICE_MODULES = (
    "tests.companion.test_protocol_ipc",
    "tests.companion.test_integration_slice",
    "tests.companion.test_character_cli_vertical",
)

def _discover_suite_modules() -> tuple[str, ...]:
    """Every companion test module there is, found rather than listed.

    This was a hand-written list, and a hand-written list of "the complete
    suite" is wrong the moment somebody adds a module — silently, and in the
    direction that makes a gate easier to pass. Five modules written during this
    phase were missing from it, including the ones covering the defect the gate
    exists to catch.

    Service modules first, then the rest in a stable order: the service-driven
    tests are where every failure has ever been, and running them first means a
    failing iteration fails sooner.
    """
    directory = Path(__file__).resolve().parents[1] / "tests" / "companion"
    found = sorted(
        f"tests.companion.{path.stem}"
        for path in directory.glob("test_*.py")
    )
    rest = tuple(name for name in found if name not in SERVICE_MODULES)
    return SERVICE_MODULES + rest


SUITE_MODULES = _discover_suite_modules()


# --------------------------------------------------------------------------- #
# Inventories
# --------------------------------------------------------------------------- #


def thread_inventory() -> dict[str, Any]:
    """Every live thread, by name and daemon status.

    Named rather than counted. "Three threads leaked" is a number; "three
    threads called bunny-companion-worker leaked" is a diagnosis.
    """
    threads = sorted(
        (item.name, bool(item.daemon), item.is_alive())
        for item in threading.enumerate()
    )
    return {
        "count": len(threads),
        "nonDaemon": sum(1 for _name, daemon, _alive in threads if not daemon),
        "names": [name for name, _daemon, _alive in threads],
    }


def descriptor_inventory() -> dict[str, Any]:
    """Open file descriptors, split into sockets, files and anonymous.

    Reads ``/proc/self/fd``. Returns ``NOT_RUN`` where there is no ``/proc``,
    because an fd count guessed from Python objects would be a different
    measurement wearing the same label.
    """
    root = Path("/proc/self/fd")
    if not root.is_dir():
        return {"result": "NOT_RUN", "reason": "this platform has no /proc/self/fd"}
    sockets: list[str] = []
    files: list[str] = []
    other: list[str] = []
    total = 0
    for entry in sorted(root.iterdir(), key=lambda item: item.name):
        total += 1
        try:
            target = os.readlink(entry)
        except OSError:
            continue
        if target.startswith("socket:"):
            sockets.append(target)
        elif target.startswith("/"):
            files.append(target)
        else:
            other.append(target)
    return {
        "total": total,
        "sockets": len(sockets),
        "files": len(files),
        "other": len(other),
        # Only the paths under a companion store or runtime directory: the rest
        # is the interpreter's own and is noise for this purpose.
        "companionFiles": sorted(
            item for item in files
            if "companion" in item or "bunny" in item
        )[:24],
    }


def socket_inventory() -> dict[str, Any]:
    """Listening and connected sockets belonging to this process.

    ``/proc/net/unix`` names the paths, which is what matters here: a leaked
    listener shows up as a path that should have been unlinked.
    """
    result: dict[str, Any] = {}
    unix = Path("/proc/net/unix")
    if unix.is_file():
        try:
            lines = unix.read_text(encoding="utf-8", errors="replace").splitlines()[1:]
        except OSError:
            lines = []
        paths = [
            parts[-1] for parts in (line.split() for line in lines)
            if parts and parts[-1].startswith("/") and "bunny-companion" in parts[-1]
        ]
        result["unixCompanionPaths"] = sorted(set(paths))
        result["unixCompanionCount"] = len(paths)
    else:
        result["unix"] = "NOT_RUN: no /proc/net/unix"
    tcp = Path("/proc/net/tcp")
    if tcp.is_file():
        try:
            lines = tcp.read_text(encoding="utf-8", errors="replace").splitlines()[1:]
        except OSError:
            lines = []
        # State 0A is LISTEN, 06 is TIME_WAIT — the two that matter for the
        # loopback fallback's port pressure.
        states = [line.split()[3] for line in lines if len(line.split()) > 3]
        result["tcpListen"] = states.count("0A")
        result["tcpTimeWait"] = states.count("06")
    else:
        result["tcp"] = "NOT_RUN: no /proc/net/tcp"
    return result


def runtime_inventory() -> dict[str, Any]:
    """Companion-owned state that should be empty between iterations."""
    import gc as _gc

    leases: list[str] = []
    waiters: list[str] = []
    held_answers: list[str] = []
    pending_approvals: list[str] = []
    executors: set[str] = set()
    locked_stores: list[str] = []
    services = 0
    runtimes = 0
    for item in _gc.get_objects():
        try:
            name = type(item).__name__
        except Exception:  # pragma: no cover - exotic proxies
            continue
        if name == "CompanionService":
            services += 1
        elif name == "CompanionRuntime":
            runtimes += 1
            try:
                leases.extend(getattr(item, "leases").leases)
            except Exception:
                pass
            try:
                # §11 wants the count of questions still outstanding. A run that
                # ends with one is a run that left an approve button behind.
                pending_approvals.extend(
                    request.request_id for request in item.approvals.pending()
                )
            except Exception:
                pass
            try:
                executors.update(getattr(item, "_executors", {}))
            except Exception:
                pass
        elif name == "InteractiveConsent":
            try:
                waiters.extend(getattr(item, "_waiting", {}))
                held_answers.extend(getattr(item, "_answered_early", {}))
            except Exception:
                pass
        elif name == "CompanionStore":
            try:
                # A lock left held is the shape of an interrupted write, and it
                # is invisible in a thread or descriptor count.
                marker = getattr(item, "root", None)
                if marker is not None and (Path(marker) / "session.lock").exists():
                    locked_stores.append(str(marker))
            except Exception:
                pass
    return {
        "liveServices": services,
        "liveRuntimes": runtimes,
        "executorLeases": sorted(leases),
        "consentWaiters": sorted(waiters),
        "heldAnswers": sorted(held_answers),
        "pendingApprovals": sorted(pending_approvals),
        "activeExecutors": sorted(executors),
        "lockedStores": sorted(locked_stores),
    }


#: Programs the voice runtime is allowed to start. Kept in step with
#: :data:`companion.voice.execution.ALLOWED_EXECUTABLES`; a name here that is
#: not there would count a child that could not exist, and the reverse would
#: miss a leak.
_VOICE_CHILDREN = frozenset({
    "espeak-ng", "espeak", "spd-say", "say",
    "paplay", "pacat", "pw-play", "aplay", "pactl", "pw-dump",
})


def voice_inventory() -> dict[str, Any]:
    """§22's voice-specific counts: children, audio, temporary files, queue.

    Child processes are read from ``/proc`` rather than from any bookkeeping
    this runtime keeps, which is the whole point: a child the runtime *thinks*
    it reaped and a child the kernel still has are exactly the pair a leak lives
    between, and asking the runtime would return the runtime's own opinion.

    Audio handles are counted the same way, as live player processes. There is
    no file descriptor to count — every backend here is a one-shot player
    holding its own connection to the audio server — so "an audio handle" is
    "a player that is still running", and after an utterance ends there must be
    none.
    """
    children: list[str] = []
    players: list[str] = []
    zombies: list[str] = []
    proc = Path("/proc")
    if proc.is_dir():
        own = os.getpid()
        for entry in proc.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                status = (entry / "status").read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            parent = 0
            name = ""
            state = ""
            for line in status.splitlines():
                if line.startswith("PPid:"):
                    parent = int(line.split()[1])
                elif line.startswith("Name:"):
                    name = line.split(maxsplit=1)[1].strip() if len(line.split()) > 1 else ""
                elif line.startswith("State:"):
                    state = line.split()[1] if len(line.split()) > 1 else ""
                if parent and name and state:
                    break
            if parent != own:
                continue
            children.append(name)
            if state == "Z":
                zombies.append(name)
            if name in _VOICE_CHILDREN:
                players.append(name)
    else:
        return {
            "result": "NOT_RUN",
            "reason": "this platform has no /proc, so child and audio handles cannot be counted",
            "temporaryWorkspaces": len(list(Path(tempfile.gettempdir()).glob("bunny-voice-*"))),
            **_voice_object_inventory(),
        }

    workspaces = sorted(Path(tempfile.gettempdir()).glob("bunny-voice-*"))
    return {
        "childProcesses": len(children),
        "childNames": sorted(set(children)),
        "zombies": len(zombies),
        "audioHandles": len(players),
        "audioNames": sorted(set(players)),
        "temporaryWorkspaces": len(workspaces),
        "temporaryFiles": sum(
            1 for item in workspaces for _ in item.rglob("*") if item.is_dir()
        ),
        **_voice_object_inventory(),
    }


def _voice_object_inventory() -> dict[str, Any]:
    """Queue depth and active requests, from whatever workers are still alive.

    Both must be zero between iterations. A queue that still has depth is an
    utterance the previous run neither spoke nor recorded, and an active request
    is a worker that never let go of one.
    """
    import gc as _gc

    depth = 0
    active = 0
    workers = 0
    services = 0
    for item in _gc.get_objects():
        try:
            name = type(item).__name__
        except Exception:  # pragma: no cover - exotic proxies
            continue
        if name == "VoiceWorker":
            workers += 1
            try:
                depth += len(item.queue)
                active += 1 if getattr(item, "_current", None) is not None else 0
            except Exception:
                continue
        elif name == "VoiceService":
            services += 1
    return {
        "liveVoiceWorkers": workers,
        "liveVoiceServices": services,
        "queueDepth": depth,
        "activeRequests": active,
    }


#: Programs the speech-input runtime is allowed to start. Kept in step with
#: :data:`companion.speech.execution.CAPTURE_EXECUTABLES` for the reason the
#: voice list is: a mismatch either counts an impossible child or misses a leak.
_CAPTURE_CHILDREN = frozenset({
    "parec", "pw-record", "arecord", "pactl", "pw-dump",
})


def speech_inventory() -> dict[str, Any]:
    """§23's speech-input counts: recorders, workspaces, captures, indicator.

    Recorder children are read from ``/proc`` exactly as the voice players are,
    and for the same reason: "an audio-input handle" here is "a recorder that
    is still running", and between iterations there must be none. The object
    counts come from the collector — live workers, active captures, recogniser
    sessions still open, indicator state, buffered bytes — because those are
    the leaks a process table cannot show.
    """
    import gc as _gc

    recorders: list[str] = []
    proc = Path("/proc")
    if proc.is_dir():
        own = os.getpid()
        for entry in proc.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                status = (entry / "status").read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            parent = 0
            name = ""
            for line in status.splitlines():
                if line.startswith("PPid:"):
                    parent = int(line.split()[1])
                elif line.startswith("Name:"):
                    name = line.split(maxsplit=1)[1].strip() if len(line.split()) > 1 else ""
                if parent and name:
                    break
            if parent == own and name in _CAPTURE_CHILDREN:
                recorders.append(name)

    workers = 0
    services = 0
    active = 0
    open_sessions = 0
    listening = False
    buffered = 0
    pending_transcripts = 0
    for item in _gc.get_objects():
        try:
            name = type(item).__name__
        except Exception:  # pragma: no cover - exotic proxies
            continue
        if name == "CaptureWorker":
            workers += 1
            try:
                current = getattr(item, "_current", None)
                if current is not None:
                    active += 1
                    handle = getattr(current, "handle", None)
                    if handle is not None:
                        buffered += handle.buffer.buffered_bytes
            except Exception:
                continue
        elif name == "SpeechInputService":
            services += 1
            try:
                listening = listening or item.indicator.listening
                pending_transcripts += item.ledger.describe()["pending"]
            except Exception:
                continue
        elif name == "_VoskSession":
            try:
                if not getattr(item, "closed", False) and getattr(item, "_engine", None) is not None:
                    open_sessions += 1
            except Exception:
                continue
    workspaces = sorted(Path(tempfile.gettempdir()).glob("bunny-speech-*"))
    return {
        "captureChildren": len(recorders),
        "captureNames": sorted(set(recorders)),
        "audioInputHandles": len(recorders),
        "temporarySpeechWorkspaces": len(workspaces),
        "liveCaptureWorkers": workers,
        "liveSpeechServices": services,
        "activeCaptures": active,
        "openRecognizerSessions": open_sessions,
        "listeningIndicator": listening,
        "bufferedBytes": buffered,
        "pendingTranscripts": pending_transcripts,
    }


#: Mirrors ``companion.agents.adapters.llamacli.ALLOWED_PROGRAMS`` — the one
#: subprocess site the agent-provider subsystem has.
_AGENT_CHILDREN = frozenset({"llama-cli"})


def agents_inventory() -> dict[str, Any]:
    """§24's agent-provider counts: children, workers, connections, streams.

    Children are read from ``/proc`` exactly as the voice players are. HTTP
    connections are read from the wire sessions' own registries — a connection
    that outlives its generation is the leak the per-request design forbids —
    and the queue depth and active-stream count are absolutes: anything but
    zero between iterations is wrong whatever the baseline held.
    """
    import gc as _gc

    children: list[str] = []
    proc = Path("/proc")
    if proc.is_dir():
        own = os.getpid()
        for entry in proc.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                status = (entry / "status").read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            parent = 0
            name = ""
            for line in status.splitlines():
                if line.startswith("PPid:"):
                    parent = int(line.split()[1])
                elif line.startswith("Name:"):
                    name = line.split(maxsplit=1)[1].strip() if len(line.split()) > 1 else ""
                if parent and name:
                    break
            if parent == own and name in _AGENT_CHILDREN:
                children.append(name)

    workers = 0
    running_workers = 0
    services = 0
    connections = 0
    queue_depth = 0
    active_streams = 0
    proposals = 0
    for item in _gc.get_objects():
        try:
            name = type(item).__name__
        except Exception:  # pragma: no cover - exotic proxies
            continue
        if name == "AgentWorker":
            workers += 1
            try:
                if item.running:
                    running_workers += 1
                status = item.status()
                queue_depth += int(status.get("queueDepth", 0))
                active_streams += int(status.get("trackedJobs", 0))
            except Exception:
                continue
        elif name == "AgentProviderService":
            services += 1
        elif name == "WireSession":
            try:
                connections += int(item.live_connections)
            except Exception:
                continue
        elif name == "StreamAssembler":
            try:
                proposals += len(getattr(item, "_proposals", ()))
            except Exception:
                continue
    return {
        "agentChildren": len(children),
        "agentChildNames": sorted(set(children)),
        "liveAgentWorkers": workers,
        "runningAgentWorkers": running_workers,
        "liveAgentServices": services,
        "httpConnections": connections,
        "providerQueueDepth": queue_depth,
        "activeStreams": active_streams,
        "toolProposalsHeld": proposals,
    }


#: Programs the desktop broker may start. A child of one of these names between
#: iterations is a clipboard owner that was not released or a settings window
#: this process is still waiting on.
_DESKTOP_CHILDREN = frozenset({
    "wl-copy", "xclip", "pactl", "gsettings", "notify-send",
    "gnome-control-center", "systemsettings", "systemsettings5",
})


def desktop_inventory() -> dict[str, Any]:
    """What the desktop broker holds: handles, owners, connections, ledger.

    §23's columns. Every one names something this process *owns* and must give
    up: a portal request it opened, a selection a child of ours is holding, a
    bus connection, an attempt still in flight, an approval it has spent.

    ``ledgerConsistent`` is the odd one out and is the most useful. It is not a
    count but a *property*: every entry in every live ledger is either settled
    or unknown, and none is left in ``started`` with nothing running. A ledger
    that failed this between iterations would mean an attempt was begun and the
    process forgot about it — which is precisely the state §20 turns into
    ``unknown`` on the next start-up, and which should never exist while the
    process is still alive.
    """
    import gc as _gc

    children: list[str] = []
    proc = Path("/proc")
    if proc.is_dir():
        own = os.getpid()
        for entry in proc.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                status = (entry / "status").read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            parent = 0
            name = ""
            for line in status.splitlines():
                if line.startswith("PPid:"):
                    parent = int(line.split()[1])
                elif line.startswith("Name:"):
                    name = line.split(maxsplit=1)[1].strip() if len(line.split()) > 1 else ""
                if parent and name:
                    break
            if parent == own and name in _DESKTOP_CHILDREN:
                children.append(name)

    brokers = 0
    portal_handles = 0
    clipboard_owners = 0
    notifications = 0
    bus_connections = 0
    inflight = 0
    approvals_spent = 0
    unknown_actions = 0
    started_actions = 0
    prepared_actions = 0
    for item in _gc.get_objects():
        try:
            name = type(item).__name__
        except Exception:  # pragma: no cover - exotic proxies
            continue
        if name == "DesktopActionBroker":
            brokers += 1
            try:
                counts = item.adapters.resource_counts()
                portal_handles += int(counts.get("portalHandles", 0))
                clipboard_owners += int(counts.get("clipboardOwners", 0))
                notifications += int(counts.get("notificationsTracked", 0))
                bus_connections += int(counts.get("dbusConnections", 0))
                inflight += len(item._inflight)  # noqa: SLF001 - the harness measures internals
                approvals_spent += len(item.consumed)
                for entry in item.ledger.entries.values():
                    if entry.state == "unknown":
                        unknown_actions += 1
                    elif entry.state == "started":
                        started_actions += 1
            except Exception:
                continue
        elif name == "DesktopSupport":
            try:
                prepared_actions += len(item._prepared)  # noqa: SLF001
            except Exception:
                continue
    return {
        "desktopChildren": len(children),
        "desktopChildNames": sorted(set(children)),
        "liveDesktopBrokers": brokers,
        "portalHandles": portal_handles,
        "clipboardOwners": clipboard_owners,
        "notificationsTracked": notifications,
        "dbusConnections": bus_connections,
        "pendingActions": inflight,
        "approvalsSpent": approvals_spent,
        "unknownActions": unknown_actions,
        "startedActions": started_actions,
        "preparedActions": prepared_actions,
        # See the docstring: a property, not a count.
        "ledgerConsistent": started_actions == 0,
    }


def renderer3d_inventory() -> dict[str, Any]:
    """§34's 3D counters: contexts, GL objects, models, timers, workers.

    Read from live Python objects rather than from the driver, because OpenGL
    has no way to enumerate what a process owns — which is exactly why
    :class:`companion.character.three_d.gpu.GpuResources` exists. Every GL name
    this build creates passes through that ledger, so counting the ledgers is
    counting the objects, and a name created outside one would be invisible
    here *and* would never be released, which is what the leak columns are for.

    ``glTable`` is a property rather than a count and is the §30 assertion in
    counter form: a suite that never selected a 3D presentation must leave the
    entry-point table unloaded, and a run where it is loaded when it should not
    be is a run that opened ``libGL`` for nothing.
    """
    import gc as _gc

    contexts = 0
    live_contexts = 0
    renderers = 0
    models = 0
    gl_objects = 0
    textures = 0
    buffers = 0
    vertex_arrays = 0
    programs = 0
    framebuffers = 0
    estimated_bytes = 0
    behaviours = 0
    state_machines = 0
    gtk_areas = 0
    leak_suspicions: list[str] = []
    for item in _gc.get_objects():
        try:
            name = type(item).__name__
        except Exception:  # pragma: no cover - exotic proxies
            continue
        if name in {"SurfacelessContext", "AdoptedContext"}:
            contexts += 1
            try:
                # Whether it still *holds* a driver context, not whether the
                # Python object exists. A released context has had
                # ``eglDestroyContext`` and ``eglTerminate`` called on it and
                # holds nothing; the object survives only because whoever made
                # it still has a reference — a unittest class attribute, in the
                # case that found this. Counting those as live GPU contexts
                # made a fifty-run suite gate report two leaked contexts when
                # the leak was a fixture and the driver had been told twice.
                #
                # ``lost`` is not the same question and must not be reused for
                # it: §23 gives that word a specific meaning (the compositor or
                # the driver took the context away) and a released context is
                # not a lost one.
                held = getattr(item, "_context", None) or getattr(item, "_gl", None)
                if held is not None and not item.lost:
                    live_contexts += 1
            except Exception:
                pass
        elif name == "ThreeDRenderer":
            renderers += 1
            try:
                if item.model is not None:
                    models += 1
            except Exception:
                pass
        elif name == "GpuResources":
            try:
                payload = item.to_json()
            except Exception:
                continue
            gl_objects += int(payload.get("live", 0))
            textures += int(payload.get("textures", 0))
            buffers += int(payload.get("buffers", 0))
            vertex_arrays += int(payload.get("vertexArrays", 0))
            programs += int(payload.get("programs", 0))
            framebuffers += int(payload.get("framebuffers", 0))
            estimated_bytes += int(payload.get("estimatedBytes", 0))
            leak_suspicions.extend(payload.get("leakSuspicions", ()))
        elif name == "ProceduralBehaviour":
            behaviours += 1
        elif name == "AnimationStateMachine":
            state_machines += 1
        elif name == "ThreeDCharacterArea":
            gtk_areas += 1

    table_loaded = False
    module = sys.modules.get("companion.character.three_d.gl")
    if module is not None:
        table_loaded = getattr(module, "_LOADED", None) is not None
    workers = sum(
        1 for thread in threading.enumerate()
        if any(marker in thread.name.casefold() for marker in ("renderer", "gl-", "three-d"))
    )
    return {
        "gpuContexts": contexts,
        "liveGpuContexts": live_contexts,
        "renderers": renderers,
        "activeModels": models,
        "glObjects": gl_objects,
        "textures": textures,
        "buffers": buffers,
        "vertexArrays": vertex_arrays,
        "shaderPrograms": programs,
        "framebuffers": framebuffers,
        "estimatedGpuBytes": estimated_bytes,
        "animationTimers": behaviours + state_machines,
        "gtkGlAreas": gtk_areas,
        "rendererWorkers": workers,
        "glTable": table_loaded,
        "leakSuspicions": sorted(set(leak_suspicions)),
    }


def memory_inventory() -> dict[str, Any]:
    """RSS from /proc, or NOT_RUN. Never a substitute measurement."""
    try:
        with open("/proc/self/status", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return {"rssBytes": int(line.split()[1]) * 1024}
    except OSError:
        pass
    return {"result": "NOT_RUN", "reason": "this platform has no /proc/self/status"}


_COMMIT_CACHE: list[str] = []


def _commit() -> str:
    """The commit under test, and whether the tree is dirty.

    Read once and cached: shelling out per iteration would add a process spawn
    to every measurement, and the whole point of recording it is that it does
    not change during a run. A dirty tree is reported as such rather than
    silently attributed to the last commit — a gate result belongs to what was
    actually executed.
    """
    if _COMMIT_CACHE:
        return _COMMIT_CACHE[0]
    # An out-of-tree copy — the Linux validation checkout is one — has no
    # repository to ask, and asking anyway is worse than not asking: an empty
    # `.git` beside the copy made `git rev-parse` walk up and answer with an
    # unrelated commit, which was then recorded against fifty iterations. The
    # override is how a caller says which commit it copied, and "unknown" is
    # what an unanswerable question produces.
    declared = os.environ.get("BUNNY_STRESS_COMMIT")
    if declared:
        _COMMIT_CACHE.append(declared)
        return declared
    value = "unknown"
    try:
        import subprocess

        root = Path(__file__).resolve().parents[1]
        if not (root / ".git").exists():
            _COMMIT_CACHE.append(value)
            return value
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=20, check=False,
        )
        if head.returncode == 0:
            value = head.stdout.strip()
            dirty = subprocess.run(
                ["git", "-C", str(root), "status", "--porcelain"],
                capture_output=True, text=True, timeout=20, check=False,
            )
            if dirty.returncode == 0 and dirty.stdout.strip():
                value += "-dirty"
    except Exception:  # noqa: BLE001 - a missing git is not a harness failure
        value = "unknown"
    _COMMIT_CACHE.append(value)
    return value


def snapshot(label: str) -> dict[str, Any]:
    return {
        "label": label,
        "threads": thread_inventory(),
        "descriptors": descriptor_inventory(),
        "sockets": socket_inventory(),
        "runtime": runtime_inventory(),
        "voice": voice_inventory(),
        "speech": speech_inventory(),
        "agents": agents_inventory(),
        "desktop": desktop_inventory(),
        "renderer3d": renderer3d_inventory(),
        "memory": memory_inventory(),
        "tempDirectories": len(list(Path(tempfile.gettempdir()).glob("bunny-*"))),
    }


def _delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    def _get(value: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if not isinstance(value, dict):
                return None
            value = value.get(key)
        return value

    result: dict[str, Any] = {}
    for name, path in (
        ("threads", ("threads", "count")),
        ("nonDaemonThreads", ("threads", "nonDaemon")),
        ("descriptors", ("descriptors", "total")),
        ("socketDescriptors", ("descriptors", "sockets")),
        ("unixCompanionSockets", ("sockets", "unixCompanionCount")),
        ("tcpListen", ("sockets", "tcpListen")),
        ("tcpTimeWait", ("sockets", "tcpTimeWait")),
        ("liveServices", ("runtime", "liveServices")),
        ("liveRuntimes", ("runtime", "liveRuntimes")),
        ("rssBytes", ("memory", "rssBytes")),
        ("tempDirectories", ("tempDirectories",)),
        # §22's voice columns.
        ("childProcesses", ("voice", "childProcesses")),
        ("zombies", ("voice", "zombies")),
        ("audioHandles", ("voice", "audioHandles")),
        ("temporaryWorkspaces", ("voice", "temporaryWorkspaces")),
        ("liveVoiceWorkers", ("voice", "liveVoiceWorkers")),
        ("liveVoiceServices", ("voice", "liveVoiceServices")),
        # §23's speech-input columns.
        ("captureChildren", ("speech", "captureChildren")),
        ("audioInputHandles", ("speech", "audioInputHandles")),
        ("temporarySpeechWorkspaces", ("speech", "temporarySpeechWorkspaces")),
        ("liveCaptureWorkers", ("speech", "liveCaptureWorkers")),
        ("liveSpeechServices", ("speech", "liveSpeechServices")),
        # §24's agent-provider columns.
        ("agentChildren", ("agents", "agentChildren")),
        ("liveAgentWorkers", ("agents", "liveAgentWorkers")),
        ("liveAgentServices", ("agents", "liveAgentServices")),
        ("httpConnections", ("agents", "httpConnections")),
        # §23's desktop columns.
        ("desktopChildren", ("desktop", "desktopChildren")),
        ("liveDesktopBrokers", ("desktop", "liveDesktopBrokers")),
        ("portalHandles", ("desktop", "portalHandles")),
        ("clipboardOwners", ("desktop", "clipboardOwners")),
        ("notificationsTracked", ("desktop", "notificationsTracked")),
        ("dbusConnections", ("desktop", "dbusConnections")),
        # §34's 3D columns. Each names something the renderer *holds*: a GPU
        # context, a driver object, an uploaded model, a behaviour with a timer,
        # a widget with a tick callback.
        ("gpuContexts", ("renderer3d", "gpuContexts")),
        ("liveGpuContexts", ("renderer3d", "liveGpuContexts")),
        ("renderers", ("renderer3d", "renderers")),
        ("activeModels", ("renderer3d", "activeModels")),
        ("glObjects", ("renderer3d", "glObjects")),
        ("textures", ("renderer3d", "textures")),
        ("buffers", ("renderer3d", "buffers")),
        ("vertexArrays", ("renderer3d", "vertexArrays")),
        ("shaderPrograms", ("renderer3d", "shaderPrograms")),
        ("framebuffers", ("renderer3d", "framebuffers")),
        ("animationTimers", ("renderer3d", "animationTimers")),
        ("gtkGlAreas", ("renderer3d", "gtkGlAreas")),
        ("rendererWorkers", ("renderer3d", "rendererWorkers")),
    ):
        start, end = _get(before, *path), _get(after, *path)
        if isinstance(start, int) and isinstance(end, int):
            result[name] = end - start
    # Absolute, like the runtime's own leases below and for the same reason: a
    # queue with depth or a request still active between iterations is wrong
    # whatever it was before, and a delta of zero against a dirty baseline would
    # read as clean.
    for name in ("queueDepth", "activeRequests"):
        result[name] = _get(after, "voice", name) or 0
    # §23's absolutes: an open capture, an open recogniser session, a lit
    # indicator or a byte still buffered between iterations is wrong whatever
    # the baseline held.
    for name in (
        "activeCaptures", "openRecognizerSessions", "bufferedBytes",
    ):
        result[name] = _get(after, "speech", name) or 0
    result["listeningIndicator"] = bool(_get(after, "speech", "listeningIndicator"))
    # §24's absolutes: a queued generation or a live stream between
    # iterations is wrong whatever the baseline held.
    for name in ("providerQueueDepth", "activeStreams"):
        result[name] = _get(after, "agents", name) or 0
    # §23's desktop absolutes: an attempt in flight, a prepared action nobody
    # spent, or an entry still `started` between iterations is wrong whatever
    # the baseline held. `approvalsSpent` is *not* absolute — a spent approval
    # is a record of consent that was used, and clearing it between iterations
    # would be the replay guard forgetting.
    for name in ("pendingActions", "preparedActions", "startedActions"):
        result[name] = _get(after, "desktop", name) or 0
    result["ledgerConsistent"] = bool(_get(after, "desktop", "ledgerConsistent"))
    result["unknownActions"] = _get(after, "desktop", "unknownActions") or 0
    # Absolute rather than differenced. A lease, a waiter, a held answer, an
    # outstanding question or a held store lock should be *empty* between
    # iterations, not merely unchanged — a delta of zero against a baseline that
    # already had one would read as clean.
    for name in (
        "executorLeases", "consentWaiters", "heldAnswers",
        "pendingApprovals", "activeExecutors", "lockedStores",
    ):
        result[name] = _get(after, "runtime", name) or []
    return result


# --------------------------------------------------------------------------- #
# Targets
# --------------------------------------------------------------------------- #


def _run_modules(modules: tuple[str, ...], *, order: str, seed: int) -> dict[str, Any]:
    names = list(modules)
    if order == "random":
        random.Random(seed).shuffle(names)
    elif order == "reverse":
        names.reverse()
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for name in names:
        suite.addTests(loader.loadTestsFromName(name))
    stream = open(os.devnull, "w", encoding="utf-8")
    try:
        result = unittest.TextTestRunner(stream=stream, verbosity=0).run(suite)
    finally:
        stream.close()
    return {
        "order": names,
        "ran": result.testsRun,
        "failures": [str(case) for case, _text in result.failures],
        "errors": [str(case) for case, _text in result.errors],
        "detail": [text for _case, text in (result.failures + result.errors)][:2],
        "ok": result.wasSuccessful(),
    }


def _run_slice() -> dict[str, Any]:
    from companion.character.vertical_slice import run_character_slice

    with tempfile.TemporaryDirectory(prefix="bunny-stress-slice-") as directory:
        report = run_character_slice(Path(directory)).to_json()
    return {
        "ok": report["passed"],
        "failures": report["failures"],
        "notRun": report["notRun"],
        "ran": len(report["steps"]),
    }


def _run_integration_slice() -> dict[str, Any]:
    from companion.vertical_slice import run_slice

    with tempfile.TemporaryDirectory(prefix="bunny-stress-int-") as directory:
        report = run_slice(Path(directory), speak=False).to_json()
    return {"ok": report["passed"], "failures": report["failures"], "ran": len(report["steps"])}


def _run_voice_lifecycle() -> dict[str, Any]:
    """One complete voice-worker lifetime, against the real local providers.

    §22's first gate is "voice-worker lifecycle runs", and the thing being
    repeated is the whole lifetime rather than a test: build a service, speak,
    cancel, degrade, restart the worker, close. That is the sequence a leak
    would accumulate across, and it is deliberately *not* the unit tests —
    those run under gate 2 and mostly use scripted providers, so a child process
    or an audio handle left behind by the real ones would never appear.
    """
    from companion.voice.captions import SpeechDisposition
    from companion.voice.policy import VoicePreferences
    from companion.voice.request import Priority
    from companion.voice.service import VoiceService, VoiceServiceOptions

    problems: list[str] = []
    with tempfile.TemporaryDirectory(prefix="bunny-stress-voice-") as directory:
        service = VoiceService(VoiceServiceOptions(
            runtime_directory=Path(directory),
            preferences=VoicePreferences(speak_progress=True),
        ))
        try:
            from companion.presentation import PresentationState

            def _state(revision: int, text: str) -> PresentationState:
                return PresentationState(
                    session_id="stress-session", task_id="stress-task",
                    phase="presenting_result", base_phase="presenting_result",
                    result_summary=text, revision=revision,
                )

            # 1. speak, and let it finish.
            first = service.publish(_state(1, "The first stress utterance, spoken to the end."))
            service.ledger.mark_shown(first.caption_id)
            request, reason = service.speak(first.caption_id, priority=Priority.TASK_RESULT)
            if request is not None and not service.worker.drain(timeout=60.0):
                problems.append("the first utterance did not settle")

            # 2. speak, and cancel it before it can.
            second = service.publish(_state(2, "The second stress utterance, cancelled part way through it."))
            service.ledger.mark_shown(second.caption_id)
            cancelled, _why = service.speak(second.caption_id, priority=Priority.TASK_RESULT)
            if cancelled is not None:
                service.voice_cancel(requestId=cancelled.request_id)
                if not service.worker.drain(timeout=60.0):
                    problems.append("the cancelled utterance did not settle")

            # 3. lose the audio, and check the captions survive it.
            for backend in service.router.backends:
                setter = getattr(backend, "set_reachable", None)
                if setter is not None:
                    setter(False)
            service.refresh()
            third = service.publish(_state(3, "The third stress utterance, with no audio device."))
            service.ledger.mark_shown(third.caption_id)
            service.speak(third.caption_id, priority=Priority.TASK_RESULT)
            service.worker.drain(timeout=30.0)
            if service.ledger.get(third.caption_id) is None:
                problems.append("the caption did not survive the audio loss")
            for backend in service.router.backends:
                setter = getattr(backend, "set_reachable", None)
                if setter is not None:
                    setter(True)

            # 4. restart the worker, and check nothing replays.
            before = sum(service.queue.counts().values())
            report = service.restart_worker(timeout=30.0)
            if report.replayed:
                problems.append(f"the restart replayed {len(report.replayed)} utterance(s)")
            service.worker.drain(timeout=15.0)
            if sum(service.queue.counts().values()) != before:
                problems.append("an utterance appeared after the restart")

            status = service.voice_status()
            if status["queueDepth"]:
                problems.append(f"the queue still holds {status['queueDepth']} utterance(s)")
            if status["activeRequests"]:
                problems.append("an utterance was still active at the end of the lifecycle")
            if not status["captionsAuthoritative"] or status["mayMutateTaskState"]:
                problems.append("the worker's own boundary claims changed")
        finally:
            service.close()
    return {"ok": not problems, "failures": problems, "ran": 4}


def _run_voice_slice() -> dict[str, Any]:
    from companion.voice.vertical_slice import run_voice_slice

    with tempfile.TemporaryDirectory(prefix="bunny-stress-vslice-") as directory:
        report = run_voice_slice(Path(directory)).to_json()
    return {
        "ok": report["passed"],
        "failures": [item["name"] for item in report["failed"]],
        "notRun": report["notRun"],
        "ran": len(report["steps"]),
        "detail": [item["detail"] for item in report["failed"]][:2],
    }


def _run_voice_renderer_slice() -> dict[str, Any]:
    from companion.character.voice_slice import run_voice_renderer_slice

    with tempfile.TemporaryDirectory(prefix="bunny-stress-vrslice-") as directory:
        report = run_voice_renderer_slice(Path(directory)).to_json()
    return {
        "ok": report["passed"],
        "failures": [item["name"] for item in report["steps"] if item["status"] == "FAIL"],
        "notRun": report["notRunCount"],
        "ran": report["stepCount"],
        "detail": [
            item["detail"] for item in report["steps"] if item["status"] == "FAIL"
        ][:2],
    }


def _run_speech_lifecycle() -> dict[str, Any]:
    """One complete capture-worker lifetime. §23's first gate.

    The sequence a leak would accumulate across: a silence capture that opens
    and closes a real recorder, a capture cancelled mid-stream, a device loss
    with its policy descent, a worker restart, and a close. Against the real
    backends where this host has one — the recorder child and its pipes are
    where a leak would live, and a scripted device has neither — and against
    the scripted device, labelled as such, where it does not, so the gate
    still exercises ordering and release everywhere.

    Deliberately not the recognition path: recognition against real audio is
    gate 3's whole job, per slice, twenty times. This gate is the *capture
    worker's* lifecycle, a hundred times, cheap enough to run that often.
    """
    from companion.speech.policy import SpeechInputPreferences
    from companion.speech.service import SpeechInputService, SpeechInputServiceOptions

    problems: list[str] = []
    mode = "real"
    with tempfile.TemporaryDirectory(prefix="bunny-stress-speech-") as directory:
        service = SpeechInputService(SpeechInputServiceOptions(
            runtime_directory=Path(directory),
            preferences=SpeechInputPreferences(),
        ))
        try:
            from tests.companion.speech_support import (
                FrameScript, RecordingSink, ScriptedCaptureBackend,
                ScriptedRecognizer, silence_pcm, speech_pcm,
            )

            sink = RecordingSink()
            service.attach_indicator_sink(sink)
            service.refresh()
            device_id = ""
            for backend in service.router.backends:
                try:
                    health = backend.health(monotonic=time.monotonic())
                    if health.ready:
                        device_id = health.default_device
                        break
                except Exception:  # noqa: BLE001
                    continue
            recognizer_ready = any(item.ready for item in service.registry.health())
            if not device_id or not recognizer_ready:
                # The scripted fallback: same worker, same ordering, no child.
                mode = "scripted"
                script = FrameScript([silence_pcm(0.5)])
                backend = ScriptedCaptureBackend(script=script)
                service.router.backends.clear()
                service.router.backends.append(backend)
                service.registry.add(ScriptedRecognizer())
                device_id = "scripted-mic"
                service.set_preferences(service.options.preferences)
            else:
                service.set_preferences(service.options.preferences)
            if not service.policy.decision.may_capture:
                problems.append(
                    f"the policy refused capture: {service.policy.decision.outcome}"
                )

            def _wait_idle(timeout: float = 30.0) -> bool:
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    if not service.worker.active:
                        return True
                    time.sleep(0.02)
                return not service.worker.active

            # 1. a silence capture: open, hear nothing, end on the timeout.
            first = service.speech_input_start(
                sessionId="stress-session",
                activationSource="explicit-protocol-request",
                deviceId=device_id,
                maxCaptureMs=6_000,
                initialSilenceMs=1_000,
            )
            if not first.get("accepted"):
                problems.append(f"the silence capture was refused: {first.get('detail')}")
            elif not _wait_idle():
                problems.append("the silence capture did not settle")

            # 2. a capture cancelled mid-stream.
            if mode == "scripted":
                script = FrameScript()
                script.hold.set()
                service.router.backends[0].script = script
            second = service.speech_input_start(
                sessionId="stress-session",
                activationSource="explicit-protocol-request",
                deviceId=device_id,
                maxCaptureMs=10_000,
                initialSilenceMs=8_000,
            )
            if second.get("accepted"):
                deadline = time.monotonic() + 10.0
                while time.monotonic() < deadline and not service.worker.active:
                    time.sleep(0.01)
                cancelled = service.speech_input_cancel(
                    requestId=second["requestId"],
                    cancellationToken=second.get("cancellationToken", ""),
                )
                if not cancelled.get("cancelled") and cancelled.get("stage") == "none":
                    problems.append("the mid-stream cancellation found nothing to cancel")
                if not _wait_idle():
                    problems.append("the cancelled capture did not settle")
            else:
                problems.append(f"the second capture was refused: {second.get('detail')}")

            # 3. device loss and the policy descent, then restoration.
            for backend in service.router.backends:
                setter = getattr(backend, "set_reachable", None)
                if setter is not None:
                    setter(False)
            service.refresh()
            if service.policy.decision.may_capture:
                problems.append("the policy still offered capture with every backend gone")
            for backend in service.router.backends:
                setter = getattr(backend, "set_reachable", None)
                if setter is not None:
                    setter(True)

            # 4. restart the worker; nothing resumes.
            report = service.restart_worker(timeout=15.0)
            if service.worker.active:
                problems.append("a capture was running after the restart")
            if report.to_json()["captureResumed"]:
                problems.append("the restart resumed a capture")

            status = service.worker.status()
            if status["capturing"]:
                problems.append("a capture survived the lifecycle")
            if service.indicator.listening:
                problems.append("the indicator stayed lit")
            boundaries = status["boundaries"]
            if boundaries["mayCreateTask"] or boundaries["remoteTransmission"]:
                problems.append("the worker's own boundary claims changed")
        finally:
            service.close()
    return {"ok": not problems, "failures": problems, "ran": 4, "mode": mode}


def _run_speech_slice() -> dict[str, Any]:
    from companion.speech.vertical_slice import run_speech_slice

    with tempfile.TemporaryDirectory(prefix="bunny-stress-sslice-") as directory:
        report = run_speech_slice(Path(directory)).to_json()
    return {
        "ok": report["passed"],
        "failures": [item["name"] for item in report["failed"]],
        "notRun": report["notRun"],
        "ran": report["stepCount"],
        "detail": [item["detail"] for item in report["failed"]][:2],
    }


def _run_agents_lifecycle() -> dict[str, Any]:
    """One complete provider-worker lifetime. §24's first gate.

    The sequence a leak would accumulate across: a bounded real generation
    where this host has a local model runtime (labelled ``real``; the HTTP
    connection and its stream are where a leak would live), a generation
    cancelled mid-stream against the scripted adapter (deterministically in
    flight, which a real model cannot promise), a structured failure against a
    loopback port with nothing behind it, and a worker restart that repeats
    nothing. Everything runs in one service so the counts the snapshot takes
    afterwards describe one object graph.
    """
    import threading as _threading

    from companion.agents.config import (
        AgentConfiguration, ProviderConfiguration, default_configuration,
    )
    from companion.agents.descriptor import EndpointIdentity
    from companion.agents.registry import SelectionRequirement
    from companion.agents.request import GenerationMessage, GenerationRequest
    from companion.agents.service import AgentProviderService, AgentServiceOptions
    from companion.agents.wire import HttpTarget
    from companion.agents.adapters import default_adapters
    from tests.companion.agents_support import ScriptedAdapter, scripted_configuration

    problems: list[str] = []
    mode = "scripted"
    with tempfile.TemporaryDirectory(prefix="bunny-stress-agents-") as directory:
        scripted = ScriptedAdapter()
        held = ScriptedAdapter(adapter_identity="scripted-hold", hold=_threading.Event())
        configuration = AgentConfiguration(
            providers=default_configuration(Path(directory)).providers + (
                scripted_configuration(),
                ProviderConfiguration(
                    provider_id="local.hold",
                    adapter_id="scripted-hold",
                    endpoint=EndpointIdentity(kind="subprocess", locator="scripted"),
                    program="scripted",
                    model_id="scripted-model",
                ),
                ProviderConfiguration(
                    provider_id="local.absent",
                    adapter_id="llamacpp",
                    endpoint=EndpointIdentity(kind="loopback-http", locator="127.0.0.1:19"),
                    http=HttpTarget(scheme="http", host="127.0.0.1", port=19),
                    model_id="absent-model",
                ),
            ),
        )
        adapters = dict(default_adapters())
        adapters["scripted"] = scripted
        adapters["scripted-hold"] = held
        service = AgentProviderService(AgentServiceOptions(
            root=Path(directory),
            configuration=configuration,
            adapters=adapters,
        ))
        try:
            def _request(number: int, provider_id: str, *, deadline: float = 30.0,
                         output_tokens: int = 48) -> GenerationRequest:
                return GenerationRequest(
                    request_id=f"gen-stress-{number:04d}-{os.getpid()}",
                    session_id="", task_id="", lifecycle_epoch=0, plan_id="",
                    provider_id=provider_id,
                    model_id=service.registry.descriptor(
                        provider_id, monotonic=time.monotonic()
                    ).model_id or "scripted-model",
                    purpose="probe",
                    messages=(GenerationMessage(role="user", content="Reply with: ready"),),
                    system_policy_reference="bunny-agent-policy/1",
                    maximum_input_tokens=1024,
                    maximum_output_tokens=output_tokens,
                    deadline_seconds=deadline,
                    created_at="",
                )

            # 1. one bounded generation, real where the host has a runtime.
            explanation = service.registry.select(
                SelectionRequirement(task_class="question"),
                monotonic=time.monotonic(),
            )
            chosen = explanation.selected
            if chosen in ("local.ollama", "local.llamacpp", "local.llamacli"):
                mode = "real"
            elif not explanation.found:
                problems.append("no provider was eligible, not even the scripted one")
                chosen = "local.scripted"
            first = service.worker.generate(_request(1, chosen))
            if not first.ok:
                problems.append(
                    f"the bounded generation on {chosen!r} failed: "
                    f"{first.failure_kind}: {first.detail}"
                )

            # 2. a generation cancelled deterministically mid-stream.
            second_request = _request(2, "local.hold", deadline=20.0)
            held.started.clear()
            outcome_box: list[Any] = []
            runner = _threading.Thread(
                target=lambda: outcome_box.append(service.worker.generate(second_request)),
                name="stress-agents-cancel", daemon=True,
            )
            runner.start()
            if not held.started.wait(timeout=10.0):
                problems.append("the held generation never started streaming")
            service.worker.cancel(second_request.request_id, reason="stress cancellation")
            runner.join(timeout=15.0)
            if runner.is_alive():
                problems.append("the cancelled generation did not settle")
            elif not outcome_box or not outcome_box[0].cancelled:
                problems.append(
                    "the mid-stream cancellation did not produce a cancelled outcome"
                )

            # 3. a structured failure that costs nothing and breaks nothing.
            third = service.worker.generate(_request(3, "local.absent", deadline=10.0))
            if third.ok:
                problems.append("a generation against nothing reported success")
            elif third.failure_kind not in ("connection", "timeout", "model-unavailable"):
                problems.append(f"the failure named {third.failure_kind!r}")
            if not service.worker.running:
                problems.append("the worker died of a provider failure")

            # 4. restart; nothing resumes, nothing repeats.
            service.restart_worker(timeout=15.0)
            status = service.worker.status()
            if not status["running"]:
                problems.append("the worker did not come back from the restart")
            if status["generationsServed"] != 0:
                problems.append("the restarted worker had already served generations")
            if status["queueDepth"] != 0 or status["trackedJobs"] != 0:
                problems.append("work survived the restart")
            boundaries = service.boundaries()
            if any(boundaries.values()):
                problems.append("a boundary claim changed")
        finally:
            service.close()
    return {"ok": not problems, "failures": problems, "ran": 4, "mode": mode}


def _run_agent_slice() -> dict[str, Any]:
    from companion.agents.vertical_slice import run_agent_slice

    with tempfile.TemporaryDirectory(prefix="bunny-stress-aslice-") as directory:
        report = run_agent_slice(Path(directory)).to_json()
    return {
        "ok": report["passed"],
        "failures": [item["name"] for item in report["failed"]],
        "notRun": report["notRun"],
        "ran": report["stepCount"],
        "detail": [item["detail"] for item in report["failed"]][:2],
    }


def _run_desktop_lifecycle() -> dict[str, Any]:
    """One complete desktop-broker lifecycle, against whatever desk this is.

    Six things happen, in the order a real task would meet them, and each is a
    property the gate is *for* rather than a step towards one:

    1. **prepare and execute an approved action.** The whole route: schema,
       normalisation, binding, ledger-before-effect, adapter, observation,
       result. Where the machine can perform it the effect is real; where it
       cannot the result is a typed ``unsupported`` and the run continues,
       because the authority half must hold on a headless runner too.
    2. **refuse the same approval a second time.** The replay guard.
    3. **refuse a changed act.** The binding, with one parameter moved.
    4. **cancel one in flight.** The scope is claimed and released, and the
       result says what it prevented.
    5. **release every resource.** The counters this gate reads must return to
       where they were, which is the leak assertion.
    6. **reopen the ledger.** Completed stays completed; nothing in flight is
       left ``started``.

    A hundred of these is the §23 gate, and what it measures is that none of the
    six leaves anything behind.
    """
    from companion.desktop.broker import BrokerOptions, DesktopActionBroker
    from companion.desktop.ledger import OperationLedger

    problems: list[str] = []
    performed: list[str] = []
    with tempfile.TemporaryDirectory(prefix="bunny-stress-desktop-") as directory:
        ledger_path = Path(directory) / "ledger.json"
        broker = DesktopActionBroker(BrokerOptions(ledger_path=ledger_path))
        broker.start()
        before = broker.adapters.resource_counts()
        try:
            report = broker.environment()
            # 1. An action the environment permits, or the least-effect one it
            # does not — a settings page opens a window and changes nothing.
            action_id = "desktop.settings.open"
            prepared = broker.prepare(
                action_id, {"page": "sound"},
                request_id="dreq-stress-1", session_id="stress-session",
                task_id="stress-task", lifecycle_epoch=0, plan_id="stress-plan",
                operation_id="stress-op-1", cancellation_token="stress-cancel-1",
            )
            result = broker.execute(
                prepared.request.with_approval("stress-approval-1"),
                approved_binding=prepared.binding,
            )
            performed.append(result.state)
            if result.state not in (
                "confirmed", "accepted-not-confirmed", "unsupported", "failed",
            ):
                problems.append(f"the first action reported {result.state!r}")
            if result.state == "confirmed" and not result.observation.verifies:
                problems.append("a confirmed result carried no verifying observation")

            # 2. The replay guard.
            replay = broker.execute(
                prepared.request.with_approval("stress-approval-1"),
                approved_binding=prepared.binding,
            )
            if replay.state not in ("refused", "accepted-not-confirmed", "confirmed", "unsupported"):
                problems.append(f"a replayed approval reported {replay.state!r}")

            # 3. A changed act, with the same approval.
            changed = broker.prepare(
                action_id, {"page": "display"},
                request_id="dreq-stress-2", session_id="stress-session",
                task_id="stress-task", lifecycle_epoch=0, plan_id="stress-plan",
                operation_id="stress-op-2", cancellation_token="stress-cancel-2",
            )
            mismatched = broker.execute(
                changed.request.with_approval("stress-approval-1"),
                approved_binding=prepared.binding,
            )
            if mismatched.state != "refused":
                problems.append(
                    f"an act that changed after approval reported {mismatched.state!r}"
                )

            # 4. A cancellation that lands before the backend.
            third = broker.prepare(
                action_id, {"page": "power"},
                request_id="dreq-stress-3", session_id="stress-session",
                task_id="stress-task", lifecycle_epoch=0, plan_id="stress-plan",
                operation_id="stress-op-3", cancellation_token="stress-cancel-3",
            )
            cancelled = broker.execute(
                third.request.with_approval("stress-approval-3"),
                approved_binding=third.binding,
                cancelled=lambda: True,
            )
            if cancelled.state != "cancelled":
                problems.append(f"a cancelled attempt reported {cancelled.state!r}")
            if cancelled.effect_prevented is not True:
                problems.append("a pre-dispatch cancellation did not claim prevention")

            # 6a. The ledger, while the process still holds it.
            still_started = [
                item for item in broker.ledger.entries.values() if item.state == "started"
            ]
            if still_started:
                problems.append(f"{len(still_started)} attempt(s) left in flight")
            if not broker.environment().posture:
                problems.append("the environment reported no posture")
            if report.posture not in (
                "desktop-actions-available", "limited-desktop-actions",
                "notification-only", "headless-no-desktop-actions",
            ):
                problems.append(f"an unknown posture: {report.posture!r}")
        finally:
            # 5. Release, and check that it released.
            released = broker.stop()
            after = broker.adapters.resource_counts()
            for key, start in before.items():
                if int(after.get(key, 0)) > int(start):
                    problems.append(
                        f"{key} went from {start} to {after.get(key)} across one lifecycle"
                    )

        # 6b. Reopen. Completed stays completed; nothing is repeatable.
        reopened = OperationLedger.load(ledger_path)
        for entry in reopened.entries.values():
            if entry.state == "started":
                problems.append(f"{entry.key} reloaded as started rather than unknown")
            if entry.state in ("completed", "undone") and entry.repeatable:
                problems.append(f"{entry.key} reloaded as repeatable")

    return {
        "ok": not problems,
        "failures": problems,
        "ran": 6,
        "states": performed,
        "released": dict(released),
    }


def _run_desktop_slice() -> dict[str, Any]:
    from companion.desktop.vertical_slice import run_desktop_slice

    with tempfile.TemporaryDirectory(prefix="bunny-stress-dslice-") as directory:
        report = run_desktop_slice(Path(directory)).to_json()
    return {
        "ok": report["passed"],
        "failures": [item["name"] for item in report["failed"]],
        "notRun": report["notRun"],
        "ran": report["stepCount"],
        "posture": report["posture"],
        # §24's latencies, per iteration. Carried out of the slice rather than
        # measured separately: a figure taken once says what one run did, and
        # twenty of them say what the thing does.
        "measurements": report["measurements"],
        "resourceDelta": report["resourceDelta"],
        "detail": [item["detail"] for item in report["failed"]][:2],
    }


def _run_renderer3d_lifecycle() -> dict[str, Any]:
    """One complete 3D renderer lifecycle. §34's first gate, one iteration.

    Eight things happen, in the order a session meets them, and each is a
    property the gate is *for* rather than a step towards one:

    1. **create a context.** The one operation that can fail for reasons that
       have nothing to do with this code — no libEGL, no driver, no display —
       and the one the report must therefore not confuse with a leak.
    2. **validate a package.** The whole model validator, on the shipped
       character, every iteration. A validator that grew a cache would show up
       as a memory trend rather than a correctness failure, so it is run rather
       than skipped after the first time.
    3. **upload it.** Buffers, textures, the morph texture, three programs.
    4. **draw every canonical state.** Each one through the mapper, so the
       animation state machine, the face rig and the procedural behaviour all
       run; and offscreen, so the pixels can be *read* rather than assumed.
    5. **move the mouth.** The viseme path to the geometry.
    6. **degrade and recover.** The rung change, including the renderer being
       rebuilt at the lightweight quality.
    7. **restart.** Release everything and build it again inside the same
       context, which is the operation §23 requires after a fault.
    8. **release.** The ledger must reach zero, and the counters this gate
       reads must return to where they started.

    A hundred of these is the gate, and what it measures is that none of the
    eight leaves anything behind.
    """
    from companion.character.defaults import default_3d_character_path
    from companion.character.mapper import (
        CharacterState,
        StateMapperInput,
        map_character_state,
    )
    from companion.character.package import validate_package_directory
    from companion.character.schema import PackageTrustState
    from companion.character.three_d.context import SurfacelessContext, offscreen_available
    from companion.character.three_d.renderer import ThreeDRenderer

    problems: list[str] = []
    available, reason = offscreen_available()
    root = default_3d_character_path()
    if not available or not root.is_dir():
        return {
            "ok": False, "ran": 0,
            "failures": [
                "no offscreen graphics context: " + reason if not available
                else "the built-in 3D package is not installed"
            ],
            "notRun": ["the 3D renderer lifecycle needs a graphics stack and the 3D package"],
        }

    context = SurfacelessContext()
    renderer = None
    coverage = 0.0
    states: list[str] = []
    try:
        package = validate_package_directory(root, trust_state=PackageTrustState.BUILT_IN)
        if package.model is None:
            problems.append("the built-in package carried no validated model")
            return {"ok": False, "ran": 2, "failures": problems}
        section = package.manifest.three_dimensional

        def build(quality: str) -> Any:
            item = ThreeDRenderer(context=context, quality=quality, seed=0x9E)
            item.load_package(package)
            item.upload(
                package.model,
                animation_map=section.animation_map,
                expression_map=section.expression_map,
                viseme_map=section.viseme_map,
                native_scale=section.native_scale,
                floor_offset=section.floor_offset,
                now=0.0,
            )
            item.begin_offscreen(160, 200)
            return item

        renderer = build("full-3d")
        before = renderer.resources.to_json()["live"]

        for index, phase in enumerate((
            "idle", "understanding", "planning", "working", "reviewing",
            "waiting_for_approval", "speaking", "success", "error",
        )):
            mapped = map_character_state(
                package.manifest,
                StateMapperInput(presentation_phase=phase, status_text="Bunny is here."),
            )
            renderer.display_state(mapped, now_ms=index * 400)
            states.append(mapped.character_state.value)
        _width, _height, pixels = renderer.read_pixels()
        opaque = sum(1 for index in range(3, len(pixels), 4) if pixels[index] > 12)
        coverage = opaque / max(1, len(pixels) // 4)
        if coverage <= 0.01:
            problems.append(f"the character covered {coverage:.3%} of the surface")

        for shape in ("open-small", "open-wide", "rounded", "neutral"):
            renderer.set_mouth_shape(shape)
            renderer.draw(now_ms=4000)
        if renderer.face is not None and renderer.face.mouth_shape != "neutral":
            problems.append("the mouth did not return to neutral")

        renderer.set_quality("lightweight-3d")
        renderer.draw(now_ms=4500)
        if renderer.renderer_name != "lightweight-3d":
            problems.append("the lightweight rung did not take effect")
        renderer.set_quality("full-3d")

        renderer.release()
        if renderer.resources.to_json()["live"]:
            problems.append("a released renderer still held GPU objects")
        renderer = build("full-3d")
        after = renderer.resources.to_json()["live"]
        if after != before:
            problems.append(f"a restart changed the live object count from {before} to {after}")
    except Exception as exc:  # noqa: BLE001 - a fault is data
        problems.append(f"{type(exc).__name__}: {exc}")
    finally:
        if renderer is not None:
            try:
                renderer.release()
                if renderer.resources.to_json()["live"]:
                    problems.append("the final release left GPU objects live")
                problems.extend(renderer.resources.leak_suspicions)
            except Exception as exc:  # noqa: BLE001
                problems.append(f"release failed: {type(exc).__name__}: {exc}")
        context.release()

    return {
        "ok": not problems,
        "failures": problems,
        "ran": 8,
        "states": states,
        "coverage": round(coverage, 5),
    }


def _run_renderer3d_slice() -> dict[str, Any]:
    from companion.character.three_d_slice import run_three_d_slice

    with tempfile.TemporaryDirectory(prefix="bunny-stress-3dslice-") as directory:
        report = run_three_d_slice(Path(directory)).to_json()
    return {
        "ok": report["passed"],
        "failures": report["failures"],
        "notRun": report["notRun"],
        "ran": report["ran"],
        "measurements": report["measurements"],
        "environment": report["environment"],
    }


def _run_alpha_lifecycle() -> dict[str, Any]:
    """One complete Public Alpha session-surface lifecycle.

    Seven things, in the order a login meets them, each chosen because it is a
    property the gate is *for* rather than a step towards one:

    1. **the default-character policy decides and acts.** The first-boot case:
       nothing selected, a rung chosen, a package selected, a claim recorded.
    2. **it declines to act a second time.** The idempotence that stops a
       machine re-selecting on every login.
    3. **it preserves a user selection.** The one rule §3 exists for, exercised
       rather than asserted about — the policy is asked again, with a
       user-selected package in place, and must not move it.
    4. **safe mode arms, is consumed, and clears.** Including the launcher's
       three-failure counter, which is §34's crash-loop breaker.
    5. **settings persist across a read.** Written, re-read, projected into the
       three preference types the subsystems take.
    6. **the recovery report answers.** On a machine with no session, no
       runtime and no desk, because that is when it is wanted.
    7. **a diagnostics bundle is written and holds no credential.**

    A hundred of these is the §42 companion-lifecycle gate. What it measures is
    that none of the seven leaves a thread, a descriptor or a temporary file
    behind — the surfaces added by this phase open sockets to probe providers
    and start helper processes to enumerate audio, and both are things that
    accumulate silently.
    """
    from companion.character.defaults import default_character_paths
    from companion.character.importer import PackageRegistry
    from companion.character.policy import apply_default_character_policy, read_policy_state
    from companion.settings import load_settings, update_settings
    from companion.support.diagnose import diagnose
    from companion.support.export import build_bundle
    from companion.support.safemode import (
        FAILURE_THRESHOLD, clear_safe_mode, consume_safe_mode, read_safe_mode,
        record_launch_outcome, request_safe_mode, safe_mode_environment,
    )

    problems: list[str] = []
    performed: list[str] = []
    with tempfile.TemporaryDirectory(prefix="bunny-stress-alpha-") as directory:
        root = Path(directory)
        registry = PackageRegistry(root / "characters", built_in_paths=default_character_paths())

        # 1 and 2: decide, act, then decline.
        first = apply_default_character_policy(registry, eligible="full-3d")
        if not first.package_id:
            problems.append("the character policy chose no package at the full-3d rung")
        performed.append(f"policy:{first.rung}:{first.package_id or 'none'}")
        second = apply_default_character_policy(registry, eligible="full-3d")
        if second.applied:
            problems.append("the character policy acted twice for one machine")

        # 3: a user selection outranks it.
        chosen = registry.built_ins()[0].package_id
        registry.select(chosen)
        third = apply_default_character_policy(registry, eligible="full-3d")
        if third.applied or not third.preserved_user_choice:
            problems.append(f"the character policy overrode a user selection of {chosen}")
        if registry.selected().package_id != chosen:
            problems.append("the selected package changed under a policy that should not act")
        performed.append("policy:preserved-user-choice")

        # 4: safe mode, including the crash-loop breaker.
        request_safe_mode(reason="stress", origin="cli", root=root)
        if not consume_safe_mode(root).enabled:
            problems.append("a one-shot safe-mode request was not seen by the launch that spends it")
        if read_safe_mode(root).enabled:
            problems.append("a one-shot safe-mode request survived the launch that spends it")
        for _ in range(FAILURE_THRESHOLD):
            record_launch_outcome(succeeded=False, root=root)
        armed = read_safe_mode(root)
        if not (armed.enabled and armed.automatic):
            problems.append(f"{FAILURE_THRESHOLD} failed launches did not arm safe mode")
        if not safe_mode_environment(root=root):
            problems.append("armed safe mode produced no environment")
        clear_safe_mode(root)
        if read_safe_mode(root).enabled:
            problems.append("safe mode survived being cleared")
        performed.append("safe-mode:armed-and-cleared")

        # 5: settings persist.
        update_settings(root, "voice", {"enabled": False, "volume": 0.5})
        reloaded = load_settings(root)
        if reloaded.voice.enabled or abs(reloaded.voice.volume - 0.5) > 1e-6:
            problems.append("a written setting did not survive a re-read")
        if reloaded.voice_preferences().enabled:
            problems.append("the voice projection disagreed with the setting")
        performed.append("settings:persisted")

        # 6 and 7: the recovery report, and a bundle with nothing secret in it.
        report = diagnose(root=root, include_failures=False)
        if not report.sections:
            problems.append("the recovery report produced no sections")
        performed.append(f"diagnose:{len(report.sections)}-sections")
        bundle = build_bundle(root=root, report=report, generated_at="stress")
        if bundle.get("uploaded") is not False:
            problems.append("the diagnostics bundle did not declare that it uploaded nothing")
        from companion.settings import _refuse_secrets

        try:
            _refuse_secrets(bundle)
        except Exception as error:
            problems.append(f"the diagnostics bundle held something credential-shaped: {error}")
        performed.append("export:clean")

        if read_policy_state(registry).user_package_id != chosen:
            problems.append("the policy did not record the user's selection for recovery")

    return {
        "ok": not problems,
        "failures": problems,
        "ran": len(performed),
        "measurements": {"performed": performed},
    }


TARGETS = {
    "service": lambda order, seed: _run_modules(SERVICE_MODULES, order=order, seed=seed),
    "alpha": lambda order, seed: _run_alpha_lifecycle(),
    "suite": lambda order, seed: _run_modules(SUITE_MODULES, order=order, seed=seed),
    "protocol": lambda order, seed: _run_modules(
        ("tests.companion.test_protocol_ipc",), order=order, seed=seed
    ),
    "slice": lambda order, seed: _run_slice(),
    "integration-slice": lambda order, seed: _run_integration_slice(),
    "voice": lambda order, seed: _run_voice_lifecycle(),
    "voice-slice": lambda order, seed: _run_voice_slice(),
    "voice-renderer-slice": lambda order, seed: _run_voice_renderer_slice(),
    "speech": lambda order, seed: _run_speech_lifecycle(),
    "speech-slice": lambda order, seed: _run_speech_slice(),
    "agents": lambda order, seed: _run_agents_lifecycle(),
    "agent-slice": lambda order, seed: _run_agent_slice(),
    "desktop": lambda order, seed: _run_desktop_lifecycle(),
    "desktop-slice": lambda order, seed: _run_desktop_slice(),
    "renderer3d": lambda order, seed: _run_renderer3d_lifecycle(),
    "renderer3d-slice": lambda order, seed: _run_renderer3d_slice(),
}


def run_in_process(target: str, runs: int, *, order: str, verbose: bool) -> dict[str, Any]:
    iterations: list[dict[str, Any]] = []
    consecutive = 0
    best = 0
    first_failure: dict[str, Any] | None = None
    baseline = snapshot("baseline")
    for index in range(1, runs + 1):
        before = snapshot("before")
        started = time.monotonic()
        try:
            outcome = TARGETS[target](order, index)
        except Exception as exc:  # a harness fault is data, not a crash
            outcome = {"ok": False, "failures": [f"{type(exc).__name__}: {exc}"], "ran": 0}
        elapsed = time.monotonic() - started
        teardown_started = time.monotonic()
        gc.collect()
        teardown = time.monotonic() - teardown_started
        after = snapshot("after")
        record = {
            "iteration": index,
            "ok": bool(outcome.get("ok")),
            "seconds": round(elapsed, 3),
            "gcSeconds": round(teardown, 4),
            "ran": outcome.get("ran"),
            "failures": outcome.get("failures", []),
            "errors": outcome.get("errors", []),
            "pid": os.getpid(),
            # Per iteration rather than once per run, because §11 requires all
            # three gates to be run on the same finalized commit and a single
            # header would not prove the tree did not move underneath a run.
            "commit": _commit(),
            "delta": _delta(before, after),
            "sinceBaseline": _delta(baseline, after),
        }
        # Whether the iteration exercised a real backend or a scripted one.
        # Carried per iteration rather than once per run: a host whose model
        # server dies half way through would otherwise produce a report that
        # claims "real" for all of it.
        if outcome.get("mode"):
            record["mode"] = outcome["mode"]
        if outcome.get("notRun"):
            record["notRun"] = outcome["notRun"]
        # Anything else the target measured, kept rather than dropped.
        #
        # An earlier version copied only the fields listed above, so a target
        # that reported its posture and its latencies had both silently
        # discarded — and the collector, reading the gate file afterwards, saw
        # twenty iterations with no posture and no figures. A harness that
        # decides which of a target's measurements are interesting is a harness
        # that will one day discard the interesting one.
        for name in (
            "posture", "measurements", "resourceDelta", "states", "released",
            # The 3D targets' own: how much of the surface the character
            # covered, and what graphics stack drew it. Added when the 3D gates
            # landed, for exactly the reason the paragraph above gives — the
            # first run of the 3D lifecycle gate reported a null coverage for
            # all hundred iterations because this list did not name it.
            "coverage", "environment",
        ):
            if outcome.get(name) is not None:
                record[name] = outcome[name]
        if not record["ok"]:
            record["detail"] = outcome.get("detail", [])
            record["order"] = outcome.get("order")
            if first_failure is None:
                first_failure = record
            best = max(best, consecutive)
            consecutive = 0
        else:
            consecutive += 1
        iterations.append(record)
        if verbose:
            mark = "ok " if record["ok"] else "FAIL"
            print(
                f"  {index:4d} {mark} {record['seconds']:6.2f}s "
                f"threads{record['delta'].get('threads', 0):+d} "
                f"fd{record['delta'].get('descriptors', 0):+d} "
                f"rss{record['sinceBaseline'].get('rssBytes', 0) // 1024:+d}K",
                file=sys.stderr, flush=True,
            )
    best = max(best, consecutive)
    return {
        "target": target,
        "order": order,
        "mode": "in-process",
        "runs": runs,
        "passed": sum(1 for item in iterations if item["ok"]),
        "failed": sum(1 for item in iterations if not item["ok"]),
        "longestConsecutivePass": best,
        "finalConsecutivePass": consecutive,
        "firstFailure": first_failure,
        "iterations": iterations,
        "baseline": baseline,
        "final": snapshot("final"),
    }


def run_isolated(target: str, runs: int, *, order: str) -> dict[str, Any]:
    """One interpreter per iteration. The control for accumulated state."""
    iterations = []
    consecutive = best = 0
    for index in range(1, runs + 1):
        started = time.monotonic()
        completed = subprocess.run(
            [sys.executable, __file__, "--target", target, "--runs", "1",
             "--order", order, "--json"],
            capture_output=True, text=True, cwd=str(_REPOSITORY),
        )
        ok = completed.returncode == 0
        iterations.append({
            "iteration": index,
            "ok": ok,
            "seconds": round(time.monotonic() - started, 3),
            "stderr": completed.stderr[-400:] if not ok else "",
        })
        if ok:
            consecutive += 1
        else:
            best = max(best, consecutive)
            consecutive = 0
    best = max(best, consecutive)
    return {
        "target": target, "order": order, "mode": "process-isolated", "runs": runs,
        "passed": sum(1 for item in iterations if item["ok"]),
        "failed": sum(1 for item in iterations if not item["ok"]),
        "longestConsecutivePass": best,
        "iterations": iterations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=sorted(TARGETS), default="service")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--order", choices=("declared", "random", "reverse"), default="declared")
    parser.add_argument("--isolate", action="store_true", help="one interpreter per iteration")
    parser.add_argument("--json", action="store_true", help="print the report and nothing else")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    verbose = not args.json
    if verbose:
        print(
            f"stress: target={args.target} runs={args.runs} order={args.order} "
            f"mode={'isolated' if args.isolate else 'in-process'} pid={os.getpid()}",
            file=sys.stderr, flush=True,
        )
    report = (
        run_isolated(args.target, args.runs, order=args.order) if args.isolate
        else run_in_process(args.target, args.runs, order=args.order, verbose=verbose)
    )
    encoded = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    if args.json:
        print(encoded)
    elif verbose:
        print(
            f"stress: {report['passed']}/{report['runs']} passed, "
            f"longest consecutive {report['longestConsecutivePass']}",
            file=sys.stderr, flush=True,
        )
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
