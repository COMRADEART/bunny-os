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
    LIGHTWEIGHT_3D = "lightweight-3d"
    FULL_3D = "full-3d"


_RANK = {
    Presentation.TEXT_ONLY: 0,
    Presentation.STATIC_IMAGE: 1,
    Presentation.ANIMATED_2D: 2,
    Presentation.LIGHTWEIGHT_3D: 3,
    Presentation.FULL_3D: 4,
}
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
    "lightweight-3d": Presentation.LIGHTWEIGHT_3D,
    "full-3d": Presentation.FULL_3D,
    # Still not a rung. ``animated-3d`` is a name that has appeared in
    # recommendations built by hand; there is no renderer behind it and the
    # honest ceiling for it is the highest thing that does exist below it.
    "animated-3d": Presentation.ANIMATED_2D,
}

#: The two 3D rungs, for the checks that treat them together.
THREE_D = (Presentation.LIGHTWEIGHT_3D, Presentation.FULL_3D)


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

    # -- the 3D rungs' own signals -----------------------------------------
    #: Whether a graphics context can be created at all here. Read from the
    #: environment once at start-up, never probed per frame.
    three_d_available: bool = False
    #: Whether the 3D renderer is currently working. False after a crash, a
    #: shader failure, an upload failure or a model that would not load.
    three_d_healthy: bool = True
    #: §23's context loss, distinct from a mere failure: everything the context
    #: held is already gone, so releasing is different and recovery is slower.
    gpu_context_lost: bool = False
    #: The 95th-percentile frame time observed at the current rung, or ``None``
    #: before enough frames exist to have one.
    frame_p95_ms: float | None = None
    #: True only after :class:`companion.character.three_d.budget.FrameHealth`
    #: has seen the ceiling exceeded for its sustained-sample count. A single
    #: slow frame must never reach this field.
    sustained_slow_frames: bool = False
    #: Dropped frames as a fraction of the frames that should have been drawn.
    dropped_frame_ratio: float | None = None
    #: Whether the graphics stack has the features the package requires.
    graphics_features_supported: bool = True
    #: Whether the selected package carries a validated model at all.
    package_supports_3d: bool = False
    #: Whether this client was given a graphics context provider at all. A
    #: machine may be able and the package willing, and the 3D rungs still
    #: unreachable — a headless or pre-3D client that was handed no provider
    #: has "nobody offered a way to draw in 3D" as its truth, and the gate
    #: below must read that before the renderer discovers it by raising.
    three_d_context_configured: bool = False
    #: What the validated model would hold on the GPU.
    model_gpu_bytes: int | None = None

    def __post_init__(self) -> None:
        if self.available_memory_bytes is not None and self.available_memory_bytes < 0:
            raise ValueError("available memory cannot be negative")
        if self.battery_percent is not None and not 0 <= self.battery_percent <= 100:
            raise ValueError("battery percentage is outside 0-100")
        if self.dropped_frame_ratio is not None and not 0 <= self.dropped_frame_ratio <= 1:
            raise ValueError("dropped-frame ratio must be normalized")


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
    def __init__(
        self,
        *,
        recovery_samples: int = 3,
        recovery_delay_seconds: float = 2.0,
        budget: Any = None,
    ) -> None:
        if recovery_samples < 1 or recovery_delay_seconds < 0:
            raise ValueError("invalid renderer hysteresis policy")
        from .three_d.budget import DEFAULT_BUDGET

        self.recovery_samples = recovery_samples
        self.recovery_delay_seconds = recovery_delay_seconds
        #: §21's thresholds. Configuration, not policy baked into this class —
        #: see :mod:`companion.character.three_d.budget`.
        self.budget = budget or DEFAULT_BUDGET
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
        if requested in THREE_D and not signals.package_supports_3d:
            # The allowance is for the machine; the package is what there is to
            # draw. A 2D character on a machine that could run 3D is drawn in
            # 2D, and that is not a degradation — nothing was lost.
            requested = Presentation.ANIMATED_2D
            reasons.append("the selected character package carries no validated 3D model")
        if requested in THREE_D and not signals.three_d_available:
            requested = Presentation.ANIMATED_2D
            reasons.append("this machine's graphics stack cannot provide a 3D context")
        if requested in THREE_D and not signals.three_d_context_configured:
            # Same shape as the two checks above, and for the same reason: a
            # client with no context provider cannot draw 3D no matter what the
            # machine could do, and saying so here lets the 2D chain serve the
            # request instead of the renderer discovering it by raising.
            requested = Presentation.ANIMATED_2D
            reasons.append("no graphics context provider is configured in this client")
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

        # §22's 3D triggers, applied before the rules that were already here so
        # that a 3D failure lands on animated-2D and is then subject to every
        # 2D rule as well. A machine that loses its GPU context *and* has no
        # memory ends up at the right rung in one pass rather than two.
        if target in THREE_D:
            if signals.gpu_context_lost:
                degrade(Presentation.ANIMATED_2D, "gpu-context-lost",
                        "the graphics context was lost; 2D presentation continues")
            elif not signals.three_d_healthy:
                degrade(Presentation.ANIMATED_2D, "renderer-3d-failed",
                        "the 3D renderer failed; 2D presentation continues")
            elif not signals.graphics_features_supported:
                degrade(Presentation.ANIMATED_2D, "graphics-feature-unsupported",
                        "this graphics stack lacks a feature the character model requires")
            if signals.on_battery and signals.battery_percent is not None and (
                signals.battery_percent < self.budget.battery_floor_percent
            ):
                degrade(Presentation.ANIMATED_2D, "battery-3d-floor",
                        f"the battery is below {self.budget.battery_floor_percent:g}%; 3D is not drawn")
        if target in THREE_D:
            level = target.value
            if signals.available_memory_bytes is not None and (
                signals.available_memory_bytes < self.budget.memory_floor(level)
            ):
                degrade(
                    Presentation.LIGHTWEIGHT_3D if target is Presentation.FULL_3D else Presentation.ANIMATED_2D,
                    "memory-below-3d-floor",
                    f"available memory is below the {level} floor",
                )
            if signals.model_gpu_bytes is not None and signals.model_gpu_bytes > self.budget.gpu_ceiling(level):
                degrade(
                    Presentation.LIGHTWEIGHT_3D if target is Presentation.FULL_3D else Presentation.ANIMATED_2D,
                    "model-above-gpu-ceiling",
                    f"the model needs more GPU memory than the {level} ceiling permits",
                )
            if signals.sustained_slow_frames:
                degrade(
                    Presentation.LIGHTWEIGHT_3D if target is Presentation.FULL_3D else Presentation.ANIMATED_2D,
                    "sustained-frame-time",
                    (
                        f"frame time stayed above the {level} ceiling of "
                        f"{self.budget.frame_ceiling(level):g} ms for "
                        f"{self.budget.sustained_samples} consecutive samples"
                    ),
                )
            if signals.dropped_frame_ratio is not None and (
                signals.dropped_frame_ratio > self.budget.dropped_frame_ratio
            ):
                degrade(
                    Presentation.LIGHTWEIGHT_3D if target is Presentation.FULL_3D else Presentation.ANIMATED_2D,
                    "dropped-frames",
                    f"{signals.dropped_frame_ratio:.0%} of frames were dropped at {level}",
                )
            if signals.thermal_pressure:
                degrade(Presentation.LIGHTWEIGHT_3D, "thermal-pressure-3d",
                        "thermal pressure reduced the 3D presentation")
            if signals.memory_pressure:
                degrade(Presentation.ANIMATED_2D, "memory-pressure-3d",
                        "memory pressure ended 3D presentation")
        if not signals.display_available:
            degrade(Presentation.TEXT_ONLY, "display-unavailable", "no display is available; presentation is text-only")
        if not signals.static_renderer_healthy:
            degrade(Presentation.TEXT_ONLY, "static-renderer-failed", "the guaranteed static renderer failed")
        elif not signals.renderer_healthy:
            degrade(Presentation.STATIC_IMAGE, "renderer-failed", "the animated renderer failed; static fallback is active")
        if signals.no_animation:
            degrade(Presentation.STATIC_IMAGE, "no-animation", "animation is disabled by the accessibility preference")
        elif signals.reduced_motion:
            if target in THREE_D:
                # §9's reduced motion is a *mode of the animation system*, not a
                # rung: the character still changes when the task changes, it
                # simply arrives without a crossfade and without procedural
                # movement. Dropping to a static image here would remove the
                # state information along with the motion, which is the opposite
                # of what the preference asks for.
                reasons.append(
                    "reduced motion is applied inside the 3D renderer: no crossfades, "
                    "no procedural movement, state changes still drawn"
                )
            else:
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
        if effective in THREE_D:
            # A 3D rung's frame rate comes from the budget rather than from the
            # package: ``declaredFrameRate`` describes a frame *sequence*, which
            # a skeletal renderer does not have. Accessibility and thermal caps
            # still apply on top, because they are ceilings rather than targets.
            frame_rate = min(frame_rate if throttle_code else 60, self.budget.target_fps(effective.value))
        if (effective in THREE_D or effective is Presentation.ANIMATED_2D) and throttle_code:
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
