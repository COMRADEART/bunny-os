# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Expressions and mouth shapes: §11 and §12, sharing one degradation rule.

Both features answer the same question — "how do I move this character's face?"
— and both must answer it for a package that has none of the optional equipment.
So both go through :class:`FaceRig`, which resolves each request down a fixed
three-rung ladder and records which rung it landed on:

1. **Morph targets**, when the package's map names targets the model carries.
2. **Bone controls**, when it does not but a jaw or mouth bone exists.
3. **Neutral**, when neither. Nothing fails, nothing is faked, and the
   resolution says ``neutral-fallback`` so a diagnostic can tell the difference
   between a character that is calm and a character that cannot smile.

§12's other half — request identity, revision matching, ordering, cancellation,
drift and worker restarts — is **not** implemented here and must not be. It
already exists in :class:`companion.character.speech_link.VisemeLink`, which the
voice runtime phase built and validated. What this module receives is a shape
that link already admitted. Building a second timeline here is exactly the
"second lip-sync timeline" §12 forbids, and it would also be a second place for
a stale frame to get in.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

from companion.character.lipsync import MouthShape

from .animation import Pose
from .errors import ModelSchemaError
from .glb import ValidatedModel
from .skeleton import SkeletonProfile

#: §11's expressions. Closed: an expression outside this set cannot be selected,
#: so a package cannot introduce a facial state the accessibility description
#: has no words for.
EXPRESSIONS: tuple[str, ...] = (
    "neutral", "happy", "focused", "thinking", "concerned",
    "warning", "error", "surprised", "sleepy",
)

#: Character state -> expression. The state comes from the canonical mapper, so
#: this is a presentation detail of an already-decided fact and not a second
#: reading of the task.
STATE_EXPRESSIONS: Mapping[str, str] = {
    "idle": "neutral",
    "greeting": "happy",
    "listening": "focused",
    "transcribing": "focused",
    "understanding": "thinking",
    "planning": "thinking",
    "working": "focused",
    "researching": "thinking",
    "typing": "focused",
    "reviewing": "focused",
    "waiting_for_user": "neutral",
    "waiting_for_approval": "concerned",
    "speaking": "neutral",
    "presenting_result": "happy",
    "success": "happy",
    "warning": "warning",
    "blocked": "concerned",
    "degraded": "concerned",
    "error": "error",
    "paused": "neutral",
    "cancelled": "neutral",
    "disconnected": "sleepy",
    "sleeping": "sleepy",
    "starting": "neutral",
    "unavailable": "sleepy",
    "moving": "neutral",
    "repositioning": "neutral",
}

#: §12's generic mouth shapes and how far open each one is. Used only by the
#: bone fallback: with morph targets the package says what the shape looks like,
#: and openness is a crude approximation that exists so a character with a jaw
#: bone and no mouth morphs still moves its mouth when it speaks.
MOUTH_OPENNESS: Mapping[str, float] = {
    MouthShape.NEUTRAL.value: 0.0,
    MouthShape.CLOSED.value: 0.0,
    MouthShape.OPEN_SMALL.value: 0.25,
    MouthShape.OPEN_MEDIUM.value: 0.55,
    MouthShape.OPEN_WIDE.value: 1.0,
    MouthShape.ROUNDED.value: 0.35,
    MouthShape.SMILE.value: 0.15,
}

#: How far the jaw bone rotates at full openness, in radians. About 17 degrees:
#: a talking mouth, not a yawn.
MAXIMUM_JAW_RADIANS = 0.30

#: How quickly the mouth moves towards a newly requested shape, per second. A
#: mouth that snapped between shapes at the viseme rate reads as a stutter; one
#: that takes longer than about 60 ms to arrive reads as dubbing.
MOUTH_RESPONSE_PER_SECOND = 22.0

#: The same, for expressions, which change on a human timescale.
EXPRESSION_RESPONSE_PER_SECOND = 5.0


@dataclass(frozen=True)
class FaceResolution:
    """How one request was satisfied, and by what."""

    requested: str
    mechanism: str
    targets: tuple[tuple[int, float], ...] = ()
    bone: int | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "mechanism": self.mechanism,
            "morphTargets": [{"index": index, "weight": weight} for index, weight in self.targets],
            "bone": self.bone,
        }


class FaceRig:
    """What a particular character can do with its face, resolved once.

    Resolution happens at load time rather than per frame, so a missing morph
    target costs one lookup at startup instead of a branch in the render loop —
    and so the answer to "can this character smile" is a value a diagnostic can
    print rather than something only the renderer knows.
    """

    def __init__(
        self,
        model: ValidatedModel,
        *,
        expression_map: Mapping[str, Mapping[str, float]] | None = None,
        viseme_map: Mapping[str, Mapping[str, float]] | None = None,
    ) -> None:
        self.model = model
        self.morph_index: dict[str, int] = {
            name: index for index, name in enumerate(model.morph_target_names)
        }
        self.skeleton: SkeletonProfile = model.skeleton
        self.jaw = self.skeleton.index("jaw")
        self.expressions: dict[str, FaceResolution] = {}
        self.visemes: dict[str, FaceResolution] = {}
        self._resolve_expressions(expression_map or {})
        self._resolve_visemes(viseme_map or {})

    def _targets(self, declared: Mapping[str, float], label: str) -> tuple[tuple[int, float], ...]:
        resolved: list[tuple[int, float]] = []
        for name, weight in declared.items():
            index = self.morph_index.get(str(name))
            if index is None:
                continue
            if not isinstance(weight, (int, float)) or isinstance(weight, bool):
                raise ModelSchemaError(f"{label} weight for {name!r} is not a number")
            value = float(weight)
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ModelSchemaError(f"{label} weight for {name!r} is outside 0..1")
            resolved.append((index, value))
        return tuple(sorted(resolved))

    def _resolve_expressions(self, declared: Mapping[str, Mapping[str, float]]) -> None:
        for expression in EXPRESSIONS:
            mapping = declared.get(expression)
            if mapping:
                targets = self._targets(mapping, f"expressionMap.{expression}")
                if targets:
                    self.expressions[expression] = FaceResolution(expression, "morph-targets", targets)
                    continue
            if expression == "neutral":
                self.expressions[expression] = FaceResolution(expression, "neutral", ())
                continue
            self.expressions[expression] = FaceResolution(expression, "neutral-fallback", ())

    def _resolve_visemes(self, declared: Mapping[str, Mapping[str, float]]) -> None:
        for shape in MOUTH_OPENNESS:
            mapping = declared.get(shape)
            if mapping:
                targets = self._targets(mapping, f"visemeMap.{shape}")
                if targets:
                    self.visemes[shape] = FaceResolution(shape, "morph-targets", targets)
                    continue
            if self.jaw is not None:
                self.visemes[shape] = FaceResolution(shape, "jaw-bone", (), self.jaw)
                continue
            self.visemes[shape] = FaceResolution(shape, "neutral-fallback", ())

    @property
    def has_expression_morphs(self) -> bool:
        return any(item.mechanism == "morph-targets" for item in self.expressions.values())

    @property
    def has_mouth_morphs(self) -> bool:
        return any(item.mechanism == "morph-targets" for item in self.visemes.values())

    def to_json(self) -> dict[str, Any]:
        return {
            "morphTargets": sorted(self.morph_index),
            "jawBone": self.jaw,
            "expressionMechanisms": {
                name: item.mechanism for name, item in sorted(self.expressions.items())
            },
            "visemeMechanisms": {
                name: item.mechanism for name, item in sorted(self.visemes.items())
            },
            "hasExpressionMorphs": self.has_expression_morphs,
            "hasMouthMorphs": self.has_mouth_morphs,
        }


class FaceController:
    """The fourth mixer layer: one expression and one mouth shape, damped.

    Damped rather than snapped, and damped *towards* a target rather than
    animated over a fixed duration, because both inputs arrive at rates nobody
    controls: an expression follows a task phase that may change twice in a
    second, and a mouth shape follows a viseme stream. A fixed-length transition
    would still be running when the next one arrived.
    """

    def __init__(self, rig: FaceRig, *, motion: str = "full") -> None:
        self.rig = rig
        self.motion = motion
        self.expression = "neutral"
        self.mouth_shape = MouthShape.NEUTRAL.value
        self._weights: dict[int, float] = {}
        self._target_weights: dict[int, float] = {}
        self._jaw = 0.0
        self._jaw_target = 0.0
        self._last = 0.0
        self.expression_changes = 0
        self.mouth_changes = 0

    def set_expression(self, expression: str) -> str:
        """Select an expression. An unknown one resolves to neutral, not an error."""
        name = str(expression)
        if name not in self.rig.expressions:
            name = "neutral"
        if name != self.expression:
            self.expression_changes += 1
        self.expression = name
        self._recompute_targets()
        return name

    def set_expression_for_state(self, character_state: str) -> str:
        return self.set_expression(STATE_EXPRESSIONS.get(str(character_state), "neutral"))

    def set_mouth_shape(self, shape: str) -> str:
        """Apply one already-admitted mouth shape. Never validates identity here."""
        name = str(shape)
        if name not in MOUTH_OPENNESS:
            # §12's missing-viseme fallback: an unknown shape closes the mouth
            # rather than holding whatever was last drawn, because a held shape
            # is a mouth frozen mid-syllable.
            name = MouthShape.NEUTRAL.value
        if name != self.mouth_shape:
            self.mouth_changes += 1
        self.mouth_shape = name
        self._recompute_targets()
        return name

    def reset_mouth(self) -> None:
        """Speech ended, was cancelled, errored, or the worker restarted."""
        self.set_mouth_shape(MouthShape.NEUTRAL.value)

    def _recompute_targets(self) -> None:
        targets: dict[int, float] = {}
        expression = self.rig.expressions.get(self.expression)
        if expression is not None:
            for index, weight in expression.targets:
                targets[index] = max(targets.get(index, 0.0), weight)
        viseme = self.rig.visemes.get(self.mouth_shape)
        openness = MOUTH_OPENNESS.get(self.mouth_shape, 0.0)
        if viseme is not None and viseme.mechanism == "morph-targets":
            for index, weight in viseme.targets:
                # The mouth wins its own targets outright: an expression that
                # also drives a mouth corner must not damp a syllable.
                targets[index] = weight
            self._jaw_target = 0.0
        elif viseme is not None and viseme.mechanism == "jaw-bone":
            self._jaw_target = openness
        else:
            self._jaw_target = 0.0
        if self.motion == "none":
            targets = {}
            self._jaw_target = 0.0
        self._target_weights = targets

    def advance(self, now: float) -> None:
        """Move the damped values towards their targets. Frame-rate independent."""
        delta = 0.0 if self._last <= 0 else max(0.0, min(0.25, now - self._last))
        self._last = now
        if self.motion == "reduced" or delta <= 0:
            self._weights = dict(self._target_weights)
            self._jaw = self._jaw_target
            return
        mouth_step = min(1.0, MOUTH_RESPONSE_PER_SECOND * delta)
        expression_step = min(1.0, EXPRESSION_RESPONSE_PER_SECOND * delta)
        keys = set(self._weights) | set(self._target_weights)
        moved: dict[int, float] = {}
        for key in keys:
            current = self._weights.get(key, 0.0)
            target = self._target_weights.get(key, 0.0)
            step = mouth_step if self._is_mouth_target(key) else expression_step
            value = current + (target - current) * step
            if abs(value) > 1e-4 or abs(target) > 1e-4:
                moved[key] = value
        self._weights = moved
        self._jaw += (self._jaw_target - self._jaw) * mouth_step

    def _is_mouth_target(self, index: int) -> bool:
        for resolution in self.rig.visemes.values():
            for target_index, _weight in resolution.targets:
                if target_index == index:
                    return True
        return False

    def pose(self) -> Pose:
        """The facial layer, as a pose the mixer can blend like any other."""
        pose = Pose()
        for index, weight in self._weights.items():
            pose.weights[index] = weight
        if self.rig.jaw is not None and abs(self._jaw) > 1e-4:
            angle = MAXIMUM_JAW_RADIANS * min(1.0, max(0.0, self._jaw))
            half = angle * 0.5
            # Rotation about X, opening the jaw downwards. The bind pose
            # supplies the rest; this layer only ever adds a hinge.
            pose.rotations[self.rig.jaw] = (math.sin(half), 0.0, 0.0, math.cos(half))
        return pose

    def status(self) -> dict[str, Any]:
        return {
            "expression": self.expression,
            "expressionMechanism": self.rig.expressions[self.expression].mechanism,
            "mouthShape": self.mouth_shape,
            "mouthMechanism": self.rig.visemes.get(self.mouth_shape, FaceResolution(self.mouth_shape, "neutral-fallback")).mechanism,
            "activeMorphTargets": len(self._weights),
            "jaw": round(self._jaw, 4),
            "expressionChanges": self.expression_changes,
            "mouthChanges": self.mouth_changes,
            "motion": self.motion,
        }


__all__ = [
    "EXPRESSIONS",
    "EXPRESSION_RESPONSE_PER_SECOND",
    "FaceController",
    "FaceResolution",
    "FaceRig",
    "MAXIMUM_JAW_RADIANS",
    "MOUTH_OPENNESS",
    "MOUTH_RESPONSE_PER_SECOND",
    "STATE_EXPRESSIONS",
]
