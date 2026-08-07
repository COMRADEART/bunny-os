# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Blink, breathe, glance: bounded procedural life with no sensor behind it.

§13 draws a line this module is built around. The character may look towards the
speech bubble, towards the task panel, or slightly away while it thinks — and
every one of those is a *presentation* fact the renderer already holds. What it
may never do is find out where the user is. There is no camera here, no face
detection, no gaze estimation and no biometric anything; the attention target is
chosen from the same layout the bubble was placed with, which is a rectangle on
a screen rather than a person in a room.

§14's constraints are the other half, and they are what keeps "feels alive" from
becoming "wakes a laptop up":

* a **seed**, so a test gets the same blinks twice and a report can quote them;
* a **maximum frequency** per behaviour, enforced by the scheduler rather than
  hoped for by the random draw;
* **reduced-motion compatibility**, which here means blinks continue and motion
  stops — a blink is not decorative movement, it is what stops a face looking
  like a photograph;
* **suspension under battery or thermal pressure**, taken from the same signals
  the renderer ladder already reads;
* and **no queue**. There is no list of pending behaviours. Each one has a next
  time and that time is rewritten when it fires, so a suspended renderer wakes
  up owing nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Any, Mapping

from .animation import Pose, Quaternion
from .skeleton import SkeletonProfile

#: Blink timing, in seconds. Humans blink every 2–10 s; the closure itself is
#: about 120 ms and is drawn as a scale on the eye bones or a morph target.
BLINK_INTERVAL = (2.4, 7.5)
BLINK_SECONDS = 0.12

#: How often the eyes move, and how far. Radians: 0.12 is about seven degrees,
#: which reads as "looked at something" rather than "rolled its eyes".
SACCADE_INTERVAL = (1.1, 4.0)
SACCADE_RADIANS = 0.12

#: Head turns are slower, rarer and smaller in proportion.
HEAD_INTERVAL = (3.0, 9.0)
HEAD_RADIANS = 0.09

#: Breathing: one cycle every four seconds, moving the chest by half a percent.
BREATH_PERIOD = 4.0
BREATH_AMPLITUDE = 0.006

#: Posture shifts: rare, small, and the thing that stops a character looking
#: like a paused video.
POSTURE_INTERVAL = (11.0, 26.0)
POSTURE_RADIANS = 0.03

#: The hard ceiling §14 asks for: no procedural behaviour may fire more often
#: than this, whatever a configuration says.
MINIMUM_INTERVAL = 0.5

#: Where the character may look. Each is a direction in the character's own
#: space, not a point in the room.
ATTENTION_TARGETS: Mapping[str, tuple[float, float]] = {
    # (yaw, pitch) in radians. Positive yaw is the character's left.
    "forward": (0.0, 0.0),
    "bubble": (-0.16, 0.06),
    "task-panel": (0.22, -0.05),
    "listening": (-0.08, 0.04),
    "speaking": (0.0, 0.02),
    "thinking": (0.14, 0.10),
    "away": (0.20, -0.08),
}


def _quaternion_from_yaw_pitch(yaw: float, pitch: float) -> Quaternion:
    """Y then X, as a unit quaternion. Small angles, so order barely matters."""
    half_yaw, half_pitch = yaw * 0.5, pitch * 0.5
    sy, cy = math.sin(half_yaw), math.cos(half_yaw)
    sp, cp = math.sin(half_pitch), math.cos(half_pitch)
    return (cy * sp, sy * cp, -sy * sp, cy * cp)


@dataclass
class _Timer:
    """One behaviour's next firing time. There is no queue; this is the whole of it."""

    low: float
    high: float
    next_at: float = 0.0

    def due(self, now: float) -> bool:
        return now >= self.next_at

    def rearm(self, now: float, rng: random.Random) -> None:
        span = max(MINIMUM_INTERVAL, self.low), max(MINIMUM_INTERVAL, self.high)
        self.next_at = now + rng.uniform(*span)


class ProceduralBehaviour:
    """Blink, breathe, glance and hold posture, all bounded and all optional."""

    def __init__(
        self,
        skeleton: SkeletonProfile,
        *,
        seed: int | None = None,
        motion: str = "full",
        blink_morph: int | None = None,
    ) -> None:
        self.skeleton = skeleton
        self.motion = motion
        self.blink_morph = blink_morph
        self.rng = random.Random(seed if seed is not None else 0x42756E6E79)
        self.deterministic = seed is not None
        self.suspended = False
        self.suspend_reason = ""
        self.attention = "forward"
        self._blink = _Timer(*BLINK_INTERVAL)
        self._saccade = _Timer(*SACCADE_INTERVAL)
        self._head = _Timer(*HEAD_INTERVAL)
        self._posture = _Timer(*POSTURE_INTERVAL)
        self._blink_until = -1.0
        self._eye_offset = (0.0, 0.0)
        self._head_offset = (0.0, 0.0)
        self._posture_offset = (0.0, 0.0)
        self._started = 0.0
        self.blinks = 0
        self.saccades = 0
        self.head_turns = 0
        self.posture_shifts = 0

    def reset(self, *, now: float = 0.0) -> None:
        """Re-arm every timer from ``now``. Used on restart and on resume.

        Everything is re-armed rather than resumed, which is what makes §14's
        "no animation queue accumulation" true rather than intended: a renderer
        that was suspended for ten minutes has ten minutes of blinks it did not
        do, and the correct number of them to do now is zero.
        """
        self._started = now
        self._blink_until = -1.0
        for timer in (self._blink, self._saccade, self._head, self._posture):
            timer.rearm(now, self.rng)

    def suspend(self, reason: str) -> None:
        self.suspended = True
        self.suspend_reason = str(reason)

    def resume(self, *, now: float) -> None:
        if self.suspended:
            self.suspended = False
            self.suspend_reason = ""
            self.reset(now=now)

    def look_at(self, target: str) -> str:
        """Choose an attention target from the layout, never from a sensor."""
        name = str(target)
        if name not in ATTENTION_TARGETS:
            name = "forward"
        self.attention = name
        return name

    def attention_for_state(self, character_state: str, *, bubble_visible: bool) -> str:
        state = str(character_state)
        if state in {"waiting_for_approval", "blocked", "error", "warning"}:
            return self.look_at("task-panel")
        if bubble_visible and state in {"speaking", "presenting_result", "success", "waiting_for_user"}:
            return self.look_at("bubble")
        if state in {"listening", "transcribing"}:
            return self.look_at("listening")
        if state in {"planning", "understanding", "researching", "reviewing"}:
            return self.look_at("thinking")
        if state == "speaking":
            return self.look_at("speaking")
        return self.look_at("forward")

    # -- per-frame ---------------------------------------------------------

    def advance(self, now: float) -> None:
        if self.suspended or self.motion == "none":
            return
        if self._started <= 0:
            self.reset(now=now)
            return
        if self._blink.due(now):
            self._blink_until = now + BLINK_SECONDS
            self._blink.rearm(now, self.rng)
            self.blinks += 1
        if self.motion != "full":
            # Reduced motion keeps the blink and drops everything that moves.
            return
        if self._saccade.due(now):
            self._eye_offset = (
                self.rng.uniform(-SACCADE_RADIANS, SACCADE_RADIANS),
                self.rng.uniform(-SACCADE_RADIANS * 0.5, SACCADE_RADIANS * 0.5),
            )
            self._saccade.rearm(now, self.rng)
            self.saccades += 1
        if self._head.due(now):
            self._head_offset = (
                self.rng.uniform(-HEAD_RADIANS, HEAD_RADIANS),
                self.rng.uniform(-HEAD_RADIANS * 0.6, HEAD_RADIANS * 0.6),
            )
            self._head.rearm(now, self.rng)
            self.head_turns += 1
        if self._posture.due(now):
            self._posture_offset = (
                self.rng.uniform(-POSTURE_RADIANS, POSTURE_RADIANS),
                self.rng.uniform(-POSTURE_RADIANS * 0.4, POSTURE_RADIANS * 0.4),
            )
            self._posture.rearm(now, self.rng)
            self.posture_shifts += 1

    def blinking(self, now: float) -> bool:
        return now <= self._blink_until

    def pose(self, now: float) -> Pose:
        """The procedural contribution. Empty when suspended or motion is off."""
        pose = Pose()
        if self.suspended or self.motion == "none":
            return pose
        head = self.skeleton.index("head")
        neck = self.skeleton.index("neck")
        chest = self.skeleton.index("chest")
        spine = self.skeleton.index("spine")
        attention_yaw, attention_pitch = ATTENTION_TARGETS[self.attention]

        if self.motion == "full":
            head_yaw = attention_yaw * 0.6 + self._head_offset[0] + self._posture_offset[0]
            head_pitch = attention_pitch * 0.6 + self._head_offset[1]
            neck_yaw = attention_yaw * 0.4
            neck_pitch = attention_pitch * 0.4 + self._posture_offset[1]
        else:
            head_yaw = attention_yaw * 0.6
            head_pitch = attention_pitch * 0.6
            neck_yaw = attention_yaw * 0.4
            neck_pitch = attention_pitch * 0.4

        if head is not None:
            pose.rotations[head] = _quaternion_from_yaw_pitch(head_yaw, head_pitch)
        if neck is not None:
            pose.rotations[neck] = _quaternion_from_yaw_pitch(neck_yaw, neck_pitch)

        if self.motion == "full":
            phase = math.sin((now - self._started) * (2 * math.pi / BREATH_PERIOD))
            breath = 1.0 + BREATH_AMPLITUDE * phase
            if chest is not None:
                pose.scales[chest] = (1.0, breath, 1.0)
            if spine is not None:
                pose.rotations[spine] = _quaternion_from_yaw_pitch(
                    self._posture_offset[0] * 0.5, BREATH_AMPLITUDE * phase
                )

        if self.blinking(now):
            if self.blink_morph is not None:
                pose.weights[self.blink_morph] = 1.0
            else:
                for name in ("left_eye", "right_eye"):
                    eye = self.skeleton.index(name)
                    if eye is not None:
                        # No eyelid bone in the profile; a closed eye is drawn by
                        # flattening the eyeball, which is what a rig without
                        # blink morphs can honestly do.
                        pose.scales[eye] = (1.0, 0.08, 1.0)
        elif self.motion == "full":
            for name in ("left_eye", "right_eye"):
                eye = self.skeleton.index(name)
                if eye is not None:
                    pose.rotations[eye] = _quaternion_from_yaw_pitch(
                        attention_yaw * 0.4 + self._eye_offset[0],
                        attention_pitch * 0.4 + self._eye_offset[1],
                    )
        return pose

    def status(self, now: float) -> dict[str, Any]:
        return {
            "motion": self.motion,
            "suspended": self.suspended,
            "suspendReason": self.suspend_reason,
            "deterministic": self.deterministic,
            "attention": self.attention,
            "blinking": self.blinking(now),
            "blinks": self.blinks,
            "saccades": self.saccades,
            "headTurns": self.head_turns,
            "postureShifts": self.posture_shifts,
            "pendingBehaviours": 0,
        }


__all__ = [
    "ATTENTION_TARGETS",
    "BLINK_INTERVAL",
    "BLINK_SECONDS",
    "BREATH_PERIOD",
    "HEAD_INTERVAL",
    "MINIMUM_INTERVAL",
    "POSTURE_INTERVAL",
    "ProceduralBehaviour",
    "SACCADE_INTERVAL",
]
