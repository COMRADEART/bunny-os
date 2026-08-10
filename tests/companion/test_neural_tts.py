# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Neural speech providers stay local, bounded, deterministic and honest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest

from companion.settings import Settings, SettingsError, VoiceSettings
from companion.voice.chunking import MAX_CHUNK_CHARACTERS, sentence_chunks
from companion.voice.execution import CancellationSignal, ExecutableRefused, PrivateWorkspace
from companion.voice.neural import KittenTTSProvider, PocketTTSProvider, _read_installation
from companion.voice.provider import ProviderRegistry

from .voice_support import make_request, write_wav


REPOSITORY = Path(__file__).resolve().parents[2]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _installation(
    parent: Path,
    *,
    provider_id: str = "pocket",
    model_id: str = "english",
    voice_id: str = "bunny-default",
) -> Path:
    root = parent / provider_id / model_id
    root.mkdir(parents=True)
    model = root / ("model.onnx" if provider_id == "kitten" else "model.safetensors")
    voice = root / ("voices.npz" if provider_id == "kitten" else "bunny-default.safetensors")
    model.write_bytes(b"pinned-model-bytes")
    voice.write_bytes(b"pinned-prepared-voice")
    files = []
    for path in (model, voice):
        files.append({
            "path": path.name,
            "sizeBytes": path.stat().st_size,
            "sha256": _sha256(path),
        })
    (root / "manifest.json").write_text(json.dumps({
        "schemaVersion": 1,
        "providerId": provider_id,
        "modelId": model_id,
        "sampleRate": 24_000,
        "files": files,
        "voices": [{
            "voiceId": voice_id,
            "name": "Bunny Default",
            "path": voice.name,
            "preference": 1.0,
            "default": True,
        }],
    }, sort_keys=True), encoding="utf-8")
    return root


class _FakeClient:
    def __init__(self, *, stale: bool = False, gate: threading.Event | None = None) -> None:
        self.stale = stale
        self.gate = gate
        self.calls: list[dict[str, object]] = []
        self.stopped = False
        self.closed = False

    def call(self, document, *, timeout_seconds):
        del timeout_seconds
        self.calls.append(dict(document))
        if document["op"] == "initialize":
            return {
                "ready": True,
                "providerId": document["providerId"],
                "modelId": document["modelId"],
            }
        if self.gate is not None:
            self.gate.wait(10.0)
        output = Path(str(document["outputPath"]))
        write_wav(output, sample_rate=int(document["sampleRate"]))
        generation = "an-old-generation" if self.stale else document["generationId"]
        return {"succeeded": True, "generationId": generation}

    def stop(self) -> None:
        self.stopped = True
        if self.gate is not None:
            self.gate.set()

    def close(self) -> None:
        self.closed = True


class _Factory:
    def __init__(self, **client_options) -> None:
        self.client_options = client_options
        self.clients: list[_FakeClient] = []

    def __call__(self, *_args, **_kwargs) -> _FakeClient:
        client = _FakeClient(**self.client_options)
        self.clients.append(client)
        return client


def _trusted(_name: str):
    return "/usr/bin/bunny-voice-neural-worker", True


class _BlockingInitializationClient(_FakeClient):
    def __init__(self, entered: threading.Event, release: threading.Event) -> None:
        super().__init__()
        self.entered = entered
        self.release = release

    def call(self, document, *, timeout_seconds):
        if document["op"] == "initialize":
            self.entered.set()
            self.release.wait(10.0)
        return super().call(document, timeout_seconds=timeout_seconds)


class ChunkingTests(unittest.TestCase):
    def test_sentence_boundaries_are_preserved_and_bounded(self) -> None:
        text = (
            "Open Files. I found the document you requested; it is in Downloads. "
            + "This deliberately long sentence has many words, " * 20
            + "and it still ends cleanly."
        )
        chunks = sentence_chunks(text)
        self.assertGreater(len(chunks), 2)
        self.assertTrue(all(0 < len(item) <= MAX_CHUNK_CHARACTERS for item in chunks))
        self.assertEqual(" ".join(chunks), " ".join(text.split()))

    def test_abbreviations_do_not_force_tiny_chunks(self) -> None:
        self.assertEqual(
            sentence_chunks("Ask Dr. Bunny to open Files."),
            ("Ask Dr. Bunny to open Files.",),
        )

    def test_empty_text_produces_no_synthesis_chunks(self) -> None:
        self.assertEqual(sentence_chunks("   \n  "), ())


class ReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.parent = Path(temporary.name)

    def test_missing_runtime_has_a_structured_state(self) -> None:
        def absent(_name: str):
            raise ExecutableRefused("worker is not installed")

        provider = PocketTTSProvider(resolver=absent, roots={"english": (self.parent,)})
        self.addCleanup(provider.close)
        health = provider.health(refresh=True)
        self.assertEqual(health.status, "RUNTIME_MISSING")
        self.assertFalse(health.ready)

    def test_missing_model_has_a_structured_state(self) -> None:
        provider = PocketTTSProvider(resolver=_trusted, roots={"english": (self.parent,)})
        self.addCleanup(provider.close)
        health = provider.health(refresh=True)
        self.assertEqual(health.status, "MODEL_MISSING")
        self.assertFalse(health.ready)

    def test_corrupt_model_is_not_ready(self) -> None:
        root = _installation(self.parent)
        (root / "model.safetensors").write_bytes(b"changed-after-manifest")
        provider = PocketTTSProvider(resolver=_trusted, roots={"english": (root,)})
        self.addCleanup(provider.close)
        health = provider.health(refresh=True)
        self.assertEqual(health.status, "MODEL_CORRUPT")
        self.assertIn("wrong size", health.detail)

    def test_unhashed_prepared_voice_is_rejected(self) -> None:
        root = _installation(self.parent)
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        manifest["files"] = manifest["files"][:1]
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        provider = PocketTTSProvider(resolver=_trusted, roots={"english": (root,)})
        self.addCleanup(provider.close)
        health = provider.health(refresh=True)
        self.assertEqual(health.status, "MODEL_CORRUPT")
        self.assertIn("no pinned digest", health.detail)

    def test_ready_means_the_worker_initialized_the_model_and_voice(self) -> None:
        root = _installation(self.parent)
        factory = _Factory()
        provider = PocketTTSProvider(
            resolver=_trusted,
            roots={"english": (root,)},
            worker_factory=factory,
            idle_unload_seconds=0,
        )
        self.addCleanup(provider.close)
        health = provider.health(refresh=True)
        self.assertEqual(health.status, "READY")
        self.assertTrue(health.ready)
        self.assertEqual(factory.clients[0].calls[0]["op"], "initialize")

    def test_service_startup_verifies_assets_without_loading_inference(self) -> None:
        root = _installation(self.parent)
        factory = _Factory()
        provider = PocketTTSProvider(
            resolver=_trusted,
            roots={"english": (root,)},
            worker_factory=factory,
            idle_unload_seconds=0,
        )
        self.addCleanup(provider.close)
        first = provider.health()
        self.assertEqual(first.status, "INITIALIZING")
        self.assertFalse(first.ready)
        for _ in range(10_000):
            measured = provider.health()
            if measured.status == "MODEL_VERIFIED":
                break
            threading.Event().wait(0.001)
        self.assertEqual(measured.status, "MODEL_VERIFIED")
        self.assertFalse(measured.ready)
        self.assertEqual(factory.clients, [], "login readiness loaded the inference worker")


class NeuralSynthesisTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.parent = Path(temporary.name)

    def _pocket(self, factory: _Factory) -> PocketTTSProvider:
        root = _installation(self.parent)
        provider = PocketTTSProvider(
            resolver=_trusted,
            roots={"english": (root,)},
            worker_factory=factory,
            idle_unload_seconds=0,
        )
        self.addCleanup(provider.close)
        return provider

    def test_default_provider_order_is_pocket_then_kitten_then_system(self) -> None:
        from companion.voice.providers import local_providers

        self.assertEqual(
            [item.declaration.provider_id for item in local_providers()],
            ["pocket", "kitten", "espeak-ng", "speech-dispatcher"],
        )

    def test_explicit_kitten_choice_never_climbs_back_to_pocket(self) -> None:
        registry = ProviderRegistry([
            PocketTTSProvider(resolver=lambda _name: (_ for _ in ()).throw(ExecutableRefused("absent"))),
            KittenTTSProvider(resolver=lambda _name: (_ for _ in ()).throw(ExecutableRefused("absent"))),
        ])
        self.addCleanup(registry.close)
        selection = registry.select(
            make_request(provider_id="kitten"),
            preferred_provider_id="kitten",
        )
        self.assertFalse(selection.selected)
        self.assertEqual([item[0] for item in selection.rejected], ["kitten"])

    def test_first_selection_waits_for_pocket_warmup_instead_of_skipping_default(self) -> None:
        root = _installation(self.parent)
        factory = _Factory()
        pocket = PocketTTSProvider(
            resolver=_trusted,
            roots={"english": (root,)},
            worker_factory=factory,
            idle_unload_seconds=0,
        )
        self.addCleanup(pocket.close)
        self.assertEqual(pocket.health().status, "INITIALIZING")
        registry = ProviderRegistry([pocket])
        selection = registry.select(
            make_request(provider_id="pocket"),
            preferred_provider_id="pocket",
        )
        self.assertTrue(selection.selected, selection.detail)
        self.assertEqual(selection.provider.declaration.provider_id, "pocket")

    def test_synthesis_uses_sentence_chunks_and_returns_real_wav_metadata(self) -> None:
        factory = _Factory()
        provider = self._pocket(factory)
        workspace = PrivateWorkspace()
        self.addCleanup(workspace.close)
        result = provider.synthesize(make_request(
            provider_id="pocket",
            text="The first sentence is ready. The second sentence is also ready.",
        ), workspace)
        self.assertTrue(result.succeeded, result.detail)
        self.assertGreater(result.frame_count, 0)
        synthesis = factory.clients[0].calls[-1]
        self.assertEqual(synthesis["op"], "synthesize")
        self.assertEqual(" ".join(synthesis["chunks"]), "The first sentence is ready. The second sentence is also ready.")

    def test_stale_generation_audio_is_refused(self) -> None:
        provider = self._pocket(_Factory(stale=True))
        workspace = PrivateWorkspace()
        self.addCleanup(workspace.close)
        result = provider.synthesize(make_request(provider_id="pocket"), workspace)
        self.assertFalse(result.succeeded)
        self.assertIn("stale generation", result.detail)

    def test_cancellation_stops_the_resident_inference_worker(self) -> None:
        gate = threading.Event()
        factory = _Factory(gate=gate)
        provider = self._pocket(factory)
        workspace = PrivateWorkspace()
        self.addCleanup(workspace.close)
        result: list[object] = []
        request = make_request(request_id="cancel-me", provider_id="pocket")
        thread = threading.Thread(target=lambda: result.append(provider.synthesize(request, workspace)))
        thread.start()
        for _ in range(1000):
            if factory.clients and len(factory.clients[0].calls) >= 2:
                break
            threading.Event().wait(0.001)
        self.assertTrue(provider.cancel("cancel-me"))
        thread.join(10.0)
        self.assertFalse(thread.is_alive())
        self.assertTrue(factory.clients[0].stopped)

    def test_cancellation_signal_interrupts_blocking_neural_inference(self) -> None:
        gate = threading.Event()
        factory = _Factory(gate=gate)
        provider = self._pocket(factory)
        workspace = PrivateWorkspace()
        self.addCleanup(workspace.close)
        signal = CancellationSignal(name="cancel-signal")
        result: list[object] = []
        request = make_request(request_id="signal-cancel", provider_id="pocket")
        thread = threading.Thread(
            target=lambda: result.append(
                provider.synthesize(request, workspace, cancellation=signal)
            )
        )
        thread.start()
        for _ in range(1000):
            if factory.clients and len(factory.clients[0].calls) >= 2:
                break
            threading.Event().wait(0.001)
        self.assertTrue(signal.cancel("interrupted by a newer request"))
        thread.join(2.0)
        self.assertFalse(thread.is_alive(), "neural cancellation must not wait for inference timeout")
        self.assertTrue(factory.clients[0].stopped)
        self.assertFalse(result[0].succeeded)
        self.assertIn("newer request", result[0].detail)

    def test_pocket_reports_unsupported_rate_as_an_explicit_degradation(self) -> None:
        provider = self._pocket(_Factory())
        workspace = PrivateWorkspace()
        self.addCleanup(workspace.close)
        result = provider.synthesize(make_request(
            provider_id="pocket", speaking_rate=1.25,
        ), workspace)
        self.assertTrue(result.succeeded)
        self.assertTrue(any("rate" in item for item in result.degradations))


class NeuralSettingTests(unittest.TestCase):
    def test_pocket_is_the_default_and_low_resource_maps_to_kitten(self) -> None:
        default = VoiceSettings()
        self.assertEqual(default.provider_id, "pocket")
        low_resource = VoiceSettings(performance_mode="low-resource")
        preferences = Settings(voice=low_resource).voice_preferences()
        self.assertEqual(preferences.provider_id, "kitten")
        self.assertEqual(preferences.model_id, "nano-int8")

    def test_quality_mode_prefers_pocket_even_after_a_lightweight_selection(self) -> None:
        configured = VoiceSettings(provider_id="kitten", performance_mode="quality")
        preferences = Settings(voice=configured).voice_preferences()
        self.assertEqual(preferences.provider_id, "pocket")
        self.assertEqual(preferences.model_id, "english")

    def test_model_and_voice_settings_never_accept_paths(self) -> None:
        for field in ("model_id", "voice_id"):
            with self.subTest(field=field), self.assertRaises(SettingsError):
                VoiceSettings(**{field: "../../outside"})

    def test_a_model_from_another_provider_is_invalid_configuration(self) -> None:
        with self.assertRaises(SettingsError):
            VoiceSettings(provider_id="pocket", model_id="nano-int8")
        with self.assertRaises(SettingsError):
            VoiceSettings(provider_id="espeak-ng", model_id="english")


class BundledAssetTests(unittest.TestCase):
    """The bytes copied into a fresh image satisfy the runtime's own gate."""

    def test_bundled_pocket_and_kitten_manifests_validate_completely(self) -> None:
        for provider_id, model_id in (("pocket", "english"), ("kitten", "nano-int8")):
            with self.subTest(provider=provider_id):
                root = REPOSITORY / "assets/voice/tts" / provider_id / model_id
                installation, status, detail = _read_installation(root, provider_id, model_id)
                self.assertIsNotNone(installation, detail)
                self.assertEqual(status, "READY")
                self.assertTrue(installation.voices)

    def test_pocket_configuration_has_no_remote_model_reference(self) -> None:
        config = (REPOSITORY / "assets/voice/tts/pocket/english/config.yaml").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("hf://", config)
        self.assertNotIn("http://", config)
        self.assertNotIn("https://", config)
        self.assertIn("weights_path: model.safetensors", config)

    def test_cpu_wheel_matches_its_upstream_pinned_digest(self) -> None:
        root = REPOSITORY / "assets/voice/runtime/wheels"
        manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["wheels"]), 1)
        record = manifest["wheels"][0]
        wheel = root / record["fileName"]
        self.assertEqual(wheel.stat().st_size, record["sizeBytes"])
        self.assertEqual(_sha256(wheel), record["sha256"])

    def test_provenance_accounts_for_every_selected_tts_byte(self) -> None:
        voice_root = REPOSITORY / "assets/voice"
        provenance = json.loads((voice_root / "PROVENANCE.json").read_text(encoding="utf-8"))
        measured = sum(
            path.stat().st_size
            for root in (voice_root / "tts", voice_root / "runtime", voice_root / "licenses")
            for path in root.rglob("*")
            if path.is_file()
        )
        self.assertEqual(
            measured,
            provenance["textToSpeech"]["selectedAssetAndNoticeSizeBytes"],
        )
        self.assertFalse(provenance["automaticDownload"])
        self.assertFalse(provenance["networkRequiredAtRuntime"])


if __name__ == "__main__":
    unittest.main()
