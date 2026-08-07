# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Canonical state to skeletal pose: candidates, priority, transitions, mixing.

The chain §9 asks for, in one module because the four steps only make sense
together::

    PresentationState -> character animation candidate set -> priority filter
        -> transition planner -> animation mixer

Two things this module refuses to become.

**It is not a second task-state machine.** The state arrives as a
:class:`companion.character.mapper.CharacterState` that the existing mapper
already produced from the canonical presentation phase, and the priority filter
below calls :func:`companion.character.mapper.priority_rank` rather than holding
an order of its own. §8 is explicit about this and the reason is the one the
mapper's own docstring gives: two priority systems disagree the first time one
of them gains a state. A test asserts that §9's sequence is a subsequence of the
canonical order, so the two cannot drift silently.

**It is not an unbounded layer stack.** §10 permits exactly four: the outgoing
base, the incoming base, one upper-body overlay and one facial layer. A mixer
that accepted a list would eventually be handed eight, and eight layers of
quaternion blending on a software rasteriser is how a companion becomes the
reason a laptop is warm.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

from companion.character.mapper import CharacterState, priority_rank

from .errors import ModelSchemaError
from .glb import AnimationClipData, ValidatedModel
from .skeleton import SkeletonProfile

#: §8's animation states. Every one is reachable from a canonical presentation
#: phase or from a client fact the mapper already folds in; none is invented
#: here. ``thinking`` is deliberately absent — the canonical vocabulary calls it
#: ``planning`` and a synonym would be a second name for one state.
ANIMATION_STATES: tuple[str, ...] = (
    "idle",
    "greeting",
    "listening",
    "transcribing",
    "understanding",
    "planning",
    "working",
    "researching",
    "typing",
    "reviewing",
    "waiting-for-user",
    "waiting-for-approval",
    "speaking",
    "presenting-result",
    "success",
    "warning",
    "blocked",
    "error",
    "paused",
    "cancelled",
    "sleeping",
    "repositioning",
)

#: Character state -> animation-state candidates, most specific first. The last
#: entry of every chain is one the default package is required to carry, so
#: resolution always terminates in something drawable.
CANDIDATES: Mapping[CharacterState, tuple[str, ...]] = {
    CharacterState.UNAVAILABLE: ("sleeping", "idle"),
    CharacterState.STARTING: ("greeting", "idle"),
    CharacterState.IDLE: ("idle",),
    CharacterState.GREETING: ("greeting", "idle"),
    CharacterState.LISTENING: ("listening", "idle"),
    CharacterState.TRANSCRIBING: ("transcribing", "listening", "idle"),
    CharacterState.UNDERSTANDING: ("understanding", "planning", "idle"),
    CharacterState.WAITING_FOR_USER: ("waiting-for-user", "idle"),
    CharacterState.WAITING_FOR_APPROVAL: ("waiting-for-approval", "warning", "idle"),
    CharacterState.PLANNING: ("planning", "understanding", "idle"),
    CharacterState.WORKING: ("working", "idle"),
    CharacterState.RESEARCHING: ("researching", "working", "idle"),
    CharacterState.TYPING: ("typing", "working", "idle"),
    CharacterState.REVIEWING: ("reviewing", "working", "idle"),
    CharacterState.SPEAKING: ("speaking", "idle"),
    CharacterState.PRESENTING_RESULT: ("presenting-result", "speaking", "success", "idle"),
    CharacterState.SUCCESS: ("success", "idle"),
    CharacterState.WARNING: ("warning", "idle"),
    CharacterState.BLOCKED: ("blocked", "warning", "idle"),
    CharacterState.DEGRADED: ("warning", "idle"),
    CharacterState.ERROR: ("error", "warning", "idle"),
    CharacterState.PAUSED: ("paused", "idle"),
    CharacterState.CANCELLED: ("cancelled", "idle"),
    CharacterState.DISCONNECTED: ("sleeping", "idle"),
    CharacterState.SLEEPING: ("sleeping", "idle"),
    CharacterState.MOVING: ("repositioning", "idle"),
    CharacterState.REPOSITIONING: ("repositioning", "idle"),
}

#: §9's priority, spelled out so a test can assert it is a subsequence of the
#: canonical order rather than a second copy of it.
SECTION_NINE_ORDER: tuple[CharacterState, ...] = (
    CharacterState.ERROR,
    CharacterState.BLOCKED,
    CharacterState.WAITING_FOR_APPROVAL,
    CharacterState.LISTENING,
    CharacterState.SPEAKING,
    CharacterState.WORKING,
    CharacterState.REVIEWING,
    CharacterState.PRESENTING_RESULT,
    CharacterState.SUCCESS,
    CharacterState.IDLE,
)

#: States whose animation may never be held back by a decorative one already
#: playing. §9's closing sentence, as a set: a cosmetic animation must never
#: obscure an approval or an error.
NON_INTERRUPTIBLE_BY_COSMETIC: frozenset[CharacterState] = frozenset({
    CharacterState.ERROR,
    CharacterState.BLOCKED,
    CharacterState.WAITING_FOR_APPROVAL,
    CharacterState.WARNING,
    CharacterState.CANCELLED,
    CharacterState.LISTENING,
})

#: Animation states that loop until something else happens, against those that
#: play once and hand back to idle. Loop/one-shot is a property of what the
#: state *means*, not of the clip, so it lives here rather than in a package
#: where an author could make an error animation loop forever.
LOOPING_STATES: frozenset[str] = frozenset({
    "idle", "listening", "transcribing", "understanding", "planning", "working",
    "researching", "typing", "reviewing", "speaking", "waiting-for-user",
    "waiting-for-approval", "sleeping", "paused", "repositioning",
})

#: Default crossfade, in seconds. Short enough that a state change reads as
#: immediate and long enough that a skeleton does not snap.
DEFAULT_CROSSFADE = 0.22

#: Crossfades that are deliberately shorter, because the user is waiting for
#: information rather than watching a character.
URGENT_CROSSFADE = 0.08

#: The maximum blend this mixer will ever run. §10.
MAXIMUM_LAYERS = 4


# --------------------------------------------------------------------------- #
# Poses
# --------------------------------------------------------------------------- #

Vector3 = tuple[float, float, float]
Quaternion = tuple[float, float, float, float]


@dataclass
class Pose:
    """One skeleton's local transforms, plus morph weights.

    Mutable on purpose: a pose is produced once per frame and overwritten in
    place by the mixer, and allocating three dictionaries per layer per frame in
    a software-rasterised renderer is a measurable cost for no benefit.
    """

    translations: MutableMapping[int, Vector3] = field(default_factory=dict)
    rotations: MutableMapping[int, Quaternion] = field(default_factory=dict)
    scales: MutableMapping[int, Vector3] = field(default_factory=dict)
    weights: MutableMapping[int, float] = field(default_factory=dict)

    def clear(self) -> None:
        self.translations.clear()
        self.rotations.clear()
        self.scales.clear()
        self.weights.clear()

    def copy(self) -> "Pose":
        return Pose(
            dict(self.translations), dict(self.rotations), dict(self.scales), dict(self.weights)
        )


def lerp(start: float, end: float, weight: float) -> float:
    return start + (end - start) * weight


def lerp3(start: Vector3, end: Vector3, weight: float) -> Vector3:
    return (
        lerp(start[0], end[0], weight),
        lerp(start[1], end[1], weight),
        lerp(start[2], end[2], weight),
    )


def nlerp(start: Quaternion, end: Quaternion, weight: float) -> Quaternion:
    """Normalised linear quaternion blend, shortest-arc.

    nlerp rather than slerp: over a 0.22 s crossfade between two poses of the
    same character the angular difference is small, the visual difference
    between the two is not observable, and slerp costs an ``acos`` and two
    ``sin`` per joint per frame on a CPU that is also rasterising.
    """
    dot = sum(a * b for a, b in zip(start, end))
    if dot < 0.0:
        end = (-end[0], -end[1], -end[2], -end[3])
    blended = tuple(lerp(a, b, weight) for a, b in zip(start, end))
    length = math.sqrt(sum(component * component for component in blended))
    if length < 1e-8:
        return start
    return tuple(component / length for component in blended)  # type: ignore[return-value]


def blend_poses(base: Pose, overlay: Pose, weight: float, *, into: Pose | None = None) -> Pose:
    """``base`` moved ``weight`` of the way towards ``overlay``.

    Keys present in only one pose are taken from that one at full strength: a
    layer that says nothing about the left foot is not an instruction to move
    the left foot towards the origin.
    """
    weight = min(1.0, max(0.0, float(weight)))
    result = into if into is not None else Pose()
    if result is not base:
        result.clear()
        result.translations.update(base.translations)
        result.rotations.update(base.rotations)
        result.scales.update(base.scales)
        result.weights.update(base.weights)
    for node, value in overlay.translations.items():
        current = result.translations.get(node)
        result.translations[node] = value if current is None else lerp3(current, value, weight)
    for node, rotation in overlay.rotations.items():
        current = result.rotations.get(node)
        result.rotations[node] = rotation if current is None else nlerp(current, rotation, weight)
    for node, scale in overlay.scales.items():
        current = result.scales.get(node)
        result.scales[node] = scale if current is None else lerp3(current, scale, weight)
    for target, value in overlay.weights.items():
        current = result.weights.get(target)
        result.weights[target] = value if current is None else lerp(current, value, weight)
    return result


# --------------------------------------------------------------------------- #
# Sampling
# --------------------------------------------------------------------------- #


class ClipSampler:
    """Sample one validated clip at a time. Pure; no clock of its own."""

    def __init__(self, clip: AnimationClipData, *, morph_target_count: int = 0) -> None:
        self.clip = clip
        self.morph_target_count = morph_target_count

    @property
    def duration(self) -> float:
        return self.clip.duration

    def sample(self, seconds: float, *, into: Pose | None = None) -> Pose:
        pose = into if into is not None else Pose()
        pose.clear()
        time = max(0.0, float(seconds))
        for channel in self.clip.channels:
            sampler = self.clip.samplers[channel.sampler]
            values = _sample_channel(sampler, time)
            if channel.path == "translation":
                pose.translations[channel.node] = (values[0], values[1], values[2])
            elif channel.path == "rotation":
                length = math.sqrt(sum(value * value for value in values[:4])) or 1.0
                pose.rotations[channel.node] = (
                    values[0] / length, values[1] / length, values[2] / length, values[3] / length,
                )
            elif channel.path == "scale":
                pose.scales[channel.node] = (values[0], values[1], values[2])
            elif channel.path == "weights":
                for index, value in enumerate(values):
                    pose.weights[index] = value
        return pose


def _sample_channel(sampler: Any, time: float) -> tuple[float, ...]:
    times = sampler.input_times
    stride = sampler.stride
    output = sampler.output
    if not times:
        return tuple(0.0 for _ in range(stride))
    if time <= times[0]:
        return _element(output, 0, stride, sampler.interpolation, first=True)
    if time >= times[-1]:
        return _element(output, len(times) - 1, stride, sampler.interpolation, first=True)
    low, high = 0, len(times) - 1
    while high - low > 1:
        middle = (low + high) // 2
        if times[middle] <= time:
            low = middle
        else:
            high = middle
    span = times[high] - times[low]
    factor = 0.0 if span <= 0 else (time - times[low]) / span
    if sampler.interpolation == "STEP":
        return _element(output, low, stride, sampler.interpolation, first=True)
    if sampler.interpolation == "CUBICSPLINE":
        # Each keyframe is (in-tangent, value, out-tangent).
        base_low = low * 3 * stride
        base_high = high * 3 * stride
        start = output[base_low + stride:base_low + 2 * stride]
        start_out = output[base_low + 2 * stride:base_low + 3 * stride]
        end_in = output[base_high:base_high + stride]
        end = output[base_high + stride:base_high + 2 * stride]
        t2 = factor * factor
        t3 = t2 * factor
        h00 = 2 * t3 - 3 * t2 + 1
        h10 = t3 - 2 * t2 + factor
        h01 = -2 * t3 + 3 * t2
        h11 = t3 - t2
        return tuple(
            h00 * start[i] + h10 * span * start_out[i] + h01 * end[i] + h11 * span * end_in[i]
            for i in range(stride)
        )
    start = output[low * stride:(low + 1) * stride]
    end = output[high * stride:(high + 1) * stride]
    return tuple(lerp(a, b, factor) for a, b in zip(start, end))


def _element(output: Sequence[float], index: int, stride: int, interpolation: str, *, first: bool) -> tuple[float, ...]:
    if interpolation == "CUBICSPLINE":
        base = index * 3 * stride + stride
        return tuple(output[base:base + stride])
    base = index * stride
    return tuple(output[base:base + stride])


# --------------------------------------------------------------------------- #
# The state machine
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AnimationDecision:
    """What the planner decided, and why. Every field is reportable."""

    animation_state: str
    clip_name: str
    candidates: tuple[str, ...]
    loop: bool
    crossfade_seconds: float
    interrupted: bool
    held: bool
    reason: str

    def to_json(self) -> dict[str, Any]:
        return {
            "animationState": self.animation_state,
            "clip": self.clip_name,
            "candidates": list(self.candidates),
            "loop": self.loop,
            "crossfadeSeconds": self.crossfade_seconds,
            "interrupted": self.interrupted,
            "held": self.held,
            "reason": self.reason,
        }


@dataclass
class _Playing:
    state: CharacterState
    animation_state: str
    sampler: ClipSampler
    started: float
    loop: bool


class AnimationStateMachine:
    """Candidates, priority, transitions and one bounded mixer.

    ``motion`` selects between three behaviours the accessibility settings ask
    for and the degradation ladder reuses:

    ``full``
        crossfades, overlays and procedural motion.
    ``reduced``
        the first frame of the target clip, no crossfade, no overlay. §9's
        "reduced motion" — the character still *changes*, so the state is still
        legible, it simply does not move to get there.
    ``none``
        the bind pose plus expression. §9's "no-animation mode".
    """

    def __init__(
        self,
        model: ValidatedModel,
        animation_map: Mapping[str, str],
        *,
        motion: str = "full",
        upper_body_root: str = "chest",
    ) -> None:
        if motion not in {"full", "reduced", "none"}:
            raise ValueError("motion must be full, reduced or none")
        self.model = model
        self.animation_map = dict(animation_map)
        self.motion = motion
        self.upper_body_root = upper_body_root
        self._samplers: dict[str, ClipSampler] = {}
        morph_count = len(model.morph_target_names)
        for animation_state, clip_name in self.animation_map.items():
            clip = model.clip(clip_name)
            if clip is None:
                raise ModelSchemaError(
                    f"animationMap sends {animation_state!r} to clip {clip_name!r}, which the model does not carry"
                )
            self._samplers[animation_state] = ClipSampler(clip, morph_target_count=morph_count)
        if "idle" not in self._samplers:
            raise ModelSchemaError("animationMap must resolve idle")
        self.current: _Playing | None = None
        self.previous: _Playing | None = None
        self.blend_started = 0.0
        self.blend_seconds = 0.0
        self.overlay: tuple[ClipSampler, float, float] | None = None
        self.decisions: list[AnimationDecision] = []
        self._base = Pose()
        self._incoming = Pose()
        self._overlay_pose = Pose()
        self._result = Pose()
        self.upper_body_nodes: frozenset[int] = frozenset()
        self._resolve_upper_body(model.skeleton)

    def _resolve_upper_body(self, skeleton: SkeletonProfile) -> None:
        root = skeleton.index(self.upper_body_root)
        if root is None:
            return
        children: dict[int, list[int]] = {}
        for node in self.model.nodes:
            children.setdefault(node.index, list(node.children))
        collected: set[int] = set()
        stack = [root]
        while stack:
            current = stack.pop()
            if current in collected:
                continue
            collected.add(current)
            stack.extend(children.get(current, ()))
        self.upper_body_nodes = frozenset(collected)

    # -- selection ---------------------------------------------------------

    def candidates_for(self, state: CharacterState) -> tuple[str, ...]:
        return CANDIDATES.get(state, ("idle",))

    def resolve(self, state: CharacterState) -> tuple[str, str, tuple[str, ...]]:
        """First candidate the package actually carries, and the chain tried."""
        chain = self.candidates_for(state)
        for candidate in chain:
            if candidate in self._samplers:
                return candidate, self._samplers[candidate].clip.name, chain
        return "idle", self._samplers["idle"].clip.name, chain

    def request(self, state: CharacterState, *, now: float) -> AnimationDecision:
        """Plan a transition into ``state``. Never raises; always decides."""
        animation_state, clip_name, chain = self.resolve(state)
        loop = animation_state in LOOPING_STATES
        crossfade = URGENT_CROSSFADE if state in NON_INTERRUPTIBLE_BY_COSMETIC else DEFAULT_CROSSFADE
        if self.motion != "full":
            crossfade = 0.0
        interrupted = False
        held = False
        reason = f"canonical character state {state.value}"

        current = self.current
        if current is not None and current.state is state and current.animation_state == animation_state:
            decision = AnimationDecision(
                animation_state, clip_name, chain, loop, 0.0, False, False,
                "already playing the animation this state resolves to",
            )
            self.decisions.append(decision)
            return decision

        if current is not None:
            incoming_rank = priority_rank(state)
            current_rank = priority_rank(current.state)
            finished = (
                not current.loop
                and now - current.started >= current.sampler.duration
            )
            if incoming_rank <= current_rank or finished:
                interrupted = not finished and current_rank != incoming_rank
                if incoming_rank < current_rank:
                    reason = (
                        f"{state.value} outranks the playing {current.state.value} "
                        "and takes the surface immediately"
                    )
            else:
                # The incoming state is less urgent and the current clip has not
                # finished. §9: a cosmetic animation must never obscure an
                # approval or an error, and the way to guarantee that is to make
                # the *less urgent* thing wait rather than to hope it is short.
                held = True
                decision = AnimationDecision(
                    current.animation_state, current.sampler.clip.name, chain, current.loop,
                    0.0, False, True,
                    f"{state.value} is less urgent than the playing {current.state.value}; held",
                )
                self.decisions.append(decision)
                return decision

        sampler = self._samplers[animation_state]
        if current is not None and self.motion == "full" and crossfade > 0:
            self.previous = current
            self.blend_started = now
            self.blend_seconds = crossfade
        else:
            self.previous = None
            self.blend_seconds = 0.0
        self.current = _Playing(state, animation_state, sampler, now, loop)
        decision = AnimationDecision(
            animation_state, sampler.clip.name, chain, loop, crossfade, interrupted, held, reason
        )
        self.decisions.append(decision)
        if len(self.decisions) > 256:
            del self.decisions[:-256]
        return decision

    # -- overlays ----------------------------------------------------------

    def set_upper_body_overlay(self, animation_state: str | None, *, now: float, weight: float = 0.6) -> bool:
        """At most one upper-body overlay. §10's third layer.

        Returns whether the overlay is active. An overlay the package does not
        carry is simply absent — an overlay is by definition the part of the
        presentation that is allowed to be missing.
        """
        if animation_state is None or self.motion != "full":
            self.overlay = None
            return False
        sampler = self._samplers.get(animation_state)
        if sampler is None:
            self.overlay = None
            return False
        self.overlay = (sampler, now, min(1.0, max(0.0, float(weight))))
        return True

    # -- evaluation --------------------------------------------------------

    def blend_weight(self, now: float) -> float:
        if self.previous is None or self.blend_seconds <= 0:
            return 1.0
        elapsed = now - self.blend_started
        if elapsed >= self.blend_seconds:
            return 1.0
        return max(0.0, elapsed / self.blend_seconds)

    def evaluate(self, now: float) -> Pose:
        """One frame's pose. At most :data:`MAXIMUM_LAYERS` contribute."""
        current = self.current
        if current is None:
            self._result.clear()
            return self._result
        if self.motion == "none":
            self._result.clear()
            return self._result

        def clip_time(playing: _Playing) -> float:
            if self.motion == "reduced":
                return 0.0
            elapsed = max(0.0, now - playing.started)
            duration = playing.sampler.duration
            if duration <= 0:
                return 0.0
            if playing.loop:
                return math.fmod(elapsed, duration)
            return min(elapsed, duration)

        current.sampler.sample(clip_time(current), into=self._incoming)
        weight = self.blend_weight(now)
        if self.previous is not None and weight < 1.0:
            self.previous.sampler.sample(clip_time(self.previous), into=self._base)
            blend_poses(self._base, self._incoming, weight, into=self._result)
        else:
            self.previous = None
            self._result.clear()
            self._result.translations.update(self._incoming.translations)
            self._result.rotations.update(self._incoming.rotations)
            self._result.scales.update(self._incoming.scales)
            self._result.weights.update(self._incoming.weights)

        if self.overlay is not None and self.upper_body_nodes:
            sampler, started, overlay_weight = self.overlay
            duration = sampler.duration or 1.0
            sampler.sample(math.fmod(max(0.0, now - started), duration), into=self._overlay_pose)
            restricted = Pose(
                {node: value for node, value in self._overlay_pose.translations.items() if node in self.upper_body_nodes},
                {node: value for node, value in self._overlay_pose.rotations.items() if node in self.upper_body_nodes},
                {node: value for node, value in self._overlay_pose.scales.items() if node in self.upper_body_nodes},
                {},
            )
            blend_poses(self._result, restricted, overlay_weight, into=self._result)
        return self._result

    def finished(self, now: float) -> bool:
        current = self.current
        if current is None or current.loop:
            return False
        return now - current.started >= current.sampler.duration

    def return_to_idle(self, *, now: float) -> AnimationDecision | None:
        """§9's return-to-idle. Only ever from a finished one-shot."""
        if not self.finished(now):
            return None
        if self.current is not None and self.current.animation_state == "idle":
            return None
        # The one-shot has run; nothing outranks idle once nothing is playing.
        self.current = None
        return self.request(CharacterState.IDLE, now=now)

    def status(self, now: float) -> dict[str, Any]:
        current = self.current
        return {
            "motion": self.motion,
            "state": current.state.value if current else None,
            "animationState": current.animation_state if current else None,
            "clip": current.sampler.clip.name if current else None,
            "loop": current.loop if current else None,
            "elapsedSeconds": round(now - current.started, 4) if current else None,
            "blending": self.previous is not None,
            "blendWeight": round(self.blend_weight(now), 4),
            "blendSeconds": self.blend_seconds,
            "overlay": self.overlay[0].clip.name if self.overlay else None,
            "layers": (
                1
                + (1 if self.previous is not None else 0)
                + (1 if self.overlay is not None else 0)
            ),
            "maximumLayers": MAXIMUM_LAYERS,
            "availableStates": sorted(self._samplers),
        }


__all__ = [
    "ANIMATION_STATES",
    "AnimationDecision",
    "AnimationStateMachine",
    "CANDIDATES",
    "ClipSampler",
    "DEFAULT_CROSSFADE",
    "LOOPING_STATES",
    "MAXIMUM_LAYERS",
    "NON_INTERRUPTIBLE_BY_COSMETIC",
    "Pose",
    "SECTION_NINE_ORDER",
    "URGENT_CROSSFADE",
    "blend_poses",
    "nlerp",
]
