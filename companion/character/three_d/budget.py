# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§21's levels and thresholds, as configuration rather than as product policy.

The instruction is explicit: "do not hard-code these thresholds as immutable
product policy; put them in capability configuration." So they are a frozen
dataclass with a named default and a :meth:`ThreeDBudget.from_mapping`
constructor that reads whatever the capability layer supplies, clamping each
value into a range this build can actually honour.

The distinction being preserved is between a *policy* and a *bound*. "Drop to
the lightweight rung when the 95th-percentile frame time exceeds 24 ms" is a
policy: a different machine, a different display, a different product decision
could reasonably choose 30 or 18, and the capability configuration is where that
belongs. "The frame-time threshold may not be zero or negative or larger than a
second" is a bound: no configuration makes those meaningful, and accepting one
would turn a policy knob into a way to disable degradation entirely.

The numbers below are the initial policy §21 sketches, not a claim about what is
right for every machine. What is measured on the reference host is in §35 of the
phase report; what a different machine should do is a configuration question.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Mapping

_MIB = 1024 * 1024

#: The five rungs, heaviest first — the same names
#: :data:`companion.presentation.PRESENTATION_KINDS` uses, minus ``audio-only``
#: which draws nothing and is therefore not a rendering level.
LEVELS: tuple[str, ...] = ("full-3d", "lightweight-3d", "animated-2d", "static-image", "text-only")


@dataclass(frozen=True)
class ThreeDBudget:
    """One machine's 3D thresholds. Every field is clamped on construction."""

    #: Frame-rate targets per rung.
    full_target_fps: int = 60
    lightweight_target_fps: int = 30

    #: The 95th-percentile frame time, in milliseconds, above which the full
    #: rung is considered not to be meeting its target. 24 ms is 41 fps: not
    #: 60, and comfortably not a stutter, so it is a threshold that fires on a
    #: machine that is genuinely struggling rather than on one bad frame.
    full_frame_ms_ceiling: float = 24.0
    #: The same for the lightweight rung. 42 ms is 24 fps.
    lightweight_frame_ms_ceiling: float = 42.0

    #: How many consecutive samples above a ceiling before the rung drops. §22
    #: asks for *sustained* high frame time; one slow frame is a compositor
    #: hiccup and three in a row is a machine.
    sustained_samples: int = 3

    #: Dropped frames as a fraction of frames that should have been drawn.
    dropped_frame_ratio: float = 0.25

    #: Available system memory below which each rung is refused.
    full_memory_floor_bytes: int = 1536 * _MIB
    lightweight_memory_floor_bytes: int = 768 * _MIB

    #: Estimated GPU memory a model may hold at each rung.
    full_gpu_bytes_ceiling: int = 192 * _MIB
    lightweight_gpu_bytes_ceiling: int = 96 * _MIB

    #: Battery percentage below which 3D is not drawn at all. Distinct from the
    #: existing 2D rule (10 %) because 3D costs more: a companion is not worth
    #: the last fifteen minutes of somebody's battery.
    battery_floor_percent: float = 25.0

    #: How long a degraded rung is held before recovery is even considered, and
    #: how many healthy samples are needed once it is. §22's hysteresis.
    recovery_hold_seconds: float = 20.0
    recovery_samples: int = 5

    #: Texture scale applied at the lightweight rung.
    lightweight_texture_scale: float = 0.5

    def __post_init__(self) -> None:
        bounds: Mapping[str, tuple[float, float]] = {
            "full_target_fps": (10, 240),
            "lightweight_target_fps": (5, 120),
            "full_frame_ms_ceiling": (4.0, 1000.0),
            "lightweight_frame_ms_ceiling": (4.0, 1000.0),
            "sustained_samples": (1, 120),
            "dropped_frame_ratio": (0.01, 1.0),
            "full_memory_floor_bytes": (64 * _MIB, 64 * 1024 * _MIB),
            "lightweight_memory_floor_bytes": (32 * _MIB, 64 * 1024 * _MIB),
            "full_gpu_bytes_ceiling": (16 * _MIB, 8192 * _MIB),
            "lightweight_gpu_bytes_ceiling": (8 * _MIB, 8192 * _MIB),
            "battery_floor_percent": (0.0, 100.0),
            "recovery_hold_seconds": (0.0, 3600.0),
            "recovery_samples": (1, 600),
            "lightweight_texture_scale": (0.1, 1.0),
        }
        for field in fields(self):
            low, high = bounds[field.name]
            value = getattr(self, field.name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"3D budget {field.name} must be a number")
            clamped = min(high, max(low, value))
            if isinstance(getattr(ThreeDBudget, "__dataclass_fields__")[field.name].default, int):
                clamped = int(clamped)
            object.__setattr__(self, field.name, clamped)
        if self.lightweight_frame_ms_ceiling < self.full_frame_ms_ceiling:
            raise ValueError("the lightweight frame-time ceiling cannot be stricter than the full one")
        if self.lightweight_memory_floor_bytes > self.full_memory_floor_bytes:
            raise ValueError("the lightweight memory floor cannot exceed the full one")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "ThreeDBudget":
        """Build from capability configuration. Unknown keys are refused.

        Refused rather than ignored: a configuration key that this build does
        not read is a setting somebody believes is in force, and silently
        dropping it is how a machine ends up running a policy nobody chose.
        """
        if not value:
            return cls()
        names = {field.name for field in fields(cls)}
        camel = {_camel(name): name for name in names}
        arguments: dict[str, Any] = {}
        unknown: list[str] = []
        for key, item in value.items():
            target = camel.get(str(key), str(key) if str(key) in names else None)
            if target is None:
                unknown.append(str(key))
                continue
            arguments[target] = item
        if unknown:
            raise ValueError("unknown 3D budget settings: " + ", ".join(sorted(unknown)))
        return cls(**arguments)

    def to_json(self) -> dict[str, Any]:
        return {_camel(field.name): getattr(self, field.name) for field in fields(self)}

    def frame_ceiling(self, level: str) -> float:
        return self.full_frame_ms_ceiling if level == "full-3d" else self.lightweight_frame_ms_ceiling

    def target_fps(self, level: str) -> int:
        return self.full_target_fps if level == "full-3d" else self.lightweight_target_fps

    def memory_floor(self, level: str) -> int:
        return (
            self.full_memory_floor_bytes if level == "full-3d"
            else self.lightweight_memory_floor_bytes
        )

    def gpu_ceiling(self, level: str) -> int:
        return (
            self.full_gpu_bytes_ceiling if level == "full-3d"
            else self.lightweight_gpu_bytes_ceiling
        )


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.title() for part in rest)


#: What a machine gets when the capability layer says nothing.
DEFAULT_BUDGET = ThreeDBudget()


class FrameHealth:
    """Sustained-slowness tracking. A counter, so one bad frame is not a verdict."""

    def __init__(self, budget: ThreeDBudget = DEFAULT_BUDGET) -> None:
        self.budget = budget
        self.slow_samples = 0
        self.healthy_samples = 0
        self.last_p95_ms: float | None = None

    def observe(self, p95_ms: float | None, level: str) -> bool:
        """Record one sample. Returns whether the rung is sustainedly too slow."""
        self.last_p95_ms = p95_ms
        if p95_ms is None:
            return False
        if p95_ms > self.budget.frame_ceiling(level):
            self.slow_samples += 1
            self.healthy_samples = 0
        else:
            self.slow_samples = 0
            self.healthy_samples += 1
        return self.slow_samples >= self.budget.sustained_samples

    def recovered(self) -> bool:
        return self.healthy_samples >= self.budget.recovery_samples

    def reset(self) -> None:
        self.slow_samples = 0
        self.healthy_samples = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "slowSamples": self.slow_samples,
            "healthySamples": self.healthy_samples,
            "lastP95Ms": self.last_p95_ms,
            "sustainedThreshold": self.budget.sustained_samples,
        }


__all__ = ["DEFAULT_BUDGET", "FrameHealth", "LEVELS", "ThreeDBudget"]
