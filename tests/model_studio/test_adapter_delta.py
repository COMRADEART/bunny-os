# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The comparison the evidence gate turns on, tested without torch.

This file exists because of a specific defect. The comparison was written as

    reference = initial.get(name) or initial.get(other)

which reads as "this, else that" and is a ``RuntimeError`` on every tensor it
finds: ``or`` asks the first result whether it is truthy, and a torch tensor
with more than one element refuses to answer. Three end-to-end runs trained
correctly, saved a correct adapter, and then crashed in the evaluation that was
supposed to prove they had worked.

So the fake tensor here raises from ``__bool__`` exactly as torch does. It is
not a convenience stand-in — that single behaviour is the whole point of it, and
a stand-in that quietly returned ``True`` would let the defect back in.
"""

from __future__ import annotations

import unittest

from model_studio.backend.transformers_lora import _compare_to_initial


class FakeTensor:
    """Enough of a tensor to be compared, and torch's refusal to be a boolean."""

    def __init__(self, values: list[float]) -> None:
        self.values = list(values)

    # -- the behaviour this file exists for -------------------------------- #
    def __bool__(self) -> bool:
        if len(self.values) > 1:
            raise RuntimeError("Boolean value of Tensor with more than one value is ambiguous")
        return bool(self.values[0])

    # -- the rest of the surface `_compare_to_initial` uses ----------------- #
    @property
    def shape(self) -> tuple[int, ...]:
        return (len(self.values),)

    def detach(self) -> "FakeTensor":
        return self

    def cpu(self) -> "FakeTensor":
        return self

    def float(self) -> "FakeTensor":
        return self

    def abs(self) -> "FakeTensor":
        return FakeTensor([abs(value) for value in self.values])

    def max(self) -> "FakeTensor":
        return FakeTensor([max(self.values)])

    def item(self) -> float:
        return float(self.values[0])

    def __sub__(self, other: "FakeTensor") -> "FakeTensor":
        return FakeTensor([a - b for a, b in zip(self.values, other.values)])


class FakeModel:
    def __init__(self, parameters: dict[str, FakeTensor]) -> None:
        self._parameters = parameters

    def named_parameters(self):
        return list(self._parameters.items())


class AgainstASnapshot(unittest.TestCase):
    def test_it_counts_the_tensors_that_moved(self) -> None:
        initial = {
            "base_model.model.layers.0.self_attn.q_proj.lora_A.default.weight":
                FakeTensor([0.1, 0.2, 0.3]),
            "base_model.model.layers.0.self_attn.q_proj.lora_B.default.weight":
                FakeTensor([0.0, 0.0, 0.0]),
        }
        trained = {
            "base_model.model.layers.0.self_attn.q_proj.lora_A.default.weight":
                FakeTensor([0.1, 0.25, 0.3]),
            "base_model.model.layers.0.self_attn.q_proj.lora_B.default.weight":
                FakeTensor([0.0, 0.0, 0.0]),
        }
        changed, total, largest = _compare_to_initial(FakeModel(trained), initial)
        self.assertEqual(total, 2)
        self.assertEqual(changed, 1)
        self.assertAlmostEqual(largest, 0.05)

    def test_an_untrained_adapter_reports_nothing_changed(self) -> None:
        """The failure that looks most like success."""
        initial = {"m.lora_A.default.weight": FakeTensor([0.1, 0.2])}
        same = {"m.lora_A.default.weight": FakeTensor([0.1, 0.2])}
        changed, total, largest = _compare_to_initial(FakeModel(same), initial)
        self.assertEqual((changed, total, largest), (0, 1, 0.0))

    def test_non_adapter_parameters_are_not_counted(self) -> None:
        model = FakeModel({
            "base_model.model.layers.0.mlp.up_proj.weight": FakeTensor([1.0, 2.0]),
            "base_model.model.layers.0.mlp.up_proj.lora_A.default.weight": FakeTensor([1.0, 2.0]),
        })
        _, total, _ = _compare_to_initial(model, {})
        self.assertEqual(total, 1, "only lora_* parameters are adapter tensors")

    def test_a_multi_element_tensor_is_never_asked_for_its_truth(self) -> None:
        """The regression itself: a lookup miss must not become a boolean test."""
        initial = {"other.name.lora_A.default.weight": FakeTensor([0.5, 0.5, 0.5])}
        trained = {"m.lora_A.default.weight": FakeTensor([0.5, 0.5, 0.5])}
        # Before the fix this raised RuntimeError from `dict.get(...) or ...`.
        changed, total, _ = _compare_to_initial(FakeModel(trained), initial)
        self.assertEqual(total, 1)
        self.assertEqual(changed, 0, "no lora_B, no snapshot entry: nothing established")

    def test_the_prefix_fallback_finds_a_renamed_key(self) -> None:
        initial = {"layers.0.q_proj.lora_B.default.weight": FakeTensor([0.0, 0.0])}
        trained = {"base_model.model.layers.0.q_proj.lora_B.default.weight":
                   FakeTensor([0.0, 0.4])}
        changed, _, largest = _compare_to_initial(FakeModel(trained), initial)
        self.assertEqual(changed, 1)
        self.assertAlmostEqual(largest, 0.4)


class WithoutASnapshot(unittest.TestCase):
    """Evaluating a run this process did not train falls back to PEFT's contract."""

    def test_a_nonzero_lora_b_is_evidence(self) -> None:
        model = FakeModel({"m.lora_B.default.weight": FakeTensor([0.0, 0.3])})
        changed, total, largest = _compare_to_initial(model, {})
        self.assertEqual((changed, total), (1, 1))
        self.assertAlmostEqual(largest, 0.3)

    def test_a_zero_lora_b_is_not(self) -> None:
        model = FakeModel({"m.lora_B.default.weight": FakeTensor([0.0, 0.0])})
        changed, total, largest = _compare_to_initial(model, {})
        self.assertEqual((changed, total, largest), (0, 1, 0.0))

    def test_lora_a_alone_establishes_nothing(self) -> None:
        """lora_A is randomly initialised; non-zero says nothing about training."""
        model = FakeModel({"m.lora_A.default.weight": FakeTensor([0.9, 0.9])})
        changed, total, _ = _compare_to_initial(model, {})
        self.assertEqual((changed, total), (0, 1))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
