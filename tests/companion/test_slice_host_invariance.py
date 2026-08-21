# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The character slice measures the selector, not the machine it runs on.

This is the isolation defect §7 of the Phase 5 directive asks for, found and
closed. Its full history is in
``qualification/phase5/isolation/TEST_ISOLATION_INVESTIGATION.md``; the part
that matters here is the mechanism.

``CharacterPresenter`` builds ``base_signals`` from ``assess_current_machine()``
— the real host — and that is correct: on a real machine under real memory
pressure the companion *should* stop animating. Everything ``_VISUAL`` does not
name survives into every evaluation the slice performs.

``memory_pressure`` is read as Linux PSI, ``/proc/pressure/memory`` ``some
avg10 >= 0.1`` (``diagnostics.signals_from_assessment``) — a ten-second rolling
average of memory stall. A suite that has just run several thousand tests in one
process crosses it, intermittently, for reasons that have nothing to do with
this slice. When it was crossed the selector degraded to ``static-image``,
citing "memory pressure disabled animation", and the run failed:

    ['step 17 (trigger controlled presentation pressure)',
     'step 21 (recover only after hysteresis)']

with 18, 19 and 20 passing, **no renderer fault**, and the presenter healthy.
Measured rates before the fix: 0/20 for the class alone, 0/40 for the module
alone, 0/60 across every earlier neighbour, and roughly 2/28 for the whole
``tests/companion`` package — because it is the package that makes the host
stall, not any test in it.

**The second-order problem was worse than the failure.** Step 18 *declares*
``memory_pressure: True`` to prove the selector degrades. On a machine already
under ambient pressure the rung was static before step 18 asked, so step 18
passed without testing anything. Pinning these signals is therefore not
silencing a flake — it is what makes steps 17 to 21 measure the selector at all.

Three tests below: the outcome is invariant to the host, the checks still work,
and no future signal can reintroduce the hole.
"""

from __future__ import annotations

import ast
import re
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import companion.character.surface as surface
from companion.character.vertical_slice import _VISUAL, run_character_slice

ROOT = Path(__file__).resolve().parents[2]
ADAPTATION = ROOT / "companion" / "character" / "adaptation.py"

#: A host in the worst state the signal set can describe.
HOSTILE = {
    "memory_pressure": True,
    "thermal_pressure": True,
    "cpu_pressure": True,
    "on_battery": True,
    "battery_percent": 3.0,
}


class _HostileHost:
    """Make every presenter built inside the block read a machine in distress.

    Patches ``base_signals`` after construction rather than faking
    ``assess_current_machine``, so the assessment, the inventory and the plan
    are all the real ones and only the signals differ. A fake assessment would
    be testing a fake.
    """

    def __enter__(self):
        self._original = surface.CharacterPresenter.__init__
        original = self._original

        def patched(inner_self, *args, **kwargs):
            original(inner_self, *args, **kwargs)
            inner_self.base_signals = replace(inner_self.base_signals, **HOSTILE)

        surface.CharacterPresenter.__init__ = patched
        return self

    def __exit__(self, *exception):
        surface.CharacterPresenter.__init__ = self._original
        return False


def run() -> dict:
    with tempfile.TemporaryDirectory(prefix="bunny-invariance-") as root:
        return run_character_slice(Path(root)).to_json()


class TheOutcomeDoesNotDependOnTheHostTests(unittest.TestCase):
    def test_the_slice_passes_on_a_host_under_every_kind_of_pressure(self) -> None:
        with _HostileHost():
            document = run()
        self.assertTrue(document["passed"], document["failures"])

    def test_the_pressure_steps_reach_the_same_rungs_either_way(self) -> None:
        """Not just "it passes" — the same rungs, so a future assertion that
        looked at the presentation rather than at ``ok`` is also protected."""
        benign = {step["step"]: step for step in run()["steps"]}
        with _HostileHost():
            hostile = {step["step"]: step for step in run()["steps"]}
        for number in (17, 18, 19, 20, 21):
            with self.subTest(step=number):
                self.assertEqual(
                    hostile[number].get("presentation"),
                    benign[number].get("presentation"),
                    f"step {number} moved because of the host, not because of the slice",
                )

    def test_step_17_reaches_animated_2d_with_no_pressure_reason(self) -> None:
        """The positive statement, so a pass cannot come from a degraded rung.

        Without this, pinning the signals to *any* value would satisfy the two
        tests above.
        """
        with _HostileHost():
            steps = {step["step"]: step for step in run()["steps"]}
        self.assertEqual(steps[17]["presentation"], "animated-2d")
        reasons = " ".join(steps[17].get("reasons", []))
        self.assertNotIn("memory pressure", reasons)
        self.assertNotIn("battery", reasons)


class TheChecksStillWorkTests(unittest.TestCase):
    """The negative control. A fix that disables the assertion is not a fix."""

    def test_step_18_still_degrades_when_the_slice_declares_pressure(self) -> None:
        with _HostileHost():
            steps = {step["step"]: step for step in run()["steps"]}
        self.assertEqual(
            steps[18]["presentation"],
            "static-image",
            "declared memory pressure no longer degrades; the pin has silenced the check",
        )
        self.assertTrue(steps[18]["ok"])

    def test_step_19_still_degrades_to_text_only(self) -> None:
        with _HostileHost():
            steps = {step["step"]: step for step in run()["steps"]}
        self.assertEqual(steps[19]["presentation"], "text-only")


class NoFutureSignalCanReopenTheHoleTests(unittest.TestCase):
    """Every host-derived signal the ladder degrades on is pinned, or declared.

    The defect was one unpinned field. Listing the current five by hand would
    close today's hole and leave the next one open, so this reads
    ``adaptation.py`` and requires each signal it consults to be accounted for.
    """

    #: Signals the slice deliberately does not pin, each with the reason.
    #:
    #: These are either derived by the presenter from state the slice controls,
    #: or are the subject of a step rather than a precondition for one.
    DELIBERATELY_UNPINNED = {
        "renderer_healthy": "derived from the presenter's own health; the fault "
                            "tests exist to move it",
        "static_renderer_healthy": "set only by the presenter's last-rung fallback",
        "reduced_motion": "derived from the accessibility preferences the slice passes",
        "no_animation": "same",
        "three_d_available": "a package property, not a host reading",
        "three_d_healthy": "derived from the graphics context, which is None here",
        "gpu_context_lost": "requires a graphics context; the slice offers none",
        "user_preference": "the renderer mode, which the slice does not set",
        "model_gpu_bytes": "a 3D package property",
        # Read only inside `if requested in THREE_D` (adaptation.py:229), and
        # the slice's plan ceiling is animated-2d, so the branch is unreachable
        # here. A package property in any case, not a host reading.
        "package_supports_3d": "a package property, and only consulted for 3D rungs",
        "graphics_features_supported": "a 3D capability, unreachable without a context",
        "dropped_frame_ratio": "a runtime observation the slice's steps produce",
        "sustained_slow_frames": "same",
        "foreground_workload_high": "a runtime observation, not a host reading",
    }

    def signals_the_ladder_reads(self) -> set[str]:
        source = ADAPTATION.read_text(encoding="utf-8")
        tree = ast.parse(source)
        names: set[str] = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "signals"
            ):
                names.add(node.attr)
        return names

    def test_the_ladder_is_still_where_this_test_thinks_it_is(self) -> None:
        """A check that parsed the wrong file would pass by finding nothing."""
        self.assertTrue(ADAPTATION.is_file())
        self.assertGreater(len(self.signals_the_ladder_reads()), 10)

    def test_every_signal_the_ladder_reads_is_pinned_or_declared(self) -> None:
        unaccounted = sorted(
            name
            for name in self.signals_the_ladder_reads()
            if name not in _VISUAL and name not in self.DELIBERATELY_UNPINNED
        )
        self.assertEqual(
            unaccounted,
            [],
            "the presentation ladder reads these and the slice neither pins them nor "
            "declares why not; a host reading will leak into the result the way "
            "memory_pressure did",
        )

    def test_every_declared_exemption_is_still_read_by_the_ladder(self) -> None:
        """An exemption for a signal that no longer exists is one nobody reviews."""
        read = self.signals_the_ladder_reads()
        stale = sorted(name for name in self.DELIBERATELY_UNPINNED if name not in read)
        self.assertEqual(stale, [], "these exemptions no longer describe anything")

    def test_the_five_pressure_signals_are_pinned_by_name(self) -> None:
        """Named individually, because these are the ones that caused it."""
        for name in ("memory_pressure", "thermal_pressure", "cpu_pressure",
                     "on_battery", "battery_percent"):
            with self.subTest(signal=name):
                self.assertIn(name, _VISUAL)

    def test_the_psi_threshold_is_still_where_the_diagnosis_says(self) -> None:
        """Ties this file's explanation to the code it describes.

        If the reading moves — a different PSI field, a different threshold —
        the prose above becomes wrong, and prose that is wrong about a
        four-phase mystery is worse than none.
        """
        diagnostics = (ROOT / "companion" / "character" / "diagnostics.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("pressure_some_avg10", diagnostics)
        self.assertRegex(diagnostics, r"memory_pressure=.*pressure\s*>=\s*0\.1")


if __name__ == "__main__":
    unittest.main()
