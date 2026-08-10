# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What gets said next, what gets skipped, and a record of which was which.

§7's rules are all here, and every one of them exists because a companion with a
naive queue is unbearable. Speech is serial and slow — a sentence takes seconds,
during which the task has moved on — so a first-in-first-out queue reads out a
history of things that already happened. The rules turn a log into a
conversation:

* a **critical warning interrupts** whatever is being said;
* an **approval prompt interrupts progress narration**, because it is a question
  and the answer is being waited on;
* **cancelling a task stops that task's speech**, all of it, queued and current;
* a **newer result supersedes an older progress update** for the same task —
  once the answer is known, narrating the search for it is noise;
* **repeated identical text is coalesced**, so a poll loop that publishes the
  same status ten times says it once;
* **decorative speech is dropped under pressure** rather than queued for later,
  because its moment has passed by the time the queue reaches it;
* the queue is **bounded**, and a full queue drops its own least urgent entry
  rather than growing.

The last one is what makes an unbounded narration loop impossible. A runtime
emitting progress faster than speech can deliver it does not accumulate a
backlog; it keeps the most urgent :data:`SpeechQueue.MAX_DEPTH` and records what
it dropped. A user hears the important things late rather than the unimportant
things forever.

**Every utterance gets a disposition.** :class:`companion.voice.captions.SpeechDisposition`
is a closed set and this module assigns one to everything that enters, including
the things that never make a sound. That is what makes §22's gate assertable:
"no utterance was lost" is a count, not a hope.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import heapq
import itertools
import threading
from typing import Any, Iterable, Mapping

from .captions import SpeechDisposition
from .policy import VoiceDecision
from .request import InterruptionPolicy, Priority, VoiceRequest, coalescing_key

__all__ = [
    "QueueOutcome",
    "QueuedUtterance",
    "SpeechQueue",
]

#: Utterances that say the task is over. Only these supersede narration.
_TERMINAL_PRIORITIES = frozenset({Priority.TASK_RESULT, Priority.TASK_ERROR})

#: Utterances that describe a task still in progress, and are therefore the ones
#: a terminal outcome makes untrue.
_NARRATION_PRIORITIES = frozenset({Priority.PROGRESS_UPDATE, Priority.DECORATIVE})


@dataclass
class QueuedUtterance:
    """One request waiting its turn, with the bookkeeping it accumulates."""

    request: VoiceRequest
    sequence: int
    enqueued_at_monotonic: float = 0.0
    disposition: str = SpeechDisposition.QUEUED
    detail: str = ""
    #: Set when this entry has been removed from the queue by supersession or a
    #: drop but the heap still holds it. Lazy deletion: rebuilding a heap on
    #: every cancellation is the kind of cost that only shows up under the load
    #: §22 applies.
    withdrawn: bool = False

    @property
    def key(self) -> tuple[int, int]:
        return (self.request.priority.value, self.sequence)

    def to_json(self) -> dict[str, Any]:
        return {
            "requestId": self.request.request_id,
            "taskId": self.request.task_id,
            "priority": self.request.priority.wire,
            "sequence": self.sequence,
            "enqueuedAtMonotonic": self.enqueued_at_monotonic,
            "disposition": self.disposition,
            "detail": self.detail,
            "textDigest": self.request.text_digest,
        }


@dataclass(frozen=True)
class QueueOutcome:
    """What happened to a submission, before anything was spoken."""

    accepted: bool
    disposition: str
    detail: str
    request_id: str = ""
    #: Requests already in the queue that this submission displaced, with the
    #: disposition each was given. Returned so the caller can record them rather
    #: than discovering later that an utterance vanished.
    displaced: tuple[tuple[str, str], ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "disposition": self.disposition,
            "detail": self.detail,
            "requestId": self.request_id,
            "displaced": [
                {"requestId": name, "disposition": value} for name, value in self.displaced
            ],
        }


class SpeechQueue:
    """A bounded priority queue with §7's displacement rules built in.

    Ordering is ``(priority, arrival)``: rank first, then first-come within a
    rank. A heap rather than a sorted list because the displacement rules need
    the *least* urgent entry as often as the most urgent, and scanning for it on
    every submission is the cost that appears under the hundred-run gate rather
    than in a unit test.

    Removal is lazy. Superseded and dropped entries are flagged and skipped when
    popped, because rebuilding the heap on every cancellation would make
    cancelling a task with a dozen queued lines quadratic in a path that runs
    while the user is waiting.
    """

    #: The deepest the queue may get. Thirty-two utterances at a few seconds
    #: each is over a minute of backlog — already far more than anybody wants —
    #: and it is a bound rather than a target: reaching it means something is
    #: emitting faster than speech can deliver, and the drop record says so.
    MAX_DEPTH = 32

    def __init__(self, *, maximum_depth: int = MAX_DEPTH) -> None:
        self.maximum_depth = max(1, maximum_depth)
        self._heap: list[tuple[tuple[int, int], int, QueuedUtterance]] = []
        self._entries: dict[str, QueuedUtterance] = {}
        self._by_content: dict[tuple[str, str, int], str] = {}
        self._counter = itertools.count()
        self._ledger: list[dict[str, Any]] = []
        self._guard = threading.RLock()
        self._live = 0

    # ----------------------------------------------------------------- #

    def __len__(self) -> int:
        with self._guard:
            return self._live

    @property
    def depth(self) -> int:
        return len(self)

    def peek_priority(self) -> Priority | None:
        with self._guard:
            for _, _, entry in sorted(self._heap):
                if not entry.withdrawn:
                    return entry.request.priority
            return None

    def contains(self, request_id: str) -> bool:
        with self._guard:
            entry = self._entries.get(request_id)
            return entry is not None and not entry.withdrawn

    def find(self, request_id: str) -> QueuedUtterance | None:
        with self._guard:
            return self._entries.get(request_id)

    # ----------------------------------------------------------------- #

    def submit(
        self,
        request: VoiceRequest,
        *,
        decision: VoiceDecision | None = None,
        monotonic: float = 0.0,
        speaking: VoiceRequest | None = None,
    ) -> QueueOutcome:
        """Offer an utterance to the queue, applying every §7 rule in order.

        ``speaking`` is what the worker currently has the floor with, passed in
        rather than held here: the queue does not own the worker's state, and a
        queue that thought it knew what was playing would be a second answer to
        a question the worker is authoritative on.
        """
        with self._guard:
            existing = self._entries.get(request.request_id)
            if existing is not None and not existing.withdrawn:
                if existing.request.conflicts_with(request):
                    # §6: a duplicate id with different content is refused. The
                    # alternative — serving it — would mean the record of what
                    # was said no longer matches what was said.
                    return self._refuse(
                        request, SpeechDisposition.DROPPED,
                        "a different utterance is already queued under this request id",
                    )
                return QueueOutcome(
                    accepted=False,
                    disposition=SpeechDisposition.COALESCED,
                    detail="this exact request is already queued",
                    request_id=request.request_id,
                )

            if request.expired(monotonic):
                return self._refuse(
                    request, SpeechDisposition.EXPIRED,
                    "the utterance expired before it could be queued",
                )

            if decision is not None and not decision.speaks:
                return self._refuse(
                    request, SpeechDisposition.DEGRADED_TO_CAPTIONS,
                    f"speech is {decision.outcome}; the caption is the whole of the output",
                )
            if decision is not None and not decision.permits(request.priority):
                return self._refuse(
                    request, SpeechDisposition.DROPPED,
                    (
                        f"{request.priority.wire} is below the current floor of "
                        f"{decision.minimum_priority.wire}"
                    ),
                )

            # -- coalescing: the same words, same task, same rank ----------
            key = coalescing_key(request)
            twin = self._by_content.get(key)
            if twin is not None:
                entry = self._entries.get(twin)
                if entry is not None and not entry.withdrawn:
                    return self._refuse(
                        request, SpeechDisposition.COALESCED,
                        f"identical text is already queued for this task as {twin}",
                    )
            if speaking is not None and coalescing_key(speaking) == key:
                return self._refuse(
                    request, SpeechDisposition.COALESCED,
                    "these words are being spoken right now",
                )

            # -- drop-if-busy ---------------------------------------------
            if request.interruption_policy is InterruptionPolicy.DROP_IF_BUSY and (
                speaking is not None or self._live
            ):
                return self._refuse(
                    request, SpeechDisposition.DROPPED,
                    "the utterance asked to be dropped rather than queued while the floor was busy",
                )

            displaced: list[tuple[str, str]] = []

            # -- supersession: a terminal outcome retires this task's narration --
            #
            # §7 names one case: "a newer task result may supersede an older
            # progress utterance". A task *error* is included here and nothing
            # else is, and the boundary is the difference between a statement
            # that the task is over and an interjection while it continues.
            # Narrating "counting the words" after "that failed" tells the user
            # something that is no longer true; a critical warning or an
            # approval prompt does not end the task, so the narration behind it
            # is still accurate and is interrupted rather than discarded.
            #
            # An earlier version superseded on anything ranked at or above a
            # result, which meant a warning silently emptied the queue. The
            # tests caught it: a warning had displaced three queued lines that
            # were still true.
            if request.priority in _TERMINAL_PRIORITIES:
                for entry in self._live_entries():
                    if (
                        entry.request.task_id == request.task_id
                        and entry.request.priority in _NARRATION_PRIORITIES
                    ):
                        self._withdraw(
                            entry, SpeechDisposition.SUPERSEDED,
                            f"superseded by {request.priority.wire} {request.request_id}",
                        )
                        displaced.append((entry.request.request_id, SpeechDisposition.SUPERSEDED))

            # -- the bound -------------------------------------------------
            if self._live >= self.maximum_depth:
                weakest = self._weakest()
                if weakest is None or weakest.request.priority.value <= request.priority.value:
                    # Through ``_refuse`` so this lands in the ledger. It used to
                    # return the outcome directly, which meant the one path a
                    # runaway narration loop actually takes was the one path
                    # that recorded nothing — §7 asks for every utterance's
                    # disposition, and "the queue was full" is a disposition.
                    return replace(
                        self._refuse(
                            request, SpeechDisposition.DROPPED,
                            (
                                f"the speech queue is at its bound of {self.maximum_depth} and "
                                f"nothing queued is less urgent than {request.priority.wire}"
                            ),
                        ),
                        displaced=tuple(displaced),
                    )
                self._withdraw(
                    weakest, SpeechDisposition.DROPPED,
                    f"dropped to make room for {request.priority.wire} {request.request_id}",
                )
                displaced.append((weakest.request.request_id, SpeechDisposition.DROPPED))

            entry = QueuedUtterance(
                request=request,
                sequence=next(self._counter),
                enqueued_at_monotonic=monotonic,
            )
            heapq.heappush(self._heap, (entry.key, entry.sequence, entry))
            self._entries[request.request_id] = entry
            self._by_content[key] = request.request_id
            self._live += 1
            return QueueOutcome(
                accepted=True,
                disposition=SpeechDisposition.QUEUED,
                detail="queued",
                request_id=request.request_id,
                displaced=tuple(displaced),
            )

    # ----------------------------------------------------------------- #

    def pop(self, *, monotonic: float = 0.0) -> QueuedUtterance | None:
        """The most urgent live utterance, skipping anything withdrawn or expired."""
        with self._guard:
            while self._heap:
                _, _, entry = heapq.heappop(self._heap)
                if entry.withdrawn:
                    continue
                self._live -= 1
                self._release(entry)
                if entry.request.expired(monotonic):
                    entry.disposition = SpeechDisposition.EXPIRED
                    entry.detail = "the utterance expired while it was queued"
                    self._log(entry)
                    continue
                return entry
            return None

    def cancel(self, request_id: str, *, token: str = "") -> bool:
        """Withdraw one queued utterance.

        The token, when supplied, must match. It is not a secret — a local
        client already holds the request id — but it binds a cancellation to
        *this* request rather than to a reused id, so a late cancel for a
        finished utterance cannot silence the one that replaced it.
        """
        with self._guard:
            entry = self._entries.get(request_id)
            if entry is None or entry.withdrawn:
                return False
            if token and entry.request.cancellation_token and token != entry.request.cancellation_token:
                return False
            self._withdraw(entry, SpeechDisposition.CANCELLED, "cancelled while queued")
            return True

    def cancel_task(self, task_id: str, *, reason: str = "the task was cancelled") -> tuple[str, ...]:
        """Withdraw everything queued for one task. §7's task-cancellation rule."""
        with self._guard:
            cancelled: list[str] = []
            for entry in self._live_entries():
                if entry.request.task_id == task_id:
                    self._withdraw(entry, SpeechDisposition.CANCELLED, reason)
                    cancelled.append(entry.request.request_id)
            return tuple(cancelled)

    def drop_below(self, floor: Priority, *, reason: str) -> tuple[str, ...]:
        """Drop everything less urgent than ``floor``. §12's resource pressure."""
        with self._guard:
            dropped: list[str] = []
            for entry in self._live_entries():
                if entry.request.priority.value > floor.value:
                    self._withdraw(entry, SpeechDisposition.DROPPED, reason)
                    dropped.append(entry.request.request_id)
            return tuple(dropped)

    def clear(self, *, reason: str = "the voice worker stopped") -> tuple[str, ...]:
        with self._guard:
            cleared: list[str] = []
            for entry in self._live_entries():
                self._withdraw(entry, SpeechDisposition.CANCELLED, reason)
                cleared.append(entry.request.request_id)
            self._heap.clear()
            self._entries.clear()
            self._by_content.clear()
            self._live = 0
            return tuple(cleared)

    # ----------------------------------------------------------------- #

    def record(self, request: VoiceRequest, disposition: str, detail: str = "") -> None:
        """Write an outcome for something the worker handled outside the queue."""
        if disposition not in SpeechDisposition.ALL:
            raise ValueError(f"unknown speech disposition: {disposition!r}")
        with self._guard:
            self._append({
                "requestId": request.request_id,
                "taskId": request.task_id,
                "priority": request.priority.wire,
                "disposition": disposition,
                "detail": detail,
                "textDigest": request.text_digest,
            })

    @property
    def ledger(self) -> tuple[dict[str, Any], ...]:
        with self._guard:
            return tuple(self._ledger)

    def counts(self) -> dict[str, int]:
        """How many utterances ended each way. §7's record, as a tally."""
        with self._guard:
            tally = {name: 0 for name in SpeechDisposition.ALL}
            for item in self._ledger:
                tally[item["disposition"]] = tally.get(item["disposition"], 0) + 1
            return tally

    def describe(self) -> dict[str, Any]:
        with self._guard:
            return {
                "depth": self._live,
                "maximumDepth": self.maximum_depth,
                "queued": [entry.to_json() for entry in self._live_entries()],
                "counts": self.counts(),
                "recorded": len(self._ledger),
            }

    # ----------------------------------------------------------------- #

    def _live_entries(self) -> list[QueuedUtterance]:
        return [entry for _, _, entry in self._heap if not entry.withdrawn]

    def _weakest(self) -> QueuedUtterance | None:
        live = self._live_entries()
        if not live:
            return None
        return max(live, key=lambda item: item.key)

    def _withdraw(self, entry: QueuedUtterance, disposition: str, detail: str) -> None:
        entry.withdrawn = True
        entry.disposition = disposition
        entry.detail = detail
        self._live = max(0, self._live - 1)
        self._release(entry)
        self._log(entry)

    def _release(self, entry: QueuedUtterance) -> None:
        self._entries.pop(entry.request.request_id, None)
        key = coalescing_key(entry.request)
        if self._by_content.get(key) == entry.request.request_id:
            self._by_content.pop(key, None)

    def _refuse(self, request: VoiceRequest, disposition: str, detail: str) -> QueueOutcome:
        self._append({
            "requestId": request.request_id,
            "taskId": request.task_id,
            "priority": request.priority.wire,
            "disposition": disposition,
            "detail": detail,
            "textDigest": request.text_digest,
        })
        return QueueOutcome(
            accepted=False, disposition=disposition, detail=detail, request_id=request.request_id
        )

    def _log(self, entry: QueuedUtterance) -> None:
        self._append(entry.to_json())

    def _append(self, document: Mapping[str, Any]) -> None:
        self._ledger.append(dict(document))
        # Bounded, like everything else that grows per utterance. The counts
        # above are computed from what is retained, so a long-running service
        # reports recent behaviour rather than an accumulating total — which is
        # the honest thing for a window that slides.
        if len(self._ledger) > 1024:
            del self._ledger[:-1024]
