# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Focused contracts for voice interaction and bounded computer control.

The speech worker's capture/backend fault matrix remains in the existing
speech suites. These tests cover the new seam: a real provider result crossing
the protocol bridge into the canonical task path, plus the newly declared safe
actions and settings boundaries.
"""

from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

from companion import local_files
from companion.intents import recognise
from companion.local_files import (
    SearchContextStore,
    resolve_search_result,
    search_files,
    validate_search_arguments,
)
from companion.local_intent import LocalIntentExecutor
from companion.local_system import get_system_metric, media_control
from companion.runtime import classify_request
from companion.settings import (
    Settings,
    SettingsError,
    SpeechInputSettings,
    VoiceSettings,
    load_settings,
    save_settings,
)
from companion.service import (
    CompanionGateway,
    CompanionService,
    InteractiveConsent,
    ServiceOptions,
)
from companion.speech.wakeword import WakeWordService, WakeWordState
from companion.tools import ToolBroker, ToolInvocationContext


ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / "shell/services/bin/bunny-shell-assistant"
EXTENSION = ROOT / "shell/components/gnome-shell-extension"


def load_bridge() -> object:
    loader = importlib.machinery.SourceFileLoader("bunny_voice_bridge_test", str(BRIDGE))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class LocalIntentRoutingTests(unittest.TestCase):
    def test_conversation_and_computer_state_are_not_conflated(self) -> None:
        self.assertIsNone(recognise("What is RAM?"))
        metric = recognise("How much RAM am I using?")
        self.assertEqual(metric.kind, "system_metric")
        self.assertEqual(metric.parameters["metric"], "memory")
        self.assertIsNone(recognise("Explain Files"))
        self.assertEqual(recognise("Open Files").kind, "open_application")

    def test_required_voice_phrases_are_local_actions_without_inference(self) -> None:
        for phrase in (
            "Open Files", "Find PDF files in Downloads",
            "How much memory am I using?", "Pause music",
        ):
            with self.subTest(phrase=phrase):
                task_type, capabilities = classify_request(phrase)
                self.assertEqual(task_type, "local_action")
                self.assertEqual(capabilities, ())

    def test_unrestricted_commands_are_not_recognised(self) -> None:
        for phrase in ("run rm -rf /", "open /etc/passwd", "delete my files", "sudo reboot"):
            self.assertIsNone(recognise(phrase), phrase)


class SafeFileSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.downloads = base / "Downloads"
        self.documents = base / "Documents"
        self.downloads.mkdir()
        self.documents.mkdir()
        self.roots = {"DOWNLOAD": self.downloads, "DOCUMENTS": self.documents}
        self.store = SearchContextStore()
        self.context = ToolInvocationContext(
            session_id="session-voice", task_id="task-search", lifecycle_epoch=0,
            plan_id="plan-search", operation_id="search-files", classification="personal",
        )

    def tearDown(self) -> None:
        local_files._SEARCH_CONTEXT.clear()  # noqa: SLF001 - isolate the process-local ledger
        self.temporary.cleanup()

    def _gateway_with_path_sink(self) -> tuple[CompanionGateway, object, object]:
        class Task:
            task_id = "task-path-authority"

        class Runtime:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str, object, object]] = []

            def submit_task(
                self, session_id: str, request: str, *,
                classification: object = None, cost_limit_units: object = None,
            ) -> Task:
                self.calls.append((session_id, request, classification, cost_limit_units))
                return Task()

        class Desktop:
            def __init__(self) -> None:
                self.contexts: dict[str, object] = {}

            def bind_path_context(self, task_id: str, context: object) -> None:
                self.contexts[task_id] = context

        runtime = Runtime()
        desktop = Desktop()
        gateway = CompanionGateway(
            runtime, consent=InteractiveConsent(maximum_wait_seconds=0.01),
        )
        gateway.attach_desktop(desktop)
        return gateway, runtime, desktop

    def test_filename_search_is_bounded_to_approved_roots(self) -> None:
        (self.downloads / "resume-final.pdf").write_text("private contents", encoding="utf-8")
        (self.documents / "resume-notes.txt").write_text("notes", encoding="utf-8")
        outcome = search_files(
            {"query": "resume", "scope": "all", "fileType": ""},
            self.context, roots=self.roots, store=self.store,
        )
        self.assertTrue(outcome.ok, outcome.detail)
        self.assertEqual(outcome.value["totalMatches"], 2)
        self.assertEqual(len(outcome.value["results"]), 2)
        rendered = repr(outcome.value)
        self.assertNotIn(self.temporary.name, rendered, "absolute paths must not reach presentation")
        self.assertNotIn("private contents", rendered, "file contents must never be read")

    def test_pdf_filter_in_downloads(self) -> None:
        (self.downloads / "one.pdf").write_bytes(b"%PDF")
        (self.downloads / "two.txt").write_text("x", encoding="utf-8")
        outcome = search_files(
            {"query": "", "scope": "downloads", "fileType": "pdf"},
            self.context, roots=self.roots, store=self.store,
        )
        self.assertTrue(outcome.ok)
        self.assertEqual([item["name"] for item in outcome.value["results"]], ["one.pdf"])

    def test_many_results_are_collapsed_but_retained_for_show_all(self) -> None:
        for index in range(10):
            (self.downloads / f"report-{index:02d}.pdf").write_bytes(b"%PDF")
        outcome = search_files(
            {"query": "report", "scope": "downloads", "fileType": "pdf"},
            self.context, roots=self.roots, store=self.store,
        )
        self.assertTrue(outcome.ok)
        self.assertEqual(len(outcome.value["results"]), 6)
        self.assertEqual(len(outcome.value["allResults"]), 10)
        self.assertIn("Show all", outcome.value["summary"])
        authority, reason = resolve_search_result(
            "session-voice", "10", store=self.store,
        )
        self.assertEqual(reason, "")
        self.assertIsNotNone(authority)

    def test_path_traversal_and_patterns_are_rejected(self) -> None:
        for query in ("../etc/passwd", "..", "*.pdf", "folder\\secret", "~/.ssh"):
            with self.subTest(query=query):
                reason = validate_search_arguments({
                    "query": query, "scope": "all", "fileType": "",
                })
                self.assertIsInstance(reason, str)

    def test_default_search_rejects_an_xdg_folder_outside_home(self) -> None:
        base = Path(self.temporary.name)
        home = base / "home"
        external = base / "external-downloads"
        home.mkdir()
        external.mkdir()
        (external / "outside.pdf").write_bytes(b"%PDF")
        with mock.patch.dict(os.environ, {
            "HOME": str(home),
            "XDG_DOWNLOAD_DIR": str(external),
        }):
            outcome = search_files(
                {"query": "", "scope": "downloads", "fileType": "pdf"},
                self.context, store=self.store,
            )
        self.assertFalse(outcome.ok)
        self.assertIn("not available", outcome.detail)

    def test_filesystem_names_are_safe_and_bounded_for_the_shell(self) -> None:
        rendered = local_files._safe_display("report\n\u202esecret" + "x" * 300, 40)
        self.assertLessEqual(len(rendered), 40)
        self.assertNotIn("\n", rendered)
        self.assertNotIn("\u202e", rendered)
        self.assertTrue(rendered.endswith("…"))

    def test_result_context_is_session_bound_and_actionable(self) -> None:
        newest = self.downloads / "resume.pdf"
        newest.write_bytes(b"%PDF")
        outcome = search_files(
            {"query": "resume", "scope": "downloads", "fileType": ""},
            self.context, roots=self.roots, store=self.store,
        )
        self.assertTrue(outcome.ok)
        authority, reason = resolve_search_result(
            "session-voice", "newest", store=self.store,
        )
        self.assertEqual(reason, "")
        self.assertIsNotNone(authority)
        self.assertEqual(authority.path, newest.resolve())
        self.assertEqual(authority.root, self.downloads.resolve())

        refused, reason = resolve_search_result(
            "session-other", "1", store=self.store,
        )
        self.assertIsNone(refused)
        self.assertIn("no recent", reason)

        newest.unlink()
        newest.mkdir()
        refused, reason = resolve_search_result(
            "session-voice", "1", store=self.store,
        )
        self.assertIsNone(refused)
        self.assertIn("regular file", reason)

    def test_result_action_has_a_closed_command_enum(self) -> None:
        opened = recognise("Open the first result")
        shown = recognise("Show the first result in its containing folder")
        self.assertEqual(opened.parameters["command"], "open")
        self.assertEqual(shown.parameters["command"], "show_containing_folder")
        self.assertEqual(recognise("Open result 24").parameters["selector"], "24")
        self.assertIsNone(recognise("Open result 25"))
        self.assertIsNone(recognise("Delete the first result"))

    def test_show_directory_takes_a_key_not_a_path(self) -> None:
        with mock.patch("companion.local_intent.user_directory", return_value=self.downloads):
            operations, _summary = LocalIntentExecutor()._operations_for(  # noqa: SLF001
                recognise("Show my Downloads")
            )
        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0].tool, "desktop.uri.open")
        self.assertEqual(operations[0].arguments, {
            "expectedScheme": "file",
            "expectedDestinationClass": "local-file",
            "pathReference": "requested-directory",
        })
        self.assertNotIn(str(self.downloads), repr(operations[0].arguments))
        self.assertIsNone(recognise("Open ../../etc"))

    def test_recent_result_plan_uses_existing_desktop_action_and_opaque_reference(self) -> None:
        intent = recognise("Open the newest one")
        operations, _summary = LocalIntentExecutor()._operations_for(intent)  # noqa: SLF001
        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0].tool, "desktop.uri.open")
        self.assertEqual(operations[0].arguments["pathReference"], "search-result")
        self.assertNotIn("selector", operations[0].arguments)
        self.assertNotIn("uri", operations[0].arguments)

    def test_local_file_module_has_no_parallel_desktop_launcher(self) -> None:
        source = (ROOT / "companion/local_files.py").read_text(encoding="utf-8")
        self.assertNotIn("Gio.AppInfo.launch_default_for_uri", source)
        self.assertNotIn("files.result_action", local_files.LOCAL_FILE_TOOLS)
        self.assertNotIn("files.show_directory", local_files.LOCAL_FILE_TOOLS)

    def test_gateway_places_a_recent_result_in_canonical_task_authority(self) -> None:
        result = self.downloads / "resume.pdf"
        result.write_bytes(b"%PDF")
        outcome = search_files(
            {"query": "resume", "scope": "downloads", "fileType": ""},
            self.context, roots=self.roots,
        )
        self.assertTrue(outcome.ok)
        gateway, runtime, desktop = self._gateway_with_path_sink()
        task = gateway._submit_runtime_task(  # noqa: SLF001 - canonical submission seam
            "session-voice", "Open the first result",
        )
        self.assertEqual(runtime.calls[0][1], "Open the first result")
        context = desktop.contexts[task.task_id]
        resolved = context.resolve("search-result")
        self.assertEqual(Path(resolved.real_path), result.resolve())
        self.assertEqual(context.identifiers(), ("search-result",))

    def test_gateway_builds_directory_authority_from_a_closed_key(self) -> None:
        gateway, _runtime, desktop = self._gateway_with_path_sink()
        with mock.patch("companion.local_intent.user_directory", return_value=self.downloads):
            task = gateway._submit_runtime_task(  # noqa: SLF001 - canonical submission seam
                "session-voice", "Show my Downloads",
            )
        context = desktop.contexts[task.task_id]
        resolved = context.resolve("requested-directory")
        self.assertTrue(resolved.is_directory)
        self.assertEqual(Path(resolved.real_path), self.downloads.resolve())

    @unittest.skipUnless(os.name == "posix", "file URI execution is a Linux desktop acceptance")
    def test_recent_result_runs_through_real_gateway_approval_and_desktop_broker(self) -> None:
        from companion.approvals import CompanionApprovalStore, ScriptedConsent
        from companion.desktop.catalogue import DESCRIPTORS
        from companion.desktop_bridge import DesktopSupport, register_desktop_tools
        from companion.runtime import CompanionRuntime, RuntimeOptions
        from companion.store import CompanionStore
        from tests.companion.desktop_support import FakeAdapters
        from tests.companion.support import machine

        adapters = FakeAdapters()
        support = DesktopSupport.create(
            adapters=adapters,
            ledger_path=Path(self.temporary.name) / "desktop-ledger.json",
        )
        broker = ToolBroker()
        broker.tools = {**broker.tools, **local_files.LOCAL_FILE_TOOLS}
        register_desktop_tools(broker, support)
        approval_classes = tuple(sorted({
            descriptor.approval_class for descriptor in DESCRIPTORS.values()
        }))
        runtime = CompanionRuntime(RuntimeOptions(
            store=CompanionStore(Path(self.temporary.name) / "store"),
            assessment=machine(),
            executors=(LocalIntentExecutor(),),
            reviewers=(),
            broker=broker,
            approvals=CompanionApprovalStore(),
            consent=ScriptedConsent(granted_actions=approval_classes),
            desktop=support,
        ))
        gateway = CompanionGateway(
            runtime, consent=InteractiveConsent(maximum_wait_seconds=0.01),
        )
        gateway.attach_desktop(support)
        result = self.downloads / "resume.pdf"
        result.write_bytes(b"%PDF")
        with mock.patch.dict(os.environ, {
            "HOME": self.temporary.name,
            "WAYLAND_DISPLAY": "wayland-test",
        }):
            support.start()
            runtime.start()
            gateway.start_worker()
            try:
                search = gateway.submit_task(
                    sessionId=runtime.create_session("Voice").session_id,
                    request="Find my resume", classification=None,
                    costLimitUnits=None, run=True,
                )
                self.assertTrue(gateway.drain())
                session_id = str(search["sessionId"])
                opened = gateway.submit_task(
                    sessionId=session_id, request="Open the first result",
                    classification=None, costLimitUnits=None, run=True,
                )
                self.assertTrue(gateway.drain())
                _resolved_session, task = runtime.find_task(opened["task"]["taskId"])
                self.assertEqual(task.state, "completed")
                self.assertEqual(len(adapters.called("uri.open")), 1)
                self.assertNotIn(task.task_id, support.path_contexts)
            finally:
                gateway.stop_worker()
                runtime.stop()
                support.stop()


class SystemAndMediaToolTests(unittest.TestCase):
    def test_system_metric_uses_measured_reader_output(self) -> None:
        outcome = get_system_metric(
            {"metric": "memory"},
            memory_reader=lambda: (True, "Measured memory: 42%.", ""),
        )
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.value, "Measured memory: 42%.")

    def test_unknown_metric_is_refused_before_any_reader(self) -> None:
        called = False

        def reader() -> tuple[bool, str, str]:
            nonlocal called
            called = True
            return True, "wrong", ""

        outcome = get_system_metric({"metric": "temperature"}, memory_reader=reader)
        self.assertFalse(outcome.ok)
        self.assertFalse(called)

    def test_mpris_command_validation(self) -> None:
        class Controller:
            def __init__(self) -> None:
                self.commands: list[str] = []

            def control(self, command: str) -> tuple[bool, str]:
                self.commands.append(command)
                return True, ""

        controller = Controller()
        self.assertTrue(media_control({"command": "pause"}, controller=controller).ok)
        self.assertEqual(controller.commands, ["pause"])
        self.assertFalse(media_control({"command": "stop"}, controller=controller).ok)
        self.assertEqual(controller.commands, ["pause"])

    def test_undeclared_shell_tool_is_still_refused(self) -> None:
        outcome = ToolBroker().invoke(
            "shell.run", {"command": "anything"}, caller="runtime")
        self.assertFalse(outcome.ok)
        self.assertIn("not an allowed tool", outcome.detail)


class VoiceSettingsTests(unittest.TestCase):
    def test_voice_settings_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = Settings(
                voice=VoiceSettings(enabled=True, response_mode="voice-only"),
                speech_input=SpeechInputSettings(
                    enabled=True, device_id="mic-1", model_id="vosk-model-small-en-us-0.15",
                    language="en", wake_word="disabled", shortcut="<Super><Alt>space",
                ),
            )
            save_settings(root, document)
            loaded = load_settings(root, strict=True)
            self.assertEqual(loaded, document)
            self.assertEqual(loaded.voice_preferences().response_mode, "voice-only")
            self.assertEqual(loaded.speech_preferences().input_device, "mic-1")

    def test_invalid_wake_word_and_response_modes_fail_closed(self) -> None:
        with self.assertRaises(SettingsError):
            SpeechInputSettings(wake_word="enabled")
        with self.assertRaises(SettingsError):
            VoiceSettings(response_mode="sometimes")

    def test_wake_word_service_cannot_enable_capture(self) -> None:
        service = WakeWordService()
        self.assertEqual(service.state, WakeWordState.DISABLED)
        self.assertFalse(service.describe()["opensMicrophone"])
        with self.assertRaises(RuntimeError):
            service.enable()

    def test_settings_protocol_persists_the_focused_voice_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gateway = CompanionGateway(
                SimpleNamespace(), consent=InteractiveConsent(maximum_wait_seconds=0.01),
                settings_root=root,
            )
            before = gateway.settings_voice_get()
            self.assertTrue(before["voiceInput"])
            answer = gateway.settings_voice_set(
                voiceInput=False, speechResponses=False, responseMode="never",
                deviceId="", modelId="", language="automatic",
                shortcut="<Super><Alt>space", wakeWord="disabled",
            )
            self.assertTrue(answer["saved"])
            self.assertFalse(load_settings(root, strict=True).speech_input.enabled)
            self.assertFalse(load_settings(root, strict=True).voice.enabled)

    def test_the_engine_round_trips_through_the_wire_contract(self) -> None:
        """get, set Kitten, get, set Pocket, get — through the operations only.

        The two operations were absent from the validated wire schema for a
        release: the protocol declared them, the service implemented them, and
        the contract a peer checks against did not list them. They are listed
        now, and this is the behaviour behind the listing — that the engine a
        person chooses is the engine that comes back, and that it survives being
        re-read from disk rather than from the object that wrote it.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gateway = CompanionGateway(
                SimpleNamespace(), consent=InteractiveConsent(maximum_wait_seconds=0.01),
                settings_root=root,
            )

            def current() -> str:
                return str(gateway.settings_voice_get()["ttsProviderId"])

            def choose(provider: str) -> None:
                answer = gateway.settings_voice_set(
                    voiceInput=True, speechResponses=True, responseMode="voice-only",
                    deviceId="", modelId="", language="automatic",
                    shortcut="<Super><Alt>space", wakeWord="disabled",
                    ttsProviderId=provider,
                )
                self.assertTrue(answer["saved"], provider)

            self.assertEqual(current(), "pocket", "Pocket is the shipped default")
            choose("kitten")
            self.assertEqual(current(), "kitten")
            # Read from the file rather than the gateway, so this is persistence
            # and not a value held in memory by the object that stored it.
            self.assertEqual(load_settings(root, strict=True).voice.provider_id, "kitten")
            choose("pocket")
            self.assertEqual(current(), "pocket")
            self.assertEqual(load_settings(root, strict=True).voice.provider_id, "pocket")

    def test_an_engine_the_registry_does_not_own_is_refused(self) -> None:
        """A provider id is data from a client, and the fallback order is fixed."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gateway = CompanionGateway(
                SimpleNamespace(), consent=InteractiveConsent(maximum_wait_seconds=0.01),
                settings_root=root,
            )
            with self.assertRaises(SettingsError):
                gateway.settings_voice_set(
                    voiceInput=True, speechResponses=True, responseMode="voice-only",
                    deviceId="", modelId="", language="automatic",
                    shortcut="<Super><Alt>space", wakeWord="disabled",
                    ttsProviderId="../../../usr/bin/espeak-ng",
                )
            self.assertEqual(
                load_settings(root, strict=True).voice.provider_id, "pocket")

    def test_service_restart_restores_saved_voice_and_input_preferences(self) -> None:
        """The login service must not replace saved settings with defaults."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save_settings(root, Settings(
                voice=VoiceSettings(
                    enabled=True,
                    response_mode="all",
                    provider_id="kitten",
                    model_id="nano-int8",
                    voice_id="Bella",
                    speaking_rate=1.25,
                    performance_mode="automatic",
                ),
                speech_input=SpeechInputSettings(
                    enabled=False,
                    device_id="alsa_input.test",
                    model_id="vosk-model-small-en-us-0.15",
                    language="en",
                ),
            ))
            service = CompanionService.__new__(CompanionService)
            service.options = ServiceOptions(root=root)
            service.root = root
            service.runtime = SimpleNamespace(clock=mock.sentinel.clock)
            service.voice = None

            with mock.patch("companion.voice.service.VoiceService") as voice_constructor:
                service._build_voice()
            voice_options = voice_constructor.call_args.args[0]
            self.assertEqual(voice_options.preferences.provider_id, "kitten")
            self.assertEqual(voice_options.preferences.model_id, "nano-int8")
            self.assertEqual(voice_options.preferences.voice_id, "Bella")
            self.assertEqual(voice_options.preferences.response_mode, "all")
            self.assertAlmostEqual(voice_options.preferences.speaking_rate, 1.25)

            with mock.patch("companion.speech.service.SpeechInputService") as speech_constructor:
                service._build_speech()
            speech_options = speech_constructor.call_args.args[0]
            self.assertFalse(speech_options.preferences.enabled)
            self.assertEqual(speech_options.preferences.input_device, "alsa_input.test")
            self.assertEqual(
                speech_options.preferences.model_id,
                "vosk-model-small-en-us-0.15",
            )


class _BridgeConnection:
    def __init__(self, *, confidence: float | None = 0.93, disposition: str = "") -> None:
        self.confidence = confidence
        self.disposition = disposition
        self.calls: list[tuple[str, dict[str, object]]] = []

    def list_sessions(self) -> dict[str, object]:
        return {"sessions": [{"title": "Bunny Desktop", "sessionId": "session-voice"}]}

    def create_session(self, **_params: object) -> dict[str, object]:
        return {"session": {"sessionId": "session-voice", "title": "Bunny Desktop"}}

    def call(self, operation: str, params: dict[str, object]) -> dict[str, object]:
        self.calls.append((operation, dict(params)))
        if operation == "speech_input_start":
            return {
                "accepted": True, "requestId": "speechreq-1",
                "cancellationToken": "speechtok-1",
            }
        if operation == "speech_input_status":
            if self.disposition:
                return {
                    "capturing": False, "current": None, "recentEvents": [],
                    "recentDispositions": [{
                        "requestId": "speechreq-1", "disposition": self.disposition,
                        "detail": "provider failed",
                    }],
                }
            return {
                "capturing": False,
                "current": None,
                "recentDispositions": [],
                "recentEvents": [{
                    "kind": "final_transcript", "sequence": 1,
                    "requestId": "speechreq-1", "sessionId": "session-voice",
                    "text": "Open Files", "confidence": self.confidence,
                    "language": "en", "providerId": "vosk",
                    "textDigest": "abc123", "audioStartedAt": 0.0,
                    "audioEndedAt": 1.25, "incomplete": False,
                }],
            }
        if operation == "speech_input_confirm":
            return {
                "submitted": True, "sessionId": "session-voice",
                "task": {"taskId": "task-voice"},
            }
        if operation == "speech_input_cancel":
            return {"cancelled": True}
        if operation == "voice_health":
            return {"policy": {"preferences": {"responseMode": "voice-only"}}}
        if operation == "voice_speak":
            return {
                "accepted": True, "requestId": "voicereq-1",
                "cancellationToken": "voicetok-1",
            }
        if operation == "voice_status":
            return {"recentEvents": [
                {
                    "kind": "audio_started", "requestId": "voicereq-1",
                    "providerId": "pocket", "backendId": "pipewire",
                    "deviceId": "default-output",
                },
                {"kind": "speech_finished", "requestId": "voicereq-1"},
            ]}
        if operation in ("speech_input_stop", "voice_cancel"):
            return {"cancelled": ["voicereq-1"], "count": 1}
        raise AssertionError(operation)

    def get_presentation_state(self, _task_id: str) -> dict[str, object]:
        return {
            "revision": 1,
            "captionId": "caption-1",
            "events": [],
            "state": {
                "phase": "success", "statusText": "Done",
                "approvalState": "not_required", "resultSummary": "Files is open.",
                "errorSummary": "",
            },
        }


class VoiceBridgeFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bridge = load_bridge()
        self.events: list[dict[str, object]] = []
        self.bridge.emit = lambda event, **fields: self.events.append({"event": event, **fields})
        self.bridge.time.sleep = lambda _seconds: None

    def _arguments(self) -> argparse.Namespace:
        return argparse.Namespace(
            timeout=1.0, session_title="Bunny Desktop",
            activation_source="push-to-talk-button", language="", device="", provider="",
            deadline=10.0, task_deadline=10.0, no_speech=False,
            presentation_revision=17,
        )

    def test_valid_stt_result_enters_the_canonical_task_and_real_tts_seam(self) -> None:
        connection = _BridgeConnection()
        self.bridge.client = lambda _timeout: connection
        result = self.bridge.command_listen(self._arguments())
        self.assertEqual(result, 0)
        names = [item["event"] for item in self.events]
        self.assertIn("transcript", names)
        transcript = next(item for item in self.events if item["event"] == "transcript")
        self.assertEqual(transcript["text"], "Open Files")
        self.assertIn("accepted", names)
        self.assertIn("speech_started", names)
        self.assertIn("speech_finished", names)
        self.assertEqual(names[-1], "finished")
        calls = [name for name, _params in connection.calls]
        self.assertLess(calls.index("speech_input_confirm"), calls.index("voice_speak"))
        confirmed = next(params for name, params in connection.calls if name == "speech_input_confirm")
        self.assertEqual(confirmed["reviewedDigest"], "abc123")
        self.assertIsNone(confirmed["text"], "the reviewed provider transcript is submitted unchanged")

    def test_bridge_carries_the_bounded_show_all_result_set_without_paths(self) -> None:
        events = [{
            "eventType": "operation_completed",
            "sequence": 11,
            "payload": {
                "name": "search-files",
                "value": {
                    "results": [{
                        "reference": "result-1", "name": "one.pdf",
                        "display": "Downloads/one.pdf",
                    }],
                    "allResults": [{
                        "reference": f"result-{index}", "name": f"{index}.pdf",
                        "display": f"Downloads/{index}.pdf",
                    } for index in range(1, 11)],
                },
            },
        }]
        results = self.bridge._file_results(events)
        self.assertEqual(len(results), 10)
        self.assertNotIn("path", repr(results).casefold())

    def test_fast_action_replays_working_before_real_speech_and_success(self) -> None:
        connection = _BridgeConnection()
        connection.get_presentation_state = lambda _task_id: {
            "revision": 19,
            "captionId": "caption-1",
            "events": [
                {
                    "eventType": "operation_started", "sequence": 13,
                    "payload": {"name": "launch-application"},
                },
                {
                    "eventType": "operation_completed", "sequence": 15,
                    "payload": {"name": "launch-application", "value": {}},
                },
                {
                    "eventType": "task_state_changed", "sequence": 16,
                    "payload": {"to": "reviewing"},
                },
                {
                    "eventType": "reviewer_observation", "sequence": 17,
                    "payload": {},
                },
                {
                    "eventType": "result_created", "sequence": 18,
                    "payload": {},
                },
                {
                    "eventType": "task_completed", "sequence": 19,
                    "payload": {},
                },
            ],
            "state": {
                "phase": "success", "statusText": "Done",
                "approvalState": "granted", "resultSummary": "Files is open.",
                "errorSummary": "",
            },
        }

        self.assertEqual(self.bridge.watch(
            connection, "task-voice", deadline=self.bridge.time.monotonic() + 10,
            speak_response=True,
        ), 0)
        phases = [
            item["phase"] for item in self.events if item["event"] == "phase"
        ]
        self.assertIn("working", phases)
        self.assertIn("speaking", phases)
        self.assertNotIn("reviewing", phases)
        self.assertEqual(phases[-1], "success")
        self.assertLess(phases.index("working"), phases.index("speaking"))

    def test_low_confidence_transcript_does_not_execute(self) -> None:
        connection = _BridgeConnection(confidence=0.1)
        self.bridge.client = lambda _timeout: connection
        self.assertEqual(self.bridge.command_listen(self._arguments()), 0)
        calls = [name for name, _params in connection.calls]
        self.assertIn("speech_input_cancel", calls)
        self.assertNotIn("speech_input_confirm", calls)
        self.assertIn("warning", [item["event"] for item in self.events])

    def test_stt_provider_failure_is_terminal_and_does_not_create_a_task(self) -> None:
        connection = _BridgeConnection(disposition="failed")
        self.bridge.client = lambda _timeout: connection
        self.assertEqual(self.bridge.command_listen(self._arguments()), 4)
        self.assertNotIn("speech_input_confirm", [name for name, _params in connection.calls])
        self.assertEqual(self.events[-1]["event"], "error")

    def test_tts_cancellation_is_not_reported_as_a_task_failure(self) -> None:
        connection = _BridgeConnection()

        def call(operation: str, params: dict[str, object]) -> dict[str, object]:
            if operation == "voice_speak":
                return {"accepted": True, "requestId": "voicereq-1", "cancellationToken": "x"}
            if operation == "voice_status":
                return {"recentEvents": [{"kind": "speech_cancelled", "requestId": "voicereq-1"}]}
            raise AssertionError(operation)

        connection.call = call
        disposition, _detail = self.bridge._speak_result(
            connection, "caption-1", "task-voice", deadline=self.bridge.time.monotonic() + 1)
        self.assertEqual(disposition, "cancelled")

    def test_tts_provider_failure_is_reported_without_changing_task_state(self) -> None:
        connection = _BridgeConnection()
        connection.call = lambda operation, _params: (
            {"accepted": False, "reason": "no local synthesizer"}
            if operation == "voice_speak" else {}
        )
        disposition, detail = self.bridge._speak_result(
            connection, "caption-1", "task-voice", deadline=self.bridge.time.monotonic() + 1)
        self.assertEqual(disposition, "failed")
        self.assertIn("synthesizer", detail)

    def test_capture_request_is_hard_bounded_to_thirty_seconds(self) -> None:
        connection = _BridgeConnection(confidence=0.1)
        self.bridge.client = lambda _timeout: connection
        self.bridge.command_listen(self._arguments())
        start = next(params for name, params in connection.calls if name == "speech_input_start")
        self.assertEqual(start["maxCaptureMs"], 30_000)
        self.assertEqual(start["presentationRevision"], 17)

    def test_headless_bridge_revision_zero_never_calls_the_capture_service(self) -> None:
        connection = _BridgeConnection()
        self.bridge.client = lambda _timeout: connection
        arguments = self._arguments()
        arguments.presentation_revision = 0
        self.assertEqual(self.bridge.command_listen(arguments), 4)
        self.assertFalse(connection.calls)
        self.assertEqual(self.events[-1]["event"], "error")

    def test_approval_control_reloads_and_returns_the_canonical_binding(self) -> None:
        binding = {
            "requestId": "approval:voice-1", "sessionId": "session-voice",
            "taskId": "task-voice", "planId": "plan-voice",
            "transitionId": "transition-voice", "action": "launch_application",
            "destination": "local", "providerId": "",
            "dataClassification": "internal", "estimatedCostUnits": None,
            "destinationFingerprint": "sha256:abc", "decision": "pending",
            "reason": "Open Files.",
        }

        class ApprovalConnection:
            def __init__(self) -> None:
                self.resolved: tuple[dict[str, object], str] | None = None

            def get_presentation_state(self, task_id: str) -> dict[str, object]:
                self.task_id = task_id
                return {"state": {"approvals": [binding]}}

            def resolve_approval(
                self, sent: dict[str, object], decision: str
            ) -> dict[str, object]:
                self.resolved = (sent, decision)
                return {"resolved": True}

        connection = ApprovalConnection()
        self.bridge.client = lambda _timeout: connection
        arguments = argparse.Namespace(
            timeout=1.0, task_id="task-voice",
            request_id="approval:voice-1", decision="allow",
        )
        self.assertEqual(self.bridge.command_approval(arguments), 0)
        self.assertEqual(connection.task_id, "task-voice")
        self.assertIsNotNone(connection.resolved)
        sent, decision = connection.resolved or ({}, "")
        self.assertEqual(decision, "granted")
        self.assertEqual(set(sent), set(self.bridge.APPROVAL_BINDING_FIELDS))
        self.assertNotIn("reason", sent)
        self.assertEqual(self.events[-1]["event"], "approval_resolved")

    def test_capture_cancellation_waits_for_confirmed_microphone_close(self) -> None:
        connection = _BridgeConnection()
        self.bridge.client = lambda _timeout: connection
        arguments = argparse.Namespace(
            request_id="speechreq-1", cancellation_token="speechtok-1", timeout=1.0,
        )
        self.assertEqual(self.bridge.command_speech_cancel(arguments), 0)
        event = self.events[-1]
        self.assertEqual(event["event"], "speech_cancelled")
        self.assertTrue(event["microphoneClosed"])
        calls = [name for name, _params in connection.calls]
        self.assertLess(calls.index("speech_input_cancel"), calls.index("speech_input_status"))

    def test_microphone_unavailable_health_is_a_normal_answer(self) -> None:
        connection = _BridgeConnection()

        def call(operation: str, _params: dict[str, object]) -> dict[str, object]:
            if operation == "speech_input_health":
                return {
                    "available": True,
                    "recognizers": [{"ready": True, "providerId": "vosk"}],
                    "policy": {"decision": {"mayCapture": True, "reasons": []}},
                }
            if operation == "speech_input_devices":
                return {"devices": [], "preferredDevice": ""}
            raise AssertionError(operation)

        connection.call = call
        self.bridge.client = lambda _timeout: connection
        args = argparse.Namespace(timeout=1.0)
        self.assertEqual(self.bridge.command_voice_health(args), 0)
        self.assertFalse(self.events[-1]["available"])
        self.assertIn("no microphone", str(self.events[-1]["reason"]))

    def test_missing_packaged_model_has_a_normal_user_facing_state(self) -> None:
        connection = _BridgeConnection()

        def call(operation: str, _params: dict[str, object]) -> dict[str, object]:
            if operation == "speech_input_health":
                return {
                    "available": True,
                    "readinessState": "STT_MODEL_MISSING",
                    "readiness": {
                        "state": "STT_MODEL_MISSING",
                        "ready": False,
                        "message": "Voice recognition isn't installed yet.",
                    },
                    "recognizers": [{
                        "ready": False,
                        "providerId": "vosk",
                        "detail": "developer-only model path diagnostic",
                    }],
                    "policy": {"decision": {"mayCapture": False, "reasons": []}},
                }
            if operation == "speech_input_devices":
                return {"devices": [{"deviceId": "mic-1"}], "preferredDevice": ""}
            raise AssertionError(operation)

        connection.call = call
        self.bridge.client = lambda _timeout: connection
        self.assertEqual(
            self.bridge.command_voice_health(argparse.Namespace(timeout=1.0)), 0)
        event = self.events[-1]
        self.assertFalse(event["available"])
        self.assertEqual(event["readinessState"], "STT_MODEL_MISSING")
        self.assertEqual(event["reason"], "Voice recognition isn't installed yet.")


class ShellVoiceBoundaryTests(unittest.TestCase):
    def test_shell_renders_voice_but_contains_no_audio_or_inference_api(self) -> None:
        voice = (EXTENSION / "lib/services/voice.js").read_text(encoding="utf-8")
        shell = (EXTENSION / "lib/desktopShell.js").read_text(encoding="utf-8")
        combined = voice + shell
        for forbidden in ("pw-record", "parec", "arecord", "Gvc.Mixer", "vosk", "whisper"):
            self.assertNotIn(forbidden, combined)
        self.assertIn("speech_input", BRIDGE.read_text(encoding="utf-8"))

    def test_privacy_indicator_precedes_the_service_start_call(self) -> None:
        shell = (EXTENSION / "lib/desktopShell.js").read_text(encoding="utf-8")
        body = shell.split("_startVoice(", 1)[1].split("_ownsVoice(", 1)[0]
        self.assertLess(body.index("_setMicrophoneVisible(true)"), body.index("this.voice.start("))
        self.assertIn("setMicrophoneActive", (EXTENSION / "lib/topBar.js").read_text(encoding="utf-8"))
        voice = (EXTENSION / "lib/services/voice.js").read_text(encoding="utf-8")
        bridge = BRIDGE.read_text(encoding="utf-8")
        self.assertIn("--presentation-revision", voice)
        self.assertIn('"presentationRevision"', bridge)

    def test_shell_renders_and_resolves_action_approval_without_weakening_policy(self) -> None:
        bridge = BRIDGE.read_text(encoding="utf-8")
        assistant = (EXTENSION / "lib/services/assistant.js").read_text(encoding="utf-8")
        voice = (EXTENSION / "lib/services/voice.js").read_text(encoding="utf-8")
        panel = (EXTENSION / "lib/assistant/panel.js").read_text(encoding="utf-8")
        shell = (EXTENSION / "lib/desktopShell.js").read_text(encoding="utf-8")
        self.assertIn('emit(\n                    "approval"', bridge)
        self.assertIn("APPROVAL_BINDING_FIELDS", bridge)
        self.assertIn("connection.resolve_approval(binding, decision)", bridge)
        self.assertIn("case 'approval':", assistant)
        self.assertIn("case 'approval':", voice)
        self.assertIn("showApproval(approval", panel)
        self.assertIn("'Deny'", panel)
        self.assertIn("'Allow'", panel)
        self.assertIn("resolveApproval(", shell)

    def test_stop_keeps_indicator_until_companion_confirms_device_closed(self) -> None:
        service = (EXTENSION / "lib/services/voice.js").read_text(encoding="utf-8")
        stop_method = service.split("stopCapture()", 1)[1].split("interruptSpeech()", 1)[0]
        self.assertIn("speech-stop", stop_method)
        self.assertNotIn("this._microphoneActive = false", stop_method)

        shell = (EXTENSION / "lib/desktopShell.js").read_text(encoding="utf-8")
        stop_branch = shell.split("this._voicePhase === 'listening'", 1)[1].split(
            "this._voicePhase === 'stopping'", 1)[0]
        self.assertIn("this._voicePhase = 'stopping'", stop_branch)
        self.assertNotIn("this._setMicrophoneVisible(false)", stop_branch)

    def test_cancel_and_escape_keep_indicator_until_worker_terminal_status(self) -> None:
        bridge = BRIDGE.read_text(encoding="utf-8")
        cancel = bridge.split("def command_speech_cancel", 1)[1].split(
            "def command_voice_cancel", 1)[0]
        self.assertIn('connection.call("speech_input_status"', cancel)
        self.assertIn('payload["microphoneClosed"] = True', cancel)

        service = (EXTENSION / "lib/services/voice.js").read_text(encoding="utf-8")
        self.assertIn("get cancellationPending()", service)
        self.assertIn("line.microphoneClosed === true", service)
        self.assertIn("onMicrophoneClosed", service)

        shell = (EXTENSION / "lib/desktopShell.js").read_text(encoding="utf-8")
        dismiss = shell.split("_dismissAssistant() {", 1)[1].split("_ask(", 1)[0]
        self.assertIn("_releaseVoiceInteraction", dismiss)
        self.assertNotIn("_setMicrophoneVisible(false)", dismiss)

    def test_push_to_talk_avoids_gnome_input_source_shortcuts(self) -> None:
        schema = (EXTENSION / "schemas/org.gnome.shell.extensions.bunny-shell.gschema.xml").read_text(encoding="utf-8")
        binding = schema.split('name="push-to-talk"', 1)[1].split("</key>", 1)[0]
        self.assertNotIn("&lt;Super&gt;space", binding)
        self.assertNotIn("&lt;Super&gt;&lt;Shift&gt;space", binding)
        self.assertIn("&lt;Super&gt;&lt;Alt&gt;space", binding)

    def test_shell_teardown_cancels_voice_service(self) -> None:
        shell = (EXTENSION / "lib/desktopShell.js").read_text(encoding="utf-8")
        self.assertIn("['voice', this.voice]", shell)
        self.assertIn("voice.cancel", shell)
        self.assertIn("interruptSpeech", shell)

    def test_typed_and_voice_originated_speech_share_interrupt_controls(self) -> None:
        assistant = (EXTENSION / "lib/services/assistant.js").read_text(encoding="utf-8")
        shell = (EXTENSION / "lib/desktopShell.js").read_text(encoding="utf-8")
        panel = (EXTENSION / "lib/assistant/panel.js").read_text(encoding="utf-8")
        self.assertIn("case 'speech_started':", assistant)
        self.assertIn("['voice-cancel', taskId]", assistant)
        self.assertIn("this.interruptSpeech();", assistant.split("ask(text", 1)[1])
        self.assertIn("this.assistant?.interruptSpeech()", shell)
        start = shell.split("_startVoice(", 1)[1].split("_ownsVoice(", 1)[0]
        self.assertLess(start.index("=== 'speaking'"), start.index("available === false"))
        self.assertIn("this._voiceStoppable = phase === 'speaking'", panel)

    def test_character_lifecycle_has_every_voice_state_transition(self) -> None:
        shell = (EXTENSION / "lib/desktopShell.js").read_text(encoding="utf-8")
        assistant = (EXTENSION / "lib/services/assistant.js").read_text(encoding="utf-8")
        for state in ("listening", "thinking", "working", "talking", "success", "warning", "error"):
            self.assertIn(state, shell + assistant)
        self.assertIn("transcribing: 'thinking'", assistant)

    def test_talking_begins_only_after_voice_worker_audio_started(self) -> None:
        bridge = BRIDGE.read_text(encoding="utf-8")
        wait = bridge.split("def _wait_for_speech", 1)[1].split("def _speak_result", 1)[0]
        speak = bridge.split("def _speak_result", 1)[1].split("def watch", 1)[0]
        self.assertIn('kind == "audio_started"', wait)
        self.assertIn("on_audio_started(event)", wait)
        self.assertIn("on_audio_started=_audio_started", speak)

        assistant = (EXTENSION / "lib/services/assistant.js").read_text(encoding="utf-8")
        self.assertIn("presenting_result: 'thinking'", assistant)
        shell = (EXTENSION / "lib/desktopShell.js").read_text(encoding="utf-8")
        typed_reply = shell.split("onReply:", 1)[1].split("onFileResults:", 1)[0]
        self.assertNotIn("setState('talking'", typed_reply)
        speech_started = shell.split("onSpeechStarted:", 1)[1].split("onSpeechFinished:", 1)[0]
        self.assertIn("setSpeaking(true)", speech_started)
        self.assertIn("setState('talking'", speech_started)

    def test_tts_and_recognition_model_selectors_save_separate_values(self) -> None:
        settings = (ROOT / "shell/services/bunny_shell/ui.py").read_text(encoding="utf-8")
        self.assertIn(
            '"modelId": recognition_model_values[model.get_selected()]',
            settings,
        )
        self.assertIn(
            '"ttsModelId": tts_model_values[tts_model.get_selected()]',
            settings,
        )
        self.assertNotIn('"ttsModelId": model_values[', settings)

    def test_file_results_have_a_bounded_scroll_area_and_show_all_control(self) -> None:
        panel = (EXTENSION / "lib/assistant/panel.js").read_text(encoding="utf-8")
        css = (EXTENSION / "stylesheet.css").read_text(encoding="utf-8")
        self.assertIn("results.slice(0, 24)", panel)
        self.assertIn("Show all ${this._fileResultItems.length} results", panel)
        self.assertIn("bunny-assistant-file-results-scroll", panel)
        self.assertIn("max-height: 132px", css)


if __name__ == "__main__":
    unittest.main()
