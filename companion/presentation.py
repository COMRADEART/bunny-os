# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Capability-plan-bounded adaptive presentation and desktop window policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .model import CompanionPhase, Placement, PresentationKind

MIB = 1024 * 1024
GIB = 1024 * MIB

_LADDER = (
    PresentationKind.FULL_3D,
    PresentationKind.LIGHTWEIGHT_3D,
    PresentationKind.ANIMATED_2D,
    PresentationKind.STATIC_IMAGE,
    PresentationKind.AUDIO_ONLY,
    PresentationKind.TEXT_ONLY,
)
_RANK = {item: index for index, item in enumerate(_LADDER)}
_CAPABILITY_IMPLEMENTATIONS = {
    "animated-3d": PresentationKind.FULL_3D,
    "full-3d": PresentationKind.FULL_3D,
    "lightweight-3d": PresentationKind.LIGHTWEIGHT_3D,
    "animated-2d": PresentationKind.ANIMATED_2D,
    "static-avatar": PresentationKind.STATIC_IMAGE,
    "static-image": PresentationKind.STATIC_IMAGE,
    "audio-only": PresentationKind.AUDIO_ONLY,
    "text-only": PresentationKind.TEXT_ONLY,
}


@dataclass(frozen=True)
class CapabilityPresentationPlan:
    plan_id: str
    service_id: str
    action: str
    implementation_id: str | None
    presentation_ceiling: PresentationKind
    requires_approval: bool = False
    reasons: tuple[str, ...] = ()

    @classmethod
    def from_execution_plan(cls, document: Mapping[str, Any]) -> "CapabilityPresentationPlan":
        identity = document.get("identity") if isinstance(document.get("identity"), Mapping) else {}
        plan_id = str(identity.get("planId") or document.get("planId") or "plan-unidentified")
        decisions = document.get("decisions")
        if not isinstance(decisions, Sequence):
            raise ValueError("capability plan has no decisions")
        selected: Mapping[str, Any] | None = None
        for decision in decisions:
            if isinstance(decision, Mapping) and decision.get("serviceId") == "bunny.companion":
                selected = decision
                break
        if selected is None:
            raise ValueError("capability plan has no bunny.companion decision")
        implementation = selected.get("implementationId")
        ceiling = _CAPABILITY_IMPLEMENTATIONS.get(str(implementation), PresentationKind.TEXT_ONLY)
        reasons = tuple(
            str(item.get("code"))
            for item in selected.get("reasons", ())
            if isinstance(item, Mapping) and item.get("code")
        )
        return cls(
            plan_id=plan_id,
            service_id="bunny.companion",
            action=str(selected.get("action", "reject")),
            implementation_id=str(implementation) if implementation else None,
            presentation_ceiling=ceiling,
            requires_approval=bool(selected.get("requiresApproval", False)),
            reasons=reasons,
        )


@dataclass(frozen=True)
class PresentationSignals:
    available_memory_bytes: int | None = None
    gpu_ready: bool = False
    vram_available_bytes: int | None = None
    display_available: bool = True
    audio_output_available: bool = True
    on_battery: bool = False
    battery_percent: float | None = None
    thermal_pressure: bool = False
    memory_pressure: bool = False
    gpu_pressure: bool = False
    foreground_workload_high: bool = False
    headless: bool = False
    user_preference: PresentationKind | None = None
    reduced_motion: bool = False
    no_animation: bool = False
    high_contrast: bool = False
    text_scale: float = 1.0
    remote_rendering_requested: bool = False
    remote_rendering_permitted: bool = False

    def __post_init__(self) -> None:
        if self.available_memory_bytes is not None and self.available_memory_bytes < 0:
            raise ValueError("available memory cannot be negative")
        if self.vram_available_bytes is not None and self.vram_available_bytes < 0:
            raise ValueError("available VRAM cannot be negative")
        if self.battery_percent is not None and not 0.0 <= self.battery_percent <= 100.0:
            raise ValueError("battery percentage is invalid")
        if not 0.75 <= self.text_scale <= 3.0:
            raise ValueError("text scale is outside the supported range")


@dataclass(frozen=True)
class PresentationDecision:
    implementation: PresentationKind
    placement: Placement
    captions: bool
    visual_listening_indicator: bool
    visual_speaking_indicator: bool
    plan_id: str
    reasons: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "implementation": self.implementation.value,
            "placement": self.placement.value,
            "captions": self.captions,
            "visualListeningIndicator": self.visual_listening_indicator,
            "visualSpeakingIndicator": self.visual_speaking_indicator,
            "planId": self.plan_id,
            "reasons": list(self.reasons),
        }


def _degrade(current: PresentationKind, floor: PresentationKind) -> PresentationKind:
    return _LADDER[max(_RANK[current], _RANK[floor])]


def placement_for_phase(phase: CompanionPhase) -> Placement:
    if phase in {CompanionPhase.IDLE, CompanionPhase.GREETING, CompanionPhase.SLEEPING}:
        return Placement.CENTER
    if phase in {CompanionPhase.WAITING_FOR_APPROVAL, CompanionPhase.BLOCKED, CompanionPhase.ERROR}:
        return Placement.TASK_PANEL
    if phase in {CompanionPhase.SPEAKING, CompanionPhase.PRESENTING_RESULT, CompanionPhase.SUCCESS}:
        return Placement.SPEECH_BUBBLE
    if phase in {CompanionPhase.WORKING, CompanionPhase.PLANNING, CompanionPhase.REVIEWING}:
        return Placement.DOCKED
    return Placement.COMPACT


def select_presentation(
    plan: CapabilityPresentationPlan,
    signals: PresentationSignals,
    *,
    phase: CompanionPhase = CompanionPhase.IDLE,
) -> PresentationDecision:
    """Select at or below the implementation authorized by the capability plan."""
    selected = plan.presentation_ceiling
    reasons = [
        f"capability plan {plan.plan_id} permits at most {plan.presentation_ceiling.value}"
    ]
    if plan.action not in {"start_local", "start_remote"}:
        selected = PresentationKind.TEXT_ONLY
        reasons.append(f"capability action is {plan.action}; only task text remains")

    if signals.user_preference is not None:
        preferred = _degrade(selected, signals.user_preference)
        if preferred != selected:
            selected = preferred
            reasons.append("user preference selected a lighter presentation")

    no_display = signals.headless or not signals.display_available
    if no_display:
        fallback = PresentationKind.AUDIO_ONLY if signals.audio_output_available else PresentationKind.TEXT_ONLY
        selected = _degrade(selected, fallback)
        # A text-only plan must not be upgraded to audio by a missing display.
        if plan.presentation_ceiling == PresentationKind.TEXT_ONLY:
            selected = PresentationKind.TEXT_ONLY
        reasons.append("no display is available; visual rendering is disabled")

    memory = signals.available_memory_bytes
    if memory is not None:
        if memory < 96 * MIB:
            selected = PresentationKind.TEXT_ONLY
            reasons.append("less than 96 MiB is available; text-only is the safe floor")
        elif memory < 256 * MIB:
            fallback = PresentationKind.AUDIO_ONLY if no_display and signals.audio_output_available else PresentationKind.TEXT_ONLY
            selected = _degrade(selected, fallback)
            reasons.append("available memory is below the static-image budget")
        elif memory < 768 * MIB:
            selected = _degrade(selected, PresentationKind.STATIC_IMAGE)
            reasons.append("available memory limits presentation to a static image")
        elif memory < 2 * GIB:
            selected = _degrade(selected, PresentationKind.ANIMATED_2D)
            reasons.append("available memory limits presentation to animated 2D")

    if signals.memory_pressure:
        selected = _degrade(selected, PresentationKind.STATIC_IMAGE)
        reasons.append("memory pressure caused an immediate graceful degradation")
    if signals.gpu_pressure:
        selected = _degrade(selected, PresentationKind.ANIMATED_2D)
        reasons.append("GPU pressure removed 3D rendering")
    if selected in {PresentationKind.FULL_3D, PresentationKind.LIGHTWEIGHT_3D}:
        vram = signals.vram_available_bytes
        if not signals.gpu_ready or (vram is not None and vram < GIB):
            selected = _degrade(selected, PresentationKind.ANIMATED_2D)
            reasons.append("GPU readiness or VRAM is insufficient for 3D")
    if signals.thermal_pressure:
        selected = _degrade(selected, PresentationKind.STATIC_IMAGE)
        reasons.append("thermal pressure disabled decorative animation")
    if signals.on_battery and signals.battery_percent is not None and signals.battery_percent < 20:
        selected = _degrade(selected, PresentationKind.STATIC_IMAGE)
        reasons.append("low battery selected a static presentation")
    if signals.foreground_workload_high:
        selected = _degrade(selected, PresentationKind.STATIC_IMAGE)
        reasons.append("the foreground workload has priority over companion rendering")
    if signals.reduced_motion or signals.no_animation:
        selected = _degrade(selected, PresentationKind.STATIC_IMAGE)
        reasons.append("accessibility motion preference overrides animation")
    if signals.remote_rendering_requested and not signals.remote_rendering_permitted:
        selected = _degrade(selected, PresentationKind.STATIC_IMAGE)
        reasons.append("remote rendering was not permitted")
    if selected == PresentationKind.AUDIO_ONLY and not signals.audio_output_available:
        selected = PresentationKind.TEXT_ONLY
        reasons.append("audio output is unavailable; captions remain")

    return PresentationDecision(
        implementation=selected,
        placement=placement_for_phase(phase),
        # Captions remain in the typed stream even in audio-only/headless
        # presentation so a remote or later visual client can render them.
        captions=True,
        visual_listening_indicator=not no_display and selected != PresentationKind.AUDIO_ONLY,
        visual_speaking_indicator=not no_display and selected != PresentationKind.AUDIO_ONLY,
        plan_id=plan.plan_id,
        reasons=tuple(reasons),
    )


class AdaptivePresentationController:
    """Immediate degradation, delayed recovery to prevent renderer flapping."""

    def __init__(self, *, recovery_samples: int = 3) -> None:
        if recovery_samples < 1:
            raise ValueError("recovery sample count must be positive")
        self.recovery_samples = recovery_samples
        self.current: PresentationDecision | None = None
        self._candidate: PresentationKind | None = None
        self._healthy_samples = 0

    def update(
        self,
        plan: CapabilityPresentationPlan,
        signals: PresentationSignals,
        *,
        phase: CompanionPhase = CompanionPhase.IDLE,
    ) -> PresentationDecision:
        proposed = select_presentation(plan, signals, phase=phase)
        if self.current is None:
            self.current = proposed
            return proposed
        current_rank = _RANK[self.current.implementation]
        proposed_rank = _RANK[proposed.implementation]
        if proposed_rank >= current_rank:
            self.current = proposed
            self._candidate = None
            self._healthy_samples = 0
            return proposed
        if self._candidate != proposed.implementation:
            self._candidate = proposed.implementation
            self._healthy_samples = 1
        else:
            self._healthy_samples += 1
        if self._healthy_samples >= self.recovery_samples:
            self.current = proposed
            self._candidate = None
            self._healthy_samples = 0
            return proposed
        held = PresentationDecision(
            implementation=self.current.implementation,
            placement=proposed.placement,
            captions=self.current.captions,
            visual_listening_indicator=self.current.visual_listening_indicator,
            visual_speaking_indicator=self.current.visual_speaking_indicator,
            plan_id=proposed.plan_id,
            reasons=(*proposed.reasons, "renderer recovery is held by hysteresis"),
        )
        self.current = held
        return held


@dataclass(frozen=True)
class MonitorGeometry:
    monitor_id: str
    x: int
    y: int
    width: int
    height: int
    scale: float = 1.0


@dataclass(frozen=True)
class DesktopContext:
    monitors: tuple[MonitorGeometry, ...]
    active_monitor_id: str | None = None
    fullscreen_application: bool = False
    notifications_suppressed: bool = False
    active_application_bounds: tuple[int, int, int, int] | None = None


@dataclass(frozen=True)
class WindowPreferences:
    snap_position: str = "right"
    always_on_top: bool = False
    click_through_when_idle: bool = True
    hide_during_fullscreen: bool = False
    preserve_focus: bool = True

    def __post_init__(self) -> None:
        if self.snap_position not in {"left", "right", "top-left", "top-right", "bottom-left", "bottom-right"}:
            raise ValueError("window snap position is invalid")


@dataclass(frozen=True)
class WindowDirective:
    visible: bool
    placement: Placement
    monitor_id: str | None
    snap_position: str
    always_on_top: bool
    click_through: bool
    accept_focus: bool
    suppress_notification: bool
    compact_for_fullscreen: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "visible": self.visible,
            "placement": self.placement.value,
            "monitorId": self.monitor_id,
            "snapPosition": self.snap_position,
            "alwaysOnTop": self.always_on_top,
            "clickThrough": self.click_through,
            "acceptFocus": self.accept_focus,
            "suppressNotification": self.suppress_notification,
            "compactForFullscreen": self.compact_for_fullscreen,
        }


def window_directive(
    phase: CompanionPhase,
    preferences: WindowPreferences,
    context: DesktopContext,
) -> WindowDirective:
    approval = phase == CompanionPhase.WAITING_FOR_APPROVAL
    placement = placement_for_phase(phase)
    fullscreen = context.fullscreen_application and not approval
    if fullscreen:
        placement = Placement.COMPACT
    visible = not (fullscreen and preferences.hide_during_fullscreen)
    passive = phase in {CompanionPhase.IDLE, CompanionPhase.SLEEPING, CompanionPhase.WORKING}
    return WindowDirective(
        visible=visible,
        placement=placement,
        monitor_id=context.active_monitor_id or (context.monitors[0].monitor_id if context.monitors else None),
        snap_position=preferences.snap_position,
        always_on_top=preferences.always_on_top and not fullscreen,
        click_through=preferences.click_through_when_idle and passive and not approval,
        accept_focus=approval or not preferences.preserve_focus,
        suppress_notification=context.notifications_suppressed or fullscreen,
        compact_for_fullscreen=fullscreen,
    )
