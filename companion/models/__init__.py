# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The runtime side of the model bridge: validate, register, apply, fall back.

Bunny OS trains nothing. Bunny Model Studio trains outside the image and cannot
reach it — it has no install route, and
``tests/model_bridge/test_build_isolation.py`` asserts that in both directions.
What crosses the boundary is a *directory*: an adapter, a manifest, and digests.
This package is what stands on the runtime side of that boundary and decides
whether the directory may be used at all.

The one rule everything here exists to hold::

    MODEL OUTPUT IS NOT AUTHORITY

A model may suggest which of :data:`companion.capsule_tasks.OPERATIONS` applies.
It cannot add an operation, alter one, or arrive carrying a permission. Neither
can the file it shipped in: :mod:`companion.models.validation` refuses a
manifest whose ``permissions`` array is non-empty, with a named code, rather
than ignoring a field it does not use. The authority path is unchanged and
untouched by this package — ``ToolBroker`` → ``capsule_tasks.OPERATIONS`` →
``TrustGate`` → the user → the capsule — and nothing here is on it.

**What "loading" means here, and why it is not what it sounds like.** Bunny's
inference is out-of-process: every provider adapter in :mod:`companion.agents`
is a client of a loopback server or an allowlisted subprocess, and the image
packages no inference runtime at all. So this package does not import a tensor
library, and adding one to load an adapter would be the wrong trade — see
:mod:`companion.models.inference`. It resolves a validated artifact to a path
inside a trusted directory, asks a backend that *declares* it can apply that
format to apply it, and then **verifies with the backend that it was applied**.
A backend that cannot confirm leaves the model inactive.

**Three outcomes, and the third is the point.** Validation returns ``PASS``,
``FAIL`` or ``UNKNOWN``, the same discipline Model Studio's preflight uses.
``UNKNOWN`` is not a pass: an adapter whose base revision cannot be verified,
or whose base weights are not on this machine, is not activated on the grounds
that nothing said no.
"""

from __future__ import annotations

#: Bumped with ``schemas/bunny-model-artifact.schema.json``.
ARTIFACT_SCHEMA_VERSION = 1

#: The manifest's file name inside an artifact directory.
MANIFEST_FILE_NAME = "bunny-model-manifest.json"

__all__ = ["ARTIFACT_SCHEMA_VERSION", "MANIFEST_FILE_NAME"]
