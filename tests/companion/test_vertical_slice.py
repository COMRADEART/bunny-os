# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from companion.approval import ApprovalResolution
from companion.gtk_shell import CompanionViewModel
from companion.model import Locality, PresentationKind, PrivacyClass
from companion.presentation import CapabilityPresentationPlan, PresentationSignals
from companion.protocol import CompanionClient, CompanionClientError, CompanionServer
from companion.providers import SpeechRequest, SpeechResult, VoiceDescriptor, VoiceProvider
from companion.runtime import CompanionRuntime, RuntimePaths


class RecordingVoice(VoiceProvider):
    def __init__(
        self,
        *,
        fail: bool = False,
        health: str = "healthy",
        locality: Locality = Locality.LOCAL,
        provider_id: str = "local-test-system-voice",
    ) -> None:
        self.requests: list[SpeechRequest] = []
        self.fail = fail
        self.health = health
        self.locality = locality
        self.provider_id = provider_id

    @property
    def descriptor(self):
        return VoiceDescriptor(
            provider_id=self.provider_id,
            voice_id="local-test-voice",
            languages=("en",),
            styles=("neutral",),
            streaming=False,
            cancellation=True,
            audio_formats=("system-device",),
            locality=self.locality,
            cost_class="free",
            privacy_classification=PrivacyClass.INTERNAL,
            health=self.health,
        )

    def speak(self, request):
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("voice failed")
        return SpeechResult(request.speech_id, completed=True)

    def cancel(self, speech_id):
        return True


def plan() -> CapabilityPresentationPlan:
    return CapabilityPresentationPlan(
        "plan-vertical-slice",
        "bunny.companion",
        "start_local",
        "static-avatar",
        PresentationKind.STATIC_IMAGE,
    )


def signals(*, audio: bool = True) -> PresentationSignals:
    return PresentationSignals(
        available_memory_bytes=1024 * 1024 * 1024,
        display_available=True,
        audio_output_available=audio,
        gpu_ready=False,
    )


class VerticalSliceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.voice = RecordingVoice()
        self.runtime = CompanionRuntime(
            paths=RuntimePaths(self.root / "state"),
            capability_plan=plan(),
            presentation_signals=signals(),
            voice_provider=self.voice,
        )
        self.server = CompanionServer(self.runtime, self.root / "runtime.sock")
        self.server.start_thread()

    def tearDown(self) -> None:
        self.server.close()
        self.runtime.close()
        self.directory.cleanup()

    def test_provider_free_end_to_end_slice_and_ui_restart(self) -> None:
        first_ui = CompanionClient(self.root / "runtime.sock")
        self.assertFalse(first_ui.health()["commercialProviderRequired"])
        pending = first_ui.submit("Record a harmless local demonstration result.")
        task_id = pending["task"]["taskId"]
        self.assertEqual(pending["state"]["state"], "waiting_for_approval")
        self.assertEqual(pending["task"]["executor"]["agentId"], "bunny/local-test-executor")
        self.assertEqual(pending["task"]["reviewers"][0]["agentId"], "bunny/local-test-reviewer")
        self.assertEqual(len(pending["approvals"]), 1)

        event_types = [item["eventType"] for item in pending["events"]]
        for required in (
            "task_created", "task_classified", "executor_selected", "reviewer_added",
            "planning_started", "tool_requested", "reviewer_observation", "approval_requested",
        ):
            self.assertIn(required, event_types)
        observation = next(item for item in pending["events"] if item["eventType"] == "reviewer_observation")
        self.assertEqual(observation["payload"]["reviewer"], "bunny/local-test-reviewer")
        self.assertEqual(observation["payload"]["severity"], "info")

        # A new client represents a restarted UI. The service and task remain.
        second_ui = CompanionClient(self.root / "runtime.sock")
        approval_centre = CompanionViewModel(second_ui, active_task_id=task_id)
        approval_centre.connect()
        restored = approval_centre.snapshot
        self.assertIsNotNone(restored)
        self.assertEqual(restored["latestSequence"], pending["latestSequence"])
        self.assertEqual(restored["state"]["state"], "waiting_for_approval")
        approval = approval_centre.approvals[0]
        completed = approval_centre.resolve(approval, "approve")
        self.assertEqual(completed["task"]["currentPhase"], "completed")
        self.assertEqual(completed["state"]["state"], "success")
        self.assertEqual(completed["task"]["toolOperations"][0]["status"], "completed")
        self.assertTrue(completed["task"]["outputs"])

        completed_types = [item["eventType"] for item in completed["events"]]
        for required in (
            "approval_resolved", "tool_started", "tool_progress", "tool_completed",
            "response_drafting", "speech_started", "speech_completed", "task_completed",
        ):
            self.assertIn(required, completed_types)
        self.assertEqual(len(self.voice.requests), 1)
        speech = next(item for item in completed["events"] if item["eventType"] == "speech_started")
        self.assertEqual(speech["payload"]["caption"], self.voice.requests[0].text)
        self.assertFalse(speech["payload"]["audioTransmitted"])

        third_ui = CompanionClient(self.root / "runtime.sock")
        final = third_ui.snapshot(task_id)
        self.assertEqual(final["state"]["state"], "success")
        view_model = CompanionViewModel(third_ui, active_task_id=task_id)
        view_model.connect()
        self.assertEqual(view_model.state["state"], "success")
        self.assertIn("completed", view_model.caption.lower())

        with self.assertRaises(CompanionClientError) as replayed:
            third_ui.resolve_approval(task_id, approval, "approve")
        self.assertEqual(replayed.exception.code, "approval_replay")

    def test_cancellation_is_persistent(self) -> None:
        client = CompanionClient(self.root / "runtime.sock")
        pending = client.submit("Cancel this harmless task.")
        task_id = pending["task"]["taskId"]
        cancelled = client.cancel(task_id)
        self.assertEqual(cancelled["task"]["currentPhase"], "cancelled")
        self.assertEqual(cancelled["state"]["state"], "cancelled")
        self.assertEqual(client.snapshot(task_id)["state"]["state"], "cancelled")

    def test_denial_blocks_and_takes_no_tool_action(self) -> None:
        client = CompanionClient(self.root / "runtime.sock")
        pending = client.submit("Deny this harmless task.")
        task_id = pending["task"]["taskId"]
        denied = client.resolve_approval(task_id, pending["approvals"][0], "deny")
        self.assertEqual(denied["task"]["currentPhase"], "blocked")
        self.assertEqual(denied["state"]["state"], "blocked")
        self.assertNotIn("tool_started", [item["eventType"] for item in denied["events"]])


class ProcessBoundaryVerticalSliceTests(unittest.TestCase):
    def test_service_entry_point_completes_provider_free_task(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            endpoint = temporary / "runtime.sock"
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(root / "services/bunny-companion/bunny_companion_service.py"),
                    "--state-directory", str(temporary / "state"),
                    "--socket", str(endpoint),
                    "--conservative",
                ],
                cwd=root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                client = CompanionClient(endpoint, timeout=1.0)
                deadline = time.monotonic() + 10.0
                last_error: Exception | None = None
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        break
                    try:
                        health = client.health()
                        break
                    except (CompanionClientError, OSError) as exc:
                        last_error = exc
                        time.sleep(0.05)
                else:
                    self.fail(f"companion service did not become ready: {last_error}")
                if process.poll() is not None:
                    stdout, stderr = process.communicate(timeout=1.0)
                    self.fail(f"companion service exited early: {stdout} {stderr}")
                self.assertFalse(health["commercialProviderRequired"])
                pending = client.submit("Complete a harmless process-boundary task.")
                completed = client.resolve_approval(
                    pending["task"]["taskId"], pending["approvals"][0], "approve"
                )
                self.assertEqual(completed["task"]["currentPhase"], "completed")
                self.assertEqual(completed["state"]["state"], "success")
            finally:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.communicate(timeout=5.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=5.0)


class RuntimeRecoveryTests(unittest.TestCase):
    def test_runtime_uses_permitted_local_voice_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            remote = RecordingVoice(
                health="unavailable",
                locality=Locality.REMOTE,
                provider_id="remote-test-voice",
            )
            local = RecordingVoice(provider_id="local-fallback-test-voice")
            runtime = CompanionRuntime(
                paths=RuntimePaths(Path(directory) / "state"),
                capability_plan=plan(),
                presentation_signals=signals(audio=True),
                voice_provider=remote,
                voice_fallbacks=(local,),
            )
            try:
                pending = runtime.submit("Use the permitted local voice fallback.")
                view = pending.approvals[0]
                completed = runtime.resolve_approval(pending.task.task_id, ApprovalResolution(
                    request_id=view["requestId"], decision="approve", plan_id=view["planId"],
                    transition_id=view["transitionId"], destination=view["destination"],
                    provider_destination=view["providerDestination"],
                ))
                self.assertEqual(completed.state["state"], "success")
                self.assertEqual(len(local.requests), 1)
                self.assertEqual(remote.requests, [])
            finally:
                runtime.close()

    def test_waiting_task_recovers_after_runtime_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = RuntimePaths(Path(directory) / "state")
            first = CompanionRuntime(
                paths=paths,
                capability_plan=plan(),
                presentation_signals=signals(audio=False),
                voice_provider=RecordingVoice(health="unavailable"),
            )
            pending = first.submit("Recover this harmless task after restart.")
            task_id = pending.task.task_id
            view = pending.approvals[0]
            first.close()

            second = CompanionRuntime(
                paths=paths,
                capability_plan=plan(),
                presentation_signals=signals(audio=False),
                voice_provider=RecordingVoice(health="unavailable"),
            )
            try:
                restored = second.snapshot(task_id)
                self.assertEqual(restored.state["state"], "waiting_for_approval")
                completed = second.resolve_approval(task_id, ApprovalResolution(
                    request_id=view["requestId"],
                    decision="approve",
                    plan_id=view["planId"],
                    transition_id=view["transitionId"],
                    destination=view["destination"],
                    provider_destination=view["providerDestination"],
                ))
                self.assertEqual(completed.state["state"], "success")
                self.assertIn("capability_degraded", [item.event_type for item in completed.events])
                self.assertNotIn("speech_started", [item.event_type for item in completed.events])
            finally:
                second.close()

    def test_completed_task_replays_after_runtime_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = RuntimePaths(Path(directory) / "state")
            first = CompanionRuntime(
                paths=paths,
                capability_plan=plan(),
                presentation_signals=signals(audio=False),
                voice_provider=RecordingVoice(health="unavailable"),
            )
            pending = first.submit("Complete and restore this task.")
            view = pending.approvals[0]
            completed = first.resolve_approval(pending.task.task_id, ApprovalResolution(
                request_id=view["requestId"], decision="approve", plan_id=view["planId"],
                transition_id=view["transitionId"], destination=view["destination"],
                provider_destination=view["providerDestination"],
            ))
            sequence = completed.latest_sequence
            first.close()
            second = CompanionRuntime(paths=paths, capability_plan=plan(), presentation_signals=signals(audio=False))
            try:
                restored = second.snapshot(pending.task.task_id)
                self.assertEqual(restored.state["state"], "success")
                self.assertEqual(restored.latest_sequence, sequence)
            finally:
                second.close()

    def test_voice_error_recovers_to_captions_and_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = CompanionRuntime(
                paths=RuntimePaths(Path(directory) / "state"),
                capability_plan=plan(),
                presentation_signals=signals(audio=True),
                voice_provider=RecordingVoice(fail=True),
            )
            try:
                pending = runtime.submit("Voice failure must not fail the task.")
                view = pending.approvals[0]
                completed = runtime.resolve_approval(pending.task.task_id, ApprovalResolution(
                    request_id=view["requestId"], decision="approve", plan_id=view["planId"],
                    transition_id=view["transitionId"], destination=view["destination"],
                    provider_destination=view["providerDestination"],
                ))
                self.assertEqual(completed.state["state"], "success")
                kinds = [item.event_type for item in completed.events]
                self.assertIn("speech_completed", kinds)
                self.assertIn("capability_degraded", kinds)
            finally:
                runtime.close()


class SchemaConformanceTests(unittest.TestCase):
    def test_vertical_slice_records_conform_when_jsonschema_is_available(self) -> None:
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema unavailable")
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            runtime = CompanionRuntime(
                paths=RuntimePaths(Path(directory) / "state"),
                capability_plan=plan(),
                presentation_signals=signals(audio=False),
                voice_provider=RecordingVoice(health="unavailable"),
            )
            try:
                snapshot = runtime.submit("Schema-check this harmless task.")
                pairs = (
                    (snapshot.task.to_json(), "companion-task.schema.json"),
                    (snapshot.state, "companion-state.schema.json"),
                    (snapshot.events[0].to_json(), "companion-event.schema.json"),
                    (snapshot.approvals[0], "companion-approval.schema.json"),
                    (runtime.voice.descriptor.to_json(), "companion-provider.schema.json"),
                )
                for document, name in pairs:
                    with self.subTest(schema=name):
                        schema = json.loads((root / "schemas" / name).read_text(encoding="utf-8"))
                        jsonschema.validate(document, schema)
            finally:
                runtime.close()


if __name__ == "__main__":
    unittest.main()
