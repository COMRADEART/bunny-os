# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Configuration validation: what it accepts, and everything it refuses.

The refusals carry the weight. A loader that accepts a typo trains at a default
and reports success, and the two runs are indistinguishable from their logs.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from model_studio.config import (
    CONFIG_SCHEMA_PATH,
    config_from_mapping,
    load_config,
    parse_simple_yaml,
)
from model_studio.errors import ConfigurationError

MINIMAL = {
    "model": {"base": "HuggingFaceTB/SmolLM2-135M-Instruct"},
    "training": {"method": "lora"},
    "dataset": {"path": "./data.jsonl"},
    "output": {"directory": "./out"},
}


def _with(section: str, **values: object) -> dict:
    document = {key: dict(item) for key, item in MINIMAL.items()}
    document.setdefault(section, {})
    document[section] = {**document.get(section, {}), **values}
    return document


class Accepts(unittest.TestCase):
    def test_the_minimal_document(self) -> None:
        config = config_from_mapping(MINIMAL)
        self.assertEqual(config.model.base, "HuggingFaceTB/SmolLM2-135M-Instruct")
        self.assertEqual(config.effective_method, "lora")
        self.assertEqual(config.training.batch_size, "auto")

    def test_defaults_are_stated_not_implied(self) -> None:
        config = config_from_mapping(MINIMAL)
        self.assertEqual(config.lora.rank, 16)
        self.assertEqual(config.lora.alpha, 32)
        self.assertTrue(config.training.gradient_checkpointing)
        self.assertTrue(config.dataset.policy_check)

    def test_qlora_with_quantization(self) -> None:
        document = _with("training", method="qlora")
        document["quantization"] = {"enabled": True, "bits": 4}
        config = config_from_mapping(document)
        self.assertEqual(config.effective_method, "qlora")

    def test_canonical_digest_ignores_formatting(self) -> None:
        first = config_from_mapping(MINIMAL)
        reordered = {key: MINIMAL[key] for key in reversed(list(MINIMAL))}
        self.assertEqual(first.canonical_sha256, config_from_mapping(reordered).canonical_sha256)

    def test_paths_resolve_against_the_document(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch) / "nested"
            root.mkdir()
            path = root / "run.json"
            path.write_text(json.dumps(MINIMAL), encoding="utf-8")
            config = load_config(path)
            self.assertEqual(config.dataset_path, (root / "data.jsonl").resolve())
            self.assertEqual(config.output_directory, (root / "out").resolve())


class Refuses(unittest.TestCase):
    def _refused(self, document: dict, fragment: str) -> None:
        with self.assertRaises(ConfigurationError) as caught:
            config_from_mapping(document)
        self.assertIn(fragment, str(caught.exception))

    def test_an_unknown_key(self) -> None:
        self._refused(_with("training", lr=0.001), "unknown key")

    def test_an_unknown_section(self) -> None:
        document = {**MINIMAL, "upload": {"enabled": True}}
        self._refused(document, "unknown top-level section")

    def test_a_missing_section(self) -> None:
        document = {key: value for key, value in MINIMAL.items() if key != "dataset"}
        self._refused(document, "missing required section")

    def test_qlora_without_quantization(self) -> None:
        self._refused(_with("training", method="qlora"), "quantization.enabled is false")

    def test_lora_with_quantization(self) -> None:
        document = {**MINIMAL, "quantization": {"enabled": True}}
        self._refused(document, "is QLoRA; say so")

    def test_alpha_below_rank(self) -> None:
        document = {**MINIMAL, "lora": {"rank": 32, "alpha": 8}}
        self._refused(document, "shrinks every update")

    def test_warmup_beyond_the_run(self) -> None:
        self._refused(_with("training", max_steps=5, warmup_steps=5), "still warming up")

    def test_remote_code(self) -> None:
        self._refused(_with("model", trust_remote_code=True), "does not execute it")

    def test_a_url_dataset(self) -> None:
        self._refused(
            _with("dataset", path="https://example.invalid/corpus.jsonl"),
            "is not fetched over the network",
        )

    def test_a_learning_rate_of_zero(self) -> None:
        self._refused(_with("training", learning_rate=0), "must be greater than 0")

    def test_a_non_integer_batch_size(self) -> None:
        self._refused(_with("training", batch_size="big"), "is not an integer or 'auto'")

    def test_an_unsupported_dataset_format(self) -> None:
        self._refused(_with("dataset", format="alpaca"), "is not one of chat")

    def test_a_future_version(self) -> None:
        self._refused({**MINIMAL, "version": 2}, "is not supported")

    def test_an_empty_base(self) -> None:
        self._refused(_with("model", base="   "), "model.base is required")

    def test_a_boolean_where_a_number_belongs(self) -> None:
        self._refused(_with("training", epochs=True), "expected an integer")


class YamlSubset(unittest.TestCase):
    """The fallback parser, checked against PyYAML wherever PyYAML is installed."""

    DOCUMENT = """
model:
  base: org/name          # a comment
  revision: main
training:
  method: lora
  epochs: 3
  learning_rate: 0.0002
  gradient_checkpointing: true
  batch_size: auto
lora:
  rank: 8
  alpha: 16
  target_modules:
    - q_proj
    - v_proj
dataset:
  path: ./data.jsonl
  validation_split: 0.25
output:
  directory: ./out
"""

    def test_it_parses(self) -> None:
        document = parse_simple_yaml(self.DOCUMENT)
        self.assertEqual(document["training"]["epochs"], 3)
        self.assertIs(document["training"]["gradient_checkpointing"], True)
        self.assertEqual(document["lora"]["target_modules"], ["q_proj", "v_proj"])
        self.assertEqual(document["dataset"]["validation_split"], 0.25)
        self.assertEqual(document["training"]["batch_size"], "auto")

    def test_it_agrees_with_pyyaml(self) -> None:
        try:
            import yaml
        except ImportError:  # pragma: no cover - PyYAML is optional here
            self.skipTest("PyYAML is not installed")
        self.assertEqual(parse_simple_yaml(self.DOCUMENT), yaml.safe_load(self.DOCUMENT))

    def test_it_agrees_on_the_shipped_example(self) -> None:
        try:
            import yaml
        except ImportError:  # pragma: no cover
            self.skipTest("PyYAML is not installed")
        example = Path(__file__).resolve().parents[2] / "model_studio/examples/bunny-demo.yaml"
        text = example.read_text(encoding="utf-8")
        self.assertEqual(parse_simple_yaml(text), yaml.safe_load(text))

    def test_it_refuses_what_it_does_not_understand(self) -> None:
        for document, fragment in (
            ("model:\n\tbase: x\n", "tabs"),
            ("model:\n  base: !!python/object x\n", "full YAML parser"),
            ("  model: x\n", "starts indented"),
            ("model:\n  base: a\n  base: b\n", "duplicate key"),
        ):
            with self.subTest(document=document):
                with self.assertRaises(ConfigurationError) as caught:
                    parse_simple_yaml(document)
                self.assertIn(fragment, str(caught.exception))


class Schema(unittest.TestCase):
    def test_the_schema_document_is_well_formed(self) -> None:
        document = json.loads(CONFIG_SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(document["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertTrue(document["$id"])
        self.assertEqual(document["type"], "object")
        try:
            import jsonschema
        except ImportError:  # pragma: no cover - optional in this repository
            self.skipTest("jsonschema is not installed")
        jsonschema.Draft202012Validator.check_schema(document)

    def test_the_schema_and_the_loader_agree_on_sections(self) -> None:
        """A section in one and not the other is a document nobody can write correctly."""
        from model_studio.config import _SECTIONS

        document = json.loads(CONFIG_SCHEMA_PATH.read_text(encoding="utf-8"))
        declared = set(document["properties"]) - {"version"}
        self.assertEqual(declared, set(_SECTIONS))
        for name, keys in _SECTIONS.items():
            with self.subTest(section=name):
                self.assertEqual(
                    set(document["properties"][name]["properties"]), set(keys)
                )

    def test_the_shipped_example_validates(self) -> None:
        try:
            import jsonschema
            import yaml
        except ImportError:  # pragma: no cover
            self.skipTest("jsonschema or PyYAML is not installed")
        example = Path(__file__).resolve().parents[2] / "model_studio/examples/bunny-demo.yaml"
        document = yaml.safe_load(example.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(
            json.loads(CONFIG_SCHEMA_PATH.read_text(encoding="utf-8"))
        ).validate(document)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
