# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Capability-plan-bounded renderer selection and hysteretic degradation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from companion.presentation import PresentationRecommendation

from .package import ValidatedPackage


class Presentation(str, Enum):
    TEXT_ONLY = "text-only"
    STATIC_IMAGE = "static-image"
    ANIMATED_2D = "animated-2d"


_RANK = {Presentation.TEXT_ONLY: 0, Presentation.STATIC_IMAGE: 1, Presentation.ANIMATED_2D: 2}
_IMPLEMENTATIONS = {
    "text-only": Presentation.TEXT_ONLY,
    # The canonical projection has an audio-only rung this renderer does not:
    # audio is the voice adapter's business and draws nothing, so for the
    # *character* it is text-only. Mapping it upward to a static image would
    # draw a picture on a machine the runtime decided should not have one.
    "audio-only": Presentation.TEXT_ONLY,
    "static-avatar": Presentation.STATIC_IMAGE,
    "static-image": Presentation.STATIC_IMAGE,
    "animated-2d": Presentation.ANIMATED_2D,
    # A higher allowance authorises at most what this phase implements; it does
    # not make the unimplemented renderer exist. The canonical projection
    # already refuses to *select* these, so reaching them here means somebody
    # constructed a recommendation by hand — and the answer is still no.
    "lightweight-3d": Presentation.ANIMATED_2D,
    "full-3d": Presentation.ANIMATED_2D,
    "animated-3d": Presentation.ANIMATED_2D,
}


@dataclass(frozen=True)
class CapabilityPresentationPlan:
    plan_id: str
    requested: Presentation
    ceiling: Presentation
    action: str = "start"
    implementation_id: str = "animated-2d"
    reasons: tuple[str, ...] = ()

    @classmethod
    def from_recommendation(cls, recommendation: PresentationRecommendation) -> "CapabilityPresentationPlan":
        """Take the allowance the canonical runtime already decided.

        This is the *only* constructor, and it takes a
        :class:`companion.presentation.PresentationRecommendation` — the value
        the integration runtime produced by reading the capability runtime's own
        signals. §2 forbids the renderer recalculating hardware capability and
        §14 says to consume the existing effective presentation allowance; a
        constructor that re-read the capability execution plan would be doing
        the reading a second time, and two readings of one measurement
        eventually disagree.

        An earlier revision did exactly that: it parsed ``assessment.plan`` for
        a ``bunny.companion`` decision and mapped ``implementationId`` itself.
        It worked, and it was a second interpretation of the same source.
        """
        ceiling = _IMPLEMENTATIONS.get(recommendation.implementation, Presentation.TEXT_ONLY)
        reasons = tuple(recommendation.reasons)
        if recommendation.limited_by_implementation:
            reasons += (
                f"the machine would permit {recommendation.eligible}; this build implements "
                f"{recommendation.implementation} and claims nothing above it",
            )
        return cls(
            plan_id=recommendation.plan_id or "plan-unidentified",
            requested=ceiling,
            ceiling=ceiling,
            action="start",
            implementation_id=recommendation.implementation,
            reasons=reasons,
        )


@dataclass(frozen=True)
class RendererSignals:
    display_available: bool = True
    available_memory_bytes: int | None = None
    graphics_ready: bool = True
    gpu_available: bool = False
    cpu_pressure: bool = False
    memory_pressure: bool = False
    thermal_pressure: bool = False
    on_battery: bool = False
    battery_percent: float | None = None
    reduced_motion: bool = False
    no_animation: bool = False
    user_preference: Presentation | None = None
    foreground_workload_high: bool = False
    renderer_healthy: bool = True
    static_renderer_healthy: bool = True

    def __post_init__(self) -> None:
        if self.available_memory_bytes is not None and self.available_memory_bytes < 0:
            raise ValueError("available memory cannot be negative")
        if self.battery_percent is not None and not 0 <= self.battery_percent <= 100:
            raise ValueError("battery percentage is outside 0-100")


@dataclass(frozen=True)
class RendererDecision:
    requested: Presentation
    effective: Presentation
    frame_rate_cap: int
    reasons: tuple[str, ...]
    held_by_hysteresis: bool
    plan_id: str

    def to_json(self) -> dict[str, Any]:
        return {
            "requestedPresentation": self.requested.value,
            "effectivePresentation": self.effective.value,
            "frameRateCap": self.frame_rate_cap,
            "reasons": list(self.reasons),
            "heldByHysteresis": self.held_by_hysteresis,
            "planId": self.plan_id,
        }


@dataclass(frozen=True)
class RendererDegradationEvent:
    event_type: str
    code: str
    previous: Presentation
    current: Presentation
    explanation: str
    task_continues: bool = True
    frame_rate_cap: int | None = None

    def to_json(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "eventType": self.event_type,
            "code": self.code,
            "previousPresentation": self.previous.value,
            "effectivePresentation": self.current.value,
            "explanation": self.explanation,
            "taskContinues": self.task_continues,
        }
        if self.frame_rate_cap is not None:
            value["frameRateCap"] = self.frame_rate_cap
        return value


class AdaptiveRendererSelector:
    def __init__(self, *, recovery_samples: int = 3, recovery_delay_seconds: float = 2.0) -> None:
        if recovery_samples < 1 or recovery_delay_seconds < 0:
            raise ValueError("invalid renderer hysteresis policy")
        self.recovery_samples = recovery_samples
        self.recovery_delay_seconds = recovery_delay_seconds
        self.current: Presentation | None = None
        self._healthy_samples = 0
        self._last_degraded_at = float("-inf")
        self._throttle_signature: tuple[str, int] | None = None
        self.events: list[RendererDegradationEvent] = []

    def evaluate(
        self,
        plan: CapabilityPresentationPlan,
        package: ValidatedPackage,
        signals: RendererSignals,
        *,
        now: float,
    ) -> RendererDecision:
        requested = plan.ceiling
        reasons = [f"capability plan {plan.plan_id} permits at most {plan.ceiling.value}"]
        if package.manifest.presentation_type.value == "static-image":
            requested = Presentation.STATIC_IMAGE if _RANK[requested] >= 1 else Presentation.TEXT_ONLY
            reasons.append("the selected package is static-image")
        if signals.user_preference is not None and _RANK[signals.user_preference] < _RANK[requested]:
            requested = signals.user_preference
            reasons.append("the user's renderer preference is a stricter ceiling")
        target = requested
        frame_rate = min(60, max(1, int(package.manifest.frame_rate)))
        code = ""
        explanation = ""
        throttle_code = ""
        throttle_explanation = ""
        static_bytes = package.manifest.width * package.manifest.height * 4

        def degrade(to: Presentation, reason_code: str, reason: str) -> None:
            nonlocal target, code, explanation
            if _RANK[to] < _RANK[target]:
                target, code, explanation = to, reason_code, reason
                reasons.append(reason)

        def cap_frame_rate(maximum: int, reason_code: str, reason: str) -> None:
            nonlocal frame_rate, throttle_code, throttle_explanation
            previous_cap = frame_rate
            frame_rate = min(frame_rate, maximum)
            reasons.append(reason)
            if frame_rate < previous_cap:
                throttle_code = reason_code
                throttle_explanation = reason

        if not signals.display_available:
            degrade(Presentation.TEXT_ONLY, "display-unavailable", "no display is available; presentation is text-only")
        if not signals.static_renderer_healthy:
            degrade(Presentation.TEXT_ONLY, "static-renderer-failed", "the guaranteed static renderer failed")
        elif not signals.renderer_healthy:
            degrade(Presentation.STATIC_IMAGE, "renderer-failed", "the animated renderer failed; static fallback is active")
        if signals.reduced_motion or signals.no_animation:
            degrade(Presentation.STATIC_IMAGE, "reduced-motion", "animation is disabled by the accessibility preference")
        if not signals.graphics_ready:
            degrade(Presentation.STATIC_IMAGE, "graphics-not-ready", "graphics acceleration is not ready; a static image is used")
        elif target is Presentation.ANIMATED_2D and not signals.gpu_available:
            cap_frame_rate(
                30,
                "gpu-unavailable",
                "no usable GPU is reported; frame-sequence animation uses its CPU-safe 30 fps ceiling",
            )
        if signals.memory_pressure:
            degrade(Presentation.STATIC_IMAGE, "memory-pressure", "memory pressure disabled animation")
        if signals.available_memory_bytes is not None:
            if signals.available_memory_bytes < static_bytes * 2:
                degrade(Presentation.TEXT_ONLY, "static-memory-unavailable", "available memory cannot safely hold the decoded fallback image")
            elif signals.available_memory_bytes < int(package.manifest.memory_estimate_bytes * 1.25):
                degrade(Presentation.STATIC_IMAGE, "package-memory-budget", "the package's declared animation memory does not fit the current budget")
        if signals.on_battery and signals.battery_percent is not None and signals.battery_percent <= 10:
            degrade(Presentation.STATIC_IMAGE, "battery-critical", "critical battery level disabled animation")
        if signals.thermal_pressure:
            cap_frame_rate(15, "thermal-pressure", "thermal pressure capped animation at 15 fps")
        if signals.cpu_pressure:
            cap_frame_rate(20, "cpu-pressure", "CPU pressure capped animation at 20 fps")
        if signals.foreground_workload_high:
            cap_frame_rate(
                12,
                "foreground-workload",
                "the foreground workload capped animation at 12 fps",
            )

        held = False
        previous = self.current
        if previous is None:
            self.current = target
        elif _RANK[target] < _RANK[previous]:
            self.current = target
            self._healthy_samples = 0
            self._last_degraded_at = now
            self.events.append(RendererDegradationEvent(
                "renderer.degraded", code or "presentation-reduced", previous, target,
                explanation or "runtime conditions required a lower presentation",
            ))
        elif _RANK[target] > _RANK[previous]:
            self._healthy_samples += 1
            if self._healthy_samples >= self.recovery_samples and now - self._last_degraded_at >= self.recovery_delay_seconds:
                self.current = target
                self._healthy_samples = 0
                self.events.append(RendererDegradationEvent(
                    "renderer.recovered", "stable-recovery", previous, target,
                    "healthy conditions remained stable for the renderer hysteresis window",
                ))
            else:
                target = previous
                held = True
                reasons.append("recovery is held until the hysteresis window is stable")
        else:
            self._healthy_samples = 0
        effective = self.current or target
        if effective is Presentation.ANIMATED_2D and throttle_code:
            signature = (throttle_code, frame_rate)
            if signature != self._throttle_signature:
                self.events.append(RendererDegradationEvent(
                    "renderer.throttled",
                    throttle_code,
                    effective,
                    effective,
                    throttle_explanation,
                    True,
                    frame_rate,
                ))
            self._throttle_signature = signature
        else:
            self._throttle_signature = None
        return RendererDecision(requested, effective, frame_rate, tuple(reasons), held, plan.plan_id)
