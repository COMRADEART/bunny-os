#!/usr/bin/python3
"""Measure deterministic host-side Bunny Shell operations.

These are not graphical login/GPU measurements and are labelled accordingly.
"""

from __future__ import annotations

import json
from pathlib import Path
import statistics
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shell/services"))

from bunny_shell.launcher import route_intent
from bunny_shell.search import SearchIndex
from bunny_shell.settings import SettingsStore
from bunny_shell.workspaces import WorkspaceStore


def measure(function, iterations: int = 200) -> dict[str, float]:
    samples = []
    for _ in range(iterations):
        start = time.perf_counter_ns()
        function()
        samples.append((time.perf_counter_ns() - start) / 1_000_000)
    ordered = sorted(samples)
    return {
        "medianMs": round(statistics.median(ordered), 4),
        "p95Ms": round(ordered[max(0, int(len(ordered) * 0.95) - 1)], 4),
        "maxMs": round(max(ordered), 4),
    }


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        project = root / "project"; project.mkdir()
        search = SearchIndex(root / "search.json", root / "index.json")
        search.add(str(project)); (project / "README.md").write_text("test", encoding="utf-8"); search.rebuild()
        workspaces = WorkspaceStore(root / "workspaces.json")
        workspaces.create("Benchmark", str(project))
        settings = SettingsStore(root / "settings.json")
        result = {
            "schemaVersion": 1,
            "scope": "host-side deterministic operations only; no graphical/GPU/VM claim",
            "intentRouting": measure(lambda: route_intent("Open network settings")),
            "metadataSearch": measure(lambda: search.query("readme")),
            "workspaceRead": measure(lambda: workspaces.list()),
            "settingsRead": measure(lambda: settings.get_all()),
            "unmeasured": ["login", "launcher window", "workspace switch", "settings window", "notification render", "command surface window", "idle memory", "idle CPU", "idle GPU"],
        }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
