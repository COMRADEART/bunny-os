# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Getting a synthesised file to a speaker, and coping when there is not one.

§9 asks for an audio-output abstraction and is explicit that it should prefer
the facilities Linux already has rather than bundling an audio server. So this
drives the players that ship with the stack — ``paplay``, ``pw-play``,
``aplay`` — through the same allowlisted, argv-only runner every synthesiser
goes through. There is no mixing, no resampling and no device management here:
those belong to the audio server, and a second implementation of them inside a
companion would eventually disagree with the first about which sink is default.

**What the host actually is, measured rather than assumed.** The reference
target is Fedora 44 under WSL, where:

* ``pactl`` reports ``Server Name: pulseaudio``, ``Server String:
  unix:/mnt/wslg/PulseServer``, one sink named ``RDPSink`` from
  ``module-rdp-sink.c`` at 44100 Hz — this is the **WSLg audio bridge**
  presenting a PulseAudio-compatible interface, and ``paplay`` works against it;
* ``pw-play`` fails with ``pw_context_connect() failed: Host is down`` — the
  PipeWire *tools* are installed but no PipeWire daemon is running;
* ``aplay`` fails with ``cannot find card '0'`` — there is no ALSA device.

That matters for what may be claimed. Audio here reaches an RDP sink and is
carried to the Windows host; **no physical speaker was validated**, and §24's
numbers are labelled accordingly. It also happens to be a useful test bed: two
of the three backends genuinely fail, so §10's fallback and degradation paths
are exercised by the machine rather than by a mock.

**Failure is data and never an exception.** Every method here returns an
outcome. A task must not fail because a speaker was unplugged (§8), and the way
to guarantee that is for the audio layer to have no way to make it happen.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
from pathlib import Path
import subprocess
import threading
import time
from typing import Any, Iterable, Mapping, Protocol, Sequence

from .execution import (
    CancellationSignal,
    Child,
    CommandOutcome,
    CommandSpec,
    ExecutableRefused,
    child_environment,
    resolve_executable,
)
from .pcm import AudioProbe, PcmError, probe_wav

__all__ = [
    "AlsaBackend",
    "AudioBackend",
    "AudioDevice",
    "AudioRouter",
    "BackendHealth",
    "DEGRADATION_KINDS",
    "DegradationRecord",
    "PipeWireBackend",
    "PlaybackHandle",
    "PlaybackOutcome",
    "PulseAudioBackend",
    "local_backends",
]

#: Every typed degradation §10 and §12 can produce. A closed set, because a
#: degradation record with a free-text kind is a record nothing can aggregate
#: and a gate cannot assert on.
DEGRADATION_KINDS = (
    "no-audio-device-at-startup",
    "device-removed-before-synthesis",
    "device-removed-during-playback",
    "default-device-changed",
    "playback-backend-crash",
    "audio-server-restart",
    "audio-permission-denied",
    "unsupported-audio-format",
    "provider-unavailable",
    "provider-failure",
    "provider-timeout",
    "no-eligible-provider",
    "resource-pressure",
    "policy-suppressed",
    "voice-disabled",
    "streaming-unavailable",
    "renderer-unavailable",
)

#: How much of an utterance a player must actually have played before its zero
#: exit status is believed. Cancellation and pausing are accounted for
#: separately, so this only fires when a player claimed success having spent far
#: too little time on the audio.
#:
#: Six tenths rather than something tighter: an audio server may legitimately
#: drop the tail of a stream at shutdown, and a floor at 0.95 would turn that
#: into a failure. The case this catches — a player that read the file in
#: completely the wrong format — is off by a factor of four, not a few percent.
PLAYBACK_COMPLETION_FLOOR = 0.6

#: How much stdout a discovery command may produce before it is treated as
#: hostile. ``pw-dump`` on a busy graph is genuinely large; a megabyte is well
#: past anything real and well short of anything that matters.
MAX_DISCOVERY_BYTES = 1024 * 1024


@dataclass(frozen=True)
class AudioDevice:
    """One output the machine can play to."""

    device_id: str
    backend_id: str
    name: str = ""
    description: str = ""
    default: bool = False
    #: The server's own word for the sink's state where it has one —
    #: ``RUNNING``, ``IDLE``, ``SUSPENDED``. Carried verbatim rather than
    #: normalised: a suspended sink is not a broken one, and flattening the
    #: distinction would make §10's "device removed" fire on an idle speaker.
    state: str = ""
    sample_specification: str = ""

    @property
    def healthy(self) -> bool:
        return self.state.upper() not in ("UNLINKED", "ERROR")

    def to_json(self) -> dict[str, Any]:
        return {
            "deviceId": self.device_id,
            "backendId": self.backend_id,
            "name": self.name,
            "description": self.description,
            "default": self.default,
            "state": self.state,
            "sampleSpecification": self.sample_specification,
            "healthy": self.healthy,
        }


@dataclass(frozen=True)
class BackendHealth:
    """Whether one backend can play right now."""

    backend_id: str
    kind: str
    available: bool = False
    #: Distinct from ``available``: the player is installed but cannot reach a
    #: server or a card. ``pw-play`` on the reference target is exactly this,
    #: and conflating the two would report PipeWire as "not installed" to a user
    #: who can see that it is.
    reachable: bool = False
    device_count: int = 0
    default_device: str = ""
    detail: str = ""
    checked_at_monotonic: float = 0.0
    consecutive_failures: int = 0

    @property
    def ready(self) -> bool:
        return self.available and self.reachable and self.device_count > 0

    def to_json(self) -> dict[str, Any]:
        return {
            "backendId": self.backend_id,
            "kind": self.kind,
            "available": self.available,
            "reachable": self.reachable,
            "ready": self.ready,
            "deviceCount": self.device_count,
            "defaultDevice": self.default_device,
            "detail": self.detail,
            "checkedAtMonotonic": self.checked_at_monotonic,
            "consecutiveFailures": self.consecutive_failures,
        }


@dataclass(frozen=True)
class DegradationRecord:
    """One thing that went wrong, in a shape something can count.

    ``captions_retained`` and ``task_affected`` are on every record and are
    always ``True`` and ``False`` respectively in this build. They are not
    decoration: they are the two claims §8 makes, written into every degradation
    so that a gate can assert them across a hundred runs rather than a reviewer
    asserting them across a reading of the code.
    """

    kind: str
    stage: str
    detail: str
    backend_id: str = ""
    provider_id: str = ""
    request_id: str = ""
    fallback: str = ""
    captions_retained: bool = True
    task_affected: bool = False
    at_monotonic: float = 0.0

    def __post_init__(self) -> None:
        if self.kind not in DEGRADATION_KINDS:
            raise ValueError(f"unknown degradation kind: {self.kind!r}")
        if self.task_affected:
            # There is no code path that sets this and there must not be. A
            # voice degradation that changed a task would be §1's boundary
            # broken, and the type refuses to represent it.
            raise ValueError(
                "a voice degradation may not affect a task; the voice runtime is a "
                "presentation subsystem and cannot change task authority"
            )

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "stage": self.stage,
            "detail": self.detail,
            "backendId": self.backend_id,
            "providerId": self.provider_id,
            "requestId": self.request_id,
            "fallback": self.fallback,
            "captionsRetained": self.captions_retained,
            "taskAffected": self.task_affected,
            "atMonotonic": self.at_monotonic,
        }


@dataclass(frozen=True)
class PlaybackOutcome:
    """What one playback did."""

    request_id: str
    backend_id: str
    device_id: str
    succeeded: bool
    cancelled: bool = False
    #: Seconds of wall-clock the player ran, *including* any time it was paused.
    elapsed_seconds: float = 0.0
    paused_seconds: float = 0.0
    audio_seconds: float = 0.0
    #: The latency the backend was asked for, where it accepts one. Not a
    #: measurement of what the server delivered — that is not observable from a
    #: one-shot player, and reporting a request as a measurement would put a
    #: number into §24 that nothing measured.
    requested_latency_ms: int = 0
    #: True when the player exited zero having spent far too little time on the
    #: audio. Kept as its own field rather than folded into ``detail`` so a gate
    #: can count it.
    truncated: bool = False
    detail: str = ""
    outcome: CommandOutcome | None = None

    @property
    def effective_audio_seconds(self) -> float:
        return max(0.0, self.elapsed_seconds - self.paused_seconds)

    def to_json(self) -> dict[str, Any]:
        return {
            "requestId": self.request_id,
            "backendId": self.backend_id,
            "deviceId": self.device_id,
            "succeeded": self.succeeded,
            "cancelled": self.cancelled,
            "elapsedSeconds": round(self.elapsed_seconds, 6),
            "pausedSeconds": round(self.paused_seconds, 6),
            "audioSeconds": round(self.audio_seconds, 6),
            "requestedLatencyMs": self.requested_latency_ms,
            "truncated": self.truncated,
            "detail": self.detail,
            "command": self.outcome.to_json() if self.outcome is not None else None,
        }


# --------------------------------------------------------------------------- #
# Playback
# --------------------------------------------------------------------------- #


class PlaybackHandle:
    """One running playback, controllable while it runs.

    Wraps :class:`companion.voice.execution.Child` rather than a ``Popen``, so
    the escalation, the process-group signalling and the reaping are the ones
    the rest of the package already uses. Pause and resume are ``SIGSTOP`` and
    ``SIGCONT`` on the group: every player in the allowlist is a one-shot
    process with no control channel, so the kernel's own stop is the only
    mechanism all three share.

    ``paused_seconds`` is accumulated rather than derived at the end, because
    §14 needs the *audio* position to reconcile viseme timing and a pause moves
    wall time without moving the audio.
    """

    def __init__(
        self,
        *,
        request_id: str,
        backend_id: str,
        device_id: str,
        spec: CommandSpec,
        audio_seconds: float = 0.0,
        requested_latency_ms: int = 0,
        monotonic: Any = None,
    ) -> None:
        self.request_id = request_id
        self.backend_id = backend_id
        self.device_id = device_id
        self.audio_seconds = audio_seconds
        self.requested_latency_ms = requested_latency_ms
        self._now = monotonic or time.monotonic
        self._spec = spec
        self._guard = threading.RLock()
        self._paused_total = 0.0
        self._paused_at = 0.0
        self._finished = False
        self._started_at = self._now()
        self._child = Child(spec)
        self._start_error = self._child.start_error

    @property
    def started(self) -> bool:
        return self._child.started

    @property
    def start_error(self) -> str:
        return self._start_error

    @property
    def paused(self) -> bool:
        return self._child.paused

    def poll(self) -> int | None:
        return self._child.poll()

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
        """Where in the utterance the audio is, as well as this can be known.

        Wall time minus paused time, clamped to the audio's own length. An
        estimate, and named ``position`` rather than ``audio_clock`` for that
        reason: a one-shot player exposes no clock, and the honest thing is a
        bounded estimate that §14 then *measures the drift of* rather than a
        fabricated precise number.
        """
        elapsed = max(0.0, self.elapsed_seconds - self.paused_seconds)
        return min(elapsed, self.audio_seconds) if self.audio_seconds else elapsed

    def pause(self) -> bool:
        with self._guard:
            if self._finished or not self._child.pause():
                return False
            self._paused_at = self._now()
            return True

    def resume(self) -> bool:
        with self._guard:
            if self._finished or not self._child.resume():
                return False
            if self._paused_at:
                self._paused_total += self._now() - self._paused_at
                self._paused_at = 0.0
            return True

    def stop(self) -> None:
        """Terminate now. Safe while paused, and safe after completion."""
        self._child.terminate(
            grace_seconds=self._spec.grace_seconds,
            kill_grace_seconds=self._spec.kill_grace_seconds,
        )

    def wait(
        self,
        *,
        cancellation: CancellationSignal | None = None,
        poll_interval: float = 0.02,
        timeout_seconds: float | None = None,
    ) -> PlaybackOutcome:
        """Block until it finishes, is cancelled, or runs out of time.

        Paused time does not count against the timeout: a user who paused
        speech and went to make tea should not come back to a player that was
        killed for taking too long.
        """
        if not self._child.started:
            self._finish()
            return PlaybackOutcome(
                request_id=self.request_id,
                backend_id=self.backend_id,
                device_id=self.device_id,
                succeeded=False,
                detail=f"the audio player could not be started: {self._start_error}",
                outcome=self._child.outcome(duration_seconds=self.elapsed_seconds),
                audio_seconds=self.audio_seconds,
                requested_latency_ms=self.requested_latency_ms,
            )
        limit = timeout_seconds if timeout_seconds is not None else self._spec.timeout_seconds
        cancelled = False
        timed_out = False
        try:
            while True:
                if self._child.poll() is not None:
                    break
                if cancellation is not None and cancellation.cancelled:
                    cancelled = True
                    break
                if limit and (self.elapsed_seconds - self.paused_seconds) >= limit:
                    timed_out = True
                    break
                if cancellation is not None:
                    cancellation.wait(poll_interval)
                else:
                    time.sleep(poll_interval)
            if cancelled or timed_out:
                self.stop()
        finally:
            self._finish()

        outcome = self._child.outcome(
            duration_seconds=self.elapsed_seconds, timed_out=timed_out, cancelled=cancelled
        )
        succeeded = outcome.exit_code == 0 and not cancelled and not timed_out
        truncated = ""
        if succeeded and self.audio_seconds:
            # A player that exited zero having played the wrong thing is not a
            # success, and exit status alone cannot tell the difference. Every
            # player in the allowlist blocks for the duration of the audio, so
            # finishing far too early means it did not play what it was given.
            #
            # This is here because it happened: /usr/bin/paplay is a symlink to
            # pacat, a multi-call binary that reads raw PCM under its own name
            # and a sound file under paplay's. Resolving the symlink made the
            # runtime exec pacat, which played a WAV header and mono samples as
            # stereo raw data — 0.73 s of noise where 2.80 s of speech belonged,
            # exit code 0. Nothing downstream could tell, and no test that only
            # checked "did it succeed" ever would.
            played = self.elapsed_seconds - self.paused_seconds
            if played < self.audio_seconds * PLAYBACK_COMPLETION_FLOOR:
                succeeded = False
                truncated = (
                    f"the player exited successfully after {played:.2f}s of "
                    f"{self.audio_seconds:.2f}s of audio; it did not play what it was given"
                )
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
            truncated=bool(truncated),
            detail=(
                "played" if succeeded
                else truncated or outcome.stderr or (
                    "cancelled" if cancelled else
                    "the player exceeded its time bound" if timed_out else
                    f"the player exited {outcome.exit_code}"
                )
            ),
            outcome=outcome,
        )

    def _finish(self) -> None:
        with self._guard:
            if self._paused_at:
                self._paused_total += self._now() - self._paused_at
                self._paused_at = 0.0
            self._finished = True
        self._child.finish()


# --------------------------------------------------------------------------- #
# Backends
# --------------------------------------------------------------------------- #


class AudioBackend(Protocol):
    """What the worker may ask of an audio backend, and nothing wider.

    No method takes a device *path*, a command or a server address. A backend
    plays a file this runtime synthesised to a device this runtime discovered,
    and §17's protocol exposes no operation that could widen that.
    """

    backend_id: str
    kind: str

    def health(self, *, monotonic: float = 0.0, refresh: bool = False) -> BackendHealth: ...
    def discover(self) -> Sequence[AudioDevice]: ...
    def default_device(self) -> AudioDevice | None: ...
    def supports(self, probe: AudioProbe) -> tuple[bool, str]: ...
    def play(
        self,
        request_id: str,
        path: str,
        *,
        device_id: str = "",
        volume: float = 1.0,
        probe: AudioProbe | None = None,
        latency_ms: int = 0,
    ) -> PlaybackHandle: ...
    def close(self) -> None: ...


class _CommandBackend:
    """Common ground for a backend that shells out to a one-shot player."""

    backend_id = ""
    kind = ""
    player = ""
    inspector = ""

    #: A player asked for a latency it cannot honour is not an error, so this is
    #: a request rather than a contract. 60 ms is short enough that speech feels
    #: responsive and long enough that a busy machine does not underrun.
    DEFAULT_LATENCY_MS = 60

    def __init__(self, *, resolver=None) -> None:
        self._resolve = resolver or resolve_executable
        self._player_path = ""
        self._inspector_path = ""
        self._resolution_error = ""
        self._trusted = True
        self._resolve_once()
        self._health: BackendHealth | None = None
        self._failures = 0
        self._devices: tuple[AudioDevice, ...] = ()
        self._closed = False
        #: A diagnostic switch, off by default and never set by the runtime.
        #: §23 step 19 asks the slice to "remove the audio device or simulate
        #: backend loss", and on a machine whose speaker cannot be unplugged by
        #: a script this is how the loss is produced. Everything downstream of
        #: it is real: the router's selection, the typed degradation record, the
        #: policy's descent and the hysteresis on the way back.
        #:
        #: Deliberately *not* a way to fake a working backend. It can only make
        #: a backend look worse than it is, so no measurement can be flattered
        #: by it.
        self._simulated_loss = False
        self._guard = threading.RLock()

    def _resolve_once(self) -> None:
        problems: list[str] = []
        for attribute, name in (("_player_path", self.player), ("_inspector_path", self.inspector)):
            if not name:
                continue
            try:
                path, trusted = self._resolve(name)
            except ExecutableRefused as exc:
                problems.append(str(exc))
                continue
            setattr(self, attribute, path)
            self._trusted = self._trusted and trusted
        self._resolution_error = "; ".join(problems)

    # ----------------------------------------------------------------- #

    def _capture(self, argv: Sequence[str], *, timeout: float = 10.0) -> tuple[int, str, str]:
        """Run a discovery command and read its stdout, bounded.

        The package's own runner discards stdout by design; discovery is the one
        place it is the answer, so it is captured here with the same environment
        and the same no-shell rule.
        """
        try:
            completed = subprocess.run(  # noqa: S603 - argv list, never a shell
                list(argv),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                env=child_environment(),
                timeout=timeout,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            return 124, "", "the audio server did not answer within the time bound"
        except OSError as exc:
            return 127, "", f"{exc.strerror or exc}"
        out = completed.stdout[:MAX_DISCOVERY_BYTES].decode("utf-8", errors="replace")
        err = completed.stderr[:4096].decode("utf-8", errors="replace").strip()
        return completed.returncode, out, err

    def discover(self) -> Sequence[AudioDevice]:
        raise NotImplementedError

    def default_device(self) -> AudioDevice | None:
        for device in self.discover():
            if device.default:
                return device
        devices = self.discover()
        return devices[0] if devices else None

    def health(self, *, monotonic: float = 0.0, refresh: bool = False) -> BackendHealth:
        with self._guard:
            cached = self._health
            if cached is not None and not refresh and monotonic - cached.checked_at_monotonic < 5.0:
                return replace(cached, consecutive_failures=self._failures)
        if refresh:
            with self._guard:
                self._player_path = ""
                self._inspector_path = ""
                self._resolve_once()
        available = bool(self._player_path) and not self._closed
        devices: Sequence[AudioDevice] = ()
        detail = self._resolution_error if not available else ""
        reachable = False
        if self._simulated_loss:
            return self._remember(BackendHealth(
                backend_id=self.backend_id,
                kind=self.kind,
                available=available,
                reachable=False,
                device_count=0,
                detail="a simulated backend loss is in effect for this diagnostic run",
                checked_at_monotonic=monotonic,
                consecutive_failures=self._failures,
            ), ())
        if available:
            try:
                devices = self.discover()
                reachable = True
            except _Unreachable as exc:
                detail = str(exc)
        default = next((item.device_id for item in devices if item.default), "")
        health = BackendHealth(
            backend_id=self.backend_id,
            kind=self.kind,
            available=available,
            reachable=reachable,
            device_count=len(devices),
            default_device=default or (devices[0].device_id if devices else ""),
            detail=detail or (f"{self._failures} consecutive failures" if self._failures else ""),
            checked_at_monotonic=monotonic,
            consecutive_failures=self._failures,
        )
        return self._remember(health, devices)

    def _remember(self, health: BackendHealth, devices: Sequence[AudioDevice]) -> BackendHealth:
        with self._guard:
            self._health = health
            self._devices = tuple(devices)
        return health

    def set_reachable(self, value: bool) -> None:
        """Diagnostic only: make this backend report itself unreachable.

        Named to match :class:`ScriptedBackend`'s own method so the vertical
        slice takes one path whether it is running against a fake or against
        ``paplay``. Clears the cached health so the next reading is the new one
        rather than a five-second-old answer.
        """
        with self._guard:
            self._simulated_loss = not value
            self._health = None

    def record(self, succeeded: bool) -> None:
        with self._guard:
            self._failures = 0 if succeeded else self._failures + 1

    def supports(self, probe: AudioProbe) -> tuple[bool, str]:
        """Whether this player can take this file as it stands.

        All three players read RIFF WAV and let the server convert, so this is
        permissive on purpose. It exists as a real check rather than a stub
        because §21 tests a format mismatch, and the check that fails there is a
        sample width the parser refuses — which is caught before a player is
        started rather than by reading a player's stderr afterwards.
        """
        if probe.sample_width not in (1, 2):
            return False, f"{probe.sample_width * 8}-bit audio is not supported by {self.backend_id}"
        if probe.channels > 2:
            return False, f"{probe.channels} channels exceed what {self.backend_id} will play"
        return True, ""

    def _play_spec(
        self, path: str, *, device_id: str, volume: float, latency_ms: int, seconds: float
    ) -> CommandSpec:
        raise NotImplementedError

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
        seconds = probe.duration_seconds if probe is not None else 0.0
        latency = latency_ms or self.DEFAULT_LATENCY_MS
        spec = self._play_spec(
            path, device_id=device_id, volume=volume, latency_ms=latency, seconds=seconds
        )
        return PlaybackHandle(
            request_id=request_id,
            backend_id=self.backend_id,
            device_id=device_id or (self._devices[0].device_id if self._devices else ""),
            spec=spec,
            audio_seconds=seconds,
            requested_latency_ms=latency,
        )

    def close(self) -> None:
        with self._guard:
            self._closed = True

    @property
    def trusted_resolution(self) -> bool:
        return self._trusted


class _Unreachable(RuntimeError):
    """The player is installed and the server is not answering."""


def _playback_timeout(seconds: float) -> float:
    """Twice the audio plus a margin, floored.

    A player that hangs on a wedged server must be bounded, and the bound has to
    scale with the utterance or a long caption would be cut off. Twice is
    generous enough to survive a slow start and tight enough that a hang is
    noticed while the user still remembers asking.
    """
    return max(10.0, min(600.0, seconds * 2.0 + 10.0))


class PulseAudioBackend(_CommandBackend):
    """``paplay`` against a PulseAudio-compatible server.

    On the reference target that server is the **WSLg audio bridge**, not
    PulseAudio proper and not PipeWire's compatibility layer: ``pactl`` reports
    ``Server String: unix:/mnt/wslg/PulseServer`` and a single ``RDPSink``.
    ``kind`` says ``pulse-compatible`` rather than ``pulseaudio`` for that
    reason — what is on the other end of the socket is not knowable from here,
    and a label that claimed to know would be wrong on three of the four hosts
    this could run on.
    """

    backend_id = "pulse"
    kind = "pulse-compatible"
    player = "paplay"
    inspector = "pactl"

    def discover(self) -> Sequence[AudioDevice]:
        if not self._inspector_path:
            # No ``pactl``: the player may still work against the default sink,
            # so this reports one unnamed device rather than none. Reporting
            # zero would make the backend un-ready and skip a path that works.
            return (AudioDevice(
                device_id="", backend_id=self.backend_id, name="default",
                description="the server's default sink; pactl is not installed to enumerate",
                default=True,
            ),)
        code, out, err = self._capture([self._inspector_path, "list", "short", "sinks"])
        if code != 0:
            raise _Unreachable(err or f"pactl exited {code}; no PulseAudio-compatible server answered")
        default_code, default_out, _ = self._capture([self._inspector_path, "get-default-sink"])
        default_name = default_out.strip() if default_code == 0 else ""
        devices: list[AudioDevice] = []
        for line in out.splitlines():
            fields = line.split("\t")
            if len(fields) < 2:
                continue
            name = fields[1].strip()
            if not name:
                continue
            devices.append(AudioDevice(
                device_id=name,
                backend_id=self.backend_id,
                name=name,
                description=fields[2].strip() if len(fields) > 2 else "",
                default=name == default_name,
                state=fields[4].strip() if len(fields) > 4 else "",
                sample_specification=fields[3].strip() if len(fields) > 3 else "",
            ))
            if len(devices) >= 64:
                break
        return tuple(devices)

    def _play_spec(
        self, path: str, *, device_id: str, volume: float, latency_ms: int, seconds: float
    ) -> CommandSpec:
        arguments: list[str] = []
        if device_id:
            arguments += [f"--device={device_id}"]
        # PulseAudio volume is 0..65536 with 65536 as 100%. Clamped rather than
        # extended: this runtime never amplifies past unity, because a companion
        # that could be made louder than the system volume is a companion that
        # can be made to shout.
        arguments += [f"--volume={int(max(0.0, min(1.0, volume)) * 65536)}"]
        arguments += [f"--latency-msec={max(1, latency_ms)}"]
        arguments += ["--client-name=bunny-companion"]
        arguments += ["--", path]
        return CommandSpec(
            executable=self._player_path,
            arguments=tuple(arguments),
            touches_audio=True,
            timeout_seconds=_playback_timeout(seconds),
        )


class PipeWireBackend(_CommandBackend):
    """``pw-play`` against a PipeWire daemon.

    Present and non-functional on the reference target: ``pw-play`` exits
    non-zero with ``pw_context_connect() failed: Host is down`` because the
    tools are installed and no daemon runs. That is exactly the state §10 calls
    "playback backend crash" from the caller's side, and it is why this backend
    is in the list rather than omitted — the fallback to ``pulse`` is exercised
    by the real machine.
    """

    backend_id = "pipewire"
    kind = "pipewire"
    player = "pw-play"
    inspector = "pw-dump"

    def discover(self) -> Sequence[AudioDevice]:
        if not self._inspector_path:
            raise _Unreachable("pw-dump is not installed, so PipeWire sinks cannot be enumerated")
        code, out, err = self._capture([self._inspector_path])
        if code != 0:
            raise _Unreachable(err or f"pw-dump exited {code}; no PipeWire daemon answered")
        try:
            graph = json.loads(out or "[]")
        except json.JSONDecodeError as exc:
            raise _Unreachable(f"pw-dump produced output this cannot read: {exc}") from exc
        if not isinstance(graph, list):
            raise _Unreachable("pw-dump did not produce a graph")
        devices: list[AudioDevice] = []
        for node in graph:
            if not isinstance(node, Mapping):
                continue
            info = node.get("info")
            props = info.get("props") if isinstance(info, Mapping) else None
            if not isinstance(props, Mapping):
                continue
            if props.get("media.class") != "Audio/Sink":
                continue
            name = str(props.get("node.name", "")).strip()
            if not name:
                continue
            devices.append(AudioDevice(
                device_id=name,
                backend_id=self.backend_id,
                name=name,
                description=str(props.get("node.description", "")),
                default=bool(props.get("node.default", False)),
                state=str(info.get("state", "")) if isinstance(info, Mapping) else "",
            ))
            if len(devices) >= 64:
                break
        if not devices:
            raise _Unreachable("the PipeWire graph contains no audio sink")
        return tuple(devices)

    def _play_spec(
        self, path: str, *, device_id: str, volume: float, latency_ms: int, seconds: float
    ) -> CommandSpec:
        arguments: list[str] = []
        if device_id:
            arguments += [f"--target={device_id}"]
        arguments += [f"--volume={max(0.0, min(1.0, volume)):.3f}"]
        arguments += [f"--latency={max(1, latency_ms)}ms"]
        arguments += ["--", path]
        return CommandSpec(
            executable=self._player_path,
            arguments=tuple(arguments),
            touches_audio=True,
            timeout_seconds=_playback_timeout(seconds),
        )


class AlsaBackend(_CommandBackend):
    """``aplay`` straight at a card.

    The floor of the ladder: no server, no mixing, and exclusive access to the
    device while it plays. On the reference target it fails with ``cannot find
    card '0'`` because WSL presents no ALSA card at all — a real instance of
    §10's "no audio device at startup", produced by the machine.

    No volume control: ``aplay`` has none, and this reports the fact through
    the outcome rather than silently ignoring the request.
    """

    backend_id = "alsa"
    kind = "alsa"
    player = "aplay"
    inspector = "aplay"

    def discover(self) -> Sequence[AudioDevice]:
        if not self._player_path:
            raise _Unreachable("aplay is not installed")
        code, out, err = self._capture([self._player_path, "-l"])
        if code != 0 or "no soundcards" in (err or "").lower():
            raise _Unreachable(err.splitlines()[0] if err else f"aplay exited {code}; no ALSA card")
        devices: list[AudioDevice] = []
        for line in out.splitlines():
            if not line.startswith("card "):
                continue
            # ``card 0: PCH [HDA Intel PCH], device 0: ALC295 Analog [...]``
            try:
                card = line.split(":", 1)[0].split()[1]
                device = line.split("device", 1)[1].split(":", 1)[0].strip()
            except (IndexError, ValueError):
                continue
            identifier = f"hw:{card},{device}"
            devices.append(AudioDevice(
                device_id=identifier,
                backend_id=self.backend_id,
                name=identifier,
                description=line.strip(),
                default=not devices,
            ))
            if len(devices) >= 32:
                break
        if not devices:
            raise _Unreachable("aplay reported no playback device")
        return tuple(devices)

    def supports(self, probe: AudioProbe) -> tuple[bool, str]:
        ok, reason = super().supports(probe)
        if not ok:
            return ok, reason
        return True, ""

    def _play_spec(
        self, path: str, *, device_id: str, volume: float, latency_ms: int, seconds: float
    ) -> CommandSpec:
        del volume, latency_ms  # aplay has neither
        arguments: list[str] = ["-q"]
        if device_id:
            arguments += ["-D", device_id]
        arguments += ["--", path]
        return CommandSpec(
            executable=self._player_path,
            arguments=tuple(arguments),
            touches_audio=True,
            timeout_seconds=_playback_timeout(seconds),
        )


def local_backends(*, resolver=None) -> list[AudioBackend]:
    """Every backend, in the order §12's ladder descends.

    PipeWire first because it is the modern default and, where it is running, it
    is the server the rest of the desktop is using. Pulse-compatible second
    because it is what almost every host presents *some* way of reaching —
    including, on the reference target, the WSLg bridge. ALSA last because it
    takes the device exclusively, which is correct only when nothing else can.
    """
    return [
        PipeWireBackend(resolver=resolver),
        PulseAudioBackend(resolver=resolver),
        AlsaBackend(resolver=resolver),
    ]


# --------------------------------------------------------------------------- #
# Routing, loss and hysteresis
# --------------------------------------------------------------------------- #


@dataclass
class _BackendState:
    """What the router remembers about one backend between utterances."""

    failures: int = 0
    #: Monotonic time before which this backend will not be tried again. The
    #: whole of §10's "avoid rapid retry loops": a backend that just failed is
    #: not asked again on the next utterance a tenth of a second later.
    blocked_until: float = 0.0
    #: Consecutive healthy observations since the last failure. §12's recovery
    #: hysteresis: a backend is not restored on the first good answer, because a
    #: server that is restarting answers once and then goes away again.
    healthy_streak: int = 0
    last_devices: tuple[str, ...] = ()


class AudioRouter:
    """Chooses a backend, notices when it stops working, and recovers carefully.

    Three behaviours §10 and §12 ask for, and each is a decision this class
    makes rather than a property of any backend:

    **Fall back once, then captions.** A failed backend is excluded for the rest
    of the utterance. If the next one also fails, the answer is captions — not a
    third attempt, because at that point the machine is telling us something and
    trying harder is how a companion turns a quiet speaker into a spinning CPU.

    **Do not retry rapidly.** A backend that fails is blocked for
    :data:`BACKOFF_SECONDS`, doubling to :data:`MAX_BACKOFF_SECONDS`. The clock
    is monotonic, so a wall-clock correction cannot shorten it.

    **Restore with hysteresis.** Coming back requires
    :data:`RESTORE_OBSERVATIONS` consecutive healthy discoveries. An audio
    server that is restarting answers once mid-restart; a backend restored on
    that one answer fails again immediately, and the pair oscillates.
    """

    BACKOFF_SECONDS = 2.0
    MAX_BACKOFF_SECONDS = 60.0
    RESTORE_OBSERVATIONS = 2

    def __init__(
        self,
        backends: Iterable[AudioBackend] | None = None,
        *,
        monotonic: Any = None,
        resolver=None,
    ) -> None:
        self.backends: list[AudioBackend] = list(
            backends if backends is not None else local_backends(resolver=resolver)
        )
        self._now = monotonic or time.monotonic
        self._state: dict[str, _BackendState] = {
            backend.backend_id: _BackendState() for backend in self.backends
        }
        self._degradations: list[DegradationRecord] = []
        self._guard = threading.RLock()
        self._preferred_device = ""

    # ----------------------------------------------------------------- #

    @property
    def degradations(self) -> tuple[DegradationRecord, ...]:
        with self._guard:
            return tuple(self._degradations)

    def record(self, record: DegradationRecord) -> DegradationRecord:
        with self._guard:
            self._degradations.append(record)
            # Bounded. A service that ran for a week with a broken speaker would
            # otherwise accumulate one record per utterance forever.
            if len(self._degradations) > 256:
                del self._degradations[:-256]
        return record

    def prefer_device(self, device_id: str) -> None:
        """Pin playback to a device the user chose. ``""`` restores the default."""
        with self._guard:
            self._preferred_device = device_id

    @property
    def preferred_device(self) -> str:
        with self._guard:
            return self._preferred_device

    # ----------------------------------------------------------------- #

    def observe(self) -> list[BackendHealth]:
        """Take a health reading of every backend and update the hysteresis.

        Called by the worker between utterances rather than during one: probing
        the audio server in the middle of playback would add a subprocess to the
        path §24 measures the latency of.
        """
        now = self._now()
        report: list[BackendHealth] = []
        for backend in self.backends:
            health = backend.health(monotonic=now)
            state = self._state.setdefault(backend.backend_id, _BackendState())
            if health.ready:
                state.healthy_streak += 1
                if state.healthy_streak >= self.RESTORE_OBSERVATIONS and state.blocked_until:
                    state.blocked_until = 0.0
                    state.failures = 0
                    self.record(DegradationRecord(
                        kind="audio-server-restart",
                        stage="observation",
                        backend_id=backend.backend_id,
                        detail=(
                            f"{backend.backend_id} answered {state.healthy_streak} consecutive "
                            "health checks and was restored"
                        ),
                        at_monotonic=now,
                    ))
                names = tuple(item.device_id for item in backend.discover()) if health.ready else ()
                if state.last_devices and names and names != state.last_devices:
                    self.record(DegradationRecord(
                        kind="default-device-changed",
                        stage="observation",
                        backend_id=backend.backend_id,
                        detail=(
                            f"the device list changed from {len(state.last_devices)} to "
                            f"{len(names)} outputs"
                        ),
                        at_monotonic=now,
                    ))
                state.last_devices = names
            else:
                state.healthy_streak = 0
            report.append(health)
        return report

    def _blocked(self, backend_id: str) -> bool:
        state = self._state.get(backend_id)
        return bool(state and state.blocked_until and self._now() < state.blocked_until)

    def penalise(self, backend_id: str, *, detail: str, kind: str, request_id: str = "") -> DegradationRecord:
        """Mark a backend as failed and block it for a growing interval."""
        now = self._now()
        state = self._state.setdefault(backend_id, _BackendState())
        state.failures += 1
        state.healthy_streak = 0
        state.blocked_until = now + min(
            self.MAX_BACKOFF_SECONDS, self.BACKOFF_SECONDS * (2 ** (state.failures - 1))
        )
        for backend in self.backends:
            if backend.backend_id == backend_id:
                backend.record(False)
        return self.record(DegradationRecord(
            kind=kind,
            stage="playback",
            backend_id=backend_id,
            request_id=request_id,
            detail=detail,
            at_monotonic=now,
        ))

    def succeed(self, backend_id: str) -> None:
        state = self._state.setdefault(backend_id, _BackendState())
        state.failures = 0
        state.blocked_until = 0.0
        state.healthy_streak += 1
        for backend in self.backends:
            if backend.backend_id == backend_id:
                backend.record(True)

    def select(
        self, *, exclude: Iterable[str] = (), probe: AudioProbe | None = None
    ) -> tuple[AudioBackend | None, AudioDevice | None, tuple[str, ...]]:
        """The first backend that is ready, not excluded and not backing off."""
        skipped = set(exclude)
        reasons: list[str] = []
        now = self._now()
        for backend in self.backends:
            name = backend.backend_id
            if name in skipped:
                reasons.append(f"{name}: excluded after failing on this utterance")
                continue
            if self._blocked(name):
                remaining = self._state[name].blocked_until - now
                reasons.append(f"{name}: backing off for another {remaining:.1f}s")
                continue
            health = backend.health(monotonic=now)
            if not health.ready:
                reasons.append(f"{name}: {health.detail or 'not ready'}")
                continue
            if probe is not None:
                ok, why = backend.supports(probe)
                if not ok:
                    reasons.append(f"{name}: {why}")
                    continue
            devices = list(backend.discover())
            device = None
            preferred = self.preferred_device
            if preferred:
                device = next((item for item in devices if item.device_id == preferred), None)
                if device is None:
                    # The user's chosen output is gone. Fall through to the
                    # default rather than refusing to speak: §10's answer to a
                    # removed device is to keep speaking where possible.
                    self.record(DegradationRecord(
                        kind="device-removed-before-synthesis",
                        stage="selection",
                        backend_id=name,
                        detail=f"the selected output {preferred!r} is no longer present",
                        at_monotonic=now,
                    ))
            if device is None:
                device = next((item for item in devices if item.default), devices[0] if devices else None)
            if device is None:
                reasons.append(f"{name}: reports no output device")
                continue
            return backend, device, tuple(reasons)
        return None, None, tuple(reasons)

    def describe(self) -> dict[str, Any]:
        now = self._now()
        return {
            "backends": [backend.health(monotonic=now).to_json() for backend in self.backends],
            "preferredDevice": self.preferred_device,
            "physicalSpeakerValidated": False,
            "degradations": [item.to_json() for item in self.degradations[-32:]],
        }

    def close(self) -> None:
        for backend in self.backends:
            try:
                backend.close()
            except Exception:  # noqa: BLE001 - closing must not stop at the first failure
                continue


def inspect_audio(path: str) -> tuple[AudioProbe | None, str]:
    """Probe a file, returning the reason rather than raising.

    Used at the seam between synthesis and playback, where a raise would have to
    be caught by something whose job is to keep a task alive.
    """
    try:
        return probe_wav(path), ""
    except PcmError as exc:
        return None, str(exc)
