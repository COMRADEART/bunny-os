# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Whether this machine can hear, told in the order the pieces can fail.

Speech input needs four things and they fail independently:

1. a **microphone** the capture backend can enumerate;
2. the **Vosk library**, importable;
3. a **model**, in one of the trusted directories;
4. a **recogniser that answers** — the library and the model, together, loading.

§9's rule is that the push-to-talk control communicates its unavailable state
rather than disappearing or failing on press, and that **typed input is
preserved in every case**. Both follow from reporting the four separately: a
control that knows it has a microphone and no model can say "speech recognition
needs a model" instead of "unavailable", and nothing in this module can turn the
text entry off because nothing in this module is consulted about it.

The last rule is the same as §8's: **no model is downloaded**. Vosk models are
tens to hundreds of megabytes and a first-run wizard that fetches one silently
has made a network decision for somebody who came here to be asked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

__all__ = ["SpeechSurvey", "MicrophoneFinding", "survey_speech"]


@dataclass(frozen=True)
class MicrophoneFinding:
    """One capture device the backend enumerated."""

    device_id: str
    backend_id: str
    name: str
    description: str = ""
    default: bool = False
    state: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "deviceId": self.device_id,
            "backendId": self.backend_id,
            "name": self.name,
            "description": self.description,
            "default": self.default,
            "state": self.state,
        }


@dataclass(frozen=True)
class SpeechSurvey:
    """The four layers, each with its own verdict."""

    microphones: tuple[MicrophoneFinding, ...] = ()
    capture_backend: str = ""
    capture_detail: str = ""
    library_present: bool = False
    library_detail: str = ""
    model_present: bool = False
    model_name: str = ""
    model_origin: str = ""
    model_bytes: int = 0
    recognizer_ready: bool = False
    recognizer_detail: str = ""
    languages: tuple[str, ...] = ()

    @property
    def microphone_present(self) -> bool:
        return bool(self.microphones)

    @property
    def available(self) -> bool:
        """Can this machine transcribe speech right now?

        All four layers. A machine with three of them has no speech recognition
        and saying otherwise would produce a push-to-talk button that fails when
        it is pressed — which §33 names as the thing not to do.
        """
        return self.microphone_present and self.recognizer_ready

    @property
    def push_to_talk_enabled(self) -> bool:
        return self.available

    @property
    def reason(self) -> str:
        """Why speech is unavailable, naming the first missing layer."""
        if self.available:
            return ""
        if not self.microphone_present:
            return self.capture_detail or "No microphone was found on this machine."
        if not self.library_present:
            return self.library_detail or "The Vosk speech-recognition library is not installed."
        if not self.model_present:
            return "No speech-recognition model is installed."
        return self.recognizer_detail or "The speech recogniser did not become ready."

    @property
    def remedy(self) -> str:
        """What the user can do, and what Bunny will not do for them."""
        if self.available:
            return (
                f"Push-to-talk is ready using {self.model_name or 'the installed model'}. "
                "The microphone opens only while the key is held."
            )
        if not self.microphone_present:
            return (
                "Connect a microphone and choose Check again. "
                "Typing works now and will keep working; speech is an addition to it."
            )
        if not self.library_present:
            return (
                "Install the vosk Python package to enable speech recognition, then choose "
                "Check again. Typing works without it."
            )
        if not self.model_present:
            return (
                "Place a Vosk model in one of the model directories to enable speech "
                "recognition. Bunny does not download recognition models for you. "
                "Typing works without one."
            )
        return (
            "Speech recognition is installed but did not start. Diagnostics records the reason. "
            "Typing works either way."
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "available": self.available,
            "pushToTalkEnabled": self.push_to_talk_enabled,
            "microphonePresent": self.microphone_present,
            "microphoneCount": len(self.microphones),
            "microphones": [device.to_json() for device in self.microphones],
            "captureBackend": self.capture_backend,
            "captureDetail": self.capture_detail,
            "libraryPresent": self.library_present,
            "libraryDetail": self.library_detail,
            "modelPresent": self.model_present,
            "modelName": self.model_name,
            "modelOrigin": self.model_origin,
            "modelBytes": self.model_bytes,
            "recognizerReady": self.recognizer_ready,
            "recognizerDetail": self.recognizer_detail,
            "languages": list(self.languages),
            "reason": self.reason,
            "remedy": self.remedy,
            "typedInputPreserved": True,
        }


def _microphones(backends: Sequence[Any]) -> tuple[tuple[MicrophoneFinding, ...], str, str]:
    findings: list[MicrophoneFinding] = []
    chosen = ""
    details: list[str] = []
    for backend in backends:
        backend_id = str(getattr(backend, "backend_id", "") or "")
        try:
            devices = backend.discover()
        except Exception as error:
            details.append(f"{backend_id}: {error}")
            continue
        for device in devices:
            findings.append(MicrophoneFinding(
                device_id=str(getattr(device, "device_id", "") or ""),
                backend_id=backend_id,
                name=str(getattr(device, "name", "") or ""),
                description=str(getattr(device, "description", "") or ""),
                default=bool(getattr(device, "default", False)),
                state=str(getattr(device, "state", "") or ""),
            ))
        if devices and not chosen:
            chosen = backend_id
        if len(findings) >= 32:
            break
    detail = (
        f"{len(findings)} capture device(s) from {chosen}" if findings
        else ("; ".join(details) or "no capture backend enumerated a device")
    )
    return tuple(findings), chosen, detail


def survey_speech(
    *,
    recognizers: Any = None,
    capture_backends: Sequence[Any] | None = None,
    monotonic: float = 0.0,
) -> SpeechSurvey:
    """Ask each of the four layers, catching failures at each one.

    Every call is guarded because this runs during onboarding: a machine with a
    hostile audio configuration must produce a *page* that says so, not a
    traceback in place of a wizard.
    """
    if capture_backends is None:
        try:
            from ..speech.capture import local_capture_backends

            capture_backends = local_capture_backends()
        except Exception as error:
            return SpeechSurvey(capture_detail=f"capture backends unavailable: {error}")
    microphones, backend_id, capture_detail = _microphones(capture_backends)

    if recognizers is None:
        try:
            from ..speech.recognizers import local_recognizers

            recognizers = local_recognizers()
        except Exception as error:
            return SpeechSurvey(
                microphones=microphones, capture_backend=backend_id, capture_detail=capture_detail,
                library_detail=f"the recogniser registry could not be built: {error}",
            )

    declaration: Any = None
    health: Any = None
    for recognizer in tuple(recognizers):
        try:
            candidate_health = recognizer.health(monotonic=monotonic, refresh=True)
            candidate_declaration = recognizer.declaration
        except Exception as error:
            health = None
            declaration = None
            capture_detail = capture_detail or str(error)
            continue
        declaration, health = candidate_declaration, candidate_health
        if getattr(candidate_health, "ready", False):
            break

    if declaration is None or health is None:
        return SpeechSurvey(
            microphones=microphones, capture_backend=backend_id, capture_detail=capture_detail,
            library_detail="no local recogniser reported a declaration",
        )

    implementation = str(getattr(declaration, "implementation_id", "") or "")
    # ``vosk/<version>+<model>`` — the two halves are exactly the two layers, and
    # ``no-model`` is the sentinel the recogniser uses when the library loaded
    # and nothing was found for it to load.
    library_present = implementation.startswith("vosk/") and "unknown" not in implementation.split("+")[0]
    model_name = implementation.split("+", 1)[1] if "+" in implementation else ""
    model_present = bool(model_name) and model_name != "no-model"
    detail = str(getattr(health, "detail", "") or "")
    if not library_present and "library is not importable" in detail:
        library_detail = detail
    elif library_present:
        library_detail = f"vosk {implementation.split('+')[0].removeprefix('vosk/')} is importable"
    else:
        library_detail = detail or "the vosk library did not report a version"

    estimate = getattr(declaration, "resource_estimate", None)
    return SpeechSurvey(
        microphones=microphones,
        capture_backend=backend_id,
        capture_detail=capture_detail,
        library_present=library_present,
        library_detail=library_detail,
        model_present=model_present,
        model_name=model_name if model_present else "",
        model_origin=str(getattr(declaration, "model_origin", "") or ""),
        model_bytes=max(0, int(getattr(estimate, "model_memory_bytes", 0) or 0)) if estimate else 0,
        recognizer_ready=bool(getattr(health, "ready", False)),
        recognizer_detail=detail,
        languages=tuple(str(item) for item in (getattr(declaration, "languages", ()) or ())),
    )
