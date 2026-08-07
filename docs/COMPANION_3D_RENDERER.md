# The Bunny Companion 3D renderer

The companion's fifth and sixth presentation rungs: a rigged humanoid character
drawn from the same canonical `PresentationState` the 2D renderers draw, with a
validated glTF model, skeletal animation, morph-target facial expressions and
lip sync, and a degradation path back down to text.

ADR-030 records why this graphics stack and not another.
`COMPANION_3D_RENDERER_REPORT.md` records what was measured.

## Where it attaches

```text
User input
   -> Companion Runtime
   -> Agent Provider
   -> Task / ToolBroker / Approval
   -> Canonical PresentationState
   -> CharacterPresenter          companion/character/surface.py
   -> map_character_state          companion/character/mapper.py
   -> AdaptiveRendererSelector     companion/character/adaptation.py
   -> CharacterRendererController  companion/character/controller.py
   -> ThreeDRenderer               companion/character/three_d/renderer.py
```

Nothing above `CharacterPresenter` changed. The 3D renderer implements the same
`companion.character.renderer.CharacterRenderer` contract the static and
animated-2D renderers implement, so the controller drives it identically: same
package loading, same position, same scale, same speech bubble, same mouth
shape, same status.

## What it may and may not do

The subsystem may load validated 3D character packages, render, animate, blend,
change expressions, move eyes/head/body, receive lip-sync events, display speech
bubbles and report its own health and performance.

It may not read `TaskStore`, fold raw runtime events, select providers, execute
tools, resolve approvals, create tasks, inspect desktop contents, read
microphone audio, contact remote services or interpret free-form agent commands.

That is enforced rather than asserted. `tests/companion/test_three_d_isolation.py`
parses the AST of every module under `companion/character/three_d/` and fails on
any import — module-scope or deferred — of the runtime, the store, approvals, the
tool broker, the agent providers, the desktop adapters, the speech recogniser or
the voice worker internals, plus `socket`, `urllib`, `subprocess` and every audio
capture library. It also enumerates the permitted companion imports, so adding
one is a decision recorded in that file rather than a line in a diff.

The `§33` vertical slice lives *outside* the boundary, at
`companion/character/three_d_slice.py`, because a harness that drives the service,
the desk and the voice worker cannot live inside a package forbidden to import
them.

## The ladder

```text
full-3d  ->  lightweight-3d  ->  animated-2d  ->  static-image  ->  text-only
```

`companion.presentation.PRESENTATION_KINDS` has always listed all six rungs
(`audio-only` sits between the last two and draws nothing). What changed is
`IMPLEMENTED_PRESENTATIONS`, which now contains every one of them.

A rung joins that set when a renderer exists behind it *and* a test draws with
it. `tests/companion/test_three_d_render.py` creates a real OpenGL context,
uploads the shipped model, draws frames and reads the pixels back; it **skips**
rather than passes where no context can be made, so it cannot become a rubber
stamp on a machine without graphics.

## Modules

| Module | What it owns |
|---|---|
| `three_d/__init__.py` | the schema and renderer API versions, and the two rung names |
| `three_d/errors.py` | the typed refusals, all descended from `CharacterError` |
| `three_d/limits.py` | every validator bound, as data, clamped to a hard ceiling |
| `three_d/glb.py` | the GLB container and glTF safe-subset validator |
| `three_d/skeleton.py` | the Bunny humanoid profile and its alias resolution |
| `three_d/package3d.py` | the versioned 3D section of the package manifest |
| `three_d/animation.py` | candidates, priority, transitions, the bounded mixer |
| `three_d/face.py` | expressions and mouth shapes, on one degradation ladder |
| `three_d/procedural.py` | blink, breathe, glance — bounded and seedable |
| `three_d/scene.py` | the deterministic camera and the fixed lights |
| `three_d/shaders.py` | the renderer's own GLSL; the only shader source there is |
| `three_d/transform.py` | column-major 4x4 arithmetic, in pure Python |
| `three_d/gl.py` | a closed `ctypes` binding to OpenGL 3.3 core |
| `three_d/context.py` | EGL surfaceless and GTK-adopted contexts |
| `three_d/gpu.py` | the GPU resource ledger |
| `three_d/renderer.py` | upload, pose, draw, release |
| `three_d/budget.py` | §21's levels and thresholds, as configuration |
| `three_d/gtk_surface.py` | the `Gtk.GLArea` widget; the only module that knows GTK |
| `three_d/diagnostics.py` | §31's six operations and nothing else |

## The character package

A 3D character package **is a 2D character package with a `threeDimensional`
section**. It carries the same raster inventory, the same `animations`, the same
`stateMap` and the same `fallbackAsset`, and then describes a GLB beside them.

That is what makes degradation honest: when a machine drops from `full-3d` to
`animated-2d` there is no second package to find, validate, decode and swap in.
The fallback is already validated, already declared, already in the same
directory. A package that declares a 3D presentation and has no working 2D body
is refused.

The section declares: the model file and its digest, the skeleton profile and
bone map, the animation map, expression and viseme maps, morph-target names, the
texture and material inventories, model bounds, native scale and floor offset,
bubble and camera anchors, every resource maximum, declared GPU and decoded
bytes, required renderer features, the static and animated-2D fallbacks, and an
accessibility description for every mapped animation state.

A package's declared maximums become the validator's limits for that package —
so a manifest can only make validation *stricter*. `ModelLimits.__post_init__`
clamps every field to the build's hard ceiling, so it can never make it looser.

## The validator

`three_d/glb.py` is the only thing in this project that reads a GLB. It refuses:

* external file references, URLs and `data:` URIs on buffers and images;
* every compression extension by name — Draco, meshopt, Basis — as unbounded
  decoders this project does not own;
* unknown required extensions, unknown top-level fields, unknown node fields;
* package-supplied cameras (§17: the presentation camera is renderer-owned);
* sparse accessors, matrix node transforms, non-triangle primitives;
* NaN and infinite values anywhere, extreme and vanishing scales, non-unit
  quaternions, models larger than 20 m across;
* cyclic node graphs, nodes with two parents, unreachable nodes;
* out-of-range vertex indices, joint indices, accessor reads and buffer views;
* non-monotonic or over-long animation timelines, channels with no target;
* non-PNG textures, and PNG bombs — through the repository's existing bounded
  PNG reader, which now decodes as well as inspects.

Every count is checked against its limit *from the JSON* before the corresponding
bytes are read.

## The skeleton profile

`bunny-humanoid-1`: eighteen required bones plus `root`, resolved in three steps —
the manifest's `boneMap` first, then a built-in alias table covering Rigify,
Mixamo, VRM and hand-built naming, then nothing. An unresolved optional bone is a
capability the package lacks; an unresolved required bone fails validation.

## Animation

`PresentationState` → `CharacterState` (the existing mapper) → candidate set →
priority filter → transition planner → mixer.

The priority filter calls `companion.character.mapper.priority_rank`. There is no
second priority table; a test asserts §9's order is a subsequence of the
canonical one. A less urgent state cannot interrupt a more urgent one that is
still playing, which is how "a cosmetic animation must never obscure an approval
or an error" is guaranteed rather than hoped for.

The mixer runs at most four layers: outgoing base, incoming base, one upper-body
overlay, one facial layer.

`motion` is `full`, `reduced` or `none`. Reduced motion keeps the 3D rung and
removes crossfades and procedural movement — the character still *changes* when
the task changes, it simply does not move to get there.

## Lip sync

The viseme stream comes from `companion.character.speech_link.VisemeLink`, built
and validated by the voice-runtime phase. Request-ID matching, presentation
revision matching, monotonic ordering, cancellation, drift handling, worker
restarts and neutral resets are all *its* job and are not reimplemented here.
What this subsystem adds is the far end: a mouth shape resolved to morph targets,
or to a jaw bone, or to neutral.

## GPU resources

Every GL object passes through `GpuResources`, which records owner, creation
point, destruction point, estimated bytes and health. Release is idempotent and
survives a lost context, so the ledger reaches zero either way — otherwise every
subsequent leak measurement compares against a poisoned baseline.

## Diagnostics

Six operations, in a frozen table with no wildcard: `renderer_3d_health`,
`renderer_3d_status`, `renderer_3d_model`, `renderer_3d_metrics`,
`renderer_3d_explain`, `renderer_3d_reload`. None takes a path, a shader, a
texture or a GL command. Reached through `bunny-os companion renderer-3d <op>`.

## Building the reference character

```sh
scripts/build_default_character_3d.py --output assets/companion/characters/default-bunny-3d
```

Deterministic: the same script produces a byte-identical GLB on Linux and
Windows. Getting there needed two fixes, both recorded in the script — a
platform-independent deflate encoder, and quantising every float to a micrometre
so that `libm` differences in the last unit in the last place do not change a
digest.
