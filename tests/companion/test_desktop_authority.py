# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§1's and §14's boundaries, asserted from the structure rather than the prose.

The claims this file checks are the ones that must hold whatever anybody later
believes about them:

* nothing under ``companion/desktop/`` imports the runtime, the store, the task
  model, the approval gate or the tool broker — the seam is
  :mod:`companion.desktop_bridge` and it lives outside the package;
* nothing under ``companion/agents/`` imports the desktop package, its adapters,
  a portal, a D-Bus client, a GTK action API or the tool broker's internals;
* no module under ``companion/desktop/`` reaches for a shell, and the two that
  spawn at all do so through the allowlisted runner;
* the request object has nowhere to put a command, an executable, an argument
  vector, an environment variable, a credential, a bus destination or a screen
  capture;
* the D-Bus surface is a closed table whose entries fix everything except the
  argument values;
* the protocol surface performs nothing.

Structural because the alternative is a comment. A test that asserted "we do not
run shells" by running one and checking it failed would prove that one string was
refused; reading the import graph proves there is no code to refuse it with.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
import unittest

import companion.agents
import companion.desktop
from companion.desktop import adapters as desktop_adapters
from companion.desktop.adapters.dbus import DBUS_CALLS
from companion.desktop.request import DesktopActionRequest, FORBIDDEN_REQUEST_FIELD_WORDS
from companion.desktop.service import DesktopActionService

#: Modules that hold task authority. Nothing under ``companion/desktop/`` may
#: import any of them — the same proof-by-import-graph the voice, speech and
#: agent packages carry.
_FORBIDDEN_FOR_DESKTOP = (
    "companion.runtime", "companion.store", "companion.task", "companion.approvals",
    "companion.executor", "companion.tools", "companion.session", "companion.reviewer",
    "companion.cancellation", "companion.recovery", "companion.coordination",
    "companion.migration", "companion.agent_bridge", "companion.desktop_bridge",
    "companion.agents",
)

#: What a provider may not reach. §14's list, plus the bridge itself: a provider
#: that could import the bridge could reach the broker through it.
_FORBIDDEN_FOR_AGENTS = (
    "companion.desktop", "companion.desktop_bridge", "companion.tools",
    "gi.repository", "dbus", "pydbus", "gtk", "Xlib",
)


def _imports(module_path: Path) -> list[str]:
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.level:
                # A relative import inside `companion/desktop/adapters/` with
                # level 2 means `companion.desktop`; with level 3, `companion`.
                found.append("companion." + node.module)
            else:
                found.append(node.module)
    return found


class ImportGraph(unittest.TestCase):
    def test_no_desktop_module_imports_task_authority(self) -> None:
        package = Path(companion.desktop.__file__).parent
        for module_path in sorted(package.rglob("*.py")):
            if module_path.name == "vertical_slice.py":
                # The slice is a *test harness* that drives a real service, so it
                # necessarily imports one. It ships in the package because it is
                # run on installed systems; it is excluded here by name rather
                # than by a pattern, so a second exclusion would have to be
                # argued for.
                continue
            for name in _imports(module_path):
                for forbidden in _FORBIDDEN_FOR_DESKTOP:
                    self.assertFalse(
                        name == forbidden or name.startswith(forbidden + "."),
                        f"{module_path.name} imports {name}, which holds task authority",
                    )

    def test_no_agent_module_can_reach_the_desktop(self) -> None:
        """§14, exactly: a provider cannot import a broker, an adapter or a bus."""
        package = Path(companion.agents.__file__).parent
        for module_path in sorted(package.rglob("*.py")):
            for name in _imports(module_path):
                for forbidden in _FORBIDDEN_FOR_AGENTS:
                    self.assertFalse(
                        name == forbidden or name.startswith(forbidden + "."),
                        f"{module_path.name} imports {name}; §14 forbids a provider reaching it",
                    )

    def test_only_the_command_transport_spawns(self) -> None:
        """``subprocess`` appears in two files, and both go through the allowlist."""
        package = Path(companion.desktop.__file__).parent
        spawning: list[str] = []
        for module_path in sorted(package.rglob("*.py")):
            tree = ast.parse(module_path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                imported: list[str] = []
                if isinstance(node, ast.Import):
                    imported = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported = [node.module]
                if any(item == "subprocess" or item.startswith("subprocess.") for item in imported):
                    spawning.append(module_path.name)
                if isinstance(node, ast.Attribute) and node.attr in ("system", "popen", "execv", "execvp"):
                    value = node.value
                    self.assertFalse(
                        isinstance(value, ast.Name) and value.id == "os",
                        f"{module_path.name} calls os.{node.attr}",
                    )
        self.assertEqual(
            sorted(set(spawning)), ["command.py"],
            "only the command transport may import subprocess",
        )

    def test_nothing_uses_shell_true(self) -> None:
        package = Path(companion.desktop.__file__).parent
        for module_path in sorted(package.rglob("*.py")):
            tree = ast.parse(module_path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.keyword) or node.arg != "shell":
                    continue
                self.assertFalse(
                    isinstance(node.value, ast.Constant) and node.value.value is True,
                    f"{module_path.name} passes shell=True",
                )


class RequestSurface(unittest.TestCase):
    def test_the_request_has_nowhere_to_put_an_execution(self) -> None:
        """§3's absences, as an absence of fields."""
        names = {name.lower() for name in DesktopActionRequest.__dataclass_fields__}
        for hostile in FORBIDDEN_REQUEST_FIELD_WORDS:
            for name in names:
                self.assertNotIn(
                    hostile, name,
                    f"DesktopActionRequest.{name} contains {hostile!r}",
                )

    def test_the_request_carries_every_field_section_three_names(self) -> None:
        expected = {
            "request_id", "session_id", "task_id", "lifecycle_epoch", "plan_id",
            "operation_id", "idempotency_key", "action_id", "parameters",
            "expected_effect", "target", "classification", "approval_class",
            "approval_reference", "created_at", "expires_at_monotonic",
            "deadline_monotonic", "cancellation_token", "reversibility",
            "undo_action_id", "presentation", "audit_reference",
        }
        missing = expected - set(DesktopActionRequest.__dataclass_fields__)
        self.assertFalse(missing, f"§3 fields absent from the request: {sorted(missing)}")

    def test_the_record_form_carries_no_parameters(self) -> None:
        """§13: a durable record holds digests, not the clipboard's contents."""
        from companion.desktop.parameters import normalise
        from companion.desktop.request import DesktopActionRequest as Request

        action = normalise(
            "desktop.clipboard.copy-text",
            {"text": "a secret-shaped sentence", "classification": "internal"},
        )
        request = Request.build(
            action, request_id="dreq-1", session_id="s-1", task_id="t-1",
            lifecycle_epoch=0, plan_id="p-1", operation_id="op",
            cancellation_token="c-1", wall_now=0.0, monotonic_now=0.0,
            approval_ttl_seconds=60.0,
        )
        record = request.to_record_json()
        self.assertNotIn("parameters", record)
        self.assertNotIn("a secret-shaped sentence", repr(record))
        self.assertTrue(record["bindingDigest"])


class DbusSurface(unittest.TestCase):
    def test_every_declared_call_fixes_its_destination(self) -> None:
        for call_id, entry in DBUS_CALLS.items():
            self.assertTrue(entry.bus_name, f"{call_id} has no bus name")
            self.assertTrue(entry.interface, f"{call_id} has no interface")
            self.assertTrue(entry.method, f"{call_id} has no method")
            self.assertTrue(entry.signature.startswith("("), f"{call_id} has no signature")

    def test_only_the_portal_request_entry_takes_an_object_path(self) -> None:
        """The single exception, and it is the only one, checked as a count."""
        parameterised = [
            call_id for call_id, entry in DBUS_CALLS.items() if not entry.object_path
        ]
        self.assertEqual(parameterised, ["portal.close_request"])

    def test_the_bus_refuses_an_undeclared_call(self) -> None:
        from companion.desktop.adapters.dbus import SessionBus
        from companion.desktop.errors import DesktopUnavailable

        bus = SessionBus()
        with self.assertRaises(DesktopUnavailable) as caught:
            bus.call("org.example.Anything.Do")
        self.assertIn("not a declared D-Bus call", str(caught.exception))

    def test_the_bus_refuses_an_arbitrary_object_path(self) -> None:
        from companion.desktop.adapters.dbus import SessionBus
        from companion.desktop.errors import DesktopUnavailable

        bus = SessionBus()
        with self.assertRaises(DesktopUnavailable):
            bus.call("portal.close_request", (), object_path="/org/example/Evil")
        with self.assertRaises(DesktopUnavailable):
            bus.call("notifications.notify", (), object_path="/somewhere/else")

    def test_the_system_bus_is_never_opened(self) -> None:
        source = Path(
            companion.desktop.__file__
        ).parent.joinpath("adapters", "dbus.py").read_text(encoding="utf-8")
        self.assertNotIn("BusType.SYSTEM", source)
        self.assertIn("BusType.SESSION", source)


class CommandSurface(unittest.TestCase):
    def test_no_generic_dbus_client_is_on_the_executable_allowlist(self) -> None:
        from companion.desktop.adapters.command import ALLOWED_EXECUTABLES

        for hostile in ("sh", "bash", "env", "xdg-open", "dbus-send", "gdbus", "busctl", "qdbus"):
            self.assertNotIn(hostile, ALLOWED_EXECUTABLES)

    def test_an_unlisted_program_is_refused_before_the_filesystem(self) -> None:
        from companion.desktop.adapters.command import CommandUnavailable, run_command

        with self.assertRaises(CommandUnavailable):
            run_command("sh", ["-c", "true"])

    def test_clipboard_text_never_reaches_an_argument_vector(self) -> None:
        """§13, and the reason: an argv is world-readable in ``/proc``."""
        from companion.desktop.adapters import clipboard as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        # The text is passed as `stdin_text=` and nowhere else. Asserted on the
        # construction sites rather than on the runner, because the runner is
        # shared and the decision is made here.
        for line in source.splitlines():
            if "BackgroundChild(" in line or line.strip().startswith('"wl-copy"') or line.strip().startswith('"xclip"'):
                self.assertNotIn("text,", line.replace("stdin_text=text", ""))
        self.assertEqual(source.count("stdin_text=text"), 2)


class AdapterSurface(unittest.TestCase):
    def test_every_adapter_exposes_only_its_declared_operations(self) -> None:
        """No adapter has a generic method through which another call could go."""
        from companion.desktop.adapters.audio import AudioControlAdapter
        from companion.desktop.adapters.clipboard import ClipboardAdapter
        from companion.desktop.adapters.filereveal import FileRevealAdapter
        from companion.desktop.adapters.notification import NotificationAdapter
        from companion.desktop.adapters.settings import SettingsAdapter
        from companion.desktop.adapters.uri import UriOpenAdapter

        permitted = {
            NotificationAdapter: {"probe", "show", "close", "supports_markup",
                                  "forget_all", "close_connection", "outstanding"},
            SettingsAdapter: {"probe", "probe_do_not_disturb", "open_page",
                              "read_do_not_disturb", "set_do_not_disturb", "desktop"},
            AudioControlAdapter: {"probe", "read", "default_output", "default_output_id",
                                  "set_volume"},
            ClipboardAdapter: {"probe", "copy", "release", "release_all", "outstanding"},
            UriOpenAdapter: {"probe", "open", "cancel", "settle", "outstanding"},
            FileRevealAdapter: {"probe", "reveal", "close"},
        }
        for adapter, allowed in permitted.items():
            public = {
                name for name, _ in inspect.getmembers(adapter)
                if not name.startswith("_") and name != "adapter_id"
            }
            extra = public - allowed
            self.assertFalse(
                extra, f"{adapter.__name__} exposes {sorted(extra)}, which nothing declares"
            )

    def test_the_adapter_outcome_cannot_carry_a_backend_object(self) -> None:
        from companion.desktop.adapters.base import AdapterOutcome

        names = set(AdapterOutcome.__dataclass_fields__)
        for hostile in ("handle", "connection", "proxy", "socket", "fd", "descriptor", "process"):
            self.assertFalse(
                any(hostile in name for name in names),
                f"AdapterOutcome has a field containing {hostile!r}",
            )

    def test_the_declared_adapters_and_the_descriptor_backends_agree(self) -> None:
        from companion.desktop.catalogue import BACKENDS

        self.assertEqual(len(BACKENDS), 8)
        self.assertEqual(len(desktop_adapters.ADAPTER_IDS), 9)  # the eight, plus the portal


class ProtocolSurface(unittest.TestCase):
    def test_the_service_boundaries_are_stated_and_false(self) -> None:
        boundaries = DesktopActionService.boundaries()
        for name in (
            "performsActions", "resolvesApprovals", "createsTasks",
            "acceptsArbitraryParameters", "invokesTools", "reachesDbusDirectly",
            "runsSubprocesses", "readsClipboard", "capturesScreen", "returnsBackendHandles",
        ):
            self.assertIn(name, boundaries)
            self.assertFalse(boundaries[name], name)

    def test_no_protocol_operation_names_a_target_or_performs_an_action(self) -> None:
        from companion.protocol import DESKTOP_OPERATIONS

        self.assertEqual(sorted(DESKTOP_OPERATIONS), [
            "desktop_action_cancel", "desktop_action_explain", "desktop_action_history",
            "desktop_action_undo", "desktop_actions_list", "desktop_actions_status",
        ])
        for operation in DESKTOP_OPERATIONS.values():
            for parameter in operation.parameters:
                lowered = parameter.name.lower()
                for hostile in (
                    "command", "path", "uri", "url", "application", "executable",
                    "parameters", "arguments", "bus", "interface", "text",
                ):
                    self.assertNotIn(hostile, lowered, f"{operation.name}.{parameter.name}")

    def test_the_service_has_no_method_that_performs_an_action(self) -> None:
        public = {
            name for name, _ in inspect.getmembers(DesktopActionService)
            if not name.startswith("_")
        }
        # Two methods. Every handler is private and reachable only through
        # `serve`, which validates against the protocol table first — so there
        # is no public entry point that skips the schema.
        self.assertEqual(public, {"serve", "boundaries"})
        self.assertEqual(set(DesktopActionService.__dataclass_fields__), {"broker"})


class BridgeSurface(unittest.TestCase):
    def test_the_tool_declaration_requires_the_authority_facts(self) -> None:
        from companion.desktop_bridge import desktop_tool_declarations

        for declaration in desktop_tool_declarations():
            self.assertTrue(declaration.requires_context, declaration.tool_id)
            self.assertTrue(declaration.interrupts_user, declaration.tool_id)
            self.assertFalse(declaration.external_destination, declaration.tool_id)

    def test_a_desktop_tool_called_without_a_context_is_refused(self) -> None:
        from companion.desktop_bridge import DesktopSupport, register_desktop_tools
        from companion.tools import ToolBroker

        from .desktop_support import FakeAdapters

        broker = ToolBroker()
        support = DesktopSupport.create(adapters=FakeAdapters())
        self.addCleanup(support.stop)
        register_desktop_tools(broker, support)
        outcome = broker.invoke(
            "desktop.notification.show", {"title": "x"}, caller="runtime",
        )
        self.assertFalse(outcome.ok)
        self.assertIn("authority facts", outcome.detail)
        self.assertTrue(broker.refusals)

    def test_a_desktop_tool_called_with_a_foreign_context_is_refused(self) -> None:
        from companion.desktop_bridge import DesktopSupport, register_desktop_tools
        from companion.tools import ToolBroker

        from .desktop_support import FakeAdapters

        broker = ToolBroker()
        support = DesktopSupport.create(adapters=FakeAdapters())
        self.addCleanup(support.stop)
        register_desktop_tools(broker, support)
        outcome = broker.invoke(
            "desktop.notification.show", {"title": "x"}, caller="runtime",
            context={"taskId": "t-1", "approvalReference": "anything"},
        )
        self.assertFalse(outcome.ok)
        self.assertIn("not a desktop invocation context", outcome.detail)

    def test_a_reviewer_cannot_reach_a_desktop_tool(self) -> None:
        from companion.desktop_bridge import DesktopSupport, register_desktop_tools
        from companion.errors import ReviewerViolation
        from companion.tools import ToolBroker

        from .desktop_support import FakeAdapters

        broker = ToolBroker()
        support = DesktopSupport.create(adapters=FakeAdapters())
        self.addCleanup(support.stop)
        register_desktop_tools(broker, support)
        with self.assertRaises(ReviewerViolation):
            broker.invoke(
                "desktop.notification.show", {"title": "x"}, caller="reviewer:local",
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
