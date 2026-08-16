#!/usr/bin/python3
"""Sample what the audio stack is actually doing, for the truthfulness check.

The state watcher records what the desktop *claims* (accessible names). This
records what is *true*: whether a capture stream exists, what state the sink
is in, and whether a player process is alive. The two files are correlated on
the guest's own clock; neither asks the other for its answer.

  s2-truth-poller.py <output.ndjson> [interval-seconds]
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path


def run(argv: list[str]) -> str:
    try:
        return subprocess.run(argv, capture_output=True, text=True,
                              timeout=5).stdout
    except Exception:  # noqa: BLE001
        return ""


def sample() -> dict:
    outputs = [line for line in run(["pactl", "list", "source-outputs",
                                     "short"]).splitlines() if line.strip()]
    sinks = run(["pactl", "list", "sinks", "short"])
    # State is the LAST column; the sample spec in the middle contains spaces.
    sink_states = [line.split()[-1] if line.split() else "?"
                   for line in sinks.splitlines() if line.strip()]
    players = 0
    for name in ("paplay", "pacat", "pw-cat", "pw-play"):
        players += len([line for line in
                        run(["pgrep", "-x", name]).splitlines() if line.strip()])
    return {
        "at": round(time.time(), 3),
        "captureStreams": len(outputs),
        "sinkStates": sink_states,
        "playerProcesses": players,
    }


def main() -> int:
    target = Path(sys.argv[1])
    interval = float(sys.argv[2]) if len(sys.argv) > 2 else 0.15
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = target.open("a", buffering=1, encoding="utf-8")
    while True:
        # Every tick is written. A change-only log made the correlation
        # sparse enough that the checker's fallback re-widened its own grace
        # window — the first EE-2 run failed on that, not on the product.
        handle.write(json.dumps(sample()) + "\n")
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
