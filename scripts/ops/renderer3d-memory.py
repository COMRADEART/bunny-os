#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§35's memory figures, taken one stage at a time in separate processes.

A development tool, not shipped.

§35 asks for the renderer, GTK, the Bunny runtime and a local model server to be
reported separately, and the only way to do that honestly is to measure a
process that contains one of them. So each stage below runs in its own
interpreter, reports its own RSS and PSS, and exits — rather than one process
importing everything and attributing the total to whichever component was added
last.

PSS as well as RSS because they answer different questions on a machine where
Mesa maps a hundred megabytes of shared driver: RSS counts every resident page
the process can see, PSS divides shared pages by the number of processes sharing
them. For a single renderer they are close; for a desktop with four GTK
applications they are not, and quoting only RSS would over-attribute Mesa to
every one of them.

Usage::

    scripts/ops/renderer3d-memory.py --output evidence/renderer3d-memory.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

_ROOT = Path(__file__).resolve().parents[2]

_STAGES: dict[str, str] = {
    "bare-interpreter": """
""",
    "companion-runtime-imported": """
import companion.runtime, companion.service, companion.presentation
""",
    "three-d-imported": """
import companion.character.three_d.renderer
import companion.character.three_d.glb
""",
    "package-validated": """
from companion.character.defaults import default_3d_character_path
from companion.character.package import validate_package_directory
from companion.character.schema import PackageTrustState
package = validate_package_directory(
    default_3d_character_path(), trust_state=PackageTrustState.BUILT_IN
)
HOLD.append(package)
""",
    "context-created": """
from companion.character.three_d.context import SurfacelessContext
context = SurfacelessContext()
context.make_current()
HOLD.append(context)
""",
    "renderer-idle": """
from companion.character.defaults import default_3d_character_path
from companion.character.package import validate_package_directory
from companion.character.schema import PackageTrustState
from companion.character.three_d.context import SurfacelessContext
from companion.character.three_d.renderer import ThreeDRenderer
package = validate_package_directory(
    default_3d_character_path(), trust_state=PackageTrustState.BUILT_IN
)
context = SurfacelessContext()
renderer = ThreeDRenderer(context=context, seed=1)
renderer.load_package(package)
HOLD.extend((package, context, renderer))
""",
    "character-loaded": """
from companion.character.defaults import default_3d_character_path
from companion.character.package import validate_package_directory
from companion.character.schema import PackageTrustState
from companion.character.three_d.context import SurfacelessContext
from companion.character.three_d.renderer import ThreeDRenderer
package = validate_package_directory(
    default_3d_character_path(), trust_state=PackageTrustState.BUILT_IN
)
section = package.manifest.three_dimensional
context = SurfacelessContext()
renderer = ThreeDRenderer(context=context, seed=1)
renderer.load_package(package)
renderer.upload(
    package.model, animation_map=section.animation_map,
    expression_map=section.expression_map, viseme_map=section.viseme_map,
    native_scale=section.native_scale, floor_offset=section.floor_offset, now=0.0,
)
EXTRA['observedGpuBytes'] = renderer.observed_memory_bytes
EXTRA['estimatedGpuBytes'] = package.model.estimated_gpu_bytes
EXTRA['decodedTextureBytes'] = package.model.decoded_texture_bytes
HOLD.extend((package, context, renderer))
""",
    "character-drawn": """
from companion.character.defaults import default_3d_character_path
from companion.character.mapper import StateMapperInput, map_character_state
from companion.character.package import validate_package_directory
from companion.character.schema import PackageTrustState
from companion.character.three_d.context import SurfacelessContext
from companion.character.three_d.renderer import ThreeDRenderer
package = validate_package_directory(
    default_3d_character_path(), trust_state=PackageTrustState.BUILT_IN
)
section = package.manifest.three_dimensional
context = SurfacelessContext()
renderer = ThreeDRenderer(context=context, seed=1)
renderer.load_package(package)
renderer.upload(
    package.model, animation_map=section.animation_map,
    expression_map=section.expression_map, viseme_map=section.viseme_map,
    native_scale=section.native_scale, floor_offset=section.floor_offset, now=0.0,
)
renderer.begin_offscreen(288, 360)
mapped = map_character_state(package.manifest, StateMapperInput(presentation_phase='working'))
renderer.display_state(mapped, now_ms=0)
for index in range(240):
    renderer.draw(now_ms=index * 16)
EXTRA['frames'] = renderer.frame_statistics()
HOLD.extend((package, context, renderer))
""",
}

_HARNESS = """
import json, sys
sys.path.insert(0, {root!r})
HOLD = []
EXTRA = {{}}
{body}

def _memory():
    result = {{}}
    try:
        with open('/proc/self/status', encoding='ascii') as handle:
            for line in handle:
                if line.startswith('VmRSS:'):
                    result['rssBytes'] = int(line.split()[1]) * 1024
                elif line.startswith('VmHWM:'):
                    result['peakRssBytes'] = int(line.split()[1]) * 1024
    except OSError:
        result['result'] = 'NOT_RUN'
    try:
        total = 0
        with open('/proc/self/smaps_rollup', encoding='ascii') as handle:
            for line in handle:
                if line.startswith('Pss:'):
                    total += int(line.split()[1]) * 1024
        result['pssBytes'] = total
    except OSError:
        result['pssBytes'] = None
    return result

print('BUNNY_MEMORY ' + json.dumps({{'memory': _memory(), 'extra': EXTRA}}))
"""


def _run(name: str, body: str) -> dict:
    script = _HARNESS.format(root=str(_ROOT), body=body)
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=300, check=False,
    )
    for line in result.stdout.splitlines():
        if line.startswith("BUNNY_MEMORY "):
            return json.loads(line[len("BUNNY_MEMORY "):])
    return {
        "result": "NOT_RUN",
        "reason": (result.stderr.strip().splitlines() or ["no output"])[-1],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    arguments = parser.parse_args()

    stages = {name: _run(name, body) for name, body in _STAGES.items()}
    report = {
        "schema": "bunny-os/renderer-3d-memory/1",
        "note": (
            "Each stage is a separate interpreter holding only what its name says. "
            "No figure here includes GTK, and none includes a local language-model "
            "server: neither was in any of these processes."
        ),
        "stages": stages,
        "derived": {},
    }
    base = stages.get("bare-interpreter", {}).get("memory", {}).get("rssBytes")
    for name, stage in stages.items():
        rss = stage.get("memory", {}).get("rssBytes")
        if isinstance(rss, int) and isinstance(base, int):
            report["derived"][name + "AboveInterpreterBytes"] = rss - base
    payload = json.dumps(report, indent=2, sort_keys=True)
    if arguments.output is not None:
        arguments.output.write_text(payload + "\n", encoding="utf-8", newline="\n")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
