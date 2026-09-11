# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bunny-owned Settings pages: companion, AI & Models, Privacy.

AI chrome reuses the Phase 2 Control Center contract. Personality is
presentation only — it cannot name a vendor or change routing.
"""

from __future__ import annotations

from typing import Any, Mapping

from .control_center import (
    ADVANCED_TITLE,
    AI_MODE_LABELS,
    ControlModule,
    ControlRow,
    ai_module,
    privacy_module,
    resolve_ai_mode,
)
from .trust_copy import NO_ONLINE_MODELS_IS_LOCAL_ONLY

PERSONALITY_CHOICES = ("bunny", "focused", "playful")
PERSONALITY_LABELS = {
    "bunny": "Bunny — warm and calm",
    "focused": "Focused — shorter answers",
    "playful": "Playful — lighter tone",
}
#: D8: a personality may not evoke a third-party model or vendor.
PERSONALITY_FORBIDDEN = frozenset({
    "openai", "anthropic", "claude", "gpt", "chatgpt", "gemini", "llama",
    "mistral", "grok", "copilot", "siri", "alexa", "bard", "chatgpt4",
})
PROACTIVITY_CHOICES = ("off", "gentle")
PROACTIVITY_LABELS = {
    "off": "Off — wait until asked",
    "gentle": "Gentle — may offer, never act",
}
ANIMATION_LABELS = {"full": "Full", "reduced": "Reduced", "none": "None"}


def normalise_personality(value: Any = None) -> str:
    token = str(value or "bunny").strip().casefold().replace(" ", "")
    if token in PERSONALITY_FORBIDDEN:
        return "bunny"
    if token in PERSONALITY_CHOICES:
        return token
    return "bunny"


def normalise_proactivity(value: Any = None) -> str:
    token = str(value or "off").strip().casefold()
    return token if token in PROACTIVITY_CHOICES else "off"


def personality_may_not_route(value: Any = None) -> bool:
    """True when the stored personality is presentation-only (the only legal case)."""
    token = str(value or "bunny").strip().casefold().replace(" ", "")
    return token not in PERSONALITY_FORBIDDEN


def bunny_companion_module(
    values: Mapping[str, Any] | None = None,
    *,
    companion_hidden: bool = False,
) -> ControlModule:
    settings = dict(values or {})
    personality = normalise_personality(settings.get("personality"))
    proactivity = normalise_proactivity(settings.get("proactivity"))
    dock = str(settings.get("dock") or settings.get("companionDock") or "bottom-right")
    scale = settings.get("scale", settings.get("companionScale", 1.0))
    try:
        scale_label = f"{float(scale):g}×"
    except (TypeError, ValueError):
        scale_label = "1×"
    intensity = settings.get("animationIntensity", settings.get("animation_intensity", 1.0))
    try:
        intensity_pct = int(round(float(intensity) * 100)) if float(intensity) <= 1 else int(intensity)
    except (TypeError, ValueError):
        intensity_pct = 100
    animation = str(settings.get("animation") or "full")
    interaction = settings.get("contextualReactions", settings.get("interaction", True))
    visible = False if companion_hidden else bool(settings.get("visible", True))
    mode = str(settings.get("companionMode") or settings.get("companion_mode") or "full")
    voice_on = bool(settings.get("voiceEnabled", True))
    return ControlModule(
        id="bunny",
        title="Bunny",
        summary="How Bunny looks and behaves. Hide the figure and the OS still works.",
        rows=(
            ControlRow(
                "visible",
                "Companion",
                "Hidden" if not visible else "Visible",
                hint="Hiding the figure does not hide Search, Settings, or Trust.",
                control="toggle",
            ),
            ControlRow(
                "character",
                "Character",
                str(settings.get("packageId") or settings.get("package_id") or "Bunny"),
                hint="One character. A missing 3D asset falls back to the vector.",
            ),
            ControlRow(
                "personality",
                "Personality",
                PERSONALITY_LABELS[personality],
                hint="Tone only. Personality cannot pick a model, a provider, or a permission.",
                control="choice",
            ),
            ControlRow(
                "voiceEnabled",
                "Voice",
                "Spoken replies" if voice_on else "Off",
                hint="Off until you want them. Push-to-talk is Super+Alt+Space. Typed Search always works.",
                control="toggle",
            ),
            ControlRow(
                "animation",
                "Animation",
                ANIMATION_LABELS.get(animation, "Full"),
                control="choice",
            ),
            ControlRow(
                "animationIntensity",
                "Animation intensity",
                f"{max(0, min(100, intensity_pct))}%",
                hint="How far poses travel. Expression stays readable at 0%.",
                control="slider",
            ),
            ControlRow(
                "dock",
                "Position",
                dock.replace("-", " "),
                hint="Named corners, not pixel coordinates. Default is bottom right.",
                control="choice",
            ),
            ControlRow(
                "scale",
                "Size",
                f"{mode} · {scale_label}",
                hint="Full, compact, or minimal chrome. Scale is 0.5× to 3×.",
                control="choice",
            ),
            ControlRow(
                "interaction",
                "Interaction",
                "Reacts to pointer and ambient events" if interaction else "Still",
                control="toggle",
            ),
            ControlRow(
                "proactivity",
                "Proactivity",
                PROACTIVITY_LABELS[proactivity],
                hint="Gentle may offer. It never acts, never grants, and never goes online by itself.",
                control="choice",
            ),
            ControlRow(
                "memory",
                "Memory",
                "Working only until you turn more on",
                hint="Session, durable, and cloud memory stay in Privacy. Defaults are off.",
            ),
            ControlRow(
                "aiMode",
                "Local / online AI",
                AI_MODE_LABELS[resolve_ai_mode(settings)],
                hint="Open AI & Models to change this. No online models ever is Local only.",
            ),
            ControlRow(
                "privacy",
                "Privacy",
                "Two consents",
                hint="Cloud memory is not Online for this request. Open Privacy to change either.",
            ),
        ),
        warnings=(
            "Personality is presentation. It cannot change routing or permissions.",
            NO_ONLINE_MODELS_IS_LOCAL_ONLY,
        ),
        companion_required=False,
    )


def ai_models_module(values: Mapping[str, Any] | None = None) -> ControlModule:
    module = ai_module(values)
    return ControlModule(
        id="ai-models",
        title="AI & Models",
        summary=module.summary,
        rows=module.rows,
        warnings=module.warnings,
        advanced=module.advanced,
        advanced_title=module.advanced_title or ADVANCED_TITLE,
        companion_required=False,
    )


def settings_privacy_module(
    values: Mapping[str, Any] | None = None, *, cloud_context: str = "none"
) -> ControlModule:
    module = privacy_module(values, cloud_context=cloud_context)
    memory_row = ControlRow(
        "localMemory",
        "Memory on this computer",
        "Working only",
        hint="Session and durable memory stay off until you turn them on. Cloud memory is a separate consent.",
    )
    return ControlModule(
        id="privacy",
        title=module.title,
        summary=module.summary,
        rows=module.rows + (memory_row,),
        warnings=tuple(module.warnings) + (NO_ONLINE_MODELS_IS_LOCAL_ONLY,),
        advanced=module.advanced,
        advanced_title=module.advanced_title or ADVANCED_TITLE,
        companion_required=False,
    )


def bunny_settings_pages(
    values: Mapping[str, Any] | None = None,
    *,
    cloud_context: str = "none",
    companion_hidden: bool = False,
) -> dict[str, ControlModule]:
    settings = values or {}
    return {
        "bunny": bunny_companion_module(settings, companion_hidden=companion_hidden),
        "ai-models": ai_models_module(settings),
        "privacy": settings_privacy_module(settings, cloud_context=cloud_context),
    }
