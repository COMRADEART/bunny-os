# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Every periodic timer in the desktop can be attributed.

§9 of the Phase 5 directive: instrument each poller, measure poll count, CPU
time, wall time, render count and data changes, and *"determine which poller
contributes most to idle CPU. Do not guess."*

Phase 4 guessed, reasonably, and named the System overview card's two-second
refresh. Half of that guess has since been measured and cleared: the four
`/proc` and `/sys` reads the card performs cost 117 microseconds per tick,
which is 0.006% of one core against a 1.27-point regression — smaller by a
factor of two hundred
(`qualification/phase5/performance/POLLER_DATA_SOURCE_COST.md`).

The other half — the redraw, which in a guest with no GPU is composited by
llvmpipe on the CPU — can only be measured inside a running shell. That is what
`util.js` now instruments, and this file is what keeps the instrumentation
complete.

**The property that matters is completeness, not correctness.** A timer that is
not named still runs and still costs; it simply does not appear in the report,
and the poller that never appears is the one that gets blamed last. So the
check is that no `interval()` call site anywhere in the desktop is anonymous.

These are source-inspection tests, like the rest of `tests/shell`. The desktop
is JavaScript inside a compositor and there is no compositor here.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXTENSION = ROOT / "shell" / "components" / "gnome-shell-extension"
UTIL = EXTENSION / "lib" / "util.js"


def javascript_files() -> list[Path]:
    return sorted(EXTENSION.rglob("*.js"))


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def strip_comments(source: str) -> str:
    """Remove // and /* */ comments so prose does not answer for code.

    Crude on purpose: it would mangle a `//` inside a string literal. No call
    site in this codebase has one, and a parser for a check this size would be
    the more fragile choice.
    """
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("//")
    )


class EveryTimerIsNamedTests(unittest.TestCase):
    def test_there_are_interval_call_sites_to_check(self) -> None:
        """A sweep that found none would pass for ever."""
        sites = [
            path
            for path in javascript_files()
            if path != UTIL and re.search(r"\binterval\(", strip_comments(text(path)))
        ]
        self.assertGreaterEqual(len(sites), 4)

    def test_no_interval_call_site_is_anonymous(self) -> None:
        """An unnamed timer runs, costs, and does not appear in the report.

        `interval()` gives an unnamed caller `unnamed:<seconds>s` rather than
        dropping it, so the measurement stays honest either way — but a
        deliberate name is what makes the report readable, and a new poller
        added without one is a poller nobody will think to look at.
        """
        anonymous: list[str] = []
        for path in javascript_files():
            if path == UTIL:
                continue
            source = strip_comments(text(path))
            for match in re.finditer(r"\binterval\(", source):
                # Take the balanced call by scanning forward; the callbacks are
                # multi-line arrow functions, so a line-based regex cannot see
                # the options object.
                depth, index = 0, match.end() - 1
                while index < len(source):
                    if source[index] == "(":
                        depth += 1
                    elif source[index] == ")":
                        depth -= 1
                        if depth == 0:
                            break
                    index += 1
                call = source[match.start(): index + 1]
                if "name:" not in call:
                    line = source[: match.start()].count("\n") + 1
                    anonymous.append(f"{path.relative_to(ROOT)}:{line}")
        self.assertEqual(
            anonymous,
            [],
            "these timers cannot be attributed in the poller report; pass {name: '...'}",
        )

    def test_the_named_pollers_cover_the_ones_phase_4_suspected(self) -> None:
        """The three cadences Phase 4's report named are individually visible.

        Named rather than counted, so that renaming one to something generic
        does not quietly satisfy this.
        """
        source = "\n".join(strip_comments(text(path)) for path in javascript_files())
        for expected in ("dock.running-apps", "topbar.indicators", "shell.housekeeping"):
            with self.subTest(poller=expected):
                self.assertIn(expected, source)
        # The cards name themselves from their own title, so the report
        # distinguishes the System card from the media widget without a second
        # list to keep in step.
        self.assertIn("card.${this.title}", source)


class TheInstrumentationItselfTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = text(UTIL)

    def test_the_report_and_its_reset_are_exported(self) -> None:
        self.assertIn("export function pollerMetrics()", self.source)
        self.assertIn("export function resetPollerMetrics()", self.source)

    def test_a_tick_that_throws_is_still_counted(self) -> None:
        """A poller whose cost only appears when it succeeds hides the
        expensive failure.

        The accounting has to sit after the try/catch, not inside the try.
        """
        body = self.source.split("export function interval(", 1)[1]
        try_index = body.index("try {")
        catch_index = body.index("} catch (error) {")
        accounting = body.index("record.wallMicroseconds += elapsed")
        self.assertGreater(
            accounting, catch_index, "the tick accounting is inside the try; a throwing tick would not be counted"
        )
        self.assertGreater(catch_index, try_index)
        self.assertIn("record.errors += 1", body)

    def test_changes_are_counted_only_when_reported(self) -> None:
        """`undefined` means "not reported", not "did not change".

        §10 turns on how often the data actually changed. A poller that has
        never been asked to answer must not be recorded as having answered no,
        because a change count of zero is exactly the evidence that would
        justify lengthening its cadence.
        """
        body = self.source.split("export function interval(", 1)[1]
        self.assertIn("if (changed === true)", body)
        self.assertNotIn("if (changed)", body)

    def test_cpu_time_is_not_claimed_per_tick(self) -> None:
        """The report must not carry a number it cannot honestly produce.

        /proc/self/stat has 10 ms resolution, so nearly every 117-microsecond
        tick would read zero, and reading it costs 19 microseconds — a 16%
        instrument overhead on the thing being measured. The report gives wall
        time and a share, and the probe attributes process CPU across it.
        """
        self.assertNotIn("cpuMicroseconds", self.source)
        self.assertIn("wallShare", self.source)

    def test_the_measurement_window_is_resettable(self) -> None:
        """Otherwise every figure is since-session-start, which on a session
        that has just completed a login journey is a number about the journey.

        The same distinction the performance probe already makes between a
        delta and an average since process start.
        """
        body = self.source.split("export function resetPollerMetrics()", 1)[1]
        for field in ("ticks", "changes", "errors", "wallMicroseconds"):
            with self.subTest(field=field):
                self.assertIn(f"record.{field} = 0", body)
        self.assertIn("_pollerEpoch = GLib.get_monotonic_time()", body)


if __name__ == "__main__":
    unittest.main()
