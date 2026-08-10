# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Public Alpha integration surfaces, asserted where they can be.

Two things these tests deliberately do *not* do. They do not open a window —
every decision the Alpha surfaces make lives outside GTK, and that is the whole
reason the onboarding model, the character policy and the diagnostic report are
separate from the windows that draw them. And they do not require a machine with
a GPU, a microphone or a model: the assertions are about the *shape* of the
answer — that presence and operation were measured separately, that a rung was
descended for a stated reason — rather than about which answer this host gives.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import tempfile
import unittest

from companion import cli as companion_cli
from companion.character.defaults import default_character_paths
from companion.character.importer import PackageRegistry
from companion.character.policy import (
    POLICY_LADDER,
    apply_default_character_policy,
    default_character_decision,
    read_policy_state,
    restore_selected_package,
)
from companion.hardware import capability_record, hardware_facts, operational_probes
from companion.identity import ALPHA_VERSION, RELEASE_CHANNELS, build_identity, derive_build_id
from companion.onboarding import ONBOARDING_STEPS, OnboardingModel
from companion.onboarding.providers import LocalProviderFinding, LocalProviderSurvey, ModelSummary
from companion.onboarding.speech import SpeechSurvey
from companion.settings import (
    SettingsError, Settings, load_settings, save_settings, update_settings,
)
from companion.support.diagnose import RECOVERY_ACTIONS, diagnose
from companion.support.export import EXCLUDED_FROM_BUNDLE, build_bundle
from companion.support.safemode import (
    FAILURE_THRESHOLD,
    SAFE_MODE_RESTRICTIONS,
    clear_safe_mode,
    consume_safe_mode,
    local_only_configuration,
    read_safe_mode,
    record_launch_outcome,
    request_safe_mode,
    safe_mode_environment,
    service_overrides,
)

REPOSITORY = Path(__file__).resolve().parents[2]


class TemporaryRootTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bunny-alpha-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def registry(self) -> PackageRegistry:
        return PackageRegistry(self.root / "characters", built_in_paths=default_character_paths())


class DefaultCharacterPolicyTests(TemporaryRootTests):
    """§3. The four rules, each asserted as the behaviour it forbids."""

    def test_ladder_descends_to_the_highest_usable_rung(self) -> None:
        expected = {
            "full-3d": "full-3d", "lightweight-3d": "lightweight-3d",
            "animated-2d": "animated-2d", "static-image": "static-image",
            "text-only": "text-only",
        }
        for eligible, rung in expected.items():
            with self.subTest(eligible=eligible):
                registry = PackageRegistry(
                    Path(tempfile.mkdtemp(dir=self.root)),
                    built_in_paths=default_character_paths(),
                )
                decision = apply_default_character_policy(registry, eligible=eligible)
                self.assertEqual(decision.rung, rung)

    def test_text_only_draws_no_package(self) -> None:
        decision = apply_default_character_policy(self.registry(), eligible="text-only")
        self.assertEqual(decision.package_id, "")
        self.assertIn("text-only", decision.summary)

    def test_a_user_selection_is_never_replaced(self) -> None:
        registry = self.registry()
        apply_default_character_policy(registry, eligible="full-3d")
        chosen = registry.built_ins()[0].package_id
        registry.select(chosen)
        decision = apply_default_character_policy(registry, eligible="full-3d")
        self.assertTrue(decision.preserved_user_choice)
        self.assertFalse(decision.applied)
        self.assertEqual(registry.selected().package_id, chosen)

    def test_a_lost_gpu_does_not_change_the_selected_package(self) -> None:
        """The rule presentation degradation exists to make unnecessary."""
        registry = self.registry()
        first = apply_default_character_policy(registry, eligible="full-3d")
        self.assertEqual(first.package_id, "bunny-default-3d")
        second = apply_default_character_policy(registry, eligible="animated-2d")
        self.assertFalse(second.applied)
        self.assertEqual(registry.selected().package_id, "bunny-default-3d")
        self.assertTrue(any("degrades instead" in reason for reason in second.reasons))

    def test_a_gained_gpu_may_raise_the_selection(self) -> None:
        registry = self.registry()
        apply_default_character_policy(registry, eligible="animated-2d")
        raised = apply_default_character_policy(registry, eligible="full-3d")
        self.assertTrue(raised.applied)
        self.assertEqual(registry.selected().package_id, "bunny-default-3d")

    def test_a_package_that_will_not_validate_is_not_eligible_at_its_rung(self) -> None:
        def refuse_three_d(bundle: str, rung) -> tuple[str, str]:
            if bundle == "three-d":
                return "", "the bundled three-d package did not validate: forced for the test"
            return "org.bunny-os.default-bunny", "validated"

        decision = default_character_decision(
            eligible="full-3d", registry=self.registry(), validator=refuse_three_d,
        )
        self.assertEqual(decision.package_id, "org.bunny-os.default-bunny")
        self.assertEqual(decision.rung, "animated-2d")
        self.assertEqual(decision.eligible_rung, "full-3d")
        self.assertTrue(any("did not validate" in reason for reason in decision.reasons))

    def test_restore_puts_the_user_choice_back(self) -> None:
        registry = self.registry()
        apply_default_character_policy(registry, eligible="animated-2d")
        registry.select("bunny-default-3d")
        apply_default_character_policy(registry, eligible="animated-2d")
        self.assertEqual(read_policy_state(registry).user_package_id, "bunny-default-3d")
        restored = restore_selected_package(registry, eligible="full-3d")
        self.assertTrue(restored.applied)
        self.assertEqual(registry.selected().package_id, "bunny-default-3d")

    def test_restore_refuses_when_capability_does_not_permit(self) -> None:
        registry = self.registry()
        apply_default_character_policy(registry, eligible="animated-2d")
        registry.select("bunny-default-3d")
        apply_default_character_policy(registry, eligible="animated-2d")
        refused = restore_selected_package(registry, eligible="static-image")
        self.assertFalse(refused.applied)
        self.assertTrue(any("until capability allows it" in reason for reason in refused.reasons))

    def test_a_dry_run_writes_nothing(self) -> None:
        """``survey_character`` asks the policy what it would do, on every draw
        of the first-run character page. That must not persist anything."""
        registry = self.registry()
        apply_default_character_policy(registry, eligible="animated-2d")
        registry.select("bunny-default-3d")
        before = read_policy_state(registry)
        decision = apply_default_character_policy(registry, eligible="full-3d", dry_run=True)
        self.assertTrue(decision.preserved_user_choice)
        self.assertEqual(read_policy_state(registry), before)

    def test_the_recorded_user_choice_follows_the_user(self) -> None:
        """Recovery restores what the user chose, not what they chose first.

        The first version recorded the user's selection only when nothing was on
        file, so a person who changed their mind twice would have recovery put
        back the character they abandoned.
        """
        registry = self.registry()
        apply_default_character_policy(registry, eligible="animated-2d")
        registry.select("bunny-default-3d")
        apply_default_character_policy(registry, eligible="animated-2d")
        self.assertEqual(read_policy_state(registry).user_package_id, "bunny-default-3d")
        registry.select("org.bunny-os.default-bunny")
        apply_default_character_policy(registry, eligible="animated-2d")
        self.assertEqual(
            read_policy_state(registry).user_package_id, "org.bunny-os.default-bunny",
        )

    def test_the_ladder_names_a_bundle_not_a_package_id(self) -> None:
        """The two built-ins disagree about their own naming; the ladder must not
        assume either. ``org.bunny-os.default-bunny`` and ``bunny-default-3d``."""
        for _rung, bundle in POLICY_LADDER:
            self.assertIn(bundle, ("three-d", "two-d", ""))


class SafeModeTests(TemporaryRootTests):
    """§19 and §34. A mode that is a combination of specified flags."""

    def test_off_by_default(self) -> None:
        self.assertFalse(read_safe_mode(self.root).enabled)
        self.assertEqual(safe_mode_environment(root=self.root), {})
        self.assertEqual(service_overrides(root=self.root), {})

    def test_a_one_shot_request_is_spent_by_one_launch(self) -> None:
        request_safe_mode(reason="test", origin="user", root=self.root)
        self.assertTrue(consume_safe_mode(self.root).enabled)
        self.assertFalse(read_safe_mode(self.root).enabled)

    def test_a_sticky_request_survives(self) -> None:
        request_safe_mode(reason="test", origin="user", sticky=True, root=self.root)
        self.assertTrue(consume_safe_mode(self.root).enabled)
        self.assertTrue(read_safe_mode(self.root).enabled)
        clear_safe_mode(self.root)
        self.assertFalse(read_safe_mode(self.root).enabled)

    def test_three_failed_launches_arm_safe_mode(self) -> None:
        for attempt in range(1, FAILURE_THRESHOLD):
            self.assertFalse(record_launch_outcome(succeeded=False, root=self.root).enabled, attempt)
        armed = record_launch_outcome(succeeded=False, root=self.root)
        self.assertTrue(armed.enabled)
        self.assertTrue(armed.automatic)
        self.assertEqual(armed.origin, "launcher")

    def test_a_successful_launch_clears_the_counter(self) -> None:
        record_launch_outcome(succeeded=False, root=self.root)
        record_launch_outcome(succeeded=True, root=self.root)
        self.assertEqual(read_safe_mode(self.root).consecutive_failures, 0)

    def test_the_environment_names_every_restriction(self) -> None:
        request_safe_mode(reason="test", origin="user", sticky=True, root=self.root)
        environment = safe_mode_environment(root=self.root)
        for _identifier, variable, _effect in SAFE_MODE_RESTRICTIONS:
            self.assertEqual(environment[variable], "1")
        self.assertEqual(environment["BUNNY_COMPANION_SAFE_MODE"], "1")

    def test_service_overrides_turn_off_exactly_the_named_subsystems(self) -> None:
        request_safe_mode(reason="test", origin="user", sticky=True, root=self.root)
        overrides = service_overrides(root=self.root)
        self.assertFalse(overrides["speech_enabled"])
        self.assertFalse(overrides["desktop_enabled"])
        self.assertFalse(overrides["voice_enabled"])
        # §19 keeps a local provider when one is explicitly selected, so the
        # agent runtime is built and the remote refusal is the configuration's.
        self.assertTrue(overrides["agents_enabled"])

    def test_remote_providers_are_removed_not_disabled(self) -> None:
        from companion.agents.config import (
            AgentConfiguration, CredentialReference, EndpointIdentity, HttpTarget,
            ProviderConfiguration,
        )

        remote = ProviderConfiguration(
            provider_id="remote.example", adapter_id="openai_compat", remote=True,
            endpoint=EndpointIdentity(kind="remote-https", locator="api.example.test"),
            http=HttpTarget(scheme="https", host="api.example.test", port=443),
            credential=CredentialReference(kind="secret-service", locator="bunny/example"),
            maximum_privacy_class="internal",
            # "metered is the honest floor for somebody else's computer" — the
            # configuration refuses a free remote provider, so the test says so.
            cost_class="metered",
        )
        local = ProviderConfiguration(
            provider_id="local.ollama", adapter_id="ollama",
            endpoint=EndpointIdentity(kind="loopback-http", locator="127.0.0.1:11434"),
            http=HttpTarget(scheme="http", host="127.0.0.1", port=11434),
        )
        filtered = local_only_configuration(AgentConfiguration(providers=(local, remote)))
        self.assertEqual([item.provider_id for item in filtered.providers], ["local.ollama"])

    def test_a_corrupt_flag_file_fails_open(self) -> None:
        (self.root).mkdir(parents=True, exist_ok=True)
        (self.root / "safe-mode.json").write_text("{not json", encoding="utf-8")
        self.assertFalse(read_safe_mode(self.root).enabled)


class OnboardingModelTests(unittest.TestCase):
    """§7. Ten steps, and an offline machine that completes all of them."""

    def test_the_ten_steps_are_the_ten_steps(self) -> None:
        self.assertEqual(
            [step.step_id for step in ONBOARDING_STEPS],
            ["welcome", "privacy", "character", "microphone", "speaker", "providers",
             "local_model", "remote_provider", "permissions", "finish"],
        )

    def test_exactly_two_steps_are_required_and_neither_asks_for_anything(self) -> None:
        required = [step for step in ONBOARDING_STEPS if step.required]
        self.assertEqual([step.step_id for step in required], ["welcome", "finish"])
        for step in required:
            self.assertEqual(step.survey, "", f"{step.step_id} asks for something and cannot be skipped")

    def test_a_machine_with_nothing_completes_the_wizard(self) -> None:
        """The §7 offline rule, run rather than asserted about."""
        model = OnboardingModel(surveyors={
            name: (lambda: None) for name in ("providers", "speech", "audio", "character")
        })
        for _ in range(len(ONBOARDING_STEPS) - 1):
            step = model.step
            model.advance(skipped=not step.required and bool(step.skip))
        self.assertEqual(model.step.step_id, "finish")
        model.advance()
        self.assertTrue(model.complete)

    def test_a_required_step_refuses_to_be_skipped(self) -> None:
        model = OnboardingModel()
        with self.assertRaises(ValueError):
            model.advance(skipped=True)

    def test_surveys_are_cached_until_refreshed(self) -> None:
        calls = []

        def counting() -> int:
            calls.append(1)
            return len(calls)

        model = OnboardingModel(surveyors={"providers": counting})
        model.go_to("providers")
        self.assertEqual(model.view().survey, 1)
        self.assertEqual(model.view().survey, 1)
        model.refresh("providers")
        self.assertEqual(model.view().survey, 2)

    def test_restore_ignores_a_step_it_does_not_know(self) -> None:
        model = OnboardingModel()
        model.restore(step_id="a-step-from-a-later-build", answers={"welcome": "answered"})
        self.assertEqual(model.step.step_id, "welcome")
        self.assertEqual(model.answers["welcome"], "answered")


class ProviderSurveyTests(unittest.TestCase):
    """§8. Five questions, and the ladder that stops one being a rung above another."""

    def finding(self, **overrides) -> LocalProviderFinding:
        base = dict(
            provider_id="local.test", adapter_id="ollama", kind="server",
            installed=False, installed_evidence="", running=False, running_evidence="",
        )
        base.update(overrides)
        return LocalProviderFinding(**base)

    def test_the_layer_is_a_ladder(self) -> None:
        """A rung cannot hold without the one below it. The first implementation
        reported ``models-present`` for a provider that was not running."""
        self.assertEqual(self.finding().layer, "absent")
        self.assertEqual(self.finding(installed=True).layer, "installed")
        self.assertEqual(self.finding(installed=True, running=True).layer, "running")
        self.assertEqual(
            self.finding(running=True, models=(ModelSummary("m"),)).layer, "models-present",
        )
        self.assertEqual(
            self.finding(installed=True, running=True, models=(ModelSummary("m"),), eligible=True).layer,
            "eligible",
        )

    def test_a_machine_with_no_model_is_told_so_plainly(self) -> None:
        """§32: the no-model configuration is supported, not an error."""
        survey = LocalProviderSurvey(findings=(self.finding(installed=True, running=True),))
        self.assertFalse(survey.any_eligible)
        self.assertFalse(survey.any_model_present)
        self.assertIn("no model is available", survey.summary)
        self.assertIn("Bunny still starts", survey.summary)

    def test_a_machine_with_nothing_installed_is_told_bunny_still_works(self) -> None:
        survey = LocalProviderSurvey(findings=(self.finding(),))
        self.assertIn("typed input works", survey.summary)

    def test_the_resource_figure_is_labelled_an_estimate(self) -> None:
        model = ModelSummary("m", size_bytes=2 * 1024 ** 3)
        self.assertTrue(model.resource_known)
        self.assertGreater(model.estimated_resident_bytes, model.size_bytes)
        self.assertIn("estimate", model.to_json()["estimateBasis"].lower())

    def test_an_unreported_size_is_not_a_small_model(self) -> None:
        model = ModelSummary("m", size_bytes=0)
        self.assertFalse(model.resource_known)
        self.assertEqual(model.estimated_resident_bytes, 0)


class SpeechSurveyTests(unittest.TestCase):
    """§9 and §33. Four layers, and typed input that survives all of them."""

    def test_the_reason_names_the_first_missing_layer(self) -> None:
        from companion.onboarding.speech import MicrophoneFinding

        device = MicrophoneFinding(device_id="d", backend_id="pulse", name="mic")
        cases = (
            (SpeechSurvey(), "microphone"),
            (SpeechSurvey(microphones=(device,)), "Vosk"),
            (SpeechSurvey(microphones=(device,), library_present=True), "model"),
        )
        for survey, expected in cases:
            with self.subTest(expected=expected):
                self.assertFalse(survey.available)
                self.assertIn(expected.lower(), survey.reason.lower())

    def test_typed_input_is_preserved_in_every_case(self) -> None:
        for survey in (SpeechSurvey(), SpeechSurvey(recognizer_ready=True)):
            self.assertTrue(survey.to_json()["typedInputPreserved"])
            self.assertIn("typ", survey.remedy.lower())

    def test_push_to_talk_follows_availability(self) -> None:
        from companion.onboarding.speech import MicrophoneFinding

        ready = SpeechSurvey(
            microphones=(MicrophoneFinding("d", "pulse", "mic"),),
            library_present=True, model_present=True, recognizer_ready=True,
        )
        self.assertTrue(ready.available)
        self.assertTrue(ready.push_to_talk_enabled)

    def test_an_output_monitor_is_not_reported_as_a_microphone(self) -> None:
        from companion.onboarding.speech import survey_speech
        from tests.companion.speech_support import ScriptedCaptureBackend

        backend = ScriptedCaptureBackend(
            "pulse", devices=(), monitors=("auto_null.monitor",)
        )
        survey = survey_speech(capture_backends=(backend,), recognizers=())

        self.assertFalse(survey.microphone_present)
        self.assertFalse(survey.push_to_talk_enabled)
        self.assertIn("not microphones", survey.capture_detail)

    def test_audio_survey_excludes_output_monitors_from_inputs(self) -> None:
        from companion.onboarding.audio import survey_audio
        from tests.companion.speech_support import ScriptedCaptureBackend

        backend = ScriptedCaptureBackend(
            "pulse", devices=(), monitors=("auto_null.monitor",)
        )
        survey = survey_audio(
            output_backends=(), input_backends=(backend,), voice_providers=()
        )

        self.assertFalse(survey.input_available)
        self.assertEqual(survey.inputs, ())
        self.assertIn("not microphones", survey.input_detail)


class IdentityTests(unittest.TestCase):
    """§39 and §40."""

    def test_two_channels_and_no_more(self) -> None:
        self.assertEqual(RELEASE_CHANNELS, ("development", "alpha"))

    def test_the_build_id_is_derived_and_not_counted(self) -> None:
        first = derive_build_id("a" * 40, 1700000000)
        second = derive_build_id("a" * 40, 1700000000)
        self.assertEqual(first, second)
        self.assertNotEqual(first, derive_build_id("b" * 40, 1700000000))

    def test_a_checkout_says_it_is_a_checkout(self) -> None:
        identity = build_identity(metadata_path=Path("/nonexistent/release.json"))
        self.assertFalse(identity.installed)
        self.assertEqual(identity.channel, "development")
        self.assertTrue(any("source checkout" in line for line in identity.lines()))

    def test_an_alpha_image_is_named_alpha_everywhere(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "release.json"
            path.write_text(json.dumps({
                "osVersion": ALPHA_VERSION, "releaseChannel": "alpha",
                "buildId": "abcdef123456.1700000000", "sourceCommit": "c" * 40,
                "imageVersion": "0.1.0-alpha", "profile": "beta",
                "architecture": "x86_64", "buildTimestamp": "2026-08-07T00:00:00Z",
            }), encoding="utf-8")
            identity = build_identity(metadata_path=path)
        self.assertTrue(identity.alpha)
        self.assertEqual(identity.display_name, "Bunny OS Alpha 0.1")
        self.assertIn("alpha", identity.image_filename)
        self.assertTrue(identity.installed)

    def test_an_unknown_channel_falls_back_to_development(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "release.json"
            path.write_text(json.dumps({
                "osVersion": "9.9.9", "releaseChannel": "canary", "sourceCommit": "d" * 40,
            }), encoding="utf-8")
            self.assertEqual(build_identity(metadata_path=path).channel, "development")


class HardwareRecordTests(unittest.TestCase):
    """§20. Facts and capability, measured separately and provably so."""

    def test_the_facts_never_raise(self) -> None:
        facts = hardware_facts()
        json.dumps(facts.to_json())

    def test_every_probe_names_what_it_was_not_inferred_from(self) -> None:
        facts = hardware_facts()
        probes = operational_probes(
            facts=facts,
            provider_survey=LocalProviderSurvey(),
            speech_survey=SpeechSurvey(),
            audio_survey=_StubAudio(),
            desktop_report=_StubDesktop(),
            three_d=(False, "stubbed"),
        )
        named = {probe.capability for probe in probes}
        for capability in ("local-model", "portal", "file-manager", "speech-model", "uri-handler"):
            self.assertIn(capability, named)
        for probe in probes:
            self.assertTrue(
                probe.inferred_from,
                f"{probe.capability} does not say which hardware fact it refuses to infer from",
            )

    def test_the_desktop_probe_is_given_its_adapters(self) -> None:
        """``probe_environment`` takes the adapter set it is to ask.

        Calling it with none raises ``missing 1 required positional argument``,
        the exception is caught, and all three desktop capabilities are reported
        unavailable with the TypeError as their reason — on a machine where the
        portal is running. The first booted image's capability record said "the
        desktop environment probe did not run" three times and read like a
        finding about the machine.
        """
        probes = operational_probes(
            provider_survey=LocalProviderSurvey(), speech_survey=SpeechSurvey(),
            audio_survey=_StubAudio(), three_d=(False, "stubbed"),
        )
        for probe in probes:
            if probe.capability in ("portal", "file-manager", "uri-handler"):
                self.assertNotIn("missing 1 required positional argument", probe.detail)
                self.assertNotIn("did not run", probe.detail)

    def test_the_record_states_the_rule(self) -> None:
        record = capability_record(
            provider_survey=LocalProviderSurvey(), speech_survey=SpeechSurvey(),
            audio_survey=_StubAudio(), desktop_report=_StubDesktop(), three_d=(False, "stubbed"),
        )
        self.assertIn("separately", record["rule"])
        json.dumps(record)


@dataclass
class _StubAudio:
    output_available: bool = False
    output_detail: str = "stubbed"
    summary: str = "stubbed"

    def to_json(self) -> dict:
        return {"outputAvailable": self.output_available}


class _StubDesktop:
    def permits(self, _action_id: str) -> bool:
        return False

    def reason(self, action_id: str) -> str:
        return f"{action_id} was stubbed"

    def to_json(self) -> dict:
        return {"posture": "headless-no-desktop-actions", "available": []}


class SettingsTests(TemporaryRootTests):
    """§29. A settings surface that persists and holds no credential."""

    def test_defaults_are_the_alpha_security_posture(self) -> None:
        settings = load_settings(self.root)
        self.assertFalse(settings.ai.remote_enabled)
        self.assertEqual(settings.privacy.desktop_action_approval, "always")
        self.assertEqual(settings.privacy.remote_transfer_ceiling, "public")
        self.assertEqual(settings.character.three_d, "auto")

    def test_a_setting_survives_a_write_and_a_read(self) -> None:
        update_settings(self.root, "voice", {"enabled": False, "volume": 0.25})
        reloaded = load_settings(self.root)
        self.assertFalse(reloaded.voice.enabled)
        self.assertAlmostEqual(reloaded.voice.volume, 0.25)

    def test_a_credential_shaped_key_is_refused(self) -> None:
        for field in ("apiKey", "token", "password", "credential"):
            with self.subTest(field=field), self.assertRaises(SettingsError):
                update_settings(self.root, "ai", {field: "x"})

    def test_approval_cannot_be_turned_off(self) -> None:
        with self.assertRaises(SettingsError):
            update_settings(self.root, "privacy", {"desktop_action_approval": "never"})

    def test_there_is_no_setting_that_raises_the_surface(self) -> None:
        """A preference may only ever simplify. There is no force-3D."""
        self.assertNotIn("on", ("auto", "off"))
        with self.assertRaises(SettingsError):
            update_settings(self.root, "character", {"three_d": "on"})

    def test_projections_take_the_simpler_of_two_requests(self) -> None:
        settings = update_settings(self.root, "character", {"animation": "none"})
        preferences = settings.accessibility_preferences()
        self.assertTrue(preferences.no_animation)
        self.assertTrue(preferences.reduced_motion)

    def test_a_broken_file_yields_defaults_rather_than_stopping_a_login(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "settings.json").write_text("{", encoding="utf-8")
        self.assertEqual(load_settings(self.root).to_json(), Settings().to_json())
        with self.assertRaises(Exception):
            load_settings(self.root, strict=True)

    def test_an_unknown_field_is_refused_with_the_known_ones_named(self) -> None:
        with self.assertRaises(SettingsError) as caught:
            update_settings(self.root, "character", {"colour": "pink"})
        self.assertIn("animation", str(caught.exception))


class DiagnosticsTests(TemporaryRootTests):
    """§18 and §38. A diagnostic that cannot fail, and a bundle with no secrets."""

    def test_the_report_never_raises_and_is_json(self) -> None:
        report = diagnose(root=self.root, include_failures=False)
        json.dumps(report.to_json())
        self.assertTrue(report.lines())

    def test_every_action_states_its_effect(self) -> None:
        for action in RECOVERY_ACTIONS:
            self.assertTrue(action.effect, action.action_id)
            self.assertTrue(action.label, action.action_id)

    def test_the_six_named_actions_exist(self) -> None:
        identifiers = {action.action_id for action in RECOVERY_ACTIONS}
        for required in ("restart", "reset-presentation", "disable-3d", "text-only", "export"):
            self.assertIn(required, identifiers)

    def test_export_is_never_an_upload(self) -> None:
        bundle = build_bundle(root=self.root, report=diagnose(root=self.root, include_failures=False))
        self.assertFalse(bundle["uploaded"])
        self.assertEqual(bundle["excluded"], list(EXCLUDED_FROM_BUNDLE))

    def test_the_bundle_carries_no_credential_shaped_key(self) -> None:
        from companion.settings import _refuse_secrets

        bundle = build_bundle(root=self.root, report=diagnose(root=self.root, include_failures=False))
        _refuse_secrets(bundle)

    def test_the_bundle_carries_no_clock_of_its_own(self) -> None:
        """The timestamp is the caller's, so two bundles agree about when.

        The *whole* bundle is deliberately not asserted identical: it re-reads
        the machine, and ``MemAvailable`` moves between two calls a millisecond
        apart. An earlier version of this test compared the two documents and
        failed on Linux for exactly that reason — which is the correct
        behaviour being caught by an incorrect assertion, so the assertion
        narrowed to the part that is a promise.
        """
        report = diagnose(root=self.root, include_failures=False)
        stamp = "2026-08-07T00:00:00Z"
        first = build_bundle(root=self.root, report=report, generated_at=stamp)
        second = build_bundle(root=self.root, report=report, generated_at=stamp)
        for key in ("generatedAt", "identity", "diagnostics", "contents", "excluded",
                    "uploaded", "componentVersions", "buildInputs", "schemaVersion"):
            self.assertEqual(
                json.dumps(first[key], sort_keys=True),
                json.dumps(second[key], sort_keys=True),
                f"{key} differs between two bundles built from one report",
            )


class RedactionTests(unittest.TestCase):
    """§37. One redaction list, used by the runtime and by the bundle."""

    def test_the_service_and_the_export_share_one_declaration(self) -> None:
        from companion import service
        from companion.privacy import DIAGNOSTIC_REDACTIONS

        self.assertIs(service._FAULT_REDACTIONS, DIAGNOSTIC_REDACTIONS)

    def test_what_must_never_be_logged_comes_out(self) -> None:
        from companion.privacy import redact_diagnostic_text

        redacted = redact_diagnostic_text(
            "/home/someone/notes api_key: sk-secret " + "a" * 40,
        )
        self.assertNotIn("someone", redacted)
        self.assertNotIn("sk-secret", redacted)
        self.assertNotIn("a" * 40, redacted)


class AlphaCommandTests(TemporaryRootTests):
    """The command forms. Every one of these has a graphical equivalent."""

    def command(self, *argv: str) -> dict:
        parser = argparse.ArgumentParser(prog="bunny-os")
        sub = parser.add_subparsers(dest="command", required=True)
        companion_cli.add_arguments(sub)
        arguments = parser.parse_args(
            ["companion", "--root", str(self.root), "--simulate", "laptop", *argv],
        )
        result = companion_cli.dispatch(arguments)
        json.dumps(result)
        return result

    def test_identity(self) -> None:
        self.assertIn("identity", self.command("identity"))

    def test_capability_record_separates_facts_from_probes(self) -> None:
        record = self.command("capability-record")
        self.assertIn("hardware", record)
        self.assertIn("operational", record)

    def test_diagnose_changes_nothing(self) -> None:
        result = self.command("diagnose")
        self.assertIn("nothing was changed", result["effect"])

    def test_safe_mode_round_trip(self) -> None:
        self.assertFalse(self.command("safe-mode", "status")["safeMode"]["enabled"])
        self.assertTrue(self.command("safe-mode", "on")["safeMode"]["enabled"])
        self.assertTrue(read_safe_mode(self.root).enabled)
        self.assertFalse(self.command("safe-mode", "off")["safeMode"]["enabled"])

    def test_settings_show_declares_it_holds_no_credential(self) -> None:
        self.assertFalse(self.command("settings", "show")["settings"]["containsCredentials"])

    def test_settings_set_persists(self) -> None:
        self.command("settings", "set", "voice", "enabled", "false")
        self.assertFalse(load_settings(self.root).voice.enabled)

    def test_character_policy_dry_run_changes_nothing(self) -> None:
        result = self.command("character-policy", "--dry-run", "--eligible", "full-3d")
        self.assertFalse(result["decision"]["applied"])
        self.assertEqual(read_policy_state(self.registry()).applied_digest, "")

    def test_character_policy_applies(self) -> None:
        result = self.command("character-policy", "--eligible", "full-3d")
        self.assertTrue(result["decision"]["applied"])
        self.assertEqual(self.registry().selected().package_id, "bunny-default-3d")

    def test_export_diagnostics_writes_a_file_and_says_it_uploaded_nothing(self) -> None:
        destination = self.root / "bundle.json"
        result = self.command("export-diagnostics", str(destination))
        self.assertFalse(result["uploaded"])
        self.assertTrue(destination.is_file())
        json.loads(destination.read_text(encoding="utf-8"))

    def test_onboarding_describes_every_page(self) -> None:
        result = self.command("onboarding")
        self.assertEqual(len(result["steps"]), len(ONBOARDING_STEPS))


class BuildIntegrationTests(unittest.TestCase):
    """§5 and §11. The unit, the launcher and the routes that carry them."""

    @staticmethod
    def destination(profile: str, path: str) -> str | None:
        """Where a repository path lands in a profile's image, or ``None``.

        Asked of the declaration in ``install_routes.py``, which is the only
        place the install set exists — the same function the installer selects
        with and the closure analyser classifies with.
        """
        from install_routes_shim import installed_destination, routes_for_profile  # type: ignore

        for route in routes_for_profile(profile):
            landed = installed_destination(route, path)
            if landed is not None:
                return landed
        return None

    def test_the_window_unit_exists_and_is_not_started_for_you(self) -> None:
        """The window ships and is startable; nothing starts it at login.

        This assertion is the reverse of the one it replaces, and the reversal
        is deliberate rather than a relaxation. The window was enabled when the
        desktop had no assistant surface of its own and an invisible companion
        was the problem. The desktop now renders the character, the bubble and
        the input, and starting the GTK window at login put a second, larger
        copy of the same assistant on top of the first — visible in the
        screenshots in DESKTOP_SHELL_ALPHA_VALIDATION.md.

        Three things are asserted, because "not enabled" alone would also be
        true of a unit somebody deleted.
        """
        unit = REPOSITORY / "systemd/user/bunny-companion-window.service"
        self.assertTrue(unit.is_file(), "the window unit must still ship")

        preset = (REPOSITORY / "config/systemd/60-bunny-os-user.preset").read_text(encoding="utf-8")
        self.assertNotIn("\nenable bunny-companion-window.service", f"\n{preset}")
        self.assertIn("disable bunny-companion-window.service", preset)

        # And the runtime, which must still be enabled — the whole point is that
        # the backend runs and the window does not.
        self.assertIn("\nenable bunny-companion.service", f"\n{preset}")

    def test_the_window_is_still_reachable_by_a_person(self) -> None:
        """Not started is not the same as not available.

        A user who wants the task list must have a way to get it, or this
        change removed a feature instead of moving it.
        """
        entry = REPOSITORY / "shell/components/applications/art.comrade.BunnyCompanion.desktop"
        self.assertTrue(entry.is_file(), "the Applications entry must still exist")
        self.assertIn("Exec=/usr/bin/bunny-companion", entry.read_text(encoding="utf-8"))

    def test_every_enabled_user_preset_unit_is_actually_enabled_by_the_build(self) -> None:
        """A preset file is not an enablement, and the two had drifted.

        ``/usr/lib/systemd/user-preset/60-bunny-os.preset`` has named
        ``bunny-companion.service`` since the integration branch, with a comment
        saying it is enabled rather than left to the desktop entry. It was not:
        nothing runs ``systemctl --global preset-all`` and the user manager does
        not apply presets by itself, so no image ever built had the symlink.
        Measured on the first booted Alpha image — ``systemctl --user is-enabled``
        answered ``disabled`` for both companion units in a live graphical
        session, and the runtime was ``inactive``.

        This asserts the two lists against each other, which is the check that
        would have caught it: every unit the preset says to enable must appear
        in ``install_activation``'s ``--global enable`` call.
        """
        preset = (REPOSITORY / "config/systemd/60-bunny-os-user.preset").read_text(encoding="utf-8")
        enabled = {
            line.split()[1] for line in preset.splitlines()
            if line.startswith("enable ") and len(line.split()) == 2
        }
        installer = (REPOSITORY / "build/scripts/install-root.py").read_text(encoding="utf-8")
        start = installer.index('"/usr/bin/systemctl", "--global", "enable"')
        finish = installer.index("], check=True)", start)
        activated = {
            token.strip().strip('",')
            for token in installer[start:finish].split()
            if token.strip().strip('",').endswith((".service", ".target", ".socket"))
        }
        missing = sorted(enabled - activated)
        self.assertEqual(
            missing, [],
            "these units are enabled in the user preset and never enabled by the build; "
            "systemd applies no preset by itself, so they would never start",
        )
        # And the other direction, which the first version did not check: a unit
        # the build enables and the preset does not mention is a unit whose
        # intended state is recorded in exactly one place. That is how the window
        # would have been un-enabled in the preset and gone on starting anyway.
        user_units = {path.name for path in (REPOSITORY / "systemd/user").glob("*.service")}
        undeclared = sorted((activated & user_units) - enabled)
        self.assertEqual(
            undeclared, [],
            "these user units are enabled by the build and not named in the preset; "
            "the two lists are the same decision and must be changed together",
        )

    def test_the_window_unit_does_not_deny_write_execute(self) -> None:
        """Mesa's shader compiler and llvmpipe's JIT map executable pages. A GTK
        client with MemoryDenyWriteExecute is killed the moment it draws in 3D."""
        unit = (REPOSITORY / "systemd/user/bunny-companion-window.service").read_text(encoding="utf-8")
        self.assertNotIn("MemoryDenyWriteExecute=yes", unit)
        self.assertIn("RestrictAddressFamilies=AF_UNIX AF_NETLINK", unit)

    def test_the_neural_voice_worker_is_offline_without_a_write_execute_denial(self) -> None:
        """CPU inference JITs kernels, but it still has no network family."""
        unit = (REPOSITORY / "systemd/user/bunny-companion.service").read_text(encoding="utf-8")
        self.assertNotIn("MemoryDenyWriteExecute=yes", unit)
        self.assertIn("RestrictAddressFamilies=AF_UNIX", unit)
        self.assertIn("MemoryMax=2G", unit)

    def test_the_launcher_and_the_diagnostics_program_are_installed(self) -> None:
        from install_routes_shim import SYSTEM_SCRIPTS  # type: ignore

        self.assertIn("bunny-companion-window", SYSTEM_SCRIPTS)
        self.assertIn("bunny-companion-recovery", SYSTEM_SCRIPTS)
        for name in ("bunny-companion-window", "bunny-companion-recovery"):
            self.assertTrue((REPOSITORY / f"scripts/{name}.py").is_file())
            self.assertEqual(
                self.destination("developer", f"scripts/{name}.py"),
                f"/usr/libexec/{name}",
            )

    def test_the_desktop_entries_reach_the_applications_directory(self) -> None:
        for name in ("BunnyCompanion", "BunnyDiagnostics"):
            source = f"desktop-integration/art.comrade.{name}.desktop"
            self.assertTrue((REPOSITORY / source).is_file())
            self.assertEqual(
                self.destination("beta", source),
                f"/usr/share/applications/art.comrade.{name}.desktop",
            )
            # Desktop profiles only: an applications list is a thing a desktop
            # has, and a minimal image should not advertise a window it cannot open.
            self.assertIsNone(self.destination("minimal", source))

    def test_the_desktop_set_declares_a_player_for_every_audio_backend(self) -> None:
        """A sound server with no player is a companion that cannot be heard.

        The beta image built from 339b629 had pipewire, wireplumber,
        pulseaudio-libs and alsa-lib installed and not one of ``paplay``,
        ``pw-play``, ``aplay``, ``parecord`` or ``spd-say``. The libraries
        arrived transitively; the programs are in packages nothing pulled in.
        Because the companion drives players *by name*, every backend reported
        itself unavailable on a machine with working speakers.

        This asserts the packages, not the binaries, because the assertion has
        to hold on a build machine that is not the image.
        """
        declared = {
            line.strip()
            for line in (REPOSITORY / "build/packages/desktop.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }
        for backend, package in (
            ("paplay/pactl/parecord (pulse)", "pulseaudio-utils"),
            ("the PulseAudio-compatible server", "pipewire-pulseaudio"),
            ("pw-play/pw-cat (pipewire)", "pipewire-utils"),
            ("aplay/arecord (alsa)", "alsa-utils"),
            ("spd-say (speech-dispatcher voice provider)", "speech-dispatcher-utils"),
        ):
            self.assertIn(package, declared, f"{backend} has no package in the desktop set")

    def test_the_voice_stack_is_declared_and_not_inherited(self) -> None:
        """espeak-ng was required by nothing and speech-dispatcher only by Orca.

        Removing the screen reader would have silently removed Bunny's voice.
        §41: an input that arrives as a side effect of an unrelated package is
        an unrecorded build input.
        """
        declared = {
            line.strip()
            for line in (REPOSITORY / "build/packages/desktop.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }
        for package in (
            "espeak-ng", "speech-dispatcher", "speech-dispatcher-espeak-ng",
            "vosk-api-devel", "python3-onnxruntime", "python3-numpy",
            "python3-scipy", "python3-sentencepiece", "python3-safetensors",
            "python3-beartype", "python3-pydantic", "python3-einops",
            "python3-huggingface-hub", "python3-requests", "python3-pyyaml",
            "python3-typing-extensions", "python3-filelock", "python3-fsspec",
            "python3-jinja2", "python3-networkx", "python3-setuptools",
            "python3-sympy",
        ):
            self.assertIn(package, declared)
        self.assertNotIn(
            "python3-torch", declared,
            "Fedora's torch package hard-requires the ROCm GPU closure; Bunny pins the CPU wheel",
        )

    def test_the_offline_stt_model_is_integrity_checked_and_installed(self) -> None:
        from companion.speech.recognizers import _discover_model

        model_root = REPOSITORY / "assets/voice/models"
        model, language, locale, detail = _discover_model((str(model_root),))
        self.assertIsNotNone(model, detail)
        self.assertEqual(model.name, "vosk-model-small-en-us-0.15")
        self.assertEqual((language, locale), ("en", "en-US"))
        for source, destination in (
            (
                "assets/voice/models/vosk-model-small-en-us-0.15/am/final.mdl",
                "/usr/share/bunny-os/speech-models/vosk-model-small-en-us-0.15/am/final.mdl",
            ),
            (
                "assets/voice/models/vosk-model-small-en-us-0.15/.bunny-model.json",
                "/usr/share/bunny-os/speech-models/vosk-model-small-en-us-0.15/.bunny-model.json",
            ),
            (
                "assets/voice/licenses/Apache-2.0.txt",
                "/usr/share/licenses/bunny-os-voice/Apache-2.0.txt",
            ),
            (
                "assets/voice/PROVENANCE.json",
                "/usr/share/doc/bunny-os/voice-provenance.json",
            ),
        ):
            self.assertEqual(self.destination("beta", source), destination)
            self.assertIsNone(self.destination("minimal", source))

    def test_the_neural_tts_models_runtime_and_worker_reach_the_image(self) -> None:
        for source, destination in (
            (
                "assets/voice/tts/pocket/english/manifest.json",
                "/usr/share/bunny-os/voice/pocket/english/manifest.json",
            ),
            (
                "assets/voice/tts/kitten/nano-int8/manifest.json",
                "/usr/share/bunny-os/voice/kitten/nano-int8/manifest.json",
            ),
            (
                "assets/voice/runtime/site-packages/pocket_tts/__init__.py",
                "/usr/lib/bunny-os/voice-runtime/site-packages/pocket_tts/__init__.py",
            ),
            (
                "assets/voice/runtime/wheels/MANIFEST.json",
                "/usr/lib/bunny-os/voice-runtime/wheels/MANIFEST.json",
            ),
            (
                "shell/services/bin/bunny-voice-neural-worker",
                "/usr/bin/bunny-voice-neural-worker",
            ),
        ):
            self.assertEqual(self.destination("beta", source), destination)
            self.assertIsNone(self.destination("minimal", source))

    def test_the_speech_dispatcher_log_is_bounded_by_a_drop_in(self) -> None:
        """1.6 GiB of voice-list transcript in a RAM-backed tmpfs, measured."""
        drop_in = REPOSITORY / "config/speech-dispatcher/bunny-os.conf"
        self.assertTrue(drop_in.is_file())
        self.assertIn("LogLevel  1", drop_in.read_text(encoding="utf-8"))
        self.assertEqual(
            self.destination("beta", "config/speech-dispatcher/bunny-os.conf"),
            # The shipped speechd.conf ends with Include "clients/*.conf", so a
            # drop-in here is read without rewriting a file the RPM owns.
            "/etc/speech-dispatcher/clients/bunny-os.conf",
        )

    def test_the_alpha_scope_document_ships(self) -> None:
        self.assertEqual(
            self.destination("beta", "docs/PUBLIC_ALPHA_SCOPE.md"),
            "/usr/share/doc/bunny-os/PUBLIC_ALPHA_SCOPE.md",
        )

    def test_no_shell_script_has_crlf_line_endings(self) -> None:
        """``.gitattributes`` says ``*.sh -text``, so git will never fix this.

        ``-text`` means no normalisation in either direction: whatever bytes are
        in the working copy go into the index verbatim and come back out the
        same on every platform. A script authored on Windows therefore reaches
        Linux with CRLF, and bash reports it as

            set: pipefail: invalid option name
            $'\\r': command not found

        which reads like a syntax error in the script rather than a line-ending
        problem. Two harness scripts on this branch were written that way and
        the first VM run failed on them.

        Checked over every ``.sh`` in the repository rather than only the new
        ones, because the property is about the repository.
        """
        offenders: list[str] = []
        for path in sorted(REPOSITORY.rglob("*.sh")):
            relative = path.relative_to(REPOSITORY).as_posix()
            if any(part in ("node_modules", ".git", "build/out") for part in relative.split("/")):
                continue
            if relative.startswith(("node_modules/", "build/out/", "qualification/")):
                continue
            try:
                if b"\r\n" in path.read_bytes():
                    offenders.append(relative)
            except OSError:
                continue
        self.assertEqual(offenders, [], "shell scripts with CRLF line endings will not run on Linux")

    def test_the_installer_models_everything_it_installs(self) -> None:
        """The closure analyser must not have to fail closed on this branch."""
        from install_routes_shim import audit_installer  # type: ignore

        complaints = audit_installer(REPOSITORY / "build/scripts/install-root.py")
        self.assertEqual(complaints, [])


def load_tests(loader, tests, pattern):  # noqa: ARG001 - unittest protocol
    """Put ``build/scripts`` on the path for the route assertions.

    A shim module rather than a bare ``sys.path`` insert, so the build scripts'
    directory is reachable for one import and is not left in front of everything
    else for the rest of the run — ``install_routes`` is a top-level name and
    the build directory holds several others.
    """
    import importlib.util
    import sys

    if "install_routes_shim" not in sys.modules:
        specification = importlib.util.spec_from_file_location(
            "install_routes_shim", REPOSITORY / "build/scripts/install_routes.py",
        )
        module = importlib.util.module_from_spec(specification)
        sys.modules["install_routes_shim"] = module
        specification.loader.exec_module(module)
    return tests


if __name__ == "__main__":
    unittest.main()
