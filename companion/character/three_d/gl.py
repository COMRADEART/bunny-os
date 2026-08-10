# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""A minimal OpenGL 3.3 core binding, owned by this repository.

Why not PyOpenGL, ModernGL or wgpu: the Bunny OS image already ships Mesa,
``gtk4`` and ``python3-gobject``, and every one of those alternatives adds a
package — two, with NumPy — to a desktop image in order to call about fifty C
functions that ``ctypes`` can call directly. ADR-030 records the comparison. The
short form is that the dependency cost of a binding is paid by every installed
machine forever, and the maintenance cost of *this* file is bounded by the
function list below, which is closed: a renderer that needs a function not here
is a renderer that has grown past what this phase implements.

Three properties matter more than the size.

**Nothing is loaded at import.** ``import companion.character.three_d.gl`` opens
no library and resolves no symbol. :func:`load_gl` does that, and it is called
after a context is current — which is also the only moment at which resolving a
GL symbol is meaningful. §30's "do not initialise GPU libraries unnecessarily in
headless mode" is therefore a property of the module rather than a discipline
the callers have to keep.

**Every call is checked, in the places where checking is affordable.**
:meth:`GL.check` reads ``glGetError`` and raises
:class:`companion.character.three_d.errors.RendererContextError`. It is called
after allocation, compilation and upload — the operations that fail — and not
inside the draw loop, where a per-call ``glGetError`` costs a pipeline flush.

**The symbol list is a contract.** ``libGL.so.1`` under libglvnd exports the
whole core profile, so symbols resolve directly; where they do not, the
platform's ``GetProcAddress`` is tried. A symbol that resolves to neither raises
at load time with its own name in the message, rather than segfaulting at the
first draw.
"""

from __future__ import annotations

import ctypes
import ctypes.util
from typing import Any, Iterable, Sequence

from .errors import RendererCapabilityError, RendererContextError

# --- constants ------------------------------------------------------------ #

GL_FALSE = 0
GL_TRUE = 1
GL_NO_ERROR = 0
GL_TRIANGLES = 0x0004
GL_UNSIGNED_BYTE = 0x1401
GL_UNSIGNED_SHORT = 0x1403
GL_UNSIGNED_INT = 0x1405
GL_FLOAT = 0x1406
GL_DEPTH_TEST = 0x0B71
GL_CULL_FACE = 0x0B44
GL_BLEND = 0x0BE2
GL_BACK = 0x0405
GL_CCW = 0x0901
GL_LESS = 0x0201
GL_LEQUAL = 0x0203
GL_SRC_ALPHA = 0x0302
GL_ONE_MINUS_SRC_ALPHA = 0x0303
GL_COLOR_BUFFER_BIT = 0x00004000
GL_DEPTH_BUFFER_BIT = 0x00000100
GL_ARRAY_BUFFER = 0x8892
GL_ELEMENT_ARRAY_BUFFER = 0x8893
GL_STATIC_DRAW = 0x88E4
GL_VERTEX_SHADER = 0x8B31
GL_FRAGMENT_SHADER = 0x8B30
GL_COMPILE_STATUS = 0x8B81
GL_LINK_STATUS = 0x8B82
GL_INFO_LOG_LENGTH = 0x8B84
GL_TEXTURE_2D = 0x0DE1
GL_TEXTURE0 = 0x84C0
GL_TEXTURE1 = 0x84C1
GL_RGBA = 0x1908
GL_RGB = 0x1907
GL_RGBA8 = 0x8058
GL_RGB32F = 0x8815
GL_TEXTURE_MIN_FILTER = 0x2801
GL_TEXTURE_MAG_FILTER = 0x2800
GL_TEXTURE_WRAP_S = 0x2802
GL_TEXTURE_WRAP_T = 0x2803
GL_NEAREST = 0x2600
GL_LINEAR = 0x2601
GL_LINEAR_MIPMAP_LINEAR = 0x2703
GL_CLAMP_TO_EDGE = 0x812F
GL_REPEAT = 0x2901
GL_MIRRORED_REPEAT = 0x8370
GL_UNPACK_ALIGNMENT = 0x0CF5
GL_PACK_ALIGNMENT = 0x0D05
GL_FRAMEBUFFER = 0x8D40
GL_RENDERBUFFER = 0x8D41
GL_COLOR_ATTACHMENT0 = 0x8CE0
GL_DEPTH_ATTACHMENT = 0x8D00
GL_DEPTH_COMPONENT24 = 0x81A6
GL_FRAMEBUFFER_COMPLETE = 0x8CD5
GL_VENDOR = 0x1F00
GL_RENDERER = 0x1F01
GL_VERSION = 0x1F02
GL_SHADING_LANGUAGE_VERSION = 0x8B8C
GL_MAX_TEXTURE_SIZE = 0x0D33
GL_MAX_VERTEX_UNIFORM_COMPONENTS = 0x8B4A
GL_MAX_VERTEX_ATTRIBS = 0x8869
GL_MAX_TEXTURE_IMAGE_UNITS = 0x8872
GL_MAX_VERTEX_TEXTURE_IMAGE_UNITS = 0x8B4C

_ERROR_NAMES = {
    0x0500: "GL_INVALID_ENUM",
    0x0501: "GL_INVALID_VALUE",
    0x0502: "GL_INVALID_OPERATION",
    0x0503: "GL_STACK_OVERFLOW",
    0x0504: "GL_STACK_UNDERFLOW",
    0x0505: "GL_OUT_OF_MEMORY",
    0x0506: "GL_INVALID_FRAMEBUFFER_OPERATION",
    0x0507: "GL_CONTEXT_LOST",
}

_VOID_P = ctypes.c_void_p
_GLenum = ctypes.c_uint
_GLuint = ctypes.c_uint
_GLint = ctypes.c_int
_GLsizei = ctypes.c_int
_GLfloat = ctypes.c_float
_GLboolean = ctypes.c_ubyte
_GLchar_p = ctypes.c_char_p
_GLbitfield = ctypes.c_uint
_GLintptr = ctypes.c_ssize_t
_GLsizeiptr = ctypes.c_ssize_t

#: ``name: (restype, argtypes)``. Closed by design; see the module docstring.
_SIGNATURES: dict[str, tuple[Any, tuple[Any, ...]]] = {
    "glGetError": (_GLenum, ()),
    "glGetString": (ctypes.c_char_p, (_GLenum,)),
    "glGetIntegerv": (None, (_GLenum, ctypes.POINTER(_GLint))),
    "glViewport": (None, (_GLint, _GLint, _GLsizei, _GLsizei)),
    "glClearColor": (None, (_GLfloat, _GLfloat, _GLfloat, _GLfloat)),
    "glClear": (None, (_GLbitfield,)),
    "glEnable": (None, (_GLenum,)),
    "glDisable": (None, (_GLenum,)),
    "glBlendFunc": (None, (_GLenum, _GLenum)),
    "glDepthFunc": (None, (_GLenum,)),
    "glCullFace": (None, (_GLenum,)),
    "glFrontFace": (None, (_GLenum,)),
    "glPixelStorei": (None, (_GLenum, _GLint)),
    "glFinish": (None, ()),
    "glFlush": (None, ()),
    "glCreateShader": (_GLuint, (_GLenum,)),
    "glShaderSource": (None, (_GLuint, _GLsizei, ctypes.POINTER(_GLchar_p), ctypes.POINTER(_GLint))),
    "glCompileShader": (None, (_GLuint,)),
    "glGetShaderiv": (None, (_GLuint, _GLenum, ctypes.POINTER(_GLint))),
    "glGetShaderInfoLog": (None, (_GLuint, _GLsizei, ctypes.POINTER(_GLsizei), ctypes.c_char_p)),
    "glDeleteShader": (None, (_GLuint,)),
    "glCreateProgram": (_GLuint, ()),
    "glAttachShader": (None, (_GLuint, _GLuint)),
    "glDetachShader": (None, (_GLuint, _GLuint)),
    "glLinkProgram": (None, (_GLuint,)),
    "glGetProgramiv": (None, (_GLuint, _GLenum, ctypes.POINTER(_GLint))),
    "glGetProgramInfoLog": (None, (_GLuint, _GLsizei, ctypes.POINTER(_GLsizei), ctypes.c_char_p)),
    "glUseProgram": (None, (_GLuint,)),
    "glDeleteProgram": (None, (_GLuint,)),
    "glGetUniformLocation": (_GLint, (_GLuint, _GLchar_p)),
    "glUniform1i": (None, (_GLint, _GLint)),
    "glUniform1f": (None, (_GLint, _GLfloat)),
    "glUniform1fv": (None, (_GLint, _GLsizei, ctypes.POINTER(_GLfloat))),
    "glUniform1iv": (None, (_GLint, _GLsizei, ctypes.POINTER(_GLint))),
    "glUniform3fv": (None, (_GLint, _GLsizei, ctypes.POINTER(_GLfloat))),
    "glUniform4fv": (None, (_GLint, _GLsizei, ctypes.POINTER(_GLfloat))),
    "glUniformMatrix4fv": (None, (_GLint, _GLsizei, _GLboolean, ctypes.POINTER(_GLfloat))),
    "glGenVertexArrays": (None, (_GLsizei, ctypes.POINTER(_GLuint))),
    "glBindVertexArray": (None, (_GLuint,)),
    "glDeleteVertexArrays": (None, (_GLsizei, ctypes.POINTER(_GLuint))),
    "glGenBuffers": (None, (_GLsizei, ctypes.POINTER(_GLuint))),
    "glBindBuffer": (None, (_GLenum, _GLuint)),
    "glBufferData": (None, (_GLenum, _GLsizeiptr, _VOID_P, _GLenum)),
    "glDeleteBuffers": (None, (_GLsizei, ctypes.POINTER(_GLuint))),
    "glEnableVertexAttribArray": (None, (_GLuint,)),
    "glDisableVertexAttribArray": (None, (_GLuint,)),
    "glVertexAttribPointer": (None, (_GLuint, _GLint, _GLenum, _GLboolean, _GLsizei, _VOID_P)),
    "glVertexAttribIPointer": (None, (_GLuint, _GLint, _GLenum, _GLsizei, _VOID_P)),
    "glBindAttribLocation": (None, (_GLuint, _GLuint, _GLchar_p)),
    "glGenTextures": (None, (_GLsizei, ctypes.POINTER(_GLuint))),
    "glBindTexture": (None, (_GLenum, _GLuint)),
    "glTexImage2D": (None, (_GLenum, _GLint, _GLint, _GLsizei, _GLsizei, _GLint, _GLenum, _GLenum, _VOID_P)),
    "glTexParameteri": (None, (_GLenum, _GLenum, _GLint)),
    "glDeleteTextures": (None, (_GLsizei, ctypes.POINTER(_GLuint))),
    "glActiveTexture": (None, (_GLenum,)),
    "glGenerateMipmap": (None, (_GLenum,)),
    "glDrawElements": (None, (_GLenum, _GLsizei, _GLenum, _VOID_P)),
    "glGenFramebuffers": (None, (_GLsizei, ctypes.POINTER(_GLuint))),
    "glBindFramebuffer": (None, (_GLenum, _GLuint)),
    "glFramebufferTexture2D": (None, (_GLenum, _GLenum, _GLenum, _GLuint, _GLint)),
    "glFramebufferRenderbuffer": (None, (_GLenum, _GLenum, _GLenum, _GLuint)),
    "glCheckFramebufferStatus": (_GLenum, (_GLenum,)),
    "glDeleteFramebuffers": (None, (_GLsizei, ctypes.POINTER(_GLuint))),
    "glGenRenderbuffers": (None, (_GLsizei, ctypes.POINTER(_GLuint))),
    "glBindRenderbuffer": (None, (_GLenum, _GLuint)),
    "glRenderbufferStorage": (None, (_GLenum, _GLenum, _GLsizei, _GLsizei)),
    "glDeleteRenderbuffers": (None, (_GLsizei, ctypes.POINTER(_GLuint))),
    "glReadPixels": (None, (_GLint, _GLint, _GLsizei, _GLsizei, _GLenum, _GLenum, _VOID_P)),
}


class GL:
    """One loaded GL entry-point table, bound to whatever context was current."""

    def __init__(self, library: Any, resolver: Any | None = None) -> None:
        self._library = library
        self._resolver = resolver
        self._functions: dict[str, Any] = {}
        missing: list[str] = []
        for name, (restype, argtypes) in _SIGNATURES.items():
            function = self._resolve(name, restype, argtypes)
            if function is None:
                missing.append(name)
                continue
            self._functions[name] = function
            setattr(self, name, function)
        if missing:
            raise RendererCapabilityError(
                "the graphics stack does not provide: " + ", ".join(sorted(missing))
            )

    def _resolve(self, name: str, restype: Any, argtypes: tuple[Any, ...]) -> Any:
        function = getattr(self._library, name, None)
        if function is None and self._resolver is not None:
            address = self._resolver(name.encode("ascii"))
            if address:
                prototype = ctypes.CFUNCTYPE(restype, *argtypes)
                return prototype(address)
            return None
        if function is None:
            return None
        function.restype = restype
        function.argtypes = list(argtypes)
        return function

    # -- convenience -------------------------------------------------------

    def check(self, what: str) -> None:
        """Raise if the driver recorded an error. Called at allocation points."""
        code = self.glGetError()
        if code != GL_NO_ERROR:
            drained = 0
            while self.glGetError() != GL_NO_ERROR and drained < 16:
                drained += 1
            raise RendererContextError(
                f"{what} failed with {_ERROR_NAMES.get(code, hex(code))}"
            )

    def drain_errors(self) -> int:
        count = 0
        while self.glGetError() != GL_NO_ERROR and count < 64:
            count += 1
        return count

    def string(self, name: int) -> str:
        value = self.glGetString(name)
        return value.decode("utf-8", "replace") if value else ""

    def integer(self, name: int) -> int:
        value = _GLint(0)
        self.glGetIntegerv(name, ctypes.byref(value))
        return int(value.value)

    def gen(self, generator: str, count: int = 1) -> list[int]:
        buffer = (_GLuint * count)()
        getattr(self, generator)(count, buffer)
        return [int(item) for item in buffer]

    def delete(self, deleter: str, names: Iterable[int]) -> None:
        values = [int(name) for name in names if name]
        if not values:
            return
        buffer = (_GLuint * len(values))(*values)
        getattr(self, deleter)(len(values), buffer)

    def floats(self, values: Sequence[float]) -> Any:
        return (_GLfloat * len(values))(*[float(value) for value in values])

    def ints(self, values: Sequence[int]) -> Any:
        return (_GLint * len(values))(*[int(value) for value in values])

    def capabilities(self) -> dict[str, Any]:
        return {
            "vendor": self.string(GL_VENDOR),
            "renderer": self.string(GL_RENDERER),
            "version": self.string(GL_VERSION),
            "shadingLanguageVersion": self.string(GL_SHADING_LANGUAGE_VERSION),
            "maxTextureSize": self.integer(GL_MAX_TEXTURE_SIZE),
            "maxVertexUniformComponents": self.integer(GL_MAX_VERTEX_UNIFORM_COMPONENTS),
            "maxVertexAttribs": self.integer(GL_MAX_VERTEX_ATTRIBS),
            "maxVertexTextureImageUnits": self.integer(GL_MAX_VERTEX_TEXTURE_IMAGE_UNITS),
        }


_LOADED: GL | None = None


def load_gl(*, reload: bool = False) -> GL:
    """Open ``libGL`` and bind the table. Only meaningful with a current context.

    Cached, because resolving fifty symbols costs a few milliseconds and the
    table is context-independent under libglvnd. ``reload=True`` exists for the
    renderer-restart path, where the cheapest way to be certain nothing stale is
    held is to bind again.
    """
    global _LOADED
    if _LOADED is not None and not reload:
        return _LOADED
    candidates = ["libGL.so.1", "libGL.so"]
    found = ctypes.util.find_library("GL")
    if found:
        candidates.append(found)
    library = None
    errors: list[str] = []
    for candidate in candidates:
        try:
            library = ctypes.CDLL(candidate, mode=ctypes.RTLD_GLOBAL)
            break
        except OSError as exc:
            errors.append(f"{candidate}: {exc}")
    if library is None:
        raise RendererCapabilityError(
            "no OpenGL library could be opened (" + "; ".join(errors) + ")"
        )
    resolver = None
    for name in ("glXGetProcAddressARB", "glXGetProcAddress", "eglGetProcAddress"):
        candidate_resolver = getattr(library, name, None)
        if candidate_resolver is not None:
            candidate_resolver.restype = ctypes.c_void_p
            candidate_resolver.argtypes = [ctypes.c_char_p]
            resolver = candidate_resolver
            break
    _LOADED = GL(library, resolver)
    return _LOADED


def unload_gl() -> None:
    """Forget the cached table. The library itself stays mapped, as ``dlclose``
    on a driver that has registered TLS destructors is how a process crashes at
    exit; releasing our *reference* is the part that is ours to do."""
    global _LOADED
    _LOADED = None


__all__ = ["GL", "load_gl", "unload_gl"] + [
    name for name in dir() if name.startswith("GL_")
]
