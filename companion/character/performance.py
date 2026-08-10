# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Development microbenchmarks for the headless reference renderer.

Results describe the current interpreter and host only.  They are not physical
hardware claims and are intentionally labelled as process-level measurements.
"""

from __future__ import annotations

import platform
from pathlib import Path
import tempfile
import time
from typing import Any

from .adaptation import (
    AdaptiveRendererSelector,
    CapabilityPresentationPlan,
    Presentation,
    RendererSignals,
)
from .animated_renderer import Animated2DRenderer
from .bubble import BubbleKind, SpeechBubbleController
from .importer import CharacterPackageImporter, PackageRegistry
from .mapper import StateMapperInput, map_character_state
from .package import ValidatedPackage, validate_package_directory
from .static_renderer import StaticImageRenderer


def _milliseconds(start_ns: int) -> float:
    return (time.perf_counter_ns() - start_ns) / 1_000_000


def measure_renderer_performance(package: ValidatedPackage) -> dict[str, Any]:
    source = package.root
    start = time.perf_counter_ns()
    loaded = validate_package_directory(source, trust_state=package.trust_state)
    package_load_ms = _milliseconds(start)

    mapped_idle = map_character_state(loaded.manifest, StateMapperInput(presentation_phase="starting"))
    mapped_work = map_character_state(loaded.manifest, StateMapperInput(presentation_phase="working", tool_activity="typing"))
    static = StaticImageRenderer()
    start = time.perf_counter_ns()
    static.load_package(loaded)
    static.display_state(mapped_idle)
    static_load_ms = _milliseconds(start)

    animated = Animated2DRenderer()
    start = time.perf_counter_ns()
    animated.load_package(loaded)
    animated.display_state(mapped_idle, now_ms=0)
    animated_load_ms = _milliseconds(start)

    idle_sample_seconds = 0.2
    idle_wall = time.perf_counter()
    idle_cpu = time.process_time()
    time.sleep(idle_sample_seconds)
    idle_elapsed = max(time.perf_counter() - idle_wall, 1e-9)
    idle_cpu_percent = max(0.0, (time.process_time() - idle_cpu) / idle_elapsed * 100)

    animated.display_state(mapped_work, now_ms=0)
    samples: list[float] = []
    for index in range(240):
        frame_start = time.perf_counter_ns()
        animated.tick(now_ms=index * 16)
        samples.append(_milliseconds(frame_start))

    # CPU is sampled while ticks are scheduled at the package's nominal frame
    # rate. The tight loop above measures tick cost; calling that loop's CPU
    # saturation "animation CPU usage" would overstate normal playback.
    active_sample_seconds = 0.5
    interval = 1.0 / min(60.0, max(1.0, loaded.manifest.frame_rate))
    animated.display_state(mapped_work, now_ms=0)
    active_cpu = time.process_time()
    active_wall = time.perf_counter()
    next_tick = active_wall
    while True:
        observed = time.perf_counter()
        elapsed = observed - active_wall
        if elapsed >= active_sample_seconds:
            break
        animated.tick(now_ms=round(elapsed * 1000))
        next_tick += interval
        time.sleep(max(0.0, min(next_tick - time.perf_counter(), active_sample_seconds - elapsed)))
    active_elapsed = max(time.perf_counter() - active_wall, 1e-9)
    active_cpu_percent = max(0.0, (time.process_time() - active_cpu) / active_elapsed * 100)

    before_drop = animated.dropped_frames
    animated.tick(now_ms=10_000)
    dropped = animated.dropped_frames - before_drop

    bubble = SpeechBubbleController()
    start = time.perf_counter_ns()
    for index in range(500):
        bubble.update(f"Streaming caption chunk {index}", kind=BubbleKind.CAPTION, partial=True, now=index / 10)
    bubble_update_us = _milliseconds(start) * 1000 / 500

    start = time.perf_counter_ns()
    animated.display_state(mapped_idle, now_ms=10_016)
    transition_ms = _milliseconds(start)
    start = time.perf_counter_ns()
    animated.unload_package()
    animated.load_package(loaded)
    animated.display_state(mapped_idle, now_ms=0)
    restart_ms = _milliseconds(start)

    with tempfile.TemporaryDirectory(prefix="bunny-character-performance-") as temporary:
        registry = PackageRegistry(Path(temporary) / "registry")
        importer = CharacterPackageImporter(registry)
        start = time.perf_counter_ns()
        importer.import_package(source)
        import_ms = _milliseconds(start)

    budget_cases = (
        (
            "text-only-ceiling",
            CapabilityPresentationPlan(
                "performance-text", Presentation.TEXT_ONLY, Presentation.TEXT_ONLY
            ),
            RendererSignals(),
        ),
        (
            "static-ceiling",
            CapabilityPresentationPlan(
                "performance-static", Presentation.STATIC_IMAGE, Presentation.STATIC_IMAGE
            ),
            RendererSignals(available_memory_bytes=128 * 1024 * 1024),
        ),
        (
            "animation-fits",
            CapabilityPresentationPlan(
                "performance-animated", Presentation.ANIMATED_2D, Presentation.ANIMATED_2D
            ),
            RendererSignals(available_memory_bytes=1024 * 1024 * 1024),
        ),
        (
            "runtime-memory-pressure",
            CapabilityPresentationPlan(
                "performance-pressure", Presentation.ANIMATED_2D, Presentation.ANIMATED_2D
            ),
            RendererSignals(
                available_memory_bytes=1024 * 1024 * 1024, memory_pressure=True
            ),
        ),
    )
    budget_decisions = []
    for name, plan, signals in budget_cases:
        decision = AdaptiveRendererSelector().evaluate(plan, loaded, signals, now=0)
        budget_decisions.append({"budget": name, **decision.to_json()})

    return {
        "measurementKind": "development-host-process-microbenchmark",
        "host": {"platform": platform.platform(), "python": platform.python_version()},
        "packageId": loaded.manifest.package_id,
        "packageDigest": loaded.package_digest,
        "packageLoadMs": round(package_load_ms, 3),
        "staticRendererLoadMs": round(static_load_ms, 3),
        "animatedRendererLoadMs": round(animated_load_ms, 3),
        "staticImageMemoryBytes": static.report_memory_use(),
        "animatedRendererMemoryBytes": animated.report_memory_use(),
        "idleCpuPercent": round(idle_cpu_percent, 3),
        "idleCpuSampleMs": round(idle_elapsed * 1000),
        "activeAnimationCpuPercent": round(active_cpu_percent, 3),
        "activeAnimationCpuSampleMs": round(active_elapsed * 1000),
        "averageFrameTickMs": round(sum(samples) / len(samples), 6),
        "maximumFrameTickMs": round(max(samples), 6),
        "droppedFramesInIntentionalGap": dropped,
        "bubbleUpdateMicroseconds": round(bubble_update_us, 3),
        "stateTransitionMs": round(transition_ms, 6),
        "rendererRestartMs": round(restart_ms, 3),
        "packageImportMs": round(import_ms, 3),
        "representativeBudgetDecisions": budget_decisions,
        "scope": (
            "Measured on the current development host with the deterministic 96x96 reference package. "
            "No Raspberry Pi, 64 MiB, GPU-workstation, or physical-target performance is claimed."
        ),
    }
