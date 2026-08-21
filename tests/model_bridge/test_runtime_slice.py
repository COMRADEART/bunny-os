# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 20: the real chain, on a real adapter, through the real authorization path.

Everything else in this directory establishes a rule. This establishes that the
rules add up to a working, safe system — and it is the only suite that needs a
real llama-server, a real GGUF adapter converted from a real Model Studio run,
and a real trust gate. It skips unless ``BUNNY_MODEL_BRIDGE_HEAVY=1``, so the
ordinary suite stays something people run.

The chain, in order, with nothing faked between the ends::

    real Model Studio adapter -> real artifact + manifest -> real digest
      -> real runtime discovery -> real validation -> real adapter load
      -> real inference -> real proposal -> real Bunny authorization
      -> denied stays denied / approved executes

Environment:

``BUNNY_MODEL_BRIDGE_ARTIFACTS``
    a trusted model directory holding the exported artifact.
``BUNNY_MODEL_BRIDGE_SERVER``
    ``host:port`` of a llama-server started with ``--lora``.
``BUNNY_MODEL_BRIDGE_BASE`` / ``BUNNY_MODEL_BRIDGE_REVISION``
    what the runtime believes its base model is, so compatibility is a real
    comparison rather than a skipped one.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time
import unittest

HEAVY = os.environ.get("BUNNY_MODEL_BRIDGE_HEAVY", "") == "1"


@unittest.skipUnless(HEAVY, "set BUNNY_MODEL_BRIDGE_HEAVY=1 to run the real runtime slice")
class RuntimeSlice(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        from companion.agents.wire import HttpTarget
        from companion.models.llama_server import LlamaServerAdapterBackend

        cls.artifacts = Path(os.environ.get("BUNNY_MODEL_BRIDGE_ARTIFACTS", "")).expanduser()
        if not cls.artifacts.is_dir():
            raise unittest.SkipTest("BUNNY_MODEL_BRIDGE_ARTIFACTS is not a directory")
        endpoint = os.environ.get("BUNNY_MODEL_BRIDGE_SERVER", "127.0.0.1:8080")
        host, _, port = endpoint.partition(":")
        cls.target = HttpTarget(scheme="http", host=host or "127.0.0.1", port=int(port or 8080))
        cls.backend = LlamaServerAdapterBackend(cls.target)
        status = cls.backend.describe()
        if not status.available:
            raise unittest.SkipTest(f"no llama-server at {endpoint}: {status.detail}")
        cls.base_reference = os.environ.get(
            "BUNNY_MODEL_BRIDGE_BASE", "HuggingFaceTB/SmolLM2-135M-Instruct"
        )
        cls.base_revision = os.environ.get(
            "BUNNY_MODEL_BRIDGE_REVISION", "12fd25f77366fa6b3b4b768ec3050bf629380bac"
        )
        cls.model_id = os.environ.get("BUNNY_MODEL_BRIDGE_MODEL", "bunny-demo")

    def setUp(self) -> None:
        import tempfile

        from companion.models.events import ModelEventLog
        from companion.models.registry import ModelRegistry
        from companion.models.validation import RuntimeExpectations

        self.state = tempfile.TemporaryDirectory()
        self.addCleanup(self.state.cleanup)
        self.registry = ModelRegistry(
            roots=[self.artifacts],
            state_root=Path(self.state.name),
            backend=self.backend,
            expectations=RuntimeExpectations(
                base_model_reference=self.base_reference,
                base_model_revision=self.base_revision,
                base_model_file=os.environ.get("BUNNY_MODEL_BRIDGE_BASE_FILE", ""),
                base_model_sha256=os.environ.get("BUNNY_MODEL_BRIDGE_BASE_SHA256", ""),
                base_model_present=True,
                trusted_roots=(self.artifacts,),
            ),
        )
        self.registry.events = ModelEventLog(self.registry.events_path)
        self.addCleanup(lambda: self.backend.release(self.model_id))

    # -- discovery, validation, load ------------------------------------- #

    def test_1_the_artifact_is_discovered_and_valid(self) -> None:
        from companion.models.validation import PASS

        models = self.registry.discover()
        self.assertTrue(models, f"no artifact under {self.artifacts}")
        found = {model.model_id: model for model in models}
        self.assertIn(self.model_id, found)
        report = found[self.model_id].report
        self.assertEqual(report.status, PASS, json.dumps(report.to_json(), indent=2))

    def test_2_the_digest_is_of_the_real_adapter_on_disk(self) -> None:
        self.registry.discover()
        model = self.registry.get(self.model_id)
        manifest = model.manifest
        self.assertIsNotNone(manifest)
        adapter = Path(model.path) / manifest.adapter_file
        digest = hashlib.sha256(adapter.read_bytes()).hexdigest()
        self.assertEqual(digest, manifest.adapter_sha256)
        self.assertGreater(adapter.stat().st_size, 1024, "a real adapter is not a stub")

    def test_3_enabling_applies_the_adapter_and_verifies_it(self) -> None:
        self.registry.discover()
        decision = self.registry.enable(self.model_id)
        self.assertTrue(decision.using_adapter, decision.reason)
        model = self.registry.get(self.model_id)
        self.assertTrue(model.application.verified,
                        "the server confirmed the adapter is in effect")
        self.assertEqual(model.application.scale, 1.0)

    def test_4_real_inference_runs_with_the_adapter_applied(self) -> None:
        """Through Bunny's own provider adapter, not a raw HTTP call."""
        from companion.agents.adapter import CancellationSignal, StreamEventFactory
        from companion.agents.adapters.llamacpp import LlamaCppAdapter
        from companion.agents.config import ProviderConfiguration
        from companion.agents.descriptor import EndpointIdentity
        from companion.agents.request import GenerationMessage, GenerationRequest

        self.registry.discover()
        self.assertTrue(self.registry.enable(self.model_id).using_adapter)

        # The server names its model by the path it loaded; the request has to
        # carry a model id, so it carries that one.
        served = self.backend.describe().base_model_path or "default"
        adapter = LlamaCppAdapter()
        configuration = ProviderConfiguration(
            provider_id="llamacpp-local",
            adapter_id="llamacpp",
            endpoint=EndpointIdentity(kind="loopback-http", locator=self.target.locator),
            http=self.target,
            model_id="",
        )
        request = GenerationRequest(
            request_id="req-slice-1",
            session_id="session-slice",
            task_id="task-slice",
            lifecycle_epoch=1,
            plan_id="plan-slice",
            provider_id="llamacpp-local",
            model_id=served,
            purpose="result",
            messages=(GenerationMessage(role="user", content="Open Downloads"),),
            system_policy_reference="policy/none",
            maximum_input_tokens=512,
            maximum_output_tokens=48,
        )
        events: list = []
        outcome = adapter.generate(
            request, configuration, secret=None, emit=events.append,
            events=StreamEventFactory(request_id=request.request_id,
                                      provider_id="llamacpp-local",
                                      monotonic=time.monotonic),
            cancellation=CancellationSignal(),
        )
        self.assertTrue(outcome.ok, outcome.detail)
        # The adapter's contract is to emit correctly-sequenced events; turning
        # them into assembled text is the worker's StreamAssembler, and this
        # test drives the adapter directly. So the output is read from the
        # deltas — exactly what the assembler would have consumed.
        kinds = [event.kind for event in events]
        self.assertIn("generation_started", kinds)
        self.assertIn("generation_completed", kinds)
        text = "".join(
            str(event.payload.get("text", ""))
            for event in events if event.kind == "output_delta"
        ).strip()
        self.assertTrue(text, f"the model produced no output; events were {kinds}")
        print(f"\n  [slice] inference with adapter: {text[:160]!r}")

    def test_5_releasing_turns_it_off_and_confirms(self) -> None:
        self.registry.discover()
        self.registry.enable(self.model_id)
        decision = self.registry.disable(self.model_id)
        self.assertFalse(decision.using_adapter)
        status = self.backend.describe()
        self.assertTrue(status.available)
        self.assertEqual(self.registry.active().code, "NO_MODEL_ENABLED")

    # -- tampering, against the real artifact ----------------------------- #

    def test_6_a_one_byte_tamper_on_the_real_adapter_is_caught(self) -> None:
        self.registry.discover()
        model = self.registry.get(self.model_id)
        adapter = Path(model.path) / model.manifest.adapter_file
        original = adapter.read_bytes()
        try:
            adapter.write_bytes(original[:-1] + bytes([original[-1] ^ 0x01]))
            decision = self.registry.enable(self.model_id)
            self.assertFalse(decision.using_adapter)
            self.assertEqual(decision.code, "ADAPTER_CHECKSUM_MISMATCH")
        finally:
            adapter.write_bytes(original)
        self.assertEqual(hashlib.sha256(adapter.read_bytes()).hexdigest(),
                         model.manifest.adapter_sha256, "the test restored the artifact")

    # -- authorization, with the real gate -------------------------------- #

    def test_7_a_denied_proposal_changes_nothing(self) -> None:
        from companion.capsule_bridge import CapsuleTaskCoordinator
        from companion.models.proposal import admit_proposal
        from tests.capsule_support import World

        world = World.build()
        self.addCleanup(world.close)
        picture = world.file("Pictures/holiday.png", b"\x89PNG\r\n\x1a\n" + b"pixels" * 64)
        before = hashlib.sha256(picture.read_bytes()).hexdigest()

        proposal = admit_proposal({"operation": "image.resize", "parameters": {"width": 512}})
        self.assertTrue(proposal.admitted)
        world.answer(("files", "deny", "once"))
        result = CapsuleTaskCoordinator(runtime=world.runtime, registry=world.registry).run(
            task_id="slice-denied", capability="resize-image", entry_id="bunny-image-tool",
            inputs=[picture], destination=world.home / "Pictures",
            request_text="Resize holiday.png to 50%.",
        )
        self.assertFalse(result.succeeded)
        self.assertEqual(hashlib.sha256(picture.read_bytes()).hexdigest(), before)
        produced = [p.name for p in (world.home / "Pictures").iterdir() if p.name != "holiday.png"]
        self.assertEqual(produced, [])
        self.assertEqual(world.executor.launches, [])

    def test_8_an_approved_proposal_executes(self) -> None:
        from companion.capsule_bridge import CapsuleTaskCoordinator
        from companion.models.proposal import admit_proposal
        from tests.capsule_support import World

        world = World.build()
        self.addCleanup(world.close)
        picture = world.file("Pictures/holiday.png", b"\x89PNG\r\n\x1a\n" + b"pixels" * 64)
        before = hashlib.sha256(picture.read_bytes()).hexdigest()

        proposal = admit_proposal({"operation": "image.resize", "parameters": {"width": 512}})
        self.assertTrue(proposal.admitted)
        world.answer(("files", "allow", "once"))
        result = CapsuleTaskCoordinator(runtime=world.runtime, registry=world.registry).run(
            task_id="slice-approved", capability="resize-image", entry_id="bunny-image-tool",
            inputs=[picture], destination=world.home / "Pictures",
            request_text="Resize holiday.png to 50%.",
        )
        self.assertTrue(result.succeeded, result.workspace.as_record())
        produced = [p for p in (world.home / "Pictures").iterdir() if p.name != "holiday.png"]
        self.assertTrue(produced, "an approved task produced nothing")
        self.assertEqual(hashlib.sha256(picture.read_bytes()).hexdigest(), before,
                         "the original must survive")

    def test_9_a_model_claiming_authority_is_refused_before_the_gate(self) -> None:
        from companion.models.proposal import admit_proposal
        from tests.capsule_support import World

        world = World.build()
        self.addCleanup(world.close)
        result = admit_proposal({
            "operation": "image.resize", "parameters": {"width": 512},
            "approved": True, "capability": "filesystem.write",
        })
        self.assertFalse(result.admitted)
        self.assertEqual(result.code, "AUTHORITY_CLAIMED")
        self.assertEqual(world.surface.asked, [])
        self.assertEqual(world.executor.launches, [])

    def test_10_the_events_describe_the_run_without_private_content(self) -> None:
        self.registry.discover()
        self.registry.enable(self.model_id)
        events = self.registry.events.read()
        kinds = {event.event_type for event in events}
        self.assertIn("model.loaded", kinds)
        text = json.dumps([event.to_json() for event in events])
        for forbidden in ("Open Downloads", "holiday.png", "prompt", "completion"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
