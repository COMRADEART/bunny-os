#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§21's measurements, on the host this is run on and no other.

Every dimension §21 names appears in the output. Each one is either a number
taken on this machine or the string ``NOT_RUN`` with the reason — never a zero,
never an estimate, and never a figure carried over from somewhere else.

What this will not produce, because it cannot:

* a Raspberry Pi, ARM or 64 MiB full-system figure — there is no code path that
  emits one, so a report cannot accidentally contain one;
* a GPU figure — nothing here touches a GPU;
* an RSS or PSS number where ``/proc`` is absent. Python's own heap accounting
  measures a different thing and reporting it under a memory heading would be a
  measurement of something else wearing the right label;
* a frame-presentation time. Frames are *computed* here and never presented,
  because presenting one needs a compositor. The computed tick is reported under
  its own name so it cannot be mistaken for the other.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time
from typing import Any, Callable

for _candidate in (Path("/usr/lib/bunny-os/python"), Path(__file__).resolve().parents[1]):
    if _candidate.is_dir() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

from companion.character.adaptation import (  # noqa: E402
    CapabilityPresentationPlan,
    RendererSignals,
)
from companion.character.defaults import default_character_path  # noqa: E402
from companion.character.importer import CharacterPackageImporter, PackageRegistry  # noqa: E402
from companion.character.mapper import StateMapperInput, map_character_state  # noqa: E402
from companion.character.package import validate_package_directory  # noqa: E402
from companion.character.positioning import Display, PixelRect  # noqa: E402
from companion.character.schema import PackageTrustState  # noqa: E402
from companion.character.surface import CharacterPresenter  # noqa: E402
from companion.presentation import PresentationRecommendation, PresentationState  # noqa: E402

_VISUAL = {
    "display_available": True,
    "graphics_ready": True,
    "available_memory_bytes": 8 * 1024 ** 3,
    "gpu_available": True,
}
_RECOMMENDATION = PresentationRecommendation(
    implementation="animated-2d", eligible="full-3d", limited_by_implementation=True,
)


def not_run(reason: str) -> dict[str, str]:
    return {"result": "NOT_RUN", "reason": reason}


def resident_bytes() -> int | None:
    """Resident set size, or ``None`` where the platform cannot report it."""
    try:
        with open("/proc/self/status", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return None


def proportional_bytes() -> int | None:
    """PSS, which only Linux's smaps_rollup provides."""
    try:
        with open("/proc/self/smaps_rollup", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("Pss:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        return None
    return None


def _timed(action: Callable[[], Any], repeats: int) -> dict[str, Any]:
    samples: list[float] = []
    for _ in range(repeats):
        start = time.perf_counter()
        action()
        samples.append((time.perf_counter() - start) * 1000.0)
    return {
        "samples": len(samples),
        "firstMs": round(samples[0], 4),
        "medianMs": round(statistics.median(samples), 4),
        "maximumMs": round(max(samples), 4),
    }


def _state(phase: str) -> PresentationState:
    return PresentationState(phase=phase, status_text="measuring", recommendation=_RECOMMENDATION)


def measure(root: Path, *, repeats: int = 20) -> dict[str, Any]:
    source = default_character_path()
    report: dict[str, Any] = {
        "measurement": "companion-character-renderer",
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "processors": os.cpu_count(),
        },
        "scope": (
            "this host only. No Raspberry Pi, ARM, 64 MiB full-system or GPU figure is "
            "produced here, and none may be inferred from these numbers."
        ),
    }

    # -- package validation, import and load ------------------------------
    report["packageValidationMs"] = _timed(
        lambda: validate_package_directory(source, trust_state=PackageTrustState.BUILT_IN),
        repeats,
    )

    registry_root = root / "import"
    registry = PackageRegistry(registry_root / "characters")
    importer = CharacterPackageImporter(registry)
    start = time.perf_counter()
    importer.import_package(source)
    report["packageImportMs"] = {
        "samples": 1,
        "firstMs": round((time.perf_counter() - start) * 1000.0, 4),
        "note": "one import only; an import is not idempotent and repeating it is refused",
    }

    package = validate_package_directory(source, trust_state=PackageTrustState.BUILT_IN)
    presenter = CharacterPresenter(
        root, display=Display("m", PixelRect(0, 0, 1920, 1080), primary=True)
    )
    report["packageLoadMs"] = _timed(
        lambda: presenter.controller.load_package(package), repeats
    )

    # -- memory -------------------------------------------------------------
    rss = resident_bytes()
    pss = proportional_bytes()
    if rss is None:
        detail = not_run("this platform has no /proc/self/status; RSS is not measurable")
        report["staticRendererRss"] = detail
        report["animatedRendererRss"] = detail
    else:
        presenter.update(_state("idle"), now=1.0, signal_overrides={**_VISUAL, "reduced_motion": True})
        report["staticRendererRss"] = {"bytes": resident_bytes(), "presentation": "static-image"}
        presenter.update(_state("working"), now=2.0, signal_overrides=_VISUAL)
        report["animatedRendererRss"] = {"bytes": resident_bytes(), "presentation": "animated-2d"}
    report["rendererPss"] = (
        {"bytes": pss} if pss is not None
        else not_run("this platform has no /proc/self/smaps_rollup; PSS is not measurable")
    )
    # The one memory figure that *is* portable: what the validator proved the
    # decoded frames will occupy. Declared and verified, not sampled.
    report["decodedFrameBytes"] = {
        "total": sum(info.decoded_bytes for info in package.image_info.values()),
        "perFrame": package.manifest.width * package.manifest.height * 4,
        "declaredByPackage": package.manifest.memory_estimate_bytes,
        "note": "computed from validated image headers, not sampled from the process",
    }

    # -- CPU ----------------------------------------------------------------
    try:
        clock = time.process_time
        idle_start = clock()
        deadline = time.monotonic() + 0.3
        while time.monotonic() < deadline:
            presenter.tick(now_ms=0)
        idle_cpu = clock() - idle_start

        active_start = clock()
        deadline = time.monotonic() + 0.6
        moment = 0
        while time.monotonic() < deadline:
            moment += 16
            presenter.tick(now_ms=moment)
        active_cpu = clock() - active_start
        report["idleCpuSeconds"] = {"seconds": round(idle_cpu, 5), "windowSeconds": 0.3}
        report["activeCpuSeconds"] = {"seconds": round(active_cpu, 5), "windowSeconds": 0.6}
    except (AttributeError, OSError):  # pragma: no cover - process_time is universal in practice
        report["idleCpuSeconds"] = not_run("process CPU time is unavailable on this host")
        report["activeCpuSeconds"] = report["idleCpuSeconds"]

    # -- frames -------------------------------------------------------------
    presenter.update(_state("working"), now=10.0, signal_overrides=_VISUAL)
    counter = {"ms": 0}

    def _tick() -> None:
        counter["ms"] += 16
        presenter.tick(now_ms=counter["ms"])

    report["frameComputeMs"] = _timed(_tick, 200)
    report["frameComputeMs"]["note"] = (
        "the cost of computing the next frame. Not a presentation time: no frame is "
        "presented here, because presenting one needs a compositor."
    )
    report["framePresentMs"] = not_run("no compositor is available on this host")
    before_drops = presenter.controller.renderer.dropped_frames if presenter.controller.renderer else 0
    presenter.tick(now_ms=counter["ms"] + 5000)
    after_drops = presenter.controller.renderer.dropped_frames if presenter.controller.renderer else 0
    report["droppedFrames"] = {
        "afterFiveSecondGap": after_drops - before_drops,
        "note": "an intentional gap; a dropped frame is counted, never hidden",
    }

    # -- transitions, captions, degradation, recovery, restart --------------
    clock_value = {"now": 100.0}

    def _advance(seconds: float = 1.0) -> float:
        clock_value["now"] += seconds
        return clock_value["now"]

    report["stateTransitionMs"] = _timed(
        lambda: presenter.update(
            _state("working" if int(clock_value["now"]) % 2 else "reviewing"),
            now=_advance(0.01), signal_overrides=_VISUAL,
        ),
        repeats,
    )
    report["captionUpdateMs"] = _timed(
        lambda: presenter.update(
            _state("presenting_result"), now=_advance(0.01), signal_overrides=_VISUAL
        ),
        repeats,
    )

    start = time.perf_counter()
    degraded = presenter.update(
        _state("working"), now=_advance(),
        signal_overrides={**_VISUAL, "memory_pressure": True},
    )
    report["degradationLatencyMs"] = {
        "milliseconds": round((time.perf_counter() - start) * 1000.0, 4),
        "to": degraded.effective_presentation,
        "note": "degradation is immediate by design; only recovery waits",
    }

    start = time.perf_counter()
    samples = 0
    recovered = degraded
    for _ in range(8):
        samples += 1
        recovered = presenter.update(_state("working"), now=_advance(1.5), signal_overrides=_VISUAL)
        if recovered.effective_presentation == "animated-2d":
            break
    report["recoveryLatency"] = {
        "milliseconds": round((time.perf_counter() - start) * 1000.0, 4),
        "samples": samples,
        "to": recovered.effective_presentation,
        "note": "held by hysteresis; the sample count is the property, not the wall clock",
    }

    start = time.perf_counter()
    presenter.restart(now=_advance(), now_ms=int(clock_value["now"] * 1000))
    report["rendererRestartMs"] = round((time.perf_counter() - start) * 1000.0, 4)

    report["gtkWidgets"] = not_run(
        "the window needs a compositor; CharacterPresenter is what is measured here"
    )
    return report


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        tempfile.mkdtemp(prefix="bunny-character-measure-")
    )
    report = measure(root)
    report["root"] = str(root)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
