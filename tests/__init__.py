"""Bunny OS validation suite."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
for source in (
    ROOT / "services/bunny-system-broker/src",
    ROOT / "services/bunny-update-agent",
    ROOT / "tools/bunny-os",
    ROOT / "shell/services",
):
    sys.path.insert(0, str(source))
