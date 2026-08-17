# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§20's installed slice: a real service, a real approval, a real character.

The twenty-four steps run against an actual :class:`companion.service.CompanionService`
over its socket — the same runtime, the same protocol, the same approval binding
check as :mod:`companion.vertical_slice`. What this adds is the character: a
validated package, a static idle frame, animation, a bubble anchored to the
character, generic lip-sync, two degradations, hysteretic recovery and a
renderer restart.

Two things it reports rather than pretends.

**No compositor runs here.** Everything below the widgets is exercised, because
:class:`companion.character.surface.CharacterPresenter` is the whole of the
character's behaviour and imports no GTK. The widget layer is marked
``NOT_RUN`` in the report rather than assumed to work — §21's rule applied to
functionality as well as to measurement.

**The task is checked, not assumed.** Step 24 does not merely observe that the
task looks finished: it compares the task id, the state and the result summary
recorded *before* the renderer was degraded and restarted against the same
fields afterwards, and fails if the renderer's troubles reached them.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
import time
from typing import Any

from companion.character.lipsync import LipSyncEvent, MouthShape
from companion.character.positioning import Display, PixelRect
from companion.character.surface import CharacterPresenter
from companion.gtk_shell import CompanionViewModel
from companion.presentation import (
    PresentationProjector,
    PresentationRecommendation,
    PresentationState,
)
from companion.protocol import CompanionClient, CompanionClientError
from companion.service import CompanionService, ServiceOptions

__all__ = ["CHARACTER_SLICE_REQUEST", "CharacterSliceReport", "run_character_slice"]

#: A harmless local request that reaches every state the slice needs: an
#: operation, a validation step the first plan omits so the reviewer has
#: something true to say, and a notice that requires consent.
CHARACTER_SLICE_REQUEST = (
    "Count the words in this note, validate the count, and notify me when it is done."
)

_WAIT = 45.0
_POLL = 0.05
_DISPLAY = Display("slice-display", PixelRect(0, 0, 1920, 1080), primary=True)

#: Signals that make a visual renderer possible on a host with no display. The
#: slice needs the *renderer* exercised; whether this particular machine has a
#: monitor is not the property under test, and pretending it does anywhere else
#: would be dishonest — so the override is explicit, named, and confined here.
_VISUAL = {
    "display_available": True,
    "graphics_ready": True,
    "available_memory_bytes": 8 * 1024 ** 3,
    "gpu_available": True,
}

#: The allowance a machine with a display would receive.
#:
#: Substituted for the projection's own recommendation, which on a host with no
#: monitor is correctly ``text-only`` — and a text-only ceiling makes every
#: visual step of this slice unreachable. The substitution is confined to
#: :func:`_visual_state`, named in the report, and is the *only* place the slice
#: departs from what the runtime actually said. Everything else — the task, the
#: approval, the events, the result — is the runtime's own.
_VISUAL_RECOMMENDATION = PresentationRecommendation(
    implementation="animated-2d",
    eligible="full-3d",
    limited_by_implementation=True,
    placement="docked",
    captions=True,
    plan_id="plan-character-slice",
    reasons=("the slice simulates a machine with a display; this host has none",),
)


def _visual_state(state: PresentationState) -> PresentationState:
    """The runtime's projection, with a display it does not have."""
    return replace(state, recommendation=_VISUAL_RECOMMENDATION)


@dataclass
class CharacterSliceReport:
    steps: list[dict[str, Any]] = field(default_factory=list)
    passed: bool = True
    failures: list[str] = field(default_factory=list)
    not_run: list[str] = field(default_factory=list)

    def record(self, number: int, name: str, ok: bool, **evidence: Any) -> None:
        self.steps.append({"step": number, "name": name, "ok": bool(ok), **evidence})
        if not ok:
            self.passed = False
            self.failures.append(f"step {number} ({name})")

    def skip(self, number: int, name: str, reason: str, **evidence: Any) -> None:
        """Record a step this host cannot run. Never counted as a pass."""
        self.steps.append({
            "step": number, "name": name, "ok": None, "result": "NOT_RUN",
            "reason": reason, **evidence,
        })
        self.not_run.append(f"step {number} ({name}): {reason}")

    def to_json(self) -> dict[str, Any]:
        return {
            "slice": "companion-character-renderer-installed",
            "passed": self.passed,
            "steps": sorted(self.steps, key=lambda item: item["step"]),
            "failures": self.failures,
            "notRun": self.not_run,
            "network": "none",
            "provider": "none",
            "credentials": "none",
            "threeDimensionalRenderer": {
                "shipped": True,
                "exercisedInThisSlice": False,
                "validatedBy": "companion/character/three_d_slice.py",
            },
            "gtkWidgetsExercised": False,
        }


class _SliceClock:
    """A clock that only ever goes forward.

    The selector measures its recovery delay as ``now - last_degraded_at``, so a
    slice that mixed ``time.monotonic()`` with small synthetic values made that
    difference negative and recovery unreachable for the rest of the run. One
    counter, advanced explicitly, removes the whole class of mistake.
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
    """Poll until something is true, or give up.

    A slice that gave up says *why* at the step that noticed. The subtle case
    this exists for: :meth:`CompanionViewModel.refresh` catches a transport
    error and returns the state it already had, so a client that has lost its
    connection keeps answering with a stale phase for ever. Without this the
    slice would report "the task did not reach success" for a task that had
    reached it perfectly well, and the real fault — the client could not
    reconnect — would be nowhere in the output.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(_POLL)
    return False


def _transport_fault(model) -> str:
    """The client's own connection error, if it has one."""
    return getattr(model, "connection_error", "") or ""


def _states_from_record(
    model: CompanionViewModel, presenter: CharacterPresenter, clock: "_SliceClock"
) -> dict[str, dict[str, Any]]:
    """Every character state the task actually passed through.

    One canonical event at a time, folded through the projection and then
    through the mapper — the architecture in §2 run end to end, and the only
    way to answer "did the character reach planning" without a stopwatch.
    """
    events = model.client.get_events(model.task_id, limit=500).get("events", [])
    projector = PresentationProjector()
    seen: dict[str, dict[str, Any]] = {}
    for index, document in enumerate(events if isinstance(events, list) else []):
        state = projector.apply_document(document)
        update = presenter.update(
            _visual_state(state), now=clock.advance(0.05), now_ms=clock.ms,
            signal_overrides=_VISUAL,
        )
        mapped = update.snapshot.mapped_state
        seen.setdefault(mapped.character_state.value, {
            "phase": state.phase,
            "animation": mapped.animation,
            "progress": state.progress,
            "frame": update.frame.asset_id if update.frame else None,
        })
    return seen


def _answer_approvals(model: CompanionViewModel, presenter: CharacterPresenter,
                      clock: "_SliceClock") -> tuple[list[str], dict[str, Any]]:
    """Answer every question the runtime asks, recording the first bubble."""
    answered: list[str] = []
    anchored: dict[str, Any] = {}
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
        if not anchored:
            update = presenter.update(
                _visual_state(state), now=clock.advance(), signal_overrides=_VISUAL
            )
            anchored = {
                "kind": update.bubble.kind.value,
                "persistent": update.bubble.persistent,
                "layout": update.layout.to_json() if update.layout else None,
                "characterState": update.snapshot.mapped_state.character_state.value,
            }
        if model.resolve(binding, "granted"):
            answered.append(str(binding.get("requestId", "")))
        else:
            break
    return answered, anchored


def _pressure_sequence(presenter: CharacterPresenter, state: PresentationState,
                       clock: "_SliceClock") -> tuple[list[dict[str, Any]], bool]:
    """Steps 17-21 as records, and whether the renderer stayed healthy.

    The records are returned rather than written so the caller can run the
    sequence again after an incidental renderer fault — see the comment at
    the call site for why one fault earns one clearly-recorded retry.
    """
    rows: list[dict[str, Any]] = []
    healthy = True

    animated = presenter.update(_visual_state(state), now=clock.advance(),
                                signal_overrides=_VISUAL)
    healthy &= animated.renderer_healthy
    rows.append(dict(
        number=17, name="trigger controlled presentation pressure",
        ok=animated.effective_presentation == "animated-2d",
        before=animated.effective_presentation,
        presentation=animated.effective_presentation,
        # Why the selector landed where it did. Without this the failure is a
        # step number: this pair has read
        # `['step 17 ...', 'step 21 ...']` on and off for four phases, and the
        # selector has been recording its own reasons the whole time. A
        # degradation that cannot say which rule fired is a degradation nobody
        # can act on.
        reasons=list(animated.snapshot.presentation.reasons),
        heldByHysteresis=animated.snapshot.presentation.held_by_hysteresis,
        rendererHealthy=animated.renderer_healthy,
    ))
    to_static = presenter.update(
        _visual_state(state), now=clock.advance(),
        signal_overrides={**_VISUAL, "memory_pressure": True},
    )
    healthy &= to_static.renderer_healthy
    rows.append(dict(
        number=18, name="degrade animated 2D to static",
        ok=to_static.effective_presentation == "static-image",
        presentation=to_static.effective_presentation,
        events=[item.get("eventType") if isinstance(item, dict) else str(item)
                for item in to_static.events],
    ))
    to_text = presenter.update(
        _visual_state(state), now=clock.advance(),
        signal_overrides={**_VISUAL, "display_available": False},
    )
    healthy &= to_text.renderer_healthy
    rows.append(dict(
        number=19, name="degrade static to text-only",
        ok=to_text.effective_presentation == "text-only",
        presentation=to_text.effective_presentation,
        description=to_text.description,
        captionStillPresent=bool(to_text.bubble.text),
    ))

    held = presenter.update(_visual_state(state), now=clock.advance(),
                            signal_overrides=_VISUAL)
    healthy &= held.renderer_healthy
    rows.append(dict(
        number=20, name="remove the pressure",
        ok=held.effective_presentation != "animated-2d",
        immediatelyAfterRemoval=held.effective_presentation,
        presentation=held.effective_presentation,
        note="recovery must not be immediate; degradation was",
    ))
    recovered = held
    for index in range(1, 6):
        recovered = presenter.update(
            _visual_state(state), now=clock.advance(1.5), signal_overrides=_VISUAL
        )
        healthy &= recovered.renderer_healthy
        if recovered.effective_presentation == "animated-2d":
            break
    rows.append(dict(
        number=21, name="recover only after hysteresis",
        ok=recovered.effective_presentation == "animated-2d" and index >= 2,
        samplesBeforeRecovery=index,
        presentation=recovered.effective_presentation,
    ))
    return rows, healthy


def run_character_slice(root: Path) -> CharacterSliceReport:
    """Run the whole installed character slice under ``root``."""
    report = CharacterSliceReport()
    root = Path(root)
    endpoint = root / "runtime" / "runtime.sock"

    # 1. Start the canonical companion service.
    service = CompanionService(ServiceOptions(
        # Longer than the slice's own answering deadline, so the loop always
        # wins the race rather than the runtime's consent lapsing underneath it.
        root=root, endpoint=endpoint, machine="laptop", consent_wait_seconds=_WAIT * 3,
    )).start()
    presenter: CharacterPresenter | None = None
    clock = _SliceClock()
    try:
        report.record(1, "start the canonical companion service", True,
                      endpoint=service.server.describe()["endpoint"])

        # 2. Start the client. The window's behaviour without its widgets.
        model = CompanionViewModel(client=CompanionClient(endpoint, timeout=15.0))
        connected = model.connect()
        report.record(2, "start the GTK client's view model", connected)
        report.skip(
            0, "render the GTK widget layer",
            "no compositor is available on this host; CharacterPresenter is exercised instead",
        )

        # 3. Load the validated default character.
        presenter = CharacterPresenter(root, display=_DISPLAY)
        package = presenter.package
        report.record(
            3, "load the validated default character package",
            package.trust_state.value == "built-in" and bool(package.package_digest),
            packageId=package.manifest.package_id,
            digest=package.package_digest[:16],
            trustState=package.trust_state.value,
            creatorTrusted=package.to_json()["creatorTrusted"],
            assets=len(package.manifest.assets),
        )

        # 4. Display the static idle state.
        idle = presenter.update(
            _visual_state(model.state), now=clock.advance(), now_ms=clock.ms,
            signal_overrides={**_VISUAL, "reduced_motion": True},
        )
        report.record(
            4, "display a static idle state",
            idle.effective_presentation == "static-image"
            and idle.frame is not None
            and idle.snapshot.mapped_state.character_state.value in ("idle", "starting"),
            presentation=idle.effective_presentation,
            frame=idle.frame.asset_id if idle.frame else None,
            description=idle.description,
        )

        # 5. Submit a harmless local task.
        submitted = model.submit(CHARACTER_SLICE_REQUEST)
        task_id = model.task_id
        report.record(5, "submit a harmless local task", submitted and bool(task_id), taskId=task_id)

        # 9-12. Reviewer, approval, anchored bubble, canonical resolution.
        answered, anchored = _answer_approvals(model, presenter, clock)
        state = model.refresh()
        observations = model.state.observations
        report.record(
            9, "display a reviewer observation", bool(observations),
            observations=[item.summary for item in observations][:3],
            authority="observation only; the renderer gives reviewers no control",
        )
        report.record(
            10, "display an approval request", bool(anchored),
            bubbleKind=anchored.get("kind"),
            characterState=anchored.get("characterState"),
        )
        report.record(
            11, "anchor the approval bubble to the character",
            bool(anchored.get("layout")) and anchored.get("persistent") is True,
            layout=anchored.get("layout"),
            persistent=anchored.get("persistent"),
        )
        report.record(
            12, "resolve the approval through the canonical runtime",
            len(answered) >= 1,
            approvals=answered,
            note="the renderer never validated the approval; it only displayed it",
        )

        finished = _wait_for(lambda: model.refresh().phase in ("success", "error", "blocked", "cancelled"))
        state = model.state

        # 6-8. Planning, working and progress, reconstructed by *folding the
        # record* rather than by polling. Polling samples whatever the surface
        # happened to be showing when the loop came round, which on a fast local
        # task can miss a phase entirely — and "we did not see it" is not the
        # same claim as "it did not happen". Folding every event prefix through
        # the canonical projection and then through the mapper asks the real
        # question: did the character pass through this state.
        seen = _states_from_record(model, presenter, clock)
        report.record(6, "transition to planning", "planning" in seen, evidence=seen.get("planning"))
        report.record(
            7, "transition to working",
            any(name in seen for name in ("working", "typing", "researching")),
            evidence=seen.get("working") or seen.get("typing") or seen.get("researching"),
        )
        report.record(
            8, "display progress",
            any(float(item.get("progress") or 0) > 0 for item in seen.values()),
            observedStates=sorted(seen),
            method="folded from the canonical event stream, not sampled",
        )


        # 13-15. Speaking, lip-sync, captions.
        speaking = presenter.update(
            _visual_state(state), speaking=True, now=clock.advance(), signal_overrides=_VISUAL
        )
        report.record(
            13, "enter the speaking state",
            speaking.snapshot.mapped_state.character_state.value == "speaking",
            characterState=speaking.snapshot.mapped_state.character_state.value,
        )
        timeline = [
            LipSyncEvent(0, MouthShape.CLOSED),
            LipSyncEvent(120, MouthShape.OPEN_SMALL),
            LipSyncEvent(260, MouthShape.OPEN_WIDE),
            LipSyncEvent(400, MouthShape.ROUNDED),
            LipSyncEvent(560, MouthShape.CLOSED),
        ]
        presenter.start_lip_sync(timeline)
        shapes = []
        for moment in (0, 130, 270, 410, 570):
            status = presenter.advance_lip_sync(moment, audio_clock_ms=moment)
            shapes.append(status.shape.value)
        final = presenter.advance_lip_sync(900, audio_clock_ms=900)
        report.record(
            14, "play generic lip-sync events",
            len(set(shapes)) > 1 and final.shape.value == "neutral" and not final.drift_detected,
            shapes=shapes,
            returnedToNeutral=final.shape.value == "neutral",
            driftDetected=final.drift_detected,
            accuracyClaim="generic mouth shapes only; no phoneme accuracy is claimed or measured",
        )
        report.record(
            15, "display synchronized captions",
            bool(speaking.bubble.text) and speaking.bubble.text == (
                state.result_summary or state.status_text
            ),
            caption=speaking.bubble.text,
        )

        # 16. Success.
        success = presenter.update(_visual_state(state), now=clock.advance(), signal_overrides=_VISUAL)
        report.record(
            16, "enter the success state",
            finished and success.snapshot.mapped_state.character_state.value == "success",
            phase=state.phase,
            characterState=success.snapshot.mapped_state.character_state.value,
            transportFault=_transport_fault(model),
        )

        before = {
            "taskId": task_id,
            "state": model.client.get_task(task_id)["task"]["state"],
            "resultSummary": state.result_summary,
        }

        # 17-21. Pressure, the two degradations, and hysteretic recovery —
        # the *capability selector's* behaviour, asked of a healthy renderer.
        #
        # A transient renderer fault anywhere in the run parks the presenter
        # unhealthy for 15 *renderer* seconds, and this slice advances about
        # eleven synthetic seconds for its whole remainder — so a single
        # incidental fault used to reach these steps disguised as a selector
        # defect: exactly steps 17 and 21 failed, 18-20 kept passing, and
        # nothing in the report named the fault. That is the pair that
        # flipped ~2-in-12 on a loaded host across three phases, and it
        # reproduces deterministically from one injected fault. So the
        # sequence now checks renderer health as it goes; a faulted attempt
        # is recorded by name, the health recovery the design actually has
        # is exercised (15 seconds pass, the selector's own hysteresis
        # follows), and the questions are asked once more of the healthy
        # renderer they were always about. A second faulted attempt stands,
        # with both faults in evidence — visible, not tolerated.
        sequence, clean = _pressure_sequence(presenter, state, clock)
        incidental: dict[str, Any] = {}
        if not clean:
            incidental = {
                "incidentalRendererFault": True,
                # Codes AND explanations: the explanation carries the actual
                # exception text, which is the sentence the next person
                # diagnosing a loaded-host fault needs. Three phases lacked it.
                "rendererEvents": [
                    {key: item.get(key) for key in ("eventType", "code", "explanation")
                     if item.get(key)}
                    if isinstance(item, dict) else str(item)
                    for item in list(presenter.controller.events)[-8:]
                ],
            }
            # The design's own recovery: the health window passes, then the
            # selector's hysteresis (three healthy samples past its delay).
            presenter.update(_visual_state(state), now=clock.advance(15.0),
                             signal_overrides=_VISUAL)
            for _ in range(3):
                presenter.update(_visual_state(state), now=clock.advance(1.5),
                                 signal_overrides=_VISUAL)
            sequence, clean = _pressure_sequence(presenter, state, clock)
            incidental["retryCleanOfFaults"] = clean
        recovered_presentation = sequence[-1]["presentation"]
        for row in sequence:
            row = dict(row)
            number, name, ok = row.pop("number"), row.pop("name"), row.pop("ok")
            extra = incidental if number == 17 else {}
            report.record(number, name, ok, **row, **extra)

        # 22-23. Restart the renderer and restore everything.
        restarted = presenter.restart(now=clock.advance(), now_ms=clock.ms)
        report.record(
            22, "restart the renderer", restarted is not None,
            events=[item.get("eventType") for item in (restarted.events if restarted else ())],
        )
        report.record(
            23, "restore package, current state and presentation",
            restarted is not None
            and restarted.snapshot.mapped_state is not None
            and restarted.effective_presentation == recovered_presentation
            and presenter.package.package_digest == package.package_digest,
            restoredPackage=presenter.package.manifest.package_id,
            restoredState=(
                restarted.snapshot.mapped_state.character_state.value
                if restarted and restarted.snapshot.mapped_state else None
            ),
            restoredPresentation=restarted.effective_presentation if restarted else None,
        )

        # 24. And none of that touched the task.
        after = {
            "taskId": model.task_id,
            "state": model.client.get_task(task_id)["task"]["state"],
            "resultSummary": model.refresh().result_summary,
        }
        health = model.client.health()
        report.record(
            24, "verify the task never restarted or was cancelled",
            before == after and after["state"] == "completed" and bool(health.get("ok")),
            before=before,
            after=after,
            runningTasks=list(health.get("runningTasks", [])),
        )
    except CompanionClientError as exc:  # pragma: no cover - reported, not raised
        report.record(0, "the slice reached the runtime", False, error=str(exc))
    finally:
        service.close()
    return report
