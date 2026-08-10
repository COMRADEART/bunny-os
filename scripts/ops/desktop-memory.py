#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§24's memory figures: what the broker costs, and what it does not.

A development tool, not shipped.

Three numbers, measured in three separate processes rather than three points in
one, because a figure taken after something else has already been imported is a
figure about the import order:

``interpreterBaseline``
    a Python that has imported nothing of this repository.
``desktopBrokerIdle``
    that, plus a started :class:`~companion.desktop.broker.DesktopActionBroker`
    with its nine adapters probed and idle. The difference is what the broker
    costs to have.
``companionStack``
    a whole :class:`~companion.service.CompanionService` with the broker in it.
    Reported separately because §24 asks for the stack and the broker to be
    distinguishable, and a reader given only the total cannot.

Per-adapter figures are measured by constructing one adapter at a time in a
fresh interpreter. They are small and they are *not* additive: the adapters
share a session-bus connection and a GObject introspection typelib, so the sum
of the nine is larger than the set of nine. Reported as measured, with that said
rather than left for a reader to be surprised by.

**The desktop application's own memory is not here and must not be.** A launched
application is a separate process this build started and does not own; counting
it against the broker would make the broker look like it costs what GNOME
Settings costs.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

SCHEMA = "bunny-os/desktop-action-memory/1"

#: One adapter per line, constructed and probed alone.
_ADAPTERS = (
    ("NotificationAdapter", "companion.desktop.adapters.notification", "NotificationAdapter"),
    ("ApplicationLaunchAdapter", "companion.desktop.adapters.application", "ApplicationLaunchAdapter"),
    ("ApplicationPresentAdapter", "companion.desktop.adapters.application", "ApplicationPresentAdapter"),
    ("SettingsAdapter", "companion.desktop.adapters.settings", "SettingsAdapter"),
    ("AudioControlAdapter", "companion.desktop.adapters.audio", "AudioControlAdapter"),
    ("ClipboardAdapter", "companion.desktop.adapters.clipboard", "ClipboardAdapter"),
    ("UriOpenAdapter", "companion.desktop.adapters.uri", "UriOpenAdapter"),
    ("FileRevealAdapter", "companion.desktop.adapters.filereveal", "FileRevealAdapter"),
    ("PortalAdapter", "companion.desktop.adapters.portal", "PortalAdapter"),
)

_PROBE = """
import json, sys, time

def figures():
    rss = pss = 0
    try:
        with open("/proc/self/status", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    rss = int(line.split()[1]) * 1024
    except OSError:
        pass
    try:
        with open("/proc/self/smaps_rollup", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("Pss:"):
                    pss = int(line.split()[1]) * 1024
    except OSError:
        pass
    return {"rssBytes": rss, "pssBytes": pss}

WHAT = sys.argv[1]
held = None
if WHAT == "baseline":
    pass
elif WHAT == "broker":
    from companion.desktop.broker import BrokerOptions, DesktopActionBroker
    held = DesktopActionBroker(BrokerOptions()).start()
    held.environment(refresh=True)
elif WHAT == "stack":
    import tempfile
    from pathlib import Path
    from companion.service import CompanionService, ServiceOptions
    directory = tempfile.mkdtemp(prefix="bunny-mem-")
    held = CompanionService(ServiceOptions(
        root=Path(directory), voice_enabled=False, speech_enabled=False,
    ))
    held.start()
elif WHAT == "stack-no-desktop":
    import tempfile
    from pathlib import Path
    from companion.service import CompanionService, ServiceOptions
    directory = tempfile.mkdtemp(prefix="bunny-mem-")
    held = CompanionService(ServiceOptions(
        root=Path(directory), voice_enabled=False, speech_enabled=False,
        desktop_enabled=False,
    ))
    held.start()
else:
    module, name = WHAT.split(":", 1)
    import importlib
    held = getattr(importlib.import_module(module), name)()
    held.probe()

value = figures()
print(json.dumps(value))
try:
    if hasattr(held, "close"):
        held.close()
    elif hasattr(held, "stop"):
        held.stop()
except Exception:
    pass
"""


def _measure(what: str, *, root: Path, repeats: int = 3) -> dict[str, Any]:
    """One figure, taken in a fresh interpreter, the median of a few runs.

    Fresh because a measurement taken after something else has imported is a
    measurement of the import order. Median because the allocator's first
    arena is not deterministic and a single sample carries that noise into a
    number somebody will compare against next month's.
    """
    samples: list[dict[str, int]] = []
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(root)
    for _ in range(repeats):
        completed = subprocess.run(
            [sys.executable, "-c", _PROBE, what],
            capture_output=True, text=True, cwd=str(root), env=environment,
            timeout=180, check=False,
        )
        if completed.returncode != 0:
            return {
                "result": "NOT_RUN",
                "reason": (completed.stderr or "").strip().splitlines()[-1:] or ["failed"],
            }
        try:
            samples.append(json.loads(completed.stdout.strip().splitlines()[-1]))
        except (ValueError, IndexError):
            return {"result": "NOT_RUN", "reason": ["the probe produced no figure"]}
    return {
        "rssBytes": sorted(item["rssBytes"] for item in samples)[len(samples) // 2],
        "pssBytes": sorted(item["pssBytes"] for item in samples)[len(samples) // 2],
        "samples": len(samples),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    baseline = _measure("baseline", root=args.root)
    broker = _measure("broker", root=args.root)
    stack = _measure("stack", root=args.root)
    without = _measure("stack-no-desktop", root=args.root)

    def _difference(bigger: dict[str, Any], smaller: dict[str, Any]) -> dict[str, Any]:
        if "rssBytes" not in bigger or "rssBytes" not in smaller:
            return {"result": "NOT_RUN", "reason": ["one side was not measured"]}
        return {
            "rssBytes": bigger["rssBytes"] - smaller["rssBytes"],
            "pssBytes": bigger["pssBytes"] - smaller["pssBytes"],
        }

    document = {
        "schemaVersion": SCHEMA,
        "interpreterBaseline": baseline,
        "desktopBrokerIdle": broker,
        "desktopBrokerCost": _difference(broker, baseline),
        "companionStack": stack,
        "companionStackWithoutDesktop": without,
        "desktopCostInStack": _difference(stack, without),
        "perAdapter": {
            name: _measure(f"{module}:{attribute}", root=args.root, repeats=2)
            for name, module, attribute in _ADAPTERS
        },
        "notes": [
            "Every figure is taken in a fresh interpreter; a measurement made after "
            "something else has imported is a measurement of the import order.",
            "Per-adapter figures are not additive: the adapters share a session-bus "
            "connection and the GObject typelib, so the sum of the nine exceeds the set.",
            "A launched application's memory is not counted. It is a separate process "
            "this build started and does not own.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        key: document[key]
        for key in ("desktopBrokerIdle", "desktopBrokerCost", "companionStack", "desktopCostInStack")
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
