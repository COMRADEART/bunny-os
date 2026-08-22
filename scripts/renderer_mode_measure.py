#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What each renderer mode actually costs, on the host this is run on.

§12 of the polished-alpha brief makes performance a first-class requirement and
names eight dimensions. This measures the ones a process without a compositor
can honestly measure, and says ``NOT_RUN`` with a reason for the rest. It does
not estimate, it does not scale a number from another machine, and it does not
report a figure for a mode it could not construct.

The claim this exists to support is a specific one: **pre-rendered has the
lowest footprint of the three**. That is a comparison, so all three modes are
measured in one process, back to back, on the same package and the same clock —
figures gathered from three separate runs would differ by whatever else the
machine was doing between them.

Two dimensions deserve their caveats stated where the number is produced rather
than in a report somebody may not read beside it:

*Idle cost* is reported as **ticks that drew** over a simulated idle minute, not
as a CPU percentage. A percentage measured over a minute of a synthetic clock is
a measurement of this script's own loop. The number of draws the policy allowed
is the property that actually determines the CPU cost, and it is exact.

*Frame time* is the time to **compute** a frame, never to present one.
Presenting needs a compositor. The distinction is kept in the key names so the
two cannot be confused, which is the same rule ``character_measure.py`` follows.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time
from typing import Any, Callable

# Only when the package is not importable yet. See the long note in
# scripts/character_measure.py: putting the installed tree ahead of an already
# importable checkout is how a suite comes to pass against code nobody changed.
if importlib.util.find_spec("companion") is None:
    for _candidate in (Path("/usr/lib/bunny-os/python"), Path(__file__).resolve().parents[1]):
        if _candidate.is_dir() and str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))

from companion.character.adaptation import (  # noqa: E402
    CapabilityPresentationPlan,
    Presentation,
    RendererSignals,
)
from companion.character.attention import (  # noqa: E402
    AttentionInput,
    attention_for,
)
from companion.character.controller import CharacterRendererController  # noqa: E402
from companion.character.defaults import default_character_path  # noqa: E402
from companion.character.mapper import (  # noqa: E402
    StateMapperInput,
    map_character_state,
)
from companion.character.modes import MODE_CEILINGS, RenderMode  # noqa: E402
from companion.character.package import (  # noqa: E402
    PackageTrustState,
    validate_package_directory,
)
from companion.character.quiescence import DEFAULT_POLICY  # noqa: E402

#: One simulated minute at 60 Hz. The tick budget an always-on companion would
#: spend if nothing ever stopped it.
IDLE_TICKS = 3600
IDLE_STEP_MS = 1000 // 60


def not_run(reason: str) -> dict[str, str]:
    return {"measured": "NOT_RUN", "reason": reason}


def resident_bytes() -> int | None:
    """RSS from ``/proc``, or ``None``. Never Python's own heap accounting.

    Reporting ``sys.getallocatedblocks`` or a ``tracemalloc`` figure under a
    memory heading would be a measurement of a different thing wearing the right
    label, so where ``/proc`` is absent this answers nothing at all.
    """
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                parts = line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    return int(parts[1]) * 1024
    except OSError:
        return None
    return None


def _timed(action: Callable[[], Any], repeats: int) -> dict[str, Any]:
    samples: list[float] = []
    for _ in range(repeats):
        start = time.perf_counter()
        action()
        samples.append((time.perf_counter() - start) * 1000.0)
    ordered = sorted(samples)
    return {
        "samples": len(samples),
        "meanMs": round(statistics.fmean(samples), 4),
        "medianMs": round(statistics.median(samples), 4),
        "p95Ms": round(ordered[max(0, int(len(ordered) * 0.95) - 1)], 4),
        "maxMs": round(max(samples), 4),
    }


def _plan(ceiling: Presentation) -> CapabilityPresentationPlan:
    return CapabilityPresentationPlan(
        plan_id="measure", requested=ceiling, ceiling=ceiling,
        implementation_id=ceiling.value,
    )


def _signals() -> RendererSignals:
    # Deliberately a *capable* machine: the point of the comparison is what each
    # mode costs when nothing is forcing it down. A signal set that degraded 3D
    # would measure the 2D renderer three times.
    return RendererSignals(
        display_available=True, graphics_ready=True, gpu_available=True,
        three_d_available=True, package_supports_3d=True,
        # The harness opens a real context for the 3D mode; without declaring
        # it the new absent-provider gate would measure the 2D renderer.
        three_d_context_configured=True,
    )


def _three_d_context() -> tuple[Any, str]:
    """A surfaceless GL context factory, or ``None`` with the reason there isn't one.

    Opened only for the 3D mode and only if the environment says one can be
    created. A measurement that skipped 3D because it never *tried* would report
    NOT_RUN on a machine that renders perfectly well — the reference host has no
    ``/dev/dri`` at all and still creates an EGL context on llvmpipe.
    """
    try:
        from companion.character.three_d.context import (
            SurfacelessContext,
            offscreen_available,
        )
    except Exception as error:
        return None, f"the 3D context module is not importable: {error}"
    try:
        available, reason = offscreen_available()
    except Exception as error:
        return None, f"the offscreen check failed: {error}"
    if not available:
        return None, reason or "no offscreen GL context is available here"
    return SurfacelessContext, reason or "an offscreen EGL context is available"


def _three_d_package() -> tuple[Any, str]:
    """The bundled 3D package, validated, or ``None`` and why not."""
    from companion.character.defaults import default_3d_character_path

    path = default_3d_character_path()
    if not path.is_dir():
        return None, f"the bundled 3D character package is not installed at {path}"
    try:
        return validate_package_directory(
            path, trust_state=PackageTrustState.BUILT_IN
        ), ""
    except Exception as error:
        return None, f"the bundled 3D character package did not validate: {error}"


def measure_mode(mode: RenderMode, package, *, repeats: int = 40) -> dict[str, Any]:
    """Every figure for one mode, or the reason there is none."""
    report: dict[str, Any] = {"mode": mode.value, "ceiling": MODE_CEILINGS[mode].value}
    context = None
    if mode is RenderMode.THREE_D:
        context, detail = _three_d_context()
        report["graphicsContext"] = detail
    controller = CharacterRendererController(mode=mode, three_d_context=context)
    controller.load_package(package)
    idle = map_character_state(package.manifest, StateMapperInput(presentation_phase="idle"))
    working = map_character_state(package.manifest, StateMapperInput(presentation_phase="working"))
    signals = _signals()
    plan = _plan(MODE_CEILINGS[mode])

    before = resident_bytes()
    start = time.perf_counter()
    try:
        controller.apply(idle, plan, signals, now=0.0, now_ms=0)
    except Exception as error:
        # A mode that will not start here is reported as not run, with what it
        # said. 3D on a host with no graphics context is the expected case and
        # it must not look like a zero.
        report["startup"] = not_run(f"the {mode.value} renderer did not start: {error}")
        return report
    report["companionStartupMs"] = round((time.perf_counter() - start) * 1000.0, 4)
    after = resident_bytes()
    renderer = controller.renderer
    report["renderer"] = renderer.renderer_name if renderer else "text-only"
    report["effectivePresentation"] = controller.decision.effective.value

    report["packageMemoryBytes"] = renderer.report_memory_use() if renderer else 0
    report["residentBytes"] = (
        {"before": before, "after": after, "deltaBytes": after - before}
        if before is not None and after is not None
        else not_run("/proc/self/status is not readable on this host")
    )

    # -- animation playback: compute cost per frame while actively working ---
    controller.apply(working, plan, signals, now=1.0, now_ms=1000)
    clock = {"ms": 1000}

    def one_tick() -> None:
        clock["ms"] += IDLE_STEP_MS
        controller.tick(now_ms=clock["ms"])

    report["frameComputeMs"] = _timed(one_tick, repeats)
    report["frameComputeMs"]["note"] = (
        "time to compute a frame, never to present one; presenting needs a compositor"
    )

    # -- idle cost: how many of a simulated minute's ticks actually drew ------
    controller.apply(idle, plan, signals, now=10.0, now_ms=10_000)
    drew = 0
    now_ms = 10_000
    idle_start = time.perf_counter()
    for _ in range(IDLE_TICKS):
        now_ms += IDLE_STEP_MS
        controller.tick(now_ms=now_ms)
        if controller.last_quiescence is not None and controller.last_quiescence.draws:
            drew += 1
    report["idleMinute"] = {
        "offeredTicks": IDLE_TICKS,
        "ticksThatDrew": drew,
        "drawFraction": round(drew / IDLE_TICKS, 4),
        "wallClockMs": round((time.perf_counter() - idle_start) * 1000.0, 3),
        "note": (
            "ticks the quiescence policy allowed over one simulated idle minute at 60 Hz. "
            "Reported as a count rather than a CPU percentage: a percentage taken over a "
            "synthetic clock measures this script's loop, not the companion."
        ),
    }
    report["finalQuiescence"] = (
        controller.last_quiescence.to_json() if controller.last_quiescence else None
    )

    # -- §16's state transition and permission dimensions --------------------
    #
    # Measured as the *whole* change a user perceives: map the phase, evaluate
    # the ladder, swap or keep the renderer, and draw. Timing only the mapper
    # would produce a flatteringly small number for a step that is not the one
    # anybody waits on.
    phases = ("idle", "listening", "planning", "working", "success", "idle")
    walk = {"index": 0, "ms": 20_000}
    mapped = {
        name: map_character_state(
            package.manifest, StateMapperInput(presentation_phase=name)
        )
        for name in set(phases)
    }

    def one_transition() -> None:
        name = phases[walk["index"] % len(phases)]
        walk["index"] += 1
        walk["ms"] += 250
        controller.apply(
            mapped[name], plan, signals,
            now=walk["ms"] / 1000.0, now_ms=walk["ms"],
        )

    report["stateTransitionMs"] = _timed(one_transition, repeats)
    report["stateTransitionMs"]["note"] = (
        "one full companion state change: phase mapped, ladder evaluated, renderer "
        "selected and a frame drawn"
    )

    approval = map_character_state(
        package.manifest,
        StateMapperInput(
            presentation_phase="waiting_for_approval",
            approval_pending=True,
            status_text="Bunny wants to open a file.",
        ),
    )
    permission = {"ms": 40_000}

    def enter_permission() -> None:
        permission["ms"] += 250
        controller.apply(
            approval, plan, signals,
            now=permission["ms"] / 1000.0, now_ms=permission["ms"],
        )

    report["permissionStateMs"] = _timed(enter_permission, repeats)
    report["permissionStateMs"]["note"] = (
        "entering waiting-for-permission, which §12 requires to be visible "
        "before the user can answer"
    )

    # The attention projection, which every surface consults each frame. Cheap
    # by construction — it is a dict lookup and three comparisons — but measured
    # rather than asserted, because "obviously cheap" is how per-frame costs
    # accumulate.
    attention_state = approval.character_state

    def one_attention() -> None:
        attention_for(AttentionInput(state=attention_state, engaged=True))

    report["attentionDecisionMs"] = _timed(one_attention, max(repeats, 200))
    return report


def measure_switching(package, *, repeats: int = 20) -> dict[str, Any]:
    """§16's renderer switching time, both directions, with the session intact."""
    controller = CharacterRendererController(mode=RenderMode.PRERENDERED)
    controller.load_package(package)
    idle = map_character_state(package.manifest, StateMapperInput(presentation_phase="idle"))
    signals = _signals()
    controller.apply(idle, _plan(Presentation.ANIMATED_2D), signals, now=0.0, now_ms=0)

    order = [RenderMode.INTERACTIVE_2D, RenderMode.PRERENDERED]
    state = {"index": 0, "ms": 0}

    def switch() -> None:
        mode = order[state["index"] % len(order)]
        state["index"] += 1
        state["ms"] += 100
        controller.set_mode(mode, now_ms=state["ms"])
        controller.apply(
            idle, _plan(MODE_CEILINGS[mode]), signals,
            now=state["ms"] / 1000.0, now_ms=state["ms"],
        )

    timing = _timed(switch, repeats)
    timing["note"] = (
        "pre-rendered <-> interactive-2d, measured as the full change: mode set, "
        "renderer built, package loaded and the current state redrawn"
    )
    timing["sessionPreserved"] = controller.mapped_state is not None
    return timing


def measure(*, repeats: int = 40) -> dict[str, Any]:
    package = validate_package_directory(
        default_character_path(), trust_state=PackageTrustState.BUILT_IN
    )
    report: dict[str, Any] = {
        "schemaVersion": 1,
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "machine": platform.machine(),
        },
        "package": {
            "packageId": package.manifest.package_id,
            "presentationType": package.manifest.presentation_type.value,
        },
        "quiescencePolicy": {
            "drowsyFps": DEFAULT_POLICY.drowsy_fps,
            "drowsySeconds": DEFAULT_POLICY.drowsy_seconds,
        },
        "modes": {},
    }
    # 3D is measured against the *3D* package. The 2D one carries no model, so
    # the ladder would correctly drop it to animated-2d and the report would
    # then contain a "3D" row describing the 2D renderer.
    three_d_package, three_d_error = _three_d_package()
    if three_d_package is not None:
        report["threeDPackage"] = {
            "packageId": three_d_package.manifest.package_id,
            "presentationType": three_d_package.manifest.presentation_type.value,
        }
    else:
        report["threeDPackage"] = not_run(three_d_error)
    for mode in RenderMode:
        if mode is RenderMode.THREE_D:
            if three_d_package is None:
                report["modes"][mode.value] = {
                    "mode": mode.value,
                    "ceiling": MODE_CEILINGS[mode].value,
                    "startup": not_run(three_d_error),
                }
                continue
            report["modes"][mode.value] = measure_mode(
                mode, three_d_package, repeats=repeats
            )
            continue
        report["modes"][mode.value] = measure_mode(mode, package, repeats=repeats)
    report["rendererSwitching"] = measure_switching(package)

    # -- the dimensions this process cannot answer, named rather than omitted --
    report["bootTime"] = not_run(
        "boot time is a property of a booted image; measure it with the VM harness, "
        "not from a process on the build host"
    )
    report["idleGpu"] = not_run("nothing here touches a GPU")
    report["desktopResponsiveness"] = not_run(
        "the desktop shell needs a compositor and a session; this process has neither"
    )

    # -- the comparison the whole file exists to make ------------------------
    #
    # Deliberately not a single "pre-rendered wins" boolean. The first version
    # was exactly that, and it reported ``holds: true`` off a *tie*: the number
    # it compared was the quiescence policy's tick count, which is a property of
    # the controller and identical for every renderer under it. A claim that
    # cannot come out false is not a check.
    #
    # The two modes differ on two axes that point in opposite directions, so
    # both are reported and neither is collapsed into a verdict:
    #
    #   - compute per frame, where the frame player wins by a wide margin
    #     because it indexes a list where the other solves for a pose;
    #   - resident image memory, where it *loses*, because it holds every
    #     decoded frame and the interactive renderer holds one.
    comparable = {
        name: value for name, value in report["modes"].items() if "idleMinute" in value
    }
    if len(comparable) > 1:
        report["comparison"] = {
            "idleMinuteComputeMs": {
                name: round(
                    value["idleMinute"]["ticksThatDrew"] * value["frameComputeMs"]["medianMs"], 3
                )
                for name, value in comparable.items()
            },
            "frameComputeMedianMs": {
                name: value["frameComputeMs"]["medianMs"] for name, value in comparable.items()
            },
            "decodedImageBytes": {
                name: value["packageMemoryBytes"] for name, value in comparable.items()
            },
            "ticksThatDrew": {
                name: value["idleMinute"]["ticksThatDrew"] for name, value in comparable.items()
            },
            "note": (
                "ticksThatDrew is a property of the quiescence policy, which sits above the "
                "renderer and is the same for all of them — equal counts here are expected "
                "and are not evidence that two modes cost the same. The cost difference is "
                "in idleMinuteComputeMs and decodedImageBytes, and those two do not favour "
                "the same mode: the frame player computes far less per frame and holds far "
                "more decoded image memory."
            ),
        }
    else:
        report["comparison"] = not_run(
            "fewer than two modes started on this host, so there is nothing to compare"
        )
    return report


def main() -> int:
    report = measure()
    destination = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    payload = json.dumps(report, indent=2, sort_keys=True)
    if destination is not None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
