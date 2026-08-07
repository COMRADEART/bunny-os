# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Speakers, microphones and whether either of them actually works.

§10 asks for validation of the speaker device, the microphone device, local TTS,
capture, and the coordination between output and input. This module reports the
first four and the fifth is a property of the runtime rather than a probe — the
speech and voice services already hold a lock against each other, and asserting
here that they do would be a second, weaker copy of that guarantee.

What "works" means, per layer, and why each one is asked separately:

``server``
    a sound server answered. ``pactl info`` failing is the single most common
    reason audio does not work, and it is invisible from the device list.
``devices``
    the server enumerated something. A running server with no sink is a real
    configuration — a container without the socket bound — and it produces
    silence rather than an error.
``voice``
    a text-to-speech provider is ready. Independent of the sink: a machine can
    have working speakers and no voice.

The speaker test is a *test*, not a probe: it plays a short sound and asks the
user whether they heard it. That is deliberate. Nothing this program can measure
distinguishes "the audio pipeline ran" from "the user heard something", and a
first run that concludes the speakers work because ``paplay`` exited zero is
exactly the class of claim this codebase keeps refusing to make.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

__all__ = ["AudioDeviceFinding", "AudioSurvey", "survey_audio"]


@dataclass(frozen=True)
class AudioDeviceFinding:
    """One output device, as the backend reported it."""

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
class AudioSurvey:
    """Output, input and voice, each with a verdict and a reason."""

    outputs: tuple[AudioDeviceFinding, ...] = ()
    output_backend: str = ""
    output_detail: str = ""
    inputs: tuple[AudioDeviceFinding, ...] = ()
    input_backend: str = ""
    input_detail: str = ""
    voice_available: bool = False
    voice_id: str = ""
    voice_detail: str = ""

    @property
    def output_available(self) -> bool:
        return bool(self.outputs)

    @property
    def input_available(self) -> bool:
        return bool(self.inputs)

    @property
    def can_speak(self) -> bool:
        """A voice *and* somewhere to play it. Either alone is silence."""
        return self.voice_available and self.output_available

    @property
    def summary(self) -> str:
        if self.can_speak:
            return (
                f"Bunny can speak through {self._default_name(self.outputs)}. "
                "Spoken output can be turned off at any time; captions always appear."
            )
        if self.output_available and not self.voice_available:
            return (
                "Speakers were found but no local voice is installed, so Bunny will not speak. "
                "Every reply is still shown as text."
            )
        if not self.output_available:
            return (
                "No audio output device was found. Bunny will not speak; "
                "every reply is shown as text and nothing else changes."
            )
        return "Audio is partly available. Text output is unaffected."

    @staticmethod
    def _default_name(devices: Sequence[AudioDeviceFinding]) -> str:
        for device in devices:
            if device.default:
                return device.description or device.name or device.device_id or "the default device"
        if devices:
            return devices[0].description or devices[0].name or "an audio device"
        return "no device"

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "outputAvailable": self.output_available,
            "outputBackend": self.output_backend,
            "outputDetail": self.output_detail,
            "outputs": [device.to_json() for device in self.outputs],
            "inputAvailable": self.input_available,
            "inputBackend": self.input_backend,
            "inputDetail": self.input_detail,
            "inputs": [device.to_json() for device in self.inputs],
            "voiceAvailable": self.voice_available,
            "voiceId": self.voice_id,
            "voiceDetail": self.voice_detail,
            "canSpeak": self.can_speak,
            "summary": self.summary,
        }


def _enumerate(backends: Sequence[Any]) -> tuple[tuple[AudioDeviceFinding, ...], str, str]:
    findings: list[AudioDeviceFinding] = []
    chosen = ""
    failures: list[str] = []
    for backend in backends:
        backend_id = str(getattr(backend, "backend_id", "") or "")
        try:
            devices = backend.discover()
        except Exception as error:
            failures.append(f"{backend_id}: {error}")
            continue
        for device in devices:
            findings.append(AudioDeviceFinding(
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
        f"{len(findings)} device(s) from {chosen}" if findings
        else ("; ".join(failures) or "no audio backend answered")
    )
    return tuple(findings), chosen, detail


def survey_audio(
    *,
    output_backends: Sequence[Any] | None = None,
    input_backends: Sequence[Any] | None = None,
    voice_providers: Any = None,
    monotonic: float = 0.0,
) -> AudioSurvey:
    """Enumerate output and input devices and find a voice. Never raises."""
    outputs, output_backend, output_detail = _side(output_backends, "voice.audio")
    inputs, input_backend, input_detail = _side(input_backends, "speech.capture")
    voice_available, voice_id, voice_detail = _voice(voice_providers, monotonic=monotonic)
    return AudioSurvey(
        outputs=outputs, output_backend=output_backend, output_detail=output_detail,
        inputs=inputs, input_backend=input_backend, input_detail=input_detail,
        voice_available=voice_available, voice_id=voice_id, voice_detail=voice_detail,
    )


def _side(backends: Sequence[Any] | None, module: str) -> tuple[tuple[AudioDeviceFinding, ...], str, str]:
    """One direction — playback or capture — discovered and enumerated.

    Both directions used to be written out inline, and both had the same bug:
    the ``except`` branch set a detail naming the import failure and then fell
    into the enumeration, which overwrote it with "no audio backend answered".
    A machine whose audio package was missing entirely reported the same
    sentence as a machine whose sound server was down, and the two need
    different remedies.
    """
    if backends is None:
        try:
            if module == "voice.audio":
                from ..voice.audio import local_backends as discover
            else:
                from ..speech.capture import local_capture_backends as discover

            backends = discover()
        except Exception as error:
            return (), "", f"the {module} backends could not be built: {error}"
    return _enumerate(backends)


def _voice(providers: Any, *, monotonic: float) -> tuple[bool, str, str]:
    if providers is None:
        try:
            from ..voice.providers import local_providers

            providers = local_providers()
        except Exception as error:
            return False, "", f"the voice provider registry could not be built: {error}"
    best_detail = ""
    for provider in tuple(providers):
        try:
            health = provider.health(monotonic=monotonic, refresh=True)
            declaration = provider.declaration
        except Exception as error:
            best_detail = best_detail or str(error)
            continue
        provider_id = str(getattr(declaration, "provider_id", "") or "")
        if getattr(health, "ready", False):
            return True, provider_id, str(getattr(health, "detail", "") or "ready")
        best_detail = best_detail or f"{provider_id}: {getattr(health, 'detail', '') or 'not ready'}"
    return False, "", best_detail or "no local voice provider is installed"
