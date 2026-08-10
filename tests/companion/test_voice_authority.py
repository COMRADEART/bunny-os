# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§20 recovery, §21 authority, §17 protocol: what voice cannot do, and after a crash.

The authority tests are the ones that matter most and they are deliberately
*structural*. Asserting "the worker did not change the task" after a run proves
the run; asserting that the module cannot reach anything that could change a
task proves the design. Both are here, and the import-graph check is the one
that would fail first if somebody wired a store into the voice runtime.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import threading
import time
import unittest

from companion.protocol import OPERATIONS, VOICE_OPERATIONS, ProtocolError
from companion.voice.captions import SpeechDisposition
from companion.voice.execution import PrivateWorkspace
from companion.voice.policy import VoicePreferences
from companion.voice.provider import ProviderRegistry
from companion.voice.recovery import (
    STALE_AFTER_SECONDS,
    RecoveryReport,
    VoiceJournal,
    recover,
    sweep_workspaces,
)
from companion.voice.request import Priority
from companion.voice.service import VoiceService, VoiceServiceOptions

from .voice_support import BARRIER_TIMEOUT, ScriptedBackend, ScriptedProvider, make_request, presentation

from .support import temporary_root

VOICE_PACKAGE = Path(__file__).resolve().parents[2] / "companion" / "voice"


class ImportBoundaryTests(unittest.TestCase):
    """The strongest statement §21 asks for: voice holds nothing that could act."""

    #: Modules that own or can change task authority. A voice module importing
    #: any of these would have the ability, whatever the code currently does
    #: with it — and "currently" is not a property anybody can review.
    FORBIDDEN = {
        "companion.runtime", "companion.store", "companion.task", "companion.session",
        "companion.approvals", "companion.executor", "companion.reviewer",
        "companion.tools", "companion.cancellation", "companion.recovery",
        "companion.events", "companion.coordination", "companion.migration",
    }

    #: Relative forms of the same, as they would appear inside the package.
    FORBIDDEN_RELATIVE = {
        "runtime", "store", "task", "session", "approvals", "executor",
        "reviewer", "tools", "cancellation", "events", "coordination", "migration",
    }

    def _imports(self, module: Path) -> set[str]:
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        found: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    found.add(node.module)
                elif node.level == 1 and node.module:
                    # ``from ..x import y`` inside companion/voice/ is
                    # companion.x; ``from .x`` is companion.voice.x.
                    found.add(f"companion.voice.{node.module}")
                elif node.level == 2 and node.module:
                    found.add(f"companion.{node.module}")
        return found

    def test_no_voice_module_imports_anything_that_owns_a_task(self) -> None:
        modules = sorted(VOICE_PACKAGE.glob("*.py"))
        self.assertGreaterEqual(len(modules), 12)
        for module in modules:
            for name in self._imports(module):
                self.assertNotIn(
                    name, self.FORBIDDEN,
                    f"{module.name} imports {name}, which can change task state",
                )
                head = name.split(".")[0]
                if name.startswith("companion.") and head == "companion":
                    tail = name.split(".", 1)[1]
                    self.assertNotIn(
                        tail.split(".")[0], self.FORBIDDEN_RELATIVE - {"recovery"},
                        f"{module.name} imports companion.{tail}",
                    )

    def test_the_worker_in_particular_holds_no_runtime(self) -> None:
        from companion.voice import worker

        for attribute in dir(worker):
            value = getattr(worker, attribute)
            self.assertNotEqual(
                getattr(value, "__name__", ""), "CompanionRuntime",
                "the voice worker module can see a CompanionRuntime",
            )

    #: Programs and libraries that capture audio. §16 and §15: this is an output
    #: subsystem, and none of these may be startable from it.
    CAPTURE_NAMES = ("arecord", "parecord", "parec", "pamon", "pw-record", "sounddevice", "pyaudio")

    def test_no_capture_program_is_reachable_from_the_voice_package(self) -> None:
        """§16 and §15: this is an output subsystem, asserted structurally.

        The allowlist is the whole of what ``resolve_executable`` will find, and
        a name absent from it cannot be started by any code path in the package.
        That is a stronger statement than "the string does not appear", and it
        is the one that matters — the string test could be satisfied by building
        the name at runtime, and would fail on a *refusal* list that names the
        programs precisely so they can be rejected.
        """
        from companion.voice.execution import ALLOWED_EXECUTABLES

        for name in self.CAPTURE_NAMES:
            self.assertNotIn(
                name, ALLOWED_EXECUTABLES,
                f"{name} is in the voice runtime's executable allowlist",
            )

    def test_no_capture_program_is_named_as_something_to_run(self) -> None:
        """Every capture name in the package is in a refusal list, not a run list.

        ``companion.voice.audio`` names ``parec`` and ``parecord`` in
        ``PlayerContract.multicall_siblings`` — the list of names that must
        *not* be substituted for the requested player, because a multi-call
        binary decides what it does from ``argv[0]``. Naming a recorder there is
        how it is kept out, not a way in. So this asserts on the fields that
        decide what gets executed rather than on the text of the file.
        """
        from companion.voice import audio, providers

        runnable: list[str] = []
        for backend in (
            audio.PulseAudioBackend, audio.PipeWireBackend, audio.AlsaBackend,
        ):
            runnable.extend([backend.player, backend.inspector])
            if backend.contract is not None:
                runnable.append(backend.contract.program)
        for provider in (providers.EspeakNgProvider, providers.SpeechDispatcherProvider):
            runnable.append(provider.executable_name)
            runnable.extend(provider.fallback_names)
        for name in self.CAPTURE_NAMES:
            self.assertNotIn(name, runnable, f"a voice component is configured to start {name}")

    def test_capture_names_appear_only_in_refusal_lists(self) -> None:
        """The text check, kept — with the one place a refusal may name them."""
        allowed_holders = {"audio.py", "system.py"}
        for module in sorted(VOICE_PACKAGE.glob("*.py")):
            if module.name in allowed_holders:
                continue
            body = module.read_text(encoding="utf-8").lower()
            for token in self.CAPTURE_NAMES:
                self.assertNotIn(token, body, f"{module.name} references {token}")

    def test_no_voice_cloning_surface_exists_anywhere(self) -> None:
        """§16, checked as names rather than as prose."""
        forbidden = (
            "clone_voice", "voice_clone", "train_voice", "voice_training",
            "speaker_embedding", "enrol_voice", "enroll_voice", "import_voice_sample",
            "upload_voice",
        )
        for module in sorted(VOICE_PACKAGE.glob("*.py")):
            tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
            for node in ast.walk(tree):
                name = ""
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    name = node.name
                elif isinstance(node, ast.Name):
                    name = node.id
                elif isinstance(node, ast.Attribute):
                    name = node.attr
                for banned in forbidden:
                    self.assertNotEqual(
                        name.lower(), banned, f"{module.name} defines {name}"
                    )


class ServiceBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = temporary_root(self)
        self.service = VoiceService(VoiceServiceOptions(
            runtime_directory=self.directory,
            registry=ProviderRegistry([ScriptedProvider()]),
            router=__import__(
                "companion.voice.audio", fromlist=["AudioRouter"]
            ).AudioRouter([ScriptedBackend()]),
            preferences=VoicePreferences(speak_progress=True),
        ))
        self.addCleanup(self.service.close)

    def test_the_service_holds_no_runtime_store_or_session(self) -> None:
        for attribute in vars(self.service):
            value = getattr(self.service, attribute)
            self.assertNotIn(
                type(value).__name__,
                ("CompanionRuntime", "CompanionStore", "CompanionSession", "CompanionApprovalStore"),
                f"VoiceService.{attribute} is a {type(value).__name__}",
            )

    def test_preparing_neural_provider_keeps_fallback_speech_available(self) -> None:
        """Cold Pocket startup must not turn a working fallback into captions."""
        from companion.voice.provider import ProviderHealth

        for status in ("INITIALIZING", "MODEL_VERIFIED"):
            with self.subTest(status=status):
                provider = ScriptedProvider(provider_id="pocket")
                provider.health = lambda **_kwargs: ProviderHealth(
                    provider_id="pocket",
                    available=False,
                    healthy=True,
                    status=status,
                    detail="Pocket TTS is preparing its local model",
                )
                service = VoiceService(VoiceServiceOptions(
                    runtime_directory=temporary_root(self),
                    registry=ProviderRegistry([provider]),
                    router=__import__(
                        "companion.voice.audio", fromlist=["AudioRouter"]
                    ).AudioRouter([ScriptedBackend()]),
                    start_worker=False,
                ))
                self.addCleanup(service.close)
                self.assertTrue(service.policy.decision.speaks)
                self.assertTrue(service.voice_status()["signals"]["localProviderAvailable"])
                self.assertTrue(service.voice_status()["signals"]["synthesisProviderAvailable"])

    def test_every_boundary_claim_is_answered_and_answered_no(self) -> None:
        boundaries = self.service.boundaries()
        self.assertTrue(boundaries["captionsAuthoritative"])
        for claim in (
            "voiceMayChangeTaskState", "voiceMayResolveApprovals", "voiceMaySelectExecutor",
            "voiceMayInvokeTools", "voiceMayReadSecretPayloads", "voiceMayRewriteCaptions",
            "voiceFailureFailsTask", "remoteProviderConfigured", "remoteTransmissionPermitted",
            "voiceCloningSupported", "voiceSampleImportSupported", "speakerEmbeddingSupported",
            "modelTrainingSupported", "microphoneUsedByVoiceRuntime",
            "speechRecognitionImplemented", "physicalSpeakerValidated",
        ):
            self.assertFalse(boundaries[claim], claim)

    def test_the_operations_are_exactly_the_eight_the_specification_names(self) -> None:
        self.assertEqual(sorted(VOICE_OPERATIONS), [
            "voice_cancel", "voice_explain", "voice_health", "voice_list",
            "voice_pause", "voice_resume", "voice_speak", "voice_status",
        ])

    def test_no_operation_accepts_an_executable_path_or_url(self) -> None:
        forbidden = {
            "executable", "command", "argv", "arguments", "path", "outputPath",
            "url", "endpoint", "module", "provider", "device", "text", "speechText",
        }
        for name, operation in VOICE_OPERATIONS.items():
            for parameter in operation.parameters:
                self.assertNotIn(parameter.name, forbidden, f"{name} accepts {parameter.name}")

    def test_an_undeclared_parameter_is_refused_rather_than_ignored(self) -> None:
        with self.assertRaises(ProtocolError):
            self.service.dispatch("voice_status", {"andAlso": "something"})
        with self.assertRaises(ProtocolError):
            self.service.dispatch("voice_speak", {"captionId": "cap-1", "executable": "/bin/sh"})

    def test_an_unknown_operation_is_refused(self) -> None:
        with self.assertRaises(ProtocolError):
            self.service.dispatch("voice_run_command", {})

    def test_speaking_takes_a_caption_reference_and_never_text(self) -> None:
        """§8: a client cannot make the companion say what the user was not shown."""
        parameters = {item.name for item in VOICE_OPERATIONS["voice_speak"].parameters}
        self.assertIn("captionId", parameters)
        self.assertNotIn("text", parameters)
        self.assertNotIn("speechText", parameters)

    def test_speaking_an_unknown_caption_is_refused_without_raising(self) -> None:
        answer = self.service.dispatch("voice_speak", {"captionId": "cap-nonexistent"})
        self.assertFalse(answer["accepted"])
        self.assertIn("no caption", answer["reason"])
        self.assertTrue(answer["captionRetained"])
        self.assertFalse(answer["taskAffected"])

    def test_the_voice_list_states_that_cloning_is_unsupported(self) -> None:
        answer = self.service.dispatch("voice_list", {})
        self.assertFalse(answer["voiceCloningSupported"])
        self.assertFalse(answer["voiceImportSupported"])
        self.assertFalse(answer["voiceTrainingSupported"])
        self.assertFalse(answer["remoteVoicesAvailable"])

    def test_a_full_round_trip_speaks_a_published_caption(self) -> None:
        caption = self.service.publish(presentation())
        self.service.ledger.mark_shown(caption.caption_id)
        answer = self.service.dispatch("voice_speak", {"captionId": caption.caption_id})
        self.assertTrue(answer["accepted"], answer["reason"])
        self.assertTrue(self.service.worker.drain(timeout=BARRIER_TIMEOUT))
        status = self.service.dispatch("voice_status")
        self.assertEqual(status["dispositions"][SpeechDisposition.PLAYED], 1)

    def test_explain_answers_why_it_is_not_speaking(self) -> None:
        answer = self.service.dispatch("voice_explain", {})
        self.assertIn("outcome", answer)
        self.assertIn("ladder", answer)
        self.assertIn("boundaries", answer)

    def test_cancelling_nothing_is_not_an_error(self) -> None:
        answer = self.service.dispatch("voice_cancel", {"requestId": "speech-absent"})
        self.assertEqual(answer["count"], 0)
        self.assertTrue(answer["captionRetained"])

    def test_cancelling_with_neither_identifier_is_refused(self) -> None:
        with self.assertRaises(ProtocolError):
            self.service.dispatch("voice_cancel", {})

    def test_the_documented_integration_is_one_service_and_no_second_runtime(self) -> None:
        described = self.service.describe()["integration"]
        self.assertFalse(described["separateUserService"])
        self.assertFalse(described["secondTaskRuntime"])
        self.assertIn("isolated worker", described["mode"])


class ServiceConstructionTests(unittest.TestCase):
    """A construction that fails must not leave a worker thread behind."""

    def _voice_threads(self) -> int:
        return sum(1 for item in threading.enumerate() if item.name == "companion-voice")

    def test_a_failed_service_construction_releases_its_voice_runtime(self) -> None:
        """§6: no leaked thread — including when the service never finished being built.

        `CompanionService.__init__` builds the voice runtime, which starts a
        thread, and only then binds the endpoint — where a second service on a
        live endpoint is refused with `DuplicateRuntime`. The half-built service
        is discarded by the caller, so if the constructor does not release the
        worker itself nothing ever can: no reference to it survives.

        Found by the §22 thread-delta column rather than by any assertion. Fifty
        complete suite runs accumulated a hundred `companion-voice` threads —
        two per run — while every test in them passed.
        """
        from companion.protocol import DuplicateRuntime
        from companion.service import CompanionService, ServiceOptions

        root = temporary_root(self)
        endpoint = root / "runtime.sock"
        first = CompanionService(ServiceOptions(
            root=root, endpoint=endpoint, machine="laptop",
        )).start()
        self.addCleanup(first.close)

        before = self._voice_threads()
        with self.assertRaises(DuplicateRuntime):
            CompanionService(ServiceOptions(
                root=root, endpoint=endpoint, machine="laptop",
            ))
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and self._voice_threads() > before:
            time.sleep(0.02)
        self.assertEqual(
            self._voice_threads(), before,
            "a refused service construction left its voice worker running",
        )

    def test_a_service_with_voice_disabled_starts_no_worker(self) -> None:
        from companion.service import CompanionService, ServiceOptions

        before = self._voice_threads()
        root = temporary_root(self)
        service = CompanionService(ServiceOptions(
            root=root, endpoint=root / "runtime.sock", machine="laptop",
            voice_enabled=False,
        ))
        try:
            self.assertIsNone(service.voice)
            self.assertEqual(self._voice_threads(), before)
            answer = service.gateway.voice_health()
            self.assertFalse(answer["available"])
            self.assertTrue(answer["captionRetained"])
            self.assertFalse(answer["taskAffected"])
        finally:
            service.close()


class JournalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = temporary_root(self)
        self.journal = VoiceJournal(self.directory / "voice-journal.jsonl")

    def test_a_settled_utterance_is_not_uncertain(self) -> None:
        request = make_request(request_id="speech-1")
        self.journal.record_start(request)
        self.journal.record_settle(request, SpeechDisposition.PLAYED)
        report = self.journal.reconcile()
        self.assertEqual(report.uncertain, ())
        self.assertEqual(report.settled, 1)

    def test_an_utterance_with_no_settle_line_is_marked_interrupted(self) -> None:
        """§20: 'no child process remains' is evidence of nothing after a crash."""
        request = make_request(request_id="speech-1")
        self.journal.record_start(request)
        report = self.journal.reconcile()
        self.assertEqual(report.uncertain, ("speech-1",))
        self.assertEqual(report.marked_interrupted, ("speech-1",))
        self.assertEqual(report.replayed, ())

    def test_nothing_is_ever_replayed_automatically(self) -> None:
        for index in range(3):
            self.journal.record_start(make_request(request_id=f"speech-{index}", text=f"line {index}"))
        report = self.journal.reconcile()
        self.assertEqual(report.replayed, ())
        self.assertFalse(report.to_json()["automaticReplay"])
        self.assertTrue(report.to_json()["captionsPreserved"])

    def test_the_journal_never_holds_the_utterance(self) -> None:
        request = make_request(text="the passphrase is opensesame")
        self.journal.record_start(request)
        self.journal.record_settle(request, SpeechDisposition.PLAYED)
        self.assertNotIn("opensesame", self.journal.path.read_text(encoding="utf-8"))

    def test_a_torn_final_line_does_not_lose_the_lines_before_it(self) -> None:
        self.journal.record_start(make_request(request_id="speech-1"))
        with self.journal.path.open("a", encoding="utf-8") as handle:
            handle.write('{"event": "start", "requestId": "trunc')
        report = self.journal.reconcile()
        self.assertEqual(report.uncertain, ("speech-1",))

    def test_the_current_process_s_own_utterance_is_not_abandoned(self) -> None:
        self.journal.record_start(make_request(request_id="speech-1"))
        report = self.journal.reconcile(own_pid=os.getpid())
        self.assertEqual(report.uncertain, ())

    def test_an_unknown_disposition_cannot_be_journalled(self) -> None:
        with self.assertRaises(ValueError):
            self.journal.record_settle(make_request(), "went_fine")

    def test_a_journal_that_cannot_be_written_does_not_stop_speech(self) -> None:
        """A journal that cannot be written makes recovery more conservative, not broken.

        The unwritable location is a path *under a regular file*, which fails on
        every platform. An absolute path like ``/nonexistent-root`` is not
        unwritable on Windows — it resolves against the current drive and the
        directory is simply created, so the test would have proved nothing.
        """
        blocker = self.directory / "not-a-directory"
        blocker.write_text("this is a file", encoding="utf-8")
        journal = VoiceJournal(blocker / "voice" / "journal.jsonl")
        journal.record_start(make_request())  # must not raise
        journal.record_settle(make_request(), SpeechDisposition.PLAYED)  # nor this
        self.assertEqual(journal.read(), [])
        self.assertEqual(journal.reconcile().uncertain, ())

    @unittest.skipUnless(os.name == "posix", "file modes are a POSIX arrangement")
    def test_the_journal_is_private(self) -> None:
        import stat

        self.journal.record_start(make_request())
        self.assertEqual(stat.S_IMODE(self.journal.path.stat().st_mode), 0o600)


class SweepTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parent = temporary_root(self)

    def _stale_workspace(self, *, age: float = STALE_AFTER_SECONDS * 2) -> PrivateWorkspace:
        workspace = PrivateWorkspace(parent=self.parent)
        workspace.file("abandoned")
        old = time.time() - age
        os.utime(workspace.root, (old, old))
        return workspace

    def test_an_abandoned_workspace_is_removed(self) -> None:
        workspace = self._stale_workspace()
        removed, skipped, files = sweep_workspaces(parent=self.parent)
        self.assertEqual(removed, 1)
        self.assertEqual(files, 1)
        self.assertEqual(skipped, ())
        self.assertFalse(workspace.root.exists())

    def test_a_fresh_workspace_is_left_alone(self) -> None:
        workspace = PrivateWorkspace(parent=self.parent)
        self.addCleanup(workspace.close)
        removed, skipped, _files = sweep_workspaces(parent=self.parent)
        self.assertEqual(removed, 0)
        self.assertTrue(workspace.root.exists())
        self.assertIn("below the", " ".join(skipped))

    def test_a_workspace_in_use_is_protected_even_when_it_is_old(self) -> None:
        workspace = self._stale_workspace()
        self.addCleanup(workspace.close)
        removed, skipped, _files = sweep_workspaces(
            parent=self.parent, active=[workspace.root]
        )
        self.assertEqual(removed, 0)
        self.assertIn("in use", " ".join(skipped))

    @unittest.skipUnless(os.name == "posix", "ownership is a POSIX arrangement")
    def test_something_that_is_not_ours_is_skipped_with_a_reason(self) -> None:
        """A matching name is a convention; the mode and the owner are the proof.

        ``chmod`` rather than ``mkdir(mode=...)``: the mode argument to ``mkdir``
        is masked by the process umask, so on a host with the usual ``0o022``
        the directory came out ``0o755`` and neither the writability check nor
        the ownership check fired — the sweep removed it and the test's premise
        had quietly evaporated. Linux found that; Windows had skipped the test.
        """
        impostor = self.parent / f"{PrivateWorkspace.PREFIX}impostor"
        impostor.mkdir()
        os.chmod(impostor, 0o777)
        self.assertTrue(
            impostor.stat().st_mode & (stat.S_IWGRP | stat.S_IWOTH),
            "the fixture is not actually world-writable, so it proves nothing",
        )
        old = time.time() - STALE_AFTER_SECONDS * 2
        os.utime(impostor, (old, old))
        removed, skipped, _files = sweep_workspaces(parent=self.parent)
        self.assertEqual(removed, 0)
        self.assertIn("writable by group or other", " ".join(skipped))
        self.assertTrue(impostor.exists())

    @unittest.skipUnless(os.name == "posix", "symbolic links are a POSIX arrangement")
    def test_a_symlink_named_like_a_workspace_is_not_followed(self) -> None:
        elsewhere = temporary_root(self)
        (elsewhere / "precious.txt").write_text("keep me", encoding="utf-8")
        link = self.parent / f"{PrivateWorkspace.PREFIX}link"
        link.symlink_to(elsewhere)
        old = time.time() - STALE_AFTER_SECONDS * 2
        os.utime(link, (old, old), follow_symlinks=False)
        removed, skipped, _files = sweep_workspaces(parent=self.parent)
        self.assertEqual(removed, 0)
        self.assertIn("symbolic link", " ".join(skipped))
        self.assertTrue((elsewhere / "precious.txt").exists())

    def test_an_unreadable_parent_is_reported_rather_than_raising(self) -> None:
        removed, skipped, files = sweep_workspaces(parent=Path("/nonexistent-sweep-root"))
        self.assertEqual((removed, files), (0, 0))


class RecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = temporary_root(self)
        self.parent = temporary_root(self)
        self.journal = VoiceJournal(self.directory / "voice-journal.jsonl")

    def test_recovery_reconciles_and_sweeps_and_truncates(self) -> None:
        self.journal.record_start(make_request(request_id="speech-1"))
        workspace = PrivateWorkspace(parent=self.parent)
        workspace.file("abandoned")
        old = time.time() - STALE_AFTER_SECONDS * 2
        os.utime(workspace.root, (old, old))

        report = recover(self.journal, parent=self.parent)
        self.assertEqual(report.marked_interrupted, ("speech-1",))
        self.assertEqual(report.workspaces_removed, 1)
        self.assertEqual(report.replayed, ())
        self.assertFalse(self.journal.path.exists())

    def test_a_second_recovery_finds_nothing_left(self) -> None:
        self.journal.record_start(make_request(request_id="speech-1"))
        recover(self.journal, parent=self.parent)
        second = recover(self.journal, parent=self.parent)
        self.assertEqual(second.uncertain, ())
        self.assertTrue(second.clean)

    def test_a_service_runs_recovery_before_it_starts_speaking(self) -> None:
        self.journal.record_start(make_request(request_id="speech-1"))
        service = VoiceService(VoiceServiceOptions(
            runtime_directory=self.directory,
            registry=ProviderRegistry([ScriptedProvider()]),
            router=__import__(
                "companion.voice.audio", fromlist=["AudioRouter"]
            ).AudioRouter([ScriptedBackend()]),
        ))
        self.addCleanup(service.close)
        self.assertEqual(service.recovery.marked_interrupted, ("speech-1",))
        self.assertEqual(service.recovery.replayed, ())

    def test_restarting_the_worker_leaves_the_task_and_captions_alone(self) -> None:
        service = VoiceService(VoiceServiceOptions(
            runtime_directory=self.directory,
            registry=ProviderRegistry([ScriptedProvider()]),
            router=__import__(
                "companion.voice.audio", fromlist=["AudioRouter"]
            ).AudioRouter([ScriptedBackend()]),
            preferences=VoicePreferences(speak_progress=True),
        ))
        self.addCleanup(service.close)
        caption = service.publish(presentation())
        request, reason = service.speak(caption.caption_id)
        self.assertIsNotNone(request, reason)
        self.assertTrue(service.worker.drain(timeout=BARRIER_TIMEOUT))

        report = service.restart_worker(timeout=BARRIER_TIMEOUT)
        self.assertEqual(report.replayed, ())
        self.assertTrue(service.worker.running)
        # The caption survives, and is still marked spoken so nothing repeats it.
        self.assertIsNotNone(service.ledger.get(caption.caption_id))
        self.assertTrue(service.ledger.already_spoken(caption.caption_id))
        again, why = service.speak(caption.caption_id)
        self.assertIsNone(again)
        self.assertIn("already been spoken", why)

    def test_an_explicit_replay_after_a_restart_is_permitted(self) -> None:
        service = VoiceService(VoiceServiceOptions(
            runtime_directory=self.directory,
            registry=ProviderRegistry([ScriptedProvider()]),
            router=__import__(
                "companion.voice.audio", fromlist=["AudioRouter"]
            ).AudioRouter([ScriptedBackend()]),
            preferences=VoicePreferences(speak_progress=True),
        ))
        self.addCleanup(service.close)
        caption = service.publish(presentation())
        service.speak(caption.caption_id)
        self.assertTrue(service.worker.drain(timeout=BARRIER_TIMEOUT))
        service.restart_worker(timeout=BARRIER_TIMEOUT)
        answer = service.dispatch("voice_speak", {"captionId": caption.caption_id, "replay": True})
        self.assertTrue(answer["accepted"], answer["reason"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
