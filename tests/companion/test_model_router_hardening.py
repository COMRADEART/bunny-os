# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""P0 model-router hardening: GPU/VRAM/NPU, throughput, cloud-context, locality.

Fixtures and injected snapshots only. This host is not claimed to have a GPU
or a GGUF; unknown and NOT_RUN paths are the honest ones.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from capability.simulate import simulate
from companion.agents.adapter import CancellationSignal, ModelListing, StreamEventFactory
from companion.agents.adapters.llamacli import LlamaCliAdapter
from companion.agents.config import AgentConfiguration, ProviderConfiguration
from companion.agents.descriptor import EndpointIdentity
from companion.agents.registry import AgentProviderRegistry, SelectionRequirement
from companion.agents.resources import (
    GPU_OFFLOAD_ALL_LAYERS,
    MachineResources,
    llama_cli_gpu_layers,
    machine_resources_from_inventory,
    probe_host_accelerators,
    selection_memory_budget,
    tier_product,
)
from companion.memory_boundary import (
    MemoryPolicy,
    authorize_remote_generate,
)

from .agents_support import ScriptedAdapter, make_request

_GIB = 1024 ** 3
_MIB = 1024 ** 2
_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "accelerators"


def _sized_provider(*, provider_id: str = "local.sized") -> ProviderConfiguration:
    return ProviderConfiguration(
        provider_id=provider_id,
        adapter_id="sized",
        endpoint=EndpointIdentity(kind="subprocess", locator="sized"),
        program="sized",
    )


def _registry(models: tuple[ModelListing, ...], resources: MachineResources | None) -> AgentProviderRegistry:
    return AgentProviderRegistry(
        AgentConfiguration(providers=(_sized_provider(),)),
        {"sized": ScriptedAdapter(
            adapter_identity="sized",
            models=models,
            probe_available=True,
            probe_detail="sized runtime",
        )},
        machine_resources=resources,
    )


def _models() -> tuple[ModelListing, ...]:
    return (
        ModelListing(model_id="alpha-200m", size_bytes=200 * _MIB, context_limit_tokens=2048),
        ModelListing(model_id="gamma-1p5b", size_bytes=int(1.5 * _GIB), context_limit_tokens=2048),
    )


class AcceleratorProbe(unittest.TestCase):
    def _tree(self) -> Path:
        root = TemporaryDirectory()
        self.addCleanup(root.cleanup)
        return Path(root.name)

    def test_an_empty_sysfs_is_unknown_not_a_fake_gpu(self) -> None:
        snapshot = probe_host_accelerators(
            sys_root=self._tree(), dev_root=self._tree(), usr_bin=self._tree(),
        )
        self.assertFalse(snapshot["gpu_usable"])
        self.assertEqual(snapshot["vram_state"], "unknown")
        self.assertEqual(snapshot["vram_available_bytes"], 0)
        self.assertIn(snapshot["npu_state"], ("unknown", "absent"))

    def test_cuda_usable_requires_both_the_node_and_the_tool(self) -> None:
        dev = self._tree()
        (dev / "nvidiactl").write_text("", encoding="utf-8")
        bin_dir = self._tree()
        snapshot = probe_host_accelerators(
            sys_root=self._tree(), dev_root=dev, usr_bin=bin_dir,
        )
        self.assertFalse(snapshot["gpu_usable"])
        (bin_dir / "nvidia-smi").write_text("#!/bin/true\n", encoding="utf-8")
        snapshot = probe_host_accelerators(
            sys_root=self._tree(), dev_root=dev, usr_bin=bin_dir,
        )
        self.assertTrue(snapshot["gpu_usable"])
        self.assertEqual(snapshot["gpu_runtime"], "cuda")
        self.assertEqual(snapshot["vram_state"], "unknown")

    def test_amdgpu_sysfs_vram_is_measured_not_invented(self) -> None:
        sysfs = self._tree()
        card = sysfs / "class" / "drm" / "card0" / "device"
        card.mkdir(parents=True)
        (card / "mem_info_vram_total").write_text(str(8 * _GIB), encoding="utf-8")
        (card / "mem_info_vram_used").write_text(str(1 * _GIB), encoding="utf-8")
        driver = sysfs / "bus" / "pci" / "drivers" / "amdgpu"
        driver.mkdir(parents=True)
        (card / "driver").symlink_to(driver)
        snapshot = probe_host_accelerators(
            sys_root=sysfs, dev_root=self._tree(), usr_bin=self._tree(),
        )
        self.assertEqual(snapshot["vram_state"], "measured")
        self.assertEqual(snapshot["vram_total_bytes"], 8 * _GIB)
        self.assertEqual(snapshot["vram_available_bytes"], 7 * _GIB)

    def test_npu_sysfs_is_present_unusable_never_scheduled(self) -> None:
        sysfs = self._tree()
        accel = sysfs / "class" / "accel" / "accel0"
        accel.mkdir(parents=True)
        snapshot = probe_host_accelerators(
            sys_root=sysfs, dev_root=self._tree(), usr_bin=self._tree(),
        )
        self.assertEqual(snapshot["npu_state"], "present-unusable")
        self.assertFalse(snapshot["gpu_usable"])

    def test_fixture_files_do_not_claim_live_hardware(self) -> None:
        for name in ("gpu_present.json", "gpu_absent.json", "gpu_unknown.json"):
            document = json.loads((_FIXTURES / name).read_text(encoding="utf-8"))
            self.assertIn(document["kind"], ("fixture", "injected"))
            self.assertNotEqual(document.get("source"), "live-host")


class SelectionBudget(unittest.TestCase):
    def test_gpu_with_measured_vram_uses_vram_not_ram(self) -> None:
        resources = MachineResources(
            available_ram_bytes=16 * _GIB,
            memory_pressure_level="nominal",
            gpu_usable=True,
            gpu_runtime="cuda",
            vram_state="measured",
            vram_available_bytes=6 * _GIB,
        )
        budget, axis = selection_memory_budget(resources)
        self.assertEqual(axis, "vram")
        self.assertEqual(budget, 6 * _GIB)

    def test_gpu_with_unknown_vram_does_not_invent_a_pool(self) -> None:
        resources = MachineResources(
            available_ram_bytes=16 * _GIB,
            memory_pressure_level="nominal",
            gpu_usable=True,
            gpu_runtime="cuda",
            vram_state="unknown",
            vram_available_bytes=0,
        )
        budget, axis = selection_memory_budget(resources)
        self.assertEqual(axis, "ram")
        self.assertEqual(budget, 8 * _GIB)

    def test_tier_product_is_none_without_measured_throughput(self) -> None:
        resources = MachineResources(
            available_ram_bytes=16 * _GIB,
            memory_pressure_level="nominal",
            gpu_usable=True,
            vram_state="measured",
            vram_available_bytes=8 * _GIB,
        )
        self.assertIsNone(tier_product(resources))

    def test_tier_product_uses_measured_throughput_times_usable_memory(self) -> None:
        resources = MachineResources(
            available_ram_bytes=16 * _GIB,
            memory_pressure_level="nominal",
            gpu_usable=True,
            vram_state="measured",
            vram_available_bytes=8 * _GIB,
            throughput_tokens_per_second=40.0,
        )
        self.assertEqual(tier_product(resources), int(8 * _GIB * 40.0))


class GpuAwareDiscovery(unittest.TestCase):
    def test_measured_vram_binds_a_model_that_fits_the_card(self) -> None:
        registry = _registry(
            _models(),
            MachineResources(
                available_ram_bytes=16 * _GIB,
                memory_pressure_level="nominal",
                gpu_usable=True,
                gpu_runtime="cuda",
                vram_state="measured",
                vram_available_bytes=512 * _MIB,
            ),
        )
        descriptor = registry.descriptor("local.sized", monotonic=0.0)
        self.assertEqual(descriptor.model_id, "alpha-200m")

    def test_gpu_absent_keeps_the_ram_largest_that_fits(self) -> None:
        registry = _registry(
            _models(),
            MachineResources(
                available_ram_bytes=16 * _GIB,
                memory_pressure_level="nominal",
                gpu_usable=False,
                vram_state="unknown",
            ),
        )
        descriptor = registry.descriptor("local.sized", monotonic=0.0)
        self.assertEqual(descriptor.model_id, "gamma-1p5b")

    def test_measured_throughput_ranks_only_when_every_fitter_was_measured(self) -> None:
        models = (
            ModelListing(model_id="slow-large", size_bytes=_GIB, context_limit_tokens=2048),
            ModelListing(model_id="fast-small", size_bytes=400 * _MIB, context_limit_tokens=2048),
        )
        resources = MachineResources(
            available_ram_bytes=16 * _GIB,
            memory_pressure_level="nominal",
            throughput_by_model=(("slow-large", 5.0), ("fast-small", 80.0)),
        )
        descriptor = _registry(models, resources).descriptor("local.sized", monotonic=0.0)
        self.assertEqual(descriptor.model_id, "fast-small")

    def test_mixed_throughput_does_not_zero_the_unmeasured_model(self) -> None:
        models = (
            ModelListing(model_id="measured-small", size_bytes=200 * _MIB, context_limit_tokens=2048),
            ModelListing(model_id="unmeasured-large", size_bytes=_GIB, context_limit_tokens=2048),
        )
        resources = MachineResources(
            available_ram_bytes=16 * _GIB,
            memory_pressure_level="nominal",
            throughput_by_model=(("measured-small", 90.0),),
        )
        descriptor = _registry(models, resources).descriptor("local.sized", monotonic=0.0)
        self.assertEqual(descriptor.model_id, "unmeasured-large")

    def test_selection_explains_gpu_and_excludes_remote_from_fallback(self) -> None:
        local = _sized_provider(provider_id="local.sized")
        from companion.agents.credentials import CredentialReference
        from companion.agents.wire import HttpTarget

        remote = ProviderConfiguration(
            provider_id="remote.scripted",
            adapter_id="scripted-remote",
            endpoint=EndpointIdentity(kind="remote-https", locator="api.example.test:443/v1"),
            http=HttpTarget(scheme="https", host="api.example.test", port=443, base_path="/v1"),
            model_id="remote-model",
            remote=True,
            credential=CredentialReference(kind="environment", locator="BUNNY_TEST_REMOTE_KEY"),
            cost_class="metered",
            maximum_privacy_class="internal",
            retention="ephemeral",
            trains_on_input=False,
        )
        resources = MachineResources(
            available_ram_bytes=16 * _GIB,
            memory_pressure_level="nominal",
            gpu_usable=True,
            gpu_runtime="cuda",
            vram_state="unknown",
            npu_state="present-unusable",
            accelerator_evidence="fixture: cuda usable, VRAM unknown",
        )
        registry = AgentProviderRegistry(
            AgentConfiguration(providers=(local, remote)),
            {
                "sized": ScriptedAdapter(
                    adapter_identity="sized",
                    models=_models(),
                    probe_available=True,
                    probe_detail="sized",
                ),
                "scripted-remote": ScriptedAdapter(
                    adapter_identity="scripted-remote",
                    models=(ModelListing(model_id="remote-model", size_bytes=1),),
                    probe_available=True,
                    probe_detail="remote",
                ),
            },
            machine_resources=resources,
        )
        explanation = registry.select(
            SelectionRequirement(
                task_class="question", locality="any", cost_limit_units=100,
            ),
            monotonic=0.0,
        )
        self.assertEqual(explanation.selected, "local.sized")
        self.assertTrue(explanation.selected_local)
        self.assertNotIn("remote.scripted", explanation.fallback_order)
        self.assertTrue(any("GPU runtime cuda is usable" in item for item in explanation.decisive_factors))
        self.assertTrue(any("NPU present but unusable" in item for item in explanation.decisive_factors))
        self.assertTrue(any("VRAM is unknown" in item for item in explanation.decisive_factors))


class LlamaCliOffload(unittest.TestCase):
    def test_unknown_gpu_passes_no_offload_flag(self) -> None:
        self.assertIsNone(llama_cli_gpu_layers(None))
        self.assertIsNone(llama_cli_gpu_layers(MachineResources(gpu_usable=False)))

    def test_usable_gpu_requests_all_layers_not_a_vram_split(self) -> None:
        self.assertEqual(
            llama_cli_gpu_layers(MachineResources(gpu_usable=True, gpu_runtime="cuda")),
            GPU_OFFLOAD_ALL_LAYERS,
        )

    def test_generate_requests_n_gpu_layers_when_bound_to_a_usable_gpu(self) -> None:
        adapter = LlamaCliAdapter(
            machine_resources=MachineResources(gpu_usable=True, gpu_runtime="cuda"),
        )
        configuration = ProviderConfiguration(
            provider_id="local.llamacli", adapter_id="llamacli",
            endpoint=EndpointIdentity(kind="subprocess", locator="llama-cli"),
            program="llama-cli",
            model_id="model.gguf",
        )
        events = StreamEventFactory(
            request_id="req-1", provider_id="local.llamacli", monotonic=lambda: 0.0,
        )
        captured: list[list[str]] = []

        def fake_popen(argv, **_kwargs):
            captured.append(list(argv))
            raise OSError("test: no spawn")

        with mock.patch("companion.agents.adapters.llamacli._resolve_program",
                        return_value=("/usr/bin/llama-cli", "")), \
             mock.patch("companion.agents.adapters.llamacli._resolve_model",
                        return_value=(Path("/tmp/model.gguf"), "")), \
             mock.patch("companion.agents.adapters.llamacli.subprocess.Popen",
                        side_effect=fake_popen):
            outcome = adapter.generate(
                make_request(provider_id="local.llamacli"),
                configuration, secret=None,
                emit=lambda _event: None, events=events,
                cancellation=CancellationSignal(),
            )
        self.assertEqual(outcome.failure_kind, "connection")
        self.assertEqual(len(captured), 1)
        self.assertIn("--n-gpu-layers", captured[0])
        self.assertEqual(captured[0][captured[0].index("--n-gpu-layers") + 1], str(GPU_OFFLOAD_ALL_LAYERS))

    def test_generate_does_not_pass_gpu_flags_when_gpu_is_unknown(self) -> None:
        adapter = LlamaCliAdapter()
        configuration = ProviderConfiguration(
            provider_id="local.llamacli", adapter_id="llamacli",
            endpoint=EndpointIdentity(kind="subprocess", locator="llama-cli"),
            program="llama-cli",
            model_id="model.gguf",
        )
        events = StreamEventFactory(
            request_id="req-1", provider_id="local.llamacli", monotonic=lambda: 0.0,
        )
        captured: list[list[str]] = []

        def fake_popen(argv, **_kwargs):
            captured.append(list(argv))
            raise OSError("test: no spawn")

        with mock.patch("companion.agents.adapters.llamacli._resolve_program",
                        return_value=("/usr/bin/llama-cli", "")), \
             mock.patch("companion.agents.adapters.llamacli._resolve_model",
                        return_value=(Path("/tmp/model.gguf"), "")), \
             mock.patch("companion.agents.adapters.llamacli.subprocess.Popen",
                        side_effect=fake_popen):
            adapter.generate(
                make_request(provider_id="local.llamacli"),
                configuration, secret=None,
                emit=lambda _event: None, events=events,
                cancellation=CancellationSignal(),
            )
        self.assertEqual(len(captured), 1)
        self.assertNotIn("--n-gpu-layers", captured[0])
        self.assertNotIn("-ngl", captured[0])


class InventoryBridge(unittest.TestCase):
    def test_gaming_desktop_inventory_marks_cuda_usable_with_measured_vram(self) -> None:
        inventory = simulate("gaming-desktop")
        resources = machine_resources_from_inventory(
            inventory,
            ram=MachineResources(available_ram_bytes=16 * _GIB, memory_pressure_level="nominal"),
        )
        self.assertTrue(resources.gpu_usable)
        self.assertEqual(resources.gpu_runtime, "cuda")
        self.assertEqual(resources.vram_state, "measured")
        self.assertGreater(resources.vram_available_bytes, 0)

    def test_pi_class_inventory_does_not_claim_cuda_or_vram(self) -> None:
        inventory = simulate("raspberry-pi-class")
        resources = machine_resources_from_inventory(inventory)
        self.assertFalse(resources.gpu_usable)
        self.assertNotEqual(resources.gpu_runtime, "cuda")


class CloudContextWire(unittest.TestCase):
    def test_current_request_is_authorised_after_remote_dispatch(self) -> None:
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
            policy=MemoryPolicy(),
        )
        self.assertTrue(decision.allowed)
        self.assertIsNotNone(decision.released)
        self.assertNotIn("summary_text", decision.released or {})

    def test_summary_text_in_the_payload_refuses_the_whole_generate(self) -> None:
        decision = authorize_remote_generate(
            {
                "user_request": "hello",
                "summary_text": "yesterday we talked about secrets",
            },
            classification="internal",
            remote_transfer_ceiling="internal",
            remote_dispatch_granted=True,
        )
        self.assertFalse(decision.allowed)
        self.assertIn("summary", decision.reason)

    def test_durable_records_are_refused(self) -> None:
        decision = authorize_remote_generate(
            {"user_request": "hello", "durable": {"body": "life story"}},
            classification="internal",
            remote_transfer_ceiling="internal",
            remote_dispatch_granted=True,
        )
        self.assertFalse(decision.allowed)

    def test_without_remote_dispatch_nothing_leaves(self) -> None:
        decision = authorize_remote_generate(
            {"user_request": "hello"},
            classification="internal",
            remote_transfer_ceiling="internal",
            remote_dispatch_granted=False,
        )
        self.assertFalse(decision.allowed)

    def test_session_and_durable_memory_stay_off_on_the_effective_policy(self) -> None:
        decision = authorize_remote_generate(
            {
                "user_request": "hello",
                "instruction": "answer",
                "system_policy_reference": "bunny-agent-policy/1",
                "classification": "internal",
                "task_id": "t",
                "purpose": "result",
            },
            classification="internal",
            remote_transfer_ceiling="internal",
            remote_dispatch_granted=True,
            policy=MemoryPolicy(session=True, durable=True, cloud_context="minimized"),
        )
        self.assertTrue(decision.allowed)
        self.assertNotIn("durable", decision.released or {})
        self.assertNotIn("session_memory", decision.released or {})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
