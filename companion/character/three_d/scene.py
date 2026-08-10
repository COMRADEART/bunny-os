# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The presentation camera and the three lights, both renderer-owned.

§17 and §18 are one module because they share a property that is the whole
point of both: **nothing outside this file supplies either of them.** A camera
mode is chosen from the presentation layout the projection already produced; a
light is a constant. No provider, no agent, no character package and no manifest
may hand this renderer a matrix, a position or a colour, and the GLB validator
refuses a document that carries a camera at all so that the intent is checked
rather than merely unimplemented.

The reason is not aesthetic. A camera matrix is a completely general affine
transform: given one, an untrusted party can put the near plane inside the
character's head, scale a single triangle across the entire surface, or place
the character somewhere the user did not agree to have a window. A companion
that took its camera from a model file would have handed the shape of its own
window to whoever wrote the model.

The lighting is deliberately cheap and deliberately fixed. One key, one fill,
one ambient term, all evaluated per fragment in the renderer's own shader, on a
software rasteriser as often as not. There is no environment map, no image-based
lighting and nothing to download — §18 says so, and a character that looked
right only after fetching an HDR would be a character that looked wrong on a
machine with no network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .glb import ModelBounds
from .transform import Matrix4, Vector3, look_at, perspective

#: §17's four modes. The value is what a report prints; the tuple beside it in
#: :data:`CAMERA_FRAMINGS` is what the camera does.
CAMERA_MODES: tuple[str, ...] = ("full-body", "waist-up", "compact", "close-speaking")

#: Bounds §17 asks for, applied to every mode and to every computed value.
FOV_RANGE = (18.0, 55.0)
DISTANCE_RANGE = (0.35, 12.0)
NEAR_RANGE = (0.01, 1.0)
FAR_RANGE = (2.0, 100.0)
PITCH_RANGE = (-0.35, 0.35)

#: Per mode: (vertical field of view, how much of the model's height is framed,
#: where in that height the camera looks, pitch in radians).
#:
#: Framing is expressed as a *fraction of the character's own height* rather
#: than a distance in metres, which is what makes the camera work for a 1.7 m
#: humanoid and a 0.9 m stylised one without a per-package setting.
CAMERA_FRAMINGS: Mapping[str, tuple[float, float, float, float]] = {
    "full-body": (32.0, 1.15, 0.52, -0.02),
    "waist-up": (30.0, 0.62, 0.74, 0.0),
    "compact": (34.0, 0.46, 0.82, 0.02),
    "close-speaking": (26.0, 0.30, 0.88, 0.03),
}

#: Placement -> camera mode. The placement comes from
#: :func:`companion.presentation.placement_for_phase`, so the camera follows the
#: canonical layout decision rather than making a second one.
PLACEMENT_CAMERAS: Mapping[str, str] = {
    "center": "full-body",
    "docked": "waist-up",
    "compact": "compact",
    "task-panel": "waist-up",
    "speech-bubble": "close-speaking",
}


@dataclass(frozen=True)
class CameraState:
    """One fully-bounded camera. Every field has been clamped before it exists."""

    mode: str
    fov_degrees: float
    position: Vector3
    target: Vector3
    near: float
    far: float
    aspect: float
    pitch: float

    def view(self) -> Matrix4:
        return look_at(self.position, self.target)

    def projection(self) -> Matrix4:
        return perspective(self.fov_degrees, self.aspect, self.near, self.far)

    def to_json(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "fovDegrees": round(self.fov_degrees, 3),
            "position": [round(value, 5) for value in self.position],
            "target": [round(value, 5) for value in self.target],
            "near": self.near,
            "far": self.far,
            "aspect": round(self.aspect, 5),
            "pitch": round(self.pitch, 5),
        }


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, float(value)))


class PresentationCamera:
    """Deterministic framing from a placement and a model's own bounds.

    Deterministic in the strong sense: the same bounds, mode and aspect always
    produce the same matrices, with no clock, no easing and no state carried
    between frames. That is what lets §33's slice assert the camera changed
    when the layout changed, and lets a screenshot be compared with another.
    """

    def __init__(self, bounds: ModelBounds, *, aspect: float = 1.0) -> None:
        self.bounds = bounds
        self.aspect = _clamp(aspect, 0.2, 8.0)
        self.mode = "full-body"

    def set_aspect(self, aspect: float) -> None:
        self.aspect = _clamp(aspect, 0.2, 8.0)

    def set_mode(self, mode: str) -> str:
        self.mode = mode if mode in CAMERA_FRAMINGS else "full-body"
        return self.mode

    def mode_for_placement(self, placement: str) -> str:
        return self.set_mode(PLACEMENT_CAMERAS.get(str(placement), "full-body"))

    def state(self, *, scale: float = 1.0) -> CameraState:
        import math

        fov, framed_fraction, look_fraction, pitch = CAMERA_FRAMINGS[self.mode]
        fov = _clamp(fov, *FOV_RANGE)
        pitch = _clamp(pitch, *PITCH_RANGE)
        height = max(1e-3, self.bounds.height)
        centre_x = (self.bounds.minimum[0] + self.bounds.maximum[0]) * 0.5
        centre_z = (self.bounds.minimum[2] + self.bounds.maximum[2]) * 0.5
        floor = self.bounds.minimum[1]
        framed = max(1e-3, height * framed_fraction)
        # How far back the camera must sit for ``framed`` to fill the view.
        distance = _clamp(
            (framed * 0.5) / math.tan(math.radians(fov) * 0.5) / max(0.35, scale),
            *DISTANCE_RANGE,
        )
        look_y = floor + height * look_fraction
        eye = (
            centre_x,
            look_y + distance * math.sin(pitch),
            centre_z + distance * math.cos(pitch),
        )
        near = _clamp(max(0.02, distance * 0.02), *NEAR_RANGE)
        far = _clamp(distance + height * 6.0, *FAR_RANGE)
        return CameraState(
            mode=self.mode, fov_degrees=fov, position=eye,
            target=(centre_x, look_y, centre_z), near=near, far=far,
            aspect=self.aspect, pitch=pitch,
        )


@dataclass(frozen=True)
class Light:
    direction: Vector3
    colour: Vector3
    intensity: float

    def to_json(self) -> dict[str, Any]:
        return {
            "direction": list(self.direction),
            "colour": list(self.colour),
            "intensity": self.intensity,
        }


@dataclass(frozen=True)
class Lighting:
    """§18's three terms. Constants, and there is no path that changes them."""

    key: Light = Light((-0.45, -0.72, -0.52), (1.0, 0.97, 0.92), 1.05)
    fill: Light = Light((0.62, -0.20, 0.75), (0.80, 0.86, 1.0), 0.42)
    ambient: Vector3 = (0.30, 0.31, 0.34)
    exposure: float = 1.0

    def to_json(self) -> dict[str, Any]:
        return {
            "key": self.key.to_json(),
            "fill": self.fill.to_json(),
            "ambient": list(self.ambient),
            "exposure": self.exposure,
            "environmentMap": None,
            "packageSuppliedLights": False,
        }


#: The one lighting rig. Named so a report can say which was used and a future
#: phase can add a second without a package being able to select it.
DEFAULT_LIGHTING = Lighting()

#: A cheaper variant for the lightweight rung: the fill is folded into ambient
#: so the fragment shader evaluates one light instead of two.
LIGHTWEIGHT_LIGHTING = Lighting(
    key=Light((-0.45, -0.72, -0.52), (1.0, 0.97, 0.92), 1.15),
    fill=Light((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), 0.0),
    ambient=(0.38, 0.39, 0.42),
)


__all__ = [
    "CAMERA_FRAMINGS",
    "CAMERA_MODES",
    "CameraState",
    "DEFAULT_LIGHTING",
    "DISTANCE_RANGE",
    "FOV_RANGE",
    "LIGHTWEIGHT_LIGHTING",
    "Light",
    "Lighting",
    "PLACEMENT_CAMERAS",
    "PresentationCamera",
]
