#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Flip the two accessibility FAIL rows on the strength of new evidence.

This is the §7 closure step, and it refuses to run on wishes: it reads the
runtime evidence JSON produced by the sweep on the subject artifact, asserts
the §8 requirements *numerically* — the intended requirement, not "the UI
appeared" — and only then rewrites the two rows in
``operations/data/qualification-matrices.json``, validated through
``release.matrix.parse_result`` like every other row.

Assertions before any row moves — each measuring the *intended requirement*:
  * the guest read back every setting it wrote;
  * text-scaling: the direct measurement is AT-SPI control geometry — the
    comparison must be conclusive, controls must have grown and none shrunk;
    the pixel share corroborates at more than 3x the run's own noise floor;
  * high-contrast: the theme must replace the ground — more than half the
    screen changes, and more than 10x the noise floor;
  * a noise floor exists, from a control shot at restored settings. This
    run's floor is dominated by the live Companion animation and the system
    gauges — named, not hidden; the diff mask is part of the evidence.

If any assertion fails, nothing is written and the rows stay FAIL.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from release.matrix import parse_result  # noqa: E402

EVIDENCE = Path(__file__).resolve().parent / "evidence" / "a11y-e906a48793d7" / "accessibility.json"
MATRICES = ROOT / "operations" / "data" / "qualification-matrices.json"
ARTIFACT = "e906a48793d7"


def main() -> int:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    measurements = evidence.get("measurements") or {}
    noise = measurements.get("noiseFloorShare")
    comparisons = {c.get("screenshot"): c for c in measurements.get("comparisons", [])}

    problems: list[str] = []
    if not isinstance(noise, (int, float)) or noise <= 0:
        problems.append("no noise floor was measured")
        noise = None

    def share(name: str):
        entry = comparisons.get(name)
        return None if entry is None else entry.get("shareOfScreen")

    text = share("a11y-03-large-text")
    contrast = share("a11y-04-high-contrast")
    if noise is not None:
        if not text or text < 3 * noise:
            problems.append(f"text-scaling 1.5 moved {text!r} of the screen against noise {noise!r}; not a pass")
        if not contrast or contrast < 10 * noise or contrast < 0.5:
            problems.append(f"high-contrast moved {contrast!r} against noise {noise!r}; not a theme switch")

    growth = measurements.get("atSpiControlGrowth") or {}
    if not (
        growth.get("conclusive") is True
        and (growth.get("grewCount") or 0) > 0
        and growth.get("shrankCount") == 0
    ):
        problems.append(f"AT-SPI control geometry is not conclusive growth: {growth}")

    if measurements.get("settingsReadBack") is not True:
        problems.append("the guest did not read back the settings it wrote")

    if problems:
        print("REFUSED — the evidence does not support flipping the rows:")
        for p in problems:
            print(f"  - {p}")
        return 4

    recorded_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    reference = str(EVIDENCE.relative_to(ROOT)).replace("\\", "/")
    base_note = (
        f"Driven in a booted guest of the subject artifact ({ARTIFACT}, image "
        f"sha256:c87a6616..., 1920x1080, llvmpipe). The preference was set via the guest's "
        f"own gsettings, read back, and the screen photographed; a control screenshot at "
        f"restored settings measures the run's own noise floor ({noise:.2%} of the screen, "
        f"dominated by the live Companion animation and system gauges - localised in "
        f"noise-mask.png, not hidden). "
    )
    rows = {
        "text-scaling": base_note + (
            f"The direct measurement is AT-SPI control geometry: at 1.5x, "
            f"{growth.get('grewCount')} of {growth.get('controlsComparable')} comparable "
            f"controls grew and none shrank (conclusive). The screen corroborates: "
            f"{text:.1%} changed ({text / noise:.1f}x the noise floor). The mechanism is "
            "the generated stylesheet - every font size is a theme value multiplied by "
            "the scale; tests/shell/test_design_system.py::"
            "test_no_font_size_survives_a_change_of_scale fails if that is removed."
        ),
        "high-contrast": base_note + (
            f"high-contrast changed {contrast:.1%} of the screen "
            f"({contrast / noise:.1f}x the noise floor): the wallpaper is replaced by the "
            "theme's opaque ground, borders replace shadows, and the palette switches to "
            "the high-contrast theme (tests/shell/test_companion_surfaces.py::"
            "test_high_contrast_exists_as_a_theme_rather_than_a_wish and the "
            "contrast-pair gate fail if that is removed). Observed limitation, recorded "
            "not hidden: the first-run GTK dialog keeps its GTK theme; the shell is what "
            "this scenario measures."
        ),
    }

    document = json.loads(MATRICES.read_text(encoding="utf-8"))
    matrix = document["matrices"]["accessibility"]
    for row in matrix:
        scenario = row.get("scenario")
        if scenario in rows:
            row.update({
                "outcome": "PASS",
                "method": "virtual-machine",
                "evidenceReference": reference,
                "recordedAt": recorded_at,
                "notes": rows[scenario],
            })
            parse_result("accessibility", row, root=ROOT)
            print(f"PASS {scenario}")
    MATRICES.write_text(
        json.dumps(document, indent=1, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )
    print("rows written; regenerate reports with scripts/write_qualification_reports.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
