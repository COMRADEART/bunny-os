# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 16 (observability) and Phase 13 (network safety).

They share a file because they share a rule: the bridge records what it did and
reaches nothing it was not asked to reach, and both are properties of what the
code *cannot* do rather than what it happens not to.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
import tempfile
import unittest

from companion.models.events import EVENT_TYPES, ModelEvent, ModelEventLog, NullEventLog
from companion.models.registry import ModelRegistry
from companion.models.validation import RuntimeExpectations
from tests.model_bridge.support import BASE_REFERENCE, BASE_REVISION, FakeBackend, write_artifact

ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / "companion" / "models"


class TheVocabulary(unittest.TestCase):
    def test_it_covers_what_phase_16_asks_for(self) -> None:
        for name in ("model.discovered", "model.validation_started", "model.validation_failed",
                     "model.validation_passed", "model.loaded", "model.load_failed",
                     "model.disabled", "model.fallback_selected"):
            self.assertIn(name, EVENT_TYPES)

    def test_an_event_type_outside_it_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            ModelEvent.build("model.exfiltrated")


class ThePayloadIsClosed(unittest.TestCase):
    """The privacy rule, enforced by the type rather than by reviewers."""

    def test_private_content_is_dropped_and_the_omission_is_recorded(self) -> None:
        event = ModelEvent.build(
            "model.loaded",
            modelId="demo",
            prompt="the user's private question",
            completion="the model's answer",
            datasetRow={"messages": ["private"]},
            filePath="/home/someone/taxes.pdf",
            apiKey="sk-secret",
        )
        self.assertEqual(dict(event.payload), {"modelId": "demo"})
        self.assertEqual(
            event.dropped_keys,
            ("apiKey", "completion", "datasetRow", "filePath", "prompt"),
        )

    def test_the_dropped_keys_appear_in_the_record(self) -> None:
        event = ModelEvent.build("model.loaded", modelId="demo", prompt="private")
        self.assertIn("droppedKeys", event.to_json())

    def test_values_are_bounded(self) -> None:
        event = ModelEvent.build("model.load_failed", modelId="demo", reason="x" * 5000)
        self.assertLessEqual(len(event.payload["reason"]), 520)

    def test_there_is_no_key_for_prompts_or_datasets(self) -> None:
        from companion.models.events import _PAYLOAD_KEYS

        for forbidden in ("prompt", "completion", "dataset", "datasetRow", "text",
                          "content", "messages", "credential", "token", "apiKey"):
            self.assertNotIn(forbidden, _PAYLOAD_KEYS)


class TheLogRecordsARun(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.base = Path(self.scratch.name)
        self.root = self.base / "agent-models"
        self.root.mkdir(parents=True)
        self.state = self.base / "state"

    def _registry(self, backend=None) -> ModelRegistry:
        registry = ModelRegistry(
            roots=[self.root], state_root=self.state, backend=backend or FakeBackend(),
            expectations=RuntimeExpectations(
                base_model_reference=BASE_REFERENCE, base_model_revision=BASE_REVISION,
                base_model_present=True, trusted_roots=(self.root,), check_modes=False,
            ),
        )
        registry.events = ModelEventLog(registry.events_path)
        return registry

    def test_a_successful_activation_leaves_a_trail(self) -> None:
        write_artifact(self.root, "demo")
        registry = self._registry()
        registry.discover()
        registry.enable("demo")
        kinds = [event.event_type for event in registry.events.read()]
        for expected in ("model.discovered", "model.validation_started",
                         "model.validation_passed", "model.loaded", "model.enabled"):
            self.assertIn(expected, kinds)

    def test_a_refused_activation_says_why(self) -> None:
        write_artifact(self.root, "demo", corrupt_digest=True)
        registry = self._registry()
        registry.discover()
        registry.enable("demo")
        events = {event.event_type: event for event in registry.events.read()}
        self.assertIn("model.validation_failed", events)
        self.assertIn("model.load_failed", events)
        self.assertEqual(events["model.load_failed"].payload["code"],
                         "ADAPTER_CHECKSUM_MISMATCH")
        self.assertIn("model.fallback_selected", events)

    def test_the_log_is_json_lines_on_disk(self) -> None:
        write_artifact(self.root, "demo")
        registry = self._registry()
        registry.discover()
        text = registry.events_path.read_text(encoding="utf-8")
        for line in text.splitlines():
            document = json.loads(line)
            self.assertIn("eventType", document)
            self.assertIn("at", document)

    def test_the_null_log_is_the_default_and_records_nothing(self) -> None:
        registry = ModelRegistry(roots=[self.root], state_root=self.state)
        self.assertIsInstance(registry.events, NullEventLog)


class NetworkSafety(unittest.TestCase):
    """Phase 13: model loading introduces no network access."""

    def _imports(self, path: Path) -> set[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
        return names

    def test_the_bridge_opens_no_socket_of_its_own(self) -> None:
        """Everything that reaches a network goes through the audited wire layer.

        ``llama_server.py`` talks to loopback, and it does so through
        :class:`companion.agents.wire.WireSession` — the same client every
        provider adapter uses, whose target type refuses a non-loopback host for
        a local endpoint. No module here imports a socket library directly.
        """
        offenders = []
        for path in sorted(BRIDGE.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            for name in self._imports(path) & {"socket", "http", "urllib", "requests",
                                               "httpx", "ftplib", "smtplib", "asyncio"}:
                offenders.append(f"{path.relative_to(ROOT).as_posix()} imports {name}")
        self.assertEqual(offenders, [])

    def test_nothing_downloads(self) -> None:
        names: set[str] = set()
        for path in sorted(BRIDGE.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            module = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(module):
                if isinstance(node, ast.Name):
                    names.add(node.id)
                elif isinstance(node, ast.Attribute):
                    names.add(node.attr)
        for forbidden in ("urlopen", "snapshot_download", "hf_hub_download", "urlretrieve",
                          "get", "download"):
            if forbidden in ("get",):
                continue  # dict.get is everywhere and is not a download
            self.assertNotIn(forbidden, names, f"the bridge references {forbidden}")

    def test_a_missing_base_model_is_reported_not_fetched(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch) / "agent-models"
            root.mkdir()
            write_artifact(root, "demo")
            registry = ModelRegistry(
                roots=[root], state_root=Path(scratch) / "state", backend=FakeBackend(),
                expectations=RuntimeExpectations(
                    base_model_reference=BASE_REFERENCE, base_model_revision=BASE_REVISION,
                    base_model_present=False, trusted_roots=(root,), check_modes=False,
                ),
            )
            registry.discover()
            decision = registry.enable("demo")
            self.assertFalse(decision.using_adapter)
            self.assertEqual(decision.code, "BASE_MODEL_NOT_PRESENT")
            self.assertIn("not fetched", decision.reason)

    def test_an_artifact_declaring_it_needs_the_network_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch) / "agent-models"
            root.mkdir()
            write_artifact(root, "demo", network_required=True)
            registry = ModelRegistry(
                roots=[root], state_root=Path(scratch) / "state", backend=FakeBackend(),
                expectations=RuntimeExpectations(
                    base_model_reference=BASE_REFERENCE, base_model_revision=BASE_REVISION,
                    base_model_present=True, trusted_roots=(root,), check_modes=False,
                ),
            )
            registry.discover()
            self.assertEqual(registry.enable("demo").code, "NETWORK_REQUIRED_REFUSED")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
