# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What a companion service owns after a start-up that did not finish.

The measured defect (§18b of the voice-runtime report) was a voice worker
started *before* the endpoint bind that raises ``DuplicateRuntime``. Fifty
complete suite runs accumulated a hundred stranded ``companion-voice`` threads,
two per run, and every test in every run passed — the leak was visible only in
the §22 thread-delta column, because nothing asserted on what a *refused*
construction left behind.

That was first fixed by unwinding the worker when the bind failed. This file is
about the stronger property: the order is such that the two cheap refusals — a
bad configuration and a second runtime — happen before anything owns a thread, a
process or a device, and the unwind covers every boundary anyway.

So each test breaks the service *after* one named step and asserts the same
seven things every time: no worker thread, no child process, no socket, no lock,
no temporary file, no audio handle, no timer. Injection is by overriding the
step method rather than by a production hook, so nothing here exists in the
shipped code to be reached by accident.
"""

from __future__ import annotations

import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest

from companion.protocol import DuplicateRuntime, RuntimeSingleton
from companion.service import (
    RELEASE_ORDER,
    STARTUP_SEQUENCE,
    CompanionService,
    ServiceOptions,
    StartupFailed,
)
from companion.voice.policy import VoicePreferences

from .support import temporary_root

POSIX = os.name == "posix"


class _Boom(RuntimeError):
    """The injected failure. Distinct so nothing can mistake it for a real one."""


def _service_class(fail_after: str):
    """A service that completes ``fail_after`` and then refuses."""
    method = "_step_" + fail_after.replace("-", "_")

    class Failing(CompanionService):
        pass

    def broken(self) -> None:
        getattr(super(Failing, self), method)()
        raise _Boom(f"injected failure after {fail_after}")

    setattr(Failing, method, broken)
    return Failing


def _voice_threads() -> int:
    return sum(1 for item in threading.enumerate() if item.name.startswith("companion-voice"))


def _protocol_threads() -> int:
    return sum(1 for item in threading.enumerate() if "companion-protocol" in item.name)


def _task_worker_threads() -> int:
    return sum(1 for item in threading.enumerate() if "companion-worker" in item.name)


def _timer_threads() -> int:
    return sum(1 for item in threading.enumerate() if isinstance(item, threading.Timer))


def _child_processes() -> int:
    """Live children of this process, read rather than reaped.

    ``/proc/self/task/*/children`` is the only way to ask this question without
    changing the answer: ``waitpid(-1, WNOHANG)`` would *reap* a child, taking
    it away from whichever :mod:`subprocess` object owns it, and a measurement
    that consumes what it measures is not a measurement.

    Zero on a platform with no ``/proc``. Recorded as a limit rather than
    presented as a clean result: on Windows this column proves nothing, and the
    gates that matter run on the Linux reference target.
    """
    root = Path("/proc/self/task")
    if not root.is_dir():  # pragma: no cover - Windows development host
        return 0
    total = 0
    for task in root.iterdir():
        try:
            total += len((task / "children").read_text(encoding="ascii").split())
        except OSError:
            continue
    return total


def _endpoint_answers(endpoint: Path) -> bool:
    """Whether anything is listening on this endpoint right now."""
    if not endpoint.exists():
        return False
    if not hasattr(socket, "AF_UNIX"):  # pragma: no cover - Windows fallback file
        return endpoint.is_file()
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.settimeout(0.25)
        probe.connect(str(endpoint))
    except OSError:
        return False
    else:
        return True
    finally:
        probe.close()


class Resources:
    """Everything §4 asks to be zero after a failed start-up, counted twice."""

    def __init__(self, root: Path, endpoint: Path) -> None:
        self.root = root
        self.endpoint = endpoint

    def take(self) -> dict[str, int]:
        return {
            "voiceWorkerThreads": _voice_threads(),
            "taskWorkerThreads": _task_worker_threads(),
            "protocolThreads": _protocol_threads(),
            "timerThreads": _timer_threads(),
            "childProcesses": _child_processes(),
            "listeningEndpoint": int(_endpoint_answers(self.endpoint)),
            "endpointFiles": len(list(self.endpoint.parent.glob(self.endpoint.name))),
            "lockFiles": len(list(self.endpoint.parent.glob(self.endpoint.name + ".lock"))),
            "voiceWorkspaces": len(list(self.root.glob("voice/*"))) if (self.root / "voice").is_dir() else 0,
            "strayTempDirectories": len(list(Path(tempfile.gettempdir()).glob("bunny-voice-*"))),
        }


class StartupOrder(unittest.TestCase):
    """The sequence itself, before any failure is injected into it."""

    def test_the_sequence_is_the_one_the_closure_requires(self) -> None:
        self.assertEqual(STARTUP_SEQUENCE, (
            "validate-configuration",
            "acquire-singleton",
            "bind-endpoint",
            # Constructed only, before the durable state: the runtime built
            # there wires provider-backed executors over this object, and a
            # constructed agent service owns a registry and a journal but no
            # thread — the worker starts at its own step below.
            "construct-agent-providers",
            "initialise-durable-state",
            "construct-voice-worker",
            "start-voice-worker",
            "start-agent-worker",
            # Constructed only: no thread, no device and no model exist until
            # a person performs an explicit activation. §4's "no microphone
            # initialisation during service startup" is why there is no
            # start-speech-worker step to order against.
            "construct-speech-input",
            "publish-readiness",
        ))

    def test_the_singleton_and_the_bind_precede_the_voice_worker(self) -> None:
        """The whole of the §18b fix, stated as a property of the order."""
        order = list(STARTUP_SEQUENCE)
        self.assertLess(order.index("acquire-singleton"), order.index("start-voice-worker"))
        self.assertLess(order.index("bind-endpoint"), order.index("start-voice-worker"))
        self.assertLess(order.index("construct-voice-worker"), order.index("start-voice-worker"))
        self.assertEqual(order[-1], "publish-readiness")

    def test_a_service_that_starts_records_every_step(self) -> None:
        root = temporary_root(self)
        service = CompanionService(ServiceOptions(
            root=root / "store", endpoint=root / "run" / "runtime.sock", machine="laptop",
        ))
        self.addCleanup(service.close)
        self.assertEqual(service.completed_steps, STARTUP_SEQUENCE[:-1])
        service.start()
        self.assertEqual(service.completed_steps, STARTUP_SEQUENCE)
        self.assertTrue(service.ready)
        document = service.describe()["startup"]
        self.assertEqual(document["completed"], list(STARTUP_SEQUENCE))
        self.assertIn("endpoint", document["held"])

    def test_every_held_resource_is_named_in_the_release_order(self) -> None:
        """A resource nobody ordered is released, and this is what says so."""
        root = temporary_root(self)
        service = CompanionService(ServiceOptions(
            root=root / "store", endpoint=root / "run" / "runtime.sock", machine="laptop",
        )).start()
        self.addCleanup(service.close)
        for name in service.held_resources:
            with self.subTest(resource=name):
                self.assertIn(name, RELEASE_ORDER)

    def test_the_release_order_is_not_reverse_creation_order(self) -> None:
        """Stated as a test so that 'simplifying' it to a stack fails here.

        Consent before the task worker and voice before the task worker are both
        measured: a plain reverse-creation unwind took the protocol suite from
        16 s to 86 s, because a service with a pending approval waited out the
        whole consent timeout before it could join its worker.
        """
        order = list(RELEASE_ORDER)
        self.assertLess(order.index("endpoint"), order.index("durable-state"))
        self.assertLess(order.index("consent"), order.index("task-worker"))
        self.assertLess(order.index("voice-runtime"), order.index("task-worker"))


class FailureAtEachBoundary(unittest.TestCase):
    """Break the service after each step; assert it owns nothing afterwards."""

    def setUp(self) -> None:
        self.root = temporary_root(self)
        self.endpoint = self.root / "run" / "runtime.sock"
        self.resources = Resources(self.root / "store", self.endpoint)
        self.baseline = self.resources.take()

    def _options(self) -> ServiceOptions:
        return ServiceOptions(
            root=self.root / "store", endpoint=self.endpoint, machine="laptop",
            consent_wait_seconds=1.0,
        )

    def _assert_nothing_survives(self, step: str) -> None:
        # Threads are joined rather than abandoned, but a join is not
        # instantaneous; give the ones that were asked to stop a moment to go.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and self.resources.take() != self.baseline:
            time.sleep(0.02)
        after = self.resources.take()
        for key, expected in self.baseline.items():
            with self.subTest(step=step, resource=key):
                self.assertEqual(
                    after[key], expected,
                    f"a failure after {step} left {after[key] - expected} more {key}",
                )

    def test_a_failure_after_each_step_leaves_nothing_behind(self) -> None:
        for step in STARTUP_SEQUENCE:
            with self.subTest(step=step):
                failing = _service_class(step)
                with self.assertRaises((StartupFailed, _Boom)) as caught:
                    service = failing(self._options())
                    # publish-readiness is reached through start(), which
                    # unwinds through the same path.
                    service.start()
                self.assertIn(step, str(caught.exception))
                self._assert_nothing_survives(step)

    def test_a_failure_after_the_worker_starts_takes_the_worker_with_it(self) -> None:
        """The precise §18b shape: a thread exists, and then it does not."""
        failing = _service_class("start-voice-worker")
        with self.assertRaises(StartupFailed):
            failing(self._options())
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and _voice_threads() > self.baseline["voiceWorkerThreads"]:
            time.sleep(0.02)
        self.assertEqual(_voice_threads(), self.baseline["voiceWorkerThreads"])

    def test_the_lock_file_is_released_by_every_failure(self) -> None:
        for step in STARTUP_SEQUENCE:
            with self.subTest(step=step):
                failing = _service_class(step)
                with self.assertRaises((StartupFailed, _Boom)):
                    failing(self._options()).start()
                # Proved by taking it again rather than by looking at the
                # filesystem: the file's existence means nothing, the lock is
                # held by a descriptor, and acquiring is the only real question.
                singleton = RuntimeSingleton(self.endpoint)
                singleton.acquire()
                singleton.release()

    def test_a_second_service_can_start_after_a_failed_one(self) -> None:
        """The property a leaked claim would break, and nothing else would."""
        failing = _service_class("construct-voice-worker")
        with self.assertRaises(StartupFailed):
            failing(self._options())
        service = CompanionService(self._options()).start()
        self.addCleanup(service.close)
        self.assertTrue(service.ready)


class ConfigurationIsRefusedBeforeAnythingExists(unittest.TestCase):
    """Step 1 owns no resource, which is the point of it being step 1."""

    def setUp(self) -> None:
        self.root = temporary_root(self)

    def test_a_root_that_is_a_file_is_refused(self) -> None:
        occupied = self.root / "store"
        occupied.write_text("not a directory", encoding="utf-8")
        with self.assertRaises(StartupFailed) as caught:
            CompanionService(ServiceOptions(root=occupied, endpoint=self.root / "r.sock"))
        self.assertEqual(caught.exception.step, "validate-configuration")
        self.assertFalse((self.root / "r.sock").exists())
        self.assertFalse((self.root / "r.sock.lock").exists())

    def test_an_out_of_range_voice_preference_is_a_configuration_error(self) -> None:
        """Not a silently voiceless service: _build_voice swallows everything.

        §8 says a misconfigured synthesiser must never stop the service. That is
        right for a missing program and wrong for a volume of 4.0, which is an
        operator mistake nobody would ever be told about.
        """
        with self.assertRaises(StartupFailed) as caught:
            CompanionService(ServiceOptions(
                root=self.root / "store", endpoint=self.root / "r.sock",
                voice_preferences=VoicePreferences(volume=4.0),
            ))
        self.assertEqual(caught.exception.step, "validate-configuration")
        self.assertIn("quieter", str(caught.exception))

    @unittest.skipUnless(POSIX, "symbolic links are a POSIX arrangement")
    def test_an_endpoint_that_is_a_symlink_is_refused_at_step_one(self) -> None:
        target = self.root / "elsewhere.sock"
        link = self.root / "runtime.sock"
        target.write_text("", encoding="utf-8")
        link.symlink_to(target)
        with self.assertRaises(Exception) as caught:
            CompanionService(ServiceOptions(root=self.root / "store", endpoint=link))
        self.assertIn("symbolic link", str(caught.exception))
        self.assertFalse((self.root / "runtime.sock.lock").exists())


class TheSingletonClaim(unittest.TestCase):
    """Step 2, on its own."""

    def setUp(self) -> None:
        self.root = temporary_root(self)
        self.endpoint = self.root / "run" / "runtime.sock"

    def test_a_second_claim_is_refused_while_the_first_is_held(self) -> None:
        first = RuntimeSingleton(self.endpoint).acquire()
        self.addCleanup(first.release)
        second = RuntimeSingleton(self.endpoint)
        try:
            second.acquire()
        except DuplicateRuntime:
            return
        second.release()
        self.skipTest("this platform has no advisory file locking; the probe is the exclusion")

    def test_releasing_twice_is_safe(self) -> None:
        singleton = RuntimeSingleton(self.endpoint).acquire()
        singleton.release()
        singleton.release()
        self.assertFalse(singleton.held)

    def test_a_second_service_is_refused_and_the_first_keeps_serving(self) -> None:
        options = ServiceOptions(
            root=self.root / "store", endpoint=self.endpoint, machine="laptop",
        )
        first = CompanionService(options).start()
        self.addCleanup(first.close)
        with self.assertRaises(DuplicateRuntime):
            CompanionService(ServiceOptions(
                root=self.root / "store2", endpoint=self.endpoint, machine="laptop",
            ))
        self.assertTrue(first.ready)
        self.assertTrue(_endpoint_answers(self.endpoint))

    def test_a_refused_second_service_strands_no_voice_worker(self) -> None:
        """§18b, as a regression rather than as an argument about order."""
        options = ServiceOptions(
            root=self.root / "store", endpoint=self.endpoint, machine="laptop",
        )
        first = CompanionService(options).start()
        self.addCleanup(first.close)
        before = _voice_threads()
        with self.assertRaises(DuplicateRuntime):
            CompanionService(ServiceOptions(
                root=self.root / "store2", endpoint=self.endpoint, machine="laptop",
            ))
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and _voice_threads() > before:
            time.sleep(0.02)
        self.assertEqual(_voice_threads(), before)


class TheEndpointIsBoundBeforeThereIsAnythingToServe(unittest.TestCase):
    """Step 3, and the deferral that makes the order possible."""

    def setUp(self) -> None:
        self.root = temporary_root(self)
        self.endpoint = self.root / "run" / "runtime.sock"

    def test_the_socket_exists_before_the_voice_worker_does(self) -> None:
        seen: dict[str, bool] = {}

        class Observing(CompanionService):
            def _step_construct_voice_worker(inner) -> None:  # noqa: N805
                seen["endpointBound"] = inner.endpoint.exists()
                seen["singletonHeld"] = bool(inner.singleton and inner.singleton.held)
                super()._step_construct_voice_worker()

        service = Observing(ServiceOptions(
            root=self.root / "store", endpoint=self.endpoint, machine="laptop",
        ))
        self.addCleanup(service.close)
        self.assertTrue(seen["endpointBound"], "the voice worker was built before the bind")
        self.assertTrue(seen["singletonHeld"], "the voice worker was built before the claim")

    def test_a_server_with_no_gateway_refuses_to_serve(self) -> None:
        from companion.protocol import CompanionServer

        server = CompanionServer(None, self.endpoint)
        self.addCleanup(server.close)
        with self.assertRaises(RuntimeError) as caught:
            server.start()
        self.assertIn("no gateway attached", str(caught.exception))

    def test_the_endpoint_is_unlinked_when_the_service_closes(self) -> None:
        service = CompanionService(ServiceOptions(
            root=self.root / "store", endpoint=self.endpoint, machine="laptop",
        )).start()
        self.assertTrue(_endpoint_answers(self.endpoint))
        service.close()
        self.assertFalse(_endpoint_answers(self.endpoint))
        self.assertFalse(self.endpoint.exists())
        self.assertFalse(Path(str(self.endpoint) + ".lock").exists())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
