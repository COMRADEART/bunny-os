# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Where a GL context comes from, and what happens when it goes away.

Two providers, one contract.

:class:`SurfacelessContext`
    An EGL context with no window, created through
    ``EGL_PLATFORM_SURFACELESS_MESA``. It is what makes 3D *testable*: the
    renderer can draw a frame, read the pixels back and assert that a character
    appeared, on a build machine with no compositor and inside a stress gate
    that runs a hundred times. It is also what the diagnostics use, because
    "does this machine's graphics stack work" is a question a headless service
    should be able to answer without opening a window on somebody's desktop.

:class:`AdoptedContext`
    A context somebody else made current — in practice GTK's ``GLArea``, which
    creates and manages its own and calls back with it bound. This provider owns
    nothing and destroys nothing; it exists so the renderer has one code path
    whether GTK or EGL is underneath.

**A context is never created speculatively.** §30: in text-only or headless
presentation nothing here is constructed, so ``libEGL`` is never opened. The
selection ladder decides first; this module runs afterwards or not at all.

**Loss is expected.** :meth:`GraphicsContext.lost` is checked before each frame
and any provider may report it — a compositor restart, a GPU reset, a display
that went away. The renderer's answer is always the same: release what it can,
emit a typed degradation, drop a rung, and retry only after a bounded interval.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import ctypes
import ctypes.util
from dataclasses import dataclass
import os
from typing import Any

from .errors import RendererCapabilityError, RendererContextError
from .gl import GL, load_gl

# --- EGL constants -------------------------------------------------------- #

EGL_NONE = 0x3038
EGL_OPENGL_API = 0x30A2
EGL_PLATFORM_SURFACELESS_MESA = 0x31DD
EGL_PLATFORM_DEVICE_EXT = 0x313F
EGL_SURFACE_TYPE = 0x3033
EGL_PBUFFER_BIT = 0x0001
EGL_RENDERABLE_TYPE = 0x3040
EGL_OPENGL_BIT = 0x0008
EGL_RED_SIZE = 0x3024
EGL_GREEN_SIZE = 0x3023
EGL_BLUE_SIZE = 0x3022
EGL_ALPHA_SIZE = 0x3021
EGL_DEPTH_SIZE = 0x3025
EGL_CONTEXT_MAJOR_VERSION = 0x3098
EGL_CONTEXT_MINOR_VERSION = 0x30FB
EGL_CONTEXT_OPENGL_PROFILE_MASK = 0x30FD
EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT = 0x00000001
EGL_CONTEXT_LOST = 0x300E
EGL_BAD_CONTEXT = 0x3006
EGL_SUCCESS = 0x3000
EGL_VENDOR = 0x3053
EGL_VERSION = 0x3054


@dataclass(frozen=True)
class ContextInfo:
    """What the driver said about itself, recorded once and reported honestly."""

    provider: str
    vendor: str
    renderer: str
    version: str
    shading_language: str
    max_texture_size: int
    max_vertex_uniform_components: int
    accelerated: bool | None
    egl_vendor: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "vendor": self.vendor,
            "renderer": self.renderer,
            "version": self.version,
            "shadingLanguageVersion": self.shading_language,
            "maxTextureSize": self.max_texture_size,
            "maxVertexUniformComponents": self.max_vertex_uniform_components,
            # ``None`` where the stack does not say. A renderer string
            # containing "llvmpipe" or "softpipe" is Mesa's software rasteriser
            # and is reported as software rather than guessed at, because every
            # frame-time measurement in §35 means something different depending
            # on which of the two it was.
            "accelerated": self.accelerated,
            "eglVendor": self.egl_vendor,
        }


class GraphicsContext(ABC):
    """The contract the renderer holds. Nothing above this knows about EGL."""

    provider = "abstract"

    @abstractmethod
    def make_current(self) -> GL:
        """Bind the context and return the entry-point table."""

    @abstractmethod
    def release(self) -> None:
        """Give back everything this provider owns. Never raises."""

    @property
    @abstractmethod
    def lost(self) -> bool:
        """Whether the context is known to be gone."""

    @abstractmethod
    def info(self) -> ContextInfo:
        """What the driver reports. Valid only while current."""


def _software(renderer: str) -> bool | None:
    lowered = renderer.casefold()
    if not lowered:
        return None
    for marker in ("llvmpipe", "softpipe", "swrast", "software rasterizer"):
        if marker in lowered:
            return False
    return True


class AdoptedContext(GraphicsContext):
    """A context somebody else owns — GTK's ``GLArea``, in practice.

    ``make_current`` does not bind anything: the caller has already done so,
    because that is what a ``GLArea`` render callback *is*. What it does is bind
    the entry-point table, which is the part the renderer needs and the part a
    toolkit does not provide.
    """

    provider = "adopted"

    def __init__(self, *, mark_lost: Any = None) -> None:
        self._gl: GL | None = None
        self._lost = False
        self._mark_lost = mark_lost

    def make_current(self) -> GL:
        if self._lost:
            raise RendererContextError("the adopted graphics context has been reported lost")
        if self._gl is None:
            self._gl = load_gl()
        return self._gl

    def mark_lost(self, reason: str = "") -> None:
        self._lost = True
        if callable(self._mark_lost):
            self._mark_lost(reason)

    def release(self) -> None:
        self._gl = None

    @property
    def lost(self) -> bool:
        return self._lost

    def info(self) -> ContextInfo:
        gl = self.make_current()
        capabilities = gl.capabilities()
        return ContextInfo(
            provider=self.provider,
            vendor=capabilities["vendor"],
            renderer=capabilities["renderer"],
            version=capabilities["version"],
            shading_language=capabilities["shadingLanguageVersion"],
            max_texture_size=capabilities["maxTextureSize"],
            max_vertex_uniform_components=capabilities["maxVertexUniformComponents"],
            accelerated=_software(capabilities["renderer"]),
        )


class SurfacelessContext(GraphicsContext):
    """An offscreen EGL context. Opens ``libEGL`` when constructed, not before."""

    provider = "egl-surfaceless"

    def __init__(self) -> None:
        self._egl = self._open()
        self._display = None
        self._context = None
        self._gl: GL | None = None
        self._lost = False
        self._loss_reason = ""
        self._egl_vendor = ""
        self._create()

    @staticmethod
    def _open() -> Any:
        candidates = ["libEGL.so.1", "libEGL.so"]
        found = ctypes.util.find_library("EGL")
        if found:
            candidates.append(found)
        errors: list[str] = []
        for candidate in candidates:
            try:
                return ctypes.CDLL(candidate, mode=ctypes.RTLD_GLOBAL)
            except OSError as exc:
                errors.append(f"{candidate}: {exc}")
        raise RendererCapabilityError("libEGL is unavailable (" + "; ".join(errors) + ")")

    def _create(self) -> None:
        egl = self._egl
        egl.eglGetError.restype = ctypes.c_int
        egl.eglGetProcAddress.restype = ctypes.c_void_p
        egl.eglGetProcAddress.argtypes = [ctypes.c_char_p]

        get_platform_display = egl.eglGetProcAddress(b"eglGetPlatformDisplayEXT")
        display = None
        if get_platform_display:
            prototype = ctypes.CFUNCTYPE(
                ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)
            )
            display = prototype(get_platform_display)(
                EGL_PLATFORM_SURFACELESS_MESA, None, None
            )
        if not display:
            egl.eglGetDisplay.restype = ctypes.c_void_p
            egl.eglGetDisplay.argtypes = [ctypes.c_void_p]
            display = egl.eglGetDisplay(ctypes.c_void_p(0))
        if not display:
            raise RendererCapabilityError("no EGL display is available for offscreen rendering")

        major, minor = ctypes.c_int(0), ctypes.c_int(0)
        egl.eglInitialize.restype = ctypes.c_uint
        egl.eglInitialize.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
        if not egl.eglInitialize(ctypes.c_void_p(display), ctypes.byref(major), ctypes.byref(minor)):
            raise RendererCapabilityError(
                f"eglInitialize failed with 0x{egl.eglGetError():04x}"
            )
        self._display = display
        egl.eglQueryString.restype = ctypes.c_char_p
        egl.eglQueryString.argtypes = [ctypes.c_void_p, ctypes.c_int]
        vendor = egl.eglQueryString(ctypes.c_void_p(display), EGL_VENDOR)
        self._egl_vendor = vendor.decode("utf-8", "replace") if vendor else ""

        egl.eglBindAPI.restype = ctypes.c_uint
        egl.eglBindAPI.argtypes = [ctypes.c_uint]
        if not egl.eglBindAPI(EGL_OPENGL_API):
            raise RendererCapabilityError("this EGL implementation cannot bind desktop OpenGL")

        attributes = (ctypes.c_int * 13)(
            EGL_SURFACE_TYPE, EGL_PBUFFER_BIT,
            EGL_RENDERABLE_TYPE, EGL_OPENGL_BIT,
            EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8,
            EGL_ALPHA_SIZE, 8,
            EGL_NONE,
        )
        config = ctypes.c_void_p()
        count = ctypes.c_int(0)
        egl.eglChooseConfig.restype = ctypes.c_uint
        egl.eglChooseConfig.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_int, ctypes.POINTER(ctypes.c_int),
        ]
        if not egl.eglChooseConfig(
            ctypes.c_void_p(display), attributes, ctypes.byref(config), 1, ctypes.byref(count)
        ) or count.value < 1:
            raise RendererCapabilityError("no EGL configuration supports offscreen desktop GL")

        context_attributes = (ctypes.c_int * 7)(
            EGL_CONTEXT_MAJOR_VERSION, 3,
            EGL_CONTEXT_MINOR_VERSION, 3,
            EGL_CONTEXT_OPENGL_PROFILE_MASK, EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT,
            EGL_NONE,
        )
        egl.eglCreateContext.restype = ctypes.c_void_p
        egl.eglCreateContext.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)
        ]
        context = egl.eglCreateContext(
            ctypes.c_void_p(display), config, ctypes.c_void_p(0), context_attributes
        )
        if not context:
            raise RendererCapabilityError(
                f"eglCreateContext failed with 0x{egl.eglGetError():04x}; "
                "an OpenGL 3.3 core context is required"
            )
        self._context = context

    def make_current(self) -> GL:
        if self._lost:
            raise RendererContextError("the offscreen graphics context has been lost")
        egl = self._egl
        egl.eglMakeCurrent.restype = ctypes.c_uint
        egl.eglMakeCurrent.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
        ]
        if not egl.eglMakeCurrent(
            ctypes.c_void_p(self._display), ctypes.c_void_p(0), ctypes.c_void_p(0),
            ctypes.c_void_p(self._context),
        ):
            code = egl.eglGetError()
            if code in (EGL_CONTEXT_LOST, EGL_BAD_CONTEXT):
                self._lost = True
            raise RendererContextError(f"eglMakeCurrent failed with 0x{code:04x}")
        if self._gl is None:
            self._gl = load_gl()
        return self._gl

    def simulate_loss(self, reason: str = "test-requested context loss") -> None:
        """Mark the context lost without destroying it.

        §23 asks for context loss to be handled, and a test that could not
        produce one would be asserting on a path nobody had run. This is the
        only way to *cause* it, it is called by tests and by the §33 slice, and
        it is deliberately not reachable from any protocol operation.
        """
        self._lost = True
        self._loss_reason = reason

    def release(self) -> None:
        egl = self._egl
        try:
            if self._display is not None:
                egl.eglMakeCurrent.restype = ctypes.c_uint
                egl.eglMakeCurrent.argtypes = [
                    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
                ]
                egl.eglMakeCurrent(
                    ctypes.c_void_p(self._display), ctypes.c_void_p(0),
                    ctypes.c_void_p(0), ctypes.c_void_p(0),
                )
            if self._context is not None and self._display is not None:
                egl.eglDestroyContext.restype = ctypes.c_uint
                egl.eglDestroyContext.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
                egl.eglDestroyContext(ctypes.c_void_p(self._display), ctypes.c_void_p(self._context))
            if self._display is not None:
                egl.eglTerminate.restype = ctypes.c_uint
                egl.eglTerminate.argtypes = [ctypes.c_void_p]
                egl.eglTerminate(ctypes.c_void_p(self._display))
        except Exception:  # noqa: BLE001 - release must not raise
            pass
        finally:
            self._context = None
            self._display = None
            self._gl = None

    @property
    def lost(self) -> bool:
        return self._lost

    def info(self) -> ContextInfo:
        gl = self.make_current()
        capabilities = gl.capabilities()
        return ContextInfo(
            provider=self.provider,
            vendor=capabilities["vendor"],
            renderer=capabilities["renderer"],
            version=capabilities["version"],
            shading_language=capabilities["shadingLanguageVersion"],
            max_texture_size=capabilities["maxTextureSize"],
            max_vertex_uniform_components=capabilities["maxVertexUniformComponents"],
            accelerated=_software(capabilities["renderer"]),
            egl_vendor=self._egl_vendor,
        )


def offscreen_available() -> tuple[bool, str]:
    """Whether an offscreen context can be made here, without making one.

    Cheap and side-effect-free by design: it is called by the eligibility check
    on every start-up, including on machines that will never draw in 3D, and
    §30 forbids initialising a GPU library to answer a question about whether
    one is needed. So this looks for the *library*, not for a context.
    """
    if os.name == "nt":
        return False, "offscreen EGL rendering is implemented for Linux graphics stacks only"
    for candidate in ("libEGL.so.1", "libEGL.so"):
        try:
            handle = ctypes.CDLL(candidate)
        except OSError:
            continue
        del handle
        return True, "libEGL is present"
    if ctypes.util.find_library("EGL"):
        return True, "libEGL is present"
    return False, "libEGL is not installed"


__all__ = [
    "AdoptedContext",
    "ContextInfo",
    "GraphicsContext",
    "SurfacelessContext",
    "offscreen_available",
]
