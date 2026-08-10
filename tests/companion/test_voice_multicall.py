# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""A program's own idea of which program it is, and what happens when it changes.

Two of the three players in the allowlist are symbolic links to multi-call
binaries. ``/usr/bin/paplay`` points at ``pacat``; ``/usr/bin/pw-play`` points at
``pw-cat``. Under their own names the targets read **raw PCM**, and under the
link names they parse a sound file. Same binary, same version, same exit status,
different audio.

That difference was measured on the reference target and cost 2.07 seconds of a
2.80-second utterance: resolving the symlink made the runtime exec ``pacat``,
which played a RIFF header and mono samples as stereo raw data — 0.73 s of
noise, exit code 0. No test that checked "did it succeed" could have seen it.

The defences are three, and each is tested here as a thing that *refuses*:

1. resolution returns the requested path, never the symlink target;
2. the backend checks the command it is about to run against a declared
   :class:`~companion.voice.audio.PlayerContract` — program name, the arguments
   that carry the semantics, and the input format it expects — and refuses
   before a process exists;
3. the completion floor refuses a zero exit whose measured duration is
   implausibly short, and *names* which of the three shapes it was.

None of it is inferred from the resolved binary's basename, because the resolved
basename is precisely the thing that is wrong in the case this exists to catch.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest

from companion.voice.audio import (
    PLAYBACK_COMPLETION_FLOOR,
    RAW_PCM_DEFAULT_BYTES_PER_SECOND,
    AlsaBackend,
    PipeWireBackend,
    PlaybackHandle,
    PlayerContract,
    PulseAudioBackend,
)
from companion.voice.execution import CommandSpec, resolve_executable
from companion.voice.pcm import AudioProbe
from companion.voice.providers import EspeakNgProvider, SpeechDispatcherProvider

from .support import temporary_root

POSIX = os.name == "posix"

#: The measured case, to the numbers in the record. eSpeak NG wrote 2.799 s at
#: 22050 Hz mono 16-bit; ``pacat`` played all 123 524 bytes, header included, at
#: its raw default of 44100 Hz stereo 16-bit.
MEASURED_AUDIO_SECONDS = 2.799
MEASURED_BYTE_SIZE = 123_524


def _probe(seconds: float = MEASURED_AUDIO_SECONDS, byte_size: int = MEASURED_BYTE_SIZE) -> AudioProbe:
    return AudioProbe(
        path="utterance.wav", channels=1, sample_width=2, sample_rate=22_050,
        frame_count=int(seconds * 22_050), byte_size=byte_size,
    )


def _resolver_for(directory: Path):
    """A resolver bound to a scratch directory, with the real search rules."""
    def resolve(name: str) -> tuple[str, bool]:
        return resolve_executable(name, directories=(str(directory),))
    return resolve


def _plant(directory: Path, name: str, body: str = "exit 0\n") -> Path:
    program = directory / name
    program.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
    program.chmod(0o755)
    return program


class ResolutionKeepsTheRequestedIdentity(unittest.TestCase):
    """Defence 1. Both multi-call pairs, not only the one that was measured."""

    @unittest.skipUnless(POSIX, "symbolic links are a POSIX arrangement")
    def test_both_multicall_pairs_resolve_to_the_requested_name(self) -> None:
        for requested, target in (("paplay", "pacat"), ("pw-play", "pw-cat")):
            with self.subTest(requested=requested):
                directory = temporary_root(self)
                real = _plant(directory, target)
                (directory / requested).symlink_to(real)
                found, trusted = resolve_executable(requested, directories=(str(directory),))
                self.assertTrue(trusted)
                self.assertEqual(
                    Path(found).name, requested,
                    f"{requested} resolved to {Path(found).name}, which is a different program",
                )


class TheBackendChecksWhatItIsAboutToRun(unittest.TestCase):
    """Defence 2. The check that does not need a symlink to fire."""

    def test_every_backend_declares_a_contract(self) -> None:
        for backend in (PulseAudioBackend, PipeWireBackend, AlsaBackend):
            with self.subTest(backend=backend.backend_id):
                self.assertIsNotNone(backend.contract)
                self.assertEqual(backend.contract.program, backend.player)
                self.assertEqual(backend.contract.input_format, "sound-file")
                self.assertEqual(backend.contract.completion_floor, PLAYBACK_COMPLETION_FLOOR)

    def test_a_sibling_is_refused_and_the_refusal_names_the_format(self) -> None:
        contract = PulseAudioBackend.contract
        refusal = contract.refusal_for("/usr/bin/pacat", ("--client-name=bunny-companion", "--", "a.wav"))
        self.assertIn("pacat", refusal)
        self.assertIn("raw PCM", refusal)
        self.assertIn("exit status is still zero", refusal)

    def test_the_pipewire_sibling_is_refused_too(self) -> None:
        refusal = PipeWireBackend.contract.refusal_for(
            "/usr/bin/pw-cat", ("--volume=1.000", "--", "a.wav"),
        )
        self.assertIn("pw-cat", refusal)
        self.assertIn("raw PCM", refusal)

    def test_an_unrelated_substitution_is_refused_as_well(self) -> None:
        """The general case, not only the two names that happen to be known."""
        refusal = PulseAudioBackend.contract.refusal_for(
            "/usr/bin/something-else", ("--client-name=bunny-companion", "--", "a.wav"),
        )
        self.assertIn("something-else", refusal)
        self.assertIn("refused", refusal)

    def test_the_correct_program_with_its_arguments_is_accepted(self) -> None:
        self.assertEqual(
            PulseAudioBackend.contract.refusal_for(
                "/usr/bin/paplay",
                ("--volume=65536", "--latency-msec=60", "--client-name=bunny-companion", "--", "a.wav"),
            ),
            "",
        )

    def test_a_missing_required_argument_is_refused(self) -> None:
        """``--`` stops option parsing before the filename; it is not decoration."""
        refusal = PulseAudioBackend.contract.refusal_for(
            "/usr/bin/paplay", ("--client-name=bunny-companion", "a.wav"),
        )
        self.assertIn("--", refusal)
        self.assertIn("refused", refusal)

    def test_a_backend_with_no_contract_refuses_to_play(self) -> None:
        """Undeclared is unrunnable: the base class carries no default."""
        class Unchecked(PulseAudioBackend):
            contract = None

        backend = Unchecked(resolver=lambda name: ("/usr/bin/paplay", True))
        refusal = backend.verify_invocation(CommandSpec(executable="/usr/bin/paplay"))
        self.assertIn("declares no player contract", refusal)

    def test_the_real_backend_builds_the_invocation_its_contract_requires(self) -> None:
        """The declaration and the arguments the backend actually emits agree."""
        for backend_class in (PulseAudioBackend, PipeWireBackend, AlsaBackend):
            with self.subTest(backend=backend_class.backend_id):
                player = f"/usr/bin/{backend_class.player}"
                backend = backend_class(resolver=lambda name, _p=player: (_p, True))
                spec = backend._play_spec(
                    "/tmp/utterance.wav", device_id="RDPSink", volume=1.0,
                    latency_ms=60, seconds=MEASURED_AUDIO_SECONDS,
                )
                self.assertEqual(Path(spec.executable).name, backend_class.player)
                self.assertEqual(backend.verify_invocation(spec), "")


class ARefusedInvocationStartsNothing(unittest.TestCase):
    """A refusal costs no process, no device and no partial utterance."""

    def test_a_substituted_player_produces_an_unstarted_handle(self) -> None:
        backend = PulseAudioBackend(resolver=lambda name: ("/usr/bin/pacat", True))
        handle = backend.play("req-1", "/tmp/utterance.wav", device_id="RDPSink", probe=_probe())
        self.assertFalse(handle.started)
        self.assertIn("pacat", handle.start_error)
        self.assertIsNone(handle.poll())
        outcome = handle.wait()
        self.assertFalse(outcome.succeeded)
        self.assertIn("pacat", outcome.detail)

    def test_the_worker_treats_the_refusal_as_a_backend_failure_not_a_task_failure(self) -> None:
        """§8: a refused player degrades to captions and the task is untouched."""
        from .voice_support import BARRIER_TIMEOUT, ScriptedProvider, make_request
        from .test_voice_worker import WorkerHarness  # the suite's own harness
        from companion.voice.captions import SpeechDisposition

        backend = PulseAudioBackend(resolver=lambda name: ("/usr/bin/pacat", True))
        # Present the backend as ready without a server: the point of this test
        # is the refusal, and a health probe would fail for a different reason.
        backend._health = None
        backend.discover = lambda: (  # type: ignore[method-assign]
            __import__("companion.voice.audio", fromlist=["AudioDevice"]).AudioDevice(
                device_id="RDPSink", backend_id="pulse", name="RDPSink", default=True,
            ),
        )
        harness = WorkerHarness(
            backends=[backend], providers=[ScriptedProvider("scripted")],
        ).start()
        self.addCleanup(harness.close)
        harness.worker.submit(make_request(request_id="a", text="a sentence"))
        self.assertTrue(harness.worker.drain(timeout=BARRIER_TIMEOUT))
        self.assertEqual(
            harness.dispositions()["a"], SpeechDisposition.DEGRADED_TO_CAPTIONS,
        )


class TheCompletionFloorNamesTheShape(unittest.TestCase):
    """Defence 3. One rule, three named ways of missing it."""

    @staticmethod
    def _handle(*, elapsed: float, audio: float, byte_size: int) -> PlaybackHandle:
        """A handle over a child that exits immediately, with a scripted clock."""
        clock = iter([0.0] + [elapsed] * 64)
        last = [0.0]

        def now() -> float:
            try:
                last[0] = next(clock)
            except StopIteration:
                pass
            return last[0]

        spec = CommandSpec(
            executable=sys.executable, arguments=("-c", "pass"), timeout_seconds=30.0,
        )
        return PlaybackHandle(
            request_id="a", backend_id="pulse", device_id="RDPSink", spec=spec,
            audio_seconds=audio, monotonic=now,
            raw_pcm_seconds=byte_size / RAW_PCM_DEFAULT_BYTES_PER_SECOND,
        )

    def test_the_floor_is_still_six_tenths(self) -> None:
        """Retained unless a measurement supports a more precise rule; none does."""
        self.assertEqual(PLAYBACK_COMPLETION_FLOOR, 0.6)

    def test_the_measured_defect_is_named_as_a_container_read_as_raw_pcm(self) -> None:
        handle = self._handle(
            elapsed=0.73, audio=MEASURED_AUDIO_SECONDS, byte_size=MEASURED_BYTE_SIZE,
        )
        outcome = handle.wait()
        self.assertFalse(outcome.succeeded)
        self.assertTrue(outcome.truncated)
        self.assertEqual(outcome.completion_shape, "container-read-as-raw-pcm")
        self.assertIn("RIFF header", outcome.detail)
        self.assertIn("0.70s", outcome.detail)
        self.assertEqual(outcome.to_json()["completionShape"], "container-read-as-raw-pcm")

    def test_a_player_that_accepted_nothing_is_named_as_such(self) -> None:
        handle = self._handle(elapsed=0.01, audio=MEASURED_AUDIO_SECONDS, byte_size=MEASURED_BYTE_SIZE)
        outcome = handle.wait()
        self.assertFalse(outcome.succeeded)
        self.assertEqual(outcome.completion_shape, "no-frames-accepted")
        self.assertIn("no audio reached the device", outcome.detail)

    def test_a_short_exit_that_matches_no_known_shape_is_still_refused(self) -> None:
        handle = self._handle(elapsed=1.0, audio=MEASURED_AUDIO_SECONDS, byte_size=0)
        outcome = handle.wait()
        self.assertFalse(outcome.succeeded)
        self.assertEqual(outcome.completion_shape, "exited-before-minimum-duration")
        self.assertIn("did not play what it was given", outcome.detail)

    def test_a_dropped_tail_is_still_a_success(self) -> None:
        """An audio server may legitimately lose the last few milliseconds."""
        handle = self._handle(
            elapsed=MEASURED_AUDIO_SECONDS * 0.95, audio=MEASURED_AUDIO_SECONDS,
            byte_size=MEASURED_BYTE_SIZE,
        )
        outcome = handle.wait()
        self.assertTrue(outcome.succeeded)
        self.assertFalse(outcome.truncated)
        self.assertEqual(outcome.completion_shape, "")

    def test_the_raw_pcm_length_matches_the_measurement(self) -> None:
        """0.70 s expected against 0.73 s observed, on the recorded numbers."""
        expected = MEASURED_BYTE_SIZE / RAW_PCM_DEFAULT_BYTES_PER_SECOND
        self.assertAlmostEqual(expected, 0.70, places=2)
        self.assertLess(abs(0.73 - expected), 0.05)


class TheProviderKeepsItsAdapterIdentity(unittest.TestCase):
    """§3 for the synthesis half: which adapter, invoked how."""

    def test_the_provider_records_which_declared_name_it_resolved(self) -> None:
        provider = EspeakNgProvider(resolver=lambda name: (f"/usr/bin/{name}", True))
        self.assertEqual(provider.program_name(), "espeak-ng")

    def test_a_fallback_is_recorded_as_the_fallback_and_not_as_the_primary(self) -> None:
        """espeak and espeak-ng are different programs with different bugs."""
        from companion.voice.execution import ExecutableRefused

        def resolve(name: str) -> tuple[str, bool]:
            if name == "espeak-ng":
                raise ExecutableRefused("espeak-ng is not installed in a trusted directory")
            return f"/usr/bin/{name}", True

        provider = EspeakNgProvider(resolver=resolve)
        self.assertEqual(provider.program_name(), "espeak")

    def test_a_substituted_program_is_refused_before_it_runs(self) -> None:
        provider = EspeakNgProvider(resolver=lambda name: ("/usr/bin/speak-ng", True))
        # The adapter asked for espeak-ng and would start speak-ng.
        refusal = provider.verify_invocation(CommandSpec(
            executable="/usr/bin/speak-ng", arguments=("--stdin", "-v", "en"),
        ))
        self.assertIn("speak-ng", refusal)
        self.assertIn("multi-call sibling", refusal)
        self.assertIn("requested adapter was not preserved", refusal)

    def test_an_invocation_without_stdin_is_refused(self) -> None:
        """Without --stdin the caption goes in argv, where /proc publishes it."""
        provider = EspeakNgProvider(resolver=lambda name: (f"/usr/bin/{name}", True))
        refusal = provider.verify_invocation(CommandSpec(
            executable="/usr/bin/espeak-ng", arguments=("-v", "en", "-s", "175"),
        ))
        self.assertIn("--stdin", refusal)

    def test_speech_dispatcher_requires_pipe_mode_and_wait(self) -> None:
        provider = SpeechDispatcherProvider(resolver=lambda name: (f"/usr/bin/{name}", True))
        refusal = provider.verify_invocation(CommandSpec(
            executable="/usr/bin/spd-say", arguments=("--application-name", "bunny-companion"),
        ))
        self.assertIn("--pipe-mode", refusal)
        self.assertIn("--wait", refusal)

    def test_the_real_invocations_satisfy_their_own_declarations(self) -> None:
        from .voice_support import make_request
        from companion.voice.execution import PrivateWorkspace

        provider = EspeakNgProvider(resolver=lambda name: (f"/usr/bin/{name}", True))
        request = make_request(request_id="a", text="a sentence")
        arguments, _ = provider._tuning(request, "en")
        spec = CommandSpec(executable="/usr/bin/espeak-ng", arguments=tuple(arguments))
        self.assertEqual(provider.verify_invocation(spec), "")
        del PrivateWorkspace  # imported to assert the module is importable here

    def test_a_refused_invocation_is_data_and_never_an_exception(self) -> None:
        """§8: a provider never raises at a caller that has to keep a task alive."""
        from .voice_support import make_request

        provider = EspeakNgProvider(resolver=lambda name: ("/usr/bin/speak-ng", True))
        outcome = provider._guarded(
            make_request(request_id="a", text="hello"), None,
            CommandSpec(executable="/usr/bin/speak-ng", arguments=("--stdin", "-v", "en")),
        )
        self.assertIsNone(outcome.exit_code)
        self.assertFalse(outcome.succeeded)
        self.assertIn("requested adapter was not preserved", outcome.start_error)


class BehaviourIsNotInferredFromTheResolvedBasename(unittest.TestCase):
    """The property the whole of this file is about, stated once, directly."""

    @unittest.skipUnless(POSIX, "symbolic links are a POSIX arrangement")
    def test_a_correctly_named_link_to_a_sibling_is_accepted(self) -> None:
        """What matters is the name the program is started under, not its inode.

        ``/usr/bin/paplay`` *is* a symlink to ``pacat`` on the reference target,
        and that arrangement is correct — it is how the distribution ships. The
        runtime must run it, under the name ``paplay``. A check that refused
        anything whose target was a sibling would refuse the working case.
        """
        directory = temporary_root(self)
        real = _plant(directory, "pacat")
        (directory / "paplay").symlink_to(real)
        backend = PulseAudioBackend(resolver=_resolver_for(directory))
        spec = backend._play_spec(
            "/tmp/utterance.wav", device_id="", volume=1.0, latency_ms=60, seconds=1.0,
        )
        self.assertEqual(Path(spec.executable).name, "paplay")
        self.assertEqual(Path(spec.executable).resolve().name, "pacat")
        self.assertEqual(
            backend.verify_invocation(spec), "",
            "the shipped arrangement — paplay as a link to pacat — was refused",
        )

    def test_the_contract_is_declared_data_and_reportable(self) -> None:
        document = PulseAudioBackend.contract.to_json()
        self.assertEqual(document["program"], "paplay")
        self.assertEqual(document["inputFormat"], "sound-file")
        self.assertIn("pacat", document["multicallSiblings"])
        self.assertIn("--", document["requiredArguments"])
        self.assertEqual(document["completionFloor"], 0.6)

    def test_a_contract_may_not_be_satisfied_by_a_name_alone(self) -> None:
        """Name *and* arguments; either one missing is a refusal."""
        contract = PlayerContract(
            program="paplay", input_format="sound-file",
            multicall_siblings=("pacat",), required_arguments=("--client-name=", "--"),
        )
        self.assertNotEqual(contract.refusal_for("/usr/bin/paplay", ("--",)), "")
        self.assertNotEqual(contract.refusal_for("/usr/bin/pacat", ("--client-name=x", "--")), "")
        self.assertEqual(contract.refusal_for("/usr/bin/paplay", ("--client-name=x", "--")), "")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
