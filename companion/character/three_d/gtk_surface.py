# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§16: the character inside a GTK window, on whatever compositor there is.

The only module in the 3D subsystem that knows GTK exists, and it imports it
inside a function. Everything above it — the state machine, the mixer, the face,
the camera, the renderer itself — is toolkit-free and tested without a
compositor; this file is the hundred lines where that stops being true, and
keeping it to a hundred lines is the point.

The arrangement is the one ``Gtk.GLArea`` is designed for and the one that keeps
the frame clock honest:

* GTK owns the context. :class:`companion.character.three_d.context.AdoptedContext`
  is how the renderer is told that — it creates nothing and destroys nothing,
  and its ``make_current`` is a no-op because the ``render`` signal has already
  made GTK's context current.
* **The frame clock is GTK's.** ``add_tick_callback`` fires on the compositor's
  own cadence; the renderer never sleeps, never rate-limits itself and never
  runs a loop. That is not a style preference — a nested compositor dies if it
  paces its own loop, and a GLArea that redrew on a timer would fight the frame
  clock rather than follow it.
* **Transparency is asked for, not assumed.** The clear colour has zero alpha
  and the widget requests it, and whether the surface is actually composited
  that way is the compositor's decision. :meth:`ThreeDCharacterArea.report` says
  which compositor answered rather than claiming a result.

Nothing here decides anything about a task. The widget is handed a
:class:`companion.character.mapper.MappedCharacterState` and draws it.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import time
from typing import Any, Callable

from .context import AdoptedContext
from .errors import RendererCapabilityError, RendererContextError

#: §16's surface modes and the character size each implies, as a fraction of the
#: work area's shorter side. Naming only: a Wayland compositor decides actual
#: placement, and this module says so rather than pretending otherwise.
SURFACE_MODES: dict[str, dict[str, Any]] = {
    "docked": {"fraction": 0.30, "camera": "waist-up"},
    "center": {"fraction": 0.55, "camera": "full-body"},
    "compact": {"fraction": 0.18, "camera": "compact"},
}


def gtk_available() -> tuple[bool, str]:
    """Whether PyGObject and GTK 4 can be imported. Imports nothing on failure."""
    try:
        import gi  # noqa: PLC0415 - the whole point is that this is deferred
    except ImportError as exc:
        return False, f"PyGObject is not installed: {exc}"
    try:
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk  # noqa: F401,PLC0415
    except (ValueError, ImportError) as exc:
        return False, f"GTK 4 is not available: {exc}"
    if not os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
        return False, "no WAYLAND_DISPLAY or DISPLAY is set"
    return True, "GTK 4 and a display are available"


@dataclass
class SurfaceReport:
    """What actually happened on this compositor. Measured, never assumed."""

    realized: bool = False
    context_created: bool = False
    frames_rendered: int = 0
    resizes: int = 0
    scale_changes: int = 0
    transparency_requested: bool = False
    alpha_supported: bool | None = None
    renderer_restarts: int = 0
    context_losses: int = 0
    errors: list[str] = None  # type: ignore[assignment]
    gl_renderer: str = ""
    gl_version: str = ""
    session_type: str = ""
    compositor: str = ""
    first_frame_ms: float | None = None
    frame_times_ms: list[float] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []
        if self.frame_times_ms is None:
            self.frame_times_ms = []

    def to_json(self) -> dict[str, Any]:
        samples = sorted(self.frame_times_ms)
        p95 = None
        if samples:
            index = max(0, min(len(samples) - 1, int(round(0.95 * (len(samples) - 1)))))
            p95 = round(samples[index], 4)
        return {
            "realized": self.realized,
            "contextCreated": self.context_created,
            "framesRendered": self.frames_rendered,
            "resizes": self.resizes,
            "scaleChanges": self.scale_changes,
            "transparencyRequested": self.transparency_requested,
            "alphaSupported": self.alpha_supported,
            "rendererRestarts": self.renderer_restarts,
            "contextLosses": self.context_losses,
            "errors": list(self.errors),
            "glRenderer": self.gl_renderer,
            "glVersion": self.gl_version,
            "sessionType": self.session_type,
            "compositor": self.compositor,
            "firstFrameMs": self.first_frame_ms,
            "frameCount": len(self.frame_times_ms),
            "meanFrameMs": (
                round(sum(samples) / len(samples), 4) if samples else None
            ),
            "p95FrameMs": p95,
        }


class ThreeDCharacterArea:
    """A ``Gtk.GLArea`` that draws one validated character.

    Constructed only after :func:`gtk_available` says yes and after the ladder
    has selected a 3D rung. It holds the renderer and the adopted context and
    nothing else; the mapped state arrives through :meth:`set_state`.
    """

    def __init__(
        self,
        package: Any,
        *,
        mode: str = "docked",
        scale: float = 1.0,
        seed: int | None = None,
        quality: str = "full-3d",
        motion: str = "full",
        on_error: Callable[[str, str], None] | None = None,
    ) -> None:
        available, reason = gtk_available()
        if not available:
            raise RendererCapabilityError(reason)
        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import Gdk, GLib, Gtk

        self.Gtk = Gtk
        self.Gdk = Gdk
        self.GLib = GLib
        self.package = package
        self.section = package.manifest.three_dimensional
        if self.section is None or package.model is None:
            raise RendererCapabilityError("the selected package carries no validated 3D model")
        self.mode = mode if mode in SURFACE_MODES else "docked"
        self.scale = float(scale)
        self.seed = seed
        self.quality = quality
        self.motion = motion
        self._on_error = on_error
        self.report = SurfaceReport(
            session_type=os.environ.get("XDG_SESSION_TYPE", ""),
            compositor=(
                "wayland:" + os.environ["WAYLAND_DISPLAY"]
                if os.environ.get("WAYLAND_DISPLAY")
                else "x11:" + os.environ.get("DISPLAY", "")
            ),
            transparency_requested=True,
        )
        self.context = AdoptedContext(mark_lost=self._context_lost)
        self.renderer: Any = None
        self.state: Any = None
        self._tick = None
        self._started = time.monotonic()

        self.area = Gtk.GLArea()
        self.area.set_has_depth_buffer(True)
        self.area.set_has_stencil_buffer(False)
        self.area.set_auto_render(False)
        # GTK 4.12 can be told to use desktop GL rather than GLES. The renderer
        # compiles ``#version 330 core``, which a GLES context refuses, so
        # asking is the difference between a working window and a shader error.
        if hasattr(self.area, "set_allowed_apis") and hasattr(Gdk, "GLAPI"):
            try:
                self.area.set_allowed_apis(Gdk.GLAPI.GL)
            except (TypeError, AttributeError):  # pragma: no cover - older GTK
                pass
        self.area.connect("realize", self._on_realize)
        self.area.connect("unrealize", self._on_unrealize)
        self.area.connect("render", self._on_render)
        self.area.connect("resize", self._on_resize)
        self.area.set_hexpand(True)
        self.area.set_vexpand(True)

    # -- lifecycle ---------------------------------------------------------

    def _fail(self, code: str, explanation: str) -> None:
        self.report.errors.append(f"{code}: {explanation}")
        if self._on_error is not None:
            self._on_error(code, explanation)

    def _context_lost(self, reason: str) -> None:
        self.report.context_losses += 1
        self._fail("gpu-context-lost", reason or "the GTK context reported loss")

    def _on_realize(self, area: Any) -> None:
        try:
            area.make_current()
            error = area.get_error()
            if error is not None:
                raise RendererContextError(str(error.message))
            self.report.realized = True
            self._build_renderer()
            self.report.context_created = True
            info = self.context.info()
            self.report.gl_renderer = info.renderer
            self.report.gl_version = info.version
            self._tick = area.add_tick_callback(self._on_tick)
        except Exception as exc:  # noqa: BLE001 - a realize fault degrades
            self._fail(type(exc).__name__, str(exc))

    def _build_renderer(self) -> None:
        from .renderer import ThreeDRenderer

        renderer = ThreeDRenderer(
            context=self.context, quality=self.quality, motion=self.motion, seed=self.seed,
        )
        renderer.load_package(self.package)
        renderer.upload(
            self.package.model,
            animation_map=self.section.animation_map,
            expression_map=self.section.expression_map,
            viseme_map=self.section.viseme_map,
            native_scale=self.section.native_scale,
            floor_offset=self.section.floor_offset,
        )
        renderer.set_scale(self.scale)
        renderer.camera.set_mode(SURFACE_MODES[self.mode]["camera"])
        width = max(1, self.area.get_allocated_width())
        height = max(1, self.area.get_allocated_height())
        renderer.set_surface_size(width, height)
        self.renderer = renderer

    def _on_unrealize(self, area: Any) -> None:
        if self._tick is not None:
            try:
                area.remove_tick_callback(self._tick)
            except (TypeError, ValueError):  # pragma: no cover - already gone
                pass
            self._tick = None
        if self.renderer is not None:
            try:
                area.make_current()
                self.renderer.release()
            except Exception as exc:  # noqa: BLE001 - teardown must not raise
                self._fail("release-failed", str(exc))
                self.renderer.release(context_lost=True)
            self.renderer = None
        self.context.release()

    # -- drawing -----------------------------------------------------------

    def _on_render(self, area: Any, _context: Any) -> bool:
        if self.renderer is None:
            return False
        started = time.monotonic()
        try:
            gl = self.context.make_current()
            # Transparent where the compositor allows it; the character is what
            # is drawn, never a background.
            self.renderer.background = (0.0, 0.0, 0.0, 0.0)
            if self.state is not None:
                self.renderer.display_state(self.state, now_ms=self._now_ms())
            else:
                self.renderer.draw(now_ms=self._now_ms())
            self.report.frames_rendered += 1
            elapsed = (time.monotonic() - started) * 1000.0
            if self.report.first_frame_ms is None:
                self.report.first_frame_ms = round(elapsed, 4)
            self.report.frame_times_ms.append(elapsed)
            if len(self.report.frame_times_ms) > 2000:
                del self.report.frame_times_ms[:-2000]
            if self.report.alpha_supported is None:
                self.report.alpha_supported = bool(getattr(area, "get_has_alpha", lambda: True)())
        except Exception as exc:  # noqa: BLE001 - a render fault degrades
            self._fail(type(exc).__name__, str(exc))
            return False
        return True

    def _on_tick(self, area: Any, _clock: Any) -> bool:
        # The compositor's clock, not ours. Queueing a render is the whole of
        # this callback; the renderer's own frame-rate cap decides whether the
        # draw does any work.
        area.queue_render()
        return self.GLib.SOURCE_CONTINUE

    def _on_resize(self, area: Any, width: int, height: int) -> None:
        self.report.resizes += 1
        if self.renderer is not None:
            self.renderer.set_surface_size(max(1, width), max(1, height))

    def _now_ms(self) -> int:
        return round((time.monotonic() - self._started) * 1000)

    # -- inputs ------------------------------------------------------------

    def set_state(self, state: Any) -> None:
        self.state = state
        self.area.queue_render()

    def set_mouth_shape(self, shape: str) -> None:
        if self.renderer is not None:
            self.renderer.set_mouth_shape(shape)
            self.area.queue_render()

    def set_scale(self, scale: float) -> None:
        self.scale = float(scale)
        self.report.scale_changes += 1
        if self.renderer is not None:
            self.renderer.set_scale(self.scale)
            self.area.queue_render()

    def set_mode(self, mode: str) -> str:
        self.mode = mode if mode in SURFACE_MODES else self.mode
        if self.renderer is not None:
            self.renderer.camera.set_mode(SURFACE_MODES[self.mode]["camera"])
            self.area.queue_render()
        return self.mode

    def set_reduced_motion(self, enabled: bool) -> None:
        self.motion = "reduced" if enabled else "full"
        if self.renderer is not None:
            self.renderer.set_reduced_motion(enabled)
            self.area.queue_render()

    def restart(self) -> bool:
        """Rebuild the renderer inside the same GTK context. §32's restart."""
        if not self.report.realized:
            return False
        try:
            self.area.make_current()
            if self.renderer is not None:
                self.renderer.release()
                self.renderer = None
            self._build_renderer()
            self.report.renderer_restarts += 1
            self.area.queue_render()
            return True
        except Exception as exc:  # noqa: BLE001 - a restart fault degrades
            self._fail("restart-failed", str(exc))
            return False

    def describe(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "scale": self.scale,
            "surface": self.report.to_json(),
            "renderer": self.renderer.describe() if self.renderer is not None else None,
        }


__all__ = ["SURFACE_MODES", "SurfaceReport", "ThreeDCharacterArea", "gtk_available"]
