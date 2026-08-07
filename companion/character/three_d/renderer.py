# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The 3D character renderer: uploads a validated model and draws it.

It implements :class:`companion.character.renderer.CharacterRenderer`, which is
what lets the existing controller drive it exactly as it drives the static and
animated-2D renderers — same package loading, same position, same scale, same
speech bubble, same mouth shape, same status. A fifth rung on a ladder should not
need a second ladder.

What is new below that contract is the GPU, and everything about it is arranged
so a failure is a degradation rather than a crash:

* every allocation goes through :class:`companion.character.three_d.gpu.GpuResources`,
  so "release everything" is a method rather than a hope;
* every frame begins by asking whether the context is still there;
* :meth:`ThreeDRenderer.upload` is the only place that touches untrusted-derived
  bytes, and by then they have been through the validator and are tightly
  packed, in-range and finite;
* the CPU does one 4x4 per joint per frame and nothing per vertex.

The renderer holds no task, no store, no approval and no clock of its own: every
method that needs time takes it. That is not tidiness, it is what makes a
hundred consecutive lifecycles reproducible.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import time
from typing import Any, Mapping, Sequence

from companion.character.errors import RendererError
from companion.character.mapper import MappedCharacterState
from companion.character.renderer import CharacterRenderer, RenderedFrame
from companion.character.package import ValidatedPackage

from . import FULL_3D, LIGHTWEIGHT_3D
from .animation import CANDIDATES, AnimationStateMachine, Pose, blend_poses
from .context import ContextInfo, GraphicsContext
from .errors import RendererCapabilityError, RendererContextError
from .face import FaceController, FaceRig
from .glb import PrimitiveData, ValidatedModel
from .gpu import GpuResources
from .gl import (
    GL,
    GL_ARRAY_BUFFER,
    GL_BACK,
    GL_BLEND,
    GL_CCW,
    GL_CLAMP_TO_EDGE,
    GL_COLOR_ATTACHMENT0,
    GL_COLOR_BUFFER_BIT,
    GL_COMPILE_STATUS,
    GL_CULL_FACE,
    GL_DEPTH_ATTACHMENT,
    GL_DEPTH_BUFFER_BIT,
    GL_DEPTH_COMPONENT24,
    GL_DEPTH_TEST,
    GL_ELEMENT_ARRAY_BUFFER,
    GL_FALSE,
    GL_FLOAT,
    GL_FRAGMENT_SHADER,
    GL_FRAMEBUFFER,
    GL_FRAMEBUFFER_COMPLETE,
    GL_INFO_LOG_LENGTH,
    GL_LEQUAL,
    GL_LINEAR,
    GL_LINK_STATUS,
    GL_MIRRORED_REPEAT,
    GL_NEAREST,
    GL_ONE_MINUS_SRC_ALPHA,
    GL_PACK_ALIGNMENT,
    GL_RENDERBUFFER,
    GL_REPEAT,
    GL_RGB,
    GL_RGB32F,
    GL_RGBA,
    GL_RGBA8,
    GL_SRC_ALPHA,
    GL_STATIC_DRAW,
    GL_TEXTURE0,
    GL_TEXTURE1,
    GL_TEXTURE_2D,
    GL_TEXTURE_MAG_FILTER,
    GL_TEXTURE_MIN_FILTER,
    GL_TEXTURE_WRAP_S,
    GL_TEXTURE_WRAP_T,
    GL_TRIANGLES,
    GL_TRUE,
    GL_UNPACK_ALIGNMENT,
    GL_UNSIGNED_BYTE,
    GL_UNSIGNED_INT,
    GL_VERTEX_SHADER,
    load_gl,
)
from .procedural import ProceduralBehaviour
from .scene import DEFAULT_LIGHTING, LIGHTWEIGHT_LIGHTING, Lighting, PresentationCamera
from .shaders import ATTRIBUTE_LOCATIONS, MAX_ACTIVE_MORPHS, shader_sources
from .transform import Matrix4, compose, multiply, scale_matrix, translation_matrix

#: The two quality levels §21 defines, and what each one changes.
QUALITY_LEVELS: Mapping[str, dict[str, Any]] = {
    FULL_3D: {
        "targetFps": 60,
        "textureScale": 1.0,
        "facialUpdateDivisor": 1,
        "overlays": True,
        "idleBehaviour": True,
        "lighting": "two-light",
    },
    LIGHTWEIGHT_3D: {
        "targetFps": 30,
        "textureScale": 0.5,
        "facialUpdateDivisor": 2,
        "overlays": False,
        "idleBehaviour": False,
        "lighting": "one-light",
    },
}

#: Default vertex attribute values for a primitive that omits an attribute.
_ATTRIBUTE_DEFAULTS: Mapping[str, tuple[float, ...]] = {
    "NORMAL": (0.0, 1.0, 0.0),
    "TEXCOORD_0": (0.0, 0.0),
    "COLOR_0": (1.0, 1.0, 1.0, 1.0),
    "WEIGHTS_0": (0.0, 0.0, 0.0, 0.0),
}

_ATTRIBUTE_BINDINGS: tuple[tuple[str, str, int], ...] = (
    ("POSITION", "aPosition", 3),
    ("NORMAL", "aNormal", 3),
    ("TEXCOORD_0", "aTexCoord", 2),
    ("JOINTS_0", "aJoints", 4),
    ("WEIGHTS_0", "aWeights", 4),
    ("COLOR_0", "aColour", 4),
)

#: Morph-texture row width. Bounded by the driver's own limit at upload.
_MORPH_TEXTURE_WIDTH = 1024


@dataclass
class _UploadedPrimitive:
    """One primitive's GL objects and the draw state they imply."""

    source: PrimitiveData
    vertex_array: int
    buffers: tuple[int, ...]
    index_buffer: int
    index_count: int
    program: int
    uniforms: dict[str, int]
    base_texture: int | None
    morph_texture: int | None
    morph_components: int
    morph_texture_width: int
    blend: bool
    double_sided: bool
    skinned: bool
    bytes_uploaded: int


class ThreeDRenderer(CharacterRenderer):
    """Draw one validated humanoid. Presentation only; no task, no store."""

    renderer_name = FULL_3D

    def __init__(
        self,
        *,
        context: GraphicsContext,
        display_available: bool = True,
        quality: str = FULL_3D,
        motion: str = "full",
        seed: int | None = None,
    ) -> None:
        super().__init__(display_available=display_available)
        if quality not in QUALITY_LEVELS:
            raise ValueError(f"unknown 3D quality level: {quality}")
        self.context = context
        self.quality = quality
        self.renderer_name = quality
        self.motion = motion
        self.seed = seed
        self.gl: GL | None = None
        self.resources: GpuResources | None = None
        self.model: ValidatedModel | None = None
        self.uploaded: list[_UploadedPrimitive] = []
        self.animation: AnimationStateMachine | None = None
        self.face: FaceController | None = None
        self.behaviour: ProceduralBehaviour | None = None
        self.camera: PresentationCamera | None = None
        self.lighting: Lighting = DEFAULT_LIGHTING if quality == FULL_3D else LIGHTWEIGHT_LIGHTING
        self.context_info: ContextInfo | None = None
        #: Where the GLB came from, for the frame descriptor. Set by the loader.
        self.model_path: Any = None
        self.frames_drawn = 0
        self.frame_times_ms: list[float] = []
        self.first_frame_ms: float | None = None
        self.model_load_ms: float | None = None
        self.last_draw_at: float = 0.0
        self.background = (0.0, 0.0, 0.0, 0.0)
        self.floor_offset = 0.0
        self.native_scale = 1.0
        self.surface_size = (512, 512)
        self._joint_cache: list[float] = []
        self._frame_parity = 0
        self._offscreen: tuple[int, int, int, tuple[int, int]] | None = None
        self._pose = Pose()
        self._model_owner = "model"

    # -- lifecycle ---------------------------------------------------------

    def bind(self) -> GL:
        """Make the context current and cache the entry table. Raises if lost."""
        if self.context.lost:
            raise RendererContextError("the graphics context has been lost")
        gl = self.context.make_current()
        if self.gl is None:
            self.gl = gl
            self.resources = GpuResources(gl)
            self.context_info = self.context.info()
        return gl

    def load_package(self, package: ValidatedPackage) -> None:
        """Accept the 2D package body. The model arrives through :meth:`upload`.

        Overridden because the base class's memory estimate counts decoded
        raster frames, and a 3D package's raster assets are its *fallbacks* — a
        preview image and a static frame that are not resident while 3D draws.
        Counting them would report memory this renderer is not using.
        """
        if not isinstance(package, ValidatedPackage):
            raise TypeError("renderer accepts only a fully validated package")
        self.package = package
        self.running = True
        self.paused = False
        self.failure = None
        self.observed_memory_bytes = 0

    def upload(
        self,
        model: ValidatedModel,
        *,
        animation_map: Mapping[str, str],
        expression_map: Mapping[str, Mapping[str, float]] | None = None,
        viseme_map: Mapping[str, Mapping[str, float]] | None = None,
        native_scale: float = 1.0,
        floor_offset: float = 0.0,
        now: float | None = None,
    ) -> None:
        """Put a validated model on the GPU. The only untrusted-derived upload.

        A previous model is released *before* the new one is bound but *after*
        it has been fully described, which is §20's bounded overlap: the peak is
        two models' worth of description and one model's worth of GL objects.
        """
        started = time.monotonic()
        gl = self.bind()
        assert self.resources is not None
        if self.model is not None:
            self.resources.begin_replacement(previous_owner=self._model_owner, new_owner="model-incoming")
            self._release_model()

        capabilities = gl.capabilities()
        joint_count = len(model.joints)
        needed_components = joint_count * 16 + 64
        if needed_components > capabilities["maxVertexUniformComponents"]:
            raise RendererCapabilityError(
                f"the model needs {joint_count} joint matrices and this driver reports "
                f"{capabilities['maxVertexUniformComponents']} vertex uniform components"
            )
        self.model = model
        self.native_scale = float(native_scale) if native_scale > 0 else 1.0
        self.floor_offset = float(floor_offset)
        self.camera = PresentationCamera(model.bounds, aspect=self._aspect())
        rig = FaceRig(model, expression_map=expression_map, viseme_map=viseme_map)
        self.face = FaceController(rig, motion=self.motion)
        blink = rig.morph_index.get("blink")
        self.behaviour = ProceduralBehaviour(
            model.skeleton, seed=self.seed, motion=self.motion, blink_morph=blink
        )
        self.behaviour.reset(now=now if now is not None else time.monotonic())
        self.animation = AnimationStateMachine(model, animation_map, motion=self.motion)

        gl.glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        textures = self._upload_textures(gl, model, capabilities["maxTextureSize"])
        self.uploaded = [
            self._upload_primitive(gl, primitive, textures, joint_count, capabilities)
            for primitive in model.primitives
        ]
        self.observed_memory_bytes = sum(item.bytes_uploaded for item in self.uploaded)
        self.model_load_ms = (time.monotonic() - started) * 1000.0

    def _aspect(self) -> float:
        width, height = self.surface_size
        return max(0.2, min(8.0, width / max(1, height)))

    def _upload_textures(self, gl: GL, model: ValidatedModel, maximum: int) -> dict[int, int]:
        assert self.resources is not None
        result: dict[int, int] = {}
        for texture in model.textures:
            if texture.width > maximum or texture.height > maximum:
                raise RendererCapabilityError(
                    f"texture {texture.index} is {texture.width}x{texture.height} and the driver "
                    f"limit is {maximum}"
                )
            name = self.resources.textures(
                1, owner=self._model_owner, created_by="glGenTextures(base-colour)",
                estimated_bytes=texture.decoded_bytes,
            )[0]
            gl.glBindTexture(GL_TEXTURE_2D, name)
            payload = (ctypes.c_ubyte * len(texture.rgba)).from_buffer_copy(texture.rgba)
            gl.glTexImage2D(
                GL_TEXTURE_2D, 0, GL_RGBA8, texture.width, texture.height, 0,
                GL_RGBA, GL_UNSIGNED_BYTE, ctypes.cast(payload, ctypes.c_void_p),
            )
            gl.check("uploading a base-colour texture")
            wrap = {10497: GL_REPEAT, 33071: GL_CLAMP_TO_EDGE, 33648: GL_MIRRORED_REPEAT}
            gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, wrap.get(texture.wrap_s, GL_REPEAT))
            gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, wrap.get(texture.wrap_t, GL_REPEAT))
            # No mipmaps: the character occupies a fixed fraction of a small
            # surface, a mip chain costs a third more memory, and generating one
            # on llvmpipe is measurable. Linear minification is the honest
            # trade and is what the lightweight rung would pick anyway.
            gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
            gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            gl.glBindTexture(GL_TEXTURE_2D, 0)
            result[texture.index] = name
        return result

    def _compile(self, gl: GL, kind: int, source: str, label: str) -> int:
        shader = gl.glCreateShader(kind)
        if not shader:
            raise RendererContextError(f"glCreateShader failed for {label}")
        encoded = source.encode("utf-8")
        pointer = ctypes.c_char_p(encoded)
        length = ctypes.c_int(len(encoded))
        gl.glShaderSource(shader, 1, ctypes.byref(pointer), ctypes.byref(length))
        gl.glCompileShader(shader)
        status = ctypes.c_int(0)
        gl.glGetShaderiv(shader, GL_COMPILE_STATUS, ctypes.byref(status))
        if not status.value:
            log_length = ctypes.c_int(0)
            gl.glGetShaderiv(shader, GL_INFO_LOG_LENGTH, ctypes.byref(log_length))
            buffer = ctypes.create_string_buffer(max(1, min(4096, log_length.value)))
            gl.glGetShaderInfoLog(shader, len(buffer), None, buffer)
            gl.glDeleteShader(shader)
            raise RendererContextError(
                f"{label} shader failed to compile: {buffer.value.decode('utf-8', 'replace').strip()}"
            )
        return shader

    def _program(self, gl: GL, primitive: PrimitiveData, joints: int) -> tuple[int, dict[str, int]]:
        assert self.resources is not None
        vertex_source, fragment_source, _key = shader_sources(
            joints=max(1, joints),
            unlit=primitive.material.unlit,
            alpha_mode=primitive.material.alpha_mode,
            lightweight=self.quality == LIGHTWEIGHT_3D,
        )
        vertex = self._compile(gl, GL_VERTEX_SHADER, vertex_source, "vertex")
        try:
            fragment = self._compile(gl, GL_FRAGMENT_SHADER, fragment_source, "fragment")
        except RendererContextError:
            gl.glDeleteShader(vertex)
            raise
        program = gl.glCreateProgram()
        if not program:
            gl.glDeleteShader(vertex)
            gl.glDeleteShader(fragment)
            raise RendererContextError("glCreateProgram failed")
        gl.glAttachShader(program, vertex)
        gl.glAttachShader(program, fragment)
        for name, location in ATTRIBUTE_LOCATIONS.items():
            gl.glBindAttribLocation(program, location, name.encode("ascii"))
        gl.glLinkProgram(program)
        status = ctypes.c_int(0)
        gl.glGetProgramiv(program, GL_LINK_STATUS, ctypes.byref(status))
        gl.glDetachShader(program, vertex)
        gl.glDetachShader(program, fragment)
        gl.glDeleteShader(vertex)
        gl.glDeleteShader(fragment)
        if not status.value:
            log_length = ctypes.c_int(0)
            gl.glGetProgramiv(program, GL_INFO_LOG_LENGTH, ctypes.byref(log_length))
            buffer = ctypes.create_string_buffer(max(1, min(4096, log_length.value)))
            gl.glGetProgramInfoLog(program, len(buffer), None, buffer)
            gl.glDeleteProgram(program)
            raise RendererContextError(
                f"the character program failed to link: {buffer.value.decode('utf-8', 'replace').strip()}"
            )
        self.resources.program(program, owner=self._model_owner, created_by="glCreateProgram")
        uniforms = {
            name: gl.glGetUniformLocation(program, name.encode("ascii"))
            for name in (
                "uModel", "uView", "uProjection", "uSkinned", "uJoints",
                "uMorphTexture", "uMorphActive", "uMorphIndex", "uMorphWeight",
                "uMorphTexWidth", "uVertexCount", "uMorphHasNormals",
                "uBaseColour", "uMetallic", "uRoughness", "uEmissive",
                "uHasBaseTexture", "uBaseTexture", "uKeyDirection", "uKeyColour",
                "uKeyIntensity", "uFillDirection", "uFillColour", "uFillIntensity",
                "uAmbient", "uCameraPosition", "uAlphaCutoff", "uOpacity",
            )
        }
        return program, uniforms

    def _upload_primitive(
        self,
        gl: GL,
        primitive: PrimitiveData,
        textures: Mapping[int, int],
        joints: int,
        capabilities: Mapping[str, Any],
    ) -> _UploadedPrimitive:
        assert self.resources is not None
        program, uniforms = self._program(gl, primitive, joints)
        vertex_array = self.resources.vertex_arrays(
            1, owner=self._model_owner, created_by="glGenVertexArrays"
        )[0]
        gl.glBindVertexArray(vertex_array)
        buffers: list[int] = []
        uploaded_bytes = 0
        skinned = "JOINTS_0" in primitive.attributes and "WEIGHTS_0" in primitive.attributes

        for attribute, shader_name, default_components in _ATTRIBUTE_BINDINGS:
            location = ATTRIBUTE_LOCATIONS[shader_name]
            stream = primitive.attributes.get(attribute)
            # glTF permits ``COLOR_0`` as VEC3 or VEC4, and the binding table
            # can only name one. Take the stream's own component count when
            # there is a stream: OpenGL fills the missing components of a vec4
            # attribute with (0, 0, 0, 1), so a VEC3 colour arrives with alpha
            # 1 — which is what it means. Reading four components from a
            # three-component buffer would have read past the end of it.
            components = default_components if stream is None else stream.components
            if stream is None:
                default = _ATTRIBUTE_DEFAULTS.get(attribute)
                if attribute == "JOINTS_0":
                    payload = bytes(4 * primitive.vertex_count)
                    component_type, normalized, integer = GL_UNSIGNED_BYTE, GL_FALSE, False
                elif default is None:
                    continue
                else:
                    values = gl.floats(list(default) * primitive.vertex_count)
                    payload = bytes(memoryview(values).cast("B"))
                    component_type, normalized, integer = GL_FLOAT, GL_FALSE, False
            else:
                payload = stream.data
                component_type = {
                    5120: 0x1400, 5121: GL_UNSIGNED_BYTE, 5122: 0x1402,
                    5123: 0x1403, 5125: GL_UNSIGNED_INT, 5126: GL_FLOAT,
                }[stream.component_type]
                normalized = GL_TRUE if stream.normalized else GL_FALSE
                integer = False
            name = self.resources.buffers(
                1, kind="vertex-buffer", owner=self._model_owner,
                created_by=f"glGenBuffers({attribute})", estimated_bytes=len(payload),
            )[0]
            buffers.append(name)
            uploaded_bytes += len(payload)
            gl.glBindBuffer(GL_ARRAY_BUFFER, name)
            data = (ctypes.c_ubyte * len(payload)).from_buffer_copy(payload)
            gl.glBufferData(GL_ARRAY_BUFFER, len(payload), ctypes.cast(data, ctypes.c_void_p), GL_STATIC_DRAW)
            gl.check(f"uploading {attribute}")
            gl.glEnableVertexAttribArray(location)
            # JOINTS_0 reaches the shader as a float vec4 and is cast to int
            # there, so it is uploaded *unnormalised*: joint 5 must arrive as
            # 5.0, not as 5/255. Integer attributes would be tidier; float
            # indices are what every glTF viewer does and they avoid a second
            # attribute path for the one case where a driver disagrees about
            # ``glVertexAttribIPointer``.
            if attribute == "JOINTS_0":
                normalized = GL_FALSE
            gl.glVertexAttribPointer(
                location, components, component_type, normalized, 0, ctypes.c_void_p(0),
            )

        index_buffer = self.resources.buffers(
            1, kind="index-buffer", owner=self._model_owner, created_by="glGenBuffers(indices)",
            estimated_bytes=len(primitive.indices),
        )[0]
        gl.glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, index_buffer)
        index_payload = (ctypes.c_ubyte * len(primitive.indices)).from_buffer_copy(primitive.indices)
        gl.glBufferData(
            GL_ELEMENT_ARRAY_BUFFER, len(primitive.indices),
            ctypes.cast(index_payload, ctypes.c_void_p), GL_STATIC_DRAW,
        )
        gl.check("uploading indices")
        uploaded_bytes += len(primitive.indices)
        gl.glBindVertexArray(0)
        gl.glBindBuffer(GL_ARRAY_BUFFER, 0)
        gl.glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0)

        morph_texture: int | None = None
        morph_components = 0
        morph_width = _MORPH_TEXTURE_WIDTH
        if primitive.morph_targets:
            morph_components = 2 if any(target.normals for target in primitive.morph_targets) else 1
            texels = len(primitive.morph_targets) * morph_components * primitive.vertex_count
            morph_width = min(_MORPH_TEXTURE_WIDTH, int(capabilities["maxTextureSize"]))
            rows = (texels + morph_width - 1) // morph_width
            if rows > int(capabilities["maxTextureSize"]):
                raise RendererCapabilityError(
                    "the model's morph targets need a larger texture than this driver supports"
                )
            payload = bytearray(morph_width * rows * 12)
            for target in primitive.morph_targets:
                for component in range(morph_components):
                    source = target.positions if component == 0 else (target.normals or b"")
                    if not source:
                        continue
                    base = (target.index * morph_components + component) * primitive.vertex_count
                    payload[base * 12:base * 12 + len(source)] = source
            morph_texture = self.resources.textures(
                1, kind="morph-texture", owner=self._model_owner,
                created_by="glGenTextures(morph)", estimated_bytes=len(payload),
            )[0]
            gl.glBindTexture(GL_TEXTURE_2D, morph_texture)
            buffer = (ctypes.c_ubyte * len(payload)).from_buffer_copy(bytes(payload))
            gl.glTexImage2D(
                GL_TEXTURE_2D, 0, GL_RGB32F, morph_width, rows, 0,
                GL_RGB, GL_FLOAT, ctypes.cast(buffer, ctypes.c_void_p),
            )
            gl.check("uploading morph targets")
            gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
            gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
            gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
            gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
            gl.glBindTexture(GL_TEXTURE_2D, 0)
            uploaded_bytes += len(payload)

        base_texture = None
        if primitive.material.base_colour_texture is not None:
            base_texture = textures.get(primitive.material.base_colour_texture)

        return _UploadedPrimitive(
            source=primitive, vertex_array=vertex_array, buffers=tuple(buffers),
            index_buffer=index_buffer, index_count=primitive.index_count,
            program=program, uniforms=uniforms, base_texture=base_texture,
            morph_texture=morph_texture, morph_components=morph_components,
            morph_texture_width=morph_width,
            blend=primitive.material.alpha_mode == "BLEND",
            double_sided=primitive.material.double_sided, skinned=skinned,
            bytes_uploaded=uploaded_bytes,
        )

    def _release_model(self, *, context_lost: bool = False) -> int:
        if self.resources is None:
            return 0
        released = self.resources.release(owner=self._model_owner, context_lost=context_lost)
        self.uploaded = []
        self.model = None
        self.animation = None
        self.face = None
        self.behaviour = None
        self.camera = None
        self.observed_memory_bytes = 0
        return released

    def unload_package(self) -> None:
        self.release(context_lost=self.context.lost)
        super().unload_package()

    def release(self, *, context_lost: bool = False) -> dict[str, int]:
        """Release every GPU object. §20's shutdown requirement. Never raises."""
        released = 0
        if self.resources is not None:
            try:
                if not context_lost and not self.context.lost:
                    self.context.make_current()
            except Exception:  # noqa: BLE001 - releasing must not raise
                context_lost = True
            released = self.resources.release(context_lost=context_lost or self.context.lost)
        self.uploaded = []
        self.model = None
        self.animation = None
        self.face = None
        self.behaviour = None
        self.camera = None
        self._offscreen = None
        self.observed_memory_bytes = 0
        self.running = False
        return {"released": released}

    # -- state -------------------------------------------------------------

    def set_surface_size(self, width: int, height: int) -> None:
        self.surface_size = (max(1, int(width)), max(1, int(height)))
        if self.camera is not None:
            self.camera.set_aspect(self._aspect())

    def set_quality(self, quality: str) -> None:
        if quality not in QUALITY_LEVELS:
            raise ValueError(f"unknown 3D quality level: {quality}")
        self.quality = quality
        self.renderer_name = quality
        self.lighting = DEFAULT_LIGHTING if quality == FULL_3D else LIGHTWEIGHT_LIGHTING
        cap = QUALITY_LEVELS[quality]["targetFps"]
        self.frame_rate_cap = min(self.frame_rate_cap, int(cap)) or int(cap)

    def set_reduced_motion(self, enabled: bool) -> None:
        super().set_reduced_motion(enabled)
        motion = "reduced" if enabled else "full"
        if self.motion != "none":
            self.motion = motion
        if self.animation is not None:
            self.animation.motion = self.motion
        if self.face is not None:
            self.face.motion = self.motion
        if self.behaviour is not None:
            self.behaviour.motion = self.motion

    def set_no_animation(self, enabled: bool) -> None:
        self.motion = "none" if enabled else ("reduced" if self.reduced_motion else "full")
        if self.animation is not None:
            self.animation.motion = self.motion
        if self.face is not None:
            self.face.motion = self.motion
        if self.behaviour is not None:
            self.behaviour.motion = self.motion

    def set_mouth_shape(self, shape: str) -> None:
        """Apply one already-admitted mouth shape. §12: no timeline is built here."""
        super().set_mouth_shape(shape)
        if self.face is not None:
            self.face.set_mouth_shape(shape)

    def set_expression(self, expression: str) -> None:
        super().set_expression(expression)
        if self.face is not None:
            self.face.set_expression(expression)

    def display_state(self, state: MappedCharacterState, *, now_ms: int = 0) -> RenderedFrame | None:
        """Take a mapped canonical state and plan the animation for it."""
        self.mapped_state = state
        now = now_ms / 1000.0
        if self.animation is None or self.model is None:
            raise RendererError("the 3D renderer has no model uploaded")
        self.animation.request(state.character_state, now=now)
        if self.face is not None:
            self.face.set_expression_for_state(state.character_state.value)
            self.expression = self.face.expression
        if self.behaviour is not None:
            self.behaviour.attention_for_state(
                state.character_state.value, bubble_visible=state.bubble_visible
            )
        if QUALITY_LEVELS[self.quality]["overlays"] and self.animation is not None:
            overlay = "listening" if state.character_state.value in {"listening", "transcribing"} else None
            self.animation.set_upper_body_overlay(overlay, now=now)
        if not self.display_available:
            self.frame = None
            return None
        return self.draw(now_ms=now_ms)

    def play_animation(self, name: str, *, now_ms: int = 0) -> RenderedFrame | None:
        """Play one animation state by name. Used by diagnostics, not by the mapper."""
        if self.animation is None:
            raise RendererError("the 3D renderer has no model uploaded")
        from companion.character.mapper import CharacterState

        for state, candidates in CANDIDATES.items():
            if candidates and candidates[0] == name:
                self.animation.request(state, now=now_ms / 1000.0)
                break
        else:
            self.animation.request(CharacterState.IDLE, now=now_ms / 1000.0)
        return self.draw(now_ms=now_ms) if self.display_available else None

    def stop_animation(self, *, now_ms: int = 0) -> RenderedFrame | None:
        from companion.character.mapper import CharacterState

        if self.animation is None:
            raise RendererError("the 3D renderer has no model uploaded")
        self.animation.current = None
        self.animation.request(CharacterState.IDLE, now=now_ms / 1000.0)
        return self.draw(now_ms=now_ms) if self.display_available else None

    # -- drawing -----------------------------------------------------------

    def pose_for(self, now: float) -> Pose:
        """One frame's blended pose: base, overlay, face and procedural life."""
        assert self.animation is not None
        pose = self.animation.evaluate(now)
        result = Pose(
            dict(pose.translations), dict(pose.rotations), dict(pose.scales), dict(pose.weights)
        )
        if self.behaviour is not None and QUALITY_LEVELS[self.quality]["idleBehaviour"]:
            self.behaviour.advance(now)
            blend_poses(result, self.behaviour.pose(now), 0.85, into=result)
        elif self.behaviour is not None:
            # The lightweight rung keeps the blink and drops the rest: a face
            # that never blinks reads as frozen, and a blink costs one morph
            # weight per frame.
            self.behaviour.advance(now)
            blink = self.behaviour.pose(now)
            trimmed = Pose({}, {}, {}, dict(blink.weights))
            blend_poses(result, trimmed, 1.0, into=result)
        if self.face is not None:
            divisor = int(QUALITY_LEVELS[self.quality]["facialUpdateDivisor"])
            if divisor <= 1 or self.frames_drawn % divisor == 0:
                self.face.advance(now)
            blend_poses(result, self.face.pose(), 1.0, into=result)
        return result

    def joint_matrices(self, pose: Pose) -> list[float]:
        """One 4x4 per joint. The whole of this renderer's per-frame CPU work."""
        model = self.model
        assert model is not None
        world: dict[int, Matrix4] = {}
        order: list[int] = []
        stack = list(model.root_nodes)
        while stack:
            index = stack.pop()
            order.append(index)
            stack.extend(model.nodes[index].children)
        for index in order:
            node = model.nodes[index]
            translation = pose.translations.get(index, node.translation)
            rotation = pose.rotations.get(index, node.rotation)
            scale = pose.scales.get(index, node.scale)
            local = compose(translation, rotation, scale)
            parent = node.parent
            world[index] = local if parent is None else multiply(world[parent], local)
        flattened: list[float] = []
        for position, joint in enumerate(model.joints):
            flattened.extend(multiply(world[joint], model.inverse_bind_matrices[position]))
        return flattened

    def _model_matrix(self) -> Matrix4:
        scale = scale_matrix(self.native_scale)
        offset = translation_matrix((0.0, self.floor_offset, 0.0))
        return multiply(offset, scale)

    def draw(self, *, now_ms: int = 0, clear: bool = True) -> RenderedFrame | None:
        """Draw one frame. A context fault raises; the presenter degrades."""
        if not self.display_available:
            return None
        started = time.monotonic()
        gl = self.bind()
        model = self.model
        if model is None or self.animation is None or self.camera is None:
            raise RendererError("the 3D renderer has no model uploaded")
        now = now_ms / 1000.0
        pose = self.pose_for(now)
        joints = self.joint_matrices(pose)
        self._joint_cache = joints
        camera = self.camera.state(scale=self.scale)
        view = camera.view()
        projection = camera.projection()
        model_matrix = self._model_matrix()

        width, height = self.surface_size
        gl.glViewport(0, 0, width, height)
        if clear:
            gl.glClearColor(*self.background)
            gl.glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        gl.glEnable(GL_DEPTH_TEST)
        gl.glDepthFunc(GL_LEQUAL)
        gl.glFrontFace(GL_CCW)

        active = self._active_morphs(pose)
        for item in self.uploaded:
            self._draw_primitive(gl, item, model_matrix, view, projection, camera, joints, active)

        gl.glBindVertexArray(0)
        gl.glUseProgram(0)
        gl.glDisable(GL_BLEND)
        elapsed = (time.monotonic() - started) * 1000.0
        self.last_frame_ms = elapsed
        self.frame_times_ms.append(elapsed)
        if len(self.frame_times_ms) > 600:
            del self.frame_times_ms[:-600]
        if self.first_frame_ms is None:
            self.first_frame_ms = elapsed
        # A dropped frame is one this renderer *could not have drawn in time* —
        # a draw that took longer than the frame budget. It is deliberately not
        # "a gap between two draw calls larger than the budget": that measures
        # how often the caller asked, and the caller may be a slice stepping a
        # synthetic clock in quarter-second jumps. The first version counted
        # exactly that and reported 553 dropped frames in a run where every
        # frame took 1.1 ms, which is a number that says nothing about the
        # renderer and would have gone into a report as though it did.
        budget = 1000.0 / max(1, self.frame_rate_cap)
        if self.frames_drawn and elapsed > budget:
            self.dropped_frames += 1
        self.last_draw_at = now_ms
        self.frames_drawn += 1
        self.frame = self._describe_frame()
        return self.frame

    def _active_morphs(self, pose: Pose) -> list[tuple[int, float]]:
        if not pose.weights:
            return []
        ordered = sorted(
            ((index, weight) for index, weight in pose.weights.items() if abs(weight) > 1e-3),
            key=lambda item: -abs(item[1]),
        )
        return ordered[:MAX_ACTIVE_MORPHS]

    def _draw_primitive(
        self,
        gl: GL,
        item: _UploadedPrimitive,
        model_matrix: Matrix4,
        view: Matrix4,
        projection: Matrix4,
        camera: Any,
        joints: Sequence[float],
        active: Sequence[tuple[int, float]],
    ) -> None:
        uniforms = item.uniforms
        gl.glUseProgram(item.program)
        gl.glBindVertexArray(item.vertex_array)
        if item.double_sided:
            gl.glDisable(GL_CULL_FACE)
        else:
            gl.glEnable(GL_CULL_FACE)
            gl.glCullFace(GL_BACK)
        if item.blend:
            gl.glEnable(GL_BLEND)
            gl.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        else:
            gl.glDisable(GL_BLEND)

        gl.glUniformMatrix4fv(uniforms["uModel"], 1, GL_FALSE, gl.floats(model_matrix))
        gl.glUniformMatrix4fv(uniforms["uView"], 1, GL_FALSE, gl.floats(view))
        gl.glUniformMatrix4fv(uniforms["uProjection"], 1, GL_FALSE, gl.floats(projection))
        gl.glUniform1i(uniforms["uSkinned"], 1 if item.skinned else 0)
        if item.skinned and joints:
            gl.glUniformMatrix4fv(uniforms["uJoints"], len(joints) // 16, GL_FALSE, gl.floats(joints))

        morph_indices = [index for index, _weight in active]
        morph_weights = [weight for _index, weight in active]
        count = len(morph_indices) if item.morph_texture is not None else 0
        gl.glUniform1i(uniforms["uMorphActive"], count)
        if count:
            padded_indices = morph_indices + [0] * (MAX_ACTIVE_MORPHS - count)
            padded_weights = morph_weights + [0.0] * (MAX_ACTIVE_MORPHS - count)
            gl.glUniform1iv(uniforms["uMorphIndex"], MAX_ACTIVE_MORPHS, gl.ints(padded_indices))
            gl.glUniform1fv(uniforms["uMorphWeight"], MAX_ACTIVE_MORPHS, gl.floats(padded_weights))
            gl.glUniform1i(uniforms["uMorphTexWidth"], item.morph_texture_width)
            gl.glUniform1i(uniforms["uVertexCount"], item.source.vertex_count)
            gl.glUniform1i(uniforms["uMorphHasNormals"], 1 if item.morph_components == 2 else 0)
            gl.glActiveTexture(GL_TEXTURE1)
            gl.glBindTexture(GL_TEXTURE_2D, item.morph_texture)
            gl.glUniform1i(uniforms["uMorphTexture"], 1)

        material = item.source.material
        gl.glUniform4fv(uniforms["uBaseColour"], 1, gl.floats(material.base_colour))
        gl.glUniform1f(uniforms["uMetallic"], material.metallic)
        gl.glUniform1f(uniforms["uRoughness"], material.roughness)
        gl.glUniform3fv(uniforms["uEmissive"], 1, gl.floats(material.emissive))
        gl.glUniform1f(uniforms["uAlphaCutoff"], material.alpha_cutoff)
        gl.glUniform1f(uniforms["uOpacity"], self.opacity)
        gl.glUniform3fv(uniforms["uKeyDirection"], 1, gl.floats(self.lighting.key.direction))
        gl.glUniform3fv(uniforms["uKeyColour"], 1, gl.floats(self.lighting.key.colour))
        gl.glUniform1f(uniforms["uKeyIntensity"], self.lighting.key.intensity)
        gl.glUniform3fv(uniforms["uFillDirection"], 1, gl.floats(self.lighting.fill.direction))
        gl.glUniform3fv(uniforms["uFillColour"], 1, gl.floats(self.lighting.fill.colour))
        gl.glUniform1f(uniforms["uFillIntensity"], self.lighting.fill.intensity)
        gl.glUniform3fv(uniforms["uAmbient"], 1, gl.floats(self.lighting.ambient))
        gl.glUniform3fv(uniforms["uCameraPosition"], 1, gl.floats(camera.position))

        if item.base_texture is not None:
            gl.glActiveTexture(GL_TEXTURE0)
            gl.glBindTexture(GL_TEXTURE_2D, item.base_texture)
            gl.glUniform1i(uniforms["uBaseTexture"], 0)
            gl.glUniform1i(uniforms["uHasBaseTexture"], 1)
        else:
            gl.glUniform1i(uniforms["uHasBaseTexture"], 0)

        gl.glDrawElements(GL_TRIANGLES, item.index_count, GL_UNSIGNED_INT, ctypes.c_void_p(0))

    def _describe_frame(self) -> RenderedFrame:
        package = self.package
        model = self.model
        state = self.mapped_state.character_state.value if self.mapped_state else "idle"
        animation = self.animation.status(self.last_draw_at / 1000.0) if self.animation else {}
        asset_id = f"model:{model.digest[:16]}" if model else "model:none"
        from pathlib import Path

        return RenderedFrame(
            asset_id=asset_id,
            asset_path=Path(getattr(self, "model_path", "") or asset_id),
            width=self.surface_size[0],
            height=self.surface_size[1],
            state=state,
            animation=str(animation.get("clip") or "idle"),
            frame_index=self.frames_drawn,
            opacity=self.opacity,
            scale=self.scale,
            mouth_shape=self.mouth_shape,
            accessibility_description=self.accessibility_description(),
        )

    # -- offscreen ---------------------------------------------------------

    def begin_offscreen(self, width: int, height: int) -> None:
        """Attach a framebuffer so a frame can be drawn and read back.

        This is what makes §32's and §34's assertions about *pixels* possible on
        a machine with no compositor, and it is the same draw path a window
        uses: only the framebuffer differs.
        """
        gl = self.bind()
        assert self.resources is not None
        if self._offscreen is not None:
            self.end_offscreen()
        width, height = max(1, int(width)), max(1, int(height))
        framebuffer = self.resources.framebuffers(
            1, owner="offscreen", created_by="glGenFramebuffers"
        )[0]
        colour = self.resources.textures(
            1, owner="offscreen", created_by="glGenTextures(offscreen-colour)",
            estimated_bytes=width * height * 4,
        )[0]
        depth = self.resources.renderbuffers(
            1, owner="offscreen", created_by="glGenRenderbuffers",
            estimated_bytes=width * height * 4,
        )[0]
        gl.glBindTexture(GL_TEXTURE_2D, colour)
        gl.glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, width, height, 0, GL_RGBA, GL_UNSIGNED_BYTE, None)
        gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        gl.glBindTexture(GL_TEXTURE_2D, 0)
        gl.glBindRenderbuffer(GL_RENDERBUFFER, depth)
        gl.glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, width, height)
        gl.glBindRenderbuffer(GL_RENDERBUFFER, 0)
        gl.glBindFramebuffer(GL_FRAMEBUFFER, framebuffer)
        gl.glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, colour, 0)
        gl.glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, depth)
        status = gl.glCheckFramebufferStatus(GL_FRAMEBUFFER)
        if status != GL_FRAMEBUFFER_COMPLETE:
            self.resources.release(owner="offscreen")
            raise RendererContextError(f"offscreen framebuffer is incomplete (0x{status:04x})")
        gl.check("creating the offscreen framebuffer")
        self._offscreen = (framebuffer, colour, depth, (width, height))
        self.set_surface_size(width, height)

    def read_pixels(self) -> tuple[int, int, bytes]:
        """Read the offscreen colour buffer back. Bounded by its own size."""
        if self._offscreen is None:
            raise RendererError("no offscreen framebuffer is attached")
        gl = self.bind()
        _framebuffer, _colour, _depth, (width, height) = self._offscreen
        gl.glPixelStorei(GL_PACK_ALIGNMENT, 1)
        buffer = (ctypes.c_ubyte * (width * height * 4))()
        gl.glReadPixels(0, 0, width, height, GL_RGBA, GL_UNSIGNED_BYTE, ctypes.cast(buffer, ctypes.c_void_p))
        gl.check("reading the offscreen framebuffer")
        return width, height, bytes(buffer)

    def end_offscreen(self) -> None:
        if self._offscreen is None:
            return
        try:
            gl = self.bind()
            gl.glBindFramebuffer(GL_FRAMEBUFFER, 0)
        except Exception:  # noqa: BLE001 - teardown must not raise
            pass
        if self.resources is not None:
            self.resources.release(owner="offscreen", context_lost=self.context.lost)
        self._offscreen = None

    # -- reporting ---------------------------------------------------------

    def frame_statistics(self) -> dict[str, Any]:
        samples = sorted(self.frame_times_ms)
        if not samples:
            return {
                "frames": 0, "lastMs": 0.0, "meanMs": None, "p95Ms": None,
                "maxMs": None, "droppedFrames": self.dropped_frames,
                "firstFrameMs": self.first_frame_ms,
            }
        index = max(0, min(len(samples) - 1, int(round(0.95 * (len(samples) - 1)))))
        return {
            "frames": self.frames_drawn,
            "lastMs": round(self.last_frame_ms, 4),
            "meanMs": round(sum(samples) / len(samples), 4),
            "p95Ms": round(samples[index], 4),
            "maxMs": round(samples[-1], 4),
            "droppedFrames": self.dropped_frames,
            "firstFrameMs": None if self.first_frame_ms is None else round(self.first_frame_ms, 4),
        }

    def describe(self) -> dict[str, Any]:
        now = self.last_draw_at / 1000.0
        return {
            "renderer": self.renderer_name,
            "quality": self.quality,
            "qualityPolicy": dict(QUALITY_LEVELS[self.quality]),
            "motion": self.motion,
            "surface": {"width": self.surface_size[0], "height": self.surface_size[1]},
            "context": self.context_info.to_json() if self.context_info else None,
            "contextLost": self.context.lost,
            "model": self.model.to_json() if self.model else None,
            "modelLoadMs": None if self.model_load_ms is None else round(self.model_load_ms, 4),
            "resources": self.resources.to_json() if self.resources else None,
            "animation": self.animation.status(now) if self.animation else None,
            "face": self.face.status() if self.face else None,
            "behaviour": self.behaviour.status(now) if self.behaviour else None,
            "camera": self.camera.state(scale=self.scale).to_json() if self.camera else None,
            "lighting": self.lighting.to_json(),
            "frames": self.frame_statistics(),
            "offscreen": self._offscreen is not None,
        }


__all__ = ["QUALITY_LEVELS", "ThreeDRenderer"]
