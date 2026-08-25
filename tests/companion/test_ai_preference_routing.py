# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings -> AI preferences reach provider selection; deterministic OS
intents stay deterministic.

The defect these tests pin: ``Settings.ai.preferred_provider_id`` and
``preferred_model_id`` were persisted by the supported CLI but consumed by
nothing, so an ordinary question was answered by
:class:`companion.executor.DeterministicLocalExecutor` with
:func:`companion.intents.capability_sentence` -- "I do not have a language
model configured" -- even when a healthy, preferred local provider was
configured and saw the real model. The fix folds Settings.ai into the agent
configuration as *preference* (never authority) and, when a provider is
selected, restricts the deterministic executor to the OS intents and pure
computation it can do without a model.

Preference is not authority: the merge only sets a registry ordering flag and a
model file name; capability, privacy, cost, health and availability stay
gated downstream. A machine whose named provider proves unavailable refuses an
inference task bounded instead of answering it with a canned sentence, and a
machine with no preference keeps today's behaviour bit for bit.
"""

from __future__ import annotations

import json
import os
import unittest
from dataclasses import dataclass, field
from typing import Any

from capability.runtime import assess_current_machine

from companion.agent_bridge import ProviderBackedExecutor
from companion.agents.config import AgentConfiguration
from companion.agents.service import AgentProviderService, AgentServiceOptions
from companion.executor import DeterministicLocalExecutor
from companion.local_files import LOCAL_FILE_TOOLS
from companion.local_system import LOCAL_SYSTEM_TOOLS
from companion.service import _merge_ai_preferences
from companion.settings import AiSettings
from companion.tools import ToolBroker

from .agents_support import ScriptedAdapter, scripted_configuration
from .support import CompanionTestCase

PLAN_WITHOUT_TOOLS = json.dumps({"summary": "Answer directly", "operations": []})
PLAN_WITH_TOOL = json.dumps({
    "summary": "Count the words with the counting tool",
    "operations": [{
        "name": "count-words", "tool": "text.count_words",
        "arguments": {"text": "count these words now"},
        "rationale": "the request asks for a count", "expectedEffect": "a number",
    }],
})

# Requests chosen for their classification, which is the routing input.
QUESTION = "Why does the Moon appear to change shape during the month?"
OPEN_FILES = "Open Files"
RAM_QUERY = "How much memory am I using?"
DISK_QUERY = "How much storage do I have?"


@dataclass
class PurposefulAdapter(ScriptedAdapter):
    """Scripts per purpose, like the bridge suite's double."""

    plan_script: tuple[tuple[str, Any], ...] = (("structured", PLAN_WITH_TOOL),)
    result_script: tuple[tuple[str, Any], ...] = (("delta", "The Moon is lit by sunlight."),)
    review_script: tuple[tuple[str, Any], ...] = (
        ("structured", json.dumps({"observations": []})),
    )
    purposes: list[str] = field(default_factory=list)

    def generate(self, request, configuration, *, secret, emit, events, cancellation):
        self.purposes.append(request.purpose)
        if request.purpose in ("plan", "repair"):
            self.script = self.plan_script
        elif request.purpose == "review":
            self.script = self.review_script
        else:
            self.script = self.result_script
        return super().generate(
            request, configuration, secret=secret, emit=emit,
            events=events, cancellation=cancellation,
        )


def _broker_with_local_tools() -> ToolBroker:
    broker = ToolBroker()
    broker.tools = {**broker.tools, **LOCAL_FILE_TOOLS, **LOCAL_SYSTEM_TOOLS}
    return broker


class PreferenceRoutingTestCase(CompanionTestCase):
    machine_name = "laptop"

    def agent_service(
        self,
        adapters: dict[str, ScriptedAdapter],
        *,
        configuration: AgentConfiguration,
    ) -> AgentProviderService:
        service = AgentProviderService(AgentServiceOptions(
            root=self.root / "agents",
            configuration=configuration,
            adapters=adapters,
        ))
        self.addCleanup(service.close)
        return service

    def runtime_with(
        self,
        service: AgentProviderService,
        deterministic: DeterministicLocalExecutor,
        *,
        broker: ToolBroker | None = None,
    ):
        broker = broker or _broker_with_local_tools()
        provider_executor = ProviderBackedExecutor(
            service, tool_declarations=broker.declarations())
        return self.started(
            executors=(deterministic, provider_executor),
            broker=broker,
            assessment=assess_current_machine(),
        ), provider_executor

    def run_request(self, runtime, request: str):
        session = runtime.create_session("preference routing")
        task = runtime.submit_task(session.session_id, request)
        finished = runtime.run_task(session.session_id, task.task_id)
        return session, task, finished

    def result_summary(self, runtime, session_id, task_id) -> str:
        summary = ""
        for event in runtime.events(session_id, task_id=task_id):
            if event.event_type == "result_created":
                result = event.payload.get("result") or {}
                summary = str(result.get("summary", ""))
        return summary

    @staticmethod
    def restricted_executor() -> DeterministicLocalExecutor:
        executor = DeterministicLocalExecutor()
        executor.declaration = DeterministicLocalExecutor.restricted_declaration()
        return executor


# --------------------------------------------------------------------------- #
# Unit: the merge is preference, never authority.
# --------------------------------------------------------------------------- #

class MergeAiPreferences(unittest.TestCase):
    def _config(self, *providers):
        return AgentConfiguration(providers=tuple(providers))

    def test_preferred_provider_gains_user_preferred_and_is_selected(self):
        config = self._config(
            scripted_configuration(provider_id="local.other", adapter_id="other"),
            scripted_configuration(provider_id="local.llamacli", adapter_id="llamacli"),
        )
        merged, selected = _merge_ai_preferences(
            config, AiSettings(preferred_provider_id="local.llamacli"))
        self.assertEqual(selected, "local.llamacli")
        by_id = {p.provider_id: p for p in merged.providers}
        self.assertTrue(by_id["local.llamacli"].user_preferred)
        self.assertFalse(by_id["local.other"].user_preferred)
        # Position is preserved; only the flag changed.
        self.assertEqual(
            [p.provider_id for p in merged.providers],
            ["local.other", "local.llamacli"])

    def test_preferred_model_without_provider_lands_on_llamacli(self):
        config = self._config(
            scripted_configuration(provider_id="local.other", adapter_id="other"),
            scripted_configuration(provider_id="local.llamacli", adapter_id="llamacli",
                                   model_id=""),
        )
        merged, selected = _merge_ai_preferences(
            config, AiSettings(preferred_model_id="qwen2.5-1.5b-instruct-q4_k_m.gguf"))
        self.assertEqual(selected, "local.llamacli")
        by_id = {p.provider_id: p for p in merged.providers}
        self.assertEqual(by_id["local.llamacli"].model_id,
                         "qwen2.5-1.5b-instruct-q4_k_m.gguf")
        self.assertFalse(by_id["local.llamacli"].user_preferred)
        self.assertEqual(by_id["local.other"].model_id, "scripted-model")

    def test_provider_and_model_both_named_land_on_the_same_provider(self):
        config = self._config(
            scripted_configuration(provider_id="local.llamacli", adapter_id="llamacli",
                                   model_id=""),
        )
        merged, selected = _merge_ai_preferences(
            config, AiSettings(preferred_provider_id="local.llamacli",
                               preferred_model_id="qwen2.5-1.5b-instruct-q4_k_m.gguf"))
        self.assertEqual(selected, "local.llamacli")
        provider = merged.providers[0]
        self.assertTrue(provider.user_preferred)
        self.assertEqual(provider.model_id, "qwen2.5-1.5b-instruct-q4_k_m.gguf")

    def test_an_unknown_provider_id_is_ignored(self):
        config = self._config(
            scripted_configuration(provider_id="local.llamacli", adapter_id="llamacli"),
        )
        merged, selected = _merge_ai_preferences(
            config, AiSettings(preferred_provider_id="local.nope"))
        self.assertEqual(selected, "")
        self.assertFalse(merged.providers[0].user_preferred)

    def test_empty_preferences_change_nothing(self):
        config = self._config(
            scripted_configuration(provider_id="local.llamacli", adapter_id="llamacli",
                                   model_id="orig.gguf"),
        )
        merged, selected = _merge_ai_preferences(config, AiSettings())
        self.assertEqual(selected, "")
        self.assertFalse(merged.providers[0].user_preferred)
        self.assertEqual(merged.providers[0].model_id, "orig.gguf")


class RestrictedDeclaration(unittest.TestCase):
    def test_restricted_keeps_only_compute_and_local_action(self):
        declaration = DeterministicLocalExecutor.restricted_declaration()
        self.assertEqual(declaration.supported_task_types, ("compute", "local_action"))

    def test_restricted_drops_the_inference_classes(self):
        declaration = DeterministicLocalExecutor.restricted_declaration()
        for inference_class in ("question", "summarise", "transform", "unclassified"):
            self.assertNotIn(inference_class, declaration.supported_task_types)

    def test_restricted_keeps_the_executor_identity(self):
        declaration = DeterministicLocalExecutor.restricted_declaration()
        self.assertEqual(declaration.executor_id, "local.deterministic")
        self.assertTrue(declaration.local)

    def test_default_declaration_still_claims_inference_classes(self):
        # Today's behaviour, bit for bit: a machine with no preference keeps the
        # deterministic executor claiming every class, including inference.
        declaration = DeterministicLocalExecutor().declaration
        for cls in ("question", "summarise", "transform", "unclassified",
                    "compute", "local_action"):
            self.assertIn(cls, declaration.supported_task_types)


# --------------------------------------------------------------------------- #
# Integration: deterministic OS intents stay deterministic under a preference.
# --------------------------------------------------------------------------- #

class DeterministicIntentsStayDeterministic(PreferenceRoutingTestCase):
    def _run_deterministic(self, request: str):
        adapter = PurposefulAdapter()
        service = self.agent_service(
            {"scripted": adapter},
            configuration=AgentConfiguration(providers=(scripted_configuration(),)),
        )
        runtime, _ = self.runtime_with(service, self.restricted_executor())
        os.environ["HOME"] = str(self.root)
        try:
            session, task, finished = self.run_request(runtime, request)
        finally:
            os.environ.pop("HOME", None)
        view = finished.view("executor")
        return adapter, finished, view

    def test_open_files_stays_deterministic(self):
        adapter, finished, view = self._run_deterministic(OPEN_FILES)
        self.assertEqual(view["executorId"], "local.deterministic")
        self.assertFalse(adapter.requests, "a generation ran for an OS intent")

    def test_ram_query_stays_deterministic(self):
        adapter, finished, view = self._run_deterministic(RAM_QUERY)
        self.assertEqual(view["executorId"], "local.deterministic")
        self.assertFalse(adapter.requests, "a generation ran for a RAM query")

    def test_disk_query_stays_deterministic(self):
        adapter, finished, view = self._run_deterministic(DISK_QUERY)
        self.assertEqual(view["executorId"], "local.deterministic")
        self.assertFalse(adapter.requests, "a generation ran for a disk query")


# --------------------------------------------------------------------------- #
# Integration: an ordinary question with a selected provider reaches generation.
# --------------------------------------------------------------------------- #

class OrdinaryQuestionReachesProvider(PreferenceRoutingTestCase):
    def test_question_with_a_selected_provider_is_generated_not_canned(self):
        adapter = PurposefulAdapter()
        service = self.agent_service(
            {"scripted": adapter},
            configuration=AgentConfiguration(providers=(scripted_configuration(),)),
        )
        runtime, provider_executor = self.runtime_with(
            service, self.restricted_executor())
        session, task, finished = self.run_request(runtime, QUESTION)
        # The provider-backed executor took the question, not the deterministic
        # one: generation happened and the answer reached the result.
        self.assertEqual(finished.view("executor")["executorId"],
                         provider_executor.declaration.executor_id)
        self.assertTrue(adapter.requests, "the question never reached generation")
        self.assertIn("result", adapter.purposes)
        self.assertEqual(finished.state, "completed")
        summary = self.result_summary(runtime, session.session_id, task.task_id)
        self.assertIn("Moon", summary)

    def test_preferred_provider_id_reaches_selection_as_user_preferred(self):
        # Two eligible local providers; the second is named in Settings.ai.
        # Preference reorders among the eligible -- it does not need authority
        # because both already pass every eligibility check.
        alpha = PurposefulAdapter()
        llamacli = PurposefulAdapter()
        base = AgentConfiguration(providers=(
            scripted_configuration(provider_id="local.alpha", adapter_id="alpha"),
            scripted_configuration(provider_id="local.llamacli", adapter_id="llamacli"),
        ))
        merged, selected = _merge_ai_preferences(
            base, AiSettings(preferred_provider_id="local.llamacli"))
        self.assertEqual(selected, "local.llamacli")
        service = self.agent_service(
            {"alpha": alpha, "llamacli": llamacli}, configuration=merged)
        runtime, _ = self.runtime_with(service, self.restricted_executor())
        session, task, finished = self.run_request(runtime, QUESTION)
        explanation = service.task_selection(task.task_id)
        self.assertIsNotNone(explanation)
        self.assertEqual(explanation["selected"], "local.llamacli")
        self.assertIn("marked userPreferred in configuration",
                      explanation["decisiveFactors"])
        # The preferred provider's adapter generated; the other stayed idle.
        self.assertTrue(llamacli.requests)
        self.assertFalse(alpha.requests)

    def test_preferred_model_id_reaches_the_model_selection_boundary(self):
        adapter = PurposefulAdapter()
        base = AgentConfiguration(providers=(
            scripted_configuration(provider_id="local.llamacli", adapter_id="llamacli",
                                   model_id=""),
        ))
        merged, _ = _merge_ai_preferences(
            base, AiSettings(preferred_model_id="qwen2.5-1.5b-instruct-q4_k_m.gguf"))
        service = self.agent_service({"llamacli": adapter}, configuration=merged)
        # The model file name landed on the provider configuration, which is
        # what the adapter resolves against before any generation.
        provider = service.registry.configuration.providers[0]
        self.assertEqual(provider.model_id, "qwen2.5-1.5b-instruct-q4_k_m.gguf")
        runtime, _ = self.runtime_with(service, self.restricted_executor())
        session, task, finished = self.run_request(runtime, QUESTION)
        self.assertEqual(finished.state, "completed")
        self.assertTrue(adapter.requests)


class UnavailablePreferredModelFailsBounded(PreferenceRoutingTestCase):
    def test_no_fallback_no_generation_when_the_preferred_model_is_unusable(self):
        # The one local provider's probe refuses: the model is not available.
        adapter = ScriptedAdapter(probe_available=False, probe_detail="model missing")
        service = self.agent_service(
            {"scripted": adapter},
            configuration=AgentConfiguration(providers=(scripted_configuration(),)),
        )
        runtime, _ = self.runtime_with(service, self.restricted_executor())
        session, task, finished = self.run_request(runtime, QUESTION)
        # With the deterministic executor restricted off the inference classes
        # and the only provider unavailable, the task is blocked bounded --
        # not answered with a canned sentence and not sent anywhere remote.
        self.assertEqual(finished.state, "blocked")
        self.assertFalse(adapter.requests,
                         "a generation was dispatched to an unusable provider")
        self.assertTrue(finished.errors)


class NoPreferenceKeepsTodayBehaviour(PreferenceRoutingTestCase):
    def test_without_a_preference_the_deterministic_executor_answers_questions(self):
        adapter = PurposefulAdapter()
        service = self.agent_service(
            {"scripted": adapter},
            configuration=AgentConfiguration(providers=(scripted_configuration(),)),
        )
        # No preference -> the unrestricted deterministic executor, exactly as
        # the service builds it when user_selected_ai_provider is "".
        runtime, _ = self.runtime_with(service, DeterministicLocalExecutor())
        os.environ["HOME"] = str(self.root)
        try:
            session, task, finished = self.run_request(runtime, QUESTION)
        finally:
            os.environ.pop("HOME", None)
        self.assertEqual(finished.view("executor")["executorId"], "local.deterministic")
        self.assertFalse(adapter.requests,
                         "a provider generation ran with no preference set")
        self.assertEqual(finished.state, "completed")
        summary = self.result_summary(runtime, session.session_id, task.task_id)
        # The capability sentence -- the honest "I do not have a language model
        # configured" reply -- is what a machine with no preference still gets.
        self.assertIn("open applications", summary.lower())


class LlamaCliStructuredOutput(unittest.TestCase):
    """The CLI subprocess adapter serves the plan step, not only free-text results.

    The defect these tests pin: ``LlamaCliAdapter.supports_structured_output`` was
    ``False`` and ``generate`` refused any request carrying a schema reference, so
    the registry refused local.llamacli for every plan purpose -- "structured
    output is required and not supported; tool proposals are required and not
    supported" -- even with the model present and healthy, and every local
    question blocked at ``waiting_for_executor``. The planner's structured output
    is prompt-based: the JSON instruction is in the prompt and ``parse_structured``
    plus one repair round validate the text. The same llama.cpp engine whose
    server adapter (``llamacpp``) declares structured support is declared here
    for the prompt path.
    """

    def test_the_adapter_declares_structured_output_support(self):
        from companion.agents.adapters.llamacli import LlamaCliAdapter

        self.assertTrue(
            LlamaCliAdapter.supports_structured_output,
            "llamacli must serve the prompt-based plan step; llamacpp (the same "
            "engine's server adapter) declares this True",
        )

    def test_a_plan_requirement_does_not_refuse_a_structured_local_provider(self):
        # The exact gate that blocked local.llamacli: a plan-purpose requirement
        # (structured output + tool proposals) against a local provider that
        # declares support. The registry must find it eligible -- the
        # structured-output and tool-proposal reasons must not appear.
        from companion.agents.adapter import ModelListing
        from companion.agents.config import AgentConfiguration, ProviderConfiguration
        from companion.agents.descriptor import EndpointIdentity
        from companion.agents.registry import AgentProviderRegistry, SelectionRequirement

        adapter = ScriptedAdapter(
            adapter_identity="llamacli",
            supports_structured_output=True,
            probe_available=True,
            probe_detail="llama-cli with qwen2.5-1.5b-instruct-q4_k_m.gguf",
            models=(ModelListing(
                model_id="qwen2.5-1.5b-instruct-q4_k_m.gguf",
                size_bytes=1117320736),),
        )
        config = ProviderConfiguration(
            provider_id="local.llamacli", adapter_id="llamacli",
            endpoint=EndpointIdentity(kind="subprocess", locator="llama-cli"),
            program="llama-cli",
            model_id="qwen2.5-1.5b-instruct-q4_k_m.gguf",
        )
        registry = AgentProviderRegistry(
            AgentConfiguration(providers=(config,)), {"llamacli": adapter})
        requirement = SelectionRequirement(
            task_class="question", locality="device-only",
            needs_structured_output=True, needs_tool_proposals=True,
        )
        explanation = registry.select(requirement, monotonic=0.0)
        self.assertTrue(explanation.found)
        self.assertEqual(explanation.selected, "local.llamacli")
        self.assertEqual(explanation.ineligible, ())
        # Belt-and-braces: the structured-output and tool-proposal reasons that
        # blocked the chain are absent from any ineligible provider.
        for _provider_id, reasons in explanation.ineligible:
            self.assertNotIn("structured output is required and not supported", reasons)
            self.assertNotIn("tool proposals are required and not supported", reasons)

    def test_generate_proceeds_past_the_structured_request_guard(self):
        # The refusal guard that made selection's "yes" a dead letter: with the
        # flag True, the plan request now carries a schema reference, and
        # generate() must run the subprocess rather than return
        # failure_kind="malformed-output". Program and model resolution are
        # stubbed and Popen is made to fail, so the outcome is "connection" --
        # the point is that it is NOT the structured-output refusal.
        from pathlib import Path
        from unittest import mock

        from companion.agents.adapter import CancellationSignal, StreamEventFactory
        from companion.agents.adapters import llamacli as llamacli_module
        from companion.agents.adapters.llamacli import LlamaCliAdapter
        from companion.agents.config import ProviderConfiguration
        from companion.agents.descriptor import EndpointIdentity
        from companion.agents.structured import PLAN_SCHEMA_REFERENCE

        from .agents_support import make_request

        request = make_request(
            provider_id="local.llamacli", purpose="plan",
            structured_schema_reference=PLAN_SCHEMA_REFERENCE,
        )
        configuration = ProviderConfiguration(
            provider_id="local.llamacli", adapter_id="llamacli",
            endpoint=EndpointIdentity(kind="subprocess", locator="llama-cli"),
            program="llama-cli",
            model_id="qwen2.5-1.5b-instruct-q4_k_m.gguf",
        )
        events = StreamEventFactory(
            request_id=request.request_id, provider_id=request.provider_id,
            monotonic=lambda: 0.0,
        )
        sink: list = []
        with mock.patch.object(llamacli_module, "_resolve_program",
                               return_value=("/usr/bin/llama-cli", "")), \
             mock.patch.object(llamacli_module, "_resolve_model",
                               return_value=(Path("/tmp/fa-model.gguf"), "")), \
             mock.patch.object(llamacli_module.subprocess, "Popen",
                               side_effect=OSError("test: no spawn")):
            outcome = LlamaCliAdapter().generate(
                request, configuration, secret=None,
                emit=sink.append, events=events, cancellation=CancellationSignal(),
            )
        self.assertNotEqual(outcome.failure_kind, "malformed-output",
                             "the structured-output refusal guard is gone")
        self.assertEqual(outcome.failure_kind, "connection")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()