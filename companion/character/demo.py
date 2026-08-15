# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Provider-free renderer vertical slice over the real runtime-core record."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from companion.demo import run_demo as run_runtime_demo
from companion.store import CompanionStore

from .adaptation import CapabilityPresentationPlan, Presentation, RendererSignals
from .bubble import BubbleKind, SpeechBubbleController, layout_bubble
from .controller import CharacterRendererController
from .defaults import default_character_path
from .lipsync import LipSyncEvent, MouthShape
from .mapper import StateMapperInput, map_character_state
from .modes import DEFAULT_MODE
from .package import validate_package_directory
from .performance import measure_renderer_performance
from .positioning import Display, PixelRect, Placement, place_character
from .schema import PackageTrustState
from .static_renderer import StaticImageRenderer


@dataclass
class CharacterDemoReport:
    steps: list[dict[str, Any]] = field(default_factory=list)
    passed: bool = True
    failures: list[str] = field(default_factory=list)
    performance: dict[str, Any] | None = None
    # The slice claims the rung it exercised, never a capability it did not
    # probe: no GL context exists here, so 3D is shipped-but-unexercised.
    three_d: dict[str, Any] = field(default_factory=lambda: {
        "shipped": True,
        "exercisedInThisSlice": False,
        "validatedBy": "companion/character/three_d_slice.py",
    })

    def record(self, number: int, name: str, ok: bool, **evidence: Any) -> None:
        self.steps.append({"step": number, "name": name, "ok": bool(ok), **evidence})
        if not ok:
            self.passed = False
            self.failures.append(f"step {number} ({name})")

    def to_json(self) -> dict[str, Any]:
        return {
            "slice": "companion-character-renderer",
            "passed": self.passed,
            "steps": self.steps,
            "failures": self.failures,
            "performance": self.performance,
            "network": "none",
            "commercialProvider": "none",
            "threeDimensionalRenderer": self.three_d,
        }


def run_character_demo(
    root: Path,
    *,
    package_path: Path | None = None,
    include_performance: bool = False,
) -> CharacterDemoReport:
    report = CharacterDemoReport()
    root = Path(root)
    runtime_root = root / "runtime"
    runtime_report = run_runtime_demo(runtime_root)
    report.record(1, "start the companion runtime", runtime_report.passed, runtimeSlice=runtime_report.to_json())

    controller = CharacterRendererController()
    report.record(2, "start the UX character surface", True, surface="headless-safe renderer controller")
    package = validate_package_directory(
        package_path or default_character_path(), trust_state=PackageTrustState.BUILT_IN
    )
    controller.load_package(package)
    report.record(3, "load the validated default package", bool(package.package_digest), package=package.to_json())
    report.three_d = {
        "shipped": True,
        "exercisedInThisSlice": False,
        "packageSupports3d": package.model is not None,
        "defaultMode": DEFAULT_MODE.value,
        "presentationExercised": Presentation.ANIMATED_2D.value,
        "validatedBy": "companion/character/three_d_slice.py",
    }

    static = StaticImageRenderer()
    static.load_package(package)
    starting = map_character_state(package.manifest, StateMapperInput(presentation_phase="starting", status_text="Starting Bunny."))
    static_frame = static.display_state(starting)
    report.record(4, "display the static fallback", static_frame is not None, frame=static_frame.to_json() if static_frame else None)

    plan = CapabilityPresentationPlan(
        "demo-capability-plan", Presentation.ANIMATED_2D, Presentation.ANIMATED_2D,
        "start", "animated-2d", ("simulated development presentation plan",),
    )
    display = Display("display-1", PixelRect(0, 0, 1920, 1080), primary=True)
    position = place_character([display], size=(288, 288), placement=Placement.BOTTOM_RIGHT)
    controller.set_position(position)
    idle = map_character_state(package.manifest, StateMapperInput(presentation_phase="idle", status_text="Bunny is ready."))
    idle_snapshot = controller.apply(idle, plan, RendererSignals(), now=0, now_ms=0)
    report.record(
        5,
        "enter idle state",
        idle_snapshot.frame is not None
        and idle_snapshot.mapped_state is not None
        and idle_snapshot.mapped_state.character_state.value == "idle",
        snapshot=idle_snapshot.to_json(),
    )

    store = CompanionStore(runtime_root / "store")
    session_ids = store.session_ids()
    tasks = tuple(store.tasks(session_ids[0])) if session_ids else ()
    task = tasks[0] if tasks else None
    events = store.read_events(session_ids[0], task_id=task.task_id) if task else ()
    event_types = [event.event_type for event in events]
    report.record(6, "submit a harmless task", task is not None and "task_created" in event_types,
                  taskId=task.task_id if task else None)

    planning = map_character_state(package.manifest, StateMapperInput(presentation_phase="planning", status_text="Preparing the plan."))
    planning_snapshot = controller.apply(planning, plan, RendererSignals(), now=0.1, now_ms=100)
    report.record(7, "transition to planning", "planning_started" in event_types and planning_snapshot.mapped_state.character_state.value == "planning")

    working = map_character_state(package.manifest, StateMapperInput(presentation_phase="working", tool_activity="typing", status_text="Working."))
    working_snapshot = controller.apply(working, plan, RendererSignals(), now=0.2, now_ms=200)
    report.record(8, "transition to working", "operation_started" in event_types and working_snapshot.mapped_state.character_state.value in {"working", "typing"})
    progress_events = [event for event in events if event.event_type == "operation_progress"]
    report.record(9, "show tool progress in the task panel", bool(progress_events), progressEvents=len(progress_events))
    observations = [event for event in events if event.event_type == "reviewer_observation"]
    report.record(10, "show a reviewer observation", bool(observations),
                  observation=observations[0].payload.get("summary") if observations else None)

    approvals = [event for event in events if event.event_type == "approval_requested"]
    approval = map_character_state(package.manifest, StateMapperInput(
        presentation_phase="waiting_for_approval", approval_pending=True, status_text="Approval is required."
    ))
    controller.apply(approval, plan, RendererSignals(), now=0.3, now_ms=300)
    report.record(11, "display an approval request", bool(approvals) and approval.bubble_visible)
    bubbles = SpeechBubbleController()
    bubble_state = bubbles.update(
        str(approvals[0].payload.get("action") if approvals else "Approval is required"),
        kind=BubbleKind.APPROVAL, final=True, now=0.3,
    )
    layout = layout_bubble(bubble_state, package.manifest.bubble_anchor, position.character, [display])
    controller.attach_bubble(bubble_state, layout)
    report.record(12, "anchor the approval bubble", bubble_state.persistent and layout.display_id == display.display_id,
                  layout=layout.to_json())
    resolved = [event for event in events if event.event_type == "approval_resolved"]
    report.record(13, "resolve the approval", any(event.payload.get("decision") == "granted" for event in resolved))

    speaking = map_character_state(package.manifest, StateMapperInput(
        presentation_phase="presenting_result", speaking=True, status_text="The task completed successfully."
    ))
    controller.apply(speaking, plan, RendererSignals(), now=0.4, now_ms=400)
    report.record(14, "transition to speaking", speaking.character_state.value == "speaking")
    lip_events = [
        LipSyncEvent(0, MouthShape.CLOSED),
        LipSyncEvent(100, MouthShape.OPEN_SMALL),
        LipSyncEvent(220, MouthShape.OPEN_WIDE),
        LipSyncEvent(360, MouthShape.ROUNDED),
        LipSyncEvent(500, MouthShape.NEUTRAL),
    ]
    controller.start_lip_sync(lip_events)
    lip = controller.advance_lip_sync(220, audio_clock_ms=225)
    lip_frame = controller.renderer.frame if controller.renderer is not None else None
    report.record(
        15,
        "play generic lip-sync events",
        lip.shape is MouthShape.OPEN_WIDE
        and not lip.drift_detected
        and lip_frame is not None
        and lip_frame.asset_id == "speaking-open",
        lipSync=lip.to_json(),
        renderedAsset=lip_frame.asset_id if lip_frame else None,
    )
    caption = bubbles.update("The task completed successfully.", partial=False, final=True, now=0.5)
    caption_layout = layout_bubble(caption, package.manifest.bubble_anchor, position.character, [display])
    controller.attach_bubble(caption, caption_layout)
    report.record(16, "display synchronized caption text", caption.final and caption.visible,
                  bubble=caption.to_json())
    success = map_character_state(package.manifest, StateMapperInput(presentation_phase="success", status_text=caption.text))
    success_snapshot = controller.apply(success, plan, RendererSignals(), now=0.6, now_ms=600)
    report.record(17, "transition to success", success_snapshot.mapped_state.character_state.value == "success")

    pressure = RendererSignals(memory_pressure=True, available_memory_bytes=512 * 1024 * 1024)
    pressured = controller.apply(success, plan, pressure, now=1.0, now_ms=1000)
    report.record(18, "introduce resource pressure through the capability presentation plan", pressure.memory_pressure)
    report.record(19, "degrade animated 2D to static", pressured.presentation.effective is Presentation.STATIC_IMAGE,
                  presentation=pressured.presentation.to_json())
    recovered = pressured
    for index in range(3):
        recovered = controller.apply(success, plan, RendererSignals(), now=3.0 + index, now_ms=3000 + index * 1000)
    report.record(20, "restore only after hysteresis", recovered.presentation.effective is Presentation.ANIMATED_2D,
                  presentation=recovered.presentation.to_json())

    tip_before = store.tip(session_ids[0]) if session_ids else (0, "")
    restarted = controller.restart_renderer(now_ms=7000)
    report.record(21, "restart the renderer", any(event.get("eventType") == "renderer.restarted" for event in restarted.events))
    restored = (
        restarted.renderer_status is not None
        and restarted.renderer_status.get("loadedPackageId") == package.manifest.package_id
        and restarted.mapped_state is not None
        and restarted.mapped_state.character_state.value == "success"
        and restarted.position is not None
    )
    report.record(22, "restore package, position and current state", restored, snapshot=restarted.to_json())
    tip_after = store.tip(session_ids[0]) if session_ids else (0, "")
    unchanged = task is not None and store.load_task(task.session_id, task.task_id).to_json() == task.to_json()
    report.record(23, "confirm task runtime survives renderer restart", tip_before == tip_after and unchanged,
                  streamTipBefore=tip_before, streamTipAfter=tip_after, taskState=task.state if task else None)
    if include_performance:
        report.performance = measure_renderer_performance(package)
    return report
