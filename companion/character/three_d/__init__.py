# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The 3D presentation subsystem: a renderer, and nothing that decides anything.

This package draws a validated humanoid character from a canonical
:class:`companion.presentation.PresentationState` that somebody else computed.
It is the fifth and sixth rungs of a ladder whose lower four already existed,
and it is *only* rungs — no task authority, no provider selection, no approval
resolution, no tool execution, no microphone, no network.

The boundary is not a convention. ``tests/companion/test_three_d_isolation.py``
reads the import graph of every module below this one and fails if any of them
reaches :mod:`companion.store`, :mod:`companion.runtime`, :mod:`companion.tools`,
:mod:`companion.approvals`, :mod:`companion.agents`, :mod:`companion.desktop`,
:mod:`companion.speech` or the voice worker internals. What may cross is the
presentation contract: :class:`companion.presentation.PresentationState`, the
mapped character state, the generic mouth shapes, and the accessibility
preferences — all of them values, none of them handles.

Import cost is part of the boundary too. Nothing here imports OpenGL, GTK or any
other graphics library at module scope; §30 requires a text-only or headless
build to initialise no GPU library at all, and a module-level ``import gi``
would defeat that before any policy could be consulted. The GL binding is loaded
by :func:`companion.character.three_d.gl.load_gl` at the moment a context is
current and not before.
"""

from __future__ import annotations

#: Bumped when the 3D section of the character package contract changes shape.
#: Independent of :data:`companion.character.CHARACTER_PACKAGE_SCHEMA_VERSION`
#: because a package may carry a 2D body of schema 1 and no 3D section at all.
THREE_D_PACKAGE_SCHEMA_VERSION = 1

#: The renderer contract a package declares against. A package whose major
#: version differs is refused rather than drawn approximately.
THREE_D_RENDERER_API_VERSION = "1.0"

#: The GLB/glTF revision this validator implements. Nothing else is accepted.
SUPPORTED_GLTF_VERSION = "2.0"

#: The two 3D rungs. They are strings rather than an enum here because they are
#: the same strings :data:`companion.presentation.PRESENTATION_KINDS` uses, and
#: a second vocabulary for one ladder is how the two drift apart.
FULL_3D = "full-3d"
LIGHTWEIGHT_3D = "lightweight-3d"

__all__ = [
    "FULL_3D",
    "LIGHTWEIGHT_3D",
    "SUPPORTED_GLTF_VERSION",
    "THREE_D_PACKAGE_SCHEMA_VERSION",
    "THREE_D_RENDERER_API_VERSION",
]
