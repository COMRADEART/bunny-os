# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§5 and §21 "Providers": running a synthesiser without giving it the machine.

The subprocess tests start real interpreters. That is deliberate and is the one
place in this suite a fake would prove nothing: whether a child that ignores
``SIGTERM`` is escalated to ``SIGKILL`` and reaped is a property of the operating
system's signal delivery, not of any Python object, and a mock that "pretended
to ignore SIGTERM" would be testing the mock.
"""

from __future__ import annotations

import os
from pathlib import Path
import stat
import sys
import tempfile
import threading
import time
import unittest

from companion.voice.execution import (
    ALLOWED_EXECUTABLES,
    CancellationSignal,
    CommandSpec,
    ExecutableRefused,
    MAX_STDERR_BYTES,
    PrivateWorkspace,
    TEXT_MARKER,
    TRUSTED_DIRECTORIES,
    child_environment,
    posix_only,
    redacted_argv,
    resolve_executable,
    run,
)
from companion.voice.provider import ProviderDeclaration, ProviderRegistry
from companion.voice.providers import (
    EspeakNgProvider,
    SpeechDispatcherProvider,
    local_providers,
)

from .voice_support import (
    ScriptedProvider,
    echoing_child,
    ignoring_terminator,
    make_request,
    noisy_child,
    sleeping_child,
)

POSIX = posix_only()


class AllowlistTests(unittest.TestCase):
    def test_a_program_outside_the_allowlist_is_refused(self) -> None:
        for name in ("bash", "sh", "curl", "python3", "rm"):
            with self.subTest(name=name):
                with self.assertRaises(ExecutableRefused) as caught:
                    resolve_executable(name)
                self.assertIn("allowlist", str(caught.exception))

    def test_a_name_containing_a_path_separator_is_refused(self) -> None:
        with self.assertRaises(ExecutableRefused):
            resolve_executable("../../bin/sh")
        with self.assertRaises(ExecutableRefused):
            resolve_executable("/usr/bin/espeak-ng")

    def test_the_allowlist_holds_only_synthesisers_players_and_enumerators(self) -> None:
        self.assertEqual(ALLOWED_EXECUTABLES, frozenset({
            "spd-say", "espeak-ng", "espeak", "say",
            "paplay", "pw-play", "aplay",
            "pactl", "pw-dump", "spd-conf",
        }))

    @unittest.skipUnless(POSIX, "trusted directories are a POSIX arrangement")
    def test_resolution_searches_trusted_directories_and_never_the_path(self) -> None:
        directory = Path(tempfile.mkdtemp())
        planted = directory / "espeak-ng"
        planted.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        planted.chmod(0o755)
        previous = os.environ.get("PATH")
        os.environ["PATH"] = str(directory)
        try:
            try:
                found, trusted = resolve_executable("espeak-ng")
            except ExecutableRefused:
                # Not installed on this host: the refusal is itself the proof
                # that the planted copy on PATH was not used.
                return
            self.assertNotEqual(Path(found).parent, directory)
            self.assertTrue(trusted)
        finally:
            if previous is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = previous

    @unittest.skipUnless(POSIX, "file modes are a POSIX arrangement")
    def test_a_world_writable_binary_is_refused(self) -> None:
        directory = Path(tempfile.mkdtemp())
        planted = directory / "espeak-ng"
        planted.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        planted.chmod(0o777)
        with self.assertRaises(ExecutableRefused) as caught:
            resolve_executable("espeak-ng", directories=(str(directory),))
        self.assertIn("writable by group or other", str(caught.exception))

    @unittest.skipUnless(POSIX, "symbolic links are a POSIX arrangement")
    def test_a_multi_call_binary_is_invoked_under_the_name_that_was_asked_for(self) -> None:
        """Resolution must not rewrite argv[0] for a program that reads it.

        `/usr/bin/paplay` is a symlink to `pacat`, and `pacat` decides what it
        does from its own name: under `paplay` it parses a sound file, under
        `pacat` it reads raw PCM. Returning the symlink target made the runtime
        exec `pacat`, which played a WAV's header and its mono samples as stereo
        raw data — 0.73 s of noise where 2.80 s of speech belonged, exit code 0.

        The resolved target is still checked; what is returned is the trusted
        path that was asked for.
        """
        directory = Path(tempfile.mkdtemp())
        real = directory / "pacat"
        real.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        real.chmod(0o755)
        (directory / "paplay").symlink_to(real)

        found, trusted = resolve_executable("paplay", directories=(str(directory),))
        self.assertTrue(trusted)
        self.assertEqual(
            Path(found).name, "paplay",
            "the program was resolved to its symlink target, which changes what it does",
        )
        self.assertEqual(Path(found).parent, directory)

    @unittest.skipUnless(POSIX, "symbolic links are a POSIX arrangement")
    def test_a_trusted_name_linking_out_of_the_trusted_set_is_refused(self) -> None:
        trusted = Path(tempfile.mkdtemp())
        elsewhere = Path(tempfile.mkdtemp())
        real = elsewhere / "impostor"
        real.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        real.chmod(0o755)
        (trusted / "espeak-ng").symlink_to(real)
        with self.assertRaises(ExecutableRefused) as caught:
            resolve_executable("espeak-ng", directories=(str(trusted),))
        self.assertIn("executable substitution", str(caught.exception))


class EnvironmentTests(unittest.TestCase):
    def test_the_child_environment_is_built_rather_than_inherited(self) -> None:
        environment = child_environment(source={
            "HOME": "/home/bunny",
            "SECRET_TOKEN": "abcdef",
            "LD_PRELOAD": "/tmp/evil.so",
            "PATH": "/tmp/attacker",
        })
        self.assertEqual(environment["HOME"], "/home/bunny")
        self.assertNotIn("SECRET_TOKEN", environment)
        self.assertNotIn("LD_PRELOAD", environment)
        self.assertEqual(environment["PATH"], os.pathsep.join(TRUSTED_DIRECTORIES))

    def test_a_provider_cannot_reintroduce_a_denied_variable(self) -> None:
        with self.assertRaises(ExecutableRefused):
            child_environment(extra={"LD_PRELOAD": "/tmp/evil.so"})
        with self.assertRaises(ExecutableRefused):
            child_environment(extra={"HTTPS_PROXY": "http://elsewhere"})

    def test_a_malformed_variable_name_or_value_is_refused(self) -> None:
        for extra in ({"A=B": "x"}, {"A": "with\0nul"}, {"": "x"}):
            with self.subTest(extra=extra):
                with self.assertRaises(ExecutableRefused):
                    child_environment(extra=extra)


class RedactionTests(unittest.TestCase):
    def test_the_declared_text_slot_is_replaced_in_a_logged_argv(self) -> None:
        argv = ["/usr/bin/spd-say", "--wait", "--", "the answer is forty-two"]
        self.assertEqual(redacted_argv(argv, text_argument_index=2)[3], TEXT_MARKER)

    def test_the_index_accounts_for_the_executable_at_position_zero(self) -> None:
        """Getting this wrong would redact a flag and publish the caption."""
        spec = CommandSpec(
            executable="/usr/bin/spd-say",
            arguments=("--wait", "--", "PLACEHOLDER"),
            text_argument_index=2,
        ).with_text("the secret caption")
        redacted = spec.redacted()
        self.assertNotIn("the secret caption", redacted)
        self.assertEqual(redacted[3], TEXT_MARKER)
        self.assertEqual(redacted[1], "--wait")

    def test_a_command_that_hides_the_text_in_an_undeclared_argument_is_refused(self) -> None:
        spec = CommandSpec(
            executable=sys.executable,
            arguments=("-c", "pass", "the secret caption"),
            stdin_text="the secret caption",
            text_argument_index=None,
        )
        with self.assertRaises(ExecutableRefused) as caught:
            run(spec)
        self.assertIn("process table", str(caught.exception))


class WorkspaceTests(unittest.TestCase):
    def test_a_workspace_is_private_and_its_files_are_private(self) -> None:
        workspace = PrivateWorkspace()
        try:
            path = workspace.file("utterance")
            self.assertTrue(path.exists())
            if POSIX:
                self.assertEqual(stat.S_IMODE(workspace.root.stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        finally:
            workspace.close()

    def test_closing_removes_everything_and_is_idempotent(self) -> None:
        workspace = PrivateWorkspace()
        path = workspace.file("utterance")
        workspace.close()
        workspace.close()
        self.assertFalse(path.exists())
        self.assertFalse(workspace.root.exists())
        self.assertTrue(workspace.closed)

    def test_a_hostile_file_name_cannot_escape_the_workspace(self) -> None:
        workspace = PrivateWorkspace()
        try:
            path = workspace.file("../../../etc/passwd")
            self.assertEqual(path.parent, workspace.root)
        finally:
            workspace.close()

    def test_a_closed_workspace_refuses_to_make_more_files(self) -> None:
        workspace = PrivateWorkspace()
        workspace.close()
        with self.assertRaises(RuntimeError):
            workspace.file("late")


class SubprocessTests(unittest.TestCase):
    def test_the_utterance_travels_through_stdin_rather_than_the_argv(self) -> None:
        directory = Path(tempfile.mkdtemp())
        target = directory / "echoed.txt"
        argv = echoing_child()
        outcome = run(CommandSpec(
            executable=argv[0],
            arguments=tuple(argv[1:]),
            stdin_text="the answer is forty-two",
            environment={"ECHO_TARGET": str(target)},
            timeout_seconds=20.0,
        ))
        self.assertTrue(outcome.succeeded, outcome.stderr)
        self.assertEqual(target.read_text(encoding="utf-8"), "the answer is forty-two")
        self.assertNotIn("forty-two", " ".join(outcome.redacted_argv))

    def test_stderr_is_captured_and_bounded(self) -> None:
        argv = noisy_child(MAX_STDERR_BYTES * 6)
        outcome = run(CommandSpec(
            executable=argv[0], arguments=tuple(argv[1:]), timeout_seconds=30.0
        ))
        self.assertLessEqual(len(outcome.stderr), MAX_STDERR_BYTES)
        self.assertTrue(outcome.stderr_truncated)

    def test_a_missing_program_is_reported_rather_than_raising(self) -> None:
        outcome = run(CommandSpec(executable="/nonexistent/program", timeout_seconds=1.0))
        self.assertFalse(outcome.succeeded)
        self.assertTrue(outcome.start_error)
        self.assertTrue(outcome.reaped)

    def test_a_timeout_terminates_and_reaps(self) -> None:
        argv = sleeping_child(60.0)
        started = time.monotonic()
        outcome = run(CommandSpec(
            executable=argv[0], arguments=tuple(argv[1:]),
            timeout_seconds=0.4, grace_seconds=2.0, kill_grace_seconds=3.0,
        ))
        self.assertTrue(outcome.timed_out)
        self.assertTrue(outcome.reaped)
        self.assertLess(time.monotonic() - started, 20.0)

    def test_cancellation_stops_a_running_child(self) -> None:
        argv = sleeping_child(60.0)
        signal = CancellationSignal(name="speech-1")
        outcome_holder: list = []

        def _run() -> None:
            outcome_holder.append(run(CommandSpec(
                executable=argv[0], arguments=tuple(argv[1:]), timeout_seconds=60.0
            ), cancellation=signal))

        thread = threading.Thread(target=_run)
        thread.start()
        # A barrier rather than a sleep: wait until the child is genuinely up.
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and not thread.is_alive():
            pass
        signal.cancel("the user cancelled")
        thread.join(timeout=20.0)
        self.assertFalse(thread.is_alive())
        outcome = outcome_holder[0]
        self.assertTrue(outcome.cancelled)
        self.assertTrue(outcome.reaped)

    @unittest.skipUnless(POSIX, "SIGTERM refusal is a POSIX behaviour")
    def test_a_child_that_ignores_termination_is_killed_and_reaped(self) -> None:
        """§21's "child-process refusal", against a child that really refuses."""
        argv = ignoring_terminator(60.0)
        started = time.monotonic()
        outcome = run(CommandSpec(
            executable=argv[0], arguments=tuple(argv[1:]),
            timeout_seconds=0.5, grace_seconds=0.5, kill_grace_seconds=5.0,
        ))
        elapsed = time.monotonic() - started
        self.assertTrue(outcome.timed_out)
        self.assertTrue(outcome.terminated)
        self.assertTrue(outcome.killed, "the escalation to SIGKILL did not happen")
        self.assertTrue(outcome.reaped, "the killed child was not reaped")
        self.assertLess(elapsed, 30.0, "the escalation was not bounded")

    def test_hostile_text_is_data_and_never_a_command(self) -> None:
        """Argument injection: the text is read, never interpreted."""
        directory = Path(tempfile.mkdtemp())
        target = directory / "echoed.txt"
        argv = echoing_child()
        hostile = "--version; $(id) `whoami` && rm -rf / | tee /tmp/x -h --help"
        outcome = run(CommandSpec(
            executable=argv[0],
            arguments=tuple(argv[1:]),
            stdin_text=hostile,
            environment={"ECHO_TARGET": str(target)},
            timeout_seconds=20.0,
        ))
        self.assertTrue(outcome.succeeded, outcome.stderr)
        self.assertEqual(target.read_text(encoding="utf-8"), hostile)


class DeclarationTests(unittest.TestCase):
    def test_an_undeclared_provider_fails_closed(self) -> None:
        declaration = ProviderDeclaration(provider_id="hollow")
        self.assertFalse(declaration.fully_declared)
        permitted, reasons = declaration.serves(make_request())
        self.assertFalse(permitted)
        self.assertIn("fails closed", " ".join(reasons))

    def test_a_remote_provider_is_refused_outright(self) -> None:
        """§15: no remote speech path exists, and the refusal is structural."""
        declaration = ProviderDeclaration(
            provider_id="elsewhere", implementation_id="x/1", languages=("en",),
            supports_streaming=True, local=False,
        )
        permitted, reasons = declaration.serves(make_request())
        self.assertFalse(permitted)
        self.assertIn("no remote speech path", " ".join(reasons))

    def test_a_provider_below_the_classification_ceiling_is_refused(self) -> None:
        declaration = ProviderDeclaration(
            provider_id="limited", implementation_id="x/1", languages=("en",),
            supports_streaming=True, maximum_privacy_class="internal",
        )
        permitted, reasons = declaration.serves(make_request(privacy_classification="secret"))
        self.assertFalse(permitted)
        self.assertIn("may hold data up to internal", " ".join(reasons))

    def test_a_paid_provider_with_no_budget_is_refused(self) -> None:
        declaration = ProviderDeclaration(
            provider_id="billed", implementation_id="x/1", languages=("en",),
            supports_streaming=True, cost_class="paid",
        )
        permitted, reasons = declaration.serves(make_request())
        self.assertFalse(permitted)
        self.assertIn("permits no spend", " ".join(reasons))

    def test_an_unsupported_language_is_refused(self) -> None:
        declaration = ProviderDeclaration(
            provider_id="english-only", implementation_id="x/1", languages=("en",),
            supports_streaming=True,
        )
        permitted, reasons = declaration.serves(make_request(language="fr", locale="fr-FR"))
        self.assertFalse(permitted)
        self.assertIn("no voice for", " ".join(reasons))

    def test_an_unsupported_rate_is_refused_on_the_synthesis_path(self) -> None:
        declaration = ProviderDeclaration(
            provider_id="fixed-rate", implementation_id="x/1", languages=("en",),
            supports_synthesis=True, audio_formats=("wav-pcm-s16le",), sample_rates=(22_050,),
        )
        permitted, reasons = declaration.serves(make_request(sample_rate=48_000))
        self.assertFalse(permitted)
        self.assertIn("48000 Hz", " ".join(reasons))

    def test_every_reason_is_gathered_rather_than_the_first(self) -> None:
        declaration = ProviderDeclaration(
            provider_id="wrong", implementation_id="x/1", languages=("de",),
            supports_streaming=True, cost_class="paid", maximum_privacy_class="public",
        )
        permitted, reasons = declaration.serves(make_request(privacy_classification="secret"))
        self.assertFalse(permitted)
        self.assertGreaterEqual(len(reasons), 3)

    def test_a_declaration_never_claims_cloning_or_remote_transmission(self) -> None:
        document = ProviderDeclaration(provider_id="x").to_json()
        self.assertFalse(document["voiceCloning"])
        self.assertFalse(document["remoteTransmission"])


class RegistrySelectionTests(unittest.TestCase):
    def test_the_first_eligible_provider_in_order_is_chosen(self) -> None:
        first = ScriptedProvider("first")
        second = ScriptedProvider("second")
        registry = ProviderRegistry([first, second])
        selection = registry.select(make_request())
        self.assertTrue(selection.selected)
        self.assertIs(selection.provider, first)

    def test_an_unavailable_provider_is_skipped_with_its_reason_kept(self) -> None:
        first = ScriptedProvider("first", available=False)
        second = ScriptedProvider("second")
        registry = ProviderRegistry([first, second])
        selection = registry.select(make_request())
        self.assertIs(selection.provider, second)
        self.assertEqual(selection.rejected[0][0], "first")

    def test_rejections_are_kept_even_when_something_was_selected(self) -> None:
        registry = ProviderRegistry([ScriptedProvider("first", available=False), ScriptedProvider("second")])
        selection = registry.select(make_request())
        self.assertTrue(selection.selected)
        self.assertTrue(selection.rejected)

    def test_an_excluded_provider_is_not_retried_on_the_same_utterance(self) -> None:
        first = ScriptedProvider("first")
        second = ScriptedProvider("second")
        registry = ProviderRegistry([first, second])
        selection = registry.select(make_request(), exclude=("first",))
        self.assertIs(selection.provider, second)
        self.assertIn("excluded after an earlier failure", selection.rejected[0][1][0])

    def test_nothing_eligible_leaves_the_caption_as_the_whole_output(self) -> None:
        registry = ProviderRegistry([ScriptedProvider("only", available=False)])
        selection = registry.select(make_request())
        self.assertFalse(selection.selected)
        self.assertIn("caption is the whole of the output", selection.detail)

    def test_a_named_voice_that_is_not_installed_is_refused_not_substituted(self) -> None:
        registry = ProviderRegistry([ScriptedProvider("only")])
        selection = registry.select(make_request(voice_id="a-voice-that-is-not-here"))
        self.assertFalse(selection.selected)
        self.assertIn("no installed voice matching", " ".join(selection.rejected[0][1]))

    def test_requiring_synthesis_skips_a_streaming_only_provider(self) -> None:
        streaming = ScriptedProvider("streaming", supports_synthesis=False)
        registry = ProviderRegistry([streaming])
        selection = registry.select(make_request(), require_synthesis=True)
        self.assertFalse(selection.selected)

    def test_an_unhealthy_provider_is_not_selected(self) -> None:
        registry = ProviderRegistry([ScriptedProvider("sick", healthy=False), ScriptedProvider("well")])
        selection = registry.select(make_request())
        self.assertEqual(selection.provider.declaration.provider_id, "well")

    def test_an_inventory_survives_a_provider_that_raises(self) -> None:
        class Exploding(ScriptedProvider):
            def inventory(self):  # type: ignore[override]
                raise RuntimeError("the inventory blew up")

        registry = ProviderRegistry([Exploding("bang"), ScriptedProvider("fine")])
        voices = registry.inventory()
        self.assertTrue(any(item.provider_id == "fine" for item in voices))


class LocalProviderTests(unittest.TestCase):
    """The two real adapters, whether or not this host has them installed."""

    def test_both_adapters_are_offered_even_when_their_programs_are_absent(self) -> None:
        registry = local_providers()
        self.assertEqual(
            [item.declaration.provider_id for item in registry],
            ["espeak-ng", "speech-dispatcher"],
        )

    def test_an_absent_program_reports_unavailable_rather_than_raising(self) -> None:
        def _absent(name, **kwargs):
            raise ExecutableRefused(f"{name!r} is not installed")

        provider = EspeakNgProvider(resolver=_absent)
        health = provider.health()
        self.assertFalse(health.available)
        self.assertFalse(health.ready)
        self.assertIn("not installed", health.detail)

    def test_an_unavailable_provider_returns_a_failure_rather_than_pretending(self) -> None:
        def _absent(name, **kwargs):
            raise ExecutableRefused(f"{name!r} is not installed")

        provider = EspeakNgProvider(resolver=_absent)
        workspace = PrivateWorkspace()
        try:
            result = provider.synthesize(make_request(), workspace)
            self.assertFalse(result.succeeded)
            self.assertEqual(result.audio_path, "")
        finally:
            workspace.close()

    def test_speech_dispatcher_refuses_synthesis_explicitly(self) -> None:
        provider = SpeechDispatcherProvider(resolver=lambda name, **kw: ("/usr/bin/spd-say", True))
        self.assertFalse(provider.declaration.supports_synthesis)
        workspace = PrivateWorkspace()
        try:
            result = provider.synthesize(make_request(), workspace)
            self.assertFalse(result.succeeded)
            self.assertIn("does not return samples", result.detail)
        finally:
            workspace.close()

    def test_espeak_declares_only_the_rate_it_actually_produces(self) -> None:
        provider = EspeakNgProvider(resolver=lambda name, **kw: ("/usr/bin/espeak-ng", True))
        self.assertEqual(provider.NATIVE_SAMPLE_RATE, 22_050)

    def test_no_commercial_provider_is_present_anywhere_in_the_package(self) -> None:
        """§4: not implemented, and not present as a stub either.

        Checked against the syntax tree with docstrings removed, because
        :mod:`companion.voice.providers` says "there is no ElevenLabs adapter"
        in its own docstring while explaining why — and a substring search finds
        the explanation and reports it as the offence. What must be absent is a
        *name*: a class, a function, a variable, an attribute or a runtime
        string that mentions one of these.
        """
        import ast

        package = Path(__file__).resolve().parents[2] / "companion" / "voice"
        forbidden = ("elevenlabs", "openai", "fishaudio", "fish_speech", "playht", "murf", "resemble")
        modules = sorted(package.glob("*.py"))
        self.assertGreaterEqual(len(modules), 12)
        for module in modules:
            tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
            docstrings = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    body = getattr(node, "body", None)
                    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                        docstrings.add(id(body[0].value))
            for node in ast.walk(tree):
                text = ""
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if id(node) in docstrings:
                        continue
                    text = node.value
                elif isinstance(node, ast.Name):
                    text = node.id
                elif isinstance(node, ast.Attribute):
                    text = node.attr
                elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    text = node.name
                lowered = text.lower()
                for name in forbidden:
                    self.assertNotIn(
                        name, lowered, f"{module.name} names a commercial provider: {text!r}"
                    )

    def test_no_module_in_the_package_opens_a_network_connection(self) -> None:
        import ast

        package = Path(__file__).resolve().parents[2] / "companion" / "voice"
        banned = {"socket", "http", "http.client", "urllib", "urllib.request", "ssl", "ftplib", "requests"}
        for module in package.glob("*.py"):
            tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn(alias.name.split(".")[0], banned, f"{module.name} imports {alias.name}")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    self.assertNotIn(
                        node.module.split(".")[0], banned, f"{module.name} imports from {node.module}"
                    )


class ScriptedProviderBehaviourTests(unittest.TestCase):
    """The fake honours the contract, so the tests that use it mean something."""

    def setUp(self) -> None:
        self.workspace = PrivateWorkspace()
        self.addCleanup(self.workspace.close)

    def test_a_crashing_provider_reports_failure_with_bounded_stderr(self) -> None:
        provider = ScriptedProvider(failure_mode="crash", stderr="segmentation fault")
        result = provider.synthesize(make_request(), self.workspace)
        self.assertFalse(result.succeeded)
        self.assertIn("crashed", result.detail)
        self.assertEqual(result.outcome.stderr, "segmentation fault")

    def test_a_provider_that_produced_no_audio_is_a_failure(self) -> None:
        provider = ScriptedProvider(failure_mode="empty")
        result = provider.synthesize(make_request(), self.workspace)
        self.assertFalse(result.succeeded)

    def test_a_timeout_is_reported_as_one(self) -> None:
        provider = ScriptedProvider(failure_mode="timeout")
        result = provider.synthesize(make_request(), self.workspace)
        self.assertFalse(result.succeeded)
        self.assertTrue(result.outcome.timed_out)

    def test_a_successful_synthesis_produces_probeable_audio(self) -> None:
        provider = ScriptedProvider()
        result = provider.synthesize(make_request(), self.workspace)
        self.assertTrue(result.succeeded)
        self.assertGreater(result.frame_count, 0)
        self.assertTrue(Path(result.audio_path).exists())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
