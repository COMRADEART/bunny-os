from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tests.support import ROOT


class AccessibilityTests(unittest.TestCase):
    def test_ui_has_programmatic_labels_and_keyboard_activation(self) -> None:
        source = (ROOT / "shell/services/bunny_shell/ui.py").read_text(encoding="utf-8")
        self.assertIn("AccessibleProperty.LABEL", source)
        self.assertIn("row-activated", source)

    def test_focus_is_visible_in_all_owned_themes(self) -> None:
        """Every theme, rendered, with a focus ring on every reactive class.

        This used to read three nine-line files in `shell/themes/` and check for
        the string ":focus-visible". Those files were installed to
        `/usr/share/bunny-shell/themes` and loaded by nothing — the check passed
        against CSS no display server had ever parsed. The themes are rendered
        from tokens now, so the same question can be asked of the actual output,
        for all four themes, against the actual list of focusable classes.
        """
        if not shutil.which("node"):
            self.skipTest("node is unavailable on this host")

        design = ROOT / "shell/components/gnome-shell-extension/lib/design"
        script = (
            f"import {{resolveTheme}} from '{(design / 'theme.js').as_uri()}';\n"
            f"import {{renderStylesheet, REACTIVE_CLASSES}} from '{(design / 'stylesheet.js').as_uri()}';\n"
            "const missing = {};\n"
            "for (const scheme of ['light', 'dark'])\n"
            "  for (const highContrast of [false, true]) {\n"
            "    const theme = resolveTheme({scheme, highContrast});\n"
            "    const css = renderStylesheet(theme);\n"
            "    const absent = REACTIVE_CLASSES.filter(c => !css.includes(`.${c}:focus`));\n"
            "    if (absent.length) missing[theme.name] = absent;\n"
            "  }\n"
            "console.log(JSON.stringify(missing));\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / "probe.mjs"
            probe.write_text(script, encoding="utf-8")
            result = subprocess.run(
                [shutil.which("node"), str(probe)],
                capture_output=True, text=True, check=False, cwd=str(ROOT))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout.strip()), {})

    def test_reduced_motion_and_text_scale_are_real_settings(self) -> None:
        source = (ROOT / "shell/services/bunny_shell/settings.py").read_text(encoding="utf-8")
        self.assertIn('"reducedMotion"', source)
        self.assertIn('"textScalePercent"', source)


if __name__ == "__main__":
    unittest.main()
