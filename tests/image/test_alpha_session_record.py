# SPDX-License-Identifier: GPL-3.0-or-later
"""The Alpha boot judge matches Bunny Shell's single-surface architecture."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "bunny_alpha_record", ROOT / "build/scripts/alpha-record.py"
)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - repository damage
    raise RuntimeError("could not load build/scripts/alpha-record.py")
ALPHA_RECORD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ALPHA_RECORD)


def session_results(enablement: str, runtime: str, window: str) -> dict[str, bool]:
    record = {
        "sections": {
            "units": {"userPreset": enablement},
            "session": {
                "processCounts": {
                    "runtime": runtime,
                    "window": window,
                    "terminals": "0",
                }
            },
        }
    }
    return {
        item["assertion"]: item["held"]
        for item in ALPHA_RECORD.assertions(record, offline=False)
    }


class AlphaSessionRecordTests(unittest.TestCase):
    def test_runtime_enabled_without_legacy_window_passes(self) -> None:
        results = session_results("enabled\ndisabled\n", "1", "0")
        self.assertTrue(results["session.runtime-enabled-window-not-autostarted"])
        self.assertTrue(results["session.runtime-only-no-companion-window"])

    def test_autostarted_companion_window_is_rejected(self) -> None:
        results = session_results("enabled\nenabled\n", "1", "1")
        self.assertFalse(results["session.runtime-enabled-window-not-autostarted"])
        self.assertFalse(results["session.runtime-only-no-companion-window"])

    def test_missing_runtime_process_is_rejected(self) -> None:
        results = session_results("enabled\ndisabled\n", "0", "0")
        self.assertFalse(results["session.runtime-only-no-companion-window"])


if __name__ == "__main__":
    unittest.main()
