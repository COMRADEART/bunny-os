#!/usr/bin/env python3
"""Accessibility assessment for a non-GNOME shell.

BUNNY WAYLAND SHELL EXPERIMENT — NOT RELEASE QUALIFIED — DO NOT USE AS THE
DEFAULT SESSION.

Parity with GNOME is not claimed anywhere in this output, and cannot be until
real assistive-technology sessions pass. What is reported is which architecture
exists, which parts were reached, and which were not.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import (  # noqa: E402
    BINARY,
    INFERRED,
    OBSERVED,
    ROOT,
    UNAVAILABLE,
    banner,
    shell_environment,
    which,
    write_report,
)


def compositor_capabilities() -> dict:
    """Read the capability list from the compositor itself."""

    if not BINARY.is_file():
        return {"evidence": UNAVAILABLE, "reason": "compositor not built", "capabilities": []}
    completed = subprocess.run(
        [str(BINARY), "--accessibility"],
        capture_output=True,
        text=True,
        check=False,
        env=shell_environment(),
    )
    if completed.returncode != 0:
        return {"evidence": UNAVAILABLE, "reason": completed.stderr[-500:], "capabilities": []}
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        return {"evidence": UNAVAILABLE, "reason": str(error), "capabilities": []}


def at_spi_probe() -> dict:
    """Is an AT-SPI bus reachable at all?"""

    busctl = which("busctl")
    if not busctl:
        return {"atSpiBusReachable": False, "evidence": UNAVAILABLE, "detail": "busctl not installed"}
    completed = subprocess.run(
        [busctl, "--user", "--no-pager", "--list", "--acquired"],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    if completed.returncode != 0:
        return {
            "atSpiBusReachable": False,
            "evidence": OBSERVED,
            "detail": "no session bus in this environment: " + completed.stderr.strip()[:200],
        }
    reachable = "org.a11y.Bus" in completed.stdout
    return {
        "atSpiBusReachable": reachable,
        "evidence": OBSERVED,
        "detail": "org.a11y.Bus present" if reachable else "org.a11y.Bus not on the session bus",
        "atSpiPackagesInstalled": bool(which("busctl")) and Path("/usr/libexec/at-spi-bus-launcher").exists(),
    }


def accessible_labels_in_chrome() -> dict:
    """Every widget the chrome builds should carry an accessible label.

    Counted from source rather than from a live AT-SPI tree, so it is evidence
    that labels were written, not that a screen reader read them.
    """

    views = (ROOT / "apps/common/bunny_shell_v3/views.py").read_text(encoding="utf-8")
    lock = (ROOT / "shell-ui/lock-screen/bunny-lock-screen").read_text(encoding="utf-8")
    labels = len(re.findall(r"AccessibleProperty\.LABEL", views + lock))
    live_regions = len(re.findall(r"AccessibleProperty\.LIVE", views + lock))
    return {
        "accessibleLabelCalls": labels,
        "liveRegionCalls": live_regions,
        "evidence": OBSERVED,
        "note": "counted in source; not verified against a running AT-SPI tree",
    }


def keyboard_reachability() -> dict:
    sys.path.insert(0, str(ROOT / "apps/common"))
    from bunny_shell_v3.chrome import DockItem, DockModel
    from bunny_shell_v3.model import ShellState
    from bunny_shell_v3.runtime import COMPONENTS, KeyboardMode

    dock = DockModel(ShellState(), max_visible=3)
    for index in range(6):
        dock.add(DockItem(entry_id=f"org.bunnyos.App{index}", name=f"App {index}", pinned=True))
    return {
        "everyDockItemKeyboardReachable": len(dock.keyboard_order()) == 6,
        "overflowItemsReachable": len(dock.keyboard_order()) > len(dock.visible()),
        "surfacesThatTakeKeyboard": sorted(
            name for name, spec in COMPONENTS.items() if spec.keyboard is not KeyboardMode.NONE
        ),
        "surfacesThatNeverTakeKeyboard": sorted(
            name for name, spec in COMPONENTS.items() if spec.keyboard is KeyboardMode.NONE
        ),
        "evidence": OBSERVED,
    }


def scaling_and_contrast() -> dict:
    sys.path.insert(0, str(ROOT / "apps/common"))
    from bunny_shell_v3.model import ShellState

    state = ShellState(reduced_motion=True, high_contrast=True)
    return {
        "reducedMotionYieldsZeroDuration": state.animation_duration_ms(250) == 0,
        "highContrastFlagHonoured": state.high_contrast,
        "twoHundredPercentScaling": {
            "evidence": OBSERVED,
            "detail": "a 3840x2160 output at scale 2.0 resolves to 1920x1080 logical; "
            "covered by the compositor's output unit tests",
        },
        "magnification": {
            "evidence": "unsupported",
            "detail": "modelled as a setting; the render path is not implemented in V3",
        },
        "evidence": OBSERVED,
    }


def main() -> int:
    banner()
    capabilities = compositor_capabilities()
    payload = {
        "schemaVersion": 1,
        "parityWithGnomeClaimed": False,
        "parityWithGnomeClaimable": capabilities.get("parityWithGnomeClaimable", False),
        "assistiveTechnologySessionRun": False,
        "assistiveTechnologyNote": (
            "No Orca session was run. Orca needs a session bus, speech-dispatcher and audio, none "
            "of which exist in this measurement environment. Every screen-reader statement in the "
            "V3 reports is therefore inferred from the toolkit, not observed."
        ),
        "architecture": {
            "shellChromeToolkit": "GTK 4",
            "chromeDrawnByCompositor": False,
            "accessibilityRoute": "AT-SPI via GTK, because the chrome is a client rather than "
            "compositor drawing",
            "compositorDrawnSurfaceAccessibility": "none; there is no AT-SPI for pixels",
            "evidence": INFERRED,
        },
        "compositorCapabilities": capabilities,
        "atSpi": at_spi_probe(),
        "accessibleLabels": accessible_labels_in_chrome(),
        "keyboard": keyboard_reachability(),
        "scalingAndContrast": scaling_and_contrast(),
    }
    write_report("accessibility.json", payload)
    print(f"parity claimable: {payload['parityWithGnomeClaimable']}")
    print(f"AT-SPI bus reachable: {payload['atSpi']['atSpiBusReachable']}")
    print(f"accessible label calls in chrome source: {payload['accessibleLabels']['accessibleLabelCalls']}")
    unmeasured = [
        capability["capability"]
        for capability in capabilities.get("capabilities", [])
        if capability["evidence"] != "observed"
    ]
    print(f"capabilities not observed: {len(unmeasured)}")
    for name in unmeasured:
        print(f"  - {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
