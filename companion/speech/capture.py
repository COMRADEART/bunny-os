# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Getting microphone frames from a real device, and coping when there is not one.

§6 asks for a capture abstraction over the facilities Linux already has, so this
drives the recorders that ship with the stack — ``parec``, ``pw-record``,
``arecord`` — through the same allowlisted, argv-only runner as everything else.
There is no mixing, no resampling and no device management here: those belong to
the audio server, and a second implementation inside a companion would
eventually disagree with the first about which source is default.

**What the host actually is, measured rather than assumed.** The reference
target is Fedora 44 under WSL, where ``pactl`` reaches the **WSLg audio bridge**
(``unix:/mnt/wslg/PulseServer``) and reports an ``RDPSource`` from
``module-rdp-source.c`` — microphone audio carried from the Windows host over
RDP. ``pw-record`` fails because no PipeWire daemon runs, and ``arecord`` fails
because there is no ALSA card. Labels here say ``pulse-compatible`` and the
report says **WSLg bridge**, because §6 requires virtualised audio to be named
as what it is; no physical microphone was validated by this build.

**Failure is data and never an exception.** A capture that cannot start, a
device that vanishes mid-utterance, a server that stops answering — each comes
back as an outcome or a health reading, because §17's whole shape is "stop,
close, clear, degrade to typing", and none of those steps can run inside an
unhandled exception.

**The buffer is bounded and the bound is enforced where the bytes arrive.**
:class:`BoundedFrameBuffer` is the only place captured audio waits in memory.
When the consumer lags, arriving frames are dropped and *counted* — §7's input
overrun, reported rather than absorbed — and the capture's total byte ceiling
is enforced here too, so no path exists on which memory grows with the length
of a held button.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace
import json
from pathlib import PurePosixPath
import subprocess
import threading
import time
from typing import Any, Iterable, Mapping, Protocol, Sequence

from ..pipewire import DEFAULT_SOURCE_KEYS, default_node_name
from ..voice.execution import CommandSpec, ExecutableRefused, child_environment
from .execution import CaptureChild, resolve_capture_executable
from .request import SpeechInputRequest

__all__ = [
    "AlsaCaptureBackend",
    "BoundedFrameBuffer",
    "CAPTURE_DEGRADATION_KINDS",
    "CaptureBackend",
    "CaptureBackendHealth",
    "CaptureDegradation",
    "CaptureDevice",
    "CaptureHandle",
    "CaptureRouter",
    "PipeWireCaptureBackend",
    "PulseAudioCaptureBackend",
    "RecorderContract",
    "local_capture_backends",
]

#: Every typed degradation this subsystem can produce. Closed, because a record
#: with a free-text kind is a record nothing can aggregate and a gate cannot
#: assert on.
CAPTURE_DEGRADATION_KINDS = (
    "no-capture-device-at-startup",
    "device-removed-before-capture",
    "device-removed-during-capture",
    "default-device-changed",
    "capture-backend-crash",
    "audio-server-restart",
    "capture-permission-denied",
    "unsupported-capture-format",
    "input-overrun",
    "recognizer-unavailable",
    "recognizer-failure",
    "no-eligible-recognizer",
    "partial-transcripts-suppressed",
    "resource-pressure",
    "policy-suppressed",
    "speech-input-disabled",
    "indicator-unavailable",
    "renderer-unavailable",
)

#: How much stdout a discovery command may produce before it is hostile.
MAX_DISCOVERY_BYTES = 1024 * 1024

#: How much captured audio may wait in memory between the reader thread and the
#: worker. Ten seconds at 16 kHz mono; a consumer further behind than this is
#: not consuming, and the honest response is a counted overrun rather than a
#: larger buffer.
DEFAULT_BUFFER_BYTES = 10 * 16_000 * 2


def _argument_present(required: str, arguments: Sequence[str]) -> bool:
    """Whether a declared argument is in an argv, exactly as declared.

    A trailing ``=`` matches by prefix ("this option, whatever its value");
    anything else must match exactly — the same rule, with the same reasoning,
    as :func:`companion.voice.audio._argument_present`.
    """
    if required.endswith("="):
        return any(item.startswith(required) for item in arguments)
    return required in tuple(arguments)


@dataclass(frozen=True)
class RecorderContract:
    """What a recorder *is*, as distinct from the file it happens to resolve to.

    ``parec`` is the measured hazard, inherited from playback: ``/usr/bin/parec``
    is a symlink to ``pacat``, the same multi-call binary as ``paplay``, and the
    program's own idea of which program it is decides whether it records or
    *plays*. A capture path execing the resolved target would hand the
    microphone request to a player — exit code zero, no audio captured, and a
    speaker possibly emitting whatever was on stdin. So every backend declares
    the program name and the arguments that carry the semantics, and the check
    runs before anything is executed.
    """

    #: The program name ``argv[0]`` must carry. Not the target of any symlink.
    program: str
    #: What the recorder emits: always ``raw-pcm`` in this build, declared so a
    #: contract for a container-writing recorder would be visibly different.
    output_format: str
    #: Names the same binary answers to with different semantics.
    multicall_siblings: tuple[str, ...] = ()
    #: Argument prefixes the invocation must contain — the ones that carry
    #: meaning rather than preference. An invocation missing one is not the
    #: invocation that was tested.
    required_arguments: tuple[str, ...] = ()

    def refusal_for(self, executable: str, arguments: Sequence[str]) -> str:
        """Why this command must not be run, or ``""``."""
        name = PurePosixPath(executable.replace("\\", "/")).name
        if name != self.program:
            if name in self.multicall_siblings:
                return (
                    f"the recorder resolved to {name!r}, a multi-call sibling of "
                    f"{self.program!r} with different semantics under its own name; "
                    "this substitution was refused before any device was opened"
                )
            return (
                f"the recorder resolved to {name!r} and {self.program!r} was requested; "
                "a program's own idea of which program it is decides what it does with "
                "the microphone, and this substitution was refused"
            )
        missing = [
            item for item in self.required_arguments
            if not _argument_present(item, arguments)
        ]
        if missing:
            return (
                f"{self.program} was invoked without {', '.join(missing)}; that is not "
                "the invocation this backend declares and was refused"
            )
        return ""

    def to_json(self) -> dict[str, Any]:
        return {
            "program": self.program,
            "outputFormat": self.output_format,
            "multicallSiblings": list(self.multicall_siblings),
            "requiredArguments": list(self.required_arguments),
        }


@dataclass(frozen=True)
class CaptureDevice:
    """One input the machine can listen through."""

    device_id: str
    backend_id: str
    name: str = ""
    description: str = ""
    default: bool = False
    #: The server's own word for the source's state, carried verbatim. A
    #: suspended source is not a broken one.
    state: str = ""
    sample_specification: str = ""
    #: ``True`` when this source is a sink's monitor — the machine listening to
    #: its own output. Enumerated and *labelled* rather than hidden, and never
    #: selected by default: a monitor chosen as a microphone is speech output
    #: feeding straight back into speech input, which is §19's feedback loop
    #: built out of device selection.
    monitor: bool = False

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
            "monitor": self.monitor,
            "healthy": self.healthy,
        }


@dataclass(frozen=True)
class CaptureBackendHealth:
    """Whether one backend can capture right now."""

    backend_id: str
    kind: str
    available: bool = False
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
class CaptureDegradation:
    """One thing that went wrong, in a shape something can count.

    ``task_affected`` is always ``False`` and the type refuses to represent
    anything else — the same position :class:`companion.voice.audio.DegradationRecord`
    takes, for the same reason: a capture degradation that changed a task would
    be §1's boundary broken.
    """

    kind: str
    stage: str
    detail: str
    backend_id: str = ""
    provider_id: str = ""
    request_id: str = ""
    fallback: str = ""
    typed_input_preserved: bool = True
    task_affected: bool = False
    at_monotonic: float = 0.0

    def __post_init__(self) -> None:
        if self.kind not in CAPTURE_DEGRADATION_KINDS:
            raise ValueError(f"unknown capture degradation kind: {self.kind!r}")
        if self.task_affected:
            raise ValueError(
                "a speech-input degradation may not affect a task; speech input is an "
                "input surface and cannot change task authority"
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
            "typedInputPreserved": self.typed_input_preserved,
            "taskAffected": self.task_affected,
            "atMonotonic": self.at_monotonic,
        }


# --------------------------------------------------------------------------- #
# The bounded buffer
# --------------------------------------------------------------------------- #


class BoundedFrameBuffer:
    """The only place captured audio waits in memory, and it cannot grow.

    Two ceilings, independently enforced:

    ``maximum_buffered_bytes``
        how far the consumer may lag. Frames arriving past it are dropped and
        counted; the count is the §7 overrun report and nothing is ever
        silently absorbed.
    ``maximum_total_bytes``
        the request's whole capture budget. Frames past it are refused and
        :attr:`exhausted` is raised, which the worker reads as "stop the
        capture now" — the maximum-byte-count bound, enforced where the bytes
        arrive rather than where somebody remembers to check.
    """

    def __init__(
        self,
        *,
        maximum_buffered_bytes: int = DEFAULT_BUFFER_BYTES,
        maximum_total_bytes: int = 0,
    ) -> None:
        self.maximum_buffered_bytes = max(4096, int(maximum_buffered_bytes))
        self.maximum_total_bytes = max(0, int(maximum_total_bytes))
        self._chunks: deque[bytes] = deque()
        self._buffered = 0
        self._total = 0
        self._dropped_bytes = 0
        self._dropped_chunks = 0
        self._closed = False
        self._exhausted = False
        self._guard = threading.Lock()
        self._available = threading.Event()

    @property
    def buffered_bytes(self) -> int:
        with self._guard:
            return self._buffered

    @property
    def total_bytes(self) -> int:
        with self._guard:
            return self._total

    @property
    def dropped_bytes(self) -> int:
        with self._guard:
            return self._dropped_bytes

    @property
    def dropped_chunks(self) -> int:
        with self._guard:
            return self._dropped_chunks

    @property
    def overran(self) -> bool:
        with self._guard:
            return self._dropped_chunks > 0

    @property
    def exhausted(self) -> bool:
        with self._guard:
            return self._exhausted

    @property
    def closed(self) -> bool:
        with self._guard:
            return self._closed

    def push(self, chunk: bytes) -> bool:
        """Accept one chunk from the reader thread. Returns whether to keep reading.

        ``False`` means the buffer is closed or the total budget is spent; the
        reader stops consuming and the recorder blocks at the pipe until the
        worker terminates it. An *overrun* — the consumer lagging — returns
        ``True`` with the chunk dropped and counted, because a lagging consumer
        is a degradation and a spent budget is an ending.
        """
        if not chunk:
            return True
        with self._guard:
            if self._closed:
                return False
            if self.maximum_total_bytes and self._total + len(chunk) > self.maximum_total_bytes:
                self._exhausted = True
                self._available.set()
                return False
            if self._buffered + len(chunk) > self.maximum_buffered_bytes:
                self._dropped_bytes += len(chunk)
                self._dropped_chunks += 1
                return True
            self._chunks.append(chunk)
            self._buffered += len(chunk)
            self._total += len(chunk)
            self._available.set()
        return True

    def read(self, *, timeout: float = 0.05) -> bytes:
        """Everything currently buffered, or ``b""`` after ``timeout``.

        Draining rather than chunk-at-a-time: the activity detector and the
        recogniser both want "what has arrived since I last looked", and a
        caller that needed pacing gets it from the capture clock, not from this
        buffer's granularity.
        """
        if not self._available.wait(timeout):
            return b""
        with self._guard:
            if not self._chunks:
                self._available.clear()
                return b""
            body = b"".join(self._chunks)
            self._chunks.clear()
            self._buffered = 0
            self._available.clear()
        return body

    def close(self) -> None:
        with self._guard:
            self._closed = True
            self._chunks.clear()
            self._buffered = 0
            self._available.set()


# --------------------------------------------------------------------------- #
# The handle
# --------------------------------------------------------------------------- #


class CaptureHandle:
    """One open microphone, owned explicitly, closed exactly once.

    Wraps a :class:`companion.speech.execution.CaptureChild` and the bounded
    buffer its frames land in. The worker reads frames from here, asks
    :meth:`running` whether the device is still delivering, and calls
    :meth:`close` in a ``finally`` — after which :attr:`closed` is the fact §5
    keys the indicator on: the indicator is cleared only once this reports the
    handle closed.
    """

    def __init__(
        self,
        *,
        request_id: str,
        backend_id: str,
        device_id: str,
        spec: CommandSpec,
        buffer: BoundedFrameBuffer,
        monotonic: Any = None,
        refusal: str = "",
    ) -> None:
        self.request_id = request_id
        self.backend_id = backend_id
        self.device_id = device_id
        self.buffer = buffer
        self._now = monotonic or time.monotonic
        self._spec = spec
        self.requested_at = self._now()
        self.first_frame_at = 0.0
        self._guard = threading.RLock()
        self._closed = False

        def _sink(chunk: bytes) -> bool:
            with self._guard:
                if not self.first_frame_at:
                    self.first_frame_at = self._now()
            return buffer.push(chunk)

        self._child = CaptureChild(spec, sink=_sink, refusal=refusal)
        self.opened_at = self._now()

    @property
    def started(self) -> bool:
        return self._child.started

    @property
    def start_error(self) -> str:
        return self._child.start_error

    @property
    def closed(self) -> bool:
        with self._guard:
            return self._closed

    @property
    def open_latency_seconds(self) -> float:
        """Request-to-process. The request-to-first-frame number is separate."""
        return max(0.0, self.opened_at - self.requested_at)

    @property
    def first_frame_latency_seconds(self) -> float:
        with self._guard:
            if not self.first_frame_at:
                return 0.0
            return max(0.0, self.first_frame_at - self.requested_at)

    @property
    def bytes_captured(self) -> int:
        return self.buffer.total_bytes

    def running(self) -> bool:
        """Whether the recorder is alive and the budget is unspent.

        A recorder that exited while capture was wanted is the §17 signal for
        device loss — on the reference target it is *the* signal, because the
        WSLg bridge ends the stream rather than erroring.
        """
        return self._child.poll() is None and not self.buffer.exhausted

    def exit_code(self) -> int | None:
        return self._child.poll()

    def read(self, *, timeout: float = 0.05) -> bytes:
        return self.buffer.read(timeout=timeout)

    def stop(self) -> None:
        """Stop the recorder. The buffer keeps what already arrived."""
        self._child.terminate(
            grace_seconds=self._spec.grace_seconds,
            kill_grace_seconds=self._spec.kill_grace_seconds,
        )

    def close(self) -> "CaptureHandle":
        """Terminate, reap, release. Idempotent, and the moment §5 waits for."""
        with self._guard:
            if self._closed:
                return self
        self._child.terminate(
            grace_seconds=self._spec.grace_seconds,
            kill_grace_seconds=self._spec.kill_grace_seconds,
        )
        self._child.finish()
        self.buffer.close()
        with self._guard:
            self._closed = True
        return self

    def outcome(self, *, duration_seconds: float, cancelled: bool = False) -> Any:
        return self._child.outcome(duration_seconds=duration_seconds, cancelled=cancelled)

    def describe(self) -> dict[str, Any]:
        return {
            "requestId": self.request_id,
            "backendId": self.backend_id,
            "deviceId": self.device_id,
            "closed": self.closed,
            "running": self._child.poll() is None,
            "bytesCaptured": self.bytes_captured,
            "bufferedBytes": self.buffer.buffered_bytes,
            "droppedBytes": self.buffer.dropped_bytes,
            "openLatencySeconds": round(self.open_latency_seconds, 6),
            "firstFrameLatencySeconds": round(self.first_frame_latency_seconds, 6),
        }


# --------------------------------------------------------------------------- #
# Backends
# --------------------------------------------------------------------------- #


class CaptureBackend(Protocol):
    """What the worker may ask of a capture backend, and nothing wider.

    No method takes a device *path*, a command or a server address. A backend
    opens a device this runtime discovered for a request this runtime
    validated, and §20's protocol exposes no operation that could widen that.
    """

    backend_id: str
    kind: str

    def health(self, *, monotonic: float = 0.0, refresh: bool = False) -> CaptureBackendHealth: ...
    def discover(self) -> Sequence[CaptureDevice]: ...
    def default_device(self) -> CaptureDevice | None: ...
    def supports(self, request: SpeechInputRequest) -> tuple[bool, str]: ...
    def open(
        self,
        request: SpeechInputRequest,
        *,
        device_id: str = "",
        buffer: BoundedFrameBuffer | None = None,
    ) -> CaptureHandle: ...
    def close(self) -> None: ...


class _RecorderBackend:
    """Common ground for a backend that shells out to a one-shot recorder."""

    backend_id = ""
    kind = ""
    recorder = ""
    inspector = ""
    #: What this backend requires of the program it starts. No default: a
    #: backend added without one refuses to record rather than recording
    #: something unchecked.
    contract: RecorderContract | None = None

    #: The latency asked of the capture server. 60 ms matches playback; short
    #: enough that push-to-talk feels immediate, long enough not to underrun.
    DEFAULT_LATENCY_MS = 60

    def __init__(self, *, resolver=None) -> None:
        self._resolve = resolver or resolve_capture_executable
        self._recorder_path = ""
        self._inspector_path = ""
        self._resolution_error = ""
        self._trusted = True
        self._resolve_once()
        self._health: CaptureBackendHealth | None = None
        self._failures = 0
        self._devices: tuple[CaptureDevice, ...] = ()
        self._closed = False
        #: Diagnostic only, and only in the direction that makes things worse:
        #: §24 step 23 asks the slice to remove the input device or simulate its
        #: loss, and on a machine whose microphone cannot be unplugged by a
        #: script this is how. It cannot fake a working backend.
        self._simulated_loss = False
        self._guard = threading.RLock()

    def _resolve_once(self) -> None:
        problems: list[str] = []
        for attribute, name in (("_recorder_path", self.recorder), ("_inspector_path", self.inspector)):
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

    def _capture_output(self, argv: Sequence[str], *, timeout: float = 10.0) -> tuple[int, str, str]:
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

    def discover(self) -> Sequence[CaptureDevice]:
        raise NotImplementedError

    def default_device(self) -> CaptureDevice | None:
        devices = list(self.discover())
        for device in devices:
            if device.default and not device.monitor:
                return device
        for device in devices:
            if not device.monitor:
                return device
        # Every source is a monitor: the machine can hear only itself. That is
        # not a microphone, and returning one as the default would select the
        # §19 feedback loop by omission.
        return None

    def health(self, *, monotonic: float = 0.0, refresh: bool = False) -> CaptureBackendHealth:
        with self._guard:
            cached = self._health
            if cached is not None and not refresh and monotonic - cached.checked_at_monotonic < 5.0:
                return replace(cached, consecutive_failures=self._failures)
        if refresh:
            with self._guard:
                self._recorder_path = ""
                self._inspector_path = ""
                self._resolve_once()
        available = bool(self._recorder_path) and not self._closed
        devices: Sequence[CaptureDevice] = ()
        detail = self._resolution_error if not available else ""
        reachable = False
        if self._simulated_loss:
            return self._remember(CaptureBackendHealth(
                backend_id=self.backend_id,
                kind=self.kind,
                available=available,
                reachable=False,
                device_count=0,
                detail="a simulated input-device loss is in effect for this diagnostic run",
                checked_at_monotonic=monotonic,
                consecutive_failures=self._failures,
            ), ())
        if available:
            try:
                devices = self.discover()
                reachable = True
            except _Unreachable as exc:
                detail = str(exc)
        usable = [item for item in devices if not item.monitor]
        default = next((item.device_id for item in usable if item.default), "")
        health = CaptureBackendHealth(
            backend_id=self.backend_id,
            kind=self.kind,
            available=available,
            reachable=reachable,
            device_count=len(usable),
            default_device=default or (usable[0].device_id if usable else ""),
            detail=detail or (f"{self._failures} consecutive failures" if self._failures else ""),
            checked_at_monotonic=monotonic,
            consecutive_failures=self._failures,
        )
        return self._remember(health, devices)

    def _remember(
        self, health: CaptureBackendHealth, devices: Sequence[CaptureDevice]
    ) -> CaptureBackendHealth:
        with self._guard:
            self._health = health
            self._devices = tuple(devices)
        return health

    def set_reachable(self, value: bool) -> None:
        """Diagnostic only: make this backend report itself unreachable."""
        with self._guard:
            self._simulated_loss = not value
            self._health = None

    def record(self, succeeded: bool) -> None:
        with self._guard:
            self._failures = 0 if succeeded else self._failures + 1

    def supports(self, request: SpeechInputRequest) -> tuple[bool, str]:
        """Whether this recorder can capture what the request asks for.

        Permissive on the server-backed paths — the server converts — and a
        real check on the raw ALSA path, where nothing does.
        """
        del request
        return True, ""

    def _record_spec(
        self, request: SpeechInputRequest, *, device_id: str
    ) -> CommandSpec:
        raise NotImplementedError

    def open(
        self,
        request: SpeechInputRequest,
        *,
        device_id: str = "",
        buffer: BoundedFrameBuffer | None = None,
    ) -> CaptureHandle:
        spec = self._record_spec(request, device_id=device_id)
        frames = buffer if buffer is not None else BoundedFrameBuffer(
            maximum_total_bytes=request.maximum_capture_bytes,
        )
        return CaptureHandle(
            request_id=request.request_id,
            backend_id=self.backend_id,
            device_id=device_id,
            spec=spec,
            buffer=frames,
            refusal=self.verify_invocation(spec),
        )

    def verify_invocation(self, spec: CommandSpec) -> str:
        """Why this command must not be started, or ``""``.

        Runs before the child exists, so a refused invocation costs no process
        and — the part that matters here — no open microphone.
        """
        if self.contract is None:
            return (
                f"{self.backend_id} declares no recorder contract, so what it would start "
                "cannot be checked; refusing rather than executing an unverified recorder"
            )
        return self.contract.refusal_for(spec.executable, spec.arguments)

    def close(self) -> None:
        with self._guard:
            self._closed = True

    @property
    def trusted_resolution(self) -> bool:
        return self._trusted


class _Unreachable(RuntimeError):
    """The recorder is installed and the server is not answering."""


def _capture_timeout(seconds: float) -> float:
    """The recorder's own time bound: the capture ceiling plus a margin.

    The worker stops the recorder long before this; the bound exists so a
    worker that faulted cannot leave a recorder holding the microphone forever.
    """
    return max(15.0, min(600.0, seconds + 30.0))


class PulseAudioCaptureBackend(_RecorderBackend):
    """``parec`` against a PulseAudio-compatible server.

    On the reference target that server is the WSLg audio bridge, and the
    source is ``RDPSource`` — the Windows host's microphone carried over RDP.
    ``kind`` says ``pulse-compatible`` for the reason the playback backend's
    does: what answers the socket is not knowable from here.
    """

    backend_id = "pulse"
    kind = "pulse-compatible"
    recorder = "parec"
    inspector = "pactl"
    #: ``/usr/bin/parec`` is a symlink to ``pacat``. Under its own name pacat
    #: *plays* stdin; under parec's it records. Same binary, same exit status,
    #: opposite direction of audio.
    contract = RecorderContract(
        program="parec",
        output_format="raw-pcm",
        multicall_siblings=("pacat", "paplay", "parecord", "pamon"),
        required_arguments=(
            "--client-name=", "--format=", "--rate=", "--channels=", "--latency-msec=",
        ),
    )

    def discover(self) -> Sequence[CaptureDevice]:
        if not self._inspector_path:
            return (CaptureDevice(
                device_id="", backend_id=self.backend_id, name="default",
                description="the server's default source; pactl is not installed to enumerate",
                default=True,
            ),)
        code, out, err = self._capture_output([self._inspector_path, "list", "short", "sources"])
        if code != 0:
            raise _Unreachable(err or f"pactl exited {code}; no PulseAudio-compatible server answered")
        default_code, default_out, _ = self._capture_output([self._inspector_path, "get-default-source"])
        default_name = default_out.strip() if default_code == 0 else ""
        devices: list[CaptureDevice] = []
        for line in out.splitlines():
            fields = line.split("\t")
            if len(fields) < 2:
                continue
            name = fields[1].strip()
            if not name:
                continue
            devices.append(CaptureDevice(
                device_id=name,
                backend_id=self.backend_id,
                name=name,
                description=fields[2].strip() if len(fields) > 2 else "",
                default=name == default_name,
                state=fields[4].strip() if len(fields) > 4 else "",
                sample_specification=fields[3].strip() if len(fields) > 3 else "",
                monitor=name.endswith(".monitor"),
            ))
            if len(devices) >= 64:
                break
        return tuple(devices)

    def _record_spec(self, request: SpeechInputRequest, *, device_id: str) -> CommandSpec:
        arguments: list[str] = []
        if device_id:
            arguments += [f"--device={device_id}"]
        arguments += [
            "--format=s16le",
            f"--rate={request.sample_rate}",
            f"--channels={request.channels}",
            f"--latency-msec={self.DEFAULT_LATENCY_MS}",
            "--client-name=bunny-companion-mic",
            "--raw",
        ]
        return CommandSpec(
            executable=self._recorder_path,
            arguments=tuple(arguments),
            touches_audio=True,
            timeout_seconds=_capture_timeout(request.maximum_capture_seconds),
        )


class PipeWireCaptureBackend(_RecorderBackend):
    """``pw-record`` against a PipeWire daemon.

    Present and non-functional on the reference target — the tools are
    installed and no daemon runs — which makes it a real instance of the
    fallback path, produced by the machine rather than by a mock.
    """

    backend_id = "pipewire"
    kind = "pipewire"
    recorder = "pw-record"
    inspector = "pw-dump"
    #: ``/usr/bin/pw-record`` is a symlink to ``pw-cat``, the same argv[0]
    #: split as parec/pacat. Never observed to record on the reference target —
    #: no daemon — so the contract is declared and checked while the capture it
    #: guards has not been exercised on a working PipeWire.
    contract = RecorderContract(
        program="pw-record",
        output_format="raw-pcm",
        multicall_siblings=("pw-cat", "pw-play", "pw-midiplay", "pw-midirecord"),
        required_arguments=("--raw", "--rate=", "--channels=", "--"),
    )

    def discover(self) -> Sequence[CaptureDevice]:
        if not self._inspector_path:
            raise _Unreachable("pw-dump is not installed, so PipeWire sources cannot be enumerated")
        code, out, err = self._capture_output([self._inspector_path])
        if code != 0:
            raise _Unreachable(err or f"pw-dump exited {code}; no PipeWire daemon answered")
        try:
            graph = json.loads(out or "[]")
        except json.JSONDecodeError as exc:
            raise _Unreachable(f"pw-dump produced output this cannot read: {exc}") from exc
        if not isinstance(graph, list):
            raise _Unreachable("pw-dump did not produce a graph")
        # Which source the session calls its default is metadata, not a node
        # property; see companion/pipewire.py for what reading it off the node
        # cost.
        default_name = default_node_name(graph, DEFAULT_SOURCE_KEYS)
        devices: list[CaptureDevice] = []
        for node in graph:
            if not isinstance(node, Mapping):
                continue
            info = node.get("info")
            props = info.get("props") if isinstance(info, Mapping) else None
            if not isinstance(props, Mapping):
                continue
            media_class = props.get("media.class")
            if media_class not in ("Audio/Source", "Audio/Source/Virtual"):
                continue
            name = str(props.get("node.name", "")).strip()
            if not name:
                continue
            devices.append(CaptureDevice(
                device_id=name,
                backend_id=self.backend_id,
                name=name,
                description=str(props.get("node.description", "")),
                default=bool(default_name) and name == default_name,
                state=str(info.get("state", "")) if isinstance(info, Mapping) else "",
                monitor="monitor" in name.lower(),
            ))
            if len(devices) >= 64:
                break
        if not devices:
            raise _Unreachable("the PipeWire graph contains no audio source")
        return tuple(devices)

    def _record_spec(self, request: SpeechInputRequest, *, device_id: str) -> CommandSpec:
        arguments: list[str] = []
        if device_id:
            arguments += [f"--target={device_id}"]
        arguments += [
            "--raw",
            "--format=s16",
            f"--rate={request.sample_rate}",
            f"--channels={request.channels}",
            f"--latency={self.DEFAULT_LATENCY_MS}ms",
            "--", "-",
        ]
        return CommandSpec(
            executable=self._recorder_path,
            arguments=tuple(arguments),
            touches_audio=True,
            timeout_seconds=_capture_timeout(request.maximum_capture_seconds),
        )


class AlsaCaptureBackend(_RecorderBackend):
    """``arecord`` straight at a card.

    The floor of the ladder, exclusive while it captures, and on the reference
    target a real instance of "no capture device at startup" — WSL presents no
    ALSA card at all.
    """

    backend_id = "alsa"
    kind = "alsa"
    recorder = "arecord"
    inspector = "arecord"
    #: ``arecord`` and ``aplay`` are one binary on some builds, split on
    #: ``argv[0]`` — record versus play, the sharpest version of the multi-call
    #: hazard this subsystem inherits.
    contract = RecorderContract(
        program="arecord",
        output_format="raw-pcm",
        multicall_siblings=("aplay",),
        required_arguments=("-q", "-t", "raw", "-f", "S16_LE"),
    )

    def discover(self) -> Sequence[CaptureDevice]:
        if not self._recorder_path:
            raise _Unreachable("arecord is not installed")
        code, out, err = self._capture_output([self._recorder_path, "-l"])
        if code != 0 or "no soundcards" in (err or "").lower():
            raise _Unreachable(err.splitlines()[0] if err else f"arecord exited {code}; no ALSA card")
        devices: list[CaptureDevice] = []
        for line in out.splitlines():
            if not line.startswith("card "):
                continue
            try:
                card = line.split(":", 1)[0].split()[1]
                device = line.split("device", 1)[1].split(":", 1)[0].strip()
            except (IndexError, ValueError):
                continue
            identifier = f"hw:{card},{device}"
            devices.append(CaptureDevice(
                device_id=identifier,
                backend_id=self.backend_id,
                name=identifier,
                description=line.strip(),
                default=not devices,
            ))
            if len(devices) >= 32:
                break
        if not devices:
            raise _Unreachable("arecord reported no capture device")
        return tuple(devices)

    def supports(self, request: SpeechInputRequest) -> tuple[bool, str]:
        # ALSA converts nothing. The formats this runtime accepts are exactly
        # what `-f S16_LE` produces, so the check is on rate and channels only
        # and both are passed through verbatim.
        return True, ""

    def _record_spec(self, request: SpeechInputRequest, *, device_id: str) -> CommandSpec:
        arguments: list[str] = ["-q", "-t", "raw", "-f", "S16_LE"]
        arguments += ["-r", str(request.sample_rate), "-c", str(request.channels)]
        if device_id:
            arguments += ["-D", device_id]
        return CommandSpec(
            executable=self._recorder_path,
            arguments=tuple(arguments),
            touches_audio=True,
            timeout_seconds=_capture_timeout(request.maximum_capture_seconds),
        )


def local_capture_backends(*, resolver=None) -> list[CaptureBackend]:
    """Every backend, in the order the router descends.

    The same order and the same reasons as playback: PipeWire where it runs,
    the pulse-compatible socket almost every host presents some way of
    reaching, ALSA last because it takes the device exclusively.
    """
    return [
        PipeWireCaptureBackend(resolver=resolver),
        PulseAudioCaptureBackend(resolver=resolver),
        AlsaCaptureBackend(resolver=resolver),
    ]


# --------------------------------------------------------------------------- #
# Routing, loss and hysteresis
# --------------------------------------------------------------------------- #


@dataclass
class _BackendState:
    failures: int = 0
    blocked_until: float = 0.0
    healthy_streak: int = 0
    last_devices: tuple[str, ...] = ()


class CaptureRouter:
    """Chooses a capture backend, notices when it stops working, recovers carefully.

    The three behaviours are the playback router's, because the failure physics
    are the same: fall back once then degrade to typing, back off a failed
    backend on a doubling monotonic interval, and restore only after
    :data:`RESTORE_OBSERVATIONS` consecutive healthy readings.
    """

    BACKOFF_SECONDS = 2.0
    MAX_BACKOFF_SECONDS = 60.0
    RESTORE_OBSERVATIONS = 2

    def __init__(
        self,
        backends: Iterable[CaptureBackend] | None = None,
        *,
        monotonic: Any = None,
        resolver=None,
    ) -> None:
        self.backends: list[CaptureBackend] = list(
            backends if backends is not None else local_capture_backends(resolver=resolver)
        )
        self._now = monotonic or time.monotonic
        self._state: dict[str, _BackendState] = {
            backend.backend_id: _BackendState() for backend in self.backends
        }
        self._degradations: list[CaptureDegradation] = []
        self._guard = threading.RLock()
        self._preferred_device = ""

    @property
    def degradations(self) -> tuple[CaptureDegradation, ...]:
        with self._guard:
            return tuple(self._degradations)

    def record(self, record: CaptureDegradation) -> CaptureDegradation:
        with self._guard:
            self._degradations.append(record)
            if len(self._degradations) > 256:
                del self._degradations[:-256]
        return record

    def prefer_device(self, device_id: str) -> None:
        with self._guard:
            self._preferred_device = device_id

    @property
    def preferred_device(self) -> str:
        with self._guard:
            return self._preferred_device

    # ----------------------------------------------------------------- #

    def observe(self) -> list[CaptureBackendHealth]:
        """A health reading of every backend, with the hysteresis updated."""
        now = self._now()
        report: list[CaptureBackendHealth] = []
        for backend in self.backends:
            health = backend.health(monotonic=now)
            state = self._state.setdefault(backend.backend_id, _BackendState())
            if health.ready:
                state.healthy_streak += 1
                if state.healthy_streak >= self.RESTORE_OBSERVATIONS and state.blocked_until:
                    state.blocked_until = 0.0
                    state.failures = 0
                    self.record(CaptureDegradation(
                        kind="audio-server-restart",
                        stage="observation",
                        backend_id=backend.backend_id,
                        detail=(
                            f"{backend.backend_id} answered {state.healthy_streak} consecutive "
                            "health checks and was restored"
                        ),
                        at_monotonic=now,
                    ))
                names = tuple(item.device_id for item in backend.discover())
                if state.last_devices and names and names != state.last_devices:
                    self.record(CaptureDegradation(
                        kind="default-device-changed",
                        stage="observation",
                        backend_id=backend.backend_id,
                        detail=(
                            f"the source list changed from {len(state.last_devices)} to "
                            f"{len(names)} inputs"
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

    def penalise(
        self, backend_id: str, *, detail: str, kind: str, request_id: str = ""
    ) -> CaptureDegradation:
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
        return self.record(CaptureDegradation(
            kind=kind,
            stage="capture",
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
        self,
        request: SpeechInputRequest | None = None,
        *,
        exclude: Iterable[str] = (),
    ) -> tuple[CaptureBackend | None, CaptureDevice | None, tuple[str, ...]]:
        """The first backend that is ready, not excluded and not backing off."""
        skipped = set(exclude)
        reasons: list[str] = []
        now = self._now()
        for backend in self.backends:
            name = backend.backend_id
            if name in skipped:
                reasons.append(f"{name}: excluded after failing on this capture")
                continue
            if self._blocked(name):
                remaining = self._state[name].blocked_until - now
                reasons.append(f"{name}: backing off for another {remaining:.1f}s")
                continue
            health = backend.health(monotonic=now)
            if not health.ready:
                reasons.append(f"{name}: {health.detail or 'not ready'}")
                continue
            if request is not None:
                ok, why = backend.supports(request)
                if not ok:
                    reasons.append(f"{name}: {why}")
                    continue
            everything = list(backend.discover())
            devices = [item for item in everything if not item.monitor]
            device = None
            preferred = (request.device_preference if request else "") or self.preferred_device
            if preferred:
                # The preferred lookup runs over *everything*, monitors
                # included: a monitor source explicitly named by its exact id
                # is honoured, because it is the controlled loopback path the
                # installed slice uses to put known audio through a real
                # capture chain. It is never a default, never enumerated as
                # usable, and its id says what it is in every event.
                device = next((item for item in everything if item.device_id == preferred), None)
                if device is None:
                    self.record(CaptureDegradation(
                        kind="device-removed-before-capture",
                        stage="selection",
                        backend_id=name,
                        detail=f"the selected input {preferred!r} is no longer present",
                        at_monotonic=now,
                    ))
            if device is None:
                device = next(
                    (item for item in devices if item.default),
                    devices[0] if devices else None,
                )
            if device is None:
                reasons.append(f"{name}: reports no capture device that is not a monitor")
                continue
            return backend, device, tuple(reasons)
        return None, None, tuple(reasons)

    def describe(self) -> dict[str, Any]:
        now = self._now()
        return {
            "backends": [backend.health(monotonic=now).to_json() for backend in self.backends],
            "preferredDevice": self.preferred_device,
            "physicalMicrophoneValidated": False,
            "degradations": [item.to_json() for item in self.degradations[-32:]],
        }

    def close(self) -> None:
        for backend in self.backends:
            try:
                backend.close()
            except Exception:  # noqa: BLE001 - closing must not stop at the first failure
                continue
