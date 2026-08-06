# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The agent-provider schemas: descriptors, requests and configuration refuse at construction.

Every test here is a §3, §5, §6 or §21 sentence asserted against the *type*,
which is where this codebase puts its rules: an invalid descriptor, request or
configuration is not representable, so no discipline downstream has to
remember one. The mirror-tuple tests are the exception that proves the rule —
the agents package may not import the canonical modules, so the docstrings
promise agreement and these tests are where the promise is collected.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

from companion import executor as canonical_executor
from companion import reviewer as canonical_reviewer
from companion import session as canonical_session
from companion import task as canonical_task
from companion.agents import structured as agents_structured
from companion.agents.config import (
    CONFIGURATION_FILE_NAME,
    AgentConfiguration,
    ProviderConfiguration,
    load_agent_configuration,
)
from companion.agents.credentials import CredentialReference
from companion.agents.descriptor import (
    COST_CLASSES,
    SUPPORTED_TASK_CLASSES,
    EndpointIdentity,
    ProviderDescriptor,
    ProviderStanding,
)
from companion.agents.errors import AgentSchemaError, ProviderConfigurationError
from companion.agents.request import (
    LOCALITY_REQUIREMENTS,
    MAX_MESSAGE_BYTES,
    MAX_MESSAGES,
    MAX_TOOL_NAMES,
    GenerationMessage,
    GenerationRequest,
    SamplingSettings,
    messages_digest,
)
from companion.agents.wire import HttpTarget
from companion.privacy import scrub_text

from .agents_support import make_request, remote_configuration, scripted_configuration

#: A value companion.privacy._CREDENTIAL_VALUE recognises as credential-shaped;
#: the scrubbing tests assert that recognition before relying on it.
CREDENTIAL_SHAPED = "Bearer abc123def456ghi789"


def _descriptor(**overrides: Any) -> ProviderDescriptor:
    """A fully-declared local descriptor; each refusal test breaks one field."""
    values: dict[str, Any] = dict(
        provider_id="local.ollama",
        adapter_id="ollama",
        model_id="qwen2.5-3b",
        model_revision="sha256-abc",
        endpoint=EndpointIdentity(kind="loopback-http", locator="127.0.0.1:11434"),
        supported_task_classes=("question", "summarise"),
        context_limit_tokens=8192,
        maximum_output_tokens=1024,
        supports_streaming=True,
        standing=ProviderStanding(
            configured=True, authenticated=True, available=True, healthy=True,
        ),
    )
    values.update(overrides)
    return ProviderDescriptor(**values)


def _full_request(**overrides: Any) -> GenerationRequest:
    """Direct construction, for the fields agents_support.make_request fixes."""
    values: dict[str, Any] = dict(
        request_id="gen-000001",
        session_id="ses-000001",
        task_id="task-000001",
        lifecycle_epoch=0,
        plan_id="plan-test",
        provider_id="local.scripted",
        model_id="scripted-model",
        purpose="result",
        messages=(GenerationMessage(role="user", content="count the words"),),
        system_policy_reference="bunny-agent-policy/1",
        maximum_input_tokens=4096,
        maximum_output_tokens=256,
    )
    values.update(overrides)
    return GenerationRequest(**values)


class ProviderDescriptorSchema(unittest.TestCase):
    """§3: one bounded record of one provider, with nowhere to put a key."""

    def test_a_fully_declared_local_descriptor_constructs(self) -> None:
        descriptor = _descriptor()
        self.assertTrue(descriptor.fully_declared)
        self.assertTrue(descriptor.handles("question"))
        self.assertFalse(descriptor.handles("compute"))
        self.assertEqual(descriptor.standing.rung, "healthy")

    def test_an_unknown_provider_type_is_refused(self) -> None:
        with self.assertRaises(AgentSchemaError):
            _descriptor(provider_type="embedding")

    def test_an_unknown_cost_class_is_refused(self) -> None:
        with self.assertRaises(AgentSchemaError):
            _descriptor(cost_class="donated")

    def test_a_remote_provider_above_internal_is_refused(self) -> None:
        """The ceiling is a promise about where data may travel."""
        for too_high in ("personal", "sensitive", "secret"):
            with self.subTest(privacy_class=too_high):
                with self.assertRaises(AgentSchemaError):
                    _descriptor(local=False, maximum_privacy_class=too_high)
        # At the ceiling it constructs: internal is the remote maximum.
        remote = _descriptor(local=False, maximum_privacy_class="internal")
        self.assertFalse(remote.local)

    def test_the_image_input_flag_may_not_disagree_with_the_modalities(self) -> None:
        with self.assertRaises(AgentSchemaError):
            _descriptor(supports_image_input=True, input_modalities=("text",))
        with self.assertRaises(AgentSchemaError):
            _descriptor(supports_image_input=False, input_modalities=("text", "image"))

    def test_an_unknown_task_class_is_refused(self) -> None:
        with self.assertRaises(AgentSchemaError):
            _descriptor(supported_task_classes=("question", "divination"))

    def test_a_negative_context_limit_is_refused(self) -> None:
        with self.assertRaises(AgentSchemaError):
            _descriptor(context_limit_tokens=-1)

    def test_a_different_schema_version_is_refused(self) -> None:
        with self.assertRaises(AgentSchemaError):
            _descriptor(schema_version=2)

    def test_fully_declared_requires_model_classes_limits_and_endpoint(self) -> None:
        """Selection may only consider a provider that stated everything."""
        for absent in (
            {"model_id": ""},
            {"supported_task_classes": ()},
            {"context_limit_tokens": 0},
            {"maximum_output_tokens": 0},
            {"endpoint": None},
        ):
            with self.subTest(absent=next(iter(absent))):
                self.assertFalse(_descriptor(**absent).fully_declared)

    def test_the_wire_form_uses_camel_case_and_names_remote_transmission(self) -> None:
        document = _descriptor().to_json()
        for key in ("schemaVersion", "providerId", "adapterId", "modelId",
                    "supportedTaskClasses", "contextLimitTokens", "costClass",
                    "maximumPrivacyClass", "fullyDeclared"):
            self.assertIn(key, document)
        self.assertNotIn("provider_id", document)
        # remoteTransmission is the honest name for "not local": the wire form
        # states what the flag means, not just what it is.
        self.assertFalse(document["remoteTransmission"])
        remote = _descriptor(local=False, maximum_privacy_class="internal").to_json()
        self.assertTrue(remote["remoteTransmission"])


class ProviderStandingLadder(unittest.TestCase):
    """§3's ladder: each rung is earned separately and rests on the one below."""

    def test_authenticated_without_configured_is_refused(self) -> None:
        with self.assertRaises(AgentSchemaError):
            ProviderStanding(authenticated=True)

    def test_available_without_authenticated_is_refused(self) -> None:
        with self.assertRaises(AgentSchemaError):
            ProviderStanding(configured=True, available=True)

    def test_healthy_without_available_is_refused(self) -> None:
        with self.assertRaises(AgentSchemaError):
            ProviderStanding(configured=True, authenticated=True, healthy=True)

    def test_the_rung_property_walks_the_ladder_from_the_top(self) -> None:
        self.assertEqual(ProviderStanding().rung, "unconfigured")
        self.assertEqual(ProviderStanding(configured=True).rung, "configured")
        self.assertEqual(
            ProviderStanding(configured=True, authenticated=True).rung, "authenticated")
        self.assertEqual(
            ProviderStanding(configured=True, authenticated=True, available=True).rung,
            "available")
        self.assertEqual(
            ProviderStanding(configured=True, authenticated=True,
                             available=True, healthy=True).rung,
            "healthy")


class EndpointIdentityRefusals(unittest.TestCase):
    """The locator refuses the places URLs hide credentials."""

    def test_a_locator_carrying_userinfo_is_refused(self) -> None:
        with self.assertRaises(AgentSchemaError):
            EndpointIdentity(kind="loopback-http", locator="user@127.0.0.1:8080")

    def test_a_locator_carrying_a_query_is_refused(self) -> None:
        with self.assertRaises(AgentSchemaError):
            EndpointIdentity(kind="remote-https", locator="api.example.test:443/v1?key=x")

    def test_a_locator_carrying_a_scheme_is_refused(self) -> None:
        """The scheme is the kind; a second statement of it could disagree."""
        with self.assertRaises(AgentSchemaError):
            EndpointIdentity(kind="loopback-http", locator="http://127.0.0.1:8080")

    def test_an_empty_locator_is_refused(self) -> None:
        with self.assertRaises(AgentSchemaError):
            EndpointIdentity(kind="subprocess", locator="")


class MirrorTupleAgreement(unittest.TestCase):
    """The agents package restates canonical tuples it may not import.

    Each docstring in the package promises a test asserts the agreement;
    these are those tests. A drift here is a real defect: two modules
    holding different answers to the same closed question.
    """

    def test_cost_classes_agree_with_the_canonical_executor_module(self) -> None:
        self.assertEqual(COST_CLASSES, canonical_executor.COST_CLASSES)

    def test_supported_task_classes_are_the_task_types_minus_unclassified(self) -> None:
        """No provider declares support for "we do not know yet"."""
        self.assertEqual(
            SUPPORTED_TASK_CLASSES,
            tuple(item for item in canonical_task.TASK_TYPES if item != "unclassified"),
        )

    def test_locality_requirements_agree_with_the_session_preferences(self) -> None:
        self.assertEqual(LOCALITY_REQUIREMENTS, canonical_session.LOCALITY_PREFERENCES)

    def test_observation_enums_agree_with_the_canonical_reviewer_module(self) -> None:
        # The private names are imported deliberately: the agreement between
        # the schema's enums and the reviewer's is exactly what is under test.
        self.assertEqual(
            agents_structured._OBSERVATION_SEVERITIES, canonical_reviewer.SEVERITIES)
        self.assertEqual(
            agents_structured._OBSERVATION_CATEGORIES, canonical_reviewer.CATEGORIES)


class GenerationRequestSchema(unittest.TestCase):
    """§6: what cannot be represented cannot be dispatched."""

    def test_a_valid_request_constructs_and_serializes_camel_case(self) -> None:
        request = make_request()
        self.assertEqual(request.purpose, "result")
        self.assertFalse(request.remote_permitted)
        document = request.to_json()
        self.assertEqual(document["requestId"], request.request_id)
        self.assertEqual(document["messageCount"], len(request.messages))

    def test_a_probe_needs_no_session_or_task(self) -> None:
        probe = make_request(purpose="probe")
        self.assertEqual(probe.session_id, "")
        self.assertEqual(probe.task_id, "")

    def test_an_unknown_purpose_is_refused(self) -> None:
        with self.assertRaises(AgentSchemaError):
            make_request(purpose="rumination")

    def test_a_non_probe_request_must_name_its_session_and_task(self) -> None:
        with self.assertRaises(AgentSchemaError):
            make_request(session_id="")
        with self.assertRaises(AgentSchemaError):
            make_request(task_id="")

    def test_a_request_with_no_messages_is_refused(self) -> None:
        with self.assertRaises(AgentSchemaError):
            _full_request(messages=())

    def test_more_messages_than_the_ceiling_is_refused(self) -> None:
        too_many = tuple(
            GenerationMessage(role="user", content="x") for _ in range(MAX_MESSAGES + 1)
        )
        with self.assertRaises(AgentSchemaError):
            _full_request(messages=too_many)

    def test_a_message_that_is_not_a_generation_message_is_refused(self) -> None:
        """A bare tuple is not a sanitized message, however message-shaped."""
        with self.assertRaises(AgentSchemaError):
            _full_request(messages=(("user", "count the words"),))

    def test_a_request_without_a_system_policy_reference_is_refused(self) -> None:
        with self.assertRaises(AgentSchemaError) as caught:
            _full_request(system_policy_reference="")
        self.assertIn("policy", str(caught.exception))

    def test_zero_or_negative_token_budgets_are_refused(self) -> None:
        for field, value in (
            ("maximum_input_tokens", 0),
            ("maximum_input_tokens", -1),
            ("maximum_output_tokens", 0),
            ("maximum_output_tokens", -256),
        ):
            with self.subTest(field=field, value=value):
                with self.assertRaises(AgentSchemaError):
                    _full_request(**{field: value})

    def test_an_unknown_locality_is_refused(self) -> None:
        with self.assertRaises(AgentSchemaError):
            _full_request(locality_requirement="wherever")

    def test_an_unknown_classification_is_refused(self) -> None:
        with self.assertRaises(AgentSchemaError):
            make_request(classification="mystery")

    def test_oversized_message_content_is_refused_not_truncated(self) -> None:
        with self.assertRaises(AgentSchemaError):
            GenerationMessage(role="user", content="x" * (MAX_MESSAGE_BYTES + 1))

    def test_more_permitted_tools_than_the_ceiling_is_refused(self) -> None:
        names = tuple(f"tool-{index}" for index in range(MAX_TOOL_NAMES + 1))
        with self.assertRaises(AgentSchemaError):
            _full_request(permitted_tool_names=names)

    def test_a_context_digest_that_does_not_match_the_messages_is_refused(self) -> None:
        """A request altered after the context was built is not representable."""
        messages = (GenerationMessage(role="user", content="count the words"),)
        altered = messages_digest(
            (GenerationMessage(role="user", content="something else"),))
        with self.assertRaises(AgentSchemaError):
            _full_request(messages=messages, context_digest=altered)
        # The matching digest is the positive control.
        request = _full_request(messages=messages, context_digest=messages_digest(messages))
        self.assertEqual(request.context_digest, messages_digest(messages))


class GenerationMessageScrubbing(unittest.TestCase):
    """§5 at the message boundary: the credential is gone and the record says so."""

    def test_credential_shaped_content_is_scrubbed_and_the_removal_recorded(self) -> None:
        # First establish that the privacy layer recognises the example; the
        # message test means nothing about a shape scrub_text would keep.
        content = f"my key is {CREDENTIAL_SHAPED}"
        self.assertNotEqual(scrub_text(content), content)
        message = GenerationMessage(role="user", content=content)
        self.assertTrue(message.scrubbed)
        self.assertNotIn("abc123def456ghi789", message.content)

    def test_ordinary_content_is_kept_verbatim_and_unmarked(self) -> None:
        message = GenerationMessage(role="user", content="count the words")
        self.assertFalse(message.scrubbed)
        self.assertEqual(message.content, "count the words")


class SamplingSettingsBounds(unittest.TestCase):
    """A closed set of numeric knobs, each bounded; nowhere to hide a parameter."""

    def test_the_defaults_are_deterministic(self) -> None:
        settings = SamplingSettings()
        self.assertEqual(settings.temperature, 0.0)
        self.assertEqual(settings.top_p, 1.0)
        self.assertEqual(settings.seed, 0)

    def test_each_knob_is_refused_outside_its_bounds(self) -> None:
        for field, value in (
            ("temperature", -0.1),
            ("temperature", 2.1),
            ("top_p", 0.0),
            ("top_p", 1.1),
            ("seed", -1),
        ):
            with self.subTest(field=field, value=value):
                with self.assertRaises(AgentSchemaError):
                    SamplingSettings(**{field: value})


class ProviderConfigurationLocality(unittest.TestCase):
    """§21: the endpoint kind, the remote flag and the wire target tell one story."""

    def test_a_remote_provider_without_a_credential_is_refused(self) -> None:
        with self.assertRaises(ProviderConfigurationError) as caught:
            replace(remote_configuration(), credential=CredentialReference())
        self.assertIn("credential", str(caught.exception))

    def test_a_remote_provider_with_a_loopback_endpoint_is_refused(self) -> None:
        with self.assertRaises(ProviderConfigurationError):
            replace(
                remote_configuration(),
                endpoint=EndpointIdentity(kind="loopback-http", locator="127.0.0.1:8080"),
            )

    def test_a_remote_provider_holding_personal_data_is_refused(self) -> None:
        with self.assertRaises(ProviderConfigurationError):
            replace(remote_configuration(), maximum_privacy_class="personal")

    def test_a_remote_provider_claiming_to_be_free_is_refused(self) -> None:
        """Metered is the honest floor for somebody else's computer."""
        with self.assertRaises(ProviderConfigurationError):
            replace(remote_configuration(), cost_class="free")

    def test_a_local_provider_with_a_remote_endpoint_kind_is_refused(self) -> None:
        with self.assertRaises(ProviderConfigurationError):
            replace(
                scripted_configuration(),
                endpoint=EndpointIdentity(kind="remote-https", locator="api.example.test:443"),
            )

    def test_a_local_provider_targeting_a_non_loopback_host_is_refused(self) -> None:
        """The §20 SSRF case at the configuration layer: "local" must mean loopback."""
        with self.assertRaises(ProviderConfigurationError):
            ProviderConfiguration(
                provider_id="local.pretender",
                adapter_id="ollama",
                endpoint=EndpointIdentity(kind="loopback-http", locator="127.0.0.1:11434"),
                http=HttpTarget(scheme="https", host="api.example.test", port=443),
            )

    def test_credential_shaped_content_in_a_string_field_is_refused(self) -> None:
        """A key pasted where a reference belongs is a key on disk in the wrong mode."""
        self.assertNotEqual(scrub_text(CREDENTIAL_SHAPED), CREDENTIAL_SHAPED)
        with self.assertRaises(ProviderConfigurationError) as caught:
            replace(scripted_configuration(), model_revision=CREDENTIAL_SHAPED)
        self.assertIn("credential", str(caught.exception))


class AgentConfigurationCoherence(unittest.TestCase):
    def test_duplicate_provider_ids_are_refused(self) -> None:
        with self.assertRaises(ProviderConfigurationError):
            AgentConfiguration(
                providers=(scripted_configuration(), scripted_configuration()))

    def test_an_unknown_executor_preference_is_refused(self) -> None:
        with self.assertRaises(ProviderConfigurationError):
            AgentConfiguration(executor_preference="fastest")

    def test_a_reviewer_provider_that_is_not_configured_is_refused(self) -> None:
        with self.assertRaises(ProviderConfigurationError):
            AgentConfiguration(
                providers=(scripted_configuration(),),
                reviewer_provider_id="local.ghost",
            )


class ConfigurationLoading(unittest.TestCase):
    """§21: a file the user edits; a broken file is an error, never a fallback."""

    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)

    def _write(self, document: Any) -> None:
        path = self.root / "agents" / CONFIGURATION_FILE_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document), encoding="utf-8")

    def test_an_absent_file_yields_the_local_only_defaults(self) -> None:
        configuration = load_agent_configuration(self.root)
        self.assertEqual(
            tuple(item.provider_id for item in configuration.providers),
            ("local.ollama", "local.llamacpp", "local.llamacli"),
        )
        self.assertTrue(all(item.local for item in configuration.providers))
        self.assertFalse(any(item.remote for item in configuration.providers))

    def test_an_unknown_provider_field_fails_closed(self) -> None:
        """A field the loader would ignore is a setting the user thinks they made."""
        self._write({"providers": [{
            "providerId": "local.custom",
            "adapterId": "ollama",
            "endpoint": {"kind": "loopback-http", "host": "127.0.0.1", "port": 11434},
            "modelPath": "/tmp/evil",
        }]})
        with self.assertRaises(ProviderConfigurationError) as caught:
            load_agent_configuration(self.root)
        self.assertIn("modelPath", str(caught.exception))

    def test_a_remote_entry_missing_its_credential_reference_fails(self) -> None:
        self._write({"providers": [{
            "providerId": "remote.paid",
            "adapterId": "openai-compatible",
            "remote": True,
            "endpoint": {"kind": "remote-https", "host": "api.example.test", "port": 443},
        }]})
        with self.assertRaises(ProviderConfigurationError) as caught:
            load_agent_configuration(self.root)
        self.assertIn("credential", str(caught.exception))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
