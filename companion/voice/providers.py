# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The local synthesisers this build can actually use, and nothing it cannot.

Two adapters, both for programs that are packaged, installed and were exercised
on the reference target:

:class:`EspeakNgProvider`
    eSpeak NG. Synthesises to a private WAV file, which is the path that makes
    amplitude-derived visemes, measured caption offsets and pause/resume
    possible, because the audio is ours before it is played. Also speaks
    directly when asked to stream.

:class:`SpeechDispatcherProvider`
    Speech Dispatcher, through ``spd-say``. Stream-only by design: it is a
    *server* with its own queue, its own priorities and its own audio
    connection, and a client that also wanted the samples would be fighting it.
    Selected when a request prefers streaming, or when eSpeak NG is absent.

There is no OpenAI adapter, no ElevenLabs adapter, no Fish Speech adapter and no
placeholder shaped like one. §4 is explicit that a commercial adapter must not
be invented, and the reason is stronger than tidiness: a stub that reported
"unavailable — no API key" would put the shape of remote speech into the code
and make adding a key the only remaining step. There is no key field anywhere in
this package.

**Exit status is not evidence.** Both traps below were measured on the reference
target, not assumed:

* ``espeak-ng --stdin -w out.wav`` with empty input exits **0** and writes no
  file;
* ``espeak-ng --stdin -w /unwritable/out.wav`` exits **0**, prints
  ``Can't write to: ...`` to stderr, and writes no file.

So :meth:`EspeakNgProvider.synthesize` treats a zero exit as necessary and not
sufficient: the artifact is probed by :func:`companion.voice.pcm.probe_wav`, and
success means there were frames in it. A provider that trusted the exit code
would report speech that never existed.

**The utterance goes through stdin in both adapters.** eSpeak NG has
``--stdin``; ``spd-say`` has ``-e``/``--pipe-mode``. Neither needs the text in
an argument, and keeping it out of one matters: an argv is readable in ``/proc``
by every process the user runs, so a caption passed as an argument is a caption
published to the machine.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
import re
import threading
from typing import Any, Mapping, Sequence

from .execution import (
    CancellationSignal,
    CommandOutcome,
    CommandSpec,
    ExecutableRefused,
    PrivateWorkspace,
    run as run_command,
)
from .pcm import PcmError, probe_wav
from .provider import (
    ProviderDeclaration,
    ProviderHealth,
    ProviderRegistry,
    ResourceEstimate,
    StreamOutcome,
    SynthesisResult,
    VoiceDescriptor,
)
from .request import VoiceRequest

__all__ = [
    "EspeakNgProvider",
    "SpeechDispatcherProvider",
    "local_providers",
]

#: How long a health answer is reused before the binary is looked at again.
#: A provider being uninstalled mid-session is rare; probing the filesystem on
#: every utterance is not free; thirty seconds is short enough that a user who
#: fixed an installation does not have to restart the service.
HEALTH_TTL_SECONDS = 30.0

#: The most voices an inventory will return. ``espeak-ng --voices`` lists 141 on
#: the reference target and ``spd-say -L`` lists thousands once variants are
#: expanded; a settings surface cannot use thousands and a service should not
#: hold them.
MAX_INVENTORY = 512

#: An identifier we will accept from a provider's own voice list. A voice id
#: reaches an argv, so anything that is not this shape is skipped and counted
#: rather than sanitised into something the provider would not recognise.
_SAFE_VOICE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}\Z")


def _argument_present(required: str, arguments: Sequence[str]) -> bool:
    """Whether a declared argument is in an argv, exactly as declared.

    A trailing ``=`` means "this option, whatever its value" and matches by
    prefix; anything else must match exactly. A prefix rule would let any long
    option satisfy a requirement for a bare ``--``, which is the argument that
    stops option parsing.
    """
    if required.endswith("="):
        return any(item.startswith(required) for item in arguments)
    return required in tuple(arguments)


def _locale_from_tag(tag: str) -> tuple[str, str]:
    """``en-gb`` becomes ``("en", "en-GB")``; ``en`` becomes ``("en", "en")``.

    eSpeak NG's language column is lower-case throughout, and the request schema
    compares locales case-sensitively after checking the language prefix. Doing
    the normalisation here means the comparison in
    :meth:`ProviderDeclaration.handles_language` is between two values that were
    produced the same way.
    """
    parts = [item for item in str(tag).split("-") if item]
    if not parts:
        return "en", "en"
    language = parts[0].lower()
    if len(parts) == 1:
        return language, language
    region = parts[1]
    normalised = region.upper() if len(region) == 2 else region.lower()
    tail = "-".join(parts[2:])
    locale = f"{language}-{normalised}" + (f"-{tail}" if tail else "")
    return language, locale


class _CommandProvider:
    """Shared machinery for a provider backed by a local program.

    Health caching, cancellation bookkeeping and the "resolve once, remember the
    refusal" rule all live here so the two adapters differ only in the parts
    that are genuinely different: how they are invoked and what they can do.
    """

    executable_name = ""
    fallback_names: tuple[str, ...] = ()
    #: Names the same binary may answer to with different semantics. Declared
    #: so a refusal can say what was substituted rather than only that the name
    #: was wrong.
    multicall_siblings: tuple[str, ...] = ()
    #: Argument prefixes that carry the adapter's semantics. Checked before
    #: every invocation, because an adapter invoked without them is not the
    #: adapter that was measured.
    required_arguments: tuple[str, ...] = ()

    def __init__(self, *, resolver=None) -> None:
        # Injected so a test can present a program that is missing, that is
        # outside the trusted directories, or that ignores termination — without
        # installing one. The default is the real, allowlisted resolution.
        from .execution import resolve_executable

        self._resolve = resolver or resolve_executable
        self._executable = ""
        #: Which declared name was resolved. ``espeak-ng`` and ``espeak`` are
        #: not the same program, and an utterance attributed to "the espeak
        #: adapter" without saying which is an utterance nobody can reproduce.
        self._program_name = ""
        self._trusted = True
        self._resolution_error = ""
        self._resolve_once()
        self._health: ProviderHealth | None = None
        self._failures = 0
        self._inventory: tuple[VoiceDescriptor, ...] | None = None
        self._inventory_skipped = 0
        self._active: dict[str, CancellationSignal] = {}
        self._guard = threading.RLock()
        self._closed = False

    # ----------------------------------------------------------------- #

    def _resolve_once(self) -> None:
        names = (self.executable_name, *self.fallback_names)
        problems: list[str] = []
        for name in names:
            if not name:
                continue
            try:
                path, trusted = self._resolve(name)
            except ExecutableRefused as exc:
                problems.append(str(exc))
                continue
            self._executable = path
            self._program_name = name
            self._trusted = trusted
            return
        self._resolution_error = "; ".join(problems) or "no executable was configured"

    @property
    def available(self) -> bool:
        return bool(self._executable) and not self._closed

    def health(self, *, monotonic: float = 0.0, refresh: bool = False) -> ProviderHealth:
        with self._guard:
            cached = self._health
            fresh = (
                cached is not None
                and not refresh
                and monotonic - cached.checked_at_monotonic < HEALTH_TTL_SECONDS
            )
            if fresh and cached is not None:
                return replace(cached, consecutive_failures=self._failures)
            if refresh or cached is None:
                # Re-resolve on an explicit refresh: a synthesiser installed
                # after the service started should become usable without a
                # restart, and one removed should stop being offered.
                if refresh:
                    self._executable = ""
                    self._resolution_error = ""
                    self._resolve_once()
                    self._inventory = None
            detail = "" if self._executable else self._resolution_error
            if self._executable and not self._trusted:
                detail = (
                    "resolved outside the trusted directories; this is a development host "
                    "and not the installed system"
                )
            health = ProviderHealth(
                provider_id=self.declaration.provider_id,
                available=bool(self._executable) and not self._closed,
                authenticated=True,
                # Two consecutive failures is unhealthy. One is a bad utterance;
                # two is a provider, and §12 wants the fallback to happen after
                # the first failure rather than on every subsequent one.
                healthy=self._failures < 2,
                detail=detail or (f"{self._failures} consecutive failures" if self._failures else ""),
                checked_at_monotonic=monotonic,
                consecutive_failures=self._failures,
            )
            self._health = health
            return health

    def _record(self, succeeded: bool) -> None:
        with self._guard:
            self._failures = 0 if succeeded else self._failures + 1
            if self._health is not None:
                self._health = replace(
                    self._health,
                    healthy=self._failures < 2,
                    consecutive_failures=self._failures,
                )

    def _register(self, request_id: str, signal: CancellationSignal) -> CancellationSignal:
        with self._guard:
            self._active[request_id] = signal
        return signal

    def _unregister(self, request_id: str) -> None:
        with self._guard:
            self._active.pop(request_id, None)

    def cancel(self, request_id: str) -> bool:
        with self._guard:
            signal = self._active.get(request_id)
        if signal is None:
            return False
        return signal.cancel("cancelled by the voice worker")

    def cancel_all(self) -> tuple[str, ...]:
        with self._guard:
            identifiers = tuple(self._active)
        return tuple(item for item in identifiers if self.cancel(item))

    def close(self) -> None:
        with self._guard:
            if self._closed:
                return
            self._closed = True
        self.cancel_all()

    # ----------------------------------------------------------------- #

    def program_name(self) -> str:
        """Which of the declared names this adapter actually resolved.

        ``espeak-ng`` and ``espeak`` are different programs with different
        argument handling and a different exit-code bug, and an adapter that
        recorded only "a synthesiser was found" could not say which one produced
        an utterance. Recorded, reported in the health, and checked before every
        invocation.
        """
        return self._program_name

    def verify_invocation(self, spec: CommandSpec) -> str:
        """Why this command must not be started, or ``""``.

        Two checks, and neither infers anything from what the path resolved to.
        The program must still be the one this adapter asked for — a multi-call
        binary decides what it does from ``argv[0]``, so a substituted name is a
        substituted program — and the arguments that carry the semantics must
        still be there. An adapter invoked without them is not the adapter that
        was measured.
        """
        name = PurePosixPath(spec.executable.replace("\\", "/")).name
        if self._program_name and name != self._program_name:
            sibling = " (a multi-call sibling that does something else under this name)" \
                if name in self.multicall_siblings else ""
            return (
                f"{self.declaration.provider_id} resolved {self._program_name!r} and would "
                f"start {name!r}{sibling}; the requested adapter was not preserved and the "
                "invocation was refused"
            )
        missing = [
            item for item in self.required_arguments
            if not _argument_present(item, spec.arguments)
        ]
        if missing:
            return (
                f"{self.declaration.provider_id} would be invoked without "
                f"{', '.join(missing)}; that is not the invocation this adapter declares"
            )
        return ""

    def _guarded(
        self,
        request: VoiceRequest,
        cancellation: CancellationSignal | None,
        spec: CommandSpec,
    ) -> CommandOutcome:
        refusal = self.verify_invocation(spec)
        if refusal:
            # Returned as data with the shape ``run_command`` produces for a
            # program that could not be started, so it travels the path every
            # caller already handles rather than a new one.
            return CommandOutcome(
                executable=spec.executable,
                redacted_argv=tuple(spec.redacted()),
                exit_code=None,
                duration_seconds=0.0,
                start_error=refusal,
            )
        signal = cancellation or CancellationSignal(name=request.request_id)
        self._register(request.request_id, signal)
        try:
            return run_command(spec, cancellation=signal)
        finally:
            # Unregistered whatever happened. A signal left in the table is a
            # cancel that would apply to whichever utterance next reused the id.
            self._unregister(request.request_id)


# --------------------------------------------------------------------------- #
# eSpeak NG
# --------------------------------------------------------------------------- #


class EspeakNgProvider(_CommandProvider):
    """eSpeak NG: a formant synthesiser that is small, fast and everywhere.

    Its output is fixed at 22.05 kHz mono 16-bit on the reference target, so the
    declaration says exactly that rather than claiming a range it would silently
    ignore. A request for 48 kHz is refused by
    :meth:`ProviderDeclaration.serves` and degrades through §12's ladder, which
    is the honest outcome: this synthesiser cannot produce 48 kHz, and
    resampling it here would be a second audio implementation pretending it can.
    """

    executable_name = "espeak-ng"
    fallback_names = ("espeak",)
    #: ``speak-ng`` and ``speak`` are symlinks to these binaries on Fedora.
    #: Declared not because their behaviour is known to differ but because
    #: the check is on what was *requested*: a program's own idea of which
    #: program it is decides what it does, and that identity is the thing
    #: symlink resolution erases.
    multicall_siblings = ("speak-ng", "speak", "espeak-ng-data")
    #: ``--stdin`` is not a preference. Without it eSpeak NG takes the
    #: utterance from argv, which publishes what the user is being told in
    #: the process table for every process on the machine to read.
    required_arguments = ("--stdin", "-v")

    #: eSpeak NG's own ranges, from its manual page. Values outside these are
    #: clamped and the clamping is *recorded*, because a rate the user asked for
    #: and did not get is a degradation whether or not it mattered.
    WPM_RANGE = (80, 450)
    DEFAULT_WPM = 175
    PITCH_RANGE = (0, 99)
    AMPLITUDE_RANGE = (0, 200)

    #: What the synthesiser emits, measured rather than assumed:
    #: ``espeak-ng --stdin -w x.wav`` produced 22050 Hz, 1 channel, 2-byte
    #: samples on eSpeak NG 1.52.0.
    NATIVE_SAMPLE_RATE = 22_050

    def __init__(self, *, resolver=None, version: str = "") -> None:
        super().__init__(resolver=resolver)
        self._version = version

    @property
    def declaration(self) -> ProviderDeclaration:
        languages = tuple(sorted({voice.language for voice in self.inventory()})) or ("en",)
        locales = tuple(sorted({voice.locale for voice in self.inventory()}))
        return ProviderDeclaration(
            provider_id="espeak-ng",
            implementation_id=self._implementation_id(),
            languages=languages,
            locales=locales,
            audio_formats=("wav-pcm-s16le",),
            sample_rates=(self.NATIVE_SAMPLE_RATE,),
            supports_synthesis=True,
            # It plays directly when not given ``-w``. Not "streaming" in the
            # sense of incremental delivery — nothing here delivers partial
            # audio — but provider-owned playback, which is what the streaming
            # path means in this package.
            supports_streaming=True,
            supports_cancellation=True,
            rate_control=True,
            pitch_control=True,
            volume_control=True,
            local=True,
            cost_class="free",
            maximum_privacy_class="secret",
            requires_authentication=False,
            # eSpeak NG can emit phoneme *names* with ``-x``; it does not emit
            # boundaries with the audio, and §13 forbids claiming timing
            # accuracy that has not been measured. So: no.
            provides_phoneme_timing=False,
            provides_native_visemes=False,
            trusted_resolution=self._trusted,
        )

    def _implementation_id(self) -> str:
        if self._version:
            return f"espeak-ng/{self._version}"
        if not self._executable:
            return "espeak-ng/absent"
        return f"espeak-ng/{Path(self._executable).name}"

    # ----------------------------------------------------------------- #

    def inventory(self) -> Sequence[VoiceDescriptor]:
        """Voices from ``espeak-ng --voices``, parsed and bounded.

        The table is fixed-width with a header, and the columns are
        ``Pty Language Age/Gender VoiceName File Other``. Split on whitespace and
        take the first four: ``VoiceName`` never contains a space (eSpeak NG
        writes ``English_(Great_Britain)``), so the split is unambiguous for the
        fields this needs.
        """
        with self._guard:
            if self._inventory is not None:
                return self._inventory
        voices: tuple[VoiceDescriptor, ...] = ()
        skipped = 0
        if self._executable:
            # Read with its own bounded call rather than through
            # :func:`companion.voice.execution.run`: that runner discards a
            # child's stdout on purpose — no utterance path wants it — and an
            # inventory is the one place stdout is the answer.
            voices, skipped = self._read_voices()
        with self._guard:
            self._inventory = voices
            self._inventory_skipped = skipped
        return voices

    def _read_voices(self) -> tuple[tuple[VoiceDescriptor, ...], int]:
        import subprocess  # local: the only stdout-capturing call in the package

        from .execution import child_environment

        try:
            completed = subprocess.run(  # noqa: S603 - argv list, never a shell
                [self._executable, "--voices"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                env=child_environment(),
                timeout=10.0,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError):
            return (), 0
        text = completed.stdout.decode("utf-8", errors="replace")
        voices: list[VoiceDescriptor] = []
        skipped = 0
        for line in text.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 4:
                continue
            tag, name = parts[1], parts[3]
            if not _SAFE_VOICE_ID.match(tag):
                skipped += 1
                continue
            language, locale = _locale_from_tag(tag)
            voices.append(VoiceDescriptor(
                voice_id=tag,
                provider_id="espeak-ng",
                name=name.replace("_", " "),
                language=language,
                locale=locale,
                # eSpeak NG's ``Pty`` column is a priority where *lower is
                # better*. Inverted into a 0..1 preference so the registry's
                # ``max`` picks what eSpeak NG itself would have picked.
                preference=_priority_to_preference(parts[0]),
                default=tag in ("en-gb", "en-us", "en"),
            ))
            if len(voices) >= MAX_INVENTORY:
                break
        return tuple(voices), skipped

    # ----------------------------------------------------------------- #

    def estimate(self, request: VoiceRequest) -> ResourceEstimate:
        # Roughly measured: the synthesiser's RSS on the reference target and a
        # WAV at the native rate. Deliberately round — an estimate presented to
        # four significant figures invites being read as a measurement.
        seconds = max(1.0, len(request.speech_text) / 14.0)
        return ResourceEstimate(
            memory_bytes=12 * 1024 * 1024,
            temporary_bytes=int(seconds * self.NATIVE_SAMPLE_RATE * 2) + 4096,
            cpu_share=0.25,
            expected_latency_seconds=0.2 + seconds * 0.05,
        )

    def _tuning(self, request: VoiceRequest, voice_id: str) -> tuple[list[str], list[str]]:
        """Arguments for one utterance, and every degradation they encode."""
        degradations: list[str] = []
        arguments = ["--stdin", "-v", voice_id]

        wpm = int(round(self.DEFAULT_WPM * request.speaking_rate))
        clamped = max(self.WPM_RANGE[0], min(self.WPM_RANGE[1], wpm))
        if clamped != wpm:
            degradations.append(
                f"speaking rate {request.speaking_rate} maps to {wpm} words per minute, "
                f"outside eSpeak NG's {self.WPM_RANGE[0]}-{self.WPM_RANGE[1]}; served at {clamped}"
            )
        arguments += ["-s", str(clamped)]

        if request.pitch is not None:
            # 0.5..2.0 across eSpeak NG's 0..99, with 1.0 at its default of 50.
            value = int(round(50 * request.pitch))
            bounded = max(self.PITCH_RANGE[0], min(self.PITCH_RANGE[1], value))
            if bounded != value:
                degradations.append(f"pitch {request.pitch} was clamped to eSpeak NG's {bounded}")
            arguments += ["-p", str(bounded)]

        amplitude = int(round(100 * request.volume))
        arguments += ["-a", str(max(self.AMPLITUDE_RANGE[0], min(self.AMPLITUDE_RANGE[1], amplitude)))]
        return arguments, degradations

    def synthesize(
        self,
        request: VoiceRequest,
        workspace: PrivateWorkspace,
        *,
        cancellation: CancellationSignal | None = None,
    ) -> SynthesisResult:
        declaration = self.declaration
        if not self.available:
            return SynthesisResult(
                request_id=request.request_id,
                provider_id=declaration.provider_id,
                implementation_id=declaration.implementation_id,
                voice_id="",
                succeeded=False,
                detail=self._resolution_error or "eSpeak NG is not installed",
            )
        voice_id = request.voice_id or _default_voice_id(self, request)
        if not voice_id:
            return SynthesisResult(
                request_id=request.request_id,
                provider_id=declaration.provider_id,
                implementation_id=declaration.implementation_id,
                voice_id="",
                succeeded=False,
                detail=f"eSpeak NG has no voice for {request.locale or request.language!r}",
            )

        target = workspace.file(f"{request.request_id}-espeak")
        arguments, degradations = self._tuning(request, voice_id)
        arguments += ["-w", str(target)]
        if request.sample_rate != self.NATIVE_SAMPLE_RATE:
            degradations.append(
                f"eSpeak NG produces {self.NATIVE_SAMPLE_RATE} Hz; {request.sample_rate} Hz was requested"
            )

        spec = CommandSpec(
            executable=self._executable,
            arguments=tuple(arguments),
            stdin_text=request.speech_text,
            text_argument_index=None,
            # A synthesiser writing to a file touches no audio device. Recorded
            # so a device loss during this phase is attributed to playback,
            # which is the only place it could have come from.
            touches_audio=False,
            timeout_seconds=_synthesis_timeout(request),
        )
        outcome = self._guarded(request, cancellation, spec)

        if outcome.cancelled:
            self._record(True)  # a cancellation is not a provider fault
            return SynthesisResult(
                request_id=request.request_id,
                provider_id=declaration.provider_id,
                implementation_id=declaration.implementation_id,
                voice_id=voice_id,
                succeeded=False,
                degradations=tuple(degradations),
                detail="synthesis was cancelled before it finished",
                outcome=outcome,
                synthesis_seconds=outcome.duration_seconds,
            )

        # The artifact, not the exit code. eSpeak NG exits 0 with no file both
        # when the input is empty and when the output path is unwritable; this
        # is the check that turns either into an honest failure.
        try:
            probe = probe_wav(target)
        except PcmError as exc:
            self._record(False)
            return SynthesisResult(
                request_id=request.request_id,
                provider_id=declaration.provider_id,
                implementation_id=declaration.implementation_id,
                voice_id=voice_id,
                succeeded=False,
                degradations=tuple(degradations),
                detail=(
                    f"eSpeak NG exited {outcome.exit_code} but produced no usable audio: {exc}"
                    + (f" ({outcome.stderr})" if outcome.stderr else "")
                ),
                outcome=outcome,
                synthesis_seconds=outcome.duration_seconds,
            )

        self._record(True)
        return SynthesisResult(
            request_id=request.request_id,
            provider_id=declaration.provider_id,
            implementation_id=declaration.implementation_id,
            voice_id=voice_id,
            succeeded=True,
            audio_path=str(target),
            audio_format="wav-pcm-s16le",
            sample_rate=probe.sample_rate,
            channels=probe.channels,
            frame_count=probe.frame_count,
            duration_seconds=probe.duration_seconds,
            synthesis_seconds=outcome.duration_seconds,
            degradations=tuple(degradations),
            detail="synthesised locally",
            outcome=outcome,
        )

    def stream(
        self,
        request: VoiceRequest,
        *,
        cancellation: CancellationSignal | None = None,
    ) -> StreamOutcome:
        """Speak through eSpeak NG's own audio output, producing no artifact.

        Reached when a request prefers streaming and the machine has no working
        playback backend of ours to hand a file to. The trade is recorded: no
        amplitude visemes, no pause, no resume.
        """
        declaration = self.declaration
        if not self.available:
            return StreamOutcome(
                request_id=request.request_id,
                provider_id=declaration.provider_id,
                implementation_id=declaration.implementation_id,
                voice_id="",
                succeeded=False,
                detail=self._resolution_error or "eSpeak NG is not installed",
            )
        voice_id = request.voice_id or _default_voice_id(self, request)
        arguments, degradations = self._tuning(request, voice_id or "en")
        degradations.append(
            "provider-owned playback: no amplitude visemes, no pause and no resume"
        )
        spec = CommandSpec(
            executable=self._executable,
            arguments=tuple(arguments),
            stdin_text=request.speech_text,
            touches_audio=True,
            timeout_seconds=_playback_timeout(request),
        )
        outcome = self._guarded(request, cancellation, spec)
        succeeded = outcome.succeeded
        self._record(succeeded or outcome.cancelled)
        return StreamOutcome(
            request_id=request.request_id,
            provider_id=declaration.provider_id,
            implementation_id=declaration.implementation_id,
            voice_id=voice_id,
            succeeded=succeeded,
            cancelled=outcome.cancelled,
            elapsed_seconds=outcome.duration_seconds,
            degradations=tuple(degradations),
            detail="spoken through eSpeak NG's own output" if succeeded else (
                outcome.stderr or f"eSpeak NG exited {outcome.exit_code}"
            ),
            outcome=outcome,
        )


def _priority_to_preference(raw: str) -> float:
    try:
        priority = int(raw)
    except (TypeError, ValueError):
        return 0.5
    # eSpeak NG uses 1..9 with 1 best. Mapped onto 0..1 with 1 -> 1.0.
    return max(0.0, min(1.0, (10 - max(1, min(9, priority))) / 9))


def _default_voice_id(provider: Any, request: VoiceRequest) -> str:
    locale = request.locale.lower()
    language = request.language.lower()
    voices = list(provider.inventory())
    for pool in (
        [item for item in voices if item.locale.lower() == locale],
        [item for item in voices if item.language.lower() == language],
    ):
        if not pool:
            continue
        default = [item for item in pool if item.default]
        chosen = default or pool
        return max(chosen, key=lambda item: (item.preference, item.voice_id)).voice_id
    return ""


def _synthesis_timeout(request: VoiceRequest) -> float:
    """A bound proportional to the text, floored and ceilinged.

    A fixed timeout is wrong in both directions: too short for a long caption on
    a slow machine, and far too generous for a five-word progress line, which is
    the case where a hung synthesiser should be noticed quickly.
    """
    return max(5.0, min(120.0, 5.0 + len(request.speech_text) / 40.0))


def _playback_timeout(request: VoiceRequest) -> float:
    """Longer than synthesis: this one has to wait for the speech to be heard."""
    return max(10.0, min(300.0, 10.0 + len(request.speech_text) / 6.0))


# --------------------------------------------------------------------------- #
# Speech Dispatcher
# --------------------------------------------------------------------------- #


class SpeechDispatcherProvider(_CommandProvider):
    """Speech Dispatcher through ``spd-say``: the platform's own speech service.

    Stream-only, and that is a property of Speech Dispatcher rather than a gap
    here. It owns the audio connection, applies the user's own configured voice
    and module, and maintains its own priority queue — which is why this adapter
    maps §7's ladder onto ``spd-say --priority`` rather than ignoring it. Two
    queues that disagree about what is urgent produce speech in an order neither
    intended.

    ``--wait`` is passed on every utterance. Without it ``spd-say`` returns as
    soon as the message is *accepted*, and a worker that treated acceptance as
    completion would advance to the next utterance while this one was still
    being spoken — the queue would run at the speed of the socket rather than
    the speed of speech.
    """

    executable_name = "spd-say"
    #: ``--pipe-mode`` keeps the utterance out of the process table and
    #: ``--wait`` makes the client block for the length of the speech. Without
    #: the second, ``spd-say`` returns as soon as the server has *accepted* the
    #: message, and every duration this runtime measures would be the latency of
    #: a socket write rather than the length of an utterance.
    required_arguments = ("--pipe-mode", "--wait")

    #: §7's ladder onto Speech Dispatcher's own five priorities. ``important``
    #: is the one that interrupts, which is why only the top two map to it.
    PRIORITY_MAP: Mapping[str, str] = {
        "critical_warning": "important",
        "approval_required": "important",
        "task_error": "message",
        "direct_user_response": "message",
        "task_result": "text",
        "progress_update": "progress",
        "decorative": "notification",
    }

    def __init__(self, *, resolver=None, version: str = "") -> None:
        super().__init__(resolver=resolver)
        self._version = version

    @property
    def declaration(self) -> ProviderDeclaration:
        voices = self.inventory()
        languages = tuple(sorted({item.language for item in voices})) or ("en",)
        return ProviderDeclaration(
            provider_id="speech-dispatcher",
            implementation_id=f"speech-dispatcher/{self._version}" if self._version
            else ("speech-dispatcher/spd-say" if self._executable else "speech-dispatcher/absent"),
            languages=languages,
            locales=tuple(sorted({item.locale for item in voices})),
            # It never hands us samples, so it declares no format and no rate.
            # Declaring one it cannot deliver would make the registry select it
            # for a request that needed an artifact.
            audio_formats=(),
            sample_rates=(),
            supports_synthesis=False,
            supports_streaming=True,
            supports_cancellation=True,
            rate_control=True,
            pitch_control=True,
            volume_control=True,
            local=True,
            cost_class="free",
            maximum_privacy_class="secret",
            requires_authentication=False,
            provides_phoneme_timing=False,
            provides_native_visemes=False,
            trusted_resolution=self._trusted,
        )

    def inventory(self) -> Sequence[VoiceDescriptor]:
        """Voices from ``spd-say --list-synthesis-voices``.

        The table is ``NAME LANGUAGE VARIANT``, right-aligned, and a name may
        contain spaces. Parsed from the *right* — the last two fields are the
        language and the variant, everything before is the name — because
        splitting from the left would put half a name into the language column
        for every voice whose name has a space in it.
        """
        with self._guard:
            if self._inventory is not None:
                return self._inventory
        voices: tuple[VoiceDescriptor, ...] = ()
        skipped = 0
        if self._executable:
            voices, skipped = self._read_voices()
        with self._guard:
            self._inventory = voices
            self._inventory_skipped = skipped
        return voices

    def _read_voices(self) -> tuple[tuple[VoiceDescriptor, ...], int]:
        import subprocess

        from .execution import child_environment

        try:
            completed = subprocess.run(  # noqa: S603 - argv list, never a shell
                [self._executable, "--list-synthesis-voices"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                env=child_environment(),
                timeout=15.0,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError):
            return (), 0
        if completed.returncode != 0:
            # A running Speech Dispatcher is needed to answer this. Its absence
            # is reported as an empty inventory, which makes the provider
            # unselectable — the honest outcome, rather than offering voices
            # that cannot be reached.
            return (), 0
        voices: list[VoiceDescriptor] = []
        skipped = 0
        for line in completed.stdout.decode("utf-8", errors="replace").splitlines():
            parts = line.split()
            if len(parts) < 3 or parts[0] == "NAME":
                continue
            variant, tag = parts[-1], parts[-2]
            name = " ".join(parts[:-2])
            identifier = name.replace(" ", "_")
            if not _SAFE_VOICE_ID.match(identifier) or not _SAFE_VOICE_ID.match(tag):
                skipped += 1
                continue
            language, locale = _locale_from_tag(tag)
            voices.append(VoiceDescriptor(
                voice_id=identifier,
                provider_id="speech-dispatcher",
                name=name,
                language=language,
                locale=locale,
                preference=0.6 if variant == "none" else 0.4,
                default=variant == "none",
            ))
            if len(voices) >= MAX_INVENTORY:
                break
        return tuple(voices), skipped

    def estimate(self, request: VoiceRequest) -> ResourceEstimate:
        return ResourceEstimate(
            # The server and its module are already running and are shared; what
            # this utterance adds is the client. Attributing the server's memory
            # to one utterance would make §24's table wrong by a factor of the
            # number of utterances.
            memory_bytes=4 * 1024 * 1024,
            temporary_bytes=0,
            cpu_share=0.1,
            expected_latency_seconds=0.3,
        )

    def synthesize(
        self,
        request: VoiceRequest,
        workspace: PrivateWorkspace,
        *,
        cancellation: CancellationSignal | None = None,
    ) -> SynthesisResult:
        """Refused, explicitly and always.

        The declaration says ``supports_synthesis=False`` and the registry will
        not select this provider for a synthesis request, so reaching here is a
        caller bypassing selection. Returning a failure rather than raising
        keeps the contract — a provider never raises at a caller who has to keep
        a task alive — while making the refusal unambiguous.
        """
        del workspace, cancellation
        declaration = self.declaration
        return SynthesisResult(
            request_id=request.request_id,
            provider_id=declaration.provider_id,
            implementation_id=declaration.implementation_id,
            voice_id="",
            succeeded=False,
            detail=(
                "Speech Dispatcher owns its own audio output and does not return samples; "
                "use the streaming path"
            ),
        )

    def stream(
        self,
        request: VoiceRequest,
        *,
        cancellation: CancellationSignal | None = None,
    ) -> StreamOutcome:
        declaration = self.declaration
        if not self.available:
            return StreamOutcome(
                request_id=request.request_id,
                provider_id=declaration.provider_id,
                implementation_id=declaration.implementation_id,
                voice_id="",
                succeeded=False,
                detail=self._resolution_error or "Speech Dispatcher's client is not installed",
            )

        degradations = [
            "provider-owned playback: no amplitude visemes, no pause and no resume"
        ]
        arguments = [
            "--wait",
            "--pipe-mode",
            "--application-name", "bunny-companion",
            "--priority", self.PRIORITY_MAP.get(request.priority.wire, "text"),
            "--language", request.language,
            "--rate", str(_percent(request.speaking_rate)),
            "--volume", str(_volume_percent(request.volume)),
        ]
        if request.pitch is not None:
            arguments += ["--pitch", str(_percent(request.pitch))]
        if request.voice_id:
            arguments += ["--synthesis-voice", request.voice_id]

        spec = CommandSpec(
            executable=self._executable,
            arguments=tuple(arguments),
            # Pipe mode: the utterance goes in on stdin and never appears in the
            # process table. ``spd-say`` echoes it to stdout, which the runner
            # sends to /dev/null.
            stdin_text=request.speech_text + "\n",
            text_argument_index=None,
            touches_audio=True,
            timeout_seconds=_playback_timeout(request),
        )
        outcome = self._guarded(request, cancellation, spec)
        succeeded = outcome.succeeded
        self._record(succeeded or outcome.cancelled)
        return StreamOutcome(
            request_id=request.request_id,
            provider_id=declaration.provider_id,
            implementation_id=declaration.implementation_id,
            voice_id=request.voice_id,
            succeeded=succeeded,
            cancelled=outcome.cancelled,
            elapsed_seconds=outcome.duration_seconds,
            degradations=tuple(degradations),
            detail="spoken through Speech Dispatcher" if succeeded else (
                outcome.stderr or f"spd-say exited {outcome.exit_code}"
            ),
            outcome=outcome,
        )

    def cancel(self, request_id: str) -> bool:
        """Stop this utterance, and tell the server to stop speaking it.

        Killing ``spd-say`` alone is not enough: the message has already been
        handed to the server, which will keep speaking it after its client dies.
        So the signal is raised *and* a ``--cancel`` client is run — the same
        escalation shape as terminate-then-kill, one layer up.
        """
        stopped = super().cancel(request_id)
        if self._executable:
            run_command(CommandSpec(
                executable=self._executable,
                arguments=("--cancel",),
                timeout_seconds=5.0,
                touches_audio=True,
            ))
        return stopped


def _percent(value: float) -> int:
    """A 0.25..4.0 multiplier onto Speech Dispatcher's -100..+100, 1.0 at zero."""
    if value >= 1.0:
        scaled = (value - 1.0) / 3.0 * 100.0
    else:
        scaled = (value - 1.0) / 0.75 * 100.0
    return int(max(-100, min(100, round(scaled))))


def _volume_percent(value: float) -> int:
    """0..1 onto -100..+100, with 1.0 the server's own default of zero."""
    return int(max(-100, min(100, round((value - 1.0) * 100))))


# --------------------------------------------------------------------------- #


def local_providers(*, resolver=None) -> ProviderRegistry:
    """Every local provider, in preference order.

    eSpeak NG first, and the reason is not audio quality — Speech Dispatcher
    usually *is* eSpeak NG underneath on a Linux desktop. It is that eSpeak NG
    hands us the samples, and the samples are what make amplitude visemes, a
    measured caption-to-audio offset, pause, resume and a mid-playback device
    change possible. §12's ladder therefore descends from "the provider that
    gives us the audio" to "the provider that keeps the audio" to captions.

    A provider whose program is absent is still constructed and still listed. It
    reports itself unavailable, which is what ``voice_health`` shows a user
    asking why nothing is speaking; omitting it would make an uninstalled
    synthesiser indistinguishable from one that was never supported.
    """
    return ProviderRegistry([
        EspeakNgProvider(resolver=resolver),
        SpeechDispatcherProvider(resolver=resolver),
    ])
