#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Readable summaries of the agent-provider JSON documents.

An ops-side reader, kept out of the runtime: it turns the documents the
gates, the health command and the slice produce into lines a person can scan.
Nothing here is evidence — the JSON is — so this file may change freely.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _health(document: dict[str, Any]) -> None:
    for provider in document.get("providers", ()):
        standing = provider.get("standing", {})
        print(
            f"{provider.get('providerId', '?'):<22} "
            f"rung={standing.get('rung', '?'):<14} "
            f"local={str(provider.get('local')):<5} "
            f"model={provider.get('modelId') or '-':<30} "
            f"{str(standing.get('detail', ''))[:70]}"
        )
    worker = document.get("worker", {})
    if worker:
        print(
            f"\nworker running={worker.get('running')} "
            f"queue={worker.get('queueDepth')} served={worker.get('generationsServed')}"
        )
    recovery = document.get("recovery", {})
    if recovery:
        print(
            f"recovery interrupted={recovery.get('interruptedCount')} "
            f"paid={recovery.get('paidInterrupted')}"
        )
    print(f"remoteConfigured={document.get('remoteConfigured')} "
          f"remoteActive={document.get('remoteActive')}")


def _slice(document: dict[str, Any]) -> None:
    for step in document.get("steps", ()):
        print(f"{step['step']:>3} {step['status']:<8} {step['name']}")
        detail = str(step.get("detail", ""))
        if detail:
            print(f"       {detail[:150]}")
    print(
        f"\npassed={document.get('passed')} "
        f"steps={document.get('stepCount')} "
        f"pass={document.get('passedCount')} "
        f"notRun={len(document.get('notRun', ()))} "
        f"failed={len(document.get('failed', ()))}"
    )


def _gate(document: dict[str, Any]) -> None:
    print(
        f"target={document.get('target')} "
        f"{document.get('passed')}/{document.get('runs')} passed, "
        f"longest consecutive {document.get('longestConsecutivePass')}"
    )
    seconds = [item.get("seconds", 0.0) for item in document.get("iterations", ())]
    if seconds:
        ordered = sorted(seconds)
        print(
            f"seconds min={ordered[0]:.2f} "
            f"median={ordered[len(ordered) // 2]:.2f} max={ordered[-1]:.2f}"
        )
    commits = sorted({item.get("commit", "") for item in document.get("iterations", ())})
    print(f"commits observed: {commits}")
    modes = sorted({str(item.get("mode", "")) for item in document.get("iterations", ())})
    if modes != [""]:
        print(f"modes observed: {modes}")
    growth: dict[str, int] = {}
    absolutes: dict[str, Any] = {}
    for item in document.get("iterations", ()):
        for key, value in (item.get("sinceBaseline") or {}).items():
            if isinstance(value, int) and value > 0 and key != "rssBytes":
                growth[key] = max(growth.get(key, 0), value)
            if isinstance(value, list) and value:
                absolutes[key] = value
        for key in ("providerQueueDepth", "activeStreams", "queueDepth", "activeRequests"):
            value = (item.get("sinceBaseline") or {}).get(key)
            if value:
                absolutes[key] = value
    print(f"resource growth since baseline: {growth or '{}'}")
    print(f"absolutes that should be empty: {absolutes or '{}'}")
    failures = [item for item in document.get("iterations", ()) if not item.get("ok")]
    for item in failures[:5]:
        print(f"  FAILED iteration {item['iteration']}: {item.get('failures')}")


def _measurements(document: dict[str, Any]) -> None:
    for series in document.get("series", ()):
        if series.get("count"):
            print(
                f"{series['name']:<30} n={series['count']:<4} "
                f"min={series['min']:<10} median={series['median']:<10} "
                f"p95={series['p95']:<10} max={series['max']} {series['unit']}"
            )
        else:
            print(f"{series['name']:<30} NOT_RUN: {series.get('reason', '')}")
    memory = document.get("memory", {})
    for name, value in memory.items():
        if isinstance(value, dict):
            if "rssBytes" in value:
                print(f"{name:<40} {value['rssBytes'] / (1024 * 1024):.1f} MiB RSS")
            elif "pssBytes" in value:
                print(f"{name:<40} {value['pssBytes'] / (1024 * 1024):.1f} MiB PSS")
            else:
                print(f"{name:<40} {value}")
        elif isinstance(value, list):
            for item in value:
                rss = item.get("rssBytes")
                pss = item.get("pssBytes")
                print(
                    f"{name:<40} pid={item.get('pid')} {item.get('name')} "
                    + (f"{rss / (1024 * 1024):.1f} MiB RSS " if rss else "")
                    + (f"{pss / (1024 * 1024):.1f} MiB PSS" if pss else "")
                )
    for note in document.get("notes", ()):
        print(f"note: {note}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("health", "slice", "gate", "measurements"))
    parser.add_argument("path", type=Path)
    arguments = parser.parse_args()
    document = json.loads(arguments.path.read_text(encoding="utf-8"))
    {"health": _health, "slice": _slice, "gate": _gate,
     "measurements": _measurements}[arguments.kind](document)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
