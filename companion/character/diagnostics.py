# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Structured local diagnostics for packages and renderer decisions."""

from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Any

from capability.runtime import Assessment

from .adaptation import CapabilityPresentationPlan, RendererSignals
from .controller import CharacterRendererController
from .defaults import default_character_paths
from .demo import run_character_demo
from .errors import CharacterError, CharacterSecurityError
from .importer import CharacterPackageImporter, PackageRegistry
from .mapper import StateMapperInput, map_character_state
from .package import validate_package_directory
from .schema import PackageTrustState, REQUIRED_CHARACTER_STATES


def registry_for(root: Path) -> PackageRegistry:
    return PackageRegistry(Path(root) / "characters", built_in_paths=default_character_paths())


def selected_package(registry: PackageRegistry):
    record = registry.selected()
    if record is None:
        raise ValueError("no built-in or imported character package is available")
    failure: CharacterError | None = None
    try:
        if record.trust_state in {
            PackageTrustState.DISABLED,
            PackageTrustState.QUARANTINED,
            PackageTrustState.INCOMPATIBLE,
            PackageTrustState.CORRUPT,
        }:
            raise CharacterSecurityError(
                f"selected package is not eligible in state {record.trust_state.value}"
            )
        trust = (
            PackageTrustState.BUILT_IN
            if record.trust_state is PackageTrustState.BUILT_IN
            else PackageTrustState.VERIFIED_INTEGRITY
        )
        return record, validate_package_directory(record.path, trust_state=trust), None
    except CharacterError as exc:
        failure = exc

    for fallback in registry.built_ins():
        if fallback.trust_state is not PackageTrustState.BUILT_IN:
            continue
        try:
            package = validate_package_directory(
                fallback.path, trust_state=PackageTrustState.BUILT_IN
            )
        except CharacterError:
            continue
        event = {
            "eventType": "renderer.package-fallback",
            "code": "selected-package-invalid",
            "failedPackageId": record.package_id,
            "failedPackageDigest": record.package_digest,
            "fallbackPackageId": fallback.package_id,
            "fallbackPackageDigest": fallback.package_digest,
            "explanation": str(failure),
            "taskContinues": True,
        }
        return fallback, package, event
    assert failure is not None
    raise failure


def three_d_signals(
    package: Any = None,
    *,
    context_provider_configured: bool = False,
) -> dict[str, Any]:
    """The 3D fields of :class:`RendererSignals`, read once at start-up.

    Separate from :func:`signals_from_assessment` because they come from a
    different place: the capability assessment describes the *machine*, and
    whether a graphics context can be made, whether the selected package
    carries a model, and whether this client was given a way to draw 3D at all
    are properties of this process's environment and its chosen character.
    Merging them would put a package lookup inside a function whose whole
    contract is that it only reads the inventory.

    ``context_provider_configured`` is part of the same truth: without it the
    signals said "this machine can do 3D" to a client nobody handed a context
    provider, the adaptation gate passed the request, and the failure happened
    inside the renderer — a degradation by crash instead of by decision.
    """
    from .three_d.diagnostics import three_d_environment

    environment = three_d_environment()
    model = getattr(package, "model", None)
    return {
        "three_d_available": bool(environment["threeDAvailable"]),
        "package_supports_3d": model is not None,
        "model_gpu_bytes": None if model is None else int(model.estimated_gpu_bytes),
        "three_d_context_configured": bool(context_provider_configured),
    }


def signals_from_assessment(assessment: Assessment) -> RendererSignals:
    """Read the capability assessment; never probe or recompute it here.

    Every field is *read* from the inventory the capability runtime already
    measured. There is no probe in this function and none may be added: §2
    forbids the renderer recalculating hardware capability, and a second
    measurement taken a second later would disagree with the one the decision
    was explained by.
    """
    inventory = assessment.inventory
    pressure = inventory.memory.pressure_some_avg10.get(None)
    battery = inventory.power.battery_percent.get(None)
    thermal = inventory.thermal.throttled.get(None)
    return RendererSignals(
        display_available=inventory.display.has_display,
        available_memory_bytes=inventory.memory.usable_available_bytes(None),
        graphics_ready=inventory.display.has_display,
        gpu_available=bool(inventory.usable_gpus),
        memory_pressure=isinstance(pressure, (int, float)) and pressure >= 0.1,
        thermal_pressure=thermal is True,
        on_battery=inventory.power.on_battery,
        battery_percent=float(battery) if isinstance(battery, (int, float)) else None,
    )


def presentation_plan_from_assessment(assessment: Assessment) -> CapabilityPresentationPlan:
    """The allowance, taken through the canonical projection's own function.

    Used by the diagnostic commands, which run without a companion service and
    therefore have no :class:`~companion.presentation.PresentationState` to read
    a recommendation out of. Rather than derive one here — which would be the
    second interpretation this whole layer exists to avoid — it calls
    :func:`companion.presentation.select_presentation`, the same function the
    runtime uses, over the same capability signals.
    """
    from companion.capability_bridge import capability_signals
    from companion.presentation import select_presentation, signals_from_capability_event

    signals = capability_signals(assessment)
    recommendation = select_presentation(
        signals_from_capability_event(
            signals,
            display_available=assessment.inventory.display.has_display,
            headless=not assessment.inventory.display.has_display,
        ),
        plan_id=assessment.plan.plan_id,
    )
    return CapabilityPresentationPlan.from_recommendation(recommendation)


def renderer_projection(root: Path, assessment: Assessment) -> dict[str, Any]:
    registry = registry_for(root)
    record, package, package_fallback = selected_package(registry)
    plan = presentation_plan_from_assessment(assessment)
    signals = signals_from_assessment(assessment)
    mapped = map_character_state(package.manifest, StateMapperInput(
        presentation_phase="idle",
        effective_presentation=plan.ceiling.value,
        status_text="Bunny is ready.",
    ))
    controller = CharacterRendererController()
    controller.load_package(package)
    if package_fallback is not None:
        controller.events.append(package_fallback)
    snapshot = controller.apply(mapped, plan, signals, now=0.0, now_ms=0)
    renderer_status = snapshot.renderer_status or {}
    missing_states = sorted(set(REQUIRED_CHARACTER_STATES).difference(package.manifest.state_map))
    return {
        "selectedPackage": record.to_json(),
        "packageFallback": package_fallback,
        "capabilityPlan": {
            "planId": plan.plan_id,
            "action": plan.action,
            "implementationId": plan.implementation_id,
            "ceiling": plan.ceiling.value,
            "reasons": list(plan.reasons),
        },
        "signals": {
            "displayAvailable": signals.display_available,
            "availableMemoryBytes": signals.available_memory_bytes,
            "graphicsReady": signals.graphics_ready,
            "gpuAvailable": signals.gpu_available,
            "memoryPressure": signals.memory_pressure,
            "thermalPressure": signals.thermal_pressure,
            "onBattery": signals.on_battery,
            "batteryPercent": signals.battery_percent,
        },
        "resourceDeclaration": {
            "width": package.manifest.width,
            "height": package.manifest.height,
            "frameRate": package.manifest.frame_rate,
            "memoryEstimateBytes": package.manifest.memory_estimate_bytes,
            "assetCount": len(package.manifest.assets),
        },
        "observedResourceUse": {
            "decodedMemoryBytes": int(renderer_status.get("observedMemoryBytes", 0)),
            "lastFrameMs": float(renderer_status.get("lastFrameMs", 0)),
            "droppedFrames": int(renderer_status.get("droppedFrames", 0)),
        },
        "missingStates": missing_states,
        "rendererErrors": [
            event for event in controller.events
            if event.get("eventType") in {"renderer.failed", "renderer.package-fallback"}
        ],
        **snapshot.to_json(),
    }


def run_diagnostic_demo(root: Path | None = None, *, performance: bool = False) -> dict[str, Any]:
    demo_root = Path(root) if root is not None else Path(tempfile.mkdtemp(prefix="bunny-character-demo-"))
    report = run_character_demo(demo_root, include_performance=performance)
    return {"root": str(demo_root), **report.to_json()}
