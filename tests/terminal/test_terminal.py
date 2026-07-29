from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from bunny_shell.terminal import classify, propose


class TerminalTests(unittest.TestCase):
    def test_read_only_command(self) -> None:
        self.assertEqual(classify("git status")[0], "read_only")

    def test_workspace_write(self) -> None:
        self.assertEqual(classify("git add README.md")[0], "workspace_write")

    def test_network_action(self) -> None:
        self.assertEqual(classify("npm install")[0], "network_action")

    def test_system_change(self) -> None:
        self.assertEqual(classify("systemctl enable example.service")[0], "system_change")

    def test_destructive_command(self) -> None:
        self.assertEqual(classify("rm -rf build/output")[0], "destructive")

    def test_unknown_and_shell_command_are_high_risk(self) -> None:
        self.assertEqual(classify("mystery-tool --go")[0], "unknown")
        self.assertEqual(classify("sh -c 'ls'")[0], "unknown")

    def test_substitution_is_unknown(self) -> None:
        self.assertEqual(classify("echo $(rm file)")[0], "unknown")

    def test_redirection_is_not_read_only(self) -> None:
        self.assertEqual(classify("echo hello > output.txt")[0], "workspace_write")

    def test_proposal_never_executes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            value = propose("rm file", temporary)
        self.assertFalse(value.executesAutomatically)
        self.assertTrue(value.editable)
        self.assertTrue(value.requiresApproval)
        self.assertTrue(value.checkpointRequired)

    def test_environment_change_is_visible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            value = propose("MODE=test make", temporary)
        self.assertEqual(value.environmentChanges, {"MODE": "test"})


if __name__ == "__main__":
    unittest.main()
