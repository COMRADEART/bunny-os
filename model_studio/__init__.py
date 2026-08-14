# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bunny Model Studio: the training side of Bunny OS, and nothing else.

Bunny OS has two AI paths and they meet in exactly one place — a directory on
disk. This package is the first one:

    dataset -> config -> preflight -> plan -> training -> adapter + provenance
                                                            |
    ------------------------------------------------------- | ----------------
                                                            v
    Bunny OS runtime: local inference, Companion, actions, approvals, capsules

The separation is not a convention in this repository, it is a build property.
``build/scripts/install_routes.py`` holds the single declaration of what reaches
the image; ``companion``, ``capsules``, ``trust``, ``catalog`` and ``capability``
each have a route there and this package deliberately has none. A package with
no route cannot be installed, so training code cannot become part of the
privileged Companion execution path by accident — it would take a new install
route, which is a reviewed edit to a file whose whole purpose is that nobody
adds one without noticing. :mod:`tests.model_studio.test_isolation` asserts the
absence, both directions: no install route resolves a path here, and nothing
here imports the runtime.

What that buys, concretely: the Companion's privileged surface does not grow by
one byte because someone fine-tuned a model, and an image built from a commit
that added a trainer is byte-identical to one built from the commit before it.

Three rules the shape enforces, rather than asks for:

**Nothing here reaches the network unless it was told to.** The default policy
is :data:`model_studio.network.OFFLINE`; it sets the offline environment for
every subprocess and library that would otherwise phone home, and the only
operation that may lift it is a base-model download the caller explicitly
approved. There is no upload code path at all — not a disabled one, not one
behind a flag — and a test greps this package's source to keep it that way.

**Nothing claims a number it did not obtain.** Hardware facts are tri-state
(:data:`model_studio.hardware.probe.SUPPORTED`, ``UNSUPPORTED``, ``UNKNOWN``)
and estimates carry the formula that produced them. A machine whose VRAM cannot
be read reports ``UNKNOWN`` and the plan is refused; it never reports a
plausible number.

**A job that stopped is never a job that finished.** ``completed`` is written by
exactly one transition, from ``evaluating``, in :mod:`model_studio.jobs.state`.
A record found in an active state whose owning process is gone is recovered to
``failed``, because the alternative — trusting a state file written before a
power cut — is how a half-trained adapter becomes a released one.
"""

from __future__ import annotations

#: Bumped when a persisted job record, provenance record or configuration
#: document changes shape in a way a reader has to know about.
STUDIO_SCHEMA_VERSION = 1

#: The name this subsystem records in provenance and job records.
STUDIO_NAME = "bunny-model-studio"

__all__ = ["STUDIO_NAME", "STUDIO_SCHEMA_VERSION"]
