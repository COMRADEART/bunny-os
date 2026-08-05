# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The plan applicator: turning a decision into operating-system actions.

:mod:`capability` decides what *should* run. This package decides what to *do*
about the difference between that and what is running, and it is the only place
in Bunny OS that is allowed to act on a machine.

The two halves are deliberately separated by a value. ``capability`` produces an
:class:`~capability.plan.ExecutionPlan`, which is a document; ``capability.apply``
consumes one. Nothing here re-derives a decision, and nothing here may decide
that a service the engine refused is eligible after all. That rule has a name in
this package — the **decision boundary** — and it is enforced structurally:
the applicator never sees an inventory it could re-plan from without also seeing
the plan that inventory produced, and every function that could widen a grant
takes the plan's figure as a ceiling rather than as a suggestion.

What the applicator *is* allowed to decide is operational:

* that a plan is too old, or has been superseded, and must not be applied;
* that the machine changed between the decision and the act, so the transition
  must be abandoned and a fresh decision requested;
* that a service failed to start and its resources must be given back;
* that a unit name is not one Bunny OS is authorised to control;
* that stopping a service now would destroy work a person is in the middle of;
* that a service has failed so often that retrying it is no longer useful.

Every one of those is a refusal, a delay or an undo. None of them starts
anything the plan did not ask for. The asymmetry is the safety property:
**the applicator can always say no, and can never say yes.**

The pipeline this package implements sits underneath the capability pipeline::

    desired execution plan
        -> plan validation          (identity.py, revalidate.py)
        -> state reconciliation     (reconcile.py)
        -> operating-system backend (backends.py, systemd.py, cgroup.py)
        -> observed actual state    (state.py)
        -> runtime monitoring       (monitor.py)
        -> reevaluation request     (back into capability.engine)

**Nothing in this package runs by default.** The default backend is
:class:`~capability.apply.backends.DryRunBackend`, which records what it would
have done and touches nothing. Modifying host services requires an explicit,
separately-named opt-in at every layer: a backend that was constructed for it,
an authorisation allowlist that names the unit, and a CLI flag that says so.
A developer checkout cannot stop a developer's services by accident, because
there is no default code path in which it tries.
"""

from __future__ import annotations

#: Version of the execution plan document this package can apply. Plans that
#: declare anything else are rejected rather than interpreted: a plan whose
#: identity block this code does not understand is a plan whose staleness this
#: code cannot check.
SUPPORTED_PLAN_SCHEMA_VERSION = 2

#: Version of the runtime state document (``schemas/service-runtime-state.schema.json``).
RUNTIME_STATE_SCHEMA_VERSION = 1

#: Version of the audit record envelope (``schemas/runtime-audit-record.schema.json``).
AUDIT_SCHEMA_VERSION = 1

__all__ = [
    "AUDIT_SCHEMA_VERSION",
    "RUNTIME_STATE_SCHEMA_VERSION",
    "SUPPORTED_PLAN_SCHEMA_VERSION",
]
