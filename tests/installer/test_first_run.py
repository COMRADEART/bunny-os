from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from installer.first_run.state import DEFAULTS, FirstRunState, validate_hostname, validate_username


class FirstRunTests(unittest.TestCase):
    def test_privacy_defaults_are_off_or_empty(self) -> None:
        self.assertFalse(DEFAULTS["telemetry"])
        self.assertFalse(DEFAULTS["cloudAIConfigured"])
        self.assertFalse(DEFAULTS["screenAccess"])
        self.assertEqual(DEFAULTS["searchLocations"], [])

    def test_state_resumes_and_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "first-run.json"
            state = FirstRunState(path)
            state.update(step="privacy", values={"telemetry": False})
            state.save()
            resumed = FirstRunState(path)
            self.assertEqual(resumed.load()["currentStep"], "privacy")
            resumed.finish()
            self.assertTrue(FirstRunState(path).load()["completed"])
            self.assertTrue(path.with_name("first-run-complete").is_file())

    def test_secret_values_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = FirstRunState(Path(directory) / "state.json")
            with self.assertRaises(ValueError):
                state.update(step="provider_setup", values={"apiKey": "secret"})

    def test_entire_home_cannot_be_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = FirstRunState(Path(directory) / "state.json")
            with self.assertRaises(ValueError):
                state.update(step="search_locations", values={"searchLocations": [str(Path.home())]})

    def test_username_rules(self) -> None:
        self.assertTrue(validate_username("alice-1"))
        self.assertFalse(validate_username("root"))
        self.assertFalse(validate_username("Alice"))

    def test_hostname_avoids_invalid_names(self) -> None:
        self.assertTrue(validate_hostname("bunny-laptop"))
        self.assertFalse(validate_hostname("Bunny Laptop"))
