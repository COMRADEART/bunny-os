"""The committed comparison must be small without becoming less true.

Collecting all seventeen dimensions from the beta profile produces 71 MB per
builder — 164,962 filesystem entries, 104,247 file digests. A committed evidence
file cannot be 140 MB, and the obvious shortcuts are both wrong: storing only a
sample would miss a difference outside it, and storing only a digest would report
"they differ" without saying where.

The reduced form keeps a digest over the whole value, so equality is preserved
exactly, plus every differing member name up to a recorded cap. These tests hold
that: nothing that differed in full may compare equal here.
"""

from __future__ import annotations

import json
from pathlib import Path
import random
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from release.comparison import (  # noqa: E402
    COMPARISON_DIMENSIONS,
    compare_dimension,
    reduce_dimension as _reduce_dimension,
)


def big_mapping(count: int = 20000, seed: int = 1) -> dict[str, str]:
    rng = random.Random(seed)
    return {
        f"usr/share/doc/package-{index}/file-{index}": f"{rng.getrandbits(256):064x}"
        for index in range(count)
    }


def state(left, right, dimension: str = "fileDigests") -> tuple[str, tuple[str, ...]]:
    pair, _, detail = _reduce_dimension(left, right)
    pair["detail"] = detail
    result = compare_dimension(dimension, pair)
    return result.state, result.differences


class SizeTests(unittest.TestCase):
    def test_a_small_dimension_is_stored_verbatim(self) -> None:
        pair, form, _ = _reduce_dimension(["sha256:a", "sha256:b"], ["sha256:a", "sha256:b"])
        self.assertEqual(form, "verbatim")
        self.assertEqual(pair["first"], ["sha256:a", "sha256:b"])

    def test_a_large_dimension_is_reduced(self) -> None:
        value = big_mapping()
        pair, form, _ = _reduce_dimension(value, value)
        self.assertEqual(form, "digest+differences")
        self.assertIn("__digest__", pair["first"])
        self.assertEqual(pair["first"]["__memberCount__"], len(value))

    def test_the_reduced_form_is_far_smaller_than_the_value(self) -> None:
        value = big_mapping()
        pair, _, _ = _reduce_dimension(value, value)
        self.assertLess(len(json.dumps(pair)), len(json.dumps(value)) // 100)


class EqualityIsPreservedTests(unittest.TestCase):
    def test_identical_large_mappings_match(self) -> None:
        value = big_mapping()
        self.assertEqual(state(value, dict(value))[0], "MATCH")

    def test_one_changed_member_among_twenty_thousand_differs_and_is_named(self) -> None:
        left = big_mapping()
        right = dict(left)
        target = sorted(right)[9999]
        right[target] = "0" * 64
        result, differences = state(left, right)
        self.assertEqual(result, "DIFFER")
        self.assertIn(target, differences)

    def test_a_member_present_on_one_side_only_is_named(self) -> None:
        left = big_mapping()
        right = dict(left)
        removed = sorted(right)[0]
        del right[removed]
        result, differences = state(left, right)
        self.assertEqual(result, "DIFFER")
        self.assertIn(removed, differences)

    def test_a_member_added_on_one_side_only_is_named(self) -> None:
        left = big_mapping()
        right = dict(left)
        right["usr/bin/backdoor"] = "f" * 64
        result, differences = state(left, right)
        self.assertEqual(result, "DIFFER")
        self.assertIn("usr/bin/backdoor", differences)

    def test_every_single_member_change_is_detected(self) -> None:
        # Not a sample: a difference anywhere must be caught, including in the
        # members a sample-based form would have dropped.
        left = big_mapping(count=2000)
        keys = sorted(left)
        for index in (0, 1, 500, 1500, 1998, 1999):
            with self.subTest(member=index):
                right = dict(left)
                right[keys[index]] = "9" * 64
                self.assertEqual(state(left, right)[0], "DIFFER")

    def test_a_large_list_dimension_reduces_and_still_compares(self) -> None:
        left = [f"package-{index}@1.{index}" for index in range(20000)]
        right = list(left)
        self.assertEqual(state(left, right, "packageInventory")[0], "MATCH")
        right[7] = "package-7@9.9"
        result, differences = state(left, right, "packageInventory")
        self.assertEqual(result, "DIFFER")
        self.assertIn("package-7@9.9", differences)


class DifferenceCapTests(unittest.TestCase):
    def test_the_cap_is_recorded_when_it_is_reached(self) -> None:
        left = big_mapping(count=20000)
        right = {key: "0" * 64 for key in left}
        pair, _, detail = _reduce_dimension(left, right)
        self.assertIn("20000 differing", detail)
        self.assertIn("first 200 recorded", detail)

    def test_the_true_difference_count_is_never_understated(self) -> None:
        left = big_mapping(count=20000)
        right = dict(left)
        for key in sorted(right)[:500]:
            right[key] = "0" * 64
        _, _, detail = _reduce_dimension(left, right)
        self.assertIn("500 differing", detail)

    def test_a_capped_comparison_still_reports_differ(self) -> None:
        left = big_mapping(count=20000)
        right = {key: "0" * 64 for key in left}
        self.assertEqual(state(left, right)[0], "DIFFER")


class NotCollectedTests(unittest.TestCase):
    def test_a_none_on_either_side_stays_none(self) -> None:
        for left, right in ((None, big_mapping()), (big_mapping(), None), (None, None)):
            with self.subTest():
                pair, form, detail = _reduce_dimension(left, right)
                self.assertEqual(form, "verbatim")
                self.assertIn("not collected from", detail)

    def test_two_absent_values_are_not_collected_rather_than_matching(self) -> None:
        self.assertEqual(state(None, None, "selinuxLabels")[0], "NOT_COLLECTED")

    def test_every_dimension_name_round_trips(self) -> None:
        for name, _, _ in COMPARISON_DIMENSIONS:
            with self.subTest(dimension=name):
                pair, _, detail = _reduce_dimension({"a": "1"}, {"a": "1"})
                pair["detail"] = detail
                self.assertEqual(compare_dimension(name, pair).state, "MATCH")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
