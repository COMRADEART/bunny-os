# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Column-major 4x4 matrix arithmetic, in pure Python.

No NumPy. That is a deliberate packaging decision rather than an oversight: the
Bunny OS image ships ``gtk4``, ``python3-gobject`` and Mesa, and adding NumPy to
it to multiply a hundred small matrices would put a 30 MB scientific stack into
a desktop image for arithmetic that costs about a millisecond a frame.

The per-frame cost is bounded and known, because the *only* thing computed on
the CPU is one 4x4 per joint. Skinning, morphing and lighting all happen in the
vertex and fragment shaders, where the per-vertex work belongs. A 96-joint
skeleton is 96 matrix composes and 96 multiplies per frame; §35 measures what
that actually costs rather than assuming it.

Layout is column-major, sixteen floats, the same order glTF and OpenGL both use,
so a matrix goes to ``glUniformMatrix4fv`` with ``transpose=GL_FALSE`` and no
repacking anywhere.
"""

from __future__ import annotations

import math
from typing import Sequence

Matrix4 = tuple[float, ...]
Vector3 = tuple[float, float, float]
Quaternion = tuple[float, float, float, float]

IDENTITY: Matrix4 = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)


def multiply(a: Sequence[float], b: Sequence[float]) -> Matrix4:
    """``a * b`` for column-major matrices: apply ``b`` first, then ``a``."""
    result = [0.0] * 16
    for column in range(4):
        c0 = b[column * 4]
        c1 = b[column * 4 + 1]
        c2 = b[column * 4 + 2]
        c3 = b[column * 4 + 3]
        for row in range(4):
            result[column * 4 + row] = (
                a[row] * c0 + a[4 + row] * c1 + a[8 + row] * c2 + a[12 + row] * c3
            )
    return tuple(result)


def compose(translation: Vector3, rotation: Quaternion, scale: Vector3) -> Matrix4:
    """TRS in glTF's order: scale, then rotate, then translate."""
    x, y, z, w = rotation
    x2, y2, z2 = x + x, y + y, z + z
    xx, xy, xz = x * x2, x * y2, x * z2
    yy, yz, zz = y * y2, y * z2, z * z2
    wx, wy, wz = w * x2, w * y2, w * z2
    sx, sy, sz = scale
    return (
        (1.0 - (yy + zz)) * sx, (xy + wz) * sx, (xz - wy) * sx, 0.0,
        (xy - wz) * sy, (1.0 - (xx + zz)) * sy, (yz + wx) * sy, 0.0,
        (xz + wy) * sz, (yz - wx) * sz, (1.0 - (xx + yy)) * sz, 0.0,
        translation[0], translation[1], translation[2], 1.0,
    )


def translation_matrix(vector: Vector3) -> Matrix4:
    return (
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        vector[0], vector[1], vector[2], 1.0,
    )


def scale_matrix(factor: float) -> Matrix4:
    return (
        factor, 0.0, 0.0, 0.0,
        0.0, factor, 0.0, 0.0,
        0.0, 0.0, factor, 0.0,
        0.0, 0.0, 0.0, 1.0,
    )


def normalise(vector: Vector3) -> Vector3:
    length = math.sqrt(sum(component * component for component in vector))
    if length < 1e-9:
        return (0.0, 0.0, 0.0)
    return (vector[0] / length, vector[1] / length, vector[2] / length)


def cross(a: Vector3, b: Vector3) -> Vector3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def dot(a: Vector3, b: Vector3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def look_at(eye: Vector3, target: Vector3, up: Vector3 = (0.0, 1.0, 0.0)) -> Matrix4:
    """A right-handed view matrix. Degenerate inputs fall back to identity-ish."""
    forward = normalise((target[0] - eye[0], target[1] - eye[1], target[2] - eye[2]))
    if forward == (0.0, 0.0, 0.0):
        forward = (0.0, 0.0, -1.0)
    side = normalise(cross(forward, up))
    if side == (0.0, 0.0, 0.0):
        side = (1.0, 0.0, 0.0)
    true_up = cross(side, forward)
    return (
        side[0], true_up[0], -forward[0], 0.0,
        side[1], true_up[1], -forward[1], 0.0,
        side[2], true_up[2], -forward[2], 0.0,
        -dot(side, eye), -dot(true_up, eye), dot(forward, eye), 1.0,
    )


def perspective(fov_degrees: float, aspect: float, near: float, far: float) -> Matrix4:
    """A standard right-handed perspective projection with a -1..1 depth range."""
    if not 1.0 <= fov_degrees <= 120.0:
        raise ValueError("field of view must be between 1 and 120 degrees")
    if aspect <= 0 or near <= 0 or far <= near:
        raise ValueError("perspective near/far/aspect are invalid")
    focal = 1.0 / math.tan(math.radians(fov_degrees) * 0.5)
    depth = near - far
    return (
        focal / aspect, 0.0, 0.0, 0.0,
        0.0, focal, 0.0, 0.0,
        0.0, 0.0, (far + near) / depth, -1.0,
        0.0, 0.0, (2.0 * far * near) / depth, 0.0,
    )


def invert_rigid(matrix: Sequence[float]) -> Matrix4:
    """Inverse of a rotation+translation matrix (no scale). Used for normals.

    Restricted to rigid transforms on purpose: a general 4x4 inverse is 100
    lines of cofactor expansion that would run once per joint per frame, and the
    only matrices this renderer inverts are rigid ones.
    """
    rotation = (
        matrix[0], matrix[4], matrix[8],
        matrix[1], matrix[5], matrix[9],
        matrix[2], matrix[6], matrix[10],
    )
    tx, ty, tz = matrix[12], matrix[13], matrix[14]
    return (
        rotation[0], rotation[3], rotation[6], 0.0,
        rotation[1], rotation[4], rotation[7], 0.0,
        rotation[2], rotation[5], rotation[8], 0.0,
        -(rotation[0] * tx + rotation[1] * ty + rotation[2] * tz),
        -(rotation[3] * tx + rotation[4] * ty + rotation[5] * tz),
        -(rotation[6] * tx + rotation[7] * ty + rotation[8] * tz),
        1.0,
    )


def transform_point(matrix: Sequence[float], point: Vector3) -> Vector3:
    x, y, z = point
    return (
        matrix[0] * x + matrix[4] * y + matrix[8] * z + matrix[12],
        matrix[1] * x + matrix[5] * y + matrix[9] * z + matrix[13],
        matrix[2] * x + matrix[6] * y + matrix[10] * z + matrix[14],
    )


__all__ = [
    "IDENTITY",
    "Matrix4",
    "Quaternion",
    "Vector3",
    "compose",
    "cross",
    "dot",
    "invert_rigid",
    "look_at",
    "multiply",
    "normalise",
    "perspective",
    "scale_matrix",
    "transform_point",
    "translation_matrix",
]
