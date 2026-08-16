#!/usr/bin/python3
"""Derive the Stage 2 voice latency table from the recorded runs.

Every number comes out of voice-<tag>.json files the pointer-driven runs
wrote: step timestamps (click, spoke) and state transitions sampled from the
accessibility tree at 0.15 s. The utterance length is subtracted where the
question is "after the person stopped speaking". Numbers are therefore
upper bounds that include the watcher's sampling grain (~0.15 s).
"""
from __future__ import annotations

import json
from pathlib import Path

RUNS = Path("/root/bunny-ops/e2e/runs/s2")
UTTERANCE_SECONDS = {
    "ee1": 2.64,      # "Open Files."
    "mem": 4.32,      # "How much memory am I using?"
    "pdfs": 4.42,     # "Find PDF files in Downloads."
    "postint": 4.32,
    "uistop": 2.39,   # "What can you do?"
}


def analyse(tag: str) -> dict | None:
    path = RUNS / f"voice-{tag}.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    steps = {step["step"]: step for step in data.get("steps", [])}
    transitions = {}
    for entry in data.get("transitions", []):
        transitions.setdefault(entry["state"], entry["at"])
    click = steps.get("clicked-microphone", {}).get("at")
    if isinstance(click, dict):
        click = None
    spoke = steps.get("spoke", {}).get("at")
    listening = transitions.get("listening")
    thinking = transitions.get("thinking")
    talking = transitions.get("talking")
    terminal = transitions.get("success") or transitions.get("idle")
    utterance_end = (spoke + UTTERANCE_SECONDS.get(tag, 0.0)) if spoke else None
    row = {"tag": tag}
    def put(name, a, b):
        if a is not None and b is not None:
            row[name] = round(b - a, 2)
    put("pressToListeningSeconds", click, listening)
    put("utteranceEndToThinkingSeconds", utterance_end, thinking)
    put("thinkingToTalkingSeconds", thinking, talking)
    put("utteranceEndToSpokenReplySeconds", utterance_end, talking)
    put("wholeInteractionSeconds", click, terminal)
    row["approved"] = data.get("approved")
    row["finalState"] = data.get("finalState")
    return row


rows = [row for tag in UTTERANCE_SECONDS if (row := analyse(tag))]
print(json.dumps({"note": "AT-SPI-sampled upper bounds; grain ~0.15s", "rows": rows}, indent=1))
