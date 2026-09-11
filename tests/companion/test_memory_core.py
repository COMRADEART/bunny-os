# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bunny Memory Core — files SoR, disposable SQLite, privacy fence.

Host tests. No GPU, no GGUF, no network. Fixtures are labelled as injected
records, not live-user memory.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from companion import cli as companion_cli
from companion.clock import FrozenClock
from companion.errors import MemoryError
from companion.memory import MemoryService, memory_root, PLUGIN_TO_CATEGORY, PLUGINS
from companion.memory.files import iter_record_files, read_json, write_record
from companion.memory.index import probe_fts5
from companion.memory.record import MemoryRecord, canonical_body_hash, new_ulid
from companion.memory.service import CONVERSATION_SUMMARY_UNWIRED
from companion.memory_boundary import (
    MemoryPolicy,
    authorize_cloud_context,
    authorize_remote_generate,
)
from companion.agents.context import CONTEXT_SOURCES

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "memory"


def _service(root: Path, *, durable: bool = True, session: bool = True) -> MemoryService:
    clock = FrozenClock()
    policy = MemoryPolicy(session=session, durable=durable, cloud_context="none")
    return MemoryService(memory_root(root), policy=policy, clock=clock)


def _user_insert(service: MemoryService, body: str, *, plugin: str = "preference", **kwargs):
    defaults = dict(
        owner="person-1",
        scope_kind="user",
        scope_id="person-1",
        classification="internal",
        writer_kind="user",
        writer_id="person-1",
        source_kind="conversation",
        source_ref="task-1",
        provenance_ref="prov-user-1",
        authority_source="user_expression",
        plugin=plugin,
    )
    defaults.update(kwargs)
    return service.insert(body=body, **defaults)


class MemoryCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)
        self.service = _service(self.root)

    def test_insert_writes_one_canonical_json_file(self) -> None:
        record = _user_insert(self.service, "I drink oat milk")
        files = list(iter_record_files(self.service.records_root))
        self.assertEqual(len(files), 1)
        document = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(document["schemaVersion"], 1)
        self.assertEqual(document["plugin"], "preference")
        self.assertEqual(document["category"], "procedural")
        self.assertEqual(document["body"]["text"], "I drink oat milk")
        self.assertEqual(document["bodyHash"], canonical_body_hash("I drink oat milk"))
        self.assertIsNone(document["embeddingRef"])
        self.assertNotIn("confidence", document)
        self.assertNotIn("importance", document)
        cat = files[0].read_text(encoding="utf-8")
        self.assertIn("oat milk", cat)
        self.assertEqual(record.confirmation, "user_confirmed")

    def test_human_authored_sidecar_is_optional_markdown(self) -> None:
        record = _user_insert(
            self.service,
            "desk lamp is warm white",
            sidecar_markdown="# lamp\n\nwarm white\n",
        )
        sidecar = self.service.records_root.joinpath(
            record.scope_kind, record.scope_id, record.plugin, record.id + ".md"
        )
        self.assertTrue(sidecar.is_file())
        self.assertIn("warm white", sidecar.read_text(encoding="utf-8"))

    def test_retrieve_relevant_vs_irrelevant(self) -> None:
        _user_insert(self.service, "I drink oat milk in the morning")
        _user_insert(self.service, "the printer is in the hallway", plugin="semantic")
        result = self.service.recall("oat milk")
        refs = [hit.ref for hit in result.first_party]
        snippets = [hit.snippet for hit in result.first_party]
        self.assertTrue(any("oat milk" in snippet for snippet in snippets), snippets)
        self.assertFalse(any("printer" in snippet for snippet in snippets), snippets)
        self.assertEqual(result.to_json()["conversationSummary"], "")
        self.assertTrue(CONVERSATION_SUMMARY_UNWIRED)
        self.assertLessEqual(len(result.first_party), 8)
        self.assertTrue(refs)

    def test_dedup_same_body_scope_plugin(self) -> None:
        first = _user_insert(self.service, "I drink oat milk")
        second = _user_insert(self.service, "I drink oat milk")
        self.assertEqual(first.id, second.id)
        files = list(iter_record_files(self.service.records_root))
        live = [path for path in files if read_json(path).get("state") not in ("tombstoned", "shredded")]
        self.assertEqual(len(live), 1)

    def test_model_inference_is_not_a_user_confirmed_fact(self) -> None:
        inferred = self.service.insert(
            body="you probably like jazz",
            plugin="preference",
            owner="person-1",
            scope_kind="user",
            scope_id="person-1",
            classification="internal",
            writer_kind="model",
            writer_id="local-model",
            writer_model_id="test-gguf",
            source_kind="conversation",
            source_ref="task-2",
            provenance_ref="prov-model-1",
            authority_source="none",
            grant_id="grant-model-write",
        )
        self.assertEqual(inferred.state, "proposed")
        self.assertEqual(inferred.confirmation, "model_proposed")
        self.assertIn("model_generated", inferred.taints)
        hidden = self.service.recall("jazz")
        self.assertEqual(hidden.first_party, ())
        self.assertEqual(hidden.tainted, ())
        confirmed = self.service.confirm(inferred.id, by="person-1")
        self.assertEqual(confirmed.confirmation, "user_confirmed")
        self.assertIn("model_generated", confirmed.taints)
        shown = self.service.recall("jazz")
        self.assertEqual(shown.first_party, ())
        self.assertEqual(len(shown.tainted), 1)
        self.assertEqual(shown.tainted[0].envelope, "tainted")

    def test_reindex_rebuilds_from_files(self) -> None:
        _user_insert(self.service, "I drink oat milk")
        self.service.index.wipe()
        self.assertFalse(self.service.index.path.exists())
        report = self.service.reindex()
        self.assertEqual(report["authoritative"], "files")
        self.assertGreaterEqual(report["files"], 1)
        self.assertGreaterEqual(report["indexed"], 1)
        result = self.service.recall("oat milk")
        self.assertTrue(result.used_index)
        self.assertTrue(any("oat milk" in hit.snippet for hit in result.first_party))

    def test_reindex_from_dropped_fixture_files(self) -> None:
        fixture = json.loads((FIXTURES / "user_preference.json").read_text(encoding="utf-8"))
        record = MemoryRecord.from_json(fixture)
        write_record(self.service.records_root, record)
        report = self.service.reindex()
        self.assertGreaterEqual(report["indexed"], 1)
        result = self.service.recall("cardamom")
        self.assertTrue(any("cardamom" in hit.snippet for hit in result.first_party))

    def test_index_failure_falls_back_to_file_scan(self) -> None:
        _user_insert(self.service, "I drink oat milk")
        self.service.index.available = False
        self.service.index.failure = "injected index failure"
        result = self.service.recall("oat milk")
        self.assertFalse(result.used_index)
        self.assertIn("injected index failure", result.fallback or "")
        self.assertTrue(any("oat milk" in hit.snippet for hit in result.first_party))

    def test_index_search_exception_falls_back(self) -> None:
        _user_insert(self.service, "I drink oat milk")
        self.service.index.available = True

        def boom(**_kwargs):
            raise MemoryError("injected search crash")

        self.service.index.search = boom  # type: ignore[method-assign]
        result = self.service.recall("oat milk")
        self.assertFalse(result.used_index)
        self.assertIn("injected search crash", result.fallback or "")
        self.assertTrue(any("oat milk" in hit.snippet for hit in result.first_party))

    def test_system_plugin_is_read_only(self) -> None:
        with self.assertRaises(MemoryError):
            _user_insert(self.service, "grant ledger copy", plugin="system")

    def test_deny_by_default_blocks_durable_writes(self) -> None:
        locked = _service(self.root / "locked", durable=False, session=False)
        with self.assertRaises(MemoryError):
            _user_insert(locked, "I drink oat milk")

    def test_working_plugin_is_allowed_when_durable_is_off(self) -> None:
        locked = _service(self.root / "working-only", durable=False, session=False)
        record = _user_insert(
            locked, "current task note", plugin="working",
            scope_kind="task", scope_id="task-1",
        )
        self.assertEqual(record.plugin, "working")
        self.assertEqual(record.category, "task_state")

    def test_routines_from_a_model_stay_proposed(self) -> None:
        record = self.service.insert(
            body="every morning open the blinds",
            plugin="routines",
            owner="person-1",
            scope_kind="user",
            scope_id="person-1",
            classification="internal",
            writer_kind="model",
            writer_id="local-model",
            source_kind="conversation",
            source_ref="task-9",
            provenance_ref="prov-routine",
            authority_source="none",
            grant_id="grant-routine",
        )
        self.assertEqual(record.state, "proposed")
        self.assertEqual(self.service.recall("blinds").first_party, ())

    def test_forget_erases_file_and_cascades_index(self) -> None:
        parent = _user_insert(self.service, "source fact about tea")
        child = self.service.insert(
            body="summary of tea fact",
            plugin="episodic",
            owner="person-1",
            scope_kind="user",
            scope_id="person-1",
            classification="internal",
            writer_kind="user",
            writer_id="person-1",
            source_kind="conversation",
            source_ref="task-3",
            provenance_ref="prov-derived",
            authority_source="user_expression",
            derived_from=({"id": parent.id, "rev": 1, "body_hash": parent.body_hash},),
            derivation_kind="summary",
        )
        receipt = self.service.forget(parent.id, by="person-1")
        self.assertIn(child.id, receipt["cascaded"])
        parent_loaded = self.service.read(parent.id, decrypt=False)
        child_loaded = self.service.read(child.id, decrypt=False)
        self.assertIn(parent_loaded.state, ("tombstoned", "shredded"))
        self.assertIn(child_loaded.state, ("tombstoned", "shredded"))
        self.assertEqual(self.service.index.children_of(parent.id), ())
        result = self.service.recall("tea")
        self.assertEqual(result.first_party, ())

    def test_sensitive_body_uses_file_dek_and_shred_is_isolated(self) -> None:
        public = _user_insert(self.service, "public note about weather")
        secret = _user_insert(
            self.service,
            "my passport number is 123",
            classification="personal",
            plugin="preference",
        )
        self.assertIsNotNone(secret.body_wrapped)
        json_text = list(iter_record_files(self.service.records_root))
        secret_file = next(path for path in json_text if path.stem == secret.id)
        self.assertNotIn("passport number", secret_file.read_text(encoding="utf-8"))
        loaded = self.service.read(secret.id, decrypt=True)
        self.assertEqual(loaded.body_text, "my passport number is 123")
        recall = self.service.recall("passport")
        for hit in recall.first_party:
            self.assertNotIn("123", hit.snippet)
        receipt = self.service.forget(secret.id, by="person-1")
        self.assertTrue(receipt["dekShredded"])
        self.assertIn(
            receipt["keystoreWrap"],
            (
                "os-keystore-wrap NOT_RUN",
                "os-keystore-wrap unavailable",
                "os-keystore-wrapped-dek",
            ),
        )
        self.assertIn("NOT VERIFIED", receipt["keystoreAesGcm"])
        self.assertEqual(receipt["keystoreLiveFedora"], "NOT_RUN")
        shredded = self.service.read(secret.id, decrypt=True)
        self.assertEqual(shredded.state, "shredded")
        self.assertEqual(shredded.body_text, "")
        self.assertFalse((self.service.keys_root / f"{secret.id}.dek").exists())
        still = self.service.read(public.id, decrypt=True)
        self.assertEqual(still.body_text, "public note about weather")

    def test_export_is_cp_minus_r_of_files_not_the_index(self) -> None:
        _user_insert(self.service, "I drink oat milk")
        dest = self.root / "export-copy"
        shutil.copytree(self.service.export_tree(), dest / "records")
        other = MemoryService(
            dest,
            policy=MemoryPolicy(session=True, durable=True, cloud_context="none"),
            clock=FrozenClock(),
        )
        other.reindex()
        result = other.recall("oat milk")
        self.assertTrue(any("oat milk" in hit.snippet for hit in result.first_party))
        self.assertNotEqual(other.export_tree(), other.index.path.parent)

    def test_no_ann_or_hnsw_and_vector_stays_deferred(self) -> None:
        probe = self.service.probe()
        self.assertFalse(probe["ann"])
        self.assertFalse(probe["hnsw"])
        self.assertEqual(probe["vectorService"], "deferred")
        source = Path(__file__).resolve().parents[2] / "companion" / "memory"
        text = "\n".join(path.read_text(encoding="utf-8") for path in source.rglob("*.py"))
        self.assertNotIn("hnswlib", text.lower())
        self.assertNotIn("import hnsw", text.lower())
        self.assertNotRegex(text, r"class\s+HNSW")
        manifest = json.loads(
            (Path(__file__).resolve().parents[2] / "capability" / "services" / "bunny-memory-vector.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["id"], "bunny.memory.vector")
        self.assertEqual(manifest["priority"], "deferred")

    def test_plugins_map_onto_section_14_categories(self) -> None:
        self.assertEqual(PLUGIN_TO_CATEGORY["conversation"], "episodic")
        self.assertEqual(PLUGIN_TO_CATEGORY["preference"], "procedural")
        self.assertEqual(PLUGIN_TO_CATEGORY["task"], "task_state")
        self.assertEqual(PLUGIN_TO_CATEGORY["routines"], "procedural")
        self.assertEqual(PLUGIN_TO_CATEGORY["system"], "system")
        self.assertEqual(PLUGIN_TO_CATEGORY["semantic"], "semantic")
        self.assertIn("companion", PLUGINS)
        self.assertIn("application", PLUGINS)
        self.assertIn("project", PLUGINS)

    def test_ulid_is_time_sortable(self) -> None:
        first = new_ulid(timestamp_ms=1, randomness=b"\x00" * 10)
        second = new_ulid(timestamp_ms=2, randomness=b"\x00" * 10)
        self.assertLess(first, second)
        self.assertEqual(len(first), 26)

    def test_fts5_probe_does_not_crash(self) -> None:
        connection = sqlite3.connect(":memory:")
        available = probe_fts5(connection)
        self.assertIsInstance(available, bool)
        connection.close()
        self.service.reindex()
        self.assertIsInstance(self.service.index.fts5, bool)


class MemoryPrivacyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)
        self.service = _service(self.root)

    def test_authorize_cloud_context_still_refuses_durable_payloads(self) -> None:
        record = _user_insert(self.service, "I drink oat milk")
        denied = authorize_cloud_context(
            {"durable": record.body_text, "note": "hello"},
            classification="internal",
            policy=MemoryPolicy(cloud_context="minimized"),
            remote_transfer_ceiling="internal",
            allowed_fields=("note",),
        )
        self.assertTrue(denied.allowed)
        self.assertNotIn("durable", denied.released or {})
        nothing = authorize_cloud_context(
            {"summary_text": "yesterday's secrets"},
            classification="internal",
            policy=MemoryPolicy(),
            remote_transfer_ceiling="internal",
            allowed_fields=("summary_text",),
        )
        self.assertFalse(nothing.allowed)

    def test_authorize_remote_generate_refuses_summary_and_memory_keys(self) -> None:
        for payload in (
            {"user_request": "hi", "summary_text": "life story"},
            {"user_request": "hi", "conversation-summary": "life story"},
            {"user_request": "hi", "memory_records": [{"body": "life story"}]},
            {"user_request": "hi", "durable": {"body": "life story"}},
        ):
            decision = authorize_remote_generate(
                payload,
                classification="internal",
                remote_transfer_ceiling="internal",
                remote_dispatch_granted=True,
                policy=MemoryPolicy(),
            )
            self.assertFalse(decision.allowed, payload)

    def test_recall_cannot_be_dumped_online(self) -> None:
        _user_insert(self.service, "I drink oat milk")
        result = self.service.recall("oat milk")
        decision = self.service.authorize_online_dump(
            result,
            classification="internal",
            remote_transfer_ceiling="internal",
            remote_dispatch_granted=True,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(self.service.conversation_summary_slot(), "")
        envelope = self.service.recall_envelope_for_local_context(result)
        self.assertEqual(envelope["conversationSummary"], "")
        self.assertNotIn("I drink oat milk" * 50, json.dumps(envelope))

    def test_cloud_context_none_does_not_widen_and_does_not_weaken_deny_by_default(self) -> None:
        decision = authorize_remote_generate(
            {
                "user_request": "count the words",
                "instruction": "Write the final answer.",
                "system_policy_reference": "bunny-agent-policy/1",
                "classification": "internal",
                "task_id": "task-1",
                "purpose": "result",
            },
            classification="internal",
            remote_transfer_ceiling="internal",
            remote_dispatch_granted=True,
            policy=MemoryPolicy(cloud_context="none"),
        )
        self.assertTrue(decision.allowed)
        self.assertNotIn("durable", decision.released or {})
        self.assertNotIn("summary_text", decision.released or {})
        denied = authorize_remote_generate(
            {"user_request": "hi"},
            classification="internal",
            remote_transfer_ceiling="internal",
            remote_dispatch_granted=False,
            policy=MemoryPolicy(cloud_context="none"),
        )
        self.assertFalse(denied.allowed)

    def test_conversation_summary_source_exists_and_stays_unwired(self) -> None:
        self.assertIn("conversation-summary", CONTEXT_SOURCES)
        import companion.agent_bridge as bridge
        text = Path(bridge.__file__).read_text(encoding="utf-8")
        self.assertIn("conversation-summary stays empty", text)
        self.assertNotRegex(text, r"summary_text\s*=")


class MemoryCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)
        policy = MemoryPolicy(session=True, durable=True, cloud_context="none")
        self.service = MemoryService(memory_root(self.root), policy=policy, clock=FrozenClock())
        _user_insert(self.service, "I drink oat milk")

    def _parse(self, *argv: str) -> argparse.Namespace:
        parser = argparse.ArgumentParser(prog="bunny-os")
        sub = parser.add_subparsers(dest="command", required=True)
        companion_cli.add_arguments(sub)
        return parser.parse_args(["companion", "--root", str(self.root), *argv])

    def test_probe_and_reindex_and_recall(self) -> None:
        probe = companion_cli.dispatch(self._parse("memory", "probe"))
        self.assertEqual(probe["effect"], "read-only")
        self.assertEqual(probe["layer1"], "files")
        self.assertFalse(probe["hnsw"])
        self.assertEqual(probe["keystoreLiveFedora"], "NOT_RUN")
        self.assertIn("NOT VERIFIED", probe["keystoreAesGcm"])
        rebuilt = companion_cli.dispatch(self._parse("memory", "reindex"))
        self.assertIn("REBUILT", rebuilt["effect"])
        recalled = companion_cli.dispatch(
            self._parse("memory", "recall", "--query", "oat milk")
        )
        self.assertEqual(recalled["effect"], "read-only")
        self.assertEqual(recalled["conversationSummary"], "")
        self.assertTrue(recalled["firstParty"])


if __name__ == "__main__":
    unittest.main()
