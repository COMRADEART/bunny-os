# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""OS-keystore DEK wrap — injected present/absent fixtures, honest live probe.

Tests inject the probe. They do not claim Fedora Secret Service PASS.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from companion.clock import FrozenClock
from companion.errors import MemoryError
from companion.memory import MemoryService, memory_root
from companion.memory.crypto import DEK_BYTES, generate_dek
from companion.memory.keystore import (
    KEK_SCOPE,
    InjectedKeystore,
    dek_blob_is_wrapped,
    materialize_dek,
    probe_os_keystore,
    unavailable_probe,
    unwrap_dek,
    wrap_dek,
)
from companion.memory.record import (
    CRYPTO_STATUS_KEYSTORE_NOT_RUN,
    CRYPTO_STATUS_KEYSTORE_UNAVAILABLE,
    CRYPTO_STATUS_KEYSTORE_UNVERIFIED,
    CRYPTO_STATUS_KEYSTORE_WRAPPED,
)
from companion.memory.service import CONVERSATION_SUMMARY_UNWIRED
from companion.memory_boundary import MemoryPolicy, authorize_remote_generate


def _service(root: Path, **kwargs) -> MemoryService:
    clock = FrozenClock()
    policy = MemoryPolicy(session=True, durable=True, cloud_context="none")
    return MemoryService(memory_root(root), policy=policy, clock=clock, **kwargs)


def _user_insert(service: MemoryService, body: str, **kwargs):
    defaults = dict(
        owner="person-1",
        scope_kind="user",
        scope_id="person-1",
        classification="personal",
        writer_kind="user",
        writer_id="person-1",
        source_kind="conversation",
        source_ref="task-1",
        provenance_ref="prov-user-1",
        authority_source="user_expression",
        plugin="preference",
    )
    defaults.update(kwargs)
    return service.insert(body=body, **defaults)


class _BrokenKeystore:
    name = "broken"

    def get_or_create_kek(self, scope: str) -> bytes:
        raise MemoryError("injected keystore failure")

    def get_kek(self, scope: str) -> bytes | None:
        return None


class KeystoreWrapUnitTests(unittest.TestCase):
    def test_wrap_round_trip(self) -> None:
        dek = generate_dek()
        kek = generate_dek()
        document = wrap_dek(dek, kek)
        self.assertEqual(document["kind"], "keystore-wrapped-dek")
        self.assertEqual(document["kekScope"], KEK_SCOPE)
        self.assertEqual(unwrap_dek(document, kek), dek)

    def test_wrong_kek_fails(self) -> None:
        dek = generate_dek()
        document = wrap_dek(dek, generate_dek())
        with self.assertRaises(MemoryError):
            unwrap_dek(document, generate_dek())


class KeystorePresentTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)
        self.store: dict[str, bytes] = {}
        self.keystore = InjectedKeystore(self.store)
        self.service = _service(self.root, keystore=self.keystore)

    def test_injected_keystore_wraps_and_unwraps(self) -> None:
        secret = _user_insert(self.service, "my passport number is 123")
        dek_path = self.service.keys_root / f"{secret.id}.dek"
        blob = dek_path.read_bytes()
        self.assertTrue(dek_blob_is_wrapped(blob))
        self.assertNotEqual(len(blob), DEK_BYTES)
        self.assertNotIn(b"passport", blob)
        wrap_doc = json.loads(blob.decode("utf-8"))
        self.assertEqual(wrap_doc["kind"], "keystore-wrapped-dek")
        self.assertNotIn("my passport number is 123", dek_path.read_text(encoding="utf-8"))
        loaded = self.service.read(secret.id, decrypt=True)
        self.assertEqual(loaded.body_text, "my passport number is 123")
        self.assertEqual(secret.body_wrapped["keystoreWrap"], CRYPTO_STATUS_KEYSTORE_WRAPPED)
        probe = self.service.probe()
        self.assertEqual(probe["keystoreWrap"], CRYPTO_STATUS_KEYSTORE_WRAPPED)
        self.assertEqual(probe["keystoreBackend"], "injected")
        self.assertEqual(probe["keystoreLiveFedora"], "NOT_RUN")
        self.assertIn("NOT VERIFIED", probe["keystoreAesGcm"])

    def test_filesystem_copy_without_kek_does_not_recover_plaintext(self) -> None:
        secret = _user_insert(self.service, "my passport number is 123")
        dest = self.root / "stolen-tree"
        shutil.copytree(self.service.records_root, dest / "records")
        shutil.copytree(self.service.keys_root, dest / "keys")
        stolen = MemoryService(
            dest,
            policy=MemoryPolicy(session=True, durable=True, cloud_context="none"),
            clock=FrozenClock(),
            keystore_probe=unavailable_probe(),
        )
        with self.assertRaises(MemoryError):
            stolen.read(secret.id, decrypt=True)
        for path in dest.rglob("*"):
            if path.is_file():
                self.assertNotIn(b"passport number is 123", path.read_bytes())
        still = self.service.read(secret.id, decrypt=True)
        self.assertEqual(still.body_text, "my passport number is 123")

    def test_copy_with_same_injected_kek_still_opens(self) -> None:
        secret = _user_insert(self.service, "my passport number is 123")
        dest = self.root / "export-tree"
        shutil.copytree(self.service.records_root, dest / "records")
        shutil.copytree(self.service.keys_root, dest / "keys")
        cloned = MemoryService(
            dest,
            policy=MemoryPolicy(session=True, durable=True, cloud_context="none"),
            clock=FrozenClock(),
            keystore=InjectedKeystore(self.store),
        )
        loaded = cloned.read(secret.id, decrypt=True)
        self.assertEqual(loaded.body_text, "my passport number is 123")

    def test_shred_one_wrapped_dek_leaves_the_other(self) -> None:
        first = _user_insert(self.service, "secret one is alpha")
        second = _user_insert(
            self.service,
            "secret two is beta",
            provenance_ref="prov-user-2",
        )
        receipt = self.service.forget(first.id, by="person-1")
        self.assertTrue(receipt["dekShredded"])
        self.assertEqual(receipt["keystoreWrap"], CRYPTO_STATUS_KEYSTORE_WRAPPED)
        gone = self.service.read(first.id, decrypt=True)
        self.assertEqual(gone.state, "shredded")
        self.assertEqual(gone.body_text, "")
        self.assertFalse((self.service.keys_root / f"{first.id}.dek").exists())
        still = self.service.read(second.id, decrypt=True)
        self.assertEqual(still.body_text, "secret two is beta")


class KeystoreAbsentTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)
        self.service = _service(self.root, keystore_probe=unavailable_probe())

    def test_absent_keystore_falls_back_to_file_dek(self) -> None:
        secret = _user_insert(self.service, "my passport number is 123")
        blob = (self.service.keys_root / f"{secret.id}.dek").read_bytes()
        self.assertEqual(len(blob), DEK_BYTES)
        self.assertFalse(dek_blob_is_wrapped(blob))
        self.assertEqual(secret.body_wrapped["keystoreWrap"], CRYPTO_STATUS_KEYSTORE_UNAVAILABLE)
        loaded = self.service.read(secret.id, decrypt=True)
        self.assertEqual(loaded.body_text, "my passport number is 123")
        probe = self.service.probe()
        self.assertEqual(probe["keystoreWrap"], CRYPTO_STATUS_KEYSTORE_UNAVAILABLE)
        self.assertEqual(probe["keystoreLiveFedora"], "NOT_RUN")

    def test_broken_backend_degrades_without_crash_or_fake_wrap(self) -> None:
        service = _service(self.root / "broken", keystore=_BrokenKeystore())
        secret = _user_insert(service, "my passport number is 123")
        blob = (service.keys_root / f"{secret.id}.dek").read_bytes()
        self.assertEqual(len(blob), DEK_BYTES)
        self.assertFalse(dek_blob_is_wrapped(blob))
        self.assertEqual(secret.body_wrapped["keystoreWrap"], CRYPTO_STATUS_KEYSTORE_UNAVAILABLE)
        self.assertEqual(service.read(secret.id, decrypt=True).body_text, "my passport number is 123")

    def test_shred_still_isolated_on_fallback(self) -> None:
        public = _user_insert(
            self.service,
            "public note about weather",
            classification="internal",
        )
        secret = _user_insert(self.service, "my passport number is 123")
        receipt = self.service.forget(secret.id, by="person-1")
        self.assertTrue(receipt["dekShredded"])
        self.assertEqual(receipt["keystoreWrap"], CRYPTO_STATUS_KEYSTORE_UNAVAILABLE)
        still = self.service.read(public.id, decrypt=True)
        self.assertEqual(still.body_text, "public note about weather")


class KeystorePrivacyAndProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)
        self.service = _service(self.root, keystore=InjectedKeystore())

    def test_recall_still_cannot_be_dumped_online(self) -> None:
        _user_insert(
            self.service,
            "I drink oat milk",
            classification="internal",
        )
        result = self.service.recall("oat milk")
        decision = self.service.authorize_online_dump(
            result,
            classification="internal",
            remote_transfer_ceiling="internal",
            remote_dispatch_granted=True,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(self.service.conversation_summary_slot(), "")
        self.assertTrue(CONVERSATION_SUMMARY_UNWIRED)
        self.assertEqual(result.to_json()["conversationSummary"], "")

    def test_does_not_retighten_cloud_context_none_vs_remote_dispatch(self) -> None:
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
        denied = authorize_remote_generate(
            {"user_request": "hi", "memory_records": [{"body": "life story"}]},
            classification="internal",
            remote_transfer_ceiling="internal",
            remote_dispatch_granted=True,
            policy=MemoryPolicy(cloud_context="none"),
        )
        self.assertFalse(denied.allowed)

    def test_live_probe_does_not_invent_secret_service_or_fedora_pass(self) -> None:
        probe, backend = probe_os_keystore()
        self.assertEqual(probe.live_fedora, "NOT_RUN")
        self.assertEqual(probe.aes_gcm, "NOT VERIFIED")
        self.assertEqual(CRYPTO_STATUS_KEYSTORE_UNVERIFIED, "os-keystore-wrap NOT VERIFIED")
        secret_tool = shutil.which("secret-tool")
        dbus_session = bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS"))
        if secret_tool is None:
            self.assertFalse(probe.available)
            self.assertIsNone(backend)
            self.assertEqual(probe.status, CRYPTO_STATUS_KEYSTORE_NOT_RUN)
            self.assertIn("secret-tool not on PATH", probe.detail)
        elif not dbus_session:
            self.assertFalse(probe.available)
            self.assertIsNone(backend)
            self.assertEqual(probe.status, CRYPTO_STATUS_KEYSTORE_UNAVAILABLE)
        if not probe.available:
            self.assertIsNone(backend)

    def test_materialize_without_backend_refuses_wrapped_blob(self) -> None:
        dek = generate_dek()
        kek = generate_dek()
        blob = json.dumps(wrap_dek(dek, kek), separators=(",", ":")).encode("utf-8")
        with self.assertRaises(MemoryError):
            materialize_dek(blob, None)
        self.assertEqual(materialize_dek(dek, None), dek)

    def test_no_ann_claim_in_probe(self) -> None:
        probe = self.service.probe()
        self.assertFalse(probe["ann"])
        self.assertFalse(probe["hnsw"])
        self.assertEqual(probe["vectorService"], "deferred")


if __name__ == "__main__":
    unittest.main()
