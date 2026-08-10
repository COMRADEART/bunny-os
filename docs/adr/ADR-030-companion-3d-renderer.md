# ADR-030: The 3D companion renderer

* **Status**: accepted
* **Date**: 2026-08-07
* **Phase**: `feature/companion-3d-renderer`
* **Supersedes**: nothing. Extends ADR-004 (desktop environment) and the
  companion character-renderer design in `docs/COMPANION_CHARACTER_RENDERER.md`.

## Context

The companion has drawn a character since the character-renderer phase, at three
rungs: `animated-2d`, `static-image` and `text-only`. The presentation ladder has
always had two rungs above those — `lightweight-3d` and `full-3d` — and they have
always been *eligible but not implemented*, which
`companion/presentation.py` recorded honestly and every consumer could read.

This phase implements them. The decision it needs is which graphics stack draws a
single rigged humanoid inside a GTK desktop companion, on machines ranging from a
laptop with an integrated GPU to a virtual machine with a software rasteriser.

Constraints that are not negotiable:

* it runs inside the existing GTK 4 client, in the same process, sharing its
  main loop;
* it must degrade to the three rungs below it rather than fail;
* a character package is untrusted input, so nothing in the stack may be an
  unbounded decoder the project does not own;
* whatever is chosen becomes a dependency of every installed Bunny OS machine,
  for as long as the companion exists.

## Options considered

Measured on the reference host (Fedora 44, Mesa 26.1.5, GTK 4.22.4,
python3-gobject 3.56.3, Python 3.14.3).

| | GTK GLArea + ctypes GL | PyOpenGL | ModernGL | wgpu-py | pyglet | Godot (separate process) |
|---|---|---|---|---|---|---|
| Linux / Wayland | yes | yes | yes | yes | yes | yes |
| GTK integration | native (`Gtk.GLArea`) | native | needs its own context | needs its own context | own window only | separate process, own window |
| Transparent surface | yes | yes | yes | yes | no (own window) | compositor-dependent |
| Fedora package | **none needed** | `python3-pyopengl` | **not packaged** | **not packaged** | `python3-pygame`-adjacent, not packaged | not packaged |
| New RPMs in the image | **0** | 1 (+ NumPy for most paths) | pip/vendored | pip/vendored + Rust dylib | pip/vendored | ~40 MB engine |
| Software fallback | llvmpipe, measured | llvmpipe | llvmpipe | Lavapipe (Vulkan) | llvmpipe | yes |
| glTF / skeletal / morph | our own validator | our own validator | our own validator | our own validator | our own validator | engine's importer |
| Bounded untrusted input | **entirely ours** | ours | ours | ours | ours | **engine's importer, not ours** |
| Resource cleanup | ours, ledgered | ours | ours | ours | ours | process kill |
| ARM potential | Mesa on ARM | same | same | wgpu on ARM | same | engine build per arch |
| Licence | ours, GPL-3.0-or-later | BSD | MIT | MIT/Apache | BSD | MIT |

## Decision

**`Gtk.GLArea` with an OpenGL 3.3 core context, driven through a repository-owned
`ctypes` binding to `libGL`, with an EGL surfaceless context for headless and
offscreen use.** glTF 2.0 / GLB is the asset format, validated by this
repository's own bounded validator before a byte reaches a driver.

Three things decided it.

**Zero new packages in the image.** The image already ships Mesa, `gtk4` and
`python3-gobject`. `companion/character/three_d/gl.py` is about fifty C entry
points bound with `ctypes` — a closed list, in one file, resolved lazily after a
context is current. PyOpenGL would have added an RPM (and, for most of its
array paths, NumPy — a 30 MB scientific stack) to every installed machine to
call the same functions. ModernGL and wgpu-py are not packaged for Fedora at
all, which means vendoring or pip, which means a supply chain this project does
not control inside an image it does control.

**The untrusted-input boundary stays ours.** A character package is a file a user
imported. Every alternative that includes an asset importer — Godot most of all
— moves the parsing of that file into code this project cannot bound, audit or
refuse. With this choice the only thing that reads a GLB is
`companion/character/three_d/glb.py`, which refuses external references, unknown
required extensions, sparse accessors, non-finite transforms, cyclic node graphs
and every compression extension by name, and produces a descriptor whose indices
are all in range before a buffer is allocated. That is not an incidental benefit
of the decision; it is most of the decision.

**GTK owns the frame clock.** `Gtk.GLArea` renders on the compositor's cadence
through `add_tick_callback`. A renderer with its own window and its own loop —
pyglet, Godot — would be a second thing pacing itself beside a compositor, which
this project has already learned the hard way is how a nested surface dies.

Godot was considered seriously and rejected on the directive's own terms: a full
game engine to display one companion, with no measured evidence that anything
above requires it. Unreal was not considered; the directive rules it out and so
does 40 MB of image.

## Consequences

**Accepted.**

* Roughly 2,000 lines of renderer this project maintains, including a GL binding,
  a glTF validator, a skinning path and a shader pair. The alternative was
  roughly the same amount of glue plus a dependency.
* No NumPy: joint matrices are composed in pure Python, one 4x4 per joint per
  frame. Measured at 23 joints on a software rasteriser this is not the
  bottleneck; a character with 96 joints would want re-measuring.
* PNG only for textures. A second image decoder is a second set of bombs.
* Fixed Huffman deflate in the asset generator, because `zlib.compress` output
  differs between platforms and the package manifest carries a digest. Measured:
  the same script produced `988815ff…` on Windows and `041ece80…` on Fedora
  before this was fixed.

**Deliberately not decided here.**

* Vulkan. Mesa's Lavapipe exists and wgpu is a real option for a future phase;
  nothing in the model format or the validator is OpenGL-specific, and the
  renderer is behind the same `CharacterRenderer` contract the 2D renderers use.
* Hardware-accelerated measurement. The reference host is `llvmpipe`, a software
  rasteriser, and every frame-time figure in the phase report says so.

## References

* `docs/COMPANION_3D_RENDERER.md` — the architecture this ADR chose.
* `COMPANION_3D_RENDERER_REPORT.md` — what was measured, and where.
* `companion/character/three_d/gl.py` — the binding and its closed symbol list.
* `companion/character/three_d/glb.py` — the validator.
