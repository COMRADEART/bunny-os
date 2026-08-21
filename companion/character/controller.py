# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Renderer orchestration that preserves task-independent presentation state."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .adaptation import (
    AdaptiveRendererSelector,
    CapabilityPresentationPlan,
    Presentation,
    RendererDecision,
    RendererSignals,
)
from .animated_renderer import Animated2DRenderer
from .bubble import BubbleLayout, BubbleState
from .lipsync import LipSyncController, LipSyncEvent, LipSyncStatus
from .mapper import MappedCharacterState
from .modes import (
    DEFAULT_MODE,
    MODE_CEILINGS,
    PRERENDERED_RENDERER,
    RenderMode,
    performance_cap,
    renderer_chain,
)
from .package import ValidatedPackage
from .positioning import PositionDecision
from .procedural_renderer import Procedural2DRenderer
from .quiescence import DEFAULT_POLICY, QuiescenceDecision, QuiescenceLevel, QuiescencePolicy
from .renderer import CharacterRenderer, RenderedFrame, RendererFailureEvent
from .static_renderer import StaticImageRenderer


@dataclass(frozen=True)
class CharacterRendererSnapshot:
    presentation: RendererDecision
    mapped_state: MappedCharacterState | None
    frame: RenderedFrame | None
    renderer_status: dict[str, Any] | None
    position: dict[str, Any] | None
    bubble: dict[str, Any] | None
    lip_sync: dict[str, Any] | None
    events: tuple[dict[str, Any], ...]
    #: The mode the user chose, which is not the same fact as
    #: ``presentation.effectivePresentation`` — that is the rung the machine is
    #: currently honouring. A settings page needs both to say "you chose 3D and
    #: this machine is drawing 2D because the GPU context was lost".
    mode: str = DEFAULT_MODE.value
    quiescence: dict[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "presentation": self.presentation.to_json(),
            "mappedState": self.mapped_state.to_json() if self.mapped_state else None,
            "frame": self.frame.to_json() if self.frame else None,
            "rendererStatus": self.renderer_status,
            "position": self.position,
            "bubble": self.bubble,
            "lipSync": self.lip_sync,
            "events": list(self.events),
            "mode": self.mode,
            "quiescence": self.quiescence,
        }


class CharacterRendererController:
    """Own renderer health only.  The companion task remains in runtime-core."""

    def __init__(
        self,
        *,
        selector: AdaptiveRendererSelector | None = None,
        three_d_context: Any = None,
        three_d_seed: int | None = None,
        mode: RenderMode | None = None,
        quiescence: QuiescencePolicy | None = None,
        idle_animation: bool = True,
        animation_intensity: float = 1.0,
        performance: str = "automatic",
        contextual_reactions: bool = True,
    ) -> None:
        self.selector = selector or AdaptiveRendererSelector()
        #: Which of the three companions the user asked for, or ``None`` when
        #: nobody said. A *choice*, never written by degradation — see
        #: :mod:`companion.character.modes` for why the mode and the capability
        #: rung are two values.
        #:
        #: ``None`` means "apply no mode ceiling", and it is the default here on
        #: purpose. The product's default is pre-rendered, but that is a
        #: *policy* and it is enforced where policy lives: in the settings
        #: default, in :func:`companion.character.policy.default_character_decision`,
        #: and in the launcher that reads both. Baking it in here instead — which
        #: is what this did first — silently capped every caller that had a
        #: capability plan permitting 3D and had never heard of modes, including
        #: the 3D slice and the diagnostics whose whole job is to draw 3D. A
        #: mechanism that quietly overrules its caller's plan is not a default,
        #: it is a bug with a rationale.
        self.mode = mode
        self.quiescence = quiescence or DEFAULT_POLICY
        self.idle_animation = idle_animation
        self.animation_intensity = animation_intensity
        #: §10's performance setting. A frame-rate ceiling only; it never
        #: changes which renderer runs.
        self.performance = performance
        #: §10's "enable/disable contextual reactions". Whether the companion
        #: attends to the pointer at all. Off is enforced here rather than by
        #: asking every caller not to call :meth:`look_at` — a preference that
        #: depends on every call site remembering it is a preference that will
        #: eventually be ignored by one of them.
        self.contextual_reactions = contextual_reactions
        #: When the current character state was entered, on the ``now_ms`` clock
        #: the caller ticks with. Quiescence is a question about *duration*, and
        #: measuring it from a wall clock while the renderer runs on a synthetic
        #: one is how a slice ends up quiescing on its second frame.
        self.state_entered_ms: int | None = None
        self.last_quiescence: QuiescenceDecision | None = None
        #: A zero-argument callable returning a
        #: :class:`companion.character.three_d.context.GraphicsContext`, or
        #: ``None``. Injected rather than constructed here so this module — which
        #: every 2D client imports — never reaches a graphics library. With
        #: ``None`` the 3D rungs are simply unreachable, which is what a
        #: headless or text-only client should get and §30 requires.
        self.three_d_context = three_d_context
        self.three_d_seed = three_d_seed
        self.package: ValidatedPackage | None = None
        self.renderer: CharacterRenderer | None = None
        self.mapped_state: MappedCharacterState | None = None
        self.decision: RendererDecision | None = None
        self.position: PositionDecision | None = None
        self.bubble_state: BubbleState | None = None
        self.bubble_layout: BubbleLayout | None = None
        self.lip_sync: LipSyncController | None = None
        self.lip_status: LipSyncStatus | None = None
        self.events: list[dict[str, Any]] = []
        self._selector_event_count = 0

    @property
    def effective_mode(self) -> RenderMode:
        """The mode used to pick a renderer, defaulting when nobody chose.

        Only the *renderer chain* consults this; the capability ceiling does
        not, because defaulting a ceiling and defaulting a renderer choice are
        different risks. Defaulting the renderer to pre-rendered on the 2D rung
        reproduces the behaviour that existed before modes — that rung was
        always served by the frame player — so a caller that never mentions a
        mode sees no change at all.
        """
        return self.mode if self.mode is not None else DEFAULT_MODE

    def load_package(self, package: ValidatedPackage) -> None:
        previous = self.package
        if (
            self.renderer is not None
            and previous is not None
            and previous.package_digest != package.package_digest
        ):
            self.renderer.unload_package()
            self.renderer = None
            self.mapped_state = None
            self.events.append({
                "eventType": "renderer.package-changed",
                "previousPackageDigest": previous.package_digest,
                "packageDigest": package.package_digest,
                "taskContinues": True,
            })
        self.package = package
        self.lip_sync = LipSyncController(package.manifest.mouth_shape_map)
        self.lip_status = None

    def unload_package(self) -> None:
        if self.renderer is not None:
            self.renderer.unload_package()
        self.renderer = None
        self.package = None
        self.mapped_state = None
        self.lip_sync = None
        self.lip_status = None

    def _renderer_for(self, presentation: Presentation, signals: RendererSignals) -> CharacterRenderer | None:
        """The renderer serving this rung under the current mode, built if needed.

        The rung says how much may be drawn; the *mode* says which renderer
        draws it, and on the 2D rung those are two different questions because
        two renderers serve it. :func:`companion.character.modes.renderer_chain`
        answers both and this walks its answer.

        Walking rather than picking is §15's fallback made immediate. Before
        this, a renderer that would not start raised, the presenter caught it,
        the selector degraded a rung and the *next* evaluation drew something —
        so a machine whose interactive renderer failed showed nothing for a
        frame and then showed a static image, having skipped the pre-rendered
        companion that would have worked perfectly. Now the chain is exhausted
        within the rung first, and only a rung with no working renderer at all
        degrades.
        """
        if presentation is Presentation.TEXT_ONLY:
            return None
        chain = renderer_chain(self.effective_mode, presentation)
        if not chain:
            return None
        if self.renderer is not None and self.renderer.renderer_name == chain[0]:
            # Already running the best renderer for this rung and mode.
            self.renderer.display_available = signals.display_available
            return self.renderer
        package = self.package
        if package is None:
            raise RuntimeError("renderer controller has no validated package")
        previous = self.renderer
        errors: list[str] = []
        renderer: CharacterRenderer | None = None
        for name in chain:
            if previous is not None and previous.renderer_name == name and previous.running:
                # The chain has fallen back to the renderer already running —
                # which is the steady state after an in-rung fallback. Keep it
                # rather than rebuilding an identical one every evaluation.
                previous.display_available = signals.display_available
                return previous
            try:
                renderer = self._construct(name, signals, package)
            except Exception as error:
                errors.append(f"{name}: {error}")
                self.events.append({
                    "eventType": "renderer.fallback",
                    "renderer": name,
                    "code": "renderer-unavailable",
                    "explanation": f"the {name} renderer could not start: {error}",
                    "taskContinues": True,
                })
                continue
            break
        if renderer is None:
            raise RuntimeError(
                "no renderer in the "
                f"{self.effective_mode.value} chain for {presentation.value} would start ("
                + "; ".join(errors) + ")"
            )
        if errors:
            self.events.append({
                "eventType": "renderer.degraded",
                "code": "renderer-chain-fallback",
                "previousPresentation": presentation.value,
                "effectivePresentation": presentation.value,
                "explanation": (
                    f"the {self.effective_mode.value} companion fell back to the {renderer.renderer_name} "
                    "renderer; the task is unaffected"
                ),
                "taskContinues": True,
            })
        if previous is not None:
            renderer.set_scale(previous.scale)
            renderer.set_opacity(previous.opacity)
            renderer.set_visibility(previous.visible)
            # A 3D renderer being replaced must give its GPU objects back before
            # the replacement draws. ``unload_package`` releases them; calling
            # it here rather than leaving it to garbage collection is what makes
            # §34's GL-object delta zero across a hundred rung changes.
            previous.unload_package()
        if self.position is not None:
            renderer.set_position(self.position)
        if self.bubble_state is not None and self.bubble_layout is not None:
            renderer.attach_speech_bubble(self.bubble_state, self.bubble_layout)
        self.renderer = renderer
        return renderer

    def _construct(
        self, name: str, signals: RendererSignals, package: ValidatedPackage
    ) -> CharacterRenderer:
        """Build one renderer by name. Raises so the chain can try the next."""
        if name in (Presentation.FULL_3D.value, Presentation.LIGHTWEIGHT_3D.value):
            return self._three_d_renderer(Presentation(name), signals, package)
        if name == "interactive-2d":
            renderer = Procedural2DRenderer(
                display_available=signals.display_available,
                seed=self.three_d_seed or 0,
                intensity=self.animation_intensity,
            )
            renderer.load_package(package)
            return renderer
        if name == PRERENDERED_RENDERER:
            renderer = Animated2DRenderer(display_available=signals.display_available)
            renderer.load_package(package)
            return renderer
        renderer = StaticImageRenderer(display_available=signals.display_available)
        renderer.load_package(package)
        return renderer

    def set_mode(self, mode: RenderMode, *, now_ms: int = 0) -> None:
        """Change which companion is drawn, keeping everything else.

        §16: the AI session survives a renderer change. It does here by
        construction — this method touches the *presentation* objects only, and
        the task, its events, its approvals and its transcript live in the
        runtime, which has no reference to any of them. The visible state is
        re-applied from :attr:`mapped_state`, so the new renderer opens on the
        state the old one was showing rather than on idle.
        """
        if mode is self.mode:
            return
        previous = self.mode
        self.mode = mode
        # The outgoing renderer is deliberately left in place. ``_renderer_for``
        # is the one path that swaps renderers, and it carries scale, opacity,
        # visibility, placement and the speech bubble across before releasing
        # the old one. Unloading and nulling here — which is what this did
        # first — meant that path saw no predecessor, so a user who had scaled
        # their companion to 1.75 got a default-sized one back the moment they
        # changed mode. §16 says only the presentation layer changes; the size
        # they chose is not part of it.
        self.events.append({
            "eventType": "renderer.mode-changed",
            "previousMode": previous.value,
            "mode": mode.value,
            "restoredState": self.mapped_state.character_state.value if self.mapped_state else None,
            "taskContinues": True,
        })
        # The state clock restarts: a character that has just been redrawn in a
        # different renderer has not been sitting still, whatever the old one's
        # timer said, and quiescing it immediately would hide the switch the
        # user just asked for.
        self.state_entered_ms = now_ms

    def _three_d_renderer(
        self, presentation: Presentation, signals: RendererSignals, package: ValidatedPackage
    ) -> CharacterRenderer:
        """Build and populate a 3D renderer, or refuse in a way the ladder reads.

        Every failure below raises, and every caller of ``_renderer_for`` is
        inside the presenter's ``try``: a refusal here becomes a typed
        degradation and the next evaluation lands on animated-2D. That is why
        this method does not itself fall back — one fallback path, in the place
        that already had one.
        """
        from .three_d.renderer import ThreeDRenderer

        if self.three_d_context is None:
            raise RuntimeError("no graphics context provider is configured for 3D presentation")
        model = package.model
        section = package.manifest.three_dimensional
        if model is None or section is None:
            raise RuntimeError("the selected package carries no validated 3D model")
        context = self.three_d_context() if callable(self.three_d_context) else self.three_d_context
        renderer = ThreeDRenderer(
            context=context,
            display_available=signals.display_available,
            quality=presentation.value,
            motion="reduced" if (signals.reduced_motion or signals.no_animation) else "full",
            seed=self.three_d_seed,
        )
        renderer.load_package(package)
        renderer.model_path = package.asset_path(
            next(asset.asset_id for asset in package.manifest.assets if asset.purpose == "model")
        )
        renderer.upload(
            model,
            animation_map=section.animation_map,
            expression_map=section.expression_map,
            viseme_map=section.viseme_map,
            native_scale=section.native_scale,
            floor_offset=section.floor_offset,
        )
        return renderer

    def apply(
        self,
        mapped: MappedCharacterState,
        plan: CapabilityPresentationPlan,
        signals: RendererSignals,
        *,
        now: float,
        now_ms: int,
    ) -> CharacterRendererSnapshot:
        package = self.package
        if package is None:
            raise RuntimeError("renderer controller has no validated package")
        plan = self._bounded_by_mode(plan)
        if self.mapped_state is None or (
            self.mapped_state.character_state is not mapped.character_state
        ):
            self.state_entered_ms = now_ms
        decision = self.selector.evaluate(plan, package, signals, now=now)
        if mapped.frame_rate_cap < decision.frame_rate_cap:
            decision = replace(
                decision,
                frame_rate_cap=mapped.frame_rate_cap,
                reasons=decision.reasons + (
                    f"the accessibility frame-rate preference capped animation at {mapped.frame_rate_cap} fps",
                ),
            )
        cap = performance_cap(self.performance)
        if cap is not None and cap < decision.frame_rate_cap:
            decision = replace(
                decision,
                frame_rate_cap=cap,
                reasons=decision.reasons + (
                    f"the {self.performance} performance setting capped animation at {cap} fps",
                ),
            )
        self.decision = decision
        self.mapped_state = mapped
        renderer = self._renderer_for(decision.effective, signals)
        frame = None
        if renderer is not None:
            renderer.set_reduced_motion(signals.reduced_motion or signals.no_animation)
            renderer.set_frame_rate_cap(decision.frame_rate_cap)
            if isinstance(renderer, Procedural2DRenderer):
                renderer.set_intensity(self.animation_intensity)
            frame = renderer.display_state(mapped, now_ms=now_ms)
            if self.lip_status is not None and self.lip_status.active:
                renderer.set_mouth_shape(self.lip_status.shape.value)
                frame = renderer.frame
        for event in self.selector.events[self._selector_event_count:]:
            self.events.append(event.to_json())
        self._selector_event_count = len(self.selector.events)
        return self.snapshot(frame=frame)

    def look_at(self, x: float, y: float) -> bool:
        """Attend to a point, if the renderer can and the user allows it.

        Returns whether the reaction was taken, so a caller can tell "ignored by
        preference" from "this renderer does not react" without inspecting
        either. The frame player cannot react — it has only the frames it was
        given — so this is a no-op there rather than an error.
        """
        if not self.contextual_reactions:
            return False
        renderer = self.renderer
        if not isinstance(renderer, Procedural2DRenderer):
            return False
        renderer.look_at(x, y)
        return True

    def set_position(self, position: PositionDecision) -> None:
        self.position = position
        if self.renderer is not None:
            self.renderer.set_position(position)

    def attach_bubble(self, state: BubbleState, layout: BubbleLayout) -> None:
        self.bubble_state, self.bubble_layout = state, layout
        if self.renderer is not None:
            self.renderer.attach_speech_bubble(state, layout)

    def detach_bubble(self) -> None:
        self.bubble_state = self.bubble_layout = None
        if self.renderer is not None:
            self.renderer.detach_speech_bubble()

    def start_lip_sync(self, events: list[LipSyncEvent], *, reduced_motion: bool = False) -> LipSyncStatus:
        if self.lip_sync is None:
            raise RuntimeError("lip sync requires a loaded character package")
        self.lip_status = self.lip_sync.start(events, reduced_motion=reduced_motion)
        return self.lip_status

    def advance_lip_sync(self, playback_ms: int, *, audio_clock_ms: int | None = None) -> LipSyncStatus:
        if self.lip_sync is None:
            raise RuntimeError("lip sync requires a loaded character package")
        self.lip_status = self.lip_sync.advance(playback_ms, audio_clock_ms=audio_clock_ms)
        if self.renderer is not None:
            self.renderer.set_mouth_shape(self.lip_status.shape.value)
        return self.lip_status

    def cancel_lip_sync(self, reason: str = "audio interrupted") -> LipSyncStatus:
        if self.lip_sync is None:
            raise RuntimeError("lip sync requires a loaded character package")
        self.lip_status = self.lip_sync.cancel(reason)
        if self.renderer is not None:
            self.renderer.set_mouth_shape("neutral")
        return self.lip_status

    def finish_lip_sync(self) -> LipSyncStatus:
        """The utterance ended of its own accord; the mouth returns to neutral.

        Distinct from :meth:`cancel_lip_sync` in the record and identical on the
        screen, which is correct: a completed utterance and an interrupted one
        both leave a closed mouth, and only one of them is a cancellation.

        Not expressible as ``advance_lip_sync`` past the end of the timeline. An
        *inactive* controller's ``advance`` returns its current status — whose
        shape is the last shape it held — and the renderer would then be told to
        draw the mouth mid-syllable again.
        """
        if self.lip_sync is None:
            raise RuntimeError("lip sync requires a loaded character package")
        self.lip_status = self.lip_sync.finish()
        if self.renderer is not None:
            self.renderer.set_mouth_shape("neutral")
        return self.lip_status

    def report_renderer_failure(self, code: str, explanation: str) -> RendererFailureEvent:
        if self.renderer is None:
            event = RendererFailureEvent("renderer.failed", "text-only", code, explanation, False, True)
        else:
            event = self.renderer.report_failure(code, explanation)
        self.events.append(event.to_json())
        return event

    def restart_renderer(self, *, now_ms: int = 0) -> CharacterRendererSnapshot:
        """Recreate only the renderer and restore package, placement and state."""
        old = self.renderer
        if old is None:
            return self.snapshot()
        try:
            presentation = Presentation(old.renderer_name)
        except ValueError:
            # A renderer whose name is not a rung name. ``interactive-2d`` is
            # the only one, and it serves the 2D rung — mapping it to
            # static-image, which is what the bare ``except`` used to do, would
            # have made a restart of the interactive companion silently demote
            # it to a still picture and never come back.
            presentation = (
                Presentation.ANIMATED_2D
                if old.renderer_name == "interactive-2d"
                else Presentation.STATIC_IMAGE
            )
        package = self.package
        if package is None:
            raise RuntimeError("renderer restart has no package")
        display_available = old.display_available
        scale = old.scale
        opacity = old.opacity
        visible = old.visible
        reduced_motion = old.reduced_motion
        frame_rate_cap = old.frame_rate_cap
        mouth_shape = old.mouth_shape
        was_paused = old.paused
        old.unload_package()
        self.renderer = None
        renderer = self._renderer_for(
            presentation, RendererSignals(display_available=display_available)
        )
        frame = None
        if renderer is not None:
            renderer.set_scale(scale)
            renderer.set_opacity(opacity)
            renderer.set_visibility(visible)
            renderer.set_reduced_motion(reduced_motion)
            renderer.set_frame_rate_cap(frame_rate_cap)
            if self.mapped_state is not None:
                frame = renderer.display_state(self.mapped_state, now_ms=now_ms)
            renderer.set_mouth_shape(mouth_shape)
            frame = renderer.frame
            if was_paused:
                renderer.pause(now_ms=now_ms)
        self.events.append({
            "eventType": "renderer.restarted",
            "renderer": renderer.renderer_name if renderer else "text-only",
            "restoredPackage": package.manifest.package_id,
            "restoredState": self.mapped_state.character_state.value if self.mapped_state else None,
            "taskContinues": True,
        })
        return self.snapshot(frame=frame)

    def _bounded_by_mode(self, plan: CapabilityPresentationPlan) -> CapabilityPresentationPlan:
        """Lower a capability plan to what the chosen mode permits.

        The mode is a ceiling applied *on top of* the machine's. A machine that
        could run 3D and a user who chose pre-rendered produce a 2D-rung plan,
        and the reason is recorded so the settings page can say why the 3D rung
        is not in use without having to guess between "your machine cannot" and
        "you asked for something lighter".
        """
        from .adaptation import _RANK

        if self.mode is None:
            # Nobody chose a mode, so nothing is capped. The caller's plan is
            # the whole answer, which is exactly what it was before modes.
            return plan
        ceiling = MODE_CEILINGS[self.mode]
        if _RANK[ceiling] >= _RANK[plan.ceiling]:
            return plan
        return replace(
            plan,
            ceiling=ceiling,
            requested=ceiling,
            reasons=plan.reasons + (
                f"the {self.mode.value} companion is the renderer mode in settings, "
                f"so presentation is capped at {ceiling.value}",
            ),
        )

    def quiescence_decision(self, *, now_ms: int) -> QuiescenceDecision:
        """What the idle policy says right now, without acting on it."""
        mapped = self.mapped_state
        state = mapped.character_state if mapped is not None else None
        cap = self.decision.frame_rate_cap if self.decision is not None else 30
        if state is None:
            return QuiescenceDecision(
                QuiescenceLevel.ACTIVE, cap, "no character state has been applied yet"
            )
        entered = self.state_entered_ms if self.state_entered_ms is not None else now_ms
        seconds = max(0.0, (now_ms - entered) / 1000.0)
        loops = bool(mapped.loop) if mapped is not None else True
        return self.quiescence.evaluate(
            state,
            seconds_in_state=seconds,
            active_cap=cap,
            idle_animation=self.idle_animation,
            loops=loops,
        )

    def tick(self, *, now_ms: int) -> RenderedFrame | None:
        """Advance the renderer, unless the idle policy says not to.

        The return value is the frame either way. A quiescent tick returns the
        frame already on screen — the caller does not have to know whether a
        draw happened, only what to show, and a caller that had to know would be
        a second place the quiescence rule lives.
        """
        renderer = self.renderer
        decision = self.quiescence_decision(now_ms=now_ms)
        self.last_quiescence = decision
        if renderer is None:
            return None
        if not decision.draws:
            # §3's "no unnecessary background rendering". Nothing is advanced and
            # no timer needs to fire again until the state changes.
            return renderer.frame
        if decision.level is QuiescenceLevel.DROWSY:
            renderer.set_frame_rate_cap(max(1, decision.frame_rate_cap))
        if isinstance(renderer, (Animated2DRenderer, Procedural2DRenderer)):
            return renderer.tick(now_ms=now_ms)
        if renderer.renderer_name in {"full-3d", "lightweight-3d"}:
            # A skeletal renderer has no frame list to advance through: every
            # tick is a new pose sampled at a new time, so a tick *is* a draw.
            # ``draw`` is bounded by the frame-rate cap the selector set.
            return renderer.draw(now_ms=now_ms)
        return renderer.frame

    def snapshot(self, *, frame: RenderedFrame | None = None) -> CharacterRendererSnapshot:
        if self.decision is None:
            self.decision = RendererDecision(
                Presentation.TEXT_ONLY, Presentation.TEXT_ONLY, 1,
                ("renderer has not received a capability plan",), False, "plan-unset",
            )
        effective_frame = frame if frame is not None else (self.renderer.frame if self.renderer else None)
        return CharacterRendererSnapshot(
            self.decision,
            self.mapped_state,
            effective_frame,
            self.renderer.status().to_json() if self.renderer else None,
            self.position.to_json() if self.position else None,
            self.bubble_state.to_json() if self.bubble_state else None,
            self.lip_status.to_json() if self.lip_status else None,
            tuple(self.events),
            self.effective_mode.value,
            self.last_quiescence.to_json() if self.last_quiescence else None,
        )
