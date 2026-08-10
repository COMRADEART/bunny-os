# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Desktop actions: a small, bounded set of things the companion may do to a desk.

Every other subsystem in this package produces *information* — text, speech, a
transcript, a drawn character. This one produces **effects**, and an effect on a
person's desktop cannot be taken back by deleting a record. So the shape of this
package is decided by what must be impossible rather than by what is convenient.

**There is no general execution surface anywhere in here.** No shell, no
subprocess of a provider's choosing, no arbitrary D-Bus destination, no synthetic
input, no pixel automation, no screen reading. Each of those is absent as a
*structure* rather than as a check: :mod:`~companion.desktop.adapters` contains
one typed adapter per declared operation, each of which can express exactly the
call it declares and has no parameter through which another call could be
smuggled. A provider that wanted to run ``rm -rf`` would have to find a field to
put it in, and there is none.

**A provider never reaches this package.** The route is fixed and one-way::

    provider tool proposal
      -> canonical PlannedOperation      (companion.executor)
      -> ToolBroker validation           (companion.tools)
      -> approval derivation and binding (companion.approvals, .binding)
      -> DesktopActionRequest            (.request)
      -> DesktopActionBroker             (.broker)
      -> one typed adapter               (.adapters)
      -> DesktopActionResult             (.result)
      -> canonical task event            (companion.runtime)

:mod:`companion.desktop_bridge` is the only seam, and it lives *outside* this
package for the same reason :mod:`companion.capability_bridge` and
:mod:`companion.agent_bridge` do: "this subsystem holds no task authority" stays
checkable by reading one directory. Nothing under ``companion/desktop/`` imports
the runtime, the store, the task model, the approval gate or the broker; the
authority facts arrive as *values* on a request that has already been validated.

**A backend that answered is not a desk that changed.** §12's result vocabulary
separates ``confirmed`` — something was read back and matched — from
``accepted-not-confirmed``, which is all a notification daemon returning an id
actually proves. The temptation to collapse them is the whole reason they are
two words: a companion that reports success it did not observe teaches a user to
stop checking.

Module map:

:mod:`~companion.desktop.catalogue`
    §4's eight actions and §6's descriptors, with the seven-word standing
    ladder — declared, available, eligible, approved, executing, completed,
    undone — and the reason a declared action is not an available one.
:mod:`~companion.desktop.parameters`
    §3's per-action parameter schemas. ``additionalProperties: false``
    everywhere, and normalisation that is part of the schema rather than
    applied afterwards, so what is approved is what is executed.
:mod:`~companion.desktop.uris`, :mod:`~companion.desktop.paths`,
:mod:`~companion.desktop.entries`
    The three validators that carry the weight: a scheme allowlist that
    refuses ``javascript:`` and ``data:``, canonical path resolution under
    approved roots with symlinks resolved before the check, and desktop-entry
    resolution that reads only installed entries and never a provider's path.
:mod:`~companion.desktop.request` / :mod:`~companion.desktop.result`
    The versioned request, and the seven result states with the observation
    that justifies each.
:mod:`~companion.desktop.binding` / :mod:`~companion.desktop.idempotency`
    §8's approval binding — every field an approval is granted against, in one
    digest — and §9's derived key, which is what makes "this already happened"
    answerable after a restart.
:mod:`~companion.desktop.environment`
    §16 and §17: what the session actually supports, read from the capability
    plan and the live session rather than inferred from installed binaries.
:mod:`~companion.desktop.ledger`
    §20's durable operation ledger. An action interrupted mid-flight is
    ``unknown``, and ``unknown`` is never automatically repeated.
:mod:`~companion.desktop.undo`
    §11's classification, and the rule that undo is a *new* action with its own
    approval, lifecycle and audit record.
:mod:`~companion.desktop.broker`
    The one place an action attempt is owned, from revalidation to result.
:mod:`~companion.desktop.service`
    §21's six narrow protocol operations, and nothing generic.
"""

from __future__ import annotations

__all__ = [
    "DESKTOP_ACTION_SCHEMA_VERSION",
]

#: The version every :class:`companion.desktop.request.DesktopActionRequest`
#: carries. Bumped when a parameter schema changes shape, because a request
#: validated against one schema and executed against another is exactly the
#: drift §3 exists to prevent.
DESKTOP_ACTION_SCHEMA_VERSION = 1
