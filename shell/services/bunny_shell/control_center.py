# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bunny / AI / Privacy Control Center modules.

Device panels still deep-link to GNOME. These three are Bunny-owned. Voice
stays off until wanted; AI is one local-first control; cloud_context is named
honestly and is not remote_dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .trust_copy import (
    ALLOWLISTED_CEILING_NOTE,
    CLIPBOARD_BLUETOOTH_NOTE,
    CLOUD_MEMORY_IS_OFF,
    CLOUD_MEMORY_STAYS_OFF,
    NETWORK_ALLOWLIST_NOTE,
    NETWORK_FULL_INTERNET,
    NETWORK_OFF,
    NO_ONLINE_MODELS_IS_LOCAL_ONLY,
)

CONTROL_CENTER_MODULES = ("bunny", "ai", "privacy")

CLOUD_CONTEXT_LABELS = {
    "none": "Off — saved memory stays on this computer",
    "minimized": "Minimized — only current-request fields may go online after Allow once",
}

AI_MODES = ("automatic", "local-only", "online-enhanced")
AI_MODE_LABELS = {
    "automatic": "Automatic",
    "local-only": "Local only",
    "online-enhanced": "Online enhanced",
}
AI_MODE_HINTS = {
    "automatic": (
        "Picks a local model from measured resources on this computer. "
        "Bunny does not go online because local is slower. An online answer still "
        "needs Allow once for this request."
    ),
    "local-only": (
        "Refuses hosted providers. Bunny will not show a Trust prompt to generate "
        "online. Typed Search still works."
    ),
    "online-enhanced": (
        "Still starts locally. Online generate is offered only when the router would "
        "escalate, and only after Allow once for this request — not always cloud."
    ),
}
_AI_WARNINGS = {
    "automatic": (
        "Automatic never goes online just because a local model is slower.",
        NO_ONLINE_MODELS_IS_LOCAL_ONLY,
    ),
    "local-only": (
        "Local only refuses hosted providers. Bunny will not ask to generate online.",
        NO_ONLINE_MODELS_IS_LOCAL_ONLY,
    ),
    "online-enhanced": (
        "Online enhanced is still local-first. Cloud generate needs Allow once "
        "for this request — not always cloud.",
        NO_ONLINE_MODELS_IS_LOCAL_ONLY,
    ),
}

ADVANCED_TITLE = "Advanced"
THROUGHPUT_NOT_MEASURED = "Not measured"
ACCELERATOR_UNKNOWN = "Unknown"
ACCELERATOR_ABSENT = "Absent"
ACCELERATOR_UNUSABLE = "Unusable"
MODEL_UNKNOWN = "Unknown"
WHY_THIS_MODEL_UNAVAILABLE = "Not available"
CONVERSATION_SUMMARY_UNWIRED = "Unwired"

_ACCELERATOR_LABELS = {
    "unknown": ACCELERATOR_UNKNOWN,
    "absent": ACCELERATOR_ABSENT,
    "none": ACCELERATOR_ABSENT,
    "unusable": ACCELERATOR_UNUSABLE,
    "present-unusable": ACCELERATOR_UNUSABLE,
    "not-usable": ACCELERATOR_UNUSABLE,
}


def accelerator_facing_label(value: Any = None) -> str:
    token = str(value or "unknown").strip().casefold().replace("_", "-")
    return _ACCELERATOR_LABELS.get(token, ACCELERATOR_UNKNOWN)


def throughput_facing_label(value: Any = None) -> str:
    if isinstance(value, bool) or value is None:
        return THROUGHPUT_NOT_MEASURED
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return f"{value} tok/s"
    if isinstance(value, float) and value >= 0 and value != float("inf") and value == value:
        if value.is_integer():
            return f"{int(value)} tok/s"
        return f"{value} tok/s"
    return THROUGHPUT_NOT_MEASURED


def model_facing_label(value: Any = None) -> str:
    text = str(value or "").strip()
    if not text or text.casefold() in {"automatic", "unknown", "none"}:
        return MODEL_UNKNOWN
    return text


def why_this_model_label(value: Any = None) -> str:
    text = str(value or "").strip()
    return text or WHY_THIS_MODEL_UNAVAILABLE


def resolve_ai_mode(values: Mapping[str, Any] | None = None, **kwargs: Any) -> str:
    settings = dict(values or {})
    settings.update(kwargs)
    if settings.get("localOnlyMode"):
        return "local-only"
    mode = str(settings.get("aiMode") or "automatic").strip().casefold()
    if mode in {"online-enhanced", "local-only"}:
        return mode
    return "automatic"


@dataclass(frozen=True)
class ControlRow:
    id: str
    label: str
    value: str
    hint: str = ""
    control: str = "label"


@dataclass(frozen=True)
class ControlModule:
    id: str
    title: str
    summary: str
    rows: tuple[ControlRow, ...]
    warnings: tuple[str, ...] = ()
    advanced: tuple[ControlRow, ...] = ()
    advanced_title: str = ""
    companion_required: bool = False


def bunny_module(values: Mapping[str, Any] | None = None, *, companion_hidden: bool = False) -> ControlModule:
    settings = values or {}
    return ControlModule(
        id="bunny",
        title="Bunny",
        summary="The companion is optional. Keyboard, dock, and Search still run the OS.",
        rows=(
            ControlRow(
                "launchBunnyAtLogin",
                "Open Bunny at login",
                "On" if settings.get("launchBunnyAtLogin") else "Off",
                control="toggle",
            ),
            ControlRow("theme", "Appearance", str(settings.get("theme", "system")), control="choice"),
            ControlRow(
                "companion",
                "Companion",
                "Hidden" if companion_hidden else "Visible",
                hint="Hiding the figure does not hide Search, Settings, or Trust.",
                control="toggle",
            ),
        ),
    )


def _ai_advanced_rows(settings: Mapping[str, Any]) -> tuple[ControlRow, ...]:
    return (
        ControlRow("modelId", "Model", model_facing_label(settings.get("modelId") or settings.get("adapter"))),
        ControlRow("adapter", "Adapter", model_facing_label(settings.get("adapter"))),
        ControlRow("throughput", "Throughput", throughput_facing_label(settings.get("tokensPerSecond"))),
        ControlRow("gpu", "GPU", accelerator_facing_label(settings.get("gpu"))),
        ControlRow("vram", "VRAM", accelerator_facing_label(settings.get("vram"))),
        ControlRow("npu", "NPU", accelerator_facing_label(settings.get("npu"))),
        ControlRow(
            "whyThisModel",
            "Why this model",
            why_this_model_label(settings.get("whyThisModel")),
        ),
    )


def _privacy_advanced_rows() -> tuple[ControlRow, ...]:
    return (
        ControlRow(
            "cloudContextSession",
            "Session memory online",
            "Off",
            hint="cloud_context does not send session memory online.",
        ),
        ControlRow(
            "cloudContextDurable",
            "Durable memory online",
            "Off",
            hint="Durable memory is never dumped online.",
        ),
        ControlRow(
            "conversationSummary",
            "Conversation summary",
            CONVERSATION_SUMMARY_UNWIRED,
            hint="Conversation summary is not wired.",
        ),
    )


def ai_module(values: Mapping[str, Any] | None = None) -> ControlModule:
    settings = values or {}
    mode = resolve_ai_mode(settings)
    return ControlModule(
        id="ai",
        title="AI",
        summary="One control. Automatic is the default. Answers start on this computer.",
        rows=(
            ControlRow(
                "aiMode",
                "AI mode",
                AI_MODE_LABELS[mode],
                hint=AI_MODE_HINTS[mode],
                control="choice",
            ),
            ControlRow(
                "voiceListening",
                "Voice listening",
                "Off until you ask",
                hint="Push-to-talk is Super+Alt+Space. Typed Search always works.",
            ),
            ControlRow(
                "voiceEnabled",
                "Spoken replies",
                "Available" if settings.get("voiceEnabled", True) else "Off",
                control="toggle",
            ),
            ControlRow(
                "microphoneEnabled",
                "Microphone permission",
                "Allowed when you talk" if settings.get("microphoneEnabled", True) else "Blocked",
                control="toggle",
            ),
        ),
        warnings=_AI_WARNINGS[mode],
        advanced=_ai_advanced_rows(settings),
        advanced_title=ADVANCED_TITLE,
    )


def privacy_module(
    values: Mapping[str, Any] | None = None, *, cloud_context: str = "none"
) -> ControlModule:
    settings = values or {}
    cloud = cloud_context if cloud_context in CLOUD_CONTEXT_LABELS else "none"
    warnings = [
        NETWORK_ALLOWLIST_NOTE,
        ALLOWLISTED_CEILING_NOTE,
        CLIPBOARD_BLUETOOTH_NOTE,
    ]
    if cloud == "none":
        warnings.append(CLOUD_MEMORY_IS_OFF)
    warnings.append(CLOUD_MEMORY_STAYS_OFF)
    return ControlModule(
        id="privacy",
        title="Privacy",
        summary="Cloud memory and a one-time online answer are two different consents.",
        rows=(
            ControlRow(
                "cloudContext",
                "Cloud memory",
                CLOUD_CONTEXT_LABELS[cloud],
                hint=CLOUD_MEMORY_IS_OFF if cloud == "none" else (
                    "Minimized still cannot send saved memory, session memory, or a conversation summary."
                ),
            ),
            ControlRow(
                "remoteDispatch",
                "Online for this request",
                "Allow once each time",
                hint=CLOUD_MEMORY_STAYS_OFF,
            ),
            ControlRow(
                "network",
                "Application network",
                f"{NETWORK_OFF} or {NETWORK_FULL_INTERNET}",
                hint=NETWORK_ALLOWLIST_NOTE,
            ),
            ControlRow(
                "appClipboard",
                "App clipboard",
                "Not mediated",
                hint=CLIPBOARD_BLUETOOTH_NOTE,
            ),
            ControlRow(
                "appBluetooth",
                "App Bluetooth",
                "Not mediated",
                hint=CLIPBOARD_BLUETOOTH_NOTE,
            ),
            ControlRow(
                "pluginNetworkDefault",
                "Plugin network",
                "Deny until asked" if settings.get("pluginNetworkDefault", "deny") == "deny" else "Ask",
                control="choice",
            ),
            ControlRow(
                "telemetryEnabled",
                "Telemetry",
                "On" if settings.get("telemetryEnabled") else "Off",
                hint="Off by default. Bunny does not phone home for analytics.",
            ),
            ControlRow(
                "clipboardHistory",
                "Clipboard history",
                "On" if settings.get("clipboardHistory") else "Off",
                hint="Off by default. There is no cloud clipboard. This is not application clipboard access.",
            ),
        ),
        warnings=tuple(warnings),
        advanced=_privacy_advanced_rows(),
        advanced_title=ADVANCED_TITLE,
    )


def control_center(
    values: Mapping[str, Any] | None = None,
    *,
    cloud_context: str = "none",
    companion_hidden: bool = False,
) -> dict[str, ControlModule]:
    settings = values or {}
    return {
        "bunny": bunny_module(settings, companion_hidden=companion_hidden),
        "ai": ai_module(settings),
        "privacy": privacy_module(settings, cloud_context=cloud_context),
    }
