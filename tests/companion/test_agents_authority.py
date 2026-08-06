# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§1's boundaries for agent providers, asserted from the structure.

The claims: a provider may accept a sanitized request, produce output, stream,
propose, report and cancel — and may not execute a tool, read a file it was
not handed, resolve or create an approval, select another provider, change
task state, or dispatch remotely without policy and approval. Where a claim is
structural it is tested structurally: the import graph of the package, the
attribute surface of the worker, the closed set of context sources, the
absence of a credential field anywhere a record is built from.

The one seam is :mod:`companion.agent_bridge`, which lives *outside* the
package — the same arrangement :mod:`companion.capability_bridge` has — so
"the subsystem is runtime-free" stays checkable by reading one directory.
"""

from __future__ import annotations

import ast
import tempfile
from pathlib import Path
import unittest

import companion.agents
from companion.agents.context import CONTEXT_SOURCES
from companion.agents.descriptor import ProviderDescriptor
from companion.agents.request import GenerationRequest

from .agents_support import build_worker

#: Modules that hold task authority. Nothing under companion/agents/ may
#: import any of them — the same proof-by-import-graph voice and speech carry.
_FORBIDDEN_IMPORTS = (
    "companion.runtime", "companion.store", "companion.task",
    "companion.approvals", "companion.executor", "companion.tools",
    "companion.session", "companion.reviewer", "companion.cancellation",
    "companion.recovery", "companion.events", "companion.coordination",
    "companion.migration",
)


class ImportGraph(unittest.TestCase):
    def test_no_agents_module_imports_task_authority(self) -> None:
        package = Path(companion.agents.__file__).parent
        for module_path in sorted(package.rglob("*.py")):
            tree = ast.parse(module_path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    if node.level:
                        names = ["companion." + node.module]
                    else:
                        names = [node.module]
                for name in names:
                    for forbidden in _FORBIDDEN_IMPORTS:
                        self.assertFalse(
                            name == forbidden or name.startswith(forbidden + "."),
                            f"{module_path.name} imports {name}, which holds task authority",
                        )

    def test_no_agents_module_reaches_for_a_shell(self) -> None:
        """No subprocess import outside the one adapter, and no os.system anywhere.

        The llamacli adapter is the single sanctioned subprocess site, and it
        builds argv arrays from an allowlist. Everything else in the package
        must not spawn at all. Read from the AST rather than the text: the
        *word* "subprocess" legitimately appears as an endpoint kind.
        """
        package = Path(companion.agents.__file__).parent
        for module_path in sorted(package.rglob("*.py")):
            tree = ast.parse(module_path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                imported: list[str] = []
                if isinstance(node, ast.Import):
                    imported = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported = [node.module]
                for name in imported:
                    if name == "subprocess" or name.startswith("subprocess."):
                        self.assertEqual(
                            module_path.name, "llamacli.py",
                            f"{module_path.name} imports subprocess; only llamacli.py may",
                        )
                if isinstance(node, ast.Attribute) and node.attr == "system":
                    value = node.value
                    self.assertFalse(
                        isinstance(value, ast.Name) and value.id == "os",
                        f"{module_path.name} calls os.system",
                    )


class SchemaSurfaces(unittest.TestCase):
    #: Exact field names a credential or a hidden channel would need. Token
    #: *counts* (``context_limit_tokens``) and the cancellation token — an
    #: opaque correlation id, not a secret — are deliberately not matched;
    #: :mod:`companion.privacy` draws the same numeric-count distinction.
    _CREDENTIAL_NAMES = frozenset({
        "credential", "credentials", "api_key", "apikey", "token", "secret",
        "authorization", "bearer", "password", "headers", "auth_header",
    })

    def test_the_descriptor_has_nowhere_to_put_a_credential(self) -> None:
        field_names = {name.lower() for name in ProviderDescriptor.__dataclass_fields__}
        self.assertFalse(field_names & self._CREDENTIAL_NAMES)
        for name in field_names:
            self.assertFalse(name.endswith(("_key", "_secret", "_token")) and name != "cancellation_token", name)

    def test_the_request_has_nowhere_to_put_hidden_reasoning(self) -> None:
        field_names = {name.lower() for name in GenerationRequest.__dataclass_fields__}
        self.assertFalse(field_names & self._CREDENTIAL_NAMES)
        for hostile in ("reasoning", "scratch", "hidden", "monologue"):
            for name in field_names:
                self.assertNotIn(hostile, name, name)

    def test_the_context_source_set_is_closed_and_excludes_the_forbidden(self) -> None:
        """§7's exclusion list, as an absence of values rather than a filter."""
        for forbidden in (
            "credentials", "raw-audio", "microphone", "screen-capture",
            "file", "other-session", "hidden-reasoning", "approval-records",
        ):
            self.assertNotIn(forbidden, CONTEXT_SOURCES)


class ObjectGraph(unittest.TestCase):
    def test_the_worker_holds_nothing_with_task_authority(self) -> None:
        root = Path(tempfile.mkdtemp())
        worker, registry, ledger, journal, clock = build_worker(root)
        self.addCleanup(worker.stop)
        for attribute in vars(worker).values():
            module = type(attribute).__module__
            for forbidden in _FORBIDDEN_IMPORTS:
                self.assertFalse(
                    module.startswith(forbidden),
                    f"the worker holds a {module} object",
                )

    def test_the_service_boundaries_are_stated_and_false(self) -> None:
        from companion.agents.service import AgentProviderService

        boundaries = AgentProviderService.boundaries()
        for name in (
            "executesTools", "resolvesApprovals", "createsTasks",
            "readsArbitraryFiles", "controlsDesktop", "mutatesConfiguration",
            "hiddenRemoteFallback", "storesCredentials",
        ):
            self.assertIn(name, boundaries)
            self.assertFalse(boundaries[name], name)

    def test_the_service_cannot_submit_or_resolve(self) -> None:
        from companion.agents.service import AgentProviderService

        self.assertFalse(hasattr(AgentProviderService, "submit_task"))
        self.assertFalse(hasattr(AgentProviderService, "resolve_approval"))
        self.assertFalse(hasattr(AgentProviderService, "runtime"))


class ProtocolSurface(unittest.TestCase):
    def test_no_provider_operation_mutates_configuration_or_carries_a_credential(self) -> None:
        from companion.protocol import PROVIDER_OPERATIONS

        self.assertEqual(sorted(PROVIDER_OPERATIONS), [
            "provider_health", "provider_models", "provider_test_local",
            "providers_explain", "providers_list", "providers_status",
            "task_provider_cancel", "task_provider_status",
        ])
        for operation in PROVIDER_OPERATIONS.values():
            for parameter in operation.parameters:
                lowered = parameter.name.lower()
                for hostile in ("credential", "key", "secret", "token", "endpoint", "url"):
                    self.assertNotIn(hostile, lowered, parameter.name)
