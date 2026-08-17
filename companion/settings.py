# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The settings a person can change, in one document that survives a reboot.

Three preference types already existed — :class:`companion.presentation.
AccessibilityPreferences`, :class:`companion.voice.policy.VoicePreferences` and
:class:`companion.speech.policy.SpeechInputPreferences` — and each one was
constructed with its defaults at every start. Nothing wrote them down. A user
who turned the voice off turned it off until they logged out, which is not a
setting, and exit criterion 21 asks for settings that persist.

So this is the file, and it is one file rather than three because the thing that
has to survive a reboot is a *person's configuration*, not three subsystems'
opinions. The subsystem types stay exactly as they are: :meth:`Settings.
accessibility`, :meth:`Settings.voice` and :meth:`Settings.speech` project into
them, and nothing downstream of those projections knows this module exists.

Two rules the shape enforces:

**No credential is ever in here.** §29 says settings must not expose raw
credentials, and the way to hold that is not to review each write — it is to
have no field that could hold one. Remote providers are recorded as an *alias*
and a credential *reference*; the secret itself lives in Secret Service and is
resolved by :mod:`companion.agents.credentials`, which is the only code in this
project that ever holds one as a string. :func:`_refuse_secrets` is a second
line, not the first.

**A setting can only ever ask for less.** Every preference type in this codebase
holds that asymmetry — a preference may simplify the surface and may not raise
it above what the machine or the policy allows — and the settings document
inherits it by construction, because it produces those types rather than
replacing them. There is deliberately no ``force_3d`` and no
``allow_remote_without_approval``.

The cost ceiling is here rather than in the provider configuration for the same
reason the character policy is not in the character registry: a limit the user
sets is a different thing from a provider's declared price, and putting them in
one place means one of them eventually overwrites the other.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping

__all__ = [
    "SETTINGS_FILE_NAME",
    "SETTINGS_SCHEMA_VERSION",
    "AccessibilitySettings",
    "AiSettings",
    "CharacterSettings",
    "PrivacySettings",
    "Settings",
    "SettingsError",
    "SpeechInputSettings",
    "VoiceSettings",
    "load_settings",
    "save_settings",
]

SETTINGS_FILE_NAME = "settings.json"
SETTINGS_SCHEMA_VERSION = 1

_MAX_FILE_BYTES = 64 * 1024

# Provider-owned model identifiers accepted by the settings schema. This is a
# validation boundary, not a claim that every model is installed: Settings can
# retain an optional Kitten choice and the provider reports its availability.
VOICE_PROVIDER_MODELS: Mapping[str, tuple[str, ...]] = {
    "pocket": ("english",),
    "kitten": ("nano-int8", "nano", "micro", "mini"),
    "espeak-ng": (),
    "speech-dispatcher": (),
}

#: Key names that must never appear in this document at any depth. Checked on
#: every read and every write. A settings file that arrived with one of these is
#: refused rather than cleaned: something wrote a credential into a
#: world-readable-shaped place, and quietly removing it would hide that.
_FORBIDDEN_KEYS = frozenset({
    "apikey", "api_key", "token", "secret", "password", "passphrase",
    "credential", "bearer", "authorization", "cookie", "privatekey", "private_key",
})


class SettingsError(ValueError):
    """The settings document is not one this build will read or write."""


def _refuse_secrets(value: Any, path: str = "") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key).casefold().replace("-", "_")
            if name in _FORBIDDEN_KEYS or name.replace("_", "") in _FORBIDDEN_KEYS:
                raise SettingsError(
                    f"{path or 'settings'}.{key} looks like a credential; settings never hold one. "
                    "A remote provider is recorded as an alias and a Secret Service reference."
                )
            _refuse_secrets(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _refuse_secrets(item, f"{path}[{index}]")


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


#: The placement names this field accepts, which are exactly
#: :class:`companion.character.positioning.Placement`'s values. Imported lazily
#: inside the function below rather than at module import: ``settings`` is
#: loaded by the CLI and by headless clients that have no business importing the
#: character package's geometry.
_DOCK_VALUES = frozenset({
    "center-screen", "dock-left", "dock-right", "bottom-left", "bottom-right",
    "top-left", "top-right", "compact-floating", "user-dragged",
})

#: Names written by earlier builds, and what each means now. ``center`` was the
#: only one that named a position the engine could already reach; the two top
#: corners named positions it could not, which is why
#: :class:`companion.character.positioning.Placement` gained them rather than
#: this mapping quietly folding them onto a bottom corner.
_DOCK_ALIASES = {
    "center": "center-screen",
    "docked": "dock-right",
    "compact": "compact-floating",
}


def normalise_dock(value: str) -> str:
    """The canonical placement name for a stored ``dock``. Never raises.

    An unreadable value becomes the default rather than an error: this is on
    the path that opens the companion window, and a typo in a settings file
    should cost a person their chosen corner, not their companion.
    """
    text = str(value or "").strip()
    if text in _DOCK_VALUES:
        return text
    return _DOCK_ALIASES.get(text, "bottom-right")


@dataclass(frozen=True)
class CharacterSettings:
    """§29 Character: selection, renderer mode, scale, dock, animation level."""

    #: Empty means "whatever the default-character policy decided". A value here
    #: is a *user* selection and :mod:`companion.character.policy` will not
    #: replace it.
    package_id: str = ""
    #: ``auto`` lets capability decide, ``off`` refuses 3D on a machine that
    #: could do it. There is no ``on``: a preference that forced 3D onto a
    #: machine that cannot render it would be a setting that breaks the window.
    #:
    #: Superseded by :attr:`render_mode` and kept because settings files written
    #: before it exist on disk. It survives as a *veto* only — see
    #: :func:`companion.character.modes.mode_from_settings` for why that
    #: direction is the one that cannot surprise anyone.
    three_d: str = "auto"
    #: Which of the three companions the user asked for: ``prerendered``, ``2d``
    #: or ``3d``. Pre-rendered is the default and the cheapest; see
    #: :mod:`companion.character.modes`.
    render_mode: str = "prerendered"
    #: ``automatic``, ``low``, ``balanced`` or ``high``. A ceiling on effort
    #: rather than a renderer choice: ``low`` on 3D means a lower frame cap and
    #: quality rung, not a silent demotion to 2D. §10 keeps the two separate so
    #: that a person who chose 3D still gets 3D on a machine set to ``low``.
    performance: str = "automatic"
    scale: float = 1.0
    #: Where the character sits. Named positions rather than coordinates —
    #: §24 forbids relying on absolute coordinates across a monitor change.
    #:
    #: The vocabulary is :class:`companion.character.positioning.Placement`'s,
    #: which it had drifted from: this field accepted ``top-left``, ``top-right``
    #: and ``center``, none of which the placement engine could express, while
    #: the engine offered ``dock-left``, ``dock-right`` and ``compact-floating``,
    #: which this field rejected. Nothing consumed the setting at all, so the
    #: divergence had never been noticed. The old names are still accepted and
    #: normalised — see :data:`_DOCK_ALIASES` — because they are in settings
    #: files on disk.
    dock: str = "bottom-right"
    #: §6's "Hidden". Orthogonal to *where* the companion sits, so it is a flag
    #: rather than a placement: a user who hides the companion and later shows
    #: it again should get it back where they left it, not in a default corner.
    #:
    #: Never absolute. The attention model overrides it for a permission
    #: request, an error and a live microphone — see
    #: :data:`companion.character.attention._ALWAYS_VISIBLE`. Hiding is a
    #: preference about the *resting* companion, not a way to dismiss a question.
    visible: bool = True
    #: ``full``, ``reduced`` or ``none``.
    animation: str = "full"
    #: §10's "enable/disable idle animation". Off means the character holds its
    #: frame when nothing is happening, and the quiescence policy stops the
    #: timer sooner rather than later.
    idle_animation: bool = True
    #: §10's "enable/disable contextual reactions" — whether the character
    #: responds to the pointer and to ambient events at all.
    contextual_reactions: bool = True
    #: §10's "animation intensity", 0 to 1. Scales how far the character departs
    #: from a neutral pose; it never scales *expression*, so a character at 0 is
    #: still readable. Only the interactive renderer can honour a value between
    #: the ends — a frame sequence is authored at one intensity.
    animation_intensity: float = 1.0
    #: How much surface the *shown* companion takes: ``full``, ``compact`` or
    #: ``minimal``. This is the chrome-density axis the setup wizard offers as
    #: "companion mode" — a person's answer to "how much of my screen do I
    #: want this to take" — and until this field existed, ``compact`` and
    #: ``minimal`` had no persisted representation at all
    #: (installer/first_run/apply.py recorded them honestly as not applied).
    #:
    #: Deliberately three values, not the wizard's five. ``off`` is
    #: :attr:`visible` and ``text-only`` is the accessibility preference, both
    #: of which already exist and are independently meaningful; a five-valued
    #: field beside them would be a second authority over the same facts. The
    #: five-way answer is :meth:`Settings.presentation_mode`.
    #:
    #: Not to be confused with three neighbours that also say "mode" or
    #: "compact": :attr:`render_mode` (which of the three renderers),
    #: ``dock="compact"`` (a legacy alias for the ``compact-floating``
    #: placement), and the transient window shapes in
    #: :mod:`companion.presentation` (phase-derived, never persisted).
    companion_mode: str = "full"

    def __post_init__(self) -> None:
        if self.three_d not in ("auto", "off"):
            raise SettingsError("character.threeD is 'auto' or 'off'")
        if self.render_mode not in ("prerendered", "2d", "3d"):
            raise SettingsError("character.renderMode is 'prerendered', '2d' or '3d'")
        if self.performance not in ("automatic", "low", "balanced", "high"):
            raise SettingsError(
                "character.performance is 'automatic', 'low', 'balanced' or 'high'"
            )
        if self.dock not in _DOCK_VALUES and self.dock not in _DOCK_ALIASES:
            raise SettingsError(
                f"character.dock {self.dock!r} is not a named position; "
                f"one of {', '.join(sorted(_DOCK_VALUES))}"
            )
        if self.animation not in ("full", "reduced", "none"):
            raise SettingsError("character.animation is 'full', 'reduced' or 'none'")
        if self.companion_mode not in ("full", "compact", "minimal"):
            raise SettingsError(
                "character.companionMode is 'full', 'compact' or 'minimal'; "
                "'off' is character.visible and 'text-only' is "
                "accessibility.textOnly"
            )
        object.__setattr__(self, "scale", _clamp(self.scale, 0.5, 3.0))
        object.__setattr__(self, "animation_intensity", _clamp(self.animation_intensity, 0.0, 1.0))

    def mode(self) -> Any:
        """The :class:`companion.character.modes.RenderMode` this asks for."""
        from .character.modes import mode_from_settings

        return mode_from_settings(self.render_mode, three_d=self.three_d)

    def placement(self) -> Any:
        """The :class:`companion.character.positioning.Placement` this asks for."""
        from .character.positioning import Placement

        return Placement(normalise_dock(self.dock))


@dataclass(frozen=True)
class VoiceSettings:
    """§29 Voice: selection, rate, volume, off."""

    enabled: bool = True
    response_mode: str = "voice-only"
    provider_id: str = "pocket"
    model_id: str = ""
    voice_id: str = ""
    speaking_rate: float = 1.0
    volume: float = 1.0
    performance_mode: str = "automatic"

    def __post_init__(self) -> None:
        if self.response_mode not in ("voice-only", "all", "never"):
            raise SettingsError("voice.responseMode is 'voice-only', 'all' or 'never'")
        if self.provider_id not in VOICE_PROVIDER_MODELS:
            raise SettingsError("voice.providerId is a supported local TTS provider")
        if self.model_id and (
            len(self.model_id) > 64 or not re.match(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$", self.model_id)
        ):
            raise SettingsError("voice.modelId is an installed model id, never a path")
        if self.model_id and self.model_id not in VOICE_PROVIDER_MODELS[self.provider_id]:
            raise SettingsError(
                f"voice.modelId {self.model_id!r} is not a model declared by {self.provider_id!r}"
            )
        if self.voice_id and (
            len(self.voice_id) > 64 or not re.match(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$", self.voice_id)
        ):
            raise SettingsError("voice.voiceId is an installed voice id, never a path")
        if self.performance_mode not in ("automatic", "quality", "low-resource"):
            raise SettingsError("voice.performanceMode is 'automatic', 'quality' or 'low-resource'")
        object.__setattr__(self, "speaking_rate", _clamp(self.speaking_rate, 0.5, 2.0))
        object.__setattr__(self, "volume", _clamp(self.volume, 0.0, 1.0))


@dataclass(frozen=True)
class SpeechInputSettings:
    """§29 Speech input: device, shortcut, model, off."""

    enabled: bool = True
    device_id: str = ""
    #: The push-to-talk binding, as a GTK accelerator string. Recorded rather
    #: than enforced here: the window owns the binding and this is what it reads.
    shortcut: str = "<Super><Alt>space"
    model_id: str = ""
    language: str = "automatic"
    wake_word: str = "disabled"

    def __post_init__(self) -> None:
        if len(self.shortcut) > 64:
            raise SettingsError("speechInput.shortcut is too long to be an accelerator")
        if len(self.device_id) > 128:
            raise SettingsError("speechInput.deviceId is too long")
        if (
            len(self.model_id) > 128
            or "/" in self.model_id
            or "\\" in self.model_id
            or self.model_id in (".", "..")
        ):
            raise SettingsError("speechInput.modelId is a model name, never a path")
        if self.language not in ("automatic", "en"):
            raise SettingsError("speechInput.language is 'automatic' or 'en'")
        if self.wake_word != "disabled":
            raise SettingsError("speechInput.wakeWord remains 'disabled' in this milestone")


@dataclass(frozen=True)
class AiSettings:
    """§29 AI: preferred local provider, model, remote aliases, cost ceiling."""

    preferred_provider_id: str = ""
    preferred_model_id: str = ""
    #: Remote providers the user configured, by alias only. The endpoint and the
    #: credential reference live in the agent configuration; this records which
    #: of them the user has *chosen to allow*, which is a different question and
    #: the one §27's "remote AI off unless configured" turns on.
    allowed_remote_aliases: tuple[str, ...] = ()
    #: Integer cost units per day. Zero means "no remote spend at all", which is
    #: the default and is not the same as "no ceiling" — an absent ceiling is
    #: expressed by ``cost_ceiling_units = -1``.
    cost_ceiling_units: int = 0

    def __post_init__(self) -> None:
        if self.cost_ceiling_units < -1:
            raise SettingsError("ai.costCeilingUnits is -1 for unlimited, or a non-negative number")
        if len(self.allowed_remote_aliases) > 16:
            raise SettingsError("ai.allowedRemoteAliases holds at most 16 entries")
        for alias in self.allowed_remote_aliases:
            if not isinstance(alias, str) or not alias or len(alias) > 64:
                raise SettingsError("ai.allowedRemoteAliases entries are short non-empty strings")

    @property
    def remote_enabled(self) -> bool:
        return bool(self.allowed_remote_aliases)


@dataclass(frozen=True)
class PrivacySettings:
    """§29 Privacy: remote-transfer default, approval policy, clipboard, history."""

    #: The highest privacy class that may ever leave the machine. ``public`` is
    #: the Alpha default and the strictest useful value; the ceiling in
    #: :mod:`companion.privacy` caps it at ``internal`` regardless.
    remote_transfer_ceiling: str = "public"
    #: ``always`` is the only Alpha value. Present as a field so the setting
    #: exists and is visibly not adjustable rather than silently absent.
    desktop_action_approval: str = "always"
    #: Refuse to copy anything above this class to the clipboard.
    clipboard_ceiling: str = "internal"
    #: How many days of task history to keep. Zero keeps everything.
    history_retention_days: int = 0

    def __post_init__(self) -> None:
        from .privacy import DATA_CLASSES

        for name, value in (
            ("remoteTransferCeiling", self.remote_transfer_ceiling),
            ("clipboardCeiling", self.clipboard_ceiling),
        ):
            if value not in DATA_CLASSES:
                raise SettingsError(f"privacy.{name} {value!r} is not a data class")
        if self.desktop_action_approval != "always":
            raise SettingsError(
                "privacy.desktopActionApproval is 'always' in this release. Approval is not "
                "a preference; it is the mechanism the action broker is built on."
            )
        if not 0 <= self.history_retention_days <= 3650:
            raise SettingsError("privacy.historyRetentionDays is between 0 and 3650")


@dataclass(frozen=True)
class AccessibilitySettings:
    """§29 Accessibility: reduced motion, text-only, captions, UI scale."""

    reduced_motion: bool = False
    no_animation: bool = False
    high_contrast: bool = False
    text_only: bool = False
    captions_always: bool = True
    ui_scale: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "ui_scale", _clamp(self.ui_scale, 0.75, 3.0))


@dataclass(frozen=True)
class Settings:
    """Every user setting, and the projections the subsystems already take."""

    character: CharacterSettings = field(default_factory=CharacterSettings)
    voice: VoiceSettings = field(default_factory=VoiceSettings)
    speech_input: SpeechInputSettings = field(default_factory=SpeechInputSettings)
    ai: AiSettings = field(default_factory=AiSettings)
    privacy: PrivacySettings = field(default_factory=PrivacySettings)
    accessibility: AccessibilitySettings = field(default_factory=AccessibilitySettings)

    # -- projections ---------------------------------------------------------

    def accessibility_preferences(self) -> Any:
        """The type the presentation ladder and the window already read.

        Character animation and the accessibility motion settings both land
        here, and they combine by taking the *simpler* of the two. A user who
        set the character to ``none`` and left reduced motion off has still
        asked for no animation.
        """
        from .presentation import AccessibilityPreferences

        animation = self.character.animation
        return AccessibilityPreferences(
            reduced_motion=(
                self.accessibility.reduced_motion
                or animation in ("reduced", "none")
                or self.character.three_d == "off"
            ),
            no_animation=self.accessibility.no_animation or animation == "none",
            high_contrast=self.accessibility.high_contrast,
            text_scale=self.accessibility.ui_scale,
            captions_always=self.accessibility.captions_always,
            prefer_text_only=self.accessibility.text_only,
        )

    def voice_preferences(self) -> Any:
        from .voice.policy import VoicePreferences

        if self.voice.performance_mode == "low-resource":
            provider_id, model_id = "kitten", "nano-int8"
        elif self.voice.performance_mode == "quality":
            provider_id, model_id = "pocket", "english"
        else:
            provider_id, model_id = self.voice.provider_id, self.voice.model_id
        return VoicePreferences(
            enabled=(self.voice.enabled and self.voice.response_mode != "never"),
            response_mode=self.voice.response_mode,
            provider_id=provider_id,
            model_id=model_id,
            voice_id=self.voice.voice_id,
            speaking_rate=self.voice.speaking_rate,
            volume=self.voice.volume,
            performance_mode=self.voice.performance_mode,
        )

    def speech_preferences(self) -> Any:
        from .speech.policy import SpeechInputPreferences

        return SpeechInputPreferences(
            enabled=self.speech_input.enabled,
            input_device=self.speech_input.device_id,
            language="en",
            locale="en-US",
            model_id=self.speech_input.model_id,
        )

    def presentation_mode(self) -> str:
        """The five-way companion mode the setup wizard offers, resolved.

        ``off``, ``text-only``, ``full``, ``compact`` or ``minimal`` — the
        vocabulary of ``installer.setup_state.COMPANION_MODES`` and the
        shell's ``companionModes.js``. Three settings fields carry it:
        a hidden companion is ``off`` whatever its chrome level, the
        accessibility text-only preference overrides the chrome level (an
        accessibility preference may only ever simplify), and otherwise the
        answer is ``character.companionMode``. One resolution order, here,
        so no consumer invents its own.
        """
        if not self.character.visible:
            return "off"
        if self.accessibility.text_only:
            return "text-only"
        return self.character.companion_mode

    # -- serialisation -------------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": SETTINGS_SCHEMA_VERSION,
            "character": {
                "packageId": self.character.package_id,
                "threeD": self.character.three_d,
                "renderMode": self.character.render_mode,
                "performance": self.character.performance,
                "scale": self.character.scale,
                "dock": self.character.dock,
                "visible": self.character.visible,
                "animation": self.character.animation,
                "idleAnimation": self.character.idle_animation,
                "contextualReactions": self.character.contextual_reactions,
                "animationIntensity": self.character.animation_intensity,
                "companionMode": self.character.companion_mode,
            },
            "voice": {
                "enabled": self.voice.enabled,
                "responseMode": self.voice.response_mode,
                "providerId": self.voice.provider_id,
                "modelId": self.voice.model_id,
                "voiceId": self.voice.voice_id,
                "speakingRate": self.voice.speaking_rate,
                "volume": self.voice.volume,
                "performanceMode": self.voice.performance_mode,
            },
            "speechInput": {
                "enabled": self.speech_input.enabled,
                "deviceId": self.speech_input.device_id,
                "shortcut": self.speech_input.shortcut,
                "modelId": self.speech_input.model_id,
                "language": self.speech_input.language,
                "wakeWord": self.speech_input.wake_word,
            },
            "ai": {
                "preferredProviderId": self.ai.preferred_provider_id,
                "preferredModelId": self.ai.preferred_model_id,
                "allowedRemoteAliases": list(self.ai.allowed_remote_aliases),
                "costCeilingUnits": self.ai.cost_ceiling_units,
                "remoteEnabled": self.ai.remote_enabled,
            },
            "privacy": {
                "remoteTransferCeiling": self.privacy.remote_transfer_ceiling,
                "desktopActionApproval": self.privacy.desktop_action_approval,
                "clipboardCeiling": self.privacy.clipboard_ceiling,
                "historyRetentionDays": self.privacy.history_retention_days,
            },
            "accessibility": {
                "reducedMotion": self.accessibility.reduced_motion,
                "noAnimation": self.accessibility.no_animation,
                "highContrast": self.accessibility.high_contrast,
                "textOnly": self.accessibility.text_only,
                "captionsAlways": self.accessibility.captions_always,
                "uiScale": self.accessibility.ui_scale,
            },
            "containsCredentials": False,
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "Settings":
        """Build from a document. Unknown keys are ignored; bad values refuse.

        Ignoring unknown keys is what lets an older build read a newer file
        without losing the user's other settings; refusing a bad *value* is what
        stops a hand-edited file from producing a companion configured in a way
        no code path expects.
        """
        if not isinstance(value, Mapping):
            raise SettingsError("settings must be an object")
        version = value.get("schemaVersion")
        if version != SETTINGS_SCHEMA_VERSION:
            raise SettingsError(f"settings schemaVersion {version!r} is not supported")
        _refuse_secrets(value)

        def section(name: str) -> Mapping[str, Any]:
            item = value.get(name, {})
            return item if isinstance(item, Mapping) else {}

        character, voice = section("character"), section("voice")
        speech, ai = section("speechInput"), section("ai")
        privacy, access = section("privacy"), section("accessibility")

        def text(source: Mapping[str, Any], key: str, default: str = "") -> str:
            item = source.get(key, default)
            if not isinstance(item, str) or len(item) > 256:
                return default
            return item

        def flag(source: Mapping[str, Any], key: str, default: bool) -> bool:
            item = source.get(key, default)
            return item if isinstance(item, bool) else default

        def number(source: Mapping[str, Any], key: str, default: float) -> float:
            item = source.get(key, default)
            return float(item) if isinstance(item, (int, float)) and not isinstance(item, bool) else default

        aliases = ai.get("allowedRemoteAliases", [])
        return cls(
            character=CharacterSettings(
                package_id=text(character, "packageId"),
                three_d=text(character, "threeD", "auto"),
                # A file written before this key existed asks for pre-rendered,
                # which is the default *and* the cheapest — so an upgrade never
                # silently promotes a machine to a heavier renderer. A machine
                # that was deliberately put in 3D keeps it through
                # ``packageId``, which the character policy still honours.
                render_mode=text(character, "renderMode", "prerendered"),
                performance=text(character, "performance", "automatic"),
                scale=number(character, "scale", 1.0),
                dock=text(character, "dock", "bottom-right"),
                visible=flag(character, "visible", True),
                animation=text(character, "animation", "full"),
                idle_animation=flag(character, "idleAnimation", True),
                contextual_reactions=flag(character, "contextualReactions", True),
                animation_intensity=number(character, "animationIntensity", 1.0),
                # A file written before this key existed shows the full
                # companion, which is what every such desktop was already
                # showing — an upgrade never changes what is on screen.
                companion_mode=text(character, "companionMode", "full"),
            ),
            voice=VoiceSettings(
                enabled=flag(voice, "enabled", True),
                response_mode=text(voice, "responseMode", "voice-only"),
                provider_id=text(voice, "providerId", "pocket"),
                model_id=text(voice, "modelId"),
                voice_id=text(voice, "voiceId"),
                speaking_rate=number(voice, "speakingRate", 1.0),
                volume=number(voice, "volume", 1.0),
                performance_mode=text(voice, "performanceMode", "automatic"),
            ),
            speech_input=SpeechInputSettings(
                enabled=flag(speech, "enabled", True),
                device_id=text(speech, "deviceId"),
                shortcut=text(speech, "shortcut", "<Super><Alt>space"),
                model_id=text(speech, "modelId"),
                language=text(speech, "language", "automatic"),
                wake_word=text(speech, "wakeWord", "disabled"),
            ),
            ai=AiSettings(
                preferred_provider_id=text(ai, "preferredProviderId"),
                preferred_model_id=text(ai, "preferredModelId"),
                allowed_remote_aliases=tuple(
                    str(item) for item in (aliases if isinstance(aliases, list) else [])
                )[:16],
                cost_ceiling_units=int(number(ai, "costCeilingUnits", 0)),
            ),
            privacy=PrivacySettings(
                remote_transfer_ceiling=text(privacy, "remoteTransferCeiling", "public"),
                desktop_action_approval=text(privacy, "desktopActionApproval", "always"),
                clipboard_ceiling=text(privacy, "clipboardCeiling", "internal"),
                history_retention_days=int(number(privacy, "historyRetentionDays", 0)),
            ),
            accessibility=AccessibilitySettings(
                reduced_motion=flag(access, "reducedMotion", False),
                no_animation=flag(access, "noAnimation", False),
                high_contrast=flag(access, "highContrast", False),
                text_only=flag(access, "textOnly", False),
                captions_always=flag(access, "captionsAlways", True),
                ui_scale=number(access, "uiScale", 1.0),
            ),
        )


def settings_path(root: Path) -> Path:
    return Path(root) / SETTINGS_FILE_NAME


def load_settings(root: Path, *, strict: bool = False) -> Settings:
    """Read the settings, or the defaults.

    ``strict=False`` — the default — is for the login path: a settings file that
    cannot be parsed must not stop a companion starting, and defaults are a
    working configuration. ``strict=True`` is for the settings *editor*, which
    has to tell the user their file is broken rather than silently showing them
    defaults and then overwriting the file they were trying to fix.
    """
    path = settings_path(root)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return Settings()
    if len(raw.encode("utf-8")) > _MAX_FILE_BYTES:
        if strict:
            raise SettingsError(f"{path} is larger than {_MAX_FILE_BYTES} bytes")
        return Settings()
    try:
        return Settings.from_json(json.loads(raw))
    except (json.JSONDecodeError, UnicodeDecodeError, SettingsError, TypeError, ValueError):
        if strict:
            raise
        return Settings()


def save_settings(root: Path, settings: Settings) -> Path:
    """Write atomically, 0600, after refusing anything credential-shaped."""
    document = settings.to_json()
    _refuse_secrets(document)
    path = settings_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(document, indent=2, sort_keys=True) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=".settings-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return path


def update_settings(root: Path, section: str, values: Mapping[str, Any]) -> Settings:
    """Change one section and persist. The CLI's and the window's single write.

    Read-modify-write rather than a partial patch on disk, so that a settings
    file is always a complete, valid document — a partial write that produced a
    file missing a section would be read back as defaults for that section.
    """
    _refuse_secrets({section: values})
    current = load_settings(root)
    sections = {
        "character": (CharacterSettings, current.character),
        "voice": (VoiceSettings, current.voice),
        "speechInput": (SpeechInputSettings, current.speech_input),
        "ai": (AiSettings, current.ai),
        "privacy": (PrivacySettings, current.privacy),
        "accessibility": (AccessibilitySettings, current.accessibility),
    }
    if section not in sections:
        raise SettingsError(f"unknown settings section {section!r}; one of {sorted(sections)}")
    _, existing = sections[section]
    known = set(asdict(existing))
    unknown = set(values) - known
    if unknown:
        raise SettingsError(f"{section} has no field(s) {sorted(unknown)}; fields are {sorted(known)}")
    updated = replace(existing, **dict(values))
    attribute = {"speechInput": "speech_input"}.get(section, section)
    settings = replace(current, **{attribute: updated})
    save_settings(root, settings)
    return settings
