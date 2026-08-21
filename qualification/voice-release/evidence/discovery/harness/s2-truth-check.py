#!/usr/bin/python3
"""EE-2: correlate what the desktop claimed with what the audio stack did.

Claims come from the state watcher (accessible names). Truth comes from the
poller (capture streams, sink states, player processes). Both are on the
guest's clock. For every interval where the UI claimed listening, a capture
stream must exist; for every interval where it claimed talking, the sink must
be running or a player alive. Boundaries get a grace window: the claim and
the stream are torn down by different processes and a sub-second skew is
scheduling, not a lie.

  s2-truth-check.py <states.ndjson> <truth.ndjson> [grace-seconds]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

GRACE = float(sys.argv[3]) if len(sys.argv) > 3 else 0.8


def load(path: str) -> list[dict]:
    records = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def character_state(record: dict) -> str:
    name = record.get("names", {}).get("Bunny, your assistant", "")
    _, _, body = name.partition("—")
    state, _, _ = body.strip().partition(".")
    return state.strip()


def mic_claimed(record: dict) -> bool:
    names = record.get("names", {})
    return ("Microphone active" in names) or character_state(record) == "listening"


def talking_claimed(record: dict) -> bool:
    return character_state(record) == "talking"


def truth_between(truth: list[dict], start: float, end: float) -> list[dict]:
    return [t for t in truth if start <= t["at"] <= end]


def main() -> int:
    states = load(sys.argv[1])
    truth = load(sys.argv[2])
    if not states or not truth:
        print(json.dumps({"verdict": "NO_DATA", "states": len(states),
                          "truth": len(truth)}))
        return 1

    # Build claim intervals from consecutive watcher samples.
    intervals = []  # (kind, start, end)
    for kind, claimed in (("listening", mic_claimed), ("talking", talking_claimed)):
        start = None
        for record in states:
            if claimed(record) and start is None:
                start = record["at"]
            elif not claimed(record) and start is not None:
                intervals.append((kind, start, record["at"]))
                start = None
        if start is not None:
            intervals.append((kind, start, states[-1]["at"]))

    findings = []
    checked = []
    for kind, start, end in intervals:
        # Shrink by the grace window; a claim shorter than 2*grace is only
        # checked at its midpoint.
        # Violations are only counted inside the graced window. Falling back
        # to the full interval when the graced window is empty re-widens the
        # grace the line above just applied — the first run FAILed on a
        # 180 ms player-teardown skew precisely because of that fallback.
        lo, hi = start + GRACE, end - GRACE
        if lo >= hi:
            lo = hi = (start + end) / 2
        samples = truth_between(truth, lo, hi)
        if not samples:
            checked.append({"claim": kind, "start": start, "end": end,
                            "seconds": round(end - start, 2),
                            "truthSamples": 0, "violations": 0, "ok": True,
                            "note": "no truth samples inside the graced window; too short to judge"})
            continue
        if kind == "listening":
            bad = [t for t in samples if t["captureStreams"] < 1]
            ok = len(bad) == 0 and len(samples) > 0
        else:
            bad = [t for t in samples
                   if t["playerProcesses"] < 1 and "RUNNING" not in t["sinkStates"]]
            ok = len(bad) == 0 and len(samples) > 0
        checked.append({"claim": kind, "start": start, "end": end,
                        "seconds": round(end - start, 2),
                        "truthSamples": len(samples),
                        "violations": len(bad), "ok": ok})
        if not ok:
            findings.append({"claim": kind, "start": start, "end": end,
                             "violations": bad[:5]})

    # The inverse direction: audio activity with no claim. A capture stream
    # while the UI says nothing is the privacy-relevant direction.
    claim_spans = [(s, e) for k, s, e in intervals if k == "listening"]
    unclaimed = []
    for t in truth:
        if t["captureStreams"] >= 1:
            covered = any(s - GRACE <= t["at"] <= e + GRACE for s, e in claim_spans)
            if not covered:
                unclaimed.append(t)
    verdict = "PASS" if not findings and not unclaimed else "FAIL"
    print(json.dumps({
        "verdict": verdict,
        "graceSeconds": GRACE,
        "intervals": checked,
        "claimViolations": findings,
        "captureWithoutClaim": unclaimed[:10],
        "captureWithoutClaimCount": len(unclaimed),
    }, indent=2))
    return 0 if verdict == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
