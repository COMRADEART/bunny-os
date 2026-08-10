# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§31's six operations, and nothing that is not one of them.

The operation table below is an **allow-list with no wildcard**. There is no
``renderer_3d_eval``, no path parameter, no shader parameter and no way to reach
a GL call from a name: :func:`run_operation` looks the name up in a frozen
mapping and refuses anything absent, and the six handlers between them accept
exactly one argument — ``packageId``, which is matched against the installed
registry rather than opened as a path.

§31's forbidden list is not merely unimplemented here, it is *unreachable*:

``arbitrary shader load``
    The only strings that ever reach ``glShaderSource`` come from
    :mod:`companion.character.three_d.shaders`, and a security test reads the
    import graph to prove no other module calls it.
``arbitrary model path``
    ``renderer_3d_model`` takes a package id, resolves it through
    :class:`companion.character.importer.PackageRegistry`, and reads the model
    the *manifest* names — a path the package validator already proved lies
    under the package root.
``arbitrary GPU command`` and ``arbitrary texture path``
    Nothing here takes a GL enum, a buffer, a file name or a byte string.
``arbitrary package mutation``
    Every handler is read-only. ``renderer_3d_reload`` re-validates and
    re-uploads the *currently selected* package; it does not select, import,
    disable or write anything.

These are diagnostics for a subsystem that lives in the client process, so they
are not companion-service protocol operations: the service holds no renderer and
answering "how is your renderer" from a process that has none would be a lie
with a schema. They are reached through the CLI, which runs in the same kind of
process the renderer does.
"""

from __future__ import annotations

import os
from pathlib import Path
import time
from typing import Any, Callable, Mapping

from .context import SurfacelessContext, offscreen_available
from .errors import RendererCapabilityError, RendererContextError

#: The six §31 names. Adding a seventh means adding a handler *and* a line here,
#: which is the point: there is no dispatch path that does not pass this table.
OPERATION_NAMES: tuple[str, ...] = (
    "renderer_3d_health",
    "renderer_3d_status",
    "renderer_3d_model",
    "renderer_3d_metrics",
    "renderer_3d_explain",
    "renderer_3d_reload",
)

#: Names that have been proposed and are refused by design, with the reason, so
#: a refusal explains itself rather than reading as "not implemented yet".
REFUSED_OPERATIONS: Mapping[str, str] = {
    "renderer_3d_load_shader": "a character package may never supply a shader; §19",
    "renderer_3d_load_model": "models are loaded from validated packages, never from a path; §31",
    "renderer_3d_load_texture": "textures live inside a validated model; §31",
    "renderer_3d_gl": "there is no arbitrary GPU command surface; §31",
    "renderer_3d_write_package": "diagnostics do not mutate packages; §31",
}


def three_d_environment() -> dict[str, Any]:
    """Can this machine draw in 3D, answered without initialising anything.

    §30: a text-only or headless build must not initialise a GPU library, and
    that includes the check that decides whether it would have been able to. So
    this looks for the *libraries* and the *session*, not for a context — the
    context is created when 3D is selected, and its failure is a degradation the
    ladder already handles.
    """
    offscreen, offscreen_reason = offscreen_available()
    wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
    x11 = bool(os.environ.get("DISPLAY"))
    session = wayland or x11
    reasons: list[str] = [offscreen_reason]
    if not session:
        reasons.append("no WAYLAND_DISPLAY or DISPLAY is set; there is no graphical session")
    return {
        "offscreenAvailable": offscreen,
        "waylandDisplay": wayland,
        "x11Display": x11,
        "graphicalSession": session,
        # A machine with libEGL but no session can still draw offscreen, which
        # is what the diagnostics and the gates use. A machine with neither
        # cannot draw at all, and the honest answer is the ladder's lowest rung.
        "threeDAvailable": offscreen,
        "windowedThreeDAvailable": offscreen and session,
        "reasons": reasons,
        "libraryInitialised": False,
    }


class ThreeDDiagnostics:
    """One diagnostic session: at most one context, always released.

    Constructed per invocation rather than held: a diagnostic that kept a GPU
    context alive between calls would be a background renderer nobody asked for,
    on a machine that may have chosen text-only.
    """

    def __init__(self, *, root: Path | None = None, package_id: str | None = None) -> None:
        self.root = Path(root) if root is not None else None
        self.package_id = package_id
        self.context: SurfacelessContext | None = None
        self.renderer: Any = None
        self.package: Any = None
        self.started = time.monotonic()
        self.events: list[dict[str, Any]] = []

    # -- resolution --------------------------------------------------------

    def _resolve_package(self) -> Any:
        from companion.character.defaults import default_3d_character_path
        from companion.character.package import validate_package_directory
        from companion.character.schema import PackageTrustState

        if self.package is not None:
            return self.package
        if self.root is not None:
            from companion.character.diagnostics import registry_for

            registry = registry_for(self.root)
            records = [
                record for record in registry.list()
                if self.package_id is None or record.package_id == self.package_id
            ]
            for record in records:
                package = validate_package_directory(
                    record.path,
                    trust_state=(
                        PackageTrustState.BUILT_IN
                        if record.trust_state is PackageTrustState.BUILT_IN
                        else PackageTrustState.VERIFIED_INTEGRITY
                    ),
                )
                if package.model is not None:
                    self.package = package
                    return package
        path = default_3d_character_path()
        if not path.is_dir():
            raise RendererCapabilityError("no built-in 3D character package is installed")
        self.package = validate_package_directory(path, trust_state=PackageTrustState.BUILT_IN)
        if self.package.model is None:
            raise RendererCapabilityError("the built-in 3D package carries no validated model")
        return self.package

    def _open(self) -> Any:
        from .renderer import ThreeDRenderer

        if self.renderer is not None:
            return self.renderer
        package = self._resolve_package()
        section = package.manifest.three_dimensional
        self.context = SurfacelessContext()
        renderer = ThreeDRenderer(context=self.context, quality="full-3d", seed=0x6E6E79)
        renderer.load_package(package)
        renderer.upload(
            package.model,
            animation_map=section.animation_map,
            expression_map=section.expression_map,
            viseme_map=section.viseme_map,
            native_scale=section.native_scale,
            floor_offset=section.floor_offset,
        )
        self.renderer = renderer
        return renderer

    def close(self) -> None:
        if self.renderer is not None:
            try:
                self.renderer.release()
            except Exception as exc:  # noqa: BLE001 - teardown must not raise
                self.events.append({"eventType": "renderer3d.release-failed", "explanation": str(exc)})
            self.renderer = None
        if self.context is not None:
            self.context.release()
            self.context = None

    def __enter__(self) -> "ThreeDDiagnostics":
        return self

    def __exit__(self, *_exception: Any) -> None:
        self.close()

    # -- the six operations ------------------------------------------------

    def renderer_3d_health(self) -> dict[str, Any]:
        """Can 3D run here, and did a context actually come up."""
        environment = three_d_environment()
        result: dict[str, Any] = {
            "operation": "renderer_3d_health",
            "environment": environment,
            "contextCreated": False,
            "healthy": False,
            "context": None,
            "explanation": "",
        }
        if not environment["threeDAvailable"]:
            result["explanation"] = "; ".join(environment["reasons"])
            return result
        try:
            context = SurfacelessContext()
        except (RendererCapabilityError, RendererContextError) as exc:
            result["explanation"] = f"a graphics context could not be created: {exc}"
            return result
        try:
            info = context.info()
            result.update({
                "contextCreated": True,
                "healthy": True,
                "context": info.to_json(),
                "explanation": (
                    "an OpenGL context was created and released; "
                    + ("hardware acceleration was reported" if info.accelerated
                       else "this stack is a software rasteriser")
                ),
            })
        finally:
            context.release()
        return result

    def renderer_3d_status(self) -> dict[str, Any]:
        """What a renderer built from the selected package looks like right now."""
        renderer = self._open()
        renderer.begin_offscreen(256, 320)
        from companion.character.mapper import CharacterState, map_character_state, StateMapperInput

        mapped = map_character_state(
            self.package.manifest,
            StateMapperInput(presentation_phase="idle", status_text="Bunny is ready."),
        )
        renderer.display_state(mapped, now_ms=0)
        status = renderer.describe()
        renderer.end_offscreen()
        return {"operation": "renderer_3d_status", **status}

    def renderer_3d_model(self) -> dict[str, Any]:
        """The validated model descriptor. Never a file, never a path parameter."""
        package = self._resolve_package()
        section = package.manifest.three_dimensional
        return {
            "operation": "renderer_3d_model",
            "packageId": package.manifest.package_id,
            "packageDigest": package.package_digest,
            "modelDigest": section.model_digest,
            "validationMs": round(package.model_validation_ms, 4),
            "model": package.model.to_json(),
            "declaredLimits": section.limits().to_json(),
            "animationMap": dict(section.animation_map),
            "requiredRendererFeatures": list(section.required_renderer_features),
        }

    def renderer_3d_metrics(self, *, frames: int = 120) -> dict[str, Any]:
        """Draw a bounded number of frames offscreen and report the timings."""
        count = max(1, min(600, int(frames)))
        renderer = self._open()
        renderer.begin_offscreen(320, 400)
        from companion.character.mapper import CharacterState, map_character_state, StateMapperInput

        mapped = map_character_state(
            self.package.manifest,
            StateMapperInput(presentation_phase="working", status_text=""),
        )
        started = time.monotonic()
        renderer.display_state(mapped, now_ms=0)
        first_frame = (time.monotonic() - started) * 1000.0
        started = time.monotonic()
        for index in range(count):
            renderer.draw(now_ms=index * 16)
        wall = (time.monotonic() - started) * 1000.0
        width, height, pixels = renderer.read_pixels()
        drawn = sum(1 for index in range(3, len(pixels), 4) if pixels[index] > 12)
        renderer.end_offscreen()
        return {
            "operation": "renderer_3d_metrics",
            "frames": count,
            "firstFrameMs": round(first_frame, 4),
            "wallMs": round(wall, 4),
            "meanMsPerFrame": round(wall / count, 4),
            "frameStatistics": renderer.frame_statistics(),
            "surface": {"width": width, "height": height},
            "coveredPixels": drawn,
            "coverageFraction": round(drawn / max(1, width * height), 6),
            "resources": renderer.resources.to_json(),
        }

    def renderer_3d_explain(self) -> dict[str, Any]:
        """Why this machine would or would not draw in 3D, in words."""
        environment = three_d_environment()
        try:
            package = self._resolve_package()
            section = package.manifest.three_dimensional
            package_note = (
                f"package {package.manifest.package_id} declares "
                f"{package.model.triangle_count} triangles, {len(package.model.joints)} joints "
                f"and {len(package.model.clips)} clips, and needs about "
                f"{package.model.estimated_gpu_bytes // 1024} KiB of GPU memory"
            )
            features = list(section.required_renderer_features)
        except Exception as exc:  # noqa: BLE001 - explaining must not fail
            package_note = f"no 3D package could be validated: {exc}"
            features = []
        from .budget import DEFAULT_BUDGET

        return {
            "operation": "renderer_3d_explain",
            "environment": environment,
            "package": package_note,
            "requiredRendererFeatures": features,
            "budget": DEFAULT_BUDGET.to_json(),
            "ladder": [
                "full-3d", "lightweight-3d", "animated-2d", "static-image", "text-only",
            ],
            "notes": [
                "the capability projection decides the ceiling; this renderer never raises it",
                "a machine with no usable GPU is not eligible for 3D even where a context exists",
                "reduced motion keeps the 3D rung and removes crossfades and procedural movement",
            ],
        }

    def renderer_3d_reload(self) -> dict[str, Any]:
        """Re-validate and re-upload the selected package. Mutates nothing on disk."""
        before = None
        if self.renderer is not None:
            before = self.renderer.resources.to_json()
        self.close()
        self.package = None
        started = time.monotonic()
        renderer = self._open()
        elapsed = (time.monotonic() - started) * 1000.0
        return {
            "operation": "renderer_3d_reload",
            "reloadMs": round(elapsed, 4),
            "modelDigest": renderer.model.digest if renderer.model else None,
            "resourcesBefore": before,
            "resourcesAfter": renderer.resources.to_json(),
            "packagesMutated": 0,
        }


#: Name -> handler. Frozen; :func:`run_operation` consults nothing else.
_HANDLERS: Mapping[str, Callable[[ThreeDDiagnostics], dict[str, Any]]] = {
    "renderer_3d_health": ThreeDDiagnostics.renderer_3d_health,
    "renderer_3d_status": ThreeDDiagnostics.renderer_3d_status,
    "renderer_3d_model": ThreeDDiagnostics.renderer_3d_model,
    "renderer_3d_metrics": ThreeDDiagnostics.renderer_3d_metrics,
    "renderer_3d_explain": ThreeDDiagnostics.renderer_3d_explain,
    "renderer_3d_reload": ThreeDDiagnostics.renderer_3d_reload,
}

if tuple(_HANDLERS) != OPERATION_NAMES:  # pragma: no cover - a wiring mistake
    raise AssertionError("the 3D diagnostics table and its name list have drifted")


def run_operation(
    name: str,
    *,
    root: Path | None = None,
    package_id: str | None = None,
    frames: int | None = None,
) -> dict[str, Any]:
    """Dispatch one named operation. Refuses every name outside the table."""
    if name in REFUSED_OPERATIONS:
        raise RendererCapabilityError(
            f"{name} is refused by design: {REFUSED_OPERATIONS[name]}"
        )
    handler = _HANDLERS.get(str(name))
    if handler is None:
        raise RendererCapabilityError(
            f"unknown 3D diagnostics operation {name!r}; the operations are "
            + ", ".join(OPERATION_NAMES)
        )
    with ThreeDDiagnostics(root=root, package_id=package_id) as session:
        if name == "renderer_3d_metrics" and frames is not None:
            return session.renderer_3d_metrics(frames=frames)
        return handler(session)


__all__ = [
    "OPERATION_NAMES",
    "REFUSED_OPERATIONS",
    "ThreeDDiagnostics",
    "run_operation",
    "three_d_environment",
]
