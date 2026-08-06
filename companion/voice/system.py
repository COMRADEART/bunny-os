# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Speaking out loud, and the boundary around listening.

Two separate things live here and they are not symmetrical, which is the point.

**Speaking is implemented.** If the machine has a local system voice — Speech
Dispatcher, eSpeak NG, or the platform's own — the companion can read a caption
aloud. It is a convenience placed on top of the caption, never instead of it:
:data:`CAPTIONS_ARE_AUTHORITATIVE` is not a constant anybody reads, it is a
statement about how this module is used. Every call site produces the caption
first and speaks second, so a machine with no voice, a broken voice or a voice
somebody muted loses nothing but the sound.

**Listening is not implemented, and this module says so rather than pretending.**
:class:`MicrophoneBoundary` is the activation rule — explicit interaction, a
visible indicator raised before anything touches the device, no remote
transmission without approval, and nothing at all at service start. What it does
*not* contain is a speech recogniser, because there is no tested local
recogniser in this build. :class:`AbsentSpeechRecognition` refuses and explains;
it does not return an empty transcript, because an empty transcript is a
recogniser that heard nothing and this is a recogniser that does not exist.

Three rules the implementation follows without exception:

* **argument arrays, never a command string.** ``subprocess`` is given a list
  and never ``shell=True``. A caption is task-derived text and therefore
  attacker-influenced; the difference between a list and a string is the
  difference between a spoken sentence and a shell injection.
* **the text is bounded before it is spoken.** A caption is a summary and
  already short; the bound is here so that a caller which forgot cannot hand a
  megabyte to a synthesiser.
* **failure is data.** :meth:`SystemVoice.speak` returns an outcome and raises
  nothing a caller has to catch to keep a task alive.
"""

from __future__ import annotations

from dataclasses import dataclass
import shutil
import subprocess
import threading
from typing import Any, Callable, Protocol, Sequence

__all__ = [
    "AbsentSpeechRecognition",
    "MAX_SPEECH_CHARACTERS",
    "MicrophoneBoundary",
    "SpeechOutcome",
    "SpeechRecognition",
    "SystemVoice",
    "VOICE_CANDIDATES",
    "local_voice_available",
]

#: The longest utterance this will pass to a synthesiser. A caption is bounded
#: at :data:`companion.privacy.MAX_SUMMARY_LENGTH` already; this is the second
#: bound, at the process boundary, where it protects against a caller rather
#: than against a payload.
MAX_SPEECH_CHARACTERS = 4000

#: Local synthesisers, in preference order, with the argv shape each needs.
#: Every one of these is on-device. There is no entry for a network voice
#: service and there is no configuration that would add one: a companion that
#: could be made to read a user's task aloud *through a remote provider* would
#: be transmitting the task, and that decision belongs to the approval layer,
#: not to a voice setting.
VOICE_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("spd-say", "speech-dispatcher"),
    ("espeak-ng", "espeak-ng"),
    ("espeak", "espeak"),
    ("say", "platform-system-voice"),
)


def local_voice_available() -> bool:
    """Whether any local synthesiser exists. Probes ``PATH`` and nothing else."""
    return any(shutil.which(executable) for executable, _ in VOICE_CANDIDATES)


@dataclass(frozen=True)
class SpeechOutcome:
    """What one attempt to speak did. Never an exception a task must survive."""

    speech_id: str
    spoken: bool = False
    cancelled: bool = False
    detail: str = ""
    voice_id: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "speechId": self.speech_id,
            "spoken": self.spoken,
            "cancelled": self.cancelled,
            "detail": self.detail,
            "voiceId": self.voice_id,
        }


class SystemVoice:
    """The local system voice, if this machine has one.

    Constructing it on a machine with no synthesiser is not an error: the
    object exists, reports itself unavailable, and every call returns an outcome
    saying so. A caller therefore never has to branch on whether voice exists
    before deciding whether it may complete a task.
    """

    def __init__(self, *, which: Callable[[str], str | None] = shutil.which) -> None:
        self.executable = ""
        self.voice_id = ""
        for candidate, name in VOICE_CANDIDATES:
            resolved = which(candidate)
            if resolved:
                self.executable = resolved
                self.voice_id = name
                break
        self._guard = threading.RLock()
        self._running: dict[str, subprocess.Popen[bytes]] = {}

    @property
    def available(self) -> bool:
        return bool(self.executable)

    def describe(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "voiceId": self.voice_id,
            "local": True,
            "costClass": "free",
            "remoteTransmission": False,
            "voiceCloning": False,
            "captionsAuthoritative": True,
        }

    def argv(self, text: str, *, rate: float = 1.0) -> list[str]:
        """The exact argument list. Built here so a test can read it.

        ``--`` where the tool supports it, so a caption beginning with a hyphen
        is spoken rather than parsed as an option. The value never leaves this
        list and is never concatenated into a string.
        """
        if not self.executable:
            raise RuntimeError("there is no local system voice on this machine")
        if self.voice_id == "speech-dispatcher":
            adjustment = int(max(-100, min(100, (rate - 1.0) * 100)))
            return [self.executable, "--wait", "--rate", str(adjustment), "--", text]
        if self.voice_id in ("espeak-ng", "espeak"):
            words_per_minute = int(max(80, min(450, 175 * rate)))
            return [self.executable, "-s", str(words_per_minute), "--", text]
        words_per_minute = int(max(80, min(450, 180 * rate)))
        return [self.executable, "-r", str(words_per_minute), "--", text]

    def speak(self, speech_id: str, text: str, *, rate: float = 1.0, timeout: float = 60.0) -> SpeechOutcome:
        """Say something. Returns what happened; raises nothing for the caller."""
        body = " ".join(str(text).split())
        if not body:
            return SpeechOutcome(speech_id, detail="there was nothing to say", voice_id=self.voice_id)
        if len(body) > MAX_SPEECH_CHARACTERS:
            # Refused rather than shortened. A caption that was cut in half and
            # spoken is a companion telling the user something other than what
            # is on the screen beside it.
            return SpeechOutcome(
                speech_id,
                detail=(
                    f"the text is {len(body)} characters against a limit of "
                    f"{MAX_SPEECH_CHARACTERS} and was not spoken; the caption is unaffected"
                ),
                voice_id=self.voice_id,
            )
        if not self.available:
            return SpeechOutcome(
                speech_id,
                detail="no local system voice is installed; the caption is the whole of the output",
            )
        try:
            process = subprocess.Popen(  # noqa: S603 - argv list, never a shell
                self.argv(body, rate=rate),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        except OSError as exc:
            return SpeechOutcome(
                speech_id, detail=f"the local voice could not be started: {exc}", voice_id=self.voice_id
            )
        with self._guard:
            self._running[speech_id] = process
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5.0)
            code = -1
        finally:
            with self._guard:
                self._running.pop(speech_id, None)
        if code == 0:
            return SpeechOutcome(speech_id, spoken=True, detail="spoken locally", voice_id=self.voice_id)
        return SpeechOutcome(
            speech_id,
            cancelled=code < 0,
            detail=f"the local voice exited {code}; the caption is unaffected",
            voice_id=self.voice_id,
        )

    def cancel(self, speech_id: str) -> bool:
        """Stop one utterance. Returns whether there was one to stop."""
        with self._guard:
            process = self._running.get(speech_id)
            if process is None or process.poll() is not None:
                return False
            process.terminate()
        return True

    def cancel_all(self) -> tuple[str, ...]:
        with self._guard:
            identifiers = tuple(self._running)
        return tuple(item for item in identifiers if self.cancel(item))


# --------------------------------------------------------------------------- #
# Listening
# --------------------------------------------------------------------------- #


class SpeechRecognition(Protocol):
    """What a recogniser would have to be. Nothing here implements it."""

    provider_id: str
    local: bool

    def transcribe(self, interaction_id: str) -> str:
        """Return what was said, or raise. Must never return silence as text."""


@dataclass(frozen=True)
class AbsentSpeechRecognition:
    """The only recogniser this build has: one that refuses and explains.

    A placeholder that returned ``""`` would be indistinguishable from a working
    recogniser that heard nothing, and every consumer downstream — the caption,
    the task submission, the transcript in the record — would treat it as a
    real result. So this raises. §16 says a placeholder must not pretend speech
    recognition exists, and the way to not pretend is to fail loudly at the one
    place somebody would notice.
    """

    provider_id: str = "absent"
    local: bool = True

    def transcribe(self, interaction_id: str) -> str:
        raise NotImplementedError(
            "this build has no speech recogniser. The microphone boundary exists and is "
            "tested; the recognition behind it does not, and returning an empty transcript "
            "would be indistinguishable from having heard nothing."
        )


#: ``(listening, remote_audio)``, called whenever the indicator must change.
IndicatorCallback = Callable[[bool, bool], None]


class MicrophoneBoundary:
    """The only way a microphone may be turned on, and the rules for doing it.

    Every refusal here is one of §16's, and each is checked *before* the
    provider is touched:

    * nothing at service start — this object activates nothing on construction
      and there is no code path that calls :meth:`start` on its own;
    * no silent activation — the indicator is raised before the provider is
      called, and cleared in ``finally`` so a provider that throws cannot leave
      it lit or, worse, leave the device open with it dark;
    * explicit interaction — ``explicit_user_activation`` is a required
      argument with no default, so a caller cannot omit it;
    * continuous listening is separately enabled, because "always on" is a
      different decision from "on now";
    * remote audio needs approval, and the approval is the runtime's, not this
      object's.
    """

    def __init__(
        self,
        *,
        microphone_available: bool,
        indicator: IndicatorCallback,
    ) -> None:
        self.microphone_available = microphone_available
        self.indicator = indicator
        self._active: tuple[SpeechRecognition, str] | None = None
        self._guard = threading.RLock()

    @property
    def active(self) -> bool:
        with self._guard:
            return self._active is not None

    def describe(self) -> dict[str, Any]:
        return {
            "microphoneAvailable": self.microphone_available,
            "active": self.active,
            "activationPolicy": "explicit user interaction only",
            "silentActivationPossible": False,
            "recognitionImplemented": False,
            "remoteAudioRequiresApproval": True,
        }

    def start(
        self,
        provider: SpeechRecognition,
        interaction_id: str,
        *,
        explicit_user_activation: bool,
        mode: str = "push_to_talk",
        continuous_enabled: bool = False,
        remote_transmission_approved: bool = False,
    ) -> None:
        if not self.microphone_available:
            raise PermissionError("there is no microphone available, or it is disabled")
        if not explicit_user_activation:
            raise PermissionError(
                "the microphone is turned on by a person and by nothing else; "
                "this activation did not come from an explicit interaction"
            )
        if mode not in ("push_to_talk", "enabled"):
            raise PermissionError(f"unsupported microphone mode: {mode!r}")
        if mode == "enabled" and not continuous_enabled:
            raise PermissionError(
                "an always-listening mode was requested and has not been enabled"
            )
        if not getattr(provider, "local", False) and not remote_transmission_approved:
            raise PermissionError(
                "this recogniser would send audio off the device and no approval covers it"
            )
        with self._guard:
            if self._active is not None:
                raise RuntimeError("a microphone interaction is already running")
            # Raised before the provider can reach the device. A provider that
            # opened the microphone and then failed would otherwise have had it
            # open with no indicator showing.
            self.indicator(True, not getattr(provider, "local", False))
            self._active = (provider, interaction_id)

    def stop(self) -> bool:
        with self._guard:
            active = self._active
            self._active = None
        # Cleared unconditionally, including on the path where nothing was
        # running. An indicator that can only be cleared by a successful stop is
        # an indicator that stays lit after a failure.
        self.indicator(False, False)
        return active is not None

    def transcribe(
        self,
        provider: SpeechRecognition,
        interaction_id: str,
        *,
        explicit_user_activation: bool,
        **options: Any,
    ) -> str:
        """Start, listen, stop. The indicator is cleared however this ends."""
        self.start(
            provider, interaction_id,
            explicit_user_activation=explicit_user_activation, **options,
        )
        try:
            return provider.transcribe(interaction_id)
        finally:
            self.stop()


def speak_caption(
    voice: SystemVoice | None,
    speech_id: str,
    caption: str,
    *,
    enabled: bool = True,
) -> SpeechOutcome:
    """Read a caption aloud, if there is anything to read it with.

    The signature is the argument: the caption is already produced and already
    displayed by the time this is called, and everything this can return is
    information about the *sound*. A task's outcome does not appear in it and
    cannot be affected by it.
    """
    if not enabled:
        return SpeechOutcome(speech_id, detail="speech is turned off; the caption stands alone")
    if voice is None:
        return SpeechOutcome(speech_id, detail="no voice is configured; the caption stands alone")
    return voice.speak(speech_id, caption)


def redacted_argv(argv: Sequence[str]) -> list[str]:
    """An argv safe to write into a log or an event. The text is not included."""
    return [str(item) for item in argv[:-1]] + ["[caption]"] if argv else []
