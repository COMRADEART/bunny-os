from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from tests.support import ROOT


SHELL = ROOT / "shell/bunny-desktop-v2"


class ShellSecurityAndPerformanceTests(unittest.TestCase):
    def test_palette_never_executes_query_text(self) -> None:
        palette = (SHELL / "components/commandPalette.js").read_text(encoding="utf-8")
        self.assertNotRegex(palette, r"spawn|Subprocess|eval\(|Function\(")
        self.assertIn("commandActions", palette)
        self.assertIn("Search text is never executed", palette)

    def test_only_fixed_action_service_launches_processes(self) -> None:
        matches = []
        for path in SHELL.rglob("*.js"):
            if "Gio.Subprocess.new" in path.read_text(encoding="utf-8"):
                matches.append(path.relative_to(SHELL).as_posix())
        self.assertEqual(matches, ["services/fixedActions.js"])
        fixed = (SHELL / "services/fixedActions.js").read_text(encoding="utf-8")
        self.assertIn("FIXED_ACTIONS", fixed)
        self.assertIn("throw new Error", fixed)

    def test_mock_mode_is_continuously_labelled_and_decisions_are_inert(self) -> None:
        top = (SHELL / "components/topBar.js").read_text(encoding="utf-8")
        panel = (SHELL / "components/systemPanel.js").read_text(encoding="utf-8")
        approval = (SHELL / "components/approvalPanel.js").read_text(encoding="utf-8")
        runtime = (ROOT / "apps/common/bunny_visual_v2/runtime.py").read_text(encoding="utf-8")
        self.assertIn("VISUAL MOCK DATA", top)
        self.assertIn("VISUAL MOCK DATA", panel)
        self.assertIn("mockMode ? false", (SHELL / "services/state.js").read_text(encoding="utf-8"))
        self.assertIn('"decisionAvailable": False if is_mock', runtime)
        self.assertIn("decisionAvailable", approval)

    def test_shell_is_event_driven_and_has_no_timer_polling(self) -> None:
        sources = "\n".join(path.read_text(encoding="utf-8") for path in SHELL.rglob("*.js"))
        self.assertNotRegex(sources, r"setInterval|timeout_add|setTimeout")
        self.assertIn("monitor_directory", sources)

    def test_performance_audit_executes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "performance.json"
            result = subprocess.run(
                [sys.executable, str(ROOT / "visual-v2/tools/performance_audit.py"), "--output", str(output)],
                cwd=ROOT, text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            audit = json.loads(output.read_text(encoding="utf-8"))
        self.assertTrue(audit["passed"])
        self.assertFalse(audit["liveShellMeasurementsAvailable"])

    def test_performance_recorder_is_bounded_and_targeted(self) -> None:
        source = (SHELL / "services/performance.js").read_text(encoding="utf-8")
        self.assertIn("MAX_RECORDS = 32", source)
        for target in ("command-palette-open", "quick-settings-open", "assistant-panel-open", "visual-mode-switch"):
            self.assertIn(target, source)


if __name__ == "__main__":
    unittest.main()
