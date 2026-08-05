# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixtures for the voice suite: barriers, scripted providers, and real WAV files.

Two rules run through everything here, and both come from §19.

**Barriers, not sleeps.** Every place a test needs to be *inside* an operation —
cancelling during synthesis, removing a device mid-playback, restarting the
renderer while the mouth is moving — is expressed as a :class:`threading.Event`
the fake waits on and the test releases. A ``sleep(0.1)`` that usually lands in
the right window is a test that fails on a loaded machine and, worse, passes on
a fast one when the code is broken. The one thing a barrier cannot express is
"the child process really ignored SIGTERM", which is why those tests start a
real interpreter rather than a fake.

**Real audio where audio is the point.** :func:`write_wav` writes an actual RIFF
file with a shaped waveform, so the amplitude viseme path is exercised on real
samples rather than on a list of numbers a test made up. The shape matters: a
constant tone produces one mouth position and would let a broken envelope
calculation pass.

The scripted provider and backend implement the real contracts —
:class:`companion.voice.provider.VoiceProvider` and
:class:`companion.voice.audio.AudioBackend` — rather than being mocks with the
methods the test happens to call. A fake that did not satisfy the protocol would
let the protocol drift.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
import os
from pathlib import Path
import struct
import sys
import threading
from typing import Any, Callable, Iterable, Mapping, Sequence
import wave

from companion.clock import Clock
from companion.presentation import PresentationRecommendation, PresentationState
from companion.voice.audio import (
    AudioDevice,
    BackendHealth,
    PlaybackHandle,
    PlaybackOutcome,
)
from companion.voice.execution import CancellationSignal, CommandOutcome, PrivateWorkspace
from companion.voice.pcm import AudioProbe, probe_wav
from companion.voice.provider import (
    ProviderDeclaration,
    ProviderHealth,
    ResourceEstimate,
    StreamOutcome,
    SynthesisResult,
    VoiceDescriptor,
)
from companion.voice.request import (
    InterruptionPolicy,
    Priority,
    VoiceRequest,
)

__all__ = [
    "FakeClock",
    "ScriptedBackend",
    "ScriptedProvider",
    "collect_events",
    "make_request",
    "presentation",
    "write_wav",
]

#: How long any barrier in this suite will wait before giving up. Long enough
#: that a loaded machine does not produce a spurious failure, short enough that
#: a genuine deadlock is reported rather than hanging the run.
BARRIER_TIMEOUT = 10.0


class FakeClock:
    """A clock a test drives, with the two hands separable.

    Not :class:`companion.clock.FrozenClock`: the voice runtime measures
    durations across real subprocess calls, so a clock that never moved would
    make every measured latency zero. This one advances by hand *and* can be put
    into a mode where monotonic tracks the real one, which is what the tests
    that exercise actual playback need.
    """

    def __init__(self, *, wall_seconds: float = 1767225600.0, monotonic_seconds: float = 1000.0) -> None:
        self.wall_seconds = wall_seconds
        self.monotonic_seconds = monotonic_seconds
        self._guard = threading.RLock()

    def wall(self) -> float:
        with self._guard:
            return self.wall_seconds

    def monotonic(self) -> float:
        with self._guard:
            return self.monotonic_seconds

    def advance(self, seconds: float) -> None:
        with self._guard:
            self.wall_seconds += seconds
            self.monotonic_seconds += seconds


def write_wav(
    path: Path | str,
    *,
    seconds: float = 0.4,
    sample_rate: int = 22_050,
    channels: int = 1,
    sample_width: int = 2,
    shape: str = "syllables",
) -> Path:
    """Write a real WAV file whose loudness varies over time.

    ``shape`` chooses the envelope. ``syllables`` alternates loud and quiet in
    120 ms blocks, which is roughly a speaking rate and — crucially — produces
    *several different* mouth shapes. A constant tone would produce one, and a
    test asserting "the timeline has more than one shape" would then be
    asserting something about the fixture rather than about the code.
    """
    target = Path(path)
    frames = int(seconds * sample_rate)
    data = bytearray()
    for index in range(frames):
        moment = index / sample_rate
        if shape == "silent":
            level = 0.0
        elif shape == "constant":
            level = 0.5
        else:
            block = int(moment / 0.12)
            level = (0.15, 0.9, 0.45, 0.05)[block % 4]
        value = level * math.sin(2 * math.pi * 220 * moment)
        for _ in range(channels):
            if sample_width == 2:
                data += struct.pack("<h", int(max(-1.0, min(1.0, value)) * 32000))
            else:
                data += struct.pack("<B", int(128 + max(-1.0, min(1.0, value)) * 120))
    with wave.open(str(target), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(sample_width)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(data))
    return target


def presentation(
    *,
    session_id: str = "session-1",
    task_id: str = "task-1",
    phase: str = "success",
    status_text: str = "Counting the words in your note.",
    result_summary: str = "There are forty-two words in your note.",
    error_summary: str = "",
    approval_state: str = "not_required",
    classification: str = "internal",
    revision: int = 7,
) -> PresentationState:
    """A canonical projection, built the way the runtime builds one."""
    return PresentationState(
        session_id=session_id,
        task_id=task_id,
        phase=phase,
        base_phase=phase,
        status_text=status_text,
        result_summary=result_summary,
        error_summary=error_summary,
        approval_state=approval_state,
        privacy_classification=classification,
        revision=revision,
        recommendation=PresentationRecommendation(
            implementation="static-image", audio_available=True
        ),
    )


def make_request(
    *,
    request_id: str = "speech-1",
    session_id: str = "session-1",
    task_id: str = "task-1",
    caption_reference: str = "cap-1",
    text: str = "There are forty-two words in your note.",
    priority: Priority = Priority.TASK_RESULT,
    interruption_policy: InterruptionPolicy = InterruptionPolicy.QUEUE,
    **extra: Any,
) -> VoiceRequest:
    return VoiceRequest(
        request_id=request_id,
        session_id=session_id,
        task_id=task_id,
        caption_reference=caption_reference,
        speech_text=text,
        priority=priority,
        interruption_policy=interruption_policy,
        **extra,
    )


def collect_events(worker: Any) -> tuple[list[Any], Callable[[], list[str]]]:
    """Subscribe to a worker and return the list plus a kinds-only view."""
    received: list[Any] = []
    lock = threading.Lock()

    def _observe(event: Any) -> None:
        with lock:
            received.append(event)

    worker.subscribe(_observe)

    def kinds() -> list[str]:
        with lock:
            return [item.kind for item in received]

    return received, kinds


# --------------------------------------------------------------------------- #
# A provider a test can steer
# --------------------------------------------------------------------------- #


class ScriptedProvider:
    """A real :class:`companion.voice.provider.VoiceProvider` a test drives.

    Every failure mode §21 asks for is a constructor argument rather than a
    subclass, so a test reads as one line describing the machine it is
    pretending to be.
    """

    def __init__(
        self,
        provider_id: str = "scripted",
        *,
        available: bool = True,
        healthy: bool = True,
        authenticated: bool = True,
        supports_synthesis: bool = True,
        supports_streaming: bool = True,
        languages: Sequence[str] = ("en",),
        locales: Sequence[str] = ("en-GB", "en-US"),
        sample_rates: Sequence[int] = (22_050,),
        audio_formats: Sequence[str] = ("wav-pcm-s16le",),
        maximum_privacy_class: str = "secret",
        local: bool = True,
        cost_class: str = "free",
        #: Held open while ``synthesize`` runs. A test releases it to let
        #: synthesis finish; leaving it closed is how "cancel during synthesis"
        #: is expressed without a sleep.
        synthesis_gate: threading.Event | None = None,
        #: Set by the fake the moment ``synthesize`` is entered.
        synthesis_entered: threading.Event | None = None,
        stream_gate: threading.Event | None = None,
        stream_entered: threading.Event | None = None,
        #: ``"crash"`` returns a failure, ``"empty"`` returns success with a file
        #: that has no frames, ``"timeout"`` reports a timed-out command.
        failure_mode: str = "",
        stderr: str = "",
        audio_seconds: float = 0.3,
        voices: Sequence[VoiceDescriptor] | None = None,
    ) -> None:
        self.provider_id = provider_id
        self._available = available
        self._healthy = healthy
        self._authenticated = authenticated
        self.synthesis_gate = synthesis_gate
        self.synthesis_entered = synthesis_entered
        self.stream_gate = stream_gate
        self.stream_entered = stream_entered
        self.failure_mode = failure_mode
        self.stderr = stderr
        self.audio_seconds = audio_seconds
        self.closed = False
        self.cancelled: list[str] = []
        self.synthesise_calls = 0
        self.stream_calls = 0
        self._guard = threading.RLock()
        self._active: dict[str, CancellationSignal] = {}
        self._voices = tuple(voices) if voices is not None else (
            VoiceDescriptor(
                voice_id=f"{provider_id}-en", provider_id=provider_id, name="Scripted English",
                language="en", locale="en-GB", preference=0.9, default=True,
            ),
        )
        self._declaration = ProviderDeclaration(
            provider_id=provider_id,
            implementation_id=f"{provider_id}/test",
            languages=tuple(languages),
            locales=tuple(locales),
            audio_formats=tuple(audio_formats),
            sample_rates=tuple(sample_rates),
            supports_synthesis=supports_synthesis,
            supports_streaming=supports_streaming,
            supports_cancellation=True,
            rate_control=True,
            pitch_control=True,
            volume_control=True,
            local=local,
            cost_class=cost_class,
            maximum_privacy_class=maximum_privacy_class,
        )

    @property
    def declaration(self) -> ProviderDeclaration:
        return self._declaration

    def set_declaration(self, **changes: Any) -> None:
        self._declaration = replace(self._declaration, **changes)

    def inventory(self) -> Sequence[VoiceDescriptor]:
        return self._voices if self._available else ()

    def health(self, *, monotonic: float = 0.0, refresh: bool = False) -> ProviderHealth:
        return ProviderHealth(
            provider_id=self.provider_id,
            available=self._available and not self.closed,
            authenticated=self._authenticated,
            healthy=self._healthy,
            detail="" if self._available else "the scripted provider is unavailable",
            checked_at_monotonic=monotonic,
        )

    def set_available(self, value: bool) -> None:
        self._available = value

    def set_healthy(self, value: bool) -> None:
        self._healthy = value

    def estimate(self, request: VoiceRequest) -> ResourceEstimate:
        return ResourceEstimate(
            memory_bytes=1024 * 1024, temporary_bytes=4096, cpu_share=0.1,
            expected_latency_seconds=0.01,
        )

    def synthesize(
        self,
        request: VoiceRequest,
        workspace: PrivateWorkspace,
        *,
        cancellation: CancellationSignal | None = None,
    ) -> SynthesisResult:
        with self._guard:
            self.synthesise_calls += 1
            if cancellation is not None:
                self._active[request.request_id] = cancellation
        if self.synthesis_entered is not None:
            self.synthesis_entered.set()
        if self.synthesis_gate is not None:
            # Waits for the test *or* for a cancellation, so a test that
            # cancels without releasing the gate does not deadlock the worker.
            while not self.synthesis_gate.wait(0.01):
                if cancellation is not None and cancellation.cancelled:
                    break
        failed = lambda detail: SynthesisResult(  # noqa: E731 - a local shorthand
            request_id=request.request_id,
            provider_id=self.provider_id,
            implementation_id=self._declaration.implementation_id,
            voice_id=request.voice_id or self._voices[0].voice_id,
            succeeded=False,
            detail=detail,
            outcome=CommandOutcome(
                executable="scripted", redacted_argv=("scripted", "[speech-text]"),
                exit_code=1, duration_seconds=0.0, stderr=self.stderr,
                timed_out=self.failure_mode == "timeout",
            ),
        )
        if cancellation is not None and cancellation.cancelled:
            return SynthesisResult(
                request_id=request.request_id,
                provider_id=self.provider_id,
                implementation_id=self._declaration.implementation_id,
                voice_id="",
                succeeded=False,
                detail="cancelled during synthesis",
                outcome=CommandOutcome(
                    executable="scripted", redacted_argv=("scripted",),
                    exit_code=-15, duration_seconds=0.0, cancelled=True,
                ),
            )
        if self.failure_mode == "crash":
            return failed("the scripted provider crashed")
        if self.failure_mode == "timeout":
            return failed("the scripted provider exceeded its time bound")

        target = workspace.file(f"{request.request_id}-scripted")
        write_wav(target, seconds=self.audio_seconds, shape="silent" if self.failure_mode == "empty" else "syllables")
        if self.failure_mode == "empty":
            # A file that exists and holds no frames: the eSpeak NG trap,
            # reproduced so the worker's artifact check is exercised.
            target.write_bytes(b"")
            return failed("the scripted provider produced no audio")
        probe = probe_wav(target)
        return SynthesisResult(
            request_id=request.request_id,
            provider_id=self.provider_id,
            implementation_id=self._declaration.implementation_id,
            voice_id=request.voice_id or self._voices[0].voice_id,
            succeeded=True,
            audio_path=str(target),
            audio_format="wav-pcm-s16le",
            sample_rate=probe.sample_rate,
            channels=probe.channels,
            frame_count=probe.frame_count,
            duration_seconds=probe.duration_seconds,
            synthesis_seconds=0.01,
            detail="synthesised by the scripted provider",
        )

    def stream(
        self,
        request: VoiceRequest,
        *,
        cancellation: CancellationSignal | None = None,
    ) -> StreamOutcome:
        with self._guard:
            self.stream_calls += 1
            if cancellation is not None:
                self._active[request.request_id] = cancellation
        if self.stream_entered is not None:
            self.stream_entered.set()
        if self.stream_gate is not None:
            while not self.stream_gate.wait(0.01):
                if cancellation is not None and cancellation.cancelled:
                    break
        cancelled = bool(cancellation is not None and cancellation.cancelled)
        succeeded = not cancelled and self.failure_mode not in ("crash", "timeout")
        return StreamOutcome(
            request_id=request.request_id,
            provider_id=self.provider_id,
            implementation_id=self._declaration.implementation_id,
            voice_id=request.voice_id,
            succeeded=succeeded,
            cancelled=cancelled,
            elapsed_seconds=0.01,
            detail="streamed by the scripted provider" if succeeded else "the scripted provider failed",
        )

    def cancel(self, request_id: str) -> bool:
        with self._guard:
            signal = self._active.get(request_id)
        self.cancelled.append(request_id)
        return bool(signal is not None and signal.cancel("cancelled"))

    def close(self) -> None:
        self.closed = True


# --------------------------------------------------------------------------- #
# A backend a test can steer
# --------------------------------------------------------------------------- #


class _ScriptedHandle(PlaybackHandle):
    """A playback handle with no child process behind it.

    Subclasses the real handle so the worker drives the real interface, and
    replaces only the parts that would have started a program. ``position`` is
    driven by the same wall clock the real one uses, so the drift arithmetic
    §14 measures is exercised rather than stubbed.
    """

    def __init__(
        self,
        *,
        request_id: str,
        backend_id: str,
        device_id: str,
        audio_seconds: float,
        gate: threading.Event | None,
        entered: threading.Event | None,
        fail: str,
        monotonic: Callable[[], float],
        real_time: bool = False,
    ) -> None:
        self.request_id = request_id
        self.backend_id = backend_id
        self.device_id = device_id
        self.audio_seconds = audio_seconds
        self.requested_latency_ms = 60
        self._now = monotonic
        self._gate = gate
        self._fail = fail
        self._guard = threading.RLock()
        self._paused = False
        self._paused_total = 0.0
        self._paused_at = 0.0
        self._started_at = self._now()
        self._done = threading.Event()
        self._stopped = False
        self.finished = False
        self._real_time = real_time
        if entered is not None:
            entered.set()
        if gate is None:
            self._done.set()

    # -- the parts of the real interface a test exercises ----------------
    @property
    def started(self) -> bool:
        return self._fail != "start"

    @property
    def start_error(self) -> str:
        return "the scripted backend could not start a player" if self._fail == "start" else ""

    @property
    def paused(self) -> bool:
        return self._paused

    def poll(self) -> int | None:
        if self._stopped:
            return -15
        if self._gate is not None and not self._gate.is_set():
            return None
        if self._paused:
            return None
        if self._real_time and (self.elapsed_seconds - self.paused_seconds) < self.audio_seconds:
            # Still playing. Without this a scripted playback completes before
            # the worker's mouth loop turns once, so the only viseme frame that
            # ever exists is the opening one — and a test asserting "the mouth
            # moved" would be asserting something about the fixture.
            return None
        return 1 if self._fail == "exit" else 0

    @property
    def elapsed_seconds(self) -> float:
        return self._now() - self._started_at

    @property
    def paused_seconds(self) -> float:
        with self._guard:
            extra = (self._now() - self._paused_at) if self._paused_at else 0.0
            return self._paused_total + extra

    @property
    def position_seconds(self) -> float:
        elapsed = max(0.0, self.elapsed_seconds - self.paused_seconds)
        return min(elapsed, self.audio_seconds) if self.audio_seconds else elapsed

    def pause(self) -> bool:
        with self._guard:
            if self._paused or self._stopped:
                return False
            self._paused = True
            self._paused_at = self._now()
            return True

    def resume(self) -> bool:
        with self._guard:
            if not self._paused:
                return False
            self._paused_total += self._now() - self._paused_at
            self._paused_at = 0.0
            self._paused = False
            return True

    def stop(self) -> None:
        self._stopped = True
        if self._gate is not None:
            self._gate.set()

    def _finish(self) -> None:
        self.finished = True

    def wait(
        self,
        *,
        cancellation: CancellationSignal | None = None,
        poll_interval: float = 0.02,
        timeout_seconds: float | None = None,
    ) -> PlaybackOutcome:
        cancelled = False
        if self._gate is not None:
            while not self._gate.wait(0.005):
                if cancellation is not None and cancellation.cancelled:
                    cancelled = True
                    break
                if self._stopped:
                    break
        if cancellation is not None and cancellation.cancelled:
            cancelled = True
        self._finish()
        succeeded = not cancelled and self._fail not in ("exit", "start")
        return PlaybackOutcome(
            request_id=self.request_id,
            backend_id=self.backend_id,
            device_id=self.device_id,
            succeeded=succeeded,
            cancelled=cancelled,
            elapsed_seconds=self.elapsed_seconds,
            paused_seconds=self.paused_seconds,
            audio_seconds=self.audio_seconds,
            requested_latency_ms=self.requested_latency_ms,
            detail=(
                "played" if succeeded
                else "cancelled" if cancelled
                else "the scripted player exited non-zero"
            ),
        )


class ScriptedBackend:
    """A real :class:`companion.voice.audio.AudioBackend` a test drives."""

    def __init__(
        self,
        backend_id: str = "scripted",
        *,
        kind: str = "scripted",
        devices: Sequence[str] = ("scripted-sink",),
        reachable: bool = True,
        unsupported: str = "",
        playback_gate: threading.Event | None = None,
        playback_entered: threading.Event | None = None,
        fail: str = "",
        monotonic: Callable[[], float] | None = None,
        real_time: bool = False,
    ) -> None:
        import time as _time

        self.backend_id = backend_id
        self.kind = kind
        self._devices = list(devices)
        self._reachable = reachable
        self.unsupported = unsupported
        self.playback_gate = playback_gate
        self.playback_entered = playback_entered
        self.fail = fail
        #: Hold the playback open for the length of the audio, so the worker's
        #: mouth loop actually turns. Off by default: most tests want playback
        #: to finish at once and would otherwise pay for the wait.
        self.real_time = real_time
        self._now = monotonic or _time.monotonic
        self.closed = False
        self.plays = 0
        self.handles: list[_ScriptedHandle] = []

    def set_devices(self, devices: Sequence[str]) -> None:
        self._devices = list(devices)

    def set_reachable(self, value: bool) -> None:
        self._reachable = value

    def health(self, *, monotonic: float = 0.0, refresh: bool = False) -> BackendHealth:
        return BackendHealth(
            backend_id=self.backend_id,
            kind=self.kind,
            available=not self.closed,
            reachable=self._reachable,
            device_count=len(self._devices) if self._reachable else 0,
            default_device=self._devices[0] if self._devices and self._reachable else "",
            detail="" if self._reachable else "the scripted audio server is not answering",
            checked_at_monotonic=monotonic,
        )

    def record(self, succeeded: bool) -> None:
        return None

    def discover(self) -> Sequence[AudioDevice]:
        if not self._reachable:
            return ()
        return tuple(
            AudioDevice(
                device_id=name, backend_id=self.backend_id, name=name,
                default=index == 0, state="RUNNING",
            )
            for index, name in enumerate(self._devices)
        )

    def default_device(self) -> AudioDevice | None:
        devices = self.discover()
        return devices[0] if devices else None

    def supports(self, probe: AudioProbe) -> tuple[bool, str]:
        if self.unsupported:
            return False, self.unsupported
        return True, ""

    def play(
        self,
        request_id: str,
        path: str,
        *,
        device_id: str = "",
        volume: float = 1.0,
        probe: AudioProbe | None = None,
        latency_ms: int = 0,
    ) -> PlaybackHandle:
        self.plays += 1
        handle = _ScriptedHandle(
            request_id=request_id,
            backend_id=self.backend_id,
            device_id=device_id or (self._devices[0] if self._devices else ""),
            audio_seconds=probe.duration_seconds if probe else 0.3,
            gate=self.playback_gate,
            entered=self.playback_entered,
            fail=self.fail,
            monotonic=self._now,
            real_time=self.real_time,
        )
        self.handles.append(handle)
        return handle

    def close(self) -> None:
        self.closed = True


def ignoring_terminator(seconds: float = 30.0) -> list[str]:
    """An argv for a child that refuses ``SIGTERM``. Real, because it must be.

    §21 asks for "child-process refusal", and it is the one behaviour a fake
    cannot stand in for: the thing under test is whether
    :func:`companion.voice.execution.run` escalates to ``SIGKILL`` and reaps,
    which is a property of the operating system's signal delivery rather than of
    any Python object.
    """
    return [
        sys.executable, "-c",
        "import signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"time.sleep({seconds})\n",
    ]


def sleeping_child(seconds: float = 30.0) -> list[str]:
    return [sys.executable, "-c", f"import time; time.sleep({seconds})"]


def noisy_child(bytes_out: int) -> list[str]:
    """A child that writes far more to stderr than the bound allows."""
    return [
        sys.executable, "-c",
        f"import sys; sys.stderr.write('x' * {bytes_out}); sys.stderr.flush()",
    ]


def echoing_child() -> list[str]:
    """A child that writes whatever it reads on stdin to a file it is told about.

    Used to prove the utterance really travels through stdin rather than through
    an argument — the test reads the file back and compares.
    """
    return [
        sys.executable, "-c",
        "import sys, os\n"
        "data = sys.stdin.read()\n"
        "open(os.environ['ECHO_TARGET'], 'w', encoding='utf-8').write(data)\n",
    ]
