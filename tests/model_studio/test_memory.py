# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The memory model: derived, checkable, and ``None`` when it cannot be derived.

The parameter count is checked against a published figure rather than against
itself. An estimator built on arithmetic that is wrong by a factor would agree
with every test written from the same arithmetic.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from model_studio.memory import (
    DTYPE_BYTES,
    adapter_parameters,
    estimate_training_memory,
    resolve_batch_size,
)
from model_studio.models import read_architecture
from tests.model_studio.support import SMOLLM2_135M_CONFIG, write_model_config


def _architecture(document: dict | None = None):
    with tempfile.TemporaryDirectory() as scratch:
        write_model_config(Path(scratch), document)
        return read_architecture(Path(scratch))


class ParameterCount(unittest.TestCase):
    def test_smollm2_135m(self) -> None:
        """The published size is 135M. The arithmetic must land on it, not near it."""
        architecture = _architecture()
        self.assertEqual(architecture.parameter_count, 134_515_008)

    def test_untied_embeddings_add_an_output_projection(self) -> None:
        tied = _architecture().parameter_count
        untied = _architecture({**SMOLLM2_135M_CONFIG, "tie_word_embeddings": False}).parameter_count
        self.assertEqual(untied - tied, 49152 * 576)

    def test_an_unknown_architecture_is_none_not_a_guess(self) -> None:
        self.assertIsNone(_architecture({**SMOLLM2_135M_CONFIG, "model_type": "mamba"}))
        self.assertIsNone(_architecture({"model_type": "llama"}))

    def test_a_missing_config_is_none(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            self.assertIsNone(read_architecture(Path(scratch)))


class AdapterCount(unittest.TestCase):
    def test_it_is_exact(self) -> None:
        architecture = _architecture()
        hidden, layers = 576, 30
        projected = 9 * 64
        key_value = 3 * 64
        rank = 16
        expected = layers * rank * (
            (hidden + projected)      # q_proj
            + (hidden + key_value)    # k_proj
            + (hidden + key_value)    # v_proj
            + (projected + hidden)    # o_proj
        )
        counted = adapter_parameters(
            architecture, rank=rank, target_modules=("q_proj", "k_proj", "v_proj", "o_proj")
        )
        self.assertEqual(counted, expected)

    def test_rank_scales_it_linearly(self) -> None:
        architecture = _architecture()
        small = adapter_parameters(architecture, rank=8, target_modules=("q_proj",))
        large = adapter_parameters(architecture, rank=16, target_modules=("q_proj",))
        self.assertEqual(large, small * 2)

    def test_an_unknown_target_makes_the_whole_figure_none(self) -> None:
        self.assertIsNone(
            adapter_parameters(_architecture(), rank=8, target_modules=("q_proj", "fc_in"))
        )


class Estimate(unittest.TestCase):
    def _estimate(self, **overrides):
        arguments = dict(
            dtype="bf16", base_dtype="bf16", batch_size=1, sequence_length=512,
            rank=16, target_modules=("q_proj", "k_proj", "v_proj", "o_proj"),
            gradient_checkpointing=True, quantization_bits=0,
        )
        arguments.update(overrides)
        return estimate_training_memory(_architecture(), **arguments)

    def test_the_base_weights_dominate_a_small_run(self) -> None:
        estimate = self._estimate()
        self.assertEqual(estimate.components["baseWeights"], int(134_515_008 * 2))
        self.assertGreater(estimate.total_bytes, estimate.components["baseWeights"])

    def test_quantization_shrinks_the_weights_and_names_its_overhead(self) -> None:
        full = self._estimate()
        quantized = self._estimate(base_dtype="nf4", quantization_bits=4)
        self.assertLess(
            quantized.components["baseWeights"], full.components["baseWeights"] / 3
        )
        self.assertIn("quantizationConstants", quantized.components)

    def test_checkpointing_reduces_activations(self) -> None:
        with_it = self._estimate(gradient_checkpointing=True)
        without = self._estimate(gradient_checkpointing=False)
        self.assertLess(with_it.components["activations"], without.components["activations"])

    def test_batch_size_scales_activations_linearly(self) -> None:
        one = self._estimate(batch_size=1).components["activations"]
        four = self._estimate(batch_size=4).components["activations"]
        self.assertEqual(four, one * 4)

    def test_an_unknown_architecture_estimates_to_none(self) -> None:
        self.assertIsNone(estimate_training_memory(
            None, dtype="bf16", base_dtype="bf16", batch_size=1, sequence_length=512,
            rank=16, target_modules=("q_proj",), gradient_checkpointing=True,
        ))

    def test_it_carries_its_formula_and_its_exclusions(self) -> None:
        estimate = self._estimate()
        self.assertIn("baseWeights = parameters", estimate.formula)
        self.assertTrue(estimate.excludes)
        self.assertTrue(any("fragmentation" in item for item in estimate.excludes))

    def test_every_dtype_has_a_byte_width(self) -> None:
        for name in ("bf16", "fp16", "fp32", "nf4", "int8"):
            self.assertIn(name, DTYPE_BYTES)


class BatchSize(unittest.TestCase):
    def test_an_explicit_size_is_kept(self) -> None:
        size, reason = resolve_batch_size(4, available_bytes=None, estimate_for=lambda _: None)
        self.assertEqual(size, 4)
        self.assertIn("given in the configuration", reason)

    def test_unmeasurable_memory_resolves_to_one_and_says_so(self) -> None:
        size, reason = resolve_batch_size(
            "auto", available_bytes=None, estimate_for=lambda _: None
        )
        self.assertEqual(size, 1)
        self.assertIn("conservative", reason)

    def test_it_picks_the_largest_that_fits(self) -> None:
        class _Estimate:
            def __init__(self, total: int) -> None:
                self.total_bytes = total

        # Two thirds of 900 is 600; batch n costs 100n, so 6 fits and 7 does not.
        size, reason = resolve_batch_size(
            "auto", available_bytes=900, estimate_for=lambda n: _Estimate(100 * n)
        )
        self.assertEqual(size, 6)
        self.assertIn("two thirds", reason)

    def test_it_never_exceeds_the_ceiling(self) -> None:
        class _Tiny:
            total_bytes = 1

        size, _ = resolve_batch_size(
            "auto", available_bytes=10 ** 12, estimate_for=lambda n: _Tiny(), ceiling=8
        )
        self.assertEqual(size, 8)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
