#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§24's per-action latencies, measured against the real backends.

A development tool, not shipped.

The vertical slice measures the latencies of the actions it performs, and it
performs four of the nine. This measures the rest, through the same broker and
the same adapters, so §24's list is answered by numbers rather than by silence.

**Approvals are constructed here rather than asked for**, and that is the one
thing to understand about what these figures mean. The broker is handed the
binding its own `prepare` produced, which is what an approved act looks like
from the broker's side. What is being measured is therefore the *dispatch* path
— normalisation, ledger write, adapter call, observation — and not the time a
person takes to answer, which is the dominant term in
`proposal-to-approval` and is not a property of this build.

**Two actions are deliberately not measured here**, and both refusals are about
what the measurement would cost the person at the desk:

``desktop.uri.open``
    this host has no handler installed for any allowlisted scheme, so the portal
    would raise an application-chooser dialog. The figure would be the time to
    show a dialog somebody then has to dismiss, which is neither this build's
    latency nor a thing to do twenty times to a desk.
``desktop.application.present``
    reports UNSUPPORTED for every entry that does not declare
    ``DBusActivatable``, and activation of one that does is the launch path
    already measured.

Every action that changes something is **restored** afterwards, in the same run,
whatever happened. A measurement harness that left the volume at 50% and
do-not-disturb on would be a worse citizen than the thing it is measuring.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
import time
from typing import Any, Callable


def _figures(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"samples": 0}
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
    return {
        "samples": len(ordered),
        "minimum": round(ordered[0], 6),
        "median": round(statistics.median(ordered), 6),
        "p95": round(ordered[index], 6),
        "maximum": round(ordered[-1], 6),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=10)
    args = parser.parse_args()

    sys.path.insert(0, str(args.root))
    from companion.desktop.broker import BrokerOptions, DesktopActionBroker
    from companion.desktop.paths import PathContext

    broker = DesktopActionBroker(BrokerOptions()).start()
    report = broker.environment(refresh=True)
    results: dict[str, Any] = {}
    states: dict[str, Any] = {}
    counter = {"n": 0}

    def once(action_id: str, parameters: dict[str, Any], *, path_context=None) -> Any:
        counter["n"] += 1
        index = counter["n"]
        prepared = broker.prepare(
            action_id, parameters,
            request_id=f"dreq-lat-{index}", session_id="latency-session",
            task_id="latency-task", lifecycle_epoch=0, plan_id="latency-plan",
            operation_id=f"op-{index}", cancellation_token=f"cancel-{index}",
            path_context=path_context,
        )
        started = time.monotonic()
        result = broker.execute(
            prepared.request.with_approval(f"approval-{index}"),
            approved_binding=prepared.binding,
            path_context=path_context,
        )
        return time.monotonic() - started, result

    def measure(name: str, action_id: str, build: Callable[[int], dict[str, Any]], **extra) -> None:
        if not report.permits(action_id):
            results[name] = {"result": "NOT_RUN", "reason": report.reason(action_id)}
            return
        seconds: list[float] = []
        outcomes: dict[str, int] = {}
        for index in range(args.samples):
            elapsed, result = once(action_id, build(index), **extra)
            seconds.append(elapsed)
            outcomes[result.state] = outcomes.get(result.state, 0) + 1
        results[name] = {**_figures(seconds), "states": outcomes}

    # -- notification: one per sample, low urgency, short timeout ----------
    measure(
        "notification-dispatch", "desktop.notification.show",
        lambda index: {
            "title": "Bunny latency check",
            "body": f"sample {index + 1}",
            "urgency": "low",
            "timeoutMs": 1000,
        },
    )

    # -- settings page: single-instance, so this activates rather than piles up
    measure(
        "settings-open", "desktop.settings.open",
        lambda index: {"page": "sound"},
    )

    # -- volume: restored afterwards, whatever happens ---------------------
    output = broker.adapters.audio.read("")
    if output is not None and isinstance(output.percent, int):
        states["volumeBefore"] = {"outputId": output.output_id, "percent": output.percent}
        try:
            measure(
                "volume-set", "desktop.audio.set-volume",
                lambda index: {
                    "percent": 40 + (index % 2) * 5, "outputId": output.output_id,
                },
            )
            read: list[float] = []
            for _ in range(args.samples):
                at = time.monotonic()
                broker.adapters.audio.read(output.output_id)
                read.append(time.monotonic() - at)
            results["volume-read-back"] = _figures(read)
        finally:
            broker.adapters.audio.set_volume(
                output_id=output.output_id, percent=output.percent, muted=output.muted,
            )
            restored = broker.adapters.audio.read(output.output_id)
            states["volumeRestored"] = restored.percent if restored else None
    else:
        results["volume-set"] = {"result": "NOT_RUN", "reason": "no readable audio output"}
        results["volume-read-back"] = {"result": "NOT_RUN", "reason": "no readable audio output"}

    # -- do-not-disturb: restored afterwards -------------------------------
    previous = broker.adapters.settings.read_do_not_disturb()
    if previous is None:
        results["do-not-disturb-set"] = {
            "result": "NOT_RUN",
            "reason": "the do-not-disturb value could not be read on this desktop",
        }
    else:
        states["doNotDisturbBefore"] = previous
        try:
            measure(
                "do-not-disturb-set", "desktop.notifications.set-do-not-disturb",
                lambda index: {"enabled": bool(index % 2)},
            )
        finally:
            broker.adapters.settings.set_do_not_disturb(previous)
            states["doNotDisturbRestored"] = broker.adapters.settings.read_do_not_disturb()

    # -- clipboard: taken and released each sample -------------------------
    if report.permits("desktop.clipboard.copy-text"):
        seconds: list[float] = []
        release: list[float] = []
        for index in range(args.samples):
            elapsed, _result = once(
                "desktop.clipboard.copy-text",
                {"text": f"Bunny OS latency check, sample {index + 1}.",
                 "classification": "internal"},
            )
            seconds.append(elapsed)
            at = time.monotonic()
            broker.adapters.clipboard.release_all("latency measurement finished")
            release.append(time.monotonic() - at)
        results["clipboard-ownership"] = _figures(seconds)
        results["clipboard-release"] = _figures(release)
        states["clipboardOwnersAfter"] = broker.adapters.clipboard.outstanding
    else:
        results["clipboard-ownership"] = {
            "result": "NOT_RUN", "reason": report.reason("desktop.clipboard.copy-text"),
        }

    # -- file reveal: one real file, in an approved root --------------------
    home = Path.home()
    documents = home / "Documents"
    documents.mkdir(parents=True, exist_ok=True)
    sample = documents / "bunny-latency-sample.txt"
    sample.write_text("A file the latency measurement reveals.\n", encoding="utf-8")
    context = PathContext.build({"sample": str(sample)}, roots=(documents,))
    measure(
        "file-reveal", "desktop.file.reveal",
        lambda index: {"pathReference": "sample"},
        path_context=context,
    )

    # -- the two that are not measured, and why -----------------------------
    results["uri-open"] = {
        "result": "NOT_RUN",
        "reason": (
            "this host has no handler installed for any allowlisted scheme, so the portal "
            "would raise an application-chooser dialog. The figure would be the time to show "
            "a dialog somebody then has to dismiss, which is neither this build's latency nor "
            "a thing to do to a desk ten times"
        ),
    }
    results["application-present"] = {
        "result": "NOT_RUN",
        "reason": (
            "UNSUPPORTED for every entry that does not declare DBusActivatable, and activation "
            "of one that does is the launch path the slice already measures"
        ),
    }
    results["proposal-to-approval"] = {
        "result": "NOT_RUN",
        "reason": (
            "dominated by how long a person takes to answer, which is not a property of this "
            "build. The machine's share of it — building the request, digesting the binding, "
            "persisting the question — is inside the slice's per-run figures"
        ),
    }

    counts = broker.adapters.resource_counts()
    broker.stop()
    document = {
        "schemaVersion": "bunny-os/desktop-action-latency/1",
        "samplesRequested": args.samples,
        "posture": report.posture,
        "latencies": results,
        "restoredState": states,
        "resourceCountsBeforeStop": counts,
        "note": (
            "Approvals are constructed rather than asked for, so these are dispatch "
            "latencies: normalisation, ledger write, adapter call, observation. Every "
            "action that changed something was restored in the same run."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        sample.unlink()
    except OSError:
        pass
    print(json.dumps({"posture": report.posture, "latencies": results, "restored": states}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
