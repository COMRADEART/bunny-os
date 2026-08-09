#!/usr/bin/python3
"""Check a run's on-screen layout from the accessibility tree.

The framebuffer capture at 1366x768 is sheared — virtio-vga's scanout stride
does not divide a width that is not a multiple of eight, and the diagonal tear
is in the *picture*, not in the session. So the layout is checked from the other
source the run already has: AT-SPI reports each control's extents in screen
coordinates, taken from Clutter's actual allocation of the actor rather than
from what the layout solver intended.

Two questions, both of which a sheared photograph cannot answer and this can:
is every control inside the screen, and do the panels overlap each other.
"""
import json
import pathlib
import sys

record = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
width, height = int(sys.argv[2]), int(sys.argv[3])
controls = record["interaction"]["controls"]["controls"]

named = [c for c in controls if c.get("extents") and c["extents"]["width"] > 0]
print(f"controls with an allocation: {len(named)}")

off_screen = []
for control in named:
    e = control["extents"]
    if e["x"] < 0 or e["y"] < 0 or e["x"] + e["width"] > width or e["y"] + e["height"] > height:
        off_screen.append((control["name"], control["role"], e))

print(f"\n--- off screen ({len(off_screen)}) ---")
for name, role, e in off_screen[:15]:
    print(f"  {name!r} ({role}) {e['x']},{e['y']} {e['width']}x{e['height']}")

# The panels the layout solver places. Named by the accessible names the shell
# sets on the containers, plus the cards' own.
PANELS = ["Bunny dock", "Bunny sidebar", "System overview", "Quick access",
          "Network and power monitor", "Bunny, your assistant"]


def rect(name):
    for control in named:
        if control["name"] == name:
            return control["extents"]
    return None


def overlaps(a, b):
    return (a["x"] < b["x"] + b["width"] and b["x"] < a["x"] + a["width"] and
            a["y"] < b["y"] + b["height"] and b["y"] < a["y"] + a["height"])


print(f"\n--- panels at {width}x{height} ---")
found = {}
for name in PANELS:
    r = rect(name)
    print(f"  {name:28s} {r}")
    if r:
        found[name] = r

print("\n--- overlapping pairs ---")
pairs = []
keys = sorted(found)
for i, a in enumerate(keys):
    for b in keys[i + 1:]:
        if overlaps(found[a], found[b]):
            pairs.append((a, b))
            print(f"  {a} <-> {b}")
if not pairs:
    print("  none")

print("\n--- controls clipped by the screen edge ---")
print(f"  {len(off_screen)} of {len(named)}")
