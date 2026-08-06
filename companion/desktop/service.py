# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The §21 operations: list, status, explain, cancel, undo, history.

Six operations, validated against the same
:data:`companion.protocol.DESKTOP_OPERATIONS` objects the wire validates
against, so the schema a client is checked by and the schema this service serves
are one table read twice — the arrangement the voice, speech and provider
services already have.

**What is not here is the point.** There is no operation that performs a desktop
action. A client can ask what exists, what the machine can do, what one action
means, and can stop or undo something already under way — and the only route to
*causing* an effect is a task whose plan proposes one and a person who approves
it. An operation taking an action id and a parameter object would be a generic
tool invocation with a narrow name, and it would let a client walk past §2's
whole pipeline: no plan, no operation identity, no approval binding, no ledger.

Nor is there a parameter anywhere that names an application, a path, a URI, a
command, a bus destination or a backend object. Every identifier these
operations accept refers to something the runtime already holds: an action id
from the declared catalogue, a request id from an attempt in flight, an
idempotency key from the ledger, a task id.

``desktop_action_undo`` is the one that looks like an exception and is not. It
takes a ledger key and derives the undo from what that entry *recorded* —
:func:`companion.desktop.undo.undo_plan_for` reads the previous state that was
observed before the change. The caller supplies no value to restore, so an undo
cannot be used to set a volume to an arbitrary number. Where the plan requires
approval, this operation returns the plan and does not execute it: the approval
goes through the canonical gate like every other, and §11's "an undo is a new
typed action with its own lifecycle" would not survive a service that just did
it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..protocol import DESKTOP_OPERATIONS, UnknownOperation
from .broker import DesktopActionBroker
from .catalogue import ACTION_IDS, DEFERRED_ACTIONS
from .errors import DesktopActionError

__all__ = ["DesktopActionService"]


@dataclass
class DesktopActionService:
    """A read-mostly view of the desktop broker, for the local protocol."""

    broker: DesktopActionBroker

    # -- the protocol surface ----------------------------------------------

    def serve(self, operation: str, parameters: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Validate and answer one operation, or refuse it by name.

        Validation is :meth:`companion.protocol.Operation.validate`, which
        refuses an undeclared parameter rather than ignoring it. §21 asks for
        that explicitly, and the reason is the same one
        :mod:`companion.protocol` gives: an ignored parameter is one a caller
        believes took effect.
        """
        declared = DESKTOP_OPERATIONS.get(operation)
        if declared is None:
            raise UnknownOperation(
                f"{operation!r} is not a desktop-action operation; this service serves "
                f"{', '.join(sorted(DESKTOP_OPERATIONS))}"
            )
        resolved = declared.validate(dict(parameters or {}))
        handler = getattr(self, "_" + operation)
        return handler(resolved)

    @staticmethod
    def boundaries() -> dict[str, bool]:
        """What this service cannot do, stated as data and asserted false.

        The same shape :class:`companion.agents.service.AgentProviderService`
        uses. A structural test reads it, so a boundary that stopped being true
        would have to be edited here — where somebody would notice — rather than
        quietly stop holding.
        """
        return {
            "performsActions": False,
            "resolvesApprovals": False,
            "createsTasks": False,
            "acceptsArbitraryParameters": False,
            "invokesTools": False,
            "reachesDbusDirectly": False,
            "runsSubprocesses": False,
            "readsClipboard": False,
            "capturesScreen": False,
            "returnsBackendHandles": False,
        }

    # -- handlers ----------------------------------------------------------

    def _desktop_actions_list(self, _parameters: Mapping[str, Any]) -> dict[str, Any]:
        """Every declared action, its descriptor, and its current standing."""
        return {
            "actions": list(self.broker.declared()),
            "deferred": [
                {"actionId": action_id, "reason": reason}
                for action_id, reason in sorted(DEFERRED_ACTIONS.items())
            ],
            "declaredCount": len(ACTION_IDS),
        }

    def _desktop_actions_status(self, _parameters: Mapping[str, Any]) -> dict[str, Any]:
        """The posture, the counters, and what still needs a decision."""
        return self.broker.status()

    def _desktop_action_explain(self, parameters: Mapping[str, Any]) -> dict[str, Any]:
        action_id = str(parameters["actionId"])
        try:
            return self.broker.explain(action_id)
        except DesktopActionError as exc:
            # A deferred action reaches here with the sentence saying it is
            # deliberately absent, which is the answer §5 asks for — a typed
            # UNSUPPORTED rather than "unknown action".
            return {
                "actionId": action_id,
                "declared": False,
                "deferred": action_id in DEFERRED_ACTIONS,
                "explanation": str(exc),
            }

    def _desktop_action_cancel(self, parameters: Mapping[str, Any]) -> dict[str, Any]:
        outcome = self.broker.cancel(
            request_id=str(parameters.get("requestId") or ""),
            cancellation_token=str(parameters.get("cancellationToken") or ""),
        )
        return {
            **outcome,
            # Said plainly, because it is the thing a person cancelling wants to
            # know and the thing §10 forbids being vague about.
            "note": (
                "a cancellation stops what has not happened. Anything the backend had already "
                "accepted is recorded as it actually is, and no rollback is claimed unless it "
                "was verified."
            ),
        }

    def _desktop_action_undo(self, parameters: Mapping[str, Any]) -> dict[str, Any]:
        key = str(parameters["idempotencyKey"])
        plan = self.broker.undo_plan(key)
        if not plan.available:
            return {"key": key, "undo": plan.to_json(), "performed": False}
        if plan.kind == "compensate":
            # The one undo that needs no new approval: it withdraws a disclosure
            # rather than making one. See companion.desktop.undo.
            outcome = self.broker.compensate(key, reason="undo requested")
            return {"key": key, "undo": plan.to_json(), "performed": True, "outcome": outcome}
        # A reversal is a new action with its own approval. Returned as a plan
        # for the caller to submit; performing it here would give the service
        # the ability to cause an effect, which is the one thing §21 keeps off
        # this surface.
        return {
            "key": key,
            "undo": plan.to_json(),
            "performed": False,
            "note": (
                "undoing this is a new action with its own approval. Submit it as a task "
                "operation; this surface does not perform desktop actions."
            ),
        }

    def _desktop_action_history(self, parameters: Mapping[str, Any]) -> dict[str, Any]:
        entries = self.broker.history(
            task_id=str(parameters.get("taskId") or ""),
            limit=int(parameters.get("limit") or 25),
        )
        return {"entries": list(entries), "count": len(entries)}
