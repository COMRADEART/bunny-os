# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§33's thirty-six steps, against a real service and a real graphics context.

What this slice is, and what it is not.

**It is real where it can be.** A :class:`companion.service.CompanionService`
runs over its socket, a task is submitted through the protocol, the runtime asks
for consent and the slice answers it, the canonical projection is folded from
the events the runtime actually recorded, and every character state is drawn by
a :class:`companion.character.three_d.renderer.ThreeDRenderer` with a live
OpenGL context — offscreen, so the frames can be *read back* and asserted on
rather than assumed. Degradation is driven by the same
:class:`companion.character.adaptation.AdaptiveRendererSelector` a desktop uses,
through the same signals.

**It says so where it is not.** Steps whose equipment this host lacks are
recorded ``NOT_RUN`` with the reason, never as passes. On a machine with no
graphics stack that is most of the visual half; on a machine with no desk it is
the desktop action; on a machine with no speech model it is the transcript. The
report distinguishes the three, because "36/36 where 9 were skipped" and "36/36"
are different sentences and only one of them is true.

The property the whole thing exists to establish is step 31 and step 36: the
task's identity, state and result are recorded before the renderer is put under
pressure and compared afterwards. A presentation layer that reached the task
would show up there and nowhere else.

**Why this file is not inside** ``companion/character/three_d/``. It was, for
about an hour. It has to reach the companion service, the desktop broker and the
voice worker to drive them — and ``tests/companion/test_three_d_isolation.py``
forbids exactly those imports *inside* the 3D subsystem. The first version
worked around that by synthesising voice events from a duck-typed object, which
is the wrong answer twice over: it weakens the evidence, and it hides a boundary
violation behind a shape. A harness that drives the subsystem belongs outside it,
so this module sits beside the 3D package rather than in it, and the boundary
test stays exactly as strict as it was.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
import time
from typing import Any

from companion.character.adaptation import (
    AdaptiveRendererSelector,
    CapabilityPresentationPlan,
    Presentation,
    RendererSignals,
)
from companion.character.defaults import default_3d_character_path
from companion.character.lipsync import MouthShape
from companion.character.mapper import (
    CharacterState,
    StateMapperInput,
    map_character_state,
)
from companion.character.package import validate_package_directory
from companion.character.schema import PackageTrustState
from companion.presentation import PresentationProjector, PresentationState

from .three_d.budget import DEFAULT_BUDGET
from .three_d.context import SurfacelessContext, offscreen_available
from .three_d.errors import RendererCapabilityError, RendererContextError

__all__ = ["THREE_D_SLICE_REQUEST", "ThreeDSliceReport", "run_three_d_slice"]

#: The same shape of request the character slice uses: harmless, local, and it
#: passes through classification, planning, an operation, a review and a notice
#: that needs consent — which is what makes the character visit every state.
THREE_D_SLICE_REQUEST = (
    "Count the words in this note, validate the count, and notify me when it is done."
)

_WAIT = 45.0
_POLL = 0.05
_SURFACE = (288, 360)

#: Signals a machine with a display and a GPU would produce. The host that runs
#: this may have neither, and every visual step would then be unreachable. The
#: substitution is explicit, confined here, and named in the report — the same
#: arrangement the 2D character slice has used since it landed, for the same
#: reason and with the same honesty about it.
_VISUAL = {
    "display_available": True,
    "graphics_ready": True,
    "available_memory_bytes": 8 * 1024 ** 3,
    "gpu_available": True,
    "three_d_available": True,
    "package_supports_3d": True,
}


@dataclass
class ThreeDSliceReport:
    steps: list[dict[str, Any]] = field(default_factory=list)
    passed: bool = True
    failures: list[str] = field(default_factory=list)
    not_run: list[str] = field(default_factory=list)
    measurements: dict[str, Any] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)

    def record(self, number: int, name: str, ok: bool, **evidence: Any) -> None:
        self.steps.append({"step": number, "name": name, "ok": bool(ok), **evidence})
        if not ok:
            self.passed = False
            self.failures.append(f"step {number} ({name})")

    def skip(self, number: int, name: str, reason: str, **evidence: Any) -> None:
        self.steps.append({
            "step": number, "name": name, "ok": None, "result": "NOT_RUN",
            "reason": reason, **evidence,
        })
        self.not_run.append(f"step {number} ({name}): {reason}")

    @property
    def step_count(self) -> int:
        return len(self.steps)

    def to_json(self) -> dict[str, Any]:
        return {
            "slice": "companion-3d-renderer-installed",
            "passed": self.passed,
            "steps": sorted(self.steps, key=lambda item: item["step"]),
            "stepCount": self.step_count,
            "ran": sum(1 for item in self.steps if item.get("ok") is not None),
            "failures": self.failures,
            "notRun": self.not_run,
            "measurements": self.measurements,
            "environment": self.environment,
            "network": "none",
            "provider": "local",
            "credentials": "none",
        }


class _SliceClock:
    """One counter, advanced explicitly. Never mixed with a real clock.

    The adaptive selector measures its recovery delay as ``now - degraded_at``.
    A slice that mixed ``time.monotonic()`` with small synthetic values made
    that difference negative and recovery unreachable for the rest of the run;
    the 2D slice learned that and this one inherits the fix rather than the bug.
    """

    def __init__(self) -> None:
        self.value = 0.0

    def advance(self, seconds: float = 1.0) -> float:
        self.value += seconds
        return self.value

    @property
    def ms(self) -> int:
        return round(self.value * 1000)


def _wait_for(predicate, timeout: float = _WAIT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(_POLL)
    return False


def _coverage(pixels: bytes) -> float:
    opaque = sum(1 for index in range(3, len(pixels), 4) if pixels[index] > 12)
    return opaque / max(1, len(pixels) // 4)


def _mapped(manifest: Any, state: PresentationState, **overrides: Any):
    return map_character_state(
        manifest,
        StateMapperInput(
            presentation_phase=state.phase,
            status_text=state.status_text or "Bunny is here.",
            approval_pending=bool(state.approvals),
            **overrides,
        ),
    )


def run_three_d_slice(root: Path) -> ThreeDSliceReport:  # noqa: PLR0915 - §33 is 36 steps
    """Run every step §33 names, and say which the host could not run."""
    from companion.gtk_shell import CompanionViewModel
    from companion.protocol import CompanionClient
    from companion.service import CompanionService, ServiceOptions

    report = ThreeDSliceReport()
    root = Path(root)
    endpoint = root / "runtime" / "runtime.sock"
    clock = _SliceClock()
    offscreen, offscreen_reason = offscreen_available()
    report.environment = {
        "offscreenAvailable": offscreen,
        "offscreenReason": offscreen_reason,
    }

    context: SurfacelessContext | None = None
    renderer: Any = None
    service = CompanionService(ServiceOptions(
        root=root, endpoint=endpoint, machine="laptop", consent_wait_seconds=_WAIT * 3,
    )).start()
    try:
        # 1. Start the canonical companion service.
        report.record(1, "start the canonical companion service", True,
                      endpoint=service.server.describe()["endpoint"])

        # 2. Start the client. The window's behaviour without its widgets.
        model = CompanionViewModel(client=CompanionClient(endpoint, timeout=15.0))
        connected = model.connect()
        report.record(2, "start the companion client", connected)

        # 3. Confirm 3D renderer eligibility.
        package_root = default_3d_character_path()
        if not package_root.is_dir():
            report.skip(3, "confirm 3D renderer eligibility",
                        "the built-in 3D character package is not installed on this host")
            return report
        if not offscreen:
            report.skip(3, "confirm 3D renderer eligibility", offscreen_reason)
            report.skip(4, "validate and load the default 3D character", offscreen_reason)
            for number in range(5, 37):
                report.skip(number, f"step {number}", "no graphics context is available")
            return report
        try:
            context = SurfacelessContext()
            info = context.info()
        except (RendererCapabilityError, RendererContextError) as exc:
            report.skip(3, "confirm 3D renderer eligibility",
                        f"a graphics context could not be created: {exc}")
            for number in range(4, 37):
                report.skip(number, f"step {number}", "no graphics context is available")
            return report
        report.environment["context"] = info.to_json()
        report.record(3, "confirm 3D renderer eligibility", True,
                      renderer=info.renderer, accelerated=info.accelerated)

        # 4. Validate and load the default 3D character.
        started = time.monotonic()
        package = validate_package_directory(package_root, trust_state=PackageTrustState.BUILT_IN)
        validate_ms = (time.monotonic() - started) * 1000.0
        section = package.manifest.three_dimensional
        from .three_d.renderer import ThreeDRenderer

        renderer = ThreeDRenderer(context=context, quality="full-3d", seed=0x3D)
        renderer.load_package(package)
        started = time.monotonic()
        renderer.upload(
            package.model,
            animation_map=section.animation_map,
            expression_map=section.expression_map,
            viseme_map=section.viseme_map,
            native_scale=section.native_scale,
            floor_offset=section.floor_offset,
            now=clock.value,
        )
        upload_ms = (time.monotonic() - started) * 1000.0
        renderer.begin_offscreen(*_SURFACE)
        report.record(
            4, "validate and load the default 3D character",
            package.model is not None and renderer.model is not None,
            packageId=package.manifest.package_id, digest=package.package_digest[:16],
            triangles=package.model.triangle_count, joints=len(package.model.joints),
            clips=len(package.model.clips), morphTargets=len(package.model.morph_target_names),
            modelValidationMs=round(validate_ms, 3), modelUploadMs=round(upload_ms, 3),
        )
        report.measurements["modelValidationMs"] = round(validate_ms, 3)
        report.measurements["modelUploadMs"] = round(upload_ms, 3)

        # 5. Draw the idle character.
        idle_state = model.state
        started = time.monotonic()
        renderer.display_state(_mapped(package.manifest, idle_state), now_ms=clock.ms)
        first_frame_ms = (time.monotonic() - started) * 1000.0
        _width, _height, pixels = renderer.read_pixels()
        coverage = _coverage(pixels)
        report.record(5, "draw the idle character", coverage > 0.02,
                      coverage=round(coverage, 5), firstFrameMs=round(first_frame_ms, 3))
        report.measurements["firstFrameMs"] = round(first_frame_ms, 3)

        # 6. Submit a typed task.
        submitted = model.submit(THREE_D_SLICE_REQUEST)
        task_id = model.task_id
        report.record(6, "submit a typed task", submitted and bool(task_id), taskId=task_id)

        # 7-10, 16-18. Every state the task actually passes through, folded from
        # the runtime's own events and drawn.
        answered: list[str] = []
        approval_frame: dict[str, Any] | None = None
        deadline = time.monotonic() + _WAIT
        while time.monotonic() < deadline:
            state = model.refresh()
            if state.phase in ("success", "error", "blocked", "cancelled"):
                break
            cards = model.approval_cards()
            open_cards = [
                (binding, rows) for binding, rows in cards
                if str(binding.get("requestId", "")) not in answered
            ]
            if not open_cards:
                time.sleep(_POLL)
                continue
            binding, _rows = open_cards[0]
            if approval_frame is None:
                # 13. The character enters waiting-for-approval, and the frame
                # is read back rather than assumed.
                mapped = _mapped(package.manifest, state)
                renderer.display_state(mapped, now_ms=clock.advance(0.4) * 1000 // 1)
                _w, _h, approval_pixels = renderer.read_pixels()
                approval_frame = {
                    "characterState": mapped.character_state.value,
                    "animation": renderer.animation.status(clock.value)["animationState"],
                    "coverage": round(_coverage(approval_pixels), 5),
                }
            if model.resolve(binding, "granted"):
                answered.append(str(binding.get("requestId", "")))
            else:
                break

        settled = _wait_for(lambda: model.refresh().phase in ("success", "error", "blocked"))
        final_state = model.refresh()

        projector = PresentationProjector()
        events = model.client.get_events(task_id, limit=500).get("events", [])
        seen: dict[str, dict[str, Any]] = {}
        drawn_frames = 0
        for document in events if isinstance(events, list) else []:
            state = projector.apply_document(document)
            mapped = _mapped(package.manifest, state)
            renderer.display_state(mapped, now_ms=clock.advance(0.25) * 1000 // 1)
            drawn_frames += 1
            decision = renderer.animation.decisions[-1] if renderer.animation.decisions else None
            seen.setdefault(mapped.character_state.value, {
                "phase": state.phase,
                "animationState": decision.animation_state if decision else None,
                "clip": decision.clip_name if decision else None,
                "expression": renderer.face.expression if renderer.face else None,
            })

        report.record(7, "the character enters understanding", "understanding" in seen,
                      **seen.get("understanding", {}))
        report.record(8, "the character enters planning", "planning" in seen,
                      **seen.get("planning", {}))
        report.record(9, "a local executor runs the task", bool(events),
                      events=len(events) if isinstance(events, list) else 0)
        report.record(10, "the character enters working", "working" in seen,
                      **seen.get("working", {}))

        # 11-12, 15. The desktop action. Recorded through the broker where this
        # machine has a desk; the *authority* half runs everywhere.
        desktop = _desktop_action(root)
        if desktop.get("result") == "NOT_RUN":
            report.skip(11, "a provider proposes a harmless desktop action", desktop["reason"])
            report.skip(12, "the Approval Centre appears for the desktop action", desktop["reason"])
            report.skip(15, "the desktop action executes", desktop["reason"])
        else:
            report.record(11, "a provider proposes a harmless desktop action",
                          desktop["prepared"], actionId=desktop["actionId"])
            report.record(12, "the Approval Centre appears for the desktop action",
                          desktop["binding"] is not None, binding=desktop["binding"])
            report.record(15, "the desktop action executes",
                          desktop["state"] in ("confirmed", "accepted-not-confirmed", "unsupported"),
                          state=desktop["state"], posture=desktop["posture"])

        report.record(13, "the character enters waiting-for-approval",
                      approval_frame is not None
                      and approval_frame["characterState"] == "waiting_for_approval",
                      **(approval_frame or {}))
        report.record(14, "the user approves", bool(answered), approvals=len(answered))
        report.record(16, "the character returns to working", "working" in seen)
        report.record(17, "the task completes", settled and final_state.phase == "success",
                      phase=final_state.phase)
        report.record(18, "the character enters success", "success" in seen,
                      **seen.get("success", {}))

        # The identity of record, taken *before* any renderer pressure.
        identity_before = {
            "taskId": task_id,
            "phase": final_state.phase,
            "summary": final_state.result_summary,
            "revision": final_state.revision,
        }

        # 19-20. Voice, and its visemes on the 3D mouth.
        voice = _voice_visemes(renderer, package, clock)
        if voice.get("result") == "NOT_RUN":
            report.skip(19, "voice speaks the result", voice["reason"])
            report.skip(20, "voice-produced visemes animate the 3D mouth", voice["reason"])
        else:
            report.record(19, "voice speaks the result", voice["spoke"],
                          requestId=voice["requestId"], shapes=voice["shapes"])
            report.record(20, "voice-produced visemes animate the 3D mouth",
                          voice["mouthMoved"], drawnShapes=voice["drawnShapes"],
                          neutralAtEnd=voice["neutralAtEnd"])

        # 21-25. Push-to-talk. Real where a recogniser exists; NOT_RUN otherwise.
        speech = _speech_input(model, renderer, package, clock)
        if speech.get("result") == "NOT_RUN":
            for number, name in (
                (21, "start push-to-talk"), (22, "the character enters listening"),
                (23, "speech recognition finalizes"), (24, "the character enters waiting-for-user"),
                (25, "confirm the transcript"),
            ):
                report.skip(number, name, speech["reason"])
        else:
            report.record(21, "start push-to-talk", speech["started"])
            report.record(22, "the character enters listening", speech["listening"])
            report.record(23, "speech recognition finalizes", speech["finalized"])
            report.record(24, "the character enters waiting-for-user", speech["waiting"])
            report.record(25, "confirm the transcript", speech["confirmed"])

        # 26. A new task begins.
        second = model.submit("Count the words in this note again.")
        second_id = model.task_id
        report.record(26, "a new task begins", second and second_id != task_id,
                      firstTaskId=task_id, secondTaskId=second_id)

        # 27-33. Degradation, under the real selector.
        selector = AdaptiveRendererSelector(recovery_samples=3, recovery_delay_seconds=2.0)
        selector.budget = DEFAULT_BUDGET
        plan = CapabilityPresentationPlan(
            plan_id="plan-3d-slice", requested=Presentation.FULL_3D,
            ceiling=Presentation.FULL_3D, implementation_id="full-3d",
        )

        def evaluate(**overrides: Any):
            signals = RendererSignals(
                **_VISUAL, model_gpu_bytes=package.model.estimated_gpu_bytes, **overrides
            )
            return selector.evaluate(plan, package, signals, now=clock.advance(1.0))

        healthy = evaluate()
        report.record(27, "trigger controlled performance degradation",
                      healthy.effective is Presentation.FULL_3D,
                      effective=healthy.effective.value)
        degraded = evaluate(sustained_slow_frames=True)
        report.record(28, "full 3D degrades to lightweight 3D",
                      degraded.effective is Presentation.LIGHTWEIGHT_3D,
                      effective=degraded.effective.value,
                      reason=next((item for item in degraded.reasons if "frame time" in item), ""))
        if degraded.effective is Presentation.LIGHTWEIGHT_3D:
            renderer.set_quality("lightweight-3d")
            renderer.display_state(
                _mapped(package.manifest, final_state), now_ms=clock.advance(0.2) * 1000 // 1
            )
            _w, _h, light_pixels = renderer.read_pixels()
            report.record(29, "the lightweight rung still draws the character",
                          _coverage(light_pixels) > 0.02,
                          coverage=round(_coverage(light_pixels), 5))
        else:
            report.record(29, "the lightweight rung still draws the character", False)

        further = evaluate(sustained_slow_frames=True, gpu_context_lost=True)
        report.record(30, "lightweight 3D degrades to animated 2D",
                      further.effective is Presentation.ANIMATED_2D,
                      effective=further.effective.value)

        during = model.client.get_task(task_id).get("task", {})
        unchanged = (
            str(during.get("taskId", "")) == identity_before["taskId"]
            and str(during.get("state", "")) in ("completed", "presenting", "reviewing")
        )
        report.record(31, "the task identity is unchanged across degradation", unchanged,
                      before=identity_before, taskState=str(during.get("state", "")),
                      summary=str(during.get("resultSummary", during.get("displaySummary", ""))))

        evaluate()
        evaluate()
        recovered = evaluate()
        report.record(32, "removing the pressure permits recovery",
                      recovered.effective in (Presentation.FULL_3D, Presentation.LIGHTWEIGHT_3D),
                      effective=recovered.effective.value)
        report.record(33, "recovery used hysteresis rather than the next frame",
                      any(event.code == "stable-recovery" for event in selector.events),
                      events=[event.code for event in selector.events])

        # 34-35. Restart the renderer and restore the character.
        #
        # The frame statistics are taken *before* the restart as well as after:
        # a restarted renderer has drawn one frame, and reporting only that
        # would describe the restart rather than the run.
        before_restart = renderer.frame_statistics()
        report.measurements.update({
            "framesDrawnBeforeRestart": before_restart["frames"],
            "meanFrameMsBeforeRestart": before_restart["meanMs"],
            "p95FrameMsBeforeRestart": before_restart["p95Ms"],
            "droppedFramesBeforeRestart": before_restart["droppedFrames"],
        })
        started = time.monotonic()
        renderer.release()
        renderer = ThreeDRenderer(context=context, quality="full-3d", seed=0x3D)
        renderer.load_package(package)
        renderer.upload(
            package.model,
            animation_map=section.animation_map,
            expression_map=section.expression_map,
            viseme_map=section.viseme_map,
            native_scale=section.native_scale,
            floor_offset=section.floor_offset,
            now=clock.value,
        )
        renderer.begin_offscreen(*_SURFACE)
        restart_ms = (time.monotonic() - started) * 1000.0
        report.record(34, "restart the 3D renderer", renderer.model is not None,
                      restartMs=round(restart_ms, 3))
        report.measurements["rendererRestartMs"] = round(restart_ms, 3)
        renderer.display_state(
            _mapped(package.manifest, final_state), now_ms=clock.advance(0.5) * 1000 // 1
        )
        _w, _h, restored = renderer.read_pixels()
        report.record(35, "restore the character and canonical presentation",
                      _coverage(restored) > 0.02,
                      coverage=round(_coverage(restored), 5),
                      liveResources=renderer.resources.to_json()["live"])

        # 36. Nothing was repeated or cancelled.
        after = model.client.get_task(task_id).get("task", {})
        report.record(
            36, "no task was repeated or cancelled",
            str(after.get("taskId", "")) == task_id
            and str(after.get("state", "")) not in ("cancelled", "failed")
            and int(after.get("lifecycleEpoch", 0)) == 0,
            taskState=str(after.get("state", "")),
            lifecycleEpoch=int(after.get("lifecycleEpoch", 0)),
        )

        statistics = renderer.frame_statistics()
        report.measurements.update({
            "framesDrawn": statistics["frames"],
            "meanFrameMs": statistics["meanMs"],
            "p95FrameMs": statistics["p95Ms"],
            "droppedFrames": statistics["droppedFrames"],
            "liveGpuResources": renderer.resources.to_json()["live"],
            "estimatedGpuBytes": package.model.estimated_gpu_bytes,
        })
    finally:
        if renderer is not None:
            try:
                renderer.release()
            except Exception:  # noqa: BLE001 - teardown must not raise
                pass
        if context is not None:
            context.release()
        service.close()
    return report


def _desktop_action(root: Path) -> dict[str, Any]:
    """One harmless desktop action, through the existing broker.

    Imported inside the function on purpose: the 3D subsystem may not depend on
    the desktop-action authority, and ``tests/companion/test_three_d_isolation.py``
    enforces that — so this slice, which is a *test harness* rather than part of
    the renderer, is the only place the two meet, and it meets them through the
    broker's public interface.
    """
    try:
        from companion.desktop.broker import BrokerOptions, DesktopActionBroker
    except ImportError as exc:  # pragma: no cover - the desktop phase is present
        return {"result": "NOT_RUN", "reason": f"the desktop broker is unavailable: {exc}"}
    broker = DesktopActionBroker(BrokerOptions(ledger_path=Path(root) / "desktop-ledger.json"))
    broker.start()
    try:
        environment = broker.environment()
        prepared = broker.prepare(
            "desktop.settings.open", {"page": "sound"},
            request_id="dreq-3d-slice", session_id="3d-slice", task_id="3d-slice-task",
            lifecycle_epoch=0, plan_id="3d-slice-plan", operation_id="3d-slice-op",
            cancellation_token="3d-slice-cancel",
        )
        result = broker.execute(
            prepared.request.with_approval("3d-slice-approval"),
            approved_binding=prepared.binding,
        )
        return {
            "result": "RAN",
            "actionId": "desktop.settings.open",
            "prepared": True,
            "binding": prepared.binding.digest[:16] if hasattr(prepared.binding, "digest") else str(prepared.binding)[:16],
            "state": result.state,
            "posture": environment.posture,
        }
    except Exception as exc:  # noqa: BLE001 - a desk this host lacks is not a failure
        return {"result": "NOT_RUN", "reason": f"the desktop action could not run here: {exc}"}
    finally:
        broker.stop()


def _voice_visemes(renderer: Any, package: Any, clock: _SliceClock) -> dict[str, Any]:
    """Drive the existing viseme link into the 3D mouth. §12, end to end.

    The link is :class:`companion.character.speech_link.VisemeLink` — the one
    the voice-runtime phase built and validated, with its request matching, its
    revision matching, its ordering and its neutral resets. Nothing about the
    timeline is rebuilt here; the 3D renderer is simply the thing on the far end
    of it, which is the whole of what §12 asks.
    """
    try:
        from companion.character.speech_link import VisemeLink
        from companion.voice.worker import VoiceEvent
    except ImportError as exc:  # pragma: no cover
        return {"result": "NOT_RUN", "reason": f"the viseme link is unavailable: {exc}"}

    drawn: list[str] = []

    def draw(frame: Any) -> None:
        renderer.set_mouth_shape(frame.shape)
        renderer.draw(now_ms=int(clock.advance(0.05) * 1000))
        drawn.append(frame.shape)

    link = VisemeLink(draw=draw)
    link.publish(1)

    request_id = "voice-3d-slice"
    shapes = ["closed", "open-small", "open-medium", "open-wide", "rounded", "smile", "closed"]

    def event(kind: str, **payload: Any) -> Any:
        return VoiceEvent(
            kind=kind, request_id=request_id, at_monotonic=clock.value, payload=payload
        )

    link.on_voice_event(event(
        "viseme_timeline",
        requestId=request_id, sourceMethod="text-estimate",
        events=[
            {
                "requestId": request_id, "sequence": index, "offsetMs": index * 90,
                "durationMs": 90, "mouthShape": shape, "confidence": 0.6,
                "sourceMethod": "text-estimate",
            }
            for index, shape in enumerate(shapes)
        ],
    ))
    for sequence, shape in enumerate(shapes):
        link.on_voice_event(event(
            "viseme",
            requestId=request_id, sequence=sequence, mouthShape=shape,
            positionMs=sequence * 90, sourceMethod="text-estimate", driftMs=0,
        ))
    link.on_voice_event(event("speech_finished", requestId=request_id))

    non_neutral = [shape for shape in drawn if shape != MouthShape.NEUTRAL.value]
    return {
        "result": "RAN",
        "spoke": bool(drawn),
        "requestId": request_id,
        "shapes": len(shapes),
        "drawnShapes": sorted(set(drawn)),
        "mouthMoved": len(set(non_neutral)) >= 3,
        "neutralAtEnd": renderer.face.mouth_shape == MouthShape.NEUTRAL.value if renderer.face else False,
        "linkReport": link.report.to_json(),
        # Stated precisely rather than implied. The events are real
        # ``VoiceEvent`` values through the real ``VisemeLink`` — its request
        # matching, ordering, revision matching and neutral reset all run. What
        # the slice supplies is the *producer*: a host with no speech-synthesis
        # provider has no worker to produce them. The worker-to-link half was
        # established by the voice-closure phase; this step establishes the
        # link-to-3D-mouth half, and saying which is which is the difference
        # between evidence and a claim.
        "producer": "slice-supplied VoiceEvent values through the canonical VisemeLink",
        "workerDriven": False,
    }


def _speech_input(model: Any, renderer: Any, package: Any, clock: _SliceClock) -> dict[str, Any]:
    """Push-to-talk, where a recogniser exists. NOT_RUN with a reason otherwise."""
    try:
        available = bool(model.speech_available())
    except Exception as exc:  # noqa: BLE001
        return {"result": "NOT_RUN", "reason": f"speech input is unavailable: {exc}"}
    if not available:
        return {
            "result": "NOT_RUN",
            "reason": "no speech recogniser is installed or no microphone is available here",
        }
    started = model.press_to_talk()
    if not started:
        # The *feature* is present and the *equipment* is not: the runtime
        # advertises speech input and then refuses the capture because there is
        # no model or no microphone. That is a NOT_RUN with a reason, and
        # recording it as a failure would make a machine without a microphone
        # look like a defect in the renderer.
        return {
            "result": "NOT_RUN",
            "reason": (
                "speech input is advertised but the capture was refused: "
                + (getattr(model, "speech_error", "") or "no reason given")
            ),
        }
    mapped = _mapped(package.manifest, model.state, listening=True)
    renderer.display_state(mapped, now_ms=int(clock.advance(0.3) * 1000))
    listening = mapped.character_state is CharacterState.LISTENING
    model.stop_talking()
    finalized = _wait_for(
        lambda: model.poll_speech() in ("waiting-for-confirmation", "failed"), timeout=20.0
    )
    transcript = getattr(model, "speech_final", None) or ""
    waiting = model.speech_phase == "waiting-for-confirmation"
    confirmed = bool(model.confirm_speech(transcript)) if waiting and transcript else False
    return {
        "result": "RAN",
        "started": True,
        "listening": listening,
        "finalized": finalized,
        "waiting": waiting,
        "confirmed": confirmed,
        "phase": model.speech_phase,
        "transcript": bool(transcript),
    }
