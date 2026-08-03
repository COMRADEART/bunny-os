# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Bunny OS capability runtime.

This package is the implementation of three components named in
``docs/phase-1/BUNNY_OS_PHASE_1.md`` §7: the **Hardware Capability Service**
(detection), the **Budget Service** (how much may safely be consumed), and the
**Capability Router** (which implementation runs, and where). The
**Capability Registry** is the manifest catalogue they read.

It exists to satisfy constitutional requirement C11 — *One Bunny, honest about
capability*:

    No editions. Capability negotiated per task from detected resources.
    [...] a profile keyed on a product tier fails review.

So there is no low/balanced/high/ultra anything here, and there must never be.
A constrained device does not receive a smaller Bunny OS; it receives the same
Bunny OS running fewer things locally, and saying which and why. §13.9 of the
same document draws the line this package implements: *identical at every
capability level* are the intent vocabulary, permission model, plan, history,
controls and every disclosure surface; *may adapt* are animation quality, model
size, concurrency, context length, background processing, caching, sandbox
density and the routing mix.

The pipeline is one direction, and each stage is a pure function of the stage
before it plus configuration:

    discovery -> inventory -> scores -> budgets -> policy -> plan -> adaptation

Only ``capability.discovery`` touches the machine. Everything downstream of it
is deterministic on its inputs, which is what makes the simulated-hardware tests
in ``tests/capability`` meaningful rather than decorative.
"""

from __future__ import annotations

#: Version of the capability inventory document (``schemas/capability-inventory.schema.json``).
INVENTORY_SCHEMA_VERSION = 1

#: Version of the service capability manifest (``schemas/service-capability-manifest.schema.json``).
MANIFEST_SCHEMA_VERSION = 1

#: Version of the resource budget document (``schemas/resource-budget.schema.json``).
BUDGET_SCHEMA_VERSION = 1

#: Version of the execution plan document (``schemas/execution-plan.schema.json``).
PLAN_SCHEMA_VERSION = 1

__all__ = [
    "BUDGET_SCHEMA_VERSION",
    "INVENTORY_SCHEMA_VERSION",
    "MANIFEST_SCHEMA_VERSION",
    "PLAN_SCHEMA_VERSION",
]
