# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The interactive 2D renderer: a companion whose pose is computed, not stored.

The pre-rendered renderer answers "which frame is this state" by looking it up.
This one answers it by *solving* for it: every state names a target pose, and
what gets drawn is the current pose easing towards that target, plus a little
motion that never stops while the character is awake. That single difference is
what §4 is asking for — reactions, continuous transitions, and a character that
is somewhere between two states rather than snapping between them.

Three things follow from computing rather than storing, and they are the reasons
this exists as a separate renderer rather than a mode of the frame player.

**Transitions have no frames to be missing.** A frame sequence can only cross
from ``thinking`` to ``success`` if somebody drew that crossing; there are 26
states and drawing every ordered pair is 650 sequences nobody will ever author.
Easing between two poses produces all of them for free, so a state change from
*anywhere* to *anywhere* is smooth.

**Reaction is cheap.** :meth:`Procedural2DRenderer.look_at` moves where the
character is attending without any new asset. §4's "basic interaction" is that
method and it costs two floats.

**It is arithmetic, so it is bounded and testable.** No decode, no GL, no
texture upload — the same rule the rest of the 2D path follows, and the reason
:mod:`companion.character.controller` can import this without pulling a graphics
library into every text-only client. A tick is a few dozen multiplications; the
cost is in the *surface* that draws the pose, not here.

Determinism is deliberate and load-bearing. Blinks come from a seeded generator
rather than :mod:`random`, so the same seed and the same clock always produce the
same pose. Without that, "does the character actually move" is not a test one can
write — and §17 asks for exactly that test.

What this module does **not** do is draw. It produces a pose; a surface applies
it. That boundary is why the pose leaves through :attr:`RenderedFrame.pose` in
named, normalised channels rather than as pixels: a GTK surface, a diagnostic
dump and a test all read the same numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Mapping

from .errors import RendererError
from .mapper import CharacterState, MappedCharacterState
from .renderer import CharacterRenderer, RenderedFrame

__all__ = ["POSE_CHANNELS", "Procedural2DRenderer", "TargetPose"]


@dataclass(frozen=True)
class TargetPose:
    """Where a state wants the body to be. Every channel is normalised.

    ``lean`` and ``tilt`` are signed: negative is towards the user's left. The
    rest are magnitudes in ``0..1``. Keeping them normalised means the surface
    decides how many pixels a full lean is, which is what lets one pose drive a
    64 px dock icon and a 400 px centred character without a second table.
    """

    #: Forward/backward inclination. Positive leans in — towards the work.
    lean: float = 0.0
    #: Head roll. Small values read as curiosity, large ones as confusion.
    tilt: float = 0.0
    #: Eyelid opening. 1 is wide, 0 is shut.
    eye_open: float = 1.0
    #: Brow height. Positive is raised (surprise, attention), negative furrowed.
    brow: float = 0.0
    #: Mouth opening, before lip-sync overrides it while speaking.
    mouth_open: float = 0.0
    #: How far up the body sits. Drives a hop on success, a slump on error.
    rise: float = 0.0
    #: Amplitude of the continuous idle motion. Zero freezes the body.
    breath: float = 1.0
    #: Speed multiplier for the continuous motion. Higher reads as agitation.
    tempo: float = 1.0
    #: How much attention is paid to the pointer. Zero looks straight ahead.
    attention: float = 1.0


#: The channel names that leave this renderer, in a fixed order.
#:
#: Fixed because the pose crosses a boundary — into a frame, a JSON diagnostic
#: and a surface — and a set iterated in hash order would make two runs of the
#: same state produce two different frames.
POSE_CHANNELS = (
    "lean", "tilt", "eye_open", "brow", "mouth_open",
    "rise", "breath", "tempo", "attention",
)

#: What each semantic state looks like. This table is the character's acting.
#:
#: Only states that differ from neutral are written out; the rest inherit
#: :data:`_NEUTRAL`. The values were chosen so that the states §7 says a user
#: must never have to guess between are visibly different *in pose alone*,
#: without colour or text: thinking looks up and away, working leans in,
#: waiting-for-approval sits upright and still and looks straight at you.
_NEUTRAL = TargetPose()

_TARGETS: Mapping[CharacterState, TargetPose] = {
    CharacterState.IDLE: TargetPose(),
    CharacterState.STARTING: TargetPose(rise=-0.2, breath=0.6, eye_open=0.7),
    CharacterState.GREETING: TargetPose(rise=0.3, brow=0.4, lean=0.15, tempo=1.3),
    # The microphone is live: upright, attentive, eyes wide, body still enough
    # that the user can tell the motion is listening rather than working.
    CharacterState.LISTENING: TargetPose(lean=0.1, brow=0.3, eye_open=1.0, breath=0.7, tempo=0.9),
    CharacterState.TRANSCRIBING: TargetPose(lean=0.1, brow=0.2, eye_open=0.9, tempo=1.1),
    # Thinking states look away and up. A character that maintains eye contact
    # while thinking reads as waiting for the user to speak.
    CharacterState.UNDERSTANDING: TargetPose(tilt=-0.25, brow=0.2, attention=0.3, eye_open=0.85),
    CharacterState.PLANNING: TargetPose(tilt=-0.3, brow=0.15, attention=0.2, eye_open=0.8, tempo=0.9),
    CharacterState.WORKING: TargetPose(lean=0.35, brow=-0.1, eye_open=0.8, attention=0.25, tempo=1.2),
    CharacterState.RESEARCHING: TargetPose(lean=0.25, tilt=0.2, brow=0.1, attention=0.3, tempo=1.1),
    CharacterState.TYPING: TargetPose(lean=0.4, brow=-0.15, eye_open=0.75, attention=0.2, tempo=1.35),
    CharacterState.REVIEWING: TargetPose(lean=0.2, tilt=0.15, brow=-0.05, eye_open=0.85, attention=0.4),
    # The permission states. Still, square-on and looking at the user: this is
    # the pose that has to read as "I am waiting for you" from across a room.
    CharacterState.WAITING_FOR_APPROVAL: TargetPose(
        lean=0.0, tilt=0.0, brow=0.35, eye_open=1.0, breath=0.5, tempo=0.8, attention=1.0
    ),
    CharacterState.WAITING_FOR_USER: TargetPose(brow=0.25, eye_open=0.95, breath=0.6, tempo=0.85),
    CharacterState.SPEAKING: TargetPose(lean=0.1, brow=0.15, mouth_open=0.4, tempo=1.1),
    CharacterState.PRESENTING_RESULT: TargetPose(rise=0.15, lean=0.1, brow=0.3, tempo=1.1),
    CharacterState.SUCCESS: TargetPose(rise=0.4, brow=0.45, eye_open=0.7, tempo=1.4),
    CharacterState.WARNING: TargetPose(tilt=0.2, brow=-0.3, eye_open=0.95, breath=0.7),
    CharacterState.BLOCKED: TargetPose(rise=-0.2, brow=-0.35, eye_open=0.9, breath=0.6, tempo=0.8),
    CharacterState.ERROR: TargetPose(rise=-0.3, lean=-0.15, brow=-0.45, eye_open=0.9, breath=0.6, tempo=0.8),
    CharacterState.DEGRADED: TargetPose(rise=-0.1, brow=-0.15, breath=0.7, tempo=0.85),
    CharacterState.PAUSED: TargetPose(breath=0.4, tempo=0.6, eye_open=0.6, attention=0.5),
    CharacterState.CANCELLED: TargetPose(rise=-0.15, brow=-0.2, breath=0.5, tempo=0.7),
    # Sleeping: eyes shut, body low, one slow breath. The only state whose
    # breath is *raised* — a sleeping character that does not visibly breathe
    # looks switched off, which is a different thing to say.
    CharacterState.SLEEPING: TargetPose(
        rise=-0.35, eye_open=0.0, breath=1.4, tempo=0.35, attention=0.0
    ),
    CharacterState.DISCONNECTED: TargetPose(rise=-0.25, eye_open=0.5, breath=0.3, tempo=0.5, attention=0.0),
    CharacterState.UNAVAILABLE: TargetPose(rise=-0.3, eye_open=0.3, breath=0.2, tempo=0.4, attention=0.0),
    CharacterState.MOVING: TargetPose(lean=0.1, tempo=1.2, attention=0.6),
    CharacterState.REPOSITIONING: TargetPose(lean=0.1, tempo=1.2, attention=0.6),
}

#: Per-channel easing half-life in seconds: how long to cover half the distance
#: to the target.
#:
#: Different per channel because a face and a body do not move at the same
#: speed. Eyes and brows are near-instant — a blink is 100 ms and a brow raise
#: is not much slower — while the body's lean takes a beat. Giving every channel
#: one time constant was the first version and it looked like a mannequin on a
#: turntable: the whole character arrived at the new pose together, which no
#: living thing does.
_HALF_LIFE: Mapping[str, float] = {
    "lean": 0.28, "tilt": 0.24, "eye_open": 0.06, "brow": 0.10,
    "mouth_open": 0.05, "rise": 0.22, "breath": 0.40, "tempo": 0.50,
    "attention": 0.30,
}

#: The channels that carry *meaning* rather than liveliness, and are therefore
#: never scaled by the animation-intensity preference.
#:
#: ``mouth_open`` is here because lip-sync drives it: scaling it would make a
#: speaking character mumble in proportion to a motion setting.
_EXPRESSION_CHANNELS = frozenset({"eye_open", "brow", "mouth_open"})

#: Seconds between blinks, and how long one lasts. A blink is modelled rather
#: than drawn because it is the single cheapest signal that a character is alive
#: — and the one whose absence is noticed first.
_BLINK_PERIOD = 4.2
_BLINK_LENGTH = 0.13


@dataclass
class _Motion:
    """The continuous, never-finished part of the pose."""

    phase: float = 0.0
    blink_at: float = _BLINK_PERIOD
    #: Where the character is attending, in normalised screen space from its own
    #: centre. Set by :meth:`Procedural2DRenderer.look_at`.
    look_x: float = 0.0
    look_y: float = 0.0
    channels: dict[str, float] = field(default_factory=dict)


class Procedural2DRenderer(CharacterRenderer):
    """A 2D character posed by arithmetic. No GL, no decode, no per-state art."""

    renderer_name = "interactive-2d"

    def __init__(
        self,
        *,
        display_available: bool = True,
        seed: int = 0,
        intensity: float = 1.0,
    ) -> None:
        super().__init__(display_available=display_available)
        self.seed = int(seed)
        #: §10's "animation intensity". Scales every *departure from neutral*,
        #: so 0 gives a still, upright character that still changes expression
        #: enough to be readable, rather than a character that stops meaning
        #: anything. Reduced motion goes further and is handled separately.
        self.intensity = self._clamp_intensity(intensity)
        self.motion = _Motion(channels={name: getattr(_NEUTRAL, name) for name in POSE_CHANNELS})
        self.target = _NEUTRAL
        self.last_tick_ms: int | None = None
        self.frames_drawn = 0

    # -- configuration ------------------------------------------------------

    @staticmethod
    def _clamp_intensity(value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    def set_intensity(self, value: float) -> None:
        self.intensity = self._clamp_intensity(value)

    def look_at(self, x: float, y: float) -> None:
        """Attend to a point, in normalised offsets from the character's centre.

        §4's "basic interaction". Clamped rather than validated: a pointer at the
        far corner of a 4K screen produces a large offset and the right response
        to that is a character looking as far as it can, not an exception on the
        input path of a mouse move.
        """
        self.motion.look_x = max(-1.0, min(1.0, float(x)))
        self.motion.look_y = max(-1.0, min(1.0, float(y)))

    # -- renderer contract --------------------------------------------------

    def display_state(self, state: MappedCharacterState, *, now_ms: int = 0) -> RenderedFrame | None:
        self._require_package()
        self.mapped_state = state
        self.expression = state.expression
        self.target = _TARGETS.get(state.character_state, _NEUTRAL)
        self.running = True
        if not self.display_available:
            self.frame = None
            return None
        # A state change is drawn immediately rather than waiting for the next
        # tick. The eased channels mean this first frame is still the *old* pose
        # heading towards the new one, which is the point: the transition starts
        # on the state change instead of up to one frame later.
        return self._draw(now_ms=now_ms)

    def play_animation(self, name: str, *, now_ms: int = 0) -> RenderedFrame | None:
        """Pose by animation name, for diagnostics and the package's own vocabulary.

        This renderer has no frame sequences, so an animation name is resolved
        back to the *state* that names it and posed accordingly. A name nothing
        claims poses neutral rather than raising: the mapper's fallback chain can
        legitimately hand over ``__static_fallback__``.
        """
        package = self._require_package()
        for state_name, animation in package.manifest.state_map.items():
            if animation == name:
                for state in CharacterState:
                    if state.value == state_name:
                        self.target = _TARGETS.get(state, _NEUTRAL)
                        break
                break
        else:
            self.target = _NEUTRAL
        self.running = True
        if not self.display_available:
            self.frame = None
            return None
        return self._draw(now_ms=now_ms, animation=name)

    def stop_animation(self, *, now_ms: int = 0) -> RenderedFrame | None:
        self.target = _TARGETS.get(CharacterState.IDLE, _NEUTRAL)
        if not self.display_available:
            self.frame = None
            return None
        return self._draw(now_ms=now_ms, animation="idle")

    def set_mouth_shape(self, shape: str) -> None:
        """Lip-sync drives ``mouth_open`` directly rather than swapping a frame.

        The frame player has a mouth asset per viseme. Here a viseme is an
        opening amount, so the same lip-sync controller drives both renderers
        without knowing which one it is talking to.
        """
        super().set_mouth_shape(shape)
        amount = _VISEME_OPENING.get(shape.casefold(), 0.0)
        self.motion.channels["mouth_open"] = amount * self._scale_for("mouth_open")
        if self.frame is not None and self.display_available:
            self.frame = self._frame_from_channels(
                self.frame.animation, self.frame.state
            )

    def tick(self, *, now_ms: int) -> RenderedFrame | None:
        """Advance the continuous motion. Cheap enough to call at the frame cap."""
        if self.paused or not self.running:
            return self.frame
        if not self.display_available:
            return None
        return self._draw(now_ms=now_ms)

    # -- the actual solve ---------------------------------------------------

    def _scale_for(self, channel: str) -> float:
        """How much of a channel's departure from neutral survives the settings.

        The **expression** channels are exempt from intensity; only the body and
        its motion are scaled. Turning animation intensity down must not force a
        sleeping character's eyes open, and it must not make a success and an
        error wear the same face — expression is the state's *meaning*, and §8's
        "subtle, not absent" is about movement.

        Only ``eye_open`` was exempt at first, which left ``brow`` scaled to
        nothing: at intensity 0 a success, an error and a permission request all
        rendered an identical flat brow, and the three states §7 says a user must
        never have to guess between became indistinguishable in exactly the
        configuration a motion-sensitive user would choose.
        """
        if channel in _EXPRESSION_CHANNELS:
            return 1.0
        if self.reduced_motion:
            # Reduced motion keeps the pose and removes the movement. The target
            # is still reached; it is simply reached without oscillation. §9 is
            # explicit that this is a mode of the animation system rather than a
            # rung, and dropping expression here would lose state information.
            return 1.0
        return self.intensity

    def _snap_to_target(self) -> None:
        """Place every channel on its target without easing."""
        for channel in POSE_CHANNELS:
            desired = float(getattr(self.target, channel))
            neutral = float(getattr(_NEUTRAL, channel))
            self.motion.channels[channel] = neutral + (desired - neutral) * self._scale_for(channel)

    def _advance(self, delta: float, now: float) -> None:
        motion = self.motion
        target = self.target
        for channel in POSE_CHANNELS:
            desired = float(getattr(target, channel))
            neutral = float(getattr(_NEUTRAL, channel))
            desired = neutral + (desired - neutral) * self._scale_for(channel)
            current = motion.channels.get(channel, neutral)
            if delta <= 0:
                motion.channels[channel] = current
                continue
            half_life = _HALF_LIFE.get(channel, 0.2)
            # Exponential approach, framed in half-lives so the easing is
            # independent of how often tick is called. A linear step per frame
            # would make the character move at a speed that depends on the frame
            # cap, so a thermally throttled machine would animate in slow motion.
            factor = 0.5 ** (delta / half_life) if half_life > 0 else 0.0
            motion.channels[channel] = desired + (current - desired) * factor

        if self.reduced_motion:
            # No oscillation and no blink. The eased approach above still runs,
            # so states still arrive — they simply arrive quietly.
            return

        tempo = motion.channels.get("tempo", 1.0)
        motion.phase = (motion.phase + delta * tempo) % 1000.0

        # NB: the breathing offset is *not* written back into ``channels``. It is
        # computed from the phase when the frame is built, in :meth:`_breathing`.
        #
        # The first version added the sine into the stored channel each tick,
        # which made it an integrator rather than an oscillator: every tick eased
        # from an already-displaced value and then displaced it again, so an idle
        # character drifted to eight times the intended amplitude and stayed
        # there. The stored channel is the *pose*; the breath is a displacement
        # applied on the way out, and keeping them apart is what stops one
        # feeding the other.

        # ``blink_at`` is when the next blink *starts*. Between that instant and
        # one blink-length later the eyelids are held shut; after it, the next
        # blink is scheduled. A state whose eyes are already shut blinks too and
        # nothing shows, which is correct and costs one comparison.
        if now >= motion.blink_at + _BLINK_LENGTH:
            motion.blink_at = now + self._next_blink_gap(now)
        elif now >= motion.blink_at:
            # Override the eyelids entirely rather than scaling what is there. A
            # blink that multiplied the current opening would be invisible on a
            # state whose eyes are already half shut.
            motion.channels["eye_open"] = 0.0

    def _next_blink_gap(self, now: float) -> float:
        """A deterministic, irregular blink gap.

        Irregular because a metronomic blink is more unsettling than none at
        all; deterministic because §17 asks for a test that the character moves,
        and a test cannot assert on :mod:`random`. A cheap integer hash of the
        seed and the blink count gives both.
        """
        counter = int(now / max(_BLINK_PERIOD, 0.001))
        mixed = (self.seed * 2654435761 + counter * 40503) & 0xFFFF
        return _BLINK_PERIOD * (0.6 + (mixed / 0xFFFF) * 0.8)

    def _draw(self, *, now_ms: int, animation: str | None = None) -> RenderedFrame:
        previous = self.last_tick_ms
        now = max(0, now_ms) / 1000.0
        if previous is None:
            # The character's *first* frame. It snaps to the target instead of
            # easing towards it from neutral, because there is nothing to ease
            # from: a companion appearing at boot in an error state should
            # appear in the error pose, not rise out of a neutral one. Without
            # this the first frame was always neutral, and a renderer that was
            # then quiesced before its first tick stayed neutral for good.
            self._snap_to_target()
        delta = 0.0 if previous is None else max(0.0, (now_ms - previous) / 1000.0)
        # A clock that jumped — a suspend, a slice stepping in whole seconds —
        # must not be integrated as one enormous step, which would slam every
        # channel onto its target and lose the transition the user was watching.
        # Clamping to a quarter second makes a jump look like a fast move rather
        # than a teleport.
        self._advance(min(delta, 0.25), now)
        self.last_tick_ms = now_ms
        self.frames_drawn += 1
        self.last_frame_ms = delta * 1000.0
        state = self.mapped_state.character_state.value if self.mapped_state else "idle"
        name = animation if animation is not None else (
            self.mapped_state.animation if self.mapped_state else "idle"
        )
        self.frame = self._frame_from_channels(name, state)
        return self.frame

    def _breathing(self) -> tuple[float, float]:
        """The ``(rise, lean)`` displacement of the continuous idle motion.

        Two sines at frequencies with no small common multiple, so the pair does
        not visibly repeat. Amplitudes are small on purpose: §8 asks for a
        companion that is present rather than distracting, and body motion large
        enough to notice individually is motion that pulls the eye off whatever
        the user is actually doing.
        """
        if self.reduced_motion:
            return 0.0, 0.0
        motion = self.motion
        breath = motion.channels.get("breath", 1.0) * self.intensity
        return (
            math.sin(motion.phase * 1.9) * 0.03 * breath,
            math.sin(motion.phase * 1.15 + 0.7) * 0.02 * breath,
        )

    def _frame_from_channels(self, animation: str, state: str) -> RenderedFrame:
        package = self._require_package()
        manifest = package.manifest
        motion = self.motion
        rise_offset, lean_offset = self._breathing()
        offsets = {"rise": rise_offset, "lean": lean_offset}
        pose: list[tuple[str, float]] = []
        for channel in POSE_CHANNELS:
            value = float(motion.channels.get(channel, getattr(_NEUTRAL, channel)))
            value += offsets.get(channel, 0.0)
            if channel in ("eye_open", "mouth_open", "breath", "attention"):
                value = max(0.0, min(1.6, value))
            else:
                value = max(-1.5, min(1.5, value))
            pose.append((channel, value))
        attention = motion.channels.get("attention", 1.0)
        pose.append(("look_x", motion.look_x * attention))
        pose.append(("look_y", motion.look_y * attention))
        return RenderedFrame(
            # Synthetic: this renderer has no per-frame asset, and saying so is
            # more honest than naming a frame it did not use. The 3D renderer
            # describes its frames the same way, for the same reason.
            asset_id=f"procedural:{state}",
            asset_path=package.asset_path(manifest.fallback_asset),
            width=manifest.width,
            height=manifest.height,
            state=state,
            animation=animation,
            frame_index=self.frames_drawn,
            opacity=self.opacity,
            scale=self.scale,
            mouth_shape=self.mouth_shape,
            accessibility_description=self.accessibility_description(),
            pose=tuple(pose),
        )

    def load_package(self, package) -> None:  # type: ignore[no-untyped-def]
        super().load_package(package)
        # One decoded canvas, like the static renderer: this renderer needs a
        # base image to pose, not the package's every frame. A package whose
        # animations hold two hundred frames costs the same here as one that
        # holds six, which is most of why the mode is light.
        try:
            self.observed_memory_bytes = package.image_info[package.manifest.fallback_asset].decoded_bytes
        except (KeyError, AttributeError):  # pragma: no cover - defensive
            raise RendererError("the interactive renderer needs a validated fallback image")

    def unload_package(self) -> None:
        self.motion = _Motion(channels={name: getattr(_NEUTRAL, name) for name in POSE_CHANNELS})
        self.target = _NEUTRAL
        self.last_tick_ms = None
        self.frames_drawn = 0
        super().unload_package()


#: How far the mouth opens for each shape the lip-sync controller produces.
#:
#: The keys are exactly :class:`companion.character.lipsync.MouthShape`'s
#: values — a test iterates that enum and asserts every member appears here, so
#: a shape added later cannot silently render as a closed mouth. ``smile`` opens
#: slightly because a smile that closed the mouth mid-word would swallow the
#: syllable it was meant to carry.
_VISEME_OPENING: Mapping[str, float] = {
    "closed": 0.0,
    "neutral": 0.0,
    "open-small": 0.3,
    "open-medium": 0.6,
    "open-wide": 0.95,
    "rounded": 0.5,
    "smile": 0.25,
}
