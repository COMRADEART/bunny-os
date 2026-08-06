# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The one place a desktop action attempt is owned, from revalidation to result.

§2's pipeline arrives here already validated: the parameters passed a closed
schema, the URI passed an allowlist, the path resolved inside an approved root,
and a person answered a question about the exact normalised act. What is left is
the part that has to be right *at the moment of the effect*, and it is the part
a check made earlier cannot cover:

1. **is this still the approved act?** :meth:`~companion.desktop.binding.ApprovalBinding.require_match`
   against the binding recorded when consent was given. Every §8 condition
   except two lives there;
2. **has this approval already been spent?** the two that do not: a replayed
   approval, caught by :attr:`DesktopActionBroker.consumed`, and an act already
   completed, caught by the ledger;
3. **is the task still running?** cancellation is re-read rather than remembered.
   A stop can arrive from another process while this one is between two lines;
4. **has consent expired?** on the monotonic clock, and the attempt's own
   deadline is clamped below it so an act cannot finish after the consent for it
   ran out;
5. **write the attempt down before making it.** §20's whole recovery story is
   that a ``started`` entry from a dead run becomes ``unknown`` — which requires
   the entry to exist before the process could die.

Then one adapter call, one observation, one result, one ledger update.

**Exactly one invocation owns an attempt.** :attr:`DesktopActionBroker._inflight`
is keyed by idempotency key and the entry is taken before anything else happens,
so two threads proposing the same act produce one attempt and one refusal rather
than two acts. That is stronger than the ledger check alone: the ledger is
durable and therefore slow, and two threads can both read "not started" from it.

**Nothing here decides whether consent was given.** The broker is handed a
binding that was already approved and checks the current act against it; it has
no approval store, no consent source and no way to grant anything. §1 says the
desktop broker may not resolve approvals, and the way that is kept is that it
has nothing to resolve one with.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
import threading
import time
from typing import Any, Mapping, Sequence

from ..clock import Clock, SystemClock, iso8601
from ..errors import CompanionError
from .adapters.clipboard import ClipboardHold
from .adapters.dbus import GioCancellable
from .binding import ApprovalBinding
from .catalogue import ACTION_IDS, DESCRIPTORS, descriptor_for
from .environment import DesktopAdapters, DesktopEnvironmentReport, probe_environment
from .errors import (
    DesktopActionError,
    DesktopAlreadyPerformed,
    DesktopApprovalMismatch,
    DesktopCancelled,
    DesktopEffectUnknown,
    DesktopRefused,
    DesktopSchemaError,
    DesktopUnavailable,
    DesktopUnsupported,
)
from .idempotency import retry_policy_for
from .ledger import LedgerEntry, OperationLedger
from .parameters import NormalisedAction, normalise
from .paths import PathContext
from .request import DesktopActionRequest
from .result import DesktopActionResult, Observation, refused, unsupported
from .undo import UndoPlan, undo_plan_for

__all__ = [
    "BrokerOptions",
    "DesktopActionBroker",
    "PreparedAction",
]


@dataclass
class BrokerOptions:
    """How one broker is configured. Everything injectable, nothing implicit."""

    #: Where the durable ledger lives. ``None`` keeps it in memory, which the
    #: unit tests use and the installed system never does.
    ledger_path: Path | None = None
    adapters: DesktopAdapters | None = None
    clock: Clock = field(default_factory=SystemClock)
    #: How long a desktop approval stands. Short, and shorter than the general
    #: companion default: a desk changes while a person is looking away from it,
    #: and consent to "set the volume to 50%" is consent to do it now.
    approval_ttl_seconds: float = 300.0
    #: §17: opening a URI with no graphical session. Off unless a policy says on.
    headless_uri_policy: bool = False
    #: The user's accessibility preferences, duck-typed. See
    #: :func:`companion.desktop.environment.probe_environment`.
    accessibility: Any = None
    #: The capability plan's signals, recorded on the environment report so a
    #: decision and its explanation come from one measurement.
    capability_signals: Mapping[str, Any] = field(default_factory=dict)
    #: How long an environment probe stays fresh. Re-probing on every action
    #: would put a bus round trip into every latency figure; never re-probing
    #: would miss a display appearing.
    probe_ttl_seconds: float = 30.0


@dataclass(frozen=True)
class PreparedAction:
    """A validated, described, not-yet-approved attempt.

    The object the ToolBroker takes an approval against. It carries the binding
    the answer will be bound to, so the question and the check are built from
    one thing — which is the property §8 needs and the thing a second
    construction would break.
    """

    request: DesktopActionRequest
    action: NormalisedAction
    binding: ApprovalBinding
    #: The undo that will be available if this succeeds, described in advance so
    #: the approval prompt can say whether it can be taken back (§18).
    undo_preview: str = ""
    #: What the environment said about this action when it was prepared.
    availability_detail: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "request": self.request.to_json(),
            "action": self.action.to_json(),
            "bindingDigest": self.binding.digest,
            "undoPreview": self.undo_preview,
            "availabilityDetail": self.availability_detail,
        }

    def to_prompt_json(self) -> dict[str, Any]:
        """§18's fields, and only those. What an approval centre renders."""
        descriptor = DESCRIPTORS[self.request.action_id]
        return {
            "actionId": self.request.action_id,
            "presentation": self.request.presentation,
            "target": self.request.target,
            "targetKind": self.request.target_kind,
            "disclosure": self.request.disclosure,
            "expectedEffect": self.request.expected_effect,
            "classification": self.request.classification,
            "reversibility": self.request.reversibility,
            "undoAvailable": bool(self.undo_preview),
            "undoDescription": self.undo_preview,
            "approvalClass": self.request.approval_class,
            "parameters": dict(self.request.parameters),
            "resourceImpact": descriptor.resource_impact,
            "knownLimitations": list(descriptor.known_limitations),
        }


@dataclass
class _Scope:
    """One attempt's live resources, so a cancel has something to act on."""

    request_id: str
    key: str
    cancellable: GioCancellable
    clipboard_hold: ClipboardHold | None = None
    notification_id: int = 0
    started_monotonic: float = 0.0


class DesktopActionBroker:
    """Accept a validated request, perform one bounded action, report honestly."""

    def __init__(self, options: BrokerOptions | None = None) -> None:
        self.options = options or BrokerOptions()
        self.clock = self.options.clock
        self.adapters = self.options.adapters or DesktopAdapters()
        self.ledger = (
            OperationLedger.load(self.options.ledger_path)
            if self.options.ledger_path is not None
            else OperationLedger()
        )
        #: (task, operation, binding digest) triples already spent this run. An
        #: approval authorises one act; presenting the same one for a second act
        #: is the replay this set exists to catch. In memory, because a run is
        #: the lifetime of the monotonic clock the expiry is measured on — and
        #: because a restarted runtime reuses no approval at all.
        self.consumed: set[tuple[str, str, str]] = set()
        self._guard = threading.RLock()
        self._inflight: dict[str, _Scope] = {}
        self._by_request: dict[str, _Scope] = {}
        self._environment: DesktopEnvironmentReport | None = None
        self._probed_at: float = 0.0
        self._started = False
        #: What loading the ledger had to reclassify, surfaced rather than
        #: swallowed. §20's "require a new decision for uncertain actions" is a
        #: sentence somebody has to be shown.
        self.recovery_warnings: tuple[str, ...] = self.ledger.warnings

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> "DesktopActionBroker":
        """Probe once, release anything a previous run left, and be ready.

        The release is §20's "clear stale portal handles" and "release temporary
        clipboard ownership". Both are trivially satisfied across a *process*
        restart — a portal handle belongs to a connection and a selection
        belongs to a process — so what this actually clears is the in-process
        case: a broker restarted inside a living service.
        """
        with self._guard:
            if self._started:
                return self
            self._started = True
        self.adapters.release_all("a new broker run is starting")
        self.environment(refresh=True)
        return self

    def stop(self) -> dict[str, int]:
        """Release everything and report what was still held.

        A non-zero count here at the end of a gate iteration is the leak §23 is
        looking for, which is why it is returned rather than logged.
        """
        with self._guard:
            scopes = list(self._inflight.values())
            self._inflight.clear()
            self._by_request.clear()
            self._started = False
        for scope in scopes:
            scope.cancellable.cancel()
        released = self.adapters.release_all("the broker is stopping")
        self.adapters.close()
        return released

    def __enter__(self) -> "DesktopActionBroker":
        return self.start()

    def __exit__(self, *_exc: object) -> None:
        self.stop()

    # -- environment -------------------------------------------------------

    def environment(self, *, refresh: bool = False) -> DesktopEnvironmentReport:
        now = self.clock.monotonic()
        with self._guard:
            fresh = (
                self._environment is not None
                and not refresh
                and (now - self._probed_at) < self.options.probe_ttl_seconds
            )
            if fresh:
                assert self._environment is not None
                return self._environment
        report = probe_environment(
            self.adapters,
            accessibility=self.options.accessibility,
            capability_signals=self.options.capability_signals,
            headless_uri_policy=self.options.headless_uri_policy,
            monotonic=self.clock.monotonic,
        )
        with self._guard:
            self._environment = report
            self._probed_at = now
        return report

    def declared(self) -> tuple[dict[str, Any], ...]:
        """Every declared action with its current standing (§6, §21)."""
        report = self.environment()
        return tuple(
            {
                **DESCRIPTORS[action_id].to_json(),
                "standing": "available" if report.permits(action_id) else "declared",
                "available": report.permits(action_id),
                "unavailableReason": report.reason(action_id),
                "retry": retry_policy_for(action_id).to_json(),
            }
            for action_id in ACTION_IDS
        )

    # -- preparation -------------------------------------------------------

    def prepare(
        self,
        action_id: str,
        parameters: Mapping[str, Any],
        *,
        request_id: str,
        session_id: str,
        task_id: str,
        lifecycle_epoch: int,
        plan_id: str,
        operation_id: str,
        cancellation_token: str,
        classification: str = "internal",
        path_context: PathContext | None = None,
        audit_reference: str = "",
        undo_of: str = "",
    ) -> PreparedAction:
        """Validate, describe, and build the request an approval will bind to.

        Reads the machine where §18 needs it to: the current volume and the
        current do-not-disturb value are fetched *here*, so the prompt can say
        "from 35% to 50%" and so the previous state that an undo would restore
        was observed before the change rather than reconstructed after it.

        **Availability is recorded here and enforced at execution.** Preparing
        an action the machine cannot perform is not an error: the schema check,
        the classification ceiling, the URI allowlist and the path resolution
        all still apply and still refuse what they refuse, and the request that
        comes out is a complete, checkable description of an act that will
        report ``unsupported``. Refusing at preparation instead was the first
        version and it was worse in the direction that matters — it turned a
        headless machine into a *planning* failure, so the run had no request to
        bind, no prompt to render and no typed result to record, and the honest
        sentence §17 asks for never reached the task's history.
        """
        descriptor = descriptor_for(action_id)
        report = self.environment()
        observed = self._observe_before(action_id, parameters)
        application_name = ""
        if action_id in ("desktop.application.launch", "desktop.application.present"):
            application_name = self._application_name(parameters.get("applicationId", ""))

        action = normalise(
            action_id,
            parameters,
            classification=classification,
            path_context=path_context,
            application_name=application_name,
            observed_state=observed,
        )
        request = DesktopActionRequest.build(
            action,
            request_id=request_id,
            session_id=session_id,
            task_id=task_id,
            lifecycle_epoch=lifecycle_epoch,
            plan_id=plan_id,
            operation_id=operation_id,
            cancellation_token=cancellation_token,
            wall_now=self.clock.wall(),
            monotonic_now=self.clock.monotonic(),
            approval_ttl_seconds=self.options.approval_ttl_seconds,
            audit_reference=audit_reference,
            undo_of=undo_of,
        )
        return PreparedAction(
            request=request,
            action=action,
            binding=request.binding,
            undo_preview=_undo_preview(descriptor, action),
            availability_detail=(
                _availability_detail(report, action_id)
                if report.permits(action_id)
                else report.reason(action_id)
            ),
        )

    def _observe_before(self, action_id: str, parameters: Mapping[str, Any]) -> dict[str, Any]:
        """The state that will be changed, read before anybody is asked about it.

        Failure to read is not an error here. It produces a prompt without a
        "from" value and an entry without a previous state, which
        :func:`companion.desktop.undo.undo_plan_for` correctly reads as "no undo
        available" — the honest consequence rather than an exception.
        """
        if action_id == "desktop.audio.set-volume":
            requested = str(parameters.get("outputId") or "")
            output = self.adapters.audio.read(requested)
            if output is None:
                return {}
            return {
                "outputId": output.output_id,
                "outputName": output.display_name,
                "percent": output.percent,
                "muted": output.muted,
            }
        if action_id == "desktop.notifications.set-do-not-disturb":
            value = self.adapters.settings.read_do_not_disturb()
            return {} if value is None else {"enabled": value}
        return {}

    def _application_name(self, application_id: Any) -> str:
        from .entries import resolve_application

        if not isinstance(application_id, str) or not application_id:
            return ""
        try:
            return resolve_application(application_id).display_name
        except DesktopActionError:
            # The refusal belongs to normalisation, which produces a message
            # about the identifier. Swallowing it here only costs a nicer name.
            return ""

    # -- execution ---------------------------------------------------------

    def execute(
        self,
        request: DesktopActionRequest,
        *,
        approved_binding: ApprovalBinding | None = None,
        path_context: PathContext | None = None,
        cancelled: Any = None,
    ) -> DesktopActionResult:
        """Perform one approved action. The only method that causes an effect.

        ``cancelled`` is a zero-argument callable the broker re-reads at each
        checkpoint. It is a callable rather than a flag because a stop can
        arrive from another process — ``bunny-os companion task cancel`` while
        this one is running — and a flag captured at entry would not see it.
        """
        started = self.clock.monotonic()
        descriptor = descriptor_for(request.action_id)

        try:
            self._authorise(request, approved_binding, cancelled)
        except DesktopCancelled as exc:
            return self._cancelled_result(request, exc, started)
        except DesktopAlreadyPerformed as exc:
            recorded = exc.recorded
            if isinstance(recorded, dict) and recorded:
                # The recorded result, returned unchanged. A fresh claim about
                # an act performed by an earlier attempt would be a claim
                # nothing observed.
                return _result_from_json(recorded)
            return DesktopActionResult(
                request_id=request.request_id,
                action_id=request.action_id,
                idempotency_key=request.idempotency_key,
                state="accepted-not-confirmed",
                observation=Observation(
                    "acknowledgement", detail="a previous attempt of this exact act completed"
                ),
                explanation=str(exc),
                target=request.target,
                target_kind=request.target_kind,
            )
        except DesktopEffectUnknown as exc:
            return DesktopActionResult(
                request_id=request.request_id,
                action_id=request.action_id,
                idempotency_key=request.idempotency_key,
                state="unknown",
                observation=Observation("none", detail="the earlier attempt was never settled"),
                explanation=str(exc),
                target=request.target,
                target_kind=request.target_kind,
                notes=(retry_policy_for(request.action_id).explanation,),
            )
        except DesktopUnsupported as exc:
            return unsupported(
                request_id=request.request_id, action_id=request.action_id,
                idempotency_key=request.idempotency_key, explanation=str(exc),
                target=request.target, target_kind=request.target_kind,
            )
        except DesktopUnavailable as exc:
            return unsupported(
                request_id=request.request_id, action_id=request.action_id,
                idempotency_key=request.idempotency_key, explanation=str(exc),
                target=request.target, target_kind=request.target_kind,
            )
        except DesktopActionError as exc:
            return refused(
                request_id=request.request_id, action_id=request.action_id,
                idempotency_key=request.idempotency_key, explanation=str(exc),
                target=request.target, target_kind=request.target_kind,
            )

        scope = self._claim(request)
        entry = LedgerEntry(
            key=request.idempotency_key,
            action_id=request.action_id,
            task_id=request.task_id,
            session_id=request.session_id,
            lifecycle_epoch=request.lifecycle_epoch,
            plan_id=request.plan_id,
            operation_id=request.operation_id,
            state="started",
            binding_digest=request.binding.digest,
            target=request.target,
            target_kind=request.target_kind,
            request_id=request.request_id,
            started_at=iso8601(self.clock.wall()),
        )
        try:
            # Durable *before* the effect. This is the whole of §20's recovery.
            self.ledger.begin(entry)
        except DesktopSchemaError as exc:
            self._release(scope)
            return refused(
                request_id=request.request_id, action_id=request.action_id,
                idempotency_key=request.idempotency_key, explanation=str(exc),
                target=request.target, target_kind=request.target_kind,
            )

        try:
            result = self._dispatch(request, scope, path_context=path_context, cancelled=cancelled)
        except DesktopCancelled as exc:
            result = self._cancelled_result(request, exc, started)
        except DesktopUnsupported as exc:
            result = unsupported(
                request_id=request.request_id, action_id=request.action_id,
                idempotency_key=request.idempotency_key, explanation=str(exc),
                target=request.target, target_kind=request.target_kind,
            )
        except DesktopActionError as exc:
            result = DesktopActionResult(
                request_id=request.request_id,
                action_id=request.action_id,
                idempotency_key=request.idempotency_key,
                state=exc.result_state if exc.result_state in ("refused", "failed", "unsupported") else "failed",
                observation=Observation("error", detail=str(exc)),
                explanation=str(exc),
                target=request.target,
                target_kind=request.target_kind,
            )
        except Exception as exc:  # an adapter is code; its faults are data
            # Deliberately `unknown` and not `failed`. An exception between the
            # backend call and the observation leaves the effect genuinely
            # undetermined, and §12 has a word for that.
            result = DesktopActionResult(
                request_id=request.request_id,
                action_id=request.action_id,
                idempotency_key=request.idempotency_key,
                state="unknown",
                observation=Observation("none", detail=f"{type(exc).__name__}: {exc}"),
                explanation=(
                    "the attempt was interrupted by an error and whether the desktop changed is "
                    "not known"
                ),
                target=request.target,
                target_kind=request.target_kind,
                notes=(retry_policy_for(request.action_id).explanation,),
            )
        finally:
            self._release(scope)

        result = replace(result, duration_seconds=max(0.0, self.clock.monotonic() - started))
        self._settle(request, result, descriptor)
        return result

    # -- authority ---------------------------------------------------------

    def _authorise(
        self,
        request: DesktopActionRequest,
        approved_binding: ApprovalBinding | None,
        cancelled: Any,
    ) -> None:
        """§8, in the order the failures matter.

        Cancellation first: a task that has been stopped should be told that,
        not told its approval no longer matches. Then the identity of the act,
        then the freshness of the consent, then the ledger.
        """
        if cancelled is not None and cancelled():
            raise DesktopCancelled(
                "the task was cancelled before this action ran",
                effect_known=True, effect_prevented=True,
            )
        if not request.approved:
            raise DesktopRefused(
                f"{request.action_id} was not approved; no response means no action"
            )
        if approved_binding is None:
            raise DesktopRefused(
                "the act that was approved was not supplied, so this one cannot be checked "
                "against it"
            )
        # Every §8 field condition, with the sentence naming which one moved.
        approved_binding.require_match(request.binding)

        now = self.clock.monotonic()
        if request.expired(now):
            raise DesktopApprovalMismatch(
                "the approval for this action has expired; consent to act now is not consent later"
            )
        if request.past_deadline(now):
            raise DesktopRefused("this attempt is past its deadline and was not made")

        spent = (request.task_id, request.operation_id, approved_binding.digest)
        with self._guard:
            if spent in self.consumed:
                raise DesktopApprovalMismatch(
                    "this approval has already authorised this action; an approval authorises "
                    "one act and cannot be spent twice"
                )

        recorded = self.ledger.get(request.idempotency_key)
        if recorded is not None:
            if recorded.state in ("completed", "undone"):
                raise DesktopAlreadyPerformed(
                    f"this exact action already completed at {recorded.settled_at or 'an earlier time'} "
                    "and was not repeated",
                    recorded=dict(recorded.result),
                )
            if recorded.state == "unknown":
                raise DesktopEffectUnknown(
                    "an earlier attempt at this exact action began and nothing settled it; "
                    "whether the desktop changed is not known, so it was not repeated"
                )
            if recorded.state == "started":
                raise DesktopRefused(
                    "this exact action is already being attempted; one attempt owns an action"
                )

        with self._guard:
            self.consumed.add(spent)

    def _claim(self, request: DesktopActionRequest) -> _Scope:
        """Take ownership of this key, or refuse. One attempt, one owner."""
        scope = _Scope(
            request_id=request.request_id,
            key=request.idempotency_key,
            cancellable=GioCancellable(),
            started_monotonic=self.clock.monotonic(),
        )
        with self._guard:
            if request.idempotency_key in self._inflight:
                raise DesktopRefused(
                    "this exact action is already being attempted by another invocation"
                )
            self._inflight[request.idempotency_key] = scope
            self._by_request[request.request_id] = scope
        return scope

    def _release(self, scope: _Scope) -> None:
        with self._guard:
            self._inflight.pop(scope.key, None)
            self._by_request.pop(scope.request_id, None)

    # -- dispatch ----------------------------------------------------------

    def _dispatch(
        self,
        request: DesktopActionRequest,
        scope: _Scope,
        *,
        path_context: PathContext | None,
        cancelled: Any,
    ) -> DesktopActionResult:
        parameters = dict(request.parameters)
        action_id = request.action_id

        def checkpoint(where: str) -> None:
            if cancelled is not None and cancelled():
                scope.cancellable.cancel()
                raise DesktopCancelled(
                    f"the action was cancelled {where}", effect_known=True, effect_prevented=True
                )
            scope.cancellable.check(where)

        checkpoint("before the backend was reached")

        # §15 step 1, enforced here rather than at preparation. The environment
        # report is what answers it — a probe of the service, not a look at the
        # filesystem — and the sentence it returns is the one the user reads.
        report = self.environment()
        if not report.permits(action_id):
            raise DesktopUnsupported(report.reason(action_id))

        if action_id == "desktop.notification.show":
            outcome = self.adapters.notification.show(
                title=parameters["title"],
                body=parameters.get("body", ""),
                urgency=parameters.get("urgency", "normal"),
                timeout_ms=parameters.get("timeoutMs"),
                cancellable=scope.cancellable,
            )
            scope.notification_id = int(outcome.state.get("notificationId", 0) or 0)
            return self._result(request, outcome)

        if action_id == "desktop.settings.open":
            return self._result(
                request, self.adapters.settings.open_page(
                    parameters["page"], cancellable=scope.cancellable
                )
            )

        if action_id == "desktop.notifications.set-do-not-disturb":
            return self._result(
                request, self.adapters.settings.set_do_not_disturb(
                    bool(parameters["enabled"]), cancellable=scope.cancellable
                )
            )

        if action_id == "desktop.audio.set-volume":
            return self._result(
                request, self.adapters.audio.set_volume(
                    output_id=str(parameters.get("outputId", "")),
                    percent=int(parameters["percent"]),
                    muted=parameters.get("muted"),
                    cancellable=scope.cancellable,
                )
            )

        if action_id == "desktop.clipboard.copy-text":
            outcome, hold = self.adapters.clipboard.copy(
                parameters["text"], cancellable=scope.cancellable
            )
            scope.clipboard_hold = hold
            if hold is not None and cancelled is not None and cancelled():
                # §10: a stop that arrived immediately after the backend
                # succeeded. The effect *can* be undone here, so it is — and the
                # result says the effect was prevented because releasing
                # ownership was verified rather than assumed.
                self.adapters.clipboard.release(hold, "cancelled immediately after ownership")
                raise DesktopCancelled(
                    "the clipboard was taken and released again before the task continued",
                    effect_known=True, effect_prevented=True,
                )
            return self._result(request, outcome)

        if action_id == "desktop.uri.open":
            uri = self._uri_for(request, path_context)
            outcome = self.adapters.uri.open(uri, cancellable=scope.cancellable)
            self.adapters.uri.settle()
            return self._result(request, outcome)

        if action_id == "desktop.file.reveal":
            if path_context is None:
                raise DesktopRefused("this task holds no path context, so nothing can be revealed")
            resolved = path_context.resolve(parameters["pathReference"])
            if resolved.real_path != request.target:
                # §8: the file this points at changed after it was approved.
                # Checked here as well as in the binding, because the reference
                # is resolved twice — once for the prompt and once for the act —
                # and a symlink re-pointed between the two would produce two
                # different files with one approval.
                raise DesktopApprovalMismatch(
                    "the file this points at changed after it was approved; nothing was revealed"
                )
            return self._result(
                request, self.adapters.file_reveal.reveal(resolved, cancellable=scope.cancellable)
            )

        if action_id in ("desktop.application.launch", "desktop.application.present"):
            return self._application(request, scope, path_context=path_context, checkpoint=checkpoint)

        raise DesktopSchemaError(f"{action_id} is declared and has no dispatch")

    def _uri_for(self, request: DesktopActionRequest, path_context: PathContext | None) -> Any:
        from .uris import parse_uri

        parameters = dict(request.parameters)
        if parameters.get("pathReference"):
            if path_context is None:
                raise DesktopRefused("this task holds no path context, so no file may be opened")
            resolved = path_context.resolve(parameters["pathReference"])
            from urllib.parse import quote

            candidate = "file://" + quote(resolved.real_path.replace("\\", "/"), safe="/")
        else:
            candidate = parameters["uri"]
        parsed = parse_uri(candidate, expected_scheme=parameters["expectedScheme"])
        if parsed.normalised != request.target:
            raise DesktopApprovalMismatch(
                "the address changed after it was approved; nothing was opened"
            )
        return parsed

    def _application(
        self,
        request: DesktopActionRequest,
        scope: _Scope,
        *,
        path_context: PathContext | None,
        checkpoint: Any,
    ) -> DesktopActionResult:
        from .entries import resolve_application
        from .uris import parse_uri

        parameters = dict(request.parameters)
        entry = resolve_application(parameters["applicationId"])
        if entry.application_id != request.target:
            raise DesktopApprovalMismatch(
                "the application changed after it was approved; nothing was launched"
            )
        checkpoint("after the application entry was resolved")

        if request.action_id == "desktop.application.present":
            return self._result(
                request,
                self.adapters.present.present(
                    entry,
                    window_identity=parameters.get("windowIdentity", ""),
                    cancellable=scope.cancellable,
                ),
            )

        file_paths: list[str] = []
        for reference in parameters.get("fileReferences", ()):
            if path_context is None:
                raise DesktopRefused("this task holds no path context, so it can supply no files")
            file_paths.append(path_context.resolve(reference).real_path)
        uris = [parse_uri(item) for item in parameters.get("uris", ())]
        return self._result(
            request,
            self.adapters.launch.launch(
                entry,
                file_paths=file_paths,
                uris=uris,
                focus_existing=bool(parameters.get("focusExisting", True)),
                cancellable=scope.cancellable,
            ),
        )

    # -- results -----------------------------------------------------------

    def _result(self, request: DesktopActionRequest, outcome: Any) -> DesktopActionResult:
        """Turn one adapter outcome into a result, without upgrading it.

        The single rule: ``confirmed`` requires
        :attr:`~companion.desktop.result.Observation.verifies`, and
        :class:`~companion.desktop.result.DesktopActionResult` refuses to be
        built otherwise. So the state is *derived* from the observation rather
        than chosen alongside it, and there is no branch here that could pick
        the confident word for an acknowledgement.
        """
        if outcome.state.get("unsupported"):
            return unsupported(
                request_id=request.request_id, action_id=request.action_id,
                idempotency_key=request.idempotency_key, explanation=outcome.detail,
                target=request.target, target_kind=request.target_kind,
            )
        if not outcome.ok:
            return DesktopActionResult(
                request_id=request.request_id,
                action_id=request.action_id,
                idempotency_key=request.idempotency_key,
                state="failed",
                observation=outcome.observation,
                explanation=outcome.detail or "the backend did not perform the action",
                target=request.target,
                target_kind=request.target_kind,
            )

        state = "confirmed" if outcome.observation.verifies else "accepted-not-confirmed"
        previous = {
            key: value for key, value in outcome.state.items()
            if key.startswith("previous") and value is not None
        }
        if request.action_id == "desktop.audio.set-volume":
            previous.setdefault("outputId", outcome.state.get("outputId", request.target))
        # Normalised *before* the availability question, not after. An adapter
        # reports ``previousPercent``; undo reads ``percent``. Asking about the
        # raw form was the first version, and it answered "no undo" for every
        # action that had one — the button was simply never offered, which is
        # the failure mode a test only catches if it asserts on the offer.
        previous = _normalise_previous(previous)
        undo_available, undo_reason = _undo_availability(request, previous)
        notes: list[str] = []
        if outcome.mechanism:
            notes.append(f"performed through {outcome.mechanism}")
        if undo_reason:
            notes.append(undo_reason)
        return DesktopActionResult(
            request_id=request.request_id,
            action_id=request.action_id,
            idempotency_key=request.idempotency_key,
            state=state,
            observation=outcome.observation,
            explanation=outcome.detail or request.expected_effect,
            target=request.target,
            target_kind=request.target_kind,
            undo_available=undo_available,
            undo_action_id=request.undo_action_id if undo_available else "",
            previous_state=previous,
            notes=tuple(notes[:8]),
        )

    def _cancelled_result(
        self, request: DesktopActionRequest, exc: DesktopCancelled, started: float
    ) -> DesktopActionResult:
        return DesktopActionResult(
            request_id=request.request_id,
            action_id=request.action_id,
            idempotency_key=request.idempotency_key,
            state="cancelled",
            observation=Observation(
                "none",
                detail=(
                    "the effect was prevented" if exc.effect_prevented
                    else "whether the effect happened is not known"
                ),
            ),
            explanation=str(exc),
            target=request.target,
            target_kind=request.target_kind,
            effect_prevented=bool(exc.effect_prevented),
            duration_seconds=max(0.0, self.clock.monotonic() - started),
        )

    def _settle(
        self, request: DesktopActionRequest, result: DesktopActionResult, descriptor: Any
    ) -> None:
        state = {
            "confirmed": "completed",
            "accepted-not-confirmed": "completed",
            "refused": "failed",
            "failed": "failed",
            "unsupported": "failed",
            "cancelled": "cancelled",
            "unknown": "unknown",
        }[result.state]
        if result.state == "cancelled" and result.effect_prevented is False:
            # A cancel that could not prevent the effect leaves the same
            # uncertainty a crash does, and §10 says to record uncertain effects
            # rather than to claim a rollback.
            state = "unknown"
        if result.previous_state:
            self.ledger.record_previous_state(request.idempotency_key, result.previous_state)
        self.ledger.settle(
            request.idempotency_key,
            state=state,
            result=result,
            settled_at=iso8601(self.clock.wall()),
        )

    # -- cancellation ------------------------------------------------------

    def cancel(self, *, request_id: str = "", cancellation_token: str = "") -> dict[str, Any]:
        """Stop an attempt in flight, and say what that did and did not prevent.

        Returns rather than raises: a cancel is a request about somebody else's
        work, and "there was nothing to cancel" is an answer rather than an
        error.
        """
        with self._guard:
            scope = self._by_request.get(request_id)
            if scope is None and cancellation_token:
                scope = next(
                    (item for item in self._inflight.values() if item.request_id == cancellation_token),
                    None,
                )
        if scope is None:
            return {"cancelled": False, "reason": "no attempt with that identity is in flight"}
        raised = scope.cancellable.cancel()
        released: dict[str, Any] = {}
        if scope.clipboard_hold is not None:
            released["clipboardReleased"] = self.adapters.clipboard.release(
                scope.clipboard_hold, "the task was cancelled"
            )
        portal_closed = self.adapters.uri.cancel()
        if portal_closed:
            released["portalRequestClosed"] = True
        if scope.notification_id:
            released["notificationWithdrawn"] = self.adapters.notification.close(scope.notification_id)
        return {"cancelled": raised, "released": released}

    def cancel_task(self, task_id: str) -> tuple[str, ...]:
        """Stop every attempt belonging to one task.

        §10: a task cancellation invalidates all pending desktop-action
        approvals. The approvals themselves live in the canonical store and are
        withdrawn there; what this does is stop the attempts and drop this
        broker's spent-approval entries for the task, so a later attempt cannot
        find one still standing.
        """
        with self._guard:
            scopes = [
                scope for scope in self._inflight.values()
                if (entry := self.ledger.get(scope.key)) is not None and entry.task_id == task_id
            ]
            self.consumed = {item for item in self.consumed if item[0] != task_id}
        stopped: list[str] = []
        for scope in scopes:
            self.cancel(request_id=scope.request_id)
            stopped.append(scope.request_id)
        return tuple(stopped)

    # -- undo --------------------------------------------------------------

    def undo_plan(self, key: str) -> UndoPlan:
        entry = self.ledger.get(key)
        if entry is None:
            return UndoPlan(kind="none", reason="no action with that key was recorded", requires_approval=False)
        return undo_plan_for(entry)

    def compensate(self, key: str, *, reason: str = "compensated") -> dict[str, Any]:
        """Perform a compensation — the one undo that needs no new approval.

        Only clipboard release reaches here; see
        :func:`companion.desktop.undo.undo_plan_for` for why withdrawing a
        disclosure is not a thing to ask permission for.
        """
        plan = self.undo_plan(key)
        if plan.kind != "compensate":
            return {"compensated": False, "reason": plan.reason or "no compensation is available"}
        released = self.adapters.clipboard.release_all(reason)
        return {"compensated": bool(released), "released": released, "explanation": plan.reason}

    def link_undo(self, *, original_key: str, undo_key: str) -> None:
        self.ledger.link_undo(original_key=original_key, undo_key=undo_key)

    # -- reporting ---------------------------------------------------------

    def status(self) -> dict[str, Any]:
        report = self.environment()
        with self._guard:
            inflight = sorted(self._inflight)
            spent = len(self.consumed)
        from .ledger import summarise

        entries = tuple(self.ledger.entries.values())
        return {
            "posture": report.posture,
            "session": report.session,
            "desktop": report.desktop,
            "availableActions": list(report.available_actions),
            "unavailableActions": dict(report.unavailable_actions),
            "inflight": len(inflight),
            "approvalsSpent": spent,
            "ledger": summarise(entries),
            "resources": self.adapters.resource_counts(),
            "recoveryWarnings": list(self.recovery_warnings),
            "pendingDecisions": [
                {
                    "key": item.key,
                    "actionId": item.action_id,
                    "taskId": item.task_id,
                    "explanation": retry_policy_for(item.action_id).explanation,
                }
                for item in self.ledger.unknown()
            ],
        }

    def history(self, *, task_id: str = "", limit: int = 50) -> tuple[dict[str, Any], ...]:
        return tuple(item.to_json() for item in self.ledger.history(task_id=task_id, limit=limit))

    def explain(self, action_id: str) -> dict[str, Any]:
        descriptor = descriptor_for(action_id)
        report = self.environment()
        return {
            **descriptor.to_json(),
            "available": report.permits(action_id),
            "unavailableReason": report.reason(action_id),
            "retry": retry_policy_for(action_id).to_json(),
            "parameterSchema": _schema_for(action_id),
        }


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _schema_for(action_id: str) -> dict[str, Any]:
    from .parameters import PARAMETER_SCHEMAS

    return dict(PARAMETER_SCHEMAS[action_id])


def _undo_preview(descriptor: Any, action: NormalisedAction) -> str:
    """What the approval prompt says about taking this back (§18)."""
    if descriptor.reversibility == "reversible" and action.previous_state:
        if action.action_id == "desktop.audio.set-volume":
            return f"Can be set back to {action.previous_state.get('percent')}%"
        if action.action_id == "desktop.notifications.set-do-not-disturb":
            return "Can be set back to its previous value"
    if descriptor.reversibility == "reversible":
        return ""
    if descriptor.reversibility == "compensatable":
        return "The clipboard can be released, but what was on it before cannot be restored"
    return ""


def _undo_availability(
    request: DesktopActionRequest, previous: Mapping[str, Any]
) -> tuple[bool, str]:
    """Whether an undo is genuinely offerable, and the note if it is not.

    Computed rather than copied from the descriptor. An action *declared*
    reversible whose previous state could not be read has no undo in practice,
    and offering one would produce a button that fails when pressed.
    """
    if request.reversibility == "compensatable":
        return True, ""
    if request.reversibility != "reversible":
        return False, ""
    if request.action_id == "desktop.audio.set-volume" and isinstance(previous.get("percent"), int):
        return True, ""
    if request.action_id == "desktop.notifications.set-do-not-disturb" and isinstance(
        previous.get("enabled"), bool
    ):
        return True, ""
    return False, (
        "no undo is offered: the previous value could not be read before the change, and "
        "restoring a value nobody observed would be a change of its own"
    )


def _normalise_previous(previous: Mapping[str, Any]) -> dict[str, Any]:
    """``previousPercent`` and friends, as the plain names undo reads."""
    mapped: dict[str, Any] = {}
    for key, value in previous.items():
        if key.startswith("previous") and len(key) > len("previous"):
            name = key[len("previous"):]
            mapped[name[0].lower() + name[1:]] = value
        else:
            mapped[key] = value
    return mapped


#: Which adapter's probe answered for which action. The same mapping
#: :func:`companion.desktop.environment.probe_environment` uses, restated here
#: because a prompt quoting "the notification daemon answered" for a clipboard
#: write would be worse than quoting nothing.
_ANSWERING_ADAPTER = {
    "desktop.notification.show": "NotificationAdapter",
    "desktop.application.launch": "ApplicationLaunchAdapter",
    "desktop.application.present": "ApplicationPresentAdapter",
    "desktop.settings.open": "SettingsAdapter",
    "desktop.audio.set-volume": "AudioControlAdapter",
    "desktop.notifications.set-do-not-disturb": "SettingsAdapter.doNotDisturb",
    "desktop.clipboard.copy-text": "ClipboardAdapter",
    "desktop.uri.open": "PortalAdapter",
    "desktop.file.reveal": "FileRevealAdapter",
}


def _availability_detail(report: DesktopEnvironmentReport, action_id: str) -> str:
    wanted = _ANSWERING_ADAPTER.get(action_id, "")
    return next(
        (item.detail for item in report.services if item.adapter_id == wanted), ""
    )


def _result_from_json(document: Mapping[str, Any]) -> DesktopActionResult:
    observation = document.get("observation") or {}
    return DesktopActionResult(
        request_id=str(document.get("requestId", "")),
        action_id=str(document.get("actionId", "")),
        idempotency_key=str(document.get("idempotencyKey", "")),
        state=str(document.get("state", "unknown")),
        observation=Observation(
            kind=str(observation.get("kind", "none")),
            detail=str(observation.get("detail", "")),
            matched=observation.get("matched"),
            observed_value=observation.get("observedValue"),
        ),
        explanation=str(document.get("explanation", "")),
        target=str(document.get("target", "")),
        target_kind=str(document.get("targetKind", "none")),
        undo_available=bool(document.get("undoAvailable", False)),
        undo_action_id=str(document.get("undoActionId", "")),
        previous_state=dict(document.get("previousState") or {}),
        effect_prevented=document.get("effectPrevented"),
        duration_seconds=float(document.get("durationSeconds", 0.0) or 0.0),
        notes=tuple(str(item) for item in (document.get("notes") or ()))[:8],
    )
