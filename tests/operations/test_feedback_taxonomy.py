# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The feedback taxonomy can name the things Alpha testers will report.

Two properties, and the second is the one with a history.

**One list, two files.** ``operations/taxonomy.py`` and
``schemas/beta-feedback.schema.json`` both enumerate the components a report
may be filed under. Two copies of a list are two chances to update one of them,
and the failure is silent in the worst direction: the importer would accept a
component the schema rejects, or the schema would advertise one the importer
refuses.

**It covers the product that exists.** The taxonomy was cut on 2026-07-29.
Since then the project has built the Companion runtime, the voice runtime, the
Trust prompt and App Capsules — and §21 of the Phase 5 directive asks for Alpha
feedback about exactly those, by name: *Companion — usefulness, distraction,
mode selection, responsiveness. Voice — recognition, latency, interruption,
confidence. Permissions — understandable? too frequent? trustworthy?*

None of them had a component. An alpha tester reporting "Bunny did not hear me"
would have had to choose between ``Audio``, which is the sound stack rather
than the speech runtime, and ``Bunny Core``, which is everything. A feedback
instrument that cannot name the thing being reported does not answer
"unknown" — it produces a misclassification that looks like data, and the
resulting counts are then quoted.

This test is the thing that notices next time, because the next subsystem will
also be built after the taxonomy was written.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from operations.taxonomy import COMPONENTS, SEVERITIES, SEVERITY_CRITERIA

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schemas" / "beta-feedback.schema.json"


def schema_document() -> dict:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def schema_enum(field: str) -> list[str]:
    return schema_document()["$defs"]["report"]["properties"][field]["enum"]


class TheTwoDeclarationsAgreeTests(unittest.TestCase):
    def test_the_component_lists_are_identical_and_in_the_same_order(self) -> None:
        """Order too, not just membership.

        A set comparison would pass while the two files disagreed about which
        component a positional index means, and the importer's diagnostics
        quote positions.
        """
        self.assertEqual(list(COMPONENTS), schema_enum("component"))

    def test_the_severity_lists_are_identical(self) -> None:
        self.assertEqual(list(SEVERITIES), schema_enum("severity"))

    def test_every_severity_carries_a_criterion(self) -> None:
        """A severity nobody can apply consistently is a severity that means nothing."""
        self.assertEqual(sorted(SEVERITY_CRITERIA), sorted(SEVERITIES))
        for name, criterion in SEVERITY_CRITERIA.items():
            with self.subTest(severity=name):
                self.assertTrue(criterion.strip())

    def test_no_component_is_listed_twice(self) -> None:
        self.assertEqual(len(COMPONENTS), len(set(COMPONENTS)))


class TheTaxonomyCoversTheShippedProductTests(unittest.TestCase):
    """Every subsystem §21 asks Alpha testers about has somewhere to go.

    Named individually rather than counted, so that adding a component does not
    quietly satisfy this test without adding the right one.
    """

    #: subsystem -> the component an Alpha report about it must be filed under.
    REQUIRED = {
        "the Companion character and its modes": "Companion",
        "speech in and speech out": "Voice",
        "the permission prompt and its decisions": "Trust",
        "confined applications": "App capsules",
        "first boot and the setup wizard": "Installer",
        "the desktop a person lands on": "Bunny Desktop",
        "coming back after a reboot": "Boot",
    }

    def test_each_alpha_feedback_subject_has_a_component(self) -> None:
        for subject, component in self.REQUIRED.items():
            with self.subTest(subject=subject):
                self.assertIn(
                    component,
                    COMPONENTS,
                    f"an Alpha report about {subject} has nowhere to be filed",
                )

    def test_the_schema_accepts_each_of_them_too(self) -> None:
        enum = schema_enum("component")
        for subject, component in self.REQUIRED.items():
            with self.subTest(subject=subject):
                self.assertIn(component, enum)

    def test_the_validator_accepts_them_and_still_refuses_an_invented_one(self) -> None:
        """The negative control. A validator that accepts everything is not one."""
        from operations.taxonomy import validate_component

        for component in self.REQUIRED.values():
            self.assertEqual(validate_component(component), component)
        for invented in ("Companion runtime", "voice", "Trust prompt", ""):
            with self.subTest(invented=invented):
                with self.assertRaises(ValueError):
                    validate_component(invented)


class ReproducibilityIsRecordedTests(unittest.TestCase):
    """§21: "Do not turn anecdotal feedback into technical claims without
    reproduction."

    The schema already carries the field that makes that enforceable. This
    asserts it stays, and that ``not_reproduced`` and ``unknown`` remain
    distinguishable from ``once`` — an anecdote nobody has tried to reproduce
    and one that could not be reproduced are different facts, and collapsing
    them is how a report becomes a claim.
    """

    def test_reproducibility_distinguishes_untried_from_failed(self) -> None:
        values = schema_enum("reproducibility")
        for required in ("always", "intermittent", "once", "not_reproduced", "unknown"):
            self.assertIn(required, values)

    def test_verification_status_distinguishes_reported_from_reproduced(self) -> None:
        values = schema_enum("verificationStatus")
        self.assertIn("unverified", values)
        self.assertIn("reproduced", values)
        self.assertNotEqual(values.index("unverified"), values.index("reproduced"))


if __name__ == "__main__":
    unittest.main()
