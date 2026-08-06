# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The capture layer: bounded buffering, recorder contracts, routing, activity.

Everything here runs without a device: the buffer and the detector are pure,
the contracts are string functions, and the router is exercised over scripted
backends implementing the real protocol.
"""

from __future__ import annotations

import unittest

from companion.speech.activity import SpeechActivityDetector
from companion.speech.capture import (
    AlsaCaptureBackend,
    BoundedFrameBuffer,
    CAPTURE_DEGRADATION_KINDS,
    CaptureDegradation,
    CaptureRouter,
    PipeWireCaptureBackend,
    PulseAudioCaptureBackend,
    RecorderContract,
)

from .speech_support import (
    ScriptedCaptureBackend,
    make_request,
    silence_pcm,
    speech_pcm,
)


class BoundedBuffer(unittest.TestCase):
    """§7: overruns are counted, budgets end capture, memory never grows."""

    def test_frames_flow_through_in_order(self) -> None:
        buffer = BoundedFrameBuffer()
        buffer.push(b"aa")
        buffer.push(b"bb")
        self.assertEqual(buffer.read(timeout=0.0), b"aabb")
        self.assertEqual(buffer.read(timeout=0.0), b"")

    def test_a_lagging_consumer_drops_and_counts_never_grows(self) -> None:
        buffer = BoundedFrameBuffer(maximum_buffered_bytes=4096)
        kept = buffer.push(b"x" * 4096)
        overrun = buffer.push(b"y" * 100)
        self.assertTrue(kept)
        self.assertTrue(overrun, "an overrun keeps reading; a budget does not")
        self.assertEqual(buffer.dropped_bytes, 100)
        self.assertEqual(buffer.dropped_chunks, 1)
        self.assertTrue(buffer.overran)
        self.assertLessEqual(buffer.buffered_bytes, 4096)

    def test_the_total_budget_stops_the_reader(self) -> None:
        buffer = BoundedFrameBuffer(maximum_total_bytes=8192)
        self.assertTrue(buffer.push(b"x" * 8000))
        self.assertFalse(buffer.push(b"y" * 500), "past the budget the reader stops")
        self.assertTrue(buffer.exhausted)

    def test_a_closed_buffer_refuses_and_releases(self) -> None:
        buffer = BoundedFrameBuffer()
        buffer.push(b"x" * 100)
        buffer.close()
        self.assertFalse(buffer.push(b"y"))
        self.assertEqual(buffer.buffered_bytes, 0)


class RecorderContracts(unittest.TestCase):
    """The multi-call hazard, checked before anything runs."""

    def test_a_sibling_substitution_is_refused_with_the_fact(self) -> None:
        contract = PulseAudioCaptureBackend.contract
        refusal = contract.refusal_for("/usr/bin/pacat", ("--raw",))
        self.assertIn("pacat", refusal)
        self.assertIn("multi-call sibling", refusal)

    def test_an_unknown_substitution_is_refused_generally(self) -> None:
        contract = PulseAudioCaptureBackend.contract
        refusal = contract.refusal_for("/usr/bin/evil", ("--raw",))
        self.assertIn("substitution", refusal)

    def test_missing_declared_arguments_are_refused(self) -> None:
        contract = RecorderContract(
            program="parec", output_format="raw-pcm",
            required_arguments=("--client-name=", "--format="),
        )
        refusal = contract.refusal_for("/usr/bin/parec", ("--format=s16le",))
        self.assertIn("--client-name=", refusal)

    def test_the_declared_invocation_passes(self) -> None:
        backend = PulseAudioCaptureBackend
        spec_args = (
            "--device=RDPSource", "--format=s16le", "--rate=16000",
            "--channels=1", "--latency-msec=60", "--client-name=bunny-companion-mic",
            "--raw",
        )
        self.assertEqual(backend.contract.refusal_for("/usr/bin/parec", spec_args), "")

    def test_every_backend_declares_a_contract(self) -> None:
        for backend in (PulseAudioCaptureBackend, PipeWireCaptureBackend, AlsaCaptureBackend):
            with self.subTest(backend=backend.backend_id):
                self.assertIsNotNone(backend.contract)
                self.assertTrue(backend.contract.multicall_siblings)

    def test_a_prefix_rule_cannot_satisfy_an_exact_argument(self) -> None:
        contract = RecorderContract(
            program="arecord", output_format="raw-pcm", required_arguments=("-q",),
        )
        self.assertIn("-q", contract.refusal_for("/usr/bin/arecord", ("-qq",)))


class DegradationRecords(unittest.TestCase):
    def test_the_kinds_are_closed(self) -> None:
        with self.assertRaises(ValueError):
            CaptureDegradation(kind="something-new", stage="capture", detail="x")

    def test_a_degradation_cannot_affect_a_task_by_type(self) -> None:
        with self.assertRaises(ValueError):
            CaptureDegradation(
                kind="input-overrun", stage="capture", detail="x", task_affected=True,
            )

    def test_the_kind_list_covers_section_seventeen(self) -> None:
        for needed in (
            "no-capture-device-at-startup", "device-removed-during-capture",
            "default-device-changed", "capture-permission-denied",
            "audio-server-restart", "unsupported-capture-format", "input-overrun",
        ):
            self.assertIn(needed, CAPTURE_DEGRADATION_KINDS)


class Routing(unittest.TestCase):
    """Selection, monitors, backoff and hysteresis over scripted backends."""

    def test_the_first_ready_backend_and_its_default_device_are_selected(self) -> None:
        down = ScriptedCaptureBackend("down", reachable=False)
        up = ScriptedCaptureBackend("up", devices=("mic-a", "mic-b"))
        router = CaptureRouter([down, up])
        backend, device, reasons = router.select(make_request())
        self.assertIs(backend, up)
        self.assertEqual(device.device_id, "mic-a")
        self.assertTrue(any("down" in reason for reason in reasons))

    def test_a_monitor_source_is_never_selected_by_default(self) -> None:
        backend = ScriptedCaptureBackend("only-monitors", devices=(), monitors=("sink.monitor",))
        router = CaptureRouter([backend])
        chosen, device, reasons = router.select(make_request())
        self.assertIsNone(device)
        self.assertTrue(any("monitor" in reason for reason in reasons))

    def test_an_explicitly_named_monitor_is_honoured(self) -> None:
        """The loopback diagnostic path: by exact name only, never by default."""
        backend = ScriptedCaptureBackend(
            "mixed", devices=("mic",), monitors=("sink.monitor",),
        )
        router = CaptureRouter([backend])
        _backend, device, _reasons = router.select(
            make_request(device_preference="sink.monitor")
        )
        self.assertEqual(device.device_id, "sink.monitor")
        self.assertTrue(device.monitor)

    def test_a_vanished_preferred_device_falls_back_with_a_record(self) -> None:
        backend = ScriptedCaptureBackend("one", devices=("mic",))
        router = CaptureRouter([backend])
        _backend, device, _reasons = router.select(
            make_request(device_preference="unplugged-mic")
        )
        self.assertEqual(device.device_id, "mic")
        kinds = [item.kind for item in router.degradations]
        self.assertIn("device-removed-before-capture", kinds)

    def test_a_penalised_backend_backs_off_on_a_growing_interval(self) -> None:
        now = [1000.0]
        backend = ScriptedCaptureBackend()
        router = CaptureRouter([backend], monotonic=lambda: now[0])
        router.penalise(backend.backend_id, kind="capture-backend-crash", detail="x")
        chosen, _device, reasons = router.select(make_request())
        self.assertIsNone(chosen)
        self.assertTrue(any("backing off" in reason for reason in reasons))
        now[0] += router.BACKOFF_SECONDS + 0.1
        chosen, _device, _reasons = router.select(make_request())
        self.assertIsNotNone(chosen)

    def test_restoration_requires_consecutive_healthy_observations(self) -> None:
        now = [1000.0]
        backend = ScriptedCaptureBackend()
        router = CaptureRouter([backend], monotonic=lambda: now[0])
        router.penalise(backend.backend_id, kind="capture-backend-crash", detail="x")
        state = router._state[backend.backend_id]
        self.assertGreater(state.blocked_until, now[0])
        router.observe()
        self.assertGreater(state.blocked_until, 0.0, "one healthy answer is not restoration")
        router.observe()
        self.assertEqual(state.blocked_until, 0.0)
        kinds = [item.kind for item in router.degradations]
        self.assertIn("audio-server-restart", kinds)

    def test_the_router_reports_no_physical_microphone_validated(self) -> None:
        router = CaptureRouter([ScriptedCaptureBackend()])
        self.assertFalse(router.describe()["physicalMicrophoneValidated"])


class Activity(unittest.TestCase):
    """§15 from the samples alone: the same PCM twice gives the same answer twice."""

    def _detector(self, **extra) -> SpeechActivityDetector:
        options = {
            "sample_rate": 16_000,
            "channels": 1,
            "initial_silence_seconds": 1.0,
            "endpoint_silence_seconds": 0.4,
            "maximum_seconds": 30.0,
        }
        options.update(extra)
        return SpeechActivityDetector(**options)

    def test_silence_alone_ends_at_the_initial_timeout(self) -> None:
        detector = self._detector()
        state = detector.feed(silence_pcm(2.0))
        self.assertTrue(state.ended)
        self.assertEqual(state.end_reason, "initial-silence")
        self.assertFalse(state.speech_detected)

    def test_speech_is_detected_and_trailing_silence_ends_it(self) -> None:
        detector = self._detector()
        state = detector.feed(speech_pcm(1.0))
        self.assertTrue(state.speech_detected)
        state = detector.feed(silence_pcm(1.0))
        self.assertTrue(state.ended)
        self.assertEqual(state.end_reason, "endpoint-silence")

    def test_the_maximum_duration_ends_even_continuous_speech(self) -> None:
        detector = self._detector(maximum_seconds=1.5)
        state = detector.feed(speech_pcm(3.0))
        self.assertTrue(state.ended)
        self.assertEqual(state.end_reason, "maximum-duration")

    def test_the_answer_is_deterministic(self) -> None:
        body = speech_pcm(0.8) + silence_pcm(1.0)
        first = self._detector().feed(body)
        second = self._detector().feed(body)
        self.assertEqual(first.to_json(), second.to_json())

    def test_calibration_only_raises_the_floor_and_saturates_honestly(self) -> None:
        detector = self._detector()
        # A loud room during calibration raises the floor…
        detector.feed(speech_pcm(0.3))
        state = detector.state()
        self.assertGreaterEqual(state.noise_floor, detector.configured_floor)
        # …and can never lower it below the configured one.
        quiet = self._detector()
        quiet.feed(silence_pcm(0.3))
        self.assertEqual(quiet.state().noise_floor, quiet.configured_floor)

    def test_the_detector_disclaims_biometrics(self) -> None:
        described = self._detector().describe()
        self.assertFalse(described["speakerIdentification"])
        self.assertFalse(described["biometricCapability"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
