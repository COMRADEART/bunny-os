from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from bunny_shell.launcher import LauncherState, parse_desktop_entry, route_intent


class LauncherTests(unittest.TestCase):
    def entry(self, body: str) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "sample.desktop"
        path.write_text(body, encoding="utf-8")
        return path

    def test_valid_application_entry(self) -> None:
        app = parse_desktop_entry(self.entry("[Desktop Entry]\nType=Application\nName=Editor\nExec=/usr/bin/editor %F\nTerminal=false\n"))
        self.assertEqual(app.argv, ("/usr/bin/editor",))

    def test_malicious_desktop_entry_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_desktop_entry(self.entry("[Desktop Entry]\nType=Application\nName=Bad\nExec=/bin/sh -c 'touch /tmp/pwn'\n"))

    def test_unsafe_url_handler_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "URL handler"):
            parse_desktop_entry(self.entry("[Desktop Entry]\nType=Application\nName=Bad URL\nExec=/usr/bin/viewer\nMimeType=x-scheme-handler/bad;\n"))

    def test_broker_action_is_typed_and_confirmed(self) -> None:
        intent = route_intent("Check for system updates")
        self.assertEqual(intent.type, "system_action")
        self.assertTrue(intent.requiresBrokerPermission)
        self.assertTrue(intent.requiresConfirmation)

    def test_bunny_prompt_cannot_name_a_broker_method(self) -> None:
        intent = route_intent("Ask Bunny to reboot the computer")
        self.assertEqual(intent.type, "bunny_request")
        self.assertFalse(intent.requiresBrokerPermission)

    def test_ambiguous_input_falls_back_to_search(self) -> None:
        self.assertEqual(route_intent("blue rabbit notes").type, "search")

    def test_pin_and_recent_state_is_bounded_and_persistent(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        state = LauncherState(Path(temporary.name) / "launcher.json")
        state.pin("org.example.Editor.desktop")
        state.record_launch("org.example.Editor.desktop")
        reloaded = LauncherState(Path(temporary.name) / "launcher.json").get()
        self.assertEqual(reloaded["pinned"], ["org.example.Editor.desktop"])
        self.assertEqual(reloaded["recent"], ["org.example.Editor.desktop"])

    def test_invalid_pin_id_is_rejected(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        with self.assertRaises(ValueError):
            LauncherState(Path(temporary.name) / "launcher.json").pin("../../bad.desktop")


if __name__ == "__main__":
    unittest.main()
