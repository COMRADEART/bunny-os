#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate the repository's own 3D companion: geometry, rig, morphs, clips.

A development tool, not shipped: ``install-root.py`` copies named scripts and
this is not one of them. What it produces — ``bunny-3d.glb`` and its textures —
*is* shipped, inside ``assets/companion/characters/default-bunny-3d/``.

Why a generator rather than a checked-in export from a DCC tool:

**Provenance.** §26 asks, for every bundled asset, who made it, from what, under
what licence, and whether it was generated or hand-created. For a binary export
those answers are a paragraph somebody wrote. Here they are this file: every
vertex, weight, keyframe and pixel in the package is a consequence of code in
the repository, under the repository's licence, derived from nothing. There is
no imported mesh, no scanned photograph, no commercial asset and no model from a
game — §26's prohibition is satisfied structurally rather than by assertion.

**Reproducibility.** The output is byte-deterministic: no clock, no randomness,
no dictionary-order dependence, floats written through ``struct`` rather than
formatted. Re-running this script on any machine produces a GLB with the same
SHA-256, which is what lets the package manifest carry that digest and the
validator check it.

**Honesty about what it is.** This is a *reference* character: a stylised
human-shaped figure of a few thousand triangles, rigged to the Bunny humanoid
profile, with the eleven face morphs the viseme and expression maps need and one
clip per canonical animation state. §25 asks for exactly that and explicitly
does not ask for production art. The phase report's "remaining production-art
work" section says what a real character would add.

Usage::

    scripts/build_default_character_3d.py --output assets/companion/characters/default-bunny-3d
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
import zlib
from typing import Any, Iterable, Sequence

# --------------------------------------------------------------------------- #
# The skeleton
# --------------------------------------------------------------------------- #

#: Bind-pose world positions, in metres, Y up, facing +Z. A 1.66 m figure in a
#: T-pose, which is the pose every skinning tool and every reader expects.
BIND: dict[str, tuple[float, float, float]] = {
    "root": (0.0, 0.0, 0.0),
    "hips": (0.0, 0.92, 0.0),
    "spine": (0.0, 1.04, 0.0),
    "chest": (0.0, 1.20, 0.0),
    "neck": (0.0, 1.40, 0.0),
    "head": (0.0, 1.48, 0.0),
    "jaw": (0.0, 1.545, 0.02),
    "left_eye": (0.036, 1.575, 0.072),
    "right_eye": (-0.036, 1.575, 0.072),
    "left_shoulder": (0.055, 1.345, 0.0),
    "left_upper_arm": (0.165, 1.345, 0.0),
    "left_lower_arm": (0.425, 1.345, 0.0),
    "left_hand": (0.665, 1.345, 0.0),
    "right_shoulder": (-0.055, 1.345, 0.0),
    "right_upper_arm": (-0.165, 1.345, 0.0),
    "right_lower_arm": (-0.425, 1.345, 0.0),
    "right_hand": (-0.665, 1.345, 0.0),
    "left_upper_leg": (0.088, 0.885, 0.0),
    "left_lower_leg": (0.088, 0.485, 0.0),
    "left_foot": (0.088, 0.075, 0.0),
    "right_upper_leg": (-0.088, 0.885, 0.0),
    "right_lower_leg": (-0.088, 0.485, 0.0),
    "right_foot": (-0.088, 0.075, 0.0),
}

PARENT: dict[str, str | None] = {
    "root": None,
    "hips": "root",
    "spine": "hips",
    "chest": "spine",
    "neck": "chest",
    "head": "neck",
    "jaw": "head",
    "left_eye": "head",
    "right_eye": "head",
    "left_shoulder": "chest",
    "left_upper_arm": "left_shoulder",
    "left_lower_arm": "left_upper_arm",
    "left_hand": "left_lower_arm",
    "right_shoulder": "chest",
    "right_upper_arm": "right_shoulder",
    "right_lower_arm": "right_upper_arm",
    "right_hand": "right_lower_arm",
    "left_upper_leg": "hips",
    "left_lower_leg": "left_upper_leg",
    "left_foot": "left_lower_leg",
    "right_upper_leg": "hips",
    "right_lower_leg": "right_upper_leg",
    "right_foot": "right_lower_leg",
}

#: Node order. Parents before children, which every reader tolerates and some
#: assume; also the order the inverse-bind matrices are written in.
ORDER: tuple[str, ...] = (
    "root", "hips", "spine", "chest", "neck", "head", "jaw", "left_eye", "right_eye",
    "left_shoulder", "left_upper_arm", "left_lower_arm", "left_hand",
    "right_shoulder", "right_upper_arm", "right_lower_arm", "right_hand",
    "left_upper_leg", "left_lower_leg", "left_foot",
    "right_upper_leg", "right_lower_leg", "right_foot",
)

#: The eleven face morphs, in the order the manifest declares them.
MORPH_NAMES: tuple[str, ...] = (
    "mouth_open_small", "mouth_open_medium", "mouth_open_wide", "mouth_rounded",
    "mouth_smile", "brow_raise", "brow_lower", "smile", "frown", "eye_narrow",
    "cheek_puff",
)

HEAD_CENTRE = (0.0, 1.575, 0.0)
HEAD_RADIUS = 0.108
MOUTH_CENTRE = (0.0, 1.532, 0.082)
BROW_CENTRE = (0.0, 1.618, 0.078)


# --------------------------------------------------------------------------- #
# Small vector helpers
# --------------------------------------------------------------------------- #


def sub(a: Sequence[float], b: Sequence[float]) -> tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def length(a: Sequence[float]) -> float:
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def normalise(a: Sequence[float]) -> tuple[float, float, float]:
    size = length(a)
    if size < 1e-9:
        return (0.0, 1.0, 0.0)
    return (a[0] / size, a[1] / size, a[2] / size)


def falloff(distance: float, radius: float) -> float:
    """Smooth 1 -> 0 over ``radius``. Used to shape every morph region."""
    if distance >= radius:
        return 0.0
    t = 1.0 - distance / radius
    return t * t * (3.0 - 2.0 * t)


# --------------------------------------------------------------------------- #
# Geometry
# --------------------------------------------------------------------------- #


class MeshBuilder:
    """Accumulates positions, normals, uvs, joints, weights and triangles."""

    def __init__(self) -> None:
        self.positions: list[tuple[float, float, float]] = []
        self.normals: list[tuple[float, float, float]] = []
        self.uvs: list[tuple[float, float]] = []
        self.joints: list[tuple[int, int, int, int]] = []
        self.weights: list[tuple[float, float, float, float]] = []
        self.indices: list[int] = []

    def add(
        self,
        position: Sequence[float],
        normal: Sequence[float],
        uv: Sequence[float],
        bones: Sequence[tuple[int, float]],
    ) -> int:
        index = len(self.positions)
        self.positions.append((float(position[0]), float(position[1]), float(position[2])))
        self.normals.append(normalise(normal))
        self.uvs.append((float(uv[0]), float(uv[1])))
        ordered = sorted(bones, key=lambda item: -item[1])[:4]
        total = sum(weight for _bone, weight in ordered) or 1.0
        padded = [(bone, weight / total) for bone, weight in ordered]
        while len(padded) < 4:
            padded.append((0, 0.0))
        self.joints.append(tuple(bone for bone, _weight in padded))  # type: ignore[arg-type]
        self.weights.append(tuple(weight for _bone, weight in padded))  # type: ignore[arg-type]
        return index

    def triangle(self, a: int, b: int, c: int) -> None:
        self.indices.extend((a, b, c))

    def quad(self, a: int, b: int, c: int, d: int) -> None:
        self.triangle(a, b, c)
        self.triangle(a, c, d)

    @property
    def vertex_count(self) -> int:
        return len(self.positions)


def tube(
    builder: MeshBuilder,
    start: Sequence[float],
    end: Sequence[float],
    start_radius: float,
    end_radius: float,
    start_bone: int,
    end_bone: int,
    *,
    segments: int = 12,
    rings: int = 5,
    uv_base: float = 0.0,
    cap_start: bool = False,
    cap_end: bool = False,
) -> None:
    """A tapered tube between two joints, skinned across the pair.

    The weight blend is the ring's position along the segment, eased so the
    middle of a limb is genuinely shared and the ends are not: a linear blend
    puts half the elbow's influence at the shoulder, which makes an arm bend
    from the armpit.
    """
    axis = sub(end, start)
    span = length(axis)
    if span < 1e-6:
        return
    direction = normalise(axis)
    reference = (0.0, 0.0, 1.0) if abs(direction[2]) < 0.9 else (1.0, 0.0, 0.0)
    side = normalise((
        direction[1] * reference[2] - direction[2] * reference[1],
        direction[2] * reference[0] - direction[0] * reference[2],
        direction[0] * reference[1] - direction[1] * reference[0],
    ))
    up = (
        direction[1] * side[2] - direction[2] * side[1],
        direction[2] * side[0] - direction[0] * side[2],
        direction[0] * side[1] - direction[1] * side[0],
    )
    first = builder.vertex_count
    for ring in range(rings + 1):
        t = ring / rings
        radius = start_radius + (end_radius - start_radius) * t
        centre = (
            start[0] + axis[0] * t, start[1] + axis[1] * t, start[2] + axis[2] * t,
        )
        eased = t * t * (3.0 - 2.0 * t)
        bones = [(start_bone, 1.0 - eased), (end_bone, eased)]
        for segment in range(segments):
            angle = 2.0 * math.pi * segment / segments
            offset = (
                side[0] * math.cos(angle) + up[0] * math.sin(angle),
                side[1] * math.cos(angle) + up[1] * math.sin(angle),
                side[2] * math.cos(angle) + up[2] * math.sin(angle),
            )
            position = (
                centre[0] + offset[0] * radius,
                centre[1] + offset[1] * radius,
                centre[2] + offset[2] * radius,
            )
            builder.add(
                position, offset,
                (segment / segments, uv_base + t * 0.2),
                [(bone, weight) for bone, weight in bones if weight > 1e-4] or [(start_bone, 1.0)],
            )
    for ring in range(rings):
        for segment in range(segments):
            nxt = (segment + 1) % segments
            a = first + ring * segments + segment
            b = first + ring * segments + nxt
            c = first + (ring + 1) * segments + nxt
            d = first + (ring + 1) * segments + segment
            builder.quad(a, b, c, d)
    if cap_start:
        centre_index = builder.add(
            start, (-direction[0], -direction[1], -direction[2]), (0.5, uv_base), [(start_bone, 1.0)]
        )
        for segment in range(segments):
            nxt = (segment + 1) % segments
            builder.triangle(centre_index, first + nxt, first + segment)
    if cap_end:
        base = first + rings * segments
        centre_index = builder.add(end, direction, (0.5, uv_base + 0.2), [(end_bone, 1.0)])
        for segment in range(segments):
            nxt = (segment + 1) % segments
            builder.triangle(centre_index, base + segment, base + nxt)


def sphere(
    builder: MeshBuilder,
    centre: Sequence[float],
    radius: float,
    bone: int,
    *,
    segments: int = 20,
    rings: int = 14,
    squash: tuple[float, float, float] = (1.0, 1.0, 1.0),
    second_bone: tuple[int, float] | None = None,
) -> None:
    first = builder.vertex_count
    for ring in range(rings + 1):
        phi = math.pi * ring / rings
        for segment in range(segments + 1):
            theta = 2.0 * math.pi * segment / segments
            direction = (
                math.sin(phi) * math.sin(theta),
                math.cos(phi),
                math.sin(phi) * math.cos(theta),
            )
            position = (
                centre[0] + direction[0] * radius * squash[0],
                centre[1] + direction[1] * radius * squash[1],
                centre[2] + direction[2] * radius * squash[2],
            )
            bones = [(bone, 1.0)]
            if second_bone is not None:
                other, weight = second_bone
                bones = [(bone, 1.0 - weight), (other, weight)]
            builder.add(
                position, direction,
                (segment / segments, 1.0 - ring / rings), bones,
            )
    stride = segments + 1
    for ring in range(rings):
        for segment in range(segments):
            a = first + ring * stride + segment
            b = first + ring * stride + segment + 1
            c = first + (ring + 1) * stride + segment + 1
            d = first + (ring + 1) * stride + segment
            builder.quad(a, b, c, d)


def box(
    builder: MeshBuilder,
    centre: Sequence[float],
    half: Sequence[float],
    bone: int,
) -> None:
    corners = [
        (centre[0] + sx * half[0], centre[1] + sy * half[1], centre[2] + sz * half[2])
        for sx, sy, sz in (
            (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
            (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1),
        )
    ]
    faces = (
        ((0, 3, 2, 1), (0.0, 0.0, -1.0)),
        ((4, 5, 6, 7), (0.0, 0.0, 1.0)),
        ((0, 4, 7, 3), (-1.0, 0.0, 0.0)),
        ((1, 2, 6, 5), (1.0, 0.0, 0.0)),
        ((0, 1, 5, 4), (0.0, -1.0, 0.0)),
        ((3, 7, 6, 2), (0.0, 1.0, 0.0)),
    )
    for face, normal in faces:
        base = builder.vertex_count
        for position, uv in zip((corners[index] for index in face), ((0, 0), (1, 0), (1, 1), (0, 1))):
            builder.add(position, normal, uv, [(bone, 1.0)])
        builder.quad(base, base + 1, base + 2, base + 3)


def build_body(joint_index: dict[str, int]) -> MeshBuilder:
    """Head, neck, torso, arms, hands, legs and feet, as one skinned mesh."""
    builder = MeshBuilder()
    j = joint_index
    # Torso: hips -> spine -> chest -> neck, four tapered sections.
    tube(builder, BIND["hips"], BIND["spine"], 0.125, 0.128, j["hips"], j["spine"], rings=3, cap_start=True)
    tube(builder, BIND["spine"], BIND["chest"], 0.128, 0.140, j["spine"], j["chest"], rings=3, uv_base=0.2)
    tube(builder, BIND["chest"], BIND["neck"], 0.140, 0.062, j["chest"], j["neck"], rings=4, uv_base=0.4)
    tube(builder, BIND["neck"], BIND["head"], 0.058, 0.062, j["neck"], j["head"], rings=2, uv_base=0.6)
    # Head.
    sphere(builder, HEAD_CENTRE, HEAD_RADIUS, j["head"], squash=(0.94, 1.06, 0.98))
    # Arms.
    for side in ("left", "right"):
        tube(
            builder, BIND[f"{side}_shoulder"], BIND[f"{side}_upper_arm"], 0.062, 0.052,
            j["chest"], j[f"{side}_upper_arm"], rings=2, segments=10, uv_base=0.0,
        )
        tube(
            builder, BIND[f"{side}_upper_arm"], BIND[f"{side}_lower_arm"], 0.052, 0.042,
            j[f"{side}_upper_arm"], j[f"{side}_lower_arm"], rings=4, segments=10, uv_base=0.2,
        )
        tube(
            builder, BIND[f"{side}_lower_arm"], BIND[f"{side}_hand"], 0.042, 0.031,
            j[f"{side}_lower_arm"], j[f"{side}_hand"], rings=4, segments=10, uv_base=0.4,
        )
        sign = 1.0 if side == "left" else -1.0
        box(
            builder,
            (BIND[f"{side}_hand"][0] + sign * 0.045, BIND[f"{side}_hand"][1], 0.0),
            (0.048, 0.030, 0.016), j[f"{side}_hand"],
        )
        # Legs.
        tube(
            builder, BIND[f"{side}_upper_leg"], BIND[f"{side}_lower_leg"], 0.072, 0.056,
            j[f"{side}_upper_leg"], j[f"{side}_lower_leg"], rings=4, segments=10, uv_base=0.0,
        )
        tube(
            builder, BIND[f"{side}_lower_leg"], BIND[f"{side}_foot"], 0.056, 0.040,
            j[f"{side}_lower_leg"], j[f"{side}_foot"], rings=4, segments=10, uv_base=0.2,
        )
        box(
            builder,
            (BIND[f"{side}_foot"][0], BIND[f"{side}_foot"][1] - 0.038, 0.048),
            (0.046, 0.038, 0.098), j[f"{side}_foot"],
        )
    return builder


def build_clothes(joint_index: dict[str, int]) -> MeshBuilder:
    """A tunic and shorts, slightly proud of the body, as a second material."""
    builder = MeshBuilder()
    j = joint_index
    tube(builder, (0.0, 0.86, 0.0), BIND["spine"], 0.138, 0.140, j["hips"], j["spine"], rings=3, cap_start=True)
    tube(builder, BIND["spine"], BIND["chest"], 0.140, 0.152, j["spine"], j["chest"], rings=3, uv_base=0.2)
    tube(builder, BIND["chest"], (0.0, 1.335, 0.0), 0.152, 0.126, j["chest"], j["chest"], rings=3, uv_base=0.4, cap_end=True)
    for side in ("left", "right"):
        tube(
            builder, BIND[f"{side}_upper_leg"], (BIND[f"{side}_upper_leg"][0], 0.68, 0.0),
            0.084, 0.076, j[f"{side}_upper_leg"], j[f"{side}_upper_leg"],
            rings=2, segments=10, cap_end=True,
        )
        tube(
            builder, BIND[f"{side}_shoulder"], BIND[f"{side}_upper_arm"], 0.072, 0.062,
            j["chest"], j[f"{side}_upper_arm"], rings=2, segments=10, cap_start=True,
        )
    return builder


def build_eyes(joint_index: dict[str, int]) -> MeshBuilder:
    """Two small spheres on the eye bones. Blinking scales these bones flat."""
    builder = MeshBuilder()
    for side in ("left", "right"):
        sphere(
            builder, BIND[f"{side}_eye"], 0.0175, joint_index[f"{side}_eye"],
            segments=12, rings=8,
        )
    return builder


# --------------------------------------------------------------------------- #
# Morph targets
# --------------------------------------------------------------------------- #


def morph_deltas(name: str, positions: Sequence[Sequence[float]]) -> list[tuple[float, float, float]]:
    """Position deltas for one named morph, computed from the head geometry.

    Analytic rather than sculpted: each morph is a falloff around a named point
    on the face, which is what keeps a generated character legible without a
    modelling tool — and keeps this file readable, which a table of four
    thousand deltas would not be.
    """
    deltas: list[tuple[float, float, float]] = []
    for position in positions:
        x, y, z = position
        front = z > 0.012
        mouth = falloff(length(sub(position, MOUTH_CENTRE)), 0.052) if front else 0.0
        brow = falloff(length(sub(position, BROW_CENTRE)), 0.048) if front else 0.0
        cheek_l = falloff(length(sub(position, (0.062, 1.556, 0.062))), 0.045) if front else 0.0
        cheek_r = falloff(length(sub(position, (-0.062, 1.556, 0.062))), 0.045) if front else 0.0
        eye_l = falloff(length(sub(position, (0.040, 1.583, 0.070))), 0.036) if front else 0.0
        eye_r = falloff(length(sub(position, (-0.040, 1.583, 0.070))), 0.036) if front else 0.0
        lower_mouth = mouth if y <= MOUTH_CENTRE[1] else mouth * 0.15
        corner = mouth * min(1.0, abs(x) / 0.030) if abs(x) > 0.012 else 0.0

        if name == "mouth_open_small":
            delta = (0.0, -0.010 * lower_mouth, 0.002 * lower_mouth)
        elif name == "mouth_open_medium":
            delta = (0.0, -0.019 * lower_mouth, 0.004 * lower_mouth)
        elif name == "mouth_open_wide":
            delta = (0.0, -0.031 * lower_mouth, 0.006 * lower_mouth)
        elif name == "mouth_rounded":
            delta = (-0.010 * corner * (1.0 if x > 0 else -1.0), -0.007 * lower_mouth, 0.008 * mouth)
        elif name == "mouth_smile":
            delta = (0.005 * corner * (1.0 if x > 0 else -1.0), 0.008 * corner, 0.002 * mouth)
        elif name == "brow_raise":
            delta = (0.0, 0.010 * brow, 0.002 * brow)
        elif name == "brow_lower":
            delta = (0.0, -0.008 * brow, 0.003 * brow)
        elif name == "smile":
            delta = (
                0.003 * (cheek_l - cheek_r),
                0.007 * (cheek_l + cheek_r) + 0.006 * corner,
                0.002 * mouth,
            )
        elif name == "frown":
            delta = (0.0, -0.009 * corner - 0.004 * brow, 0.0)
        elif name == "eye_narrow":
            delta = (0.0, -0.006 * (eye_l + eye_r), 0.004 * (eye_l + eye_r))
        elif name == "cheek_puff":
            delta = (
                0.009 * (cheek_l - cheek_r),
                0.0,
                0.007 * (cheek_l + cheek_r),
            )
        else:
            raise SystemExit(f"unknown morph target: {name}")
        deltas.append(delta)
    return deltas


# --------------------------------------------------------------------------- #
# Animation
# --------------------------------------------------------------------------- #


def quaternion(axis: str, degrees: float) -> tuple[float, float, float, float]:
    half = math.radians(degrees) * 0.5
    s, c = math.sin(half), math.cos(half)
    return {
        "x": (s, 0.0, 0.0, c),
        "y": (0.0, s, 0.0, c),
        "z": (0.0, 0.0, s, c),
    }[axis]


def combine(*rotations: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    result = (0.0, 0.0, 0.0, 1.0)
    for rotation in rotations:
        x1, y1, z1, w1 = result
        x2, y2, z2, w2 = rotation
        result = (
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        )
    return result


def rotate(**parts: float) -> tuple[float, float, float, float]:
    """``rotate(x=10, z=-4)`` — degrees, applied X then Y then Z."""
    return combine(*(quaternion(axis, parts[axis]) for axis in ("x", "y", "z") if axis in parts))


REST = (0.0, 0.0, 0.0, 1.0)

#: Every clip: name -> (duration, loop, {bone: [(time, rotation), ...]}).
#:
#: A looping clip repeats its first key at its last time, so the crossfade back
#: to the start is a no-op rather than a snap.
CLIPS: dict[str, tuple[float, bool, dict[str, list[tuple[float, tuple[float, float, float, float]]]]]] = {
    "idle": (4.0, True, {
        "spine": [(0.0, REST), (2.0, rotate(z=1.2)), (4.0, REST)],
        "left_upper_arm": [(0.0, rotate(z=-72.0)), (2.0, rotate(z=-70.0)), (4.0, rotate(z=-72.0))],
        "right_upper_arm": [(0.0, rotate(z=72.0)), (2.0, rotate(z=70.0)), (4.0, rotate(z=72.0))],
        "left_lower_arm": [(0.0, rotate(y=-8.0)), (4.0, rotate(y=-8.0))],
        "right_lower_arm": [(0.0, rotate(y=8.0)), (4.0, rotate(y=8.0))],
        "head": [(0.0, REST), (2.0, rotate(x=1.5)), (4.0, REST)],
    }),
    "greeting": (2.0, False, {
        "right_upper_arm": [
            (0.0, rotate(z=72.0)), (0.4, rotate(z=140.0)), (0.9, rotate(z=150.0)),
            (1.4, rotate(z=140.0)), (2.0, rotate(z=72.0)),
        ],
        "right_lower_arm": [(0.0, REST), (0.6, rotate(y=22.0)), (1.2, rotate(y=-14.0)), (2.0, REST)],
        "left_upper_arm": [(0.0, rotate(z=-72.0)), (2.0, rotate(z=-72.0))],
        "head": [(0.0, REST), (0.8, rotate(x=-4.0, y=-6.0)), (2.0, REST)],
    }),
    "listening": (3.0, True, {
        "head": [(0.0, rotate(x=-5.0, z=6.0)), (1.5, rotate(x=-6.5, z=8.0)), (3.0, rotate(x=-5.0, z=6.0))],
        "neck": [(0.0, rotate(x=-3.0)), (1.5, rotate(x=-4.0)), (3.0, rotate(x=-3.0))],
        "spine": [(0.0, rotate(x=-2.5)), (3.0, rotate(x=-2.5))],
        "left_upper_arm": [(0.0, rotate(z=-70.0)), (3.0, rotate(z=-70.0))],
        "right_upper_arm": [(0.0, rotate(z=70.0)), (3.0, rotate(z=70.0))],
    }),
    "transcribing": (2.4, True, {
        "head": [(0.0, rotate(x=-3.0)), (0.6, rotate(x=-6.0)), (1.2, rotate(x=-3.0)), (1.8, rotate(x=-6.0)), (2.4, rotate(x=-3.0))],
        "left_upper_arm": [(0.0, rotate(z=-70.0)), (2.4, rotate(z=-70.0))],
        "right_upper_arm": [(0.0, rotate(z=70.0)), (2.4, rotate(z=70.0))],
    }),
    "understanding": (3.0, True, {
        "head": [(0.0, rotate(z=8.0, x=2.0)), (1.5, rotate(z=11.0, x=3.0)), (3.0, rotate(z=8.0, x=2.0))],
        "right_upper_arm": [(0.0, rotate(z=28.0, x=-40.0)), (3.0, rotate(z=28.0, x=-40.0))],
        "right_lower_arm": [(0.0, rotate(y=95.0)), (3.0, rotate(y=95.0))],
        "left_upper_arm": [(0.0, rotate(z=-66.0)), (3.0, rotate(z=-66.0))],
    }),
    "planning": (3.6, True, {
        "head": [(0.0, rotate(z=6.0)), (1.2, rotate(z=6.0, y=-8.0)), (2.4, rotate(z=6.0, y=8.0)), (3.6, rotate(z=6.0))],
        "right_upper_arm": [(0.0, rotate(z=30.0, x=-38.0)), (3.6, rotate(z=30.0, x=-38.0))],
        "right_lower_arm": [(0.0, rotate(y=90.0)), (3.6, rotate(y=90.0))],
        "left_upper_arm": [(0.0, rotate(z=-40.0, x=-20.0)), (3.6, rotate(z=-40.0, x=-20.0))],
        "left_lower_arm": [(0.0, rotate(y=-70.0)), (3.6, rotate(y=-70.0))],
    }),
    "working": (2.0, True, {
        "left_upper_arm": [(0.0, rotate(z=-46.0, x=-52.0)), (1.0, rotate(z=-44.0, x=-58.0)), (2.0, rotate(z=-46.0, x=-52.0))],
        "right_upper_arm": [(0.0, rotate(z=46.0, x=-52.0)), (1.0, rotate(z=44.0, x=-58.0)), (2.0, rotate(z=46.0, x=-52.0))],
        "left_lower_arm": [(0.0, rotate(y=-42.0)), (1.0, rotate(y=-52.0)), (2.0, rotate(y=-42.0))],
        "right_lower_arm": [(0.0, rotate(y=42.0)), (1.0, rotate(y=52.0)), (2.0, rotate(y=42.0))],
        "head": [(0.0, rotate(x=8.0)), (2.0, rotate(x=8.0))],
        "spine": [(0.0, rotate(x=4.0)), (1.0, rotate(x=5.5)), (2.0, rotate(x=4.0))],
    }),
    "researching": (4.0, True, {
        "head": [(0.0, rotate(y=-16.0, x=5.0)), (2.0, rotate(y=16.0, x=5.0)), (4.0, rotate(y=-16.0, x=5.0))],
        "left_upper_arm": [(0.0, rotate(z=-40.0, x=-46.0)), (4.0, rotate(z=-40.0, x=-46.0))],
        "left_lower_arm": [(0.0, rotate(y=-46.0)), (4.0, rotate(y=-46.0))],
        "right_upper_arm": [(0.0, rotate(z=40.0, x=-46.0)), (4.0, rotate(z=40.0, x=-46.0))],
        "right_lower_arm": [(0.0, rotate(y=46.0)), (4.0, rotate(y=46.0))],
        "spine": [(0.0, rotate(x=5.0)), (4.0, rotate(x=5.0))],
    }),
    "typing": (1.2, True, {
        "left_upper_arm": [(0.0, rotate(z=-40.0, x=-62.0)), (1.2, rotate(z=-40.0, x=-62.0))],
        "right_upper_arm": [(0.0, rotate(z=40.0, x=-62.0)), (1.2, rotate(z=40.0, x=-62.0))],
        "left_lower_arm": [(0.0, rotate(y=-52.0)), (0.3, rotate(y=-58.0)), (0.6, rotate(y=-52.0)), (0.9, rotate(y=-58.0)), (1.2, rotate(y=-52.0))],
        "right_lower_arm": [(0.0, rotate(y=58.0)), (0.3, rotate(y=52.0)), (0.6, rotate(y=58.0)), (0.9, rotate(y=52.0)), (1.2, rotate(y=58.0))],
        "head": [(0.0, rotate(x=12.0)), (1.2, rotate(x=12.0))],
    }),
    "reviewing": (3.2, True, {
        "left_upper_arm": [(0.0, rotate(z=-34.0, x=-58.0)), (3.2, rotate(z=-34.0, x=-58.0))],
        "left_lower_arm": [(0.0, rotate(y=-64.0)), (3.2, rotate(y=-64.0))],
        "right_upper_arm": [(0.0, rotate(z=64.0)), (3.2, rotate(z=64.0))],
        "head": [(0.0, rotate(x=15.0, y=-6.0)), (1.6, rotate(x=15.0, y=6.0)), (3.2, rotate(x=15.0, y=-6.0))],
    }),
    "waiting-for-user": (3.4, True, {
        "hips": [(0.0, rotate(z=1.5)), (1.7, rotate(z=-1.5)), (3.4, rotate(z=1.5))],
        "head": [(0.0, rotate(y=4.0)), (1.7, rotate(y=-4.0)), (3.4, rotate(y=4.0))],
        "left_upper_arm": [(0.0, rotate(z=-70.0)), (3.4, rotate(z=-70.0))],
        "right_upper_arm": [(0.0, rotate(z=70.0)), (3.4, rotate(z=70.0))],
    }),
    "waiting-for-approval": (2.2, True, {
        "left_upper_arm": [(0.0, rotate(z=-52.0, x=-30.0)), (2.2, rotate(z=-52.0, x=-30.0))],
        "right_upper_arm": [(0.0, rotate(z=52.0, x=-30.0)), (2.2, rotate(z=52.0, x=-30.0))],
        "left_lower_arm": [(0.0, rotate(y=-24.0)), (2.2, rotate(y=-24.0))],
        "right_lower_arm": [(0.0, rotate(y=24.0)), (2.2, rotate(y=24.0))],
        "head": [(0.0, rotate(x=-3.0)), (2.2, rotate(x=-3.0))],
    }),
    "speaking": (2.6, True, {
        "right_upper_arm": [(0.0, rotate(z=58.0, x=-24.0)), (0.9, rotate(z=50.0, x=-34.0)), (1.8, rotate(z=60.0, x=-20.0)), (2.6, rotate(z=58.0, x=-24.0))],
        "right_lower_arm": [(0.0, rotate(y=34.0)), (1.3, rotate(y=48.0)), (2.6, rotate(y=34.0))],
        "left_upper_arm": [(0.0, rotate(z=-68.0)), (2.6, rotate(z=-68.0))],
        "head": [(0.0, REST), (1.3, rotate(x=-2.0, y=3.0)), (2.6, REST)],
    }),
    "presenting-result": (2.2, False, {
        "left_upper_arm": [(0.0, rotate(z=-70.0)), (0.7, rotate(z=-40.0, x=-30.0)), (2.2, rotate(z=-44.0, x=-26.0))],
        "right_upper_arm": [(0.0, rotate(z=70.0)), (0.7, rotate(z=40.0, x=-30.0)), (2.2, rotate(z=44.0, x=-26.0))],
        "head": [(0.0, REST), (0.7, rotate(x=-6.0)), (2.2, rotate(x=-4.0))],
        "spine": [(0.0, REST), (0.7, rotate(x=-4.0)), (2.2, rotate(x=-3.0))],
    }),
    "success": (1.6, False, {
        "right_upper_arm": [(0.0, rotate(z=72.0)), (0.45, rotate(z=155.0)), (1.0, rotate(z=148.0)), (1.6, rotate(z=150.0))],
        "left_upper_arm": [(0.0, rotate(z=-72.0)), (0.45, rotate(z=-62.0)), (1.6, rotate(z=-66.0))],
        "head": [(0.0, REST), (0.45, rotate(x=-9.0)), (1.6, rotate(x=-6.0))],
        "spine": [(0.0, REST), (0.45, rotate(x=-5.0)), (1.6, rotate(x=-3.0))],
    }),
    "warning": (1.8, False, {
        "right_upper_arm": [(0.0, rotate(z=72.0)), (0.5, rotate(z=126.0, x=-16.0)), (1.8, rotate(z=120.0, x=-14.0))],
        "right_lower_arm": [(0.0, REST), (0.5, rotate(y=34.0)), (1.8, rotate(y=30.0))],
        "head": [(0.0, REST), (0.5, rotate(x=-4.0)), (1.8, rotate(x=-3.0))],
        "spine": [(0.0, REST), (0.5, rotate(x=-3.5)), (1.8, rotate(x=-3.0))],
    }),
    "blocked": (2.0, True, {
        "left_upper_arm": [(0.0, rotate(z=-28.0, x=-64.0)), (2.0, rotate(z=-28.0, x=-64.0))],
        "right_upper_arm": [(0.0, rotate(z=28.0, x=-64.0)), (2.0, rotate(z=28.0, x=-64.0))],
        "left_lower_arm": [(0.0, rotate(y=-92.0)), (2.0, rotate(y=-92.0))],
        "right_lower_arm": [(0.0, rotate(y=92.0)), (2.0, rotate(y=92.0))],
        "head": [(0.0, rotate(x=3.0)), (2.0, rotate(x=3.0))],
    }),
    "error": (1.5, False, {
        "spine": [(0.0, REST), (0.5, rotate(x=8.0)), (1.5, rotate(x=7.0))],
        "head": [(0.0, REST), (0.5, rotate(x=16.0)), (1.5, rotate(x=14.0))],
        "left_upper_arm": [(0.0, rotate(z=-72.0)), (0.5, rotate(z=-82.0)), (1.5, rotate(z=-80.0))],
        "right_upper_arm": [(0.0, rotate(z=72.0)), (0.5, rotate(z=82.0)), (1.5, rotate(z=80.0))],
    }),
    "paused": (3.0, True, {
        "spine": [(0.0, REST), (1.5, rotate(x=1.0)), (3.0, REST)],
        "left_upper_arm": [(0.0, rotate(z=-74.0)), (3.0, rotate(z=-74.0))],
        "right_upper_arm": [(0.0, rotate(z=74.0)), (3.0, rotate(z=74.0))],
        "head": [(0.0, rotate(x=2.0)), (3.0, rotate(x=2.0))],
    }),
    "cancelled": (1.3, False, {
        "left_upper_arm": [(0.0, rotate(z=-60.0)), (0.5, rotate(z=-78.0)), (1.3, rotate(z=-76.0))],
        "right_upper_arm": [(0.0, rotate(z=60.0)), (0.5, rotate(z=78.0)), (1.3, rotate(z=76.0))],
        "head": [(0.0, REST), (0.5, rotate(x=10.0, y=6.0)), (1.3, rotate(x=8.0, y=5.0))],
    }),
    "sleeping": (5.0, True, {
        "head": [(0.0, rotate(x=22.0, z=6.0)), (2.5, rotate(x=25.0, z=7.0)), (5.0, rotate(x=22.0, z=6.0))],
        "spine": [(0.0, rotate(x=5.0)), (2.5, rotate(x=7.0)), (5.0, rotate(x=5.0))],
        "left_upper_arm": [(0.0, rotate(z=-78.0)), (5.0, rotate(z=-78.0))],
        "right_upper_arm": [(0.0, rotate(z=78.0)), (5.0, rotate(z=78.0))],
    }),
    "repositioning": (1.6, True, {
        "hips": [(0.0, rotate(z=3.0)), (0.8, rotate(z=-3.0)), (1.6, rotate(z=3.0))],
        "spine": [(0.0, rotate(x=3.0)), (1.6, rotate(x=3.0))],
        "left_upper_arm": [(0.0, rotate(z=-62.0)), (1.6, rotate(z=-62.0))],
        "right_upper_arm": [(0.0, rotate(z=62.0)), (1.6, rotate(z=62.0))],
        "head": [(0.0, rotate(x=-2.0)), (0.8, rotate(x=-4.0)), (1.6, rotate(x=-2.0))],
    }),
}


# --------------------------------------------------------------------------- #
# PNG
# --------------------------------------------------------------------------- #


#: RFC 1951 §3.2.5, the length code table: code -> (base length, extra bits).
_LENGTH_CODES: tuple[tuple[int, int, int], ...] = (
    (257, 3, 0), (258, 4, 0), (259, 5, 0), (260, 6, 0), (261, 7, 0), (262, 8, 0),
    (263, 9, 0), (264, 10, 0), (265, 11, 1), (266, 13, 1), (267, 15, 1), (268, 17, 1),
    (269, 19, 2), (270, 23, 2), (271, 27, 2), (272, 31, 2), (273, 35, 3), (274, 43, 3),
    (275, 51, 3), (276, 59, 3), (277, 67, 4), (278, 83, 4), (279, 99, 4), (280, 115, 4),
    (281, 131, 5), (282, 163, 5), (283, 195, 5), (284, 227, 5), (285, 258, 0),
)


class _BitWriter:
    """Deflate's bit order: codes MSB-first, extra bits LSB-first, bytes LSB-first."""

    def __init__(self) -> None:
        self.data = bytearray()
        self._bits = 0
        self._count = 0

    def bits(self, value: int, count: int) -> None:
        """``count`` bits of ``value``, least-significant first."""
        for index in range(count):
            self._bits |= ((value >> index) & 1) << self._count
            self._count += 1
            if self._count == 8:
                self.data.append(self._bits)
                self._bits = 0
                self._count = 0

    def code(self, value: int, count: int) -> None:
        """A Huffman code: written most-significant bit first."""
        for index in range(count - 1, -1, -1):
            self.bits((value >> index) & 1, 1)

    def flush(self) -> bytes:
        if self._count:
            self.data.append(self._bits)
            self._bits = 0
            self._count = 0
        return bytes(self.data)


def _fixed_literal(value: int) -> tuple[int, int]:
    if value <= 143:
        return 0x30 + value, 8
    if value <= 255:
        return 0x190 + value - 144, 9
    if value <= 279:
        return value - 256, 7
    return 0xC0 + value - 280, 8


def deflate_fixed_rle(payload: bytes) -> bytes:
    """A zlib stream using fixed Huffman codes and distance-1 run matching.

    ``zlib.compress`` is **not** portable, and this is not a theoretical worry:
    the first build of this script used it, and the GLB it produced on Windows
    had SHA-256 ``988815ff…`` while the same script on Fedora produced
    ``041ece80…`` — same Python version, same inputs, different zlib build,
    different Huffman tree. The manifest carries that digest and the validator
    checks it, so a package built on one machine failed its own integrity check
    on the other.

    So the encoder is here, and it is deliberately the *simplest* thing that
    still compresses: RFC 1951's fixed Huffman tables, which are constants, plus
    greedy run-length matching at distance 1. Everything a real encoder chooses
    — the tree, the match search, the block boundaries — is what varies between
    implementations, and none of it is chosen here.

    It suits what it encodes. A silhouette frame is mostly one repeated value
    and compresses about twenty-fold; the character texture is a smooth gradient
    and compresses about three-fold. A photographic texture would compress badly
    and should use a real encoder, with the digest taken from whatever that
    encoder produced on the machine that built the package.
    """
    writer = _BitWriter()
    writer.bits(1, 1)  # BFINAL
    writer.bits(1, 2)  # BTYPE = fixed Huffman
    position = 0
    size = len(payload)
    while position < size:
        byte = payload[position]
        run = 1
        while position + run < size and payload[position + run] == byte and run < 259:
            run += 1
        code, width = _fixed_literal(byte)
        writer.code(code, width)
        position += 1
        remaining = run - 1
        while remaining >= 3:
            take = min(258, remaining)
            for identifier, base, extra in reversed(_LENGTH_CODES):
                span = base + ((1 << extra) - 1 if extra else 0)
                if base <= take <= span:
                    length_code, length_base, length_extra = identifier, base, extra
                    break
            else:  # pragma: no cover - the table covers 3..258 exhaustively
                raise SystemExit(f"no length code for {take}")
            code, width = _fixed_literal(length_code)
            writer.code(code, width)
            if length_extra:
                writer.bits(take - length_base, length_extra)
            writer.code(0, 5)  # distance code 0 == distance 1
            position += take
            remaining -= take
        while remaining > 0:
            code, width = _fixed_literal(byte)
            writer.code(code, width)
            position += 1
            remaining -= 1
    code, width = _fixed_literal(256)  # end of block
    writer.code(code, width)
    stream = b"\x78\x01" + writer.flush() + struct.pack(">I", zlib.adler32(payload) & 0xFFFFFFFF)
    # Fixed Huffman spends nine bits on every byte above 143, so on data with few
    # runs — the skin gradient is exactly that — it is *larger* than not
    # compressing at all. Stored blocks are the floor, and picking the smaller of
    # the two is still a deterministic function of the input.
    stored = _deflate_stored(payload)
    chosen = stream if len(stream) <= len(stored) else stored
    if zlib.decompress(chosen) != payload:  # pragma: no cover - a bug, not an input
        raise SystemExit("the deterministic deflate encoder produced a stream zlib cannot read")
    return chosen


def _deflate_stored(payload: bytes) -> bytes:
    """Uncompressed deflate blocks: the deterministic floor."""
    stream = bytearray(b"\x78\x01")
    chunk_size = 65535
    if not payload:
        stream.extend(b"\x01\x00\x00\xff\xff")
    for start in range(0, len(payload), chunk_size):
        block = payload[start:start + chunk_size]
        final = 1 if start + chunk_size >= len(payload) else 0
        stream.append(final)
        stream.extend(struct.pack("<HH", len(block), len(block) ^ 0xFFFF))
        stream.extend(block)
    stream.extend(struct.pack(">I", zlib.adler32(payload) & 0xFFFFFFFF))
    return bytes(stream)


def write_png(path: Path, width: int, height: int, pixels: bytes) -> bytes:
    """Minimal RGBA8 PNG, filter 0, deterministic on every platform."""
    data = _png_bytes(width, height, pixels)
    path.write_bytes(data)
    return data


def skin_texture(size: int = 64) -> bytes:
    """A soft vertical gradient with a subtle cloth band. No photograph, no scan."""
    pixels = bytearray()
    for y in range(size):
        t = y / (size - 1)
        for x in range(size):
            u = x / (size - 1)
            shade = 0.90 + 0.10 * math.sin(u * math.pi)
            red = int(226 * shade - 26 * t)
            green = int(191 * shade - 22 * t)
            blue = int(168 * shade - 18 * t)
            pixels.extend((max(0, min(255, red)), max(0, min(255, green)), max(0, min(255, blue)), 255))
    return bytes(pixels)


#: The 2D fallback frames, and the pose each one draws.
#:
#: Flat schematic silhouettes of the same figure, not renders of it. Rendering
#: the GLB to produce them would have been prettier and would have made this
#: script require a GPU, a context and a compositor to build a *package* — so
#: the fallback is drawn arithmetically and the report says plainly that it is a
#: schematic. §37 lists replacing these with real art as remaining work.
#:
#: ``(arm_angle_degrees, lean, head_tilt, tint)``
FALLBACK_POSES: dict[str, tuple[float, float, float, tuple[int, int, int]]] = {
    "idle-1": (18.0, 0.0, 0.0, (94, 132, 176)),
    "idle-2": (22.0, 0.01, 0.02, (94, 132, 176)),
    "listening": (16.0, -0.03, 0.10, (86, 146, 168)),
    "thinking": (52.0, 0.0, 0.09, (108, 126, 176)),
    "working-1": (62.0, 0.04, -0.06, (98, 140, 152)),
    "working-2": (70.0, 0.05, -0.07, (98, 140, 152)),
    "reviewing": (58.0, 0.05, -0.10, (104, 134, 160)),
    "speaking-closed": (30.0, -0.02, 0.02, (96, 138, 178)),
    "speaking-open": (38.0, -0.03, 0.03, (96, 138, 178)),
    "success": (128.0, -0.04, -0.05, (92, 164, 128)),
    "warning": (96.0, -0.02, -0.02, (196, 158, 76)),
    "error": (10.0, 0.07, 0.13, (188, 104, 100)),
    "sleeping": (8.0, 0.05, 0.20, (118, 122, 148)),
    "moving": (26.0, 0.0, -0.03, (94, 132, 176)),
    "preview-3d": (24.0, 0.0, 0.0, (94, 132, 176)),
}


def silhouette(pose: tuple[float, float, float, tuple[int, int, int]], size: int = 96) -> bytes:
    """One flat figure at one pose. Pure arithmetic; no font, photo or import."""
    arm_degrees, lean, tilt, colour = pose
    arm = math.radians(arm_degrees)
    pixels = bytearray()
    for y in range(size):
        for x in range(size):
            nx = (x - size / 2) / (size / 2)
            ny = (y - size / 2) / (size / 2)
            # Lean and head tilt shear the figure about its feet.
            sx = nx - lean * (0.9 - ny)
            head_x = sx - tilt * 0.35
            inside = False
            if (head_x * head_x + (ny + 0.60) ** 2) < 0.052:
                inside = True
            elif abs(sx) < 0.19 and -0.42 < ny < 0.40:
                inside = True
            elif abs(abs(sx) - 0.115) < 0.072 and 0.34 < ny < 0.93:
                inside = True
            else:
                # Two arms, each a rotated capsule from the shoulder.
                for side in (-1.0, 1.0):
                    ox, oy = sx - side * 0.185, ny + 0.34
                    ax = ox * math.cos(arm) + oy * math.sin(arm) * side
                    ay = -ox * math.sin(arm) * side + oy * math.cos(arm)
                    if abs(ax) < 0.062 and -0.02 < ay < 0.62:
                        inside = True
                        break
            if inside:
                shade = 1.0 - 0.16 * max(0.0, ny)
                pixels.extend((
                    max(0, min(255, int(colour[0] * shade))),
                    max(0, min(255, int(colour[1] * shade))),
                    max(0, min(255, int(colour[2] * shade))),
                    255,
                ))
            else:
                pixels.extend((0, 0, 0, 0))
    return bytes(pixels)


# --------------------------------------------------------------------------- #
# GLB assembly
# --------------------------------------------------------------------------- #


class BufferWriter:
    """Appends aligned blocks to the single binary chunk and records views."""

    def __init__(self) -> None:
        self.data = bytearray()
        self.views: list[dict[str, Any]] = []
        self.accessors: list[dict[str, Any]] = []

    def _align(self, alignment: int = 4) -> None:
        while len(self.data) % alignment:
            self.data.append(0)

    def view(self, payload: bytes, *, target: int | None = None) -> int:
        self._align()
        offset = len(self.data)
        self.data.extend(payload)
        entry: dict[str, Any] = {"buffer": 0, "byteOffset": offset, "byteLength": len(payload)}
        if target is not None:
            entry["target"] = target
        self.views.append(entry)
        return len(self.views) - 1

    def accessor(
        self,
        payload: bytes,
        *,
        component_type: int,
        element_type: str,
        count: int,
        target: int | None = None,
        minimum: Sequence[float] | None = None,
        maximum: Sequence[float] | None = None,
        normalized: bool = False,
    ) -> int:
        view = self.view(payload, target=target)
        entry: dict[str, Any] = {
            "bufferView": view,
            "componentType": component_type,
            "count": count,
            "type": element_type,
        }
        if normalized:
            entry["normalized"] = True
        if minimum is not None:
            entry["min"] = [float(value) for value in minimum]
        if maximum is not None:
            entry["max"] = [float(value) for value in maximum]
        self.accessors.append(entry)
        return len(self.accessors) - 1

    def floats(self, values: Iterable[float], *, element_type: str, target: int | None = None,
               bounds: bool = False) -> int:
        # Quantised to a micrometre before packing, and this is the second half
        # of the determinism story. ``math.sin`` and ``math.cos`` are libm calls,
        # and glibc and the MSVC runtime disagree in the last unit in the last
        # place — enough to change a vertex, an accessor's ``min``, the length
        # of the JSON chunk and therefore the digest. Rounding to 1e-6 is four
        # orders of magnitude finer than anything visible on a 1.7 m figure and
        # ten orders coarser than the disagreement, so the two platforms land on
        # the same number. §33 of the report records the measurement that showed
        # this was necessary rather than theoretical.
        flat = [round(float(value), 6) + 0.0 for value in values]
        components = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}[element_type]
        count = len(flat) // components
        minimum = maximum = None
        if bounds and count:
            minimum = [min(flat[index::components]) for index in range(components)]
            maximum = [max(flat[index::components]) for index in range(components)]
        return self.accessor(
            struct.pack(f"<{len(flat)}f", *flat), component_type=5126, element_type=element_type,
            count=count, target=target, minimum=minimum, maximum=maximum,
        )


def build_glb() -> tuple[bytes, dict[str, Any]]:
    joint_index = {name: index for index, name in enumerate(ORDER)}
    body = build_body(joint_index)
    clothes = build_clothes(joint_index)
    eyes = build_eyes(joint_index)

    writer = BufferWriter()
    nodes: list[dict[str, Any]] = []
    for name in ORDER:
        parent = PARENT[name]
        origin = (0.0, 0.0, 0.0) if parent is None else BIND[parent]
        local = sub(BIND[name], origin)
        entry: dict[str, Any] = {"name": name, "translation": [round(value, 6) for value in local]}
        children = [joint_index[child] for child in ORDER if PARENT[child] == name]
        if children:
            entry["children"] = children
        nodes.append(entry)

    inverse_bind: list[float] = []
    for name in ORDER:
        x, y, z = BIND[name]
        inverse_bind.extend((
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            -x, -y, -z, 1.0,
        ))
    ibm_accessor = writer.floats(inverse_bind, element_type="MAT4")

    meshes: list[dict[str, Any]] = []
    mesh_nodes: list[int] = []
    for mesh_index, (builder, mesh_name, material) in enumerate((
        (body, "BunnyBody", 0), (clothes, "BunnyClothes", 1), (eyes, "BunnyEyes", 2),
    )):
        attributes = {
            "POSITION": writer.floats(
                (value for position in builder.positions for value in position),
                element_type="VEC3", target=34962, bounds=True,
            ),
            "NORMAL": writer.floats(
                (value for normal in builder.normals for value in normal),
                element_type="VEC3", target=34962,
            ),
            "TEXCOORD_0": writer.floats(
                (value for uv in builder.uvs for value in uv),
                element_type="VEC2", target=34962,
            ),
            "JOINTS_0": writer.accessor(
                struct.pack(
                    f"<{len(builder.joints) * 4}B",
                    *[value for group in builder.joints for value in group],
                ),
                component_type=5121, element_type="VEC4", count=builder.vertex_count, target=34962,
            ),
            "WEIGHTS_0": writer.floats(
                (value for group in builder.weights for value in group),
                element_type="VEC4", target=34962,
            ),
        }
        indices = writer.accessor(
            struct.pack(f"<{len(builder.indices)}H", *builder.indices),
            component_type=5123, element_type="SCALAR", count=len(builder.indices), target=34963,
        )
        primitive: dict[str, Any] = {
            "attributes": attributes, "indices": indices, "material": material, "mode": 4,
        }
        mesh: dict[str, Any] = {"name": mesh_name, "primitives": [primitive]}
        if mesh_index == 0:
            targets = []
            for morph in MORPH_NAMES:
                deltas = morph_deltas(morph, builder.positions)
                targets.append({
                    "POSITION": writer.floats(
                        (value for delta in deltas for value in delta),
                        element_type="VEC3", target=34962, bounds=True,
                    )
                })
            primitive["targets"] = targets
            mesh["weights"] = [0.0] * len(MORPH_NAMES)
            mesh["extras"] = {"targetNames": list(MORPH_NAMES)}
        meshes.append(mesh)
        node_index = len(nodes)
        node: dict[str, Any] = {"name": mesh_name, "mesh": mesh_index, "skin": 0}
        if mesh_index == 0:
            node["weights"] = [0.0] * len(MORPH_NAMES)
        nodes.append(node)
        mesh_nodes.append(node_index)

    animations: list[dict[str, Any]] = []
    for clip_name, (duration, _loop, tracks) in CLIPS.items():
        samplers: list[dict[str, Any]] = []
        channels: list[dict[str, Any]] = []
        for bone, keys in sorted(tracks.items()):
            times = [time for time, _rotation in keys]
            if times[-1] < duration:
                times.append(duration)
                keys = list(keys) + [(duration, keys[-1][1])]
            values = [component for _time, rotation in keys for component in rotation]
            sampler = {
                "input": writer.floats(times, element_type="SCALAR", bounds=True),
                "output": writer.floats(values, element_type="VEC4"),
                "interpolation": "LINEAR",
            }
            samplers.append(sampler)
            channels.append({
                "sampler": len(samplers) - 1,
                "target": {"node": joint_index[bone], "path": "rotation"},
            })
        animations.append({"name": clip_name, "samplers": samplers, "channels": channels})

    texture_bytes = skin_texture()
    texture_png = _png_bytes(64, 64, texture_bytes)
    image_view = writer.view(texture_png)

    document: dict[str, Any] = {
        "asset": {
            "version": "2.0",
            "generator": "bunny-os scripts/build_default_character_3d.py",
            "copyright": "Copyright 2026 ComradeArt. GPL-3.0-or-later.",
        },
        "scene": 0,
        "scenes": [{"nodes": [0] + mesh_nodes}],
        "nodes": nodes,
        "meshes": meshes,
        "skins": [{"inverseBindMatrices": ibm_accessor, "joints": list(range(len(ORDER))), "skeleton": 0}],
        "animations": animations,
        "materials": [
            {
                "name": "bunny-skin",
                "pbrMetallicRoughness": {
                    "baseColorFactor": [1.0, 1.0, 1.0, 1.0],
                    "baseColorTexture": {"index": 0},
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.72,
                },
            },
            {
                "name": "bunny-cloth",
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.29, 0.44, 0.62, 1.0],
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.88,
                },
            },
            {
                "name": "bunny-eye",
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.12, 0.13, 0.16, 1.0],
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.28,
                },
            },
        ],
        "images": [{"name": "bunny-skin", "mimeType": "image/png", "bufferView": image_view}],
        "samplers": [{"magFilter": 9729, "minFilter": 9729, "wrapS": 10497, "wrapT": 10497}],
        "textures": [{"name": "bunny-skin", "sampler": 0, "source": 0}],
        "bufferViews": writer.views,
        "accessors": writer.accessors,
        "buffers": [{"byteLength": len(writer.data)}],
    }

    binary = bytes(writer.data)
    while len(binary) % 4:
        binary += b"\x00"
    document["buffers"][0]["byteLength"] = len(binary)
    json_bytes = json.dumps(document, separators=(",", ":"), sort_keys=False).encode("utf-8")
    while len(json_bytes) % 4:
        json_bytes += b" "

    total = 12 + 8 + len(json_bytes) + 8 + len(binary)
    glb = (
        struct.pack("<III", 0x46546C67, 2, total)
        + struct.pack("<II", len(json_bytes), 0x4E4F534A) + json_bytes
        + struct.pack("<II", len(binary), 0x004E4942) + binary
    )
    summary = {
        "vertices": body.vertex_count + clothes.vertex_count + eyes.vertex_count,
        "triangles": (len(body.indices) + len(clothes.indices) + len(eyes.indices)) // 3,
        "joints": len(ORDER),
        "clips": len(animations),
        "morphTargets": len(MORPH_NAMES),
        "textureBytes": len(texture_png),
        "bounds": _bounds(body.positions + clothes.positions + eyes.positions),
    }
    return glb, summary


def _png_bytes(width: int, height: int, pixels: bytes) -> bytes:
    raw = bytearray()
    for row in range(height):
        raw.append(0)
        raw.extend(pixels[row * width * 4:(row + 1) * width * 4])

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", deflate_fixed_rle(bytes(raw)))
        + chunk(b"IEND", b"")
    )


def _bounds(positions: Sequence[Sequence[float]]) -> dict[str, list[float]]:
    minimum = [min(position[axis] for position in positions) for axis in range(3)]
    maximum = [max(position[axis] for position in positions) for axis in range(3)]
    return {"min": [round(value, 6) for value in minimum], "max": [round(value, 6) for value in maximum]}


LICENCE_TEXT = """Bunny reference 3D companion character
Copyright 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later

Every byte of this package is generated by
scripts/build_default_character_3d.py in the Bunny OS repository. The geometry,
the rig, the skin weights, the morph targets, the animation clips, the texture
and the 2D fallback frames are computed arithmetically from that script. Nothing
here is derived from a scan, a photograph, a purchased asset, a game character,
a motion-capture recording or any third-party model, and no third-party licence
applies to any part of it.

The package may be redistributed and modified under the terms of the GNU General
Public Licence, version 3 or later, together with the rest of Bunny OS.
"""

PROVENANCE_NOTE = (
    "Generated, not hand-created. Every asset in this package is the output of "
    "scripts/build_default_character_3d.py at the recorded commit; re-running "
    "that script reproduces each file byte for byte, which is what the digests "
    "in manifest.json are checked against."
)

#: State -> 2D animation, for the fallback body of the manifest.
FALLBACK_STATE_MAP: dict[str, str] = {
    "idle": "idle", "starting": "idle", "greeting": "idle",
    "listening": "listening", "transcribing": "listening",
    "understanding": "thinking", "planning": "thinking", "thinking": "thinking",
    "researching": "thinking", "reviewing": "reviewing",
    "working": "working", "typing": "working",
    "waiting_for_user": "listening", "waiting_for_approval": "warning",
    "speaking": "speaking", "presenting_result": "speaking",
    "success": "success", "warning": "warning", "blocked": "warning",
    "degraded": "warning", "error": "error", "paused": "idle",
    "cancelled": "idle", "disconnected": "sleeping", "unavailable": "sleeping",
    "sleeping": "sleeping", "moving": "moving", "repositioning": "moving",
    "static_fallback": "idle",
}

FALLBACK_ANIMATIONS: dict[str, dict[str, Any]] = {
    "idle": {
        "kind": "frame-sequence", "loop": True, "transition": "crossfade", "playbackSpeed": 1.0,
        "frames": [{"assetId": "idle-1", "durationMs": 900}, {"assetId": "idle-2", "durationMs": 900}],
    },
    "working": {
        "kind": "frame-sequence", "loop": True, "transition": "crossfade", "playbackSpeed": 1.0,
        "frames": [{"assetId": "working-1", "durationMs": 400}, {"assetId": "working-2", "durationMs": 400}],
    },
    "speaking": {
        "kind": "frame-sequence", "loop": True, "transition": "interruptible", "playbackSpeed": 1.0,
        "frames": [
            {"assetId": "speaking-closed", "durationMs": 160},
            {"assetId": "speaking-open", "durationMs": 160},
        ],
    },
    "listening": {
        "kind": "static", "loop": False, "transition": "immediate",
        "frames": [{"assetId": "listening", "durationMs": 1000}],
    },
    "thinking": {
        "kind": "static", "loop": False, "transition": "immediate",
        "frames": [{"assetId": "thinking", "durationMs": 1000}],
    },
    "reviewing": {
        "kind": "static", "loop": False, "transition": "immediate",
        "frames": [{"assetId": "reviewing", "durationMs": 1000}],
    },
    "success": {
        "kind": "static", "loop": False, "transition": "return-to-idle",
        "frames": [{"assetId": "success", "durationMs": 1400}],
    },
    "warning": {
        "kind": "static", "loop": False, "transition": "immediate",
        "frames": [{"assetId": "warning", "durationMs": 1000}],
    },
    "error": {
        "kind": "static", "loop": False, "transition": "immediate",
        "frames": [{"assetId": "error", "durationMs": 1000}],
    },
    "sleeping": {
        "kind": "static", "loop": False, "transition": "immediate",
        "frames": [{"assetId": "sleeping", "durationMs": 1000}],
    },
    "moving": {
        "kind": "static", "loop": False, "transition": "immediate",
        "frames": [{"assetId": "moving", "durationMs": 1000}],
    },
    "mouth-closed": {
        "kind": "static", "loop": False, "transition": "immediate",
        "frames": [{"assetId": "speaking-closed", "durationMs": 120}],
    },
    "mouth-open": {
        "kind": "static", "loop": False, "transition": "immediate",
        "frames": [{"assetId": "speaking-open", "durationMs": 120}],
    },
}

ACCESSIBILITY_STATES: dict[str, str] = {
    "idle": "Bunny is standing still and ready.",
    "greeting": "Bunny raises a hand in greeting.",
    "listening": "Bunny leans in slightly and turns its head to listen.",
    "transcribing": "Bunny nods while the words are written down.",
    "understanding": "Bunny tilts its head, thinking about the request.",
    "planning": "Bunny looks from side to side while planning.",
    "working": "Bunny works with both hands in front of it.",
    "researching": "Bunny looks left and right, reading.",
    "typing": "Bunny's hands move quickly in front of it.",
    "reviewing": "Bunny holds something up and looks down at it.",
    "waiting-for-user": "Bunny shifts its weight, waiting for you.",
    "waiting-for-approval": "Bunny holds both hands open and waits for your decision.",
    "speaking": "Bunny gestures while speaking.",
    "presenting-result": "Bunny opens both arms to present the result.",
    "success": "Bunny raises one arm; the task finished successfully.",
    "warning": "Bunny raises a hand; something needs attention.",
    "blocked": "Bunny folds its arms; the task has not continued.",
    "error": "Bunny's shoulders drop and it looks down; something went wrong.",
    "paused": "Bunny stands still; the task is paused.",
    "cancelled": "Bunny lowers its arms and looks away; the task was cancelled.",
    "sleeping": "Bunny's head is lowered and it breathes slowly.",
    "repositioning": "Bunny shifts as it is moved to a new place.",
}

VISEME_MAP: dict[str, dict[str, float]] = {
    "neutral": {},
    "closed": {},
    "open-small": {"mouth_open_small": 1.0},
    "open-medium": {"mouth_open_medium": 1.0},
    "open-wide": {"mouth_open_wide": 1.0},
    "rounded": {"mouth_rounded": 1.0},
    "smile": {"mouth_smile": 1.0},
}

EXPRESSION_MAP: dict[str, dict[str, float]] = {
    "neutral": {},
    "happy": {"smile": 0.85, "brow_raise": 0.2},
    "focused": {"brow_lower": 0.5},
    "thinking": {"brow_lower": 0.35, "eye_narrow": 0.3},
    "concerned": {"brow_lower": 0.6, "frown": 0.4},
    "warning": {"brow_raise": 0.5, "frown": 0.5},
    "error": {"frown": 0.9, "brow_lower": 0.4},
    "surprised": {"brow_raise": 1.0, "mouth_open_medium": 0.5},
    "sleepy": {"eye_narrow": 0.8, "brow_lower": 0.2},
}


def digest_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_package(directory: Path) -> dict[str, Any]:
    """Write every file of the package and the manifest that describes them."""
    assets_directory = directory / "assets"
    assets_directory.mkdir(parents=True, exist_ok=True)
    inventory: list[dict[str, Any]] = []

    glb, summary = build_glb()
    model_path = assets_directory / "bunny-3d.glb"
    model_path.write_bytes(glb)
    inventory.append({
        "assetId": "bunny-3d-model", "path": "assets/bunny-3d.glb",
        "mediaType": "model/gltf-binary", "sha256": digest_of(glb),
        "sizeBytes": len(glb), "purpose": "model",
    })

    for name, pose in FALLBACK_POSES.items():
        payload = _png_bytes(96, 96, silhouette(pose))
        (assets_directory / f"{name}.png").write_bytes(payload)
        inventory.append({
            "assetId": name, "path": f"assets/{name}.png", "mediaType": "image/png",
            "sha256": digest_of(payload), "sizeBytes": len(payload),
            "width": 96, "height": 96,
            "purpose": "thumbnail" if name == "preview-3d" else "render",
        })

    licence = LICENCE_TEXT.encode("utf-8")
    (directory / "LICENSE.txt").write_bytes(licence)
    inventory.append({
        "assetId": "licence", "path": "LICENSE.txt", "mediaType": "text/plain",
        "sha256": digest_of(licence), "sizeBytes": len(licence), "purpose": "license",
    })

    provenance = {
        "creator": "ComradeArt",
        "creationSource": "scripts/build_default_character_3d.py",
        "generated": True,
        "handCreated": False,
        "tool": "python3 (standard library only)",
        "generationWorkflow": (
            "Geometry, rig, skin weights, morph targets, animation clips, texture and 2D "
            "fallback frames are computed arithmetically by the named script and written "
            "directly to GLB and PNG. No modelling, sculpting or animation tool is involved."
        ),
        "modificationHistory": [
            {
                "change": "created",
                "description": (
                    "Initial reference character for the Bunny Companion 3D renderer phase: "
                    "23 joints on the bunny-humanoid-1 profile, 11 face morph targets, "
                    "22 animation clips, one 64x64 generated texture."
                ),
            }
        ],
        "derivedFrom": "nothing",
        "thirdPartyContent": "none",
        "licence": "GPL-3.0-or-later",
        "note": PROVENANCE_NOTE,
        "modelSummary": summary,
    }
    provenance_bytes = json.dumps(provenance, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    (directory / "PROVENANCE.json").write_bytes(provenance_bytes)
    inventory.append({
        "assetId": "provenance", "path": "PROVENANCE.json", "mediaType": "application/json",
        "sha256": digest_of(provenance_bytes), "sizeBytes": len(provenance_bytes),
        "purpose": "provenance",
    })

    bounds = summary["bounds"]
    height = bounds["max"][1] - bounds["min"][1]
    manifest: dict[str, Any] = {
        "schemaVersion": 1,
        "packageId": "bunny-default-3d",
        "characterId": "bunny",
        "characterName": "Bunny (3D reference)",
        "packageVersion": "1.0.0",
        "creator": "ComradeArt",
        "license": "GPL-3.0-or-later",
        "copyright": "Copyright 2026 ComradeArt",
        "licenseAsset": "licence",
        "supportedRendererVersions": {
            "full-3d": "1.0", "lightweight-3d": "1.0", "animated-2d": "1.0", "static-image": "1.0",
        },
        "minimumBunnyOsVersion": "0.1.0",
        "presentationType": "full-3d",
        "assetInventory": inventory,
        "fallbackAsset": "idle-1",
        "thumbnailAsset": "preview-3d",
        "declaredDimensions": {"width": 96, "height": 96},
        "declaredFrameRate": 30.0,
        "declaredMemoryEstimateBytes": 8 * 1024 * 1024,
        "animations": FALLBACK_ANIMATIONS,
        "stateMap": FALLBACK_STATE_MAP,
        "expressionMap": {
            "idle": "idle", "happy": "success", "focused": "working",
            "thinking": "thinking", "concerned": "warning", "error": "error",
            "neutral": "idle", "sleepy": "sleeping",
        },
        "mouthShapeMap": {
            "closed": "mouth-closed", "neutral": "mouth-closed",
            "open-small": "mouth-open", "open-medium": "mouth-open",
            "open-wide": "mouth-open", "rounded": "mouth-open", "smile": "mouth-open",
        },
        "bubbleAnchor": {"x": 0.72, "y": 0.18, "preferredSide": "auto"},
        "boundingBox": {"x": 0.12, "y": 0.02, "width": 0.76, "height": 0.96},
        "safeMargins": {"top": 0.02, "right": 0.04, "bottom": 0.02, "left": 0.04},
        "generationProvenance": {
            "generated": True,
            "tool": "scripts/build_default_character_3d.py",
            "creator": "ComradeArt",
            "derivedFrom": "nothing",
        },
        "threeDimensional": {
            "schemaVersion": 1,
            "rendererApiVersion": "1.0",
            "modelFile": "assets/bunny-3d.glb",
            "modelDigest": digest_of(glb),
            "modelSizeBytes": len(glb),
            "gltfVersion": "2.0",
            "skeletonProfile": "bunny-humanoid-1",
            "boneMap": {name: name for name in ORDER},
            "rootBone": "root",
            "headBone": "head",
            "neckBone": "neck",
            "eyeBones": ["left_eye", "right_eye"],
            "handBones": ["left_hand", "right_hand"],
            "animationMap": {name: name for name in CLIPS},
            "expressionMap": EXPRESSION_MAP,
            "visemeMap": VISEME_MAP,
            "morphTargets": list(MORPH_NAMES),
            "textureInventory": [
                {"name": "bunny-skin", "width": 64, "height": 64, "mediaType": "image/png"}
            ],
            "materialInventory": ["bunny-skin", "bunny-cloth", "bunny-eye"],
            "modelBounds": bounds,
            "nativeScale": 1.0,
            "floorOffset": 0.0,
            "bubbleAnchor": [0.24, round(height * 0.86, 4), 0.10],
            "cameraAnchor": [0.0, round(height * 0.55, 4), 0.0],
            "maximumTriangles": 8000,
            "maximumVertices": 6000,
            "maximumJoints": 32,
            "maximumMorphTargets": 16,
            "maximumTextures": 4,
            "maximumTextureDimensions": 256,
            "declaredGpuBytes": 4 * 1024 * 1024,
            "declaredDecodedBytes": 1024 * 1024,
            "requiredRendererFeatures": [
                "skeletal-animation", "morph-targets", "base-colour-texture",
            ],
            "staticFallbackAsset": "idle-1",
            "animatedFallbackState": "idle",
            "previewAsset": "preview-3d",
            "accessibilityStates": ACCESSIBILITY_STATES,
        },
    }
    manifest_bytes = json.dumps(manifest, indent=2, sort_keys=False).encode("utf-8") + b"\n"
    (directory / "manifest.json").write_bytes(manifest_bytes)
    summary["packageFiles"] = len(inventory) + 1
    summary["manifestBytes"] = len(manifest_bytes)
    summary["modelBytes"] = len(glb)
    summary["modelDigest"] = digest_of(glb)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="the package directory to write into")
    parser.add_argument("--summary", action="store_true", help="print the model summary as JSON")
    arguments = parser.parse_args()

    summary = build_package(arguments.output)
    if arguments.summary:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(
            f"wrote {arguments.output} "
            f"({summary['modelBytes']} model bytes, sha256 {summary['modelDigest']})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
