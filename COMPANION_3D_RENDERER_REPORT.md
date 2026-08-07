# Bunny Companion 3D Renderer

## 1. Starting and final SHAs

| | |
|---|---|
| Base branch | `feature/companion-desktop-actions` |
| Starting commit | `fa49380dadf0aa90690c4f2be5b483b16a56c0db` (verified head of the base branch; working tree clean) |
| Branch | `feature/companion-3d-renderer` |
| Source commit | `8bd18d7a62831b553b1505f0967ceaa2dfe0d991` — "A ladder that had two rungs nobody had built" |
| Gate commit | *(§32 below records the commit every gate iteration was run against)* |
| Evidence commit | *(the commit that adds `qualification/companion-3d-renderer/evidence/` and this report)* |
| Final SHA | *(the closure commit that follows, which edits only this table and §3's post-gate paragraph)* |

### Pre-branch checks

All four were run before the branch existed.

1. **Complete SHA resolved.** `git rev-parse feature/companion-desktop-actions` →
   `fa49380dadf0aa90690c4f2be5b483b16a56c0db`, which matches the expected
   abbreviated base `fa49380`.
2. **Working tree clean.** `git status --porcelain` produced no output.
3. **The desktop-actions post-gate range has zero installed-path changes.** The
   corrected analyser over `d0442fb..fa49380` — everything after that phase's
   gate commit — reports **0 installed, 1 context-only, 16 unreachable**. The
   one context-only path is `scripts/ops/desktop-collect.py`, a development tool
   the Containerfile can see and no route installs.
4. **The corrected build-input-closure analyser was run**, and is the analyser
   used throughout this report — the one driven by
   `build/scripts/install_routes.py`, which refuses to make a claim at all if
   `install-root.py` installs anything the route table does not describe.

Every prior evidence tree and report is preserved byte for byte;
`tests/companion/test_three_d_preservation.py` reads 4,676 recorded digests and
fails on a file that changed, disappeared, or was added to an earlier phase's
tree. No completed source branch was modified. No reproducibility candidate was
created.

## 2. Branch lineage

```text
main
 └─ … ─ feature/companion-voice-runtime
        └─ fix/companion-voice-closure
           └─ feature/companion-speech-input
              └─ feature/companion-agent-providers
                 └─ feature/companion-desktop-actions   fa49380
                    └─ feature/companion-3d-renderer    8bd18d7 …
```

This phase adds a capability. It corrects no earlier phase and supersedes no
earlier claim.

## 3. Build-input impact

The analyser over `fa49380..8bd18d7` reports **52 installed, 5 context-only,
13 unreachable**. Profiles affected: `beta`, `desktop`, `developer`, `live`,
`minimal`, `recovery`, `shell`, `shell-test`.

| Group | Paths | Route | Destination |
|---|---|---|---|
| the built-in 3D character package | 19 | `character-packages`, tree | `/usr/share/bunny-os/companion/characters/default-bunny-3d/` |
| the companion Python package | 33 | `companion-package`, package | `/usr/lib/bunny-os/python/companion/` |

**No new install route and no new destination.** The 3D subsystem lands under
the existing `companion` package route and the character package under the
existing `character-packages` tree route, both of which have been in
`install_routes.py` since the character-renderer phase.

**No new RPM.** ADR-030 records this as a decision rather than an accident: the
image already ships Mesa, `gtk4` and `python3-gobject`, and the renderer binds
about fifty OpenGL entry points with `ctypes` rather than adding
`python3-pyopengl` (and, for most of its array paths, NumPy) to every installed
machine.

The five context-only paths are development tools the Containerfile can see and
no route installs: `scripts/build_default_character_3d.py`,
`scripts/gtk_3d_probe.py`, `scripts/companion_stress.py`,
`scripts/ops/renderer3d-collect.py`, `scripts/ops/renderer3d-gates.sh`.

**Post-gate range:** *(recorded in §32 after the gates)*

**Every commit changes the OCI configuration digest** through the revision label
and `/usr/lib/bunny-os/release.json`. An unchanged layer digest is not an
unchanged image, and this phase makes no reproducibility claim (§39).

## 4. Renderer ADR

`docs/adr/ADR-030-companion-3d-renderer.md`.

**Decision:** `Gtk.GLArea` with an OpenGL 3.3 core context, driven through a
repository-owned `ctypes` binding to `libGL`, with an EGL surfaceless context for
headless and offscreen use. glTF 2.0 / GLB as the asset format, validated by this
repository's own bounded validator.

**Options measured:** PyOpenGL, ModernGL, wgpu-py, pyglet, Godot as a separate
presentation process. The comparison table is in the ADR. Three things decided
it:

* **Zero new packages in the image.** ModernGL and wgpu-py are not packaged for
  Fedora at all, which means vendoring or pip inside an image this project
  otherwise controls completely. PyOpenGL is packaged, and costs an RPM plus
  NumPy on every machine to call functions `ctypes` calls directly.
* **The untrusted-input boundary stays ours.** A character package is a file a
  user imported. Every option with its own asset importer — Godot most of all —
  moves the parsing of that file into code this project cannot bound or refuse.
* **GTK owns the frame clock.** `Gtk.GLArea` renders on the compositor's cadence
  through `add_tick_callback`. A renderer with its own window and its own loop
  would be a second thing pacing itself beside a compositor.

Unreal was not considered: the directive rules it out and so does the image size.
Godot was considered seriously and rejected on the directive's own terms — a full
game engine to display one companion, with no measured evidence that anything
requires it.

## 5. 3D architecture

```text
Canonical PresentationState        companion/presentation.py
        ↓
CharacterPresenter                 companion/character/surface.py
        ↓
map_character_state                companion/character/mapper.py     (unchanged)
        ↓
AdaptiveRendererSelector           companion/character/adaptation.py
        ↓
CharacterRendererController        companion/character/controller.py
        ↓
ThreeDRenderer                     companion/character/three_d/renderer.py
```

Seventeen modules under `companion/character/three_d/`, listed with what each
owns in `docs/COMPANION_3D_RENDERER.md`. The renderer implements the existing
`companion.character.renderer.CharacterRenderer` contract, so the controller
drives it exactly as it drives the static and animated-2D renderers — same
package loading, position, scale, speech bubble, mouth shape and status.

Nothing above `CharacterPresenter` changed shape. The mapper is untouched; the
3D state machine consumes its output and calls its `priority_rank`.

## 6. Package-schema extension

`companion/character/three_d/package3d.py`, schema version 1, renderer API 1.0.

A 3D character package **is a 2D character package with a `threeDimensional`
section** — the same raster inventory, the same `animations`, the same
`stateMap`, the same `fallbackAsset`, and a GLB beside them. That is what makes
degradation honest: dropping from `full-3d` to `animated-2d` finds the fallback
already validated and already in the same directory rather than loading a second
package at the moment the machine is already in trouble. A package declaring a 3D
presentation without a working 2D body is refused.

Every §5 field is present: `modelFile`, `modelDigest`, `gltfVersion`,
`skeletonProfile`, `rootBone`, `headBone`, `neckBone`, `eyeBones`, `handBones`,
`animationMap`, `expressionMap`, `visemeMap`, `morphTargets`, `textureInventory`,
`materialInventory`, `modelBounds`, `nativeScale`, `floorOffset`, `bubbleAnchor`,
`cameraAnchor`, `maximumTriangles`, `maximumVertices`, `maximumJoints`,
`maximumMorphTargets`, `maximumTextures`, `maximumTextureDimensions`,
`declaredGpuBytes`, `declaredDecodedBytes`, `requiredRendererFeatures`, plus
`staticFallbackAsset`, `animatedFallbackState`, `previewAsset` and
`accessibilityStates`.

**A package's declared maximums become the validator's limits for that package.**
`ModelLimits.__post_init__` clamps every field to the build's hard ceiling, so a
manifest can make validation stricter and can never make it looser. A manifest
claiming ten million triangles gets the build's 200,000 and its model is refused
against that.

`accessibilityStates` must describe every mapped animation state, or the package
is refused. There is no way to ship a 3D character whose states a screen reader
cannot name.

## 7. GLB validator

`companion/character/three_d/glb.py` is the only thing in this project that reads
a GLB, and the renderer never sees a file — only a frozen `ValidatedModel` whose
every index is proved in range and every float proved finite.

Three rules shape it. **Declared before observed**: every count is checked
against its limit from the JSON before the corresponding bytes are read, so a
document that lies about its own size is refused at the length of a list rather
than after allocating what it claimed. **No second decoder**: Draco, meshopt and
Basis are refused by name with the reason attached. **Refusals name the thing**:
`ModelSecurityError` for reaching outside the package, `ModelLimitError` for
exceeding a bound, `ModelSchemaError` for a document that is merely wrong.

Limits enforced: file size, JSON chunk size, binary chunk size, vertices,
triangles, nodes, node depth, meshes, primitives, joints, skins, animations,
animation duration, animation channels, animation samplers, keyframes,
keyframes per sampler, morph targets, textures, images, samplers, texture
dimension, decoded texture bytes, materials, buffers, buffer views, accessors,
scenes, extension names, name length, and estimated GPU bytes.

Rejections: external file references, URLs and `data:` URIs on buffers and
images; a second buffer; every compression extension by name; unknown required
extensions; unknown top-level, node and morph-target fields; package-supplied
cameras; sparse accessors; matrix node transforms; non-triangle primitives; NaN
and infinite values anywhere; extreme and vanishing scales; non-unit quaternions;
models over 20 m across; cyclic node graphs; nodes with two parents; unreachable
nodes; out-of-range vertex, joint, accessor and buffer-view reads; non-monotonic
and over-long animation timelines; channels with no target node; weight channels
on meshes without morph targets; non-PNG textures; unsupported wrap and filter
modes; and PNG bombs.

PNG decoding goes through `companion/character/image.py` — the repository's
existing bounded reader, extended in this phase to reconstruct pixels as well as
inspect them, so there is one PNG implementation rather than two.

## 8. Skeleton profile

`bunny-humanoid-1`: the eighteen bones §7 requires plus `root`, resolved in three
steps, most explicit first — the manifest's `boneMap`, then a built-in alias
table, then nothing.

The alias table covers Rigify (`upper_arm.L`), Mixamo (`mixamorig:LeftArm`), VRM
(`J_Bip_L_UpperArm`) and hand-built armatures (`LeftUpperArm`, `left_upper_arm`),
compared with separators removed and case folded — but never with the side folded
away: `.L` and `.R` suffixes are rewritten to a `left`/`right` prefix so a side
cannot disappear into a separator strip.

Optional bones — eyes, jaw, shoulders, toes, hair, accessory roots, and fingers
and toes by pattern — are capabilities a package may lack, never errors. An
unresolved *required* bone fails validation, because a humanoid without a head is
not a humanoid and the renderer would be guessing where the speech bubble goes.

`ancestry_violations` reports which profile bones do not descend from where the
profile says they do, as *ancestry* rather than parentage, because real rigs
legitimately insert twist and roll bones.

## 9. Animation system

```text
PresentationState → CharacterState → candidate set → priority filter
    → transition planner → animation mixer
```

Twenty-two animation states, one per §8 entry. Each character state has a
candidate chain that terminates in `idle`, so resolution always ends in something
drawable.

**There is no second task-state machine.** The priority filter calls
`companion.character.mapper.priority_rank`; §9's order is spelled out as
`SECTION_NINE_ORDER` only so that a test can assert it is a *subsequence* of the
canonical order. A less urgent state cannot interrupt a more urgent one that is
still playing — which is how "a cosmetic animation must never obscure an approval
or an error" is guaranteed rather than hoped for. A finished one-shot releases
the hold.

Loop/one-shot is a property of what the state *means*, held in `LOOPING_STATES`
rather than in the package, so a package author cannot make an error animation
loop for ever.

`motion` has three values: `full` (crossfades, overlays, procedural motion),
`reduced` (first-frame poses, no crossfade, no procedural movement, state changes
still drawn) and `none` (bind pose plus expression).

## 10. Animation blending

At most four layers, and the bound is structural rather than advisory: the mixer
has fields for the outgoing base, the incoming base, one upper-body overlay and
one facial layer, and no list.

Crossfade is 0.22 s ordinarily and 0.08 s into a state the user must attend to.
Quaternions blend by shortest-arc nlerp — over a 0.22 s crossfade between two
poses of the same character the difference from slerp is not observable, and
slerp costs an `acos` and two `sin` per joint per frame on a CPU that is also
rasterising.

Keys present in only one pose are taken from that one at full strength: a layer
that says nothing about the left foot is not an instruction to move the left foot
towards the origin.

The upper-body overlay is restricted to the subtree below `chest`, computed once
at load from the validated node graph.

Tracked and reported: blend start, blend duration, current weight, completion,
cancellation, and the live layer count against the maximum.

## 11. Facial system

Nine expressions — neutral, happy, focused, thinking, concerned, warning, error,
surprised, sleepy — resolved down a fixed three-rung ladder that records which
rung it landed on: **morph targets**, then **bone controls**, then **neutral**.
`FaceRig.to_json()` reports the mechanism per expression, so a diagnostic can
tell the difference between a character that is calm and a character that cannot
smile.

No character fails for lacking optional morphs. `expression_map` entries naming
targets the model does not carry are dropped at rig-build time, and the
expression falls to `neutral-fallback`.

Expression follows the canonical character state through `STATE_EXPRESSIONS` —
a presentation detail of an already-decided fact, not a second reading of the
task.

Values are damped towards a target rather than animated over a fixed duration,
because both inputs arrive at rates nobody controls; the mouth damps about four
times faster than the expression.

## 12. Lip-sync integration

**No second timeline is built.** Request-ID matching, presentation-revision
matching, monotonic ordering, cancellation, drift handling, worker-restart and
renderer-restart handling and neutral resets all live in
`companion.character.speech_link.VisemeLink`, built and validated by the
voice-runtime and voice-closure phases. This phase adds the far end: an
already-admitted mouth shape resolved to morph targets, or to a jaw bone, or to
neutral.

The seven generic shapes map to package-defined morph targets where declared;
where they are not, a jaw bone rotates by up to 0.30 rad proportional to the
shape's openness; where there is neither, the mouth holds neutral and says so.

An unknown shape closes the mouth rather than holding whatever was last drawn,
because a held shape is a mouth frozen mid-syllable. Speech completion,
cancellation, error and worker restart all route to `reset_mouth()`.

Verified against pixels: `test_a_viseme_moves_the_mouth` in
`tests/companion/test_three_d_render.py` draws with the mouth neutral, reads the
framebuffer, sets `open-wide`, draws again and asserts the two differ.

## 13. Procedural idle, head and eye behaviour

Blink (2.4–7.5 s, 120 ms closure), saccades (1.1–4.0 s, ±0.12 rad), head turns
(3.0–9.0 s, ±0.09 rad), breathing (4 s period, 0.6 % chest scale) and posture
shifts (11–26 s, ±0.03 rad).

**There is no sensor.** No camera, no face detection, no gaze estimation, no
biometric anything. The attention target is chosen from the same layout the
speech bubble was placed with — a rectangle on a screen, not a person in a room.
Targets are `forward`, `bubble`, `task-panel`, `listening`, `speaking`,
`thinking`, `away`, and an unknown name resolves to `forward`.

§14's constraints: a **seed** makes a run reproducible (asserted by replaying 400
steps twice and comparing blink, saccade and head-turn counts); a **minimum
interval** of 0.5 s is enforced by the scheduler rather than hoped for from the
random draw (asserted over 2,000 steps); **reduced motion** keeps the blink and
drops everything that moves; **suspension** under battery or thermal pressure
stops everything; and there is **no queue** — each behaviour has a next time that
is rewritten when it fires, so a renderer suspended for ten minutes wakes owing
nothing.

## 14. Rendering surface

`companion/character/three_d/gtk_surface.py` is the only module in the subsystem
that knows GTK exists, and it imports it inside a function.

`Gtk.GLArea` with a depth buffer, `auto_render` off, and — where GTK 4.12+
provides it — `set_allowed_apis(Gdk.GLAPI.GL)`, because the renderer compiles
`#version 330 core` and a GLES context refuses it.

The frame clock is GTK's: `add_tick_callback` queues a render on the
compositor's cadence and the renderer's own frame-rate cap decides whether the
draw does work. Nothing here sleeps or loops.

Transparency is *requested* — clear colour with zero alpha — and whether the
surface is composited that way is the compositor's decision, which the surface
report records rather than claims.

Modes: `docked`, `center`, `compact`, each with a size fraction and a camera
mode. Character scale, position, speech-bubble anchor and reduced motion are
inputs. §32 records what happened on the compositor that was available.

## 15. Camera

Deterministic, renderer-owned, and bounded on every axis: FOV 18–55°, distance
0.35–12 m, near 0.01–1 m, far 2–100 m, pitch ±0.35 rad.

Four modes — full-body, waist-up, compact, close-speaking — selected from the
canonical placement `companion.presentation.placement_for_phase` already
produced, so the camera follows the layout decision rather than making a second
one.

Framing is expressed as a fraction of the character's own height rather than a
distance in metres, so the same camera works for a 1.7 m humanoid and a 0.9 m
stylised one without a per-package setting.

**No provider may supply camera matrices**, and this is checked rather than
merely unimplemented: the GLB validator refuses a document carrying a `cameras`
array or a node with a `camera` property, so the *intent* is refused and not just
ignored. The reason is not aesthetic — a camera matrix is a general affine
transform, and given one an untrusted party can put the near plane inside the
character's head or scale one triangle across the screen.

Determinism is asserted: the same bounds, mode and aspect always produce the same
matrices, with no clock and no easing.

## 16. Lighting

One key light, one fill light, one ambient term. Constants, with no path that
changes them and no way for a package to contribute one. No environment map and
nothing to download; a character that looked right only after fetching an HDR
would be a character that looked wrong on a machine with no network.

The lightweight rung folds the fill into ambient so the fragment shader evaluates
one light instead of two.

## 17. Materials and shaders

A small fixed material model: glTF metallic-roughness PBR, `OPAQUE`/`MASK`/
`BLEND` alpha, double-sided, optional base-colour texture, optional
`KHR_materials_unlit`. Every factor is clamped at parse time.

**Package-supplied shaders are impossible, not merely unimplemented.** The only
strings ever handed to `glShaderSource` come from
`companion/character/three_d/shaders.py`, and
`tests/companion/test_three_d_security.py` walks the AST of every file under
`companion/` to assert that `renderer.py` is the only module that calls it. The
two substituted values are integers this build computed and clamped; the alpha
mode is looked up in a closed table, so a package that somehow reached the
function with `"OPAQUE; void main(){}"` gets a `KeyError` and no shader.

Skinning is a `mat4` uniform array sized to the model's joint count at compile
time; a model needing more joints than the driver's vertex-uniform budget allows
is refused with a typed capability error rather than compiled into something that
links and draws the wrong skeleton.

Morph targets arrive as an `RGB32F` texture sampled with `texelFetch`, because GL
3.3 core guarantees sixteen vertex attributes and six are already used. At most
eight targets contribute to a frame, chosen on the CPU by weight.

## 18. GPU resource lifecycle

Every GL object this renderer creates passes through
`companion/character/three_d/gpu.py`, which records kind, driver name, owner,
creation point, creation call, estimated bytes and health. That is the only way
to answer §34's question — "did a hundred lifecycles leak a texture?" — because
OpenGL has no way to enumerate what a process owns.

Release is idempotent, never raises, and takes `context_lost`: when the context
is gone the names are already invalid, so the ledger drops them without calling
the driver and still reaches zero. A release path that could throw would stop
halfway and leave the rest of the ledger live, which is the leak it exists to
prevent.

Model replacement is bounded to one overlap: `begin_replacement` refuses to open
if any owner other than the outgoing and incoming model is live.

Kinds tracked: vertex buffers, index buffers, vertex arrays, textures, morph
textures, shader programs, framebuffers, renderbuffers.

## 19. Capability integration

The renderer reads the capability assessment; it never probes. `three_d_signals`
is separate from `signals_from_assessment` because the two answer different
questions — the assessment describes the *machine*, and whether a graphics
context can be made and whether the selected package carries a model are
properties of this process and its chosen character.

`companion.presentation.select_presentation` gained one memory band
(`lightweight-3d` between 2 GiB and 3 GiB) and kept its existing rule that a
machine with no usable GPU is not eligible for 3D at all.

`IMPLEMENTED_PRESENTATIONS` gained `full-3d` and `lightweight-3d`. That line is
the one that makes every consumer downstream start believing 3D is available, so
it moved only once there was a renderer behind it *and* a test that draws with
it — `tests/companion/test_three_d_render.py`, which **skips rather than passes**
where no context can be made.

§21's levels and thresholds are `companion/character/three_d/budget.py`: a frozen
dataclass with a named default and a `from_mapping` constructor that reads
capability configuration and clamps each value into a range this build can
honour. The distinction preserved is between a *policy* (24 ms p95 before the
full rung drops — a different machine could reasonably choose 30 or 18) and a
*bound* (the threshold may not be zero, negative, or larger than a second). An
unknown configuration key is **refused**, not ignored, because a setting somebody
believes is in force and this build does not read is how a machine ends up
running a policy nobody chose.

## 20. Adaptive degradation

Triggers, all in `AdaptiveRendererSelector.evaluate`:

| Trigger | Effect |
|---|---|
| GPU context loss | `animated-2d` |
| 3D renderer failure | `animated-2d` |
| unsupported graphics feature | `animated-2d` |
| model load failure | `animated-2d` (the renderer refuses, the presenter degrades) |
| battery below 25 % | `animated-2d` |
| memory below the rung's floor | one rung down |
| model above the rung's GPU ceiling | one rung down |
| sustained slow frames | one rung down |
| dropped-frame ratio above 25 % | one rung down |
| thermal pressure | `lightweight-3d` |
| memory pressure | `animated-2d` (and the pre-existing 2D rule takes it to `static-image`) |

The 3D rules run *before* the rules that were already there, so a machine that
loses its context and has no memory arrives at the right rung in one evaluation
rather than descending one per frame.

**Sustained** is enforced by `FrameHealth`, which requires the ceiling to be
exceeded for three consecutive samples and ignores samples taken before there
are twenty frames — otherwise the first frame, which compiles three shader
programs, would degrade every machine that ever started a renderer.

Degradation never restarts the task, never changes its result, never invalidates
an approval, preserves captions, the task panel and voice, and returns lip sync
to neutral. §31 of the slice compares the task's identity, state and result
recorded *before* the pressure against the same fields afterwards.

Recovery is held by the selector's hysteresis (three healthy samples and a delay)
and, for faults rather than capability, by the presenter's separate 15-second
health-recovery window and its restart guard.

**Reduced motion keeps the 3D rung.** It is a mode of the animation system, not a
rung: dropping to a static image would remove the state information along with
the motion, which is the opposite of what the preference asks for. `no_animation`
still drops to `static-image`, and the renderer's own `none` mode is implemented
and tested but not what the ladder selects — a still 3D render costs more than
the static PNG for the same visual result. That is stated rather than hidden.

## 21. GPU and context-loss recovery

`GraphicsContext.lost` is checked before every frame. On failure the renderer
raises a typed `RendererContextError`, the presenter catches it, records a typed
degradation event, releases what it can, drops a rung, and retries only after a
bounded interval.

Handled and tested: context creation failure (`SurfacelessContext` raises
`RendererCapabilityError`, the ladder lands on `animated-2d`), context loss
(`simulate_loss` — reachable from tests and the slice, and deliberately not from
any protocol operation), shader compilation failure (the log is read back and
attached to the error), texture allocation failure, model upload failure,
framebuffer incompleteness, and a context destroyed underneath a live renderer.

The last of those is the one that matters most for the leak columns:
`test_a_context_destroyed_underneath_the_renderer_is_survivable` releases the EGL
context first and then the renderer, and asserts the ledger still reaches zero —
because if it did not, every subsequent leak measurement would compare against a
poisoned baseline.

## 22. Character customization

Selection is by installed package id through the existing registry:
`bunny-os companion character select bunny-default-3d`. Settings may store a
package id, scale, dock mode, preferred camera, a reduced-motion override and an
idle-animation preference. Arbitrary model paths, network URLs and executable
customization scripts have nowhere to be stored — the registry holds ids and
digests, and the renderer reads the path the *manifest* names, which the package
validator already proved lies under the package root.

**A package change is user-initiated, and this phase kept it that way.** The 2D
character remains the default selection: `default_character_paths()` returns the
2D package first, and `PackageRegistry.selected()` returns the first built-in
when the user has chosen nothing. Promoting the 3D character to the default would
have been this phase changing what every existing machine draws as a side effect
of adding a renderer. §35 lists this as a limitation.

## 23. Default 3D character

`assets/companion/characters/default-bunny-3d/`, generated by
`scripts/build_default_character_3d.py`.

| | |
|---|---|
| Vertices | 1,568 |
| Triangles | 2,452 |
| Joints | 23 (18 required + root + jaw + 2 eyes + 2 shoulders) |
| Animation clips | 22, one per canonical animation state |
| Morph targets | 11 |
| Materials | 3 (skin, cloth, eye) |
| Textures | 1, 64×64 PNG, generated |
| GLB size | 303,984 bytes |
| GLB SHA-256 | `778228cdac72a38ea0c5f1690cc25081475390c789d7fa360a0d47811d177914` |
| Estimated GPU bytes | 269,264 |
| Height | 1.690 m |
| Package files | 19 |

Human silhouette, fully rigged, neutral materials, repository-owned. Clips for
idle, greeting, listening, transcribing, understanding, planning, working,
researching, typing, reviewing, waiting-for-user, waiting-for-approval, speaking,
presenting-result, success, warning, blocked, error, paused, cancelled, sleeping
and repositioning. Morph targets for five mouth shapes, two brow positions, smile,
frown, eye-narrow and cheek-puff. Blinking is bone-driven — the eye bones flatten
the eye spheres — and the package does not declare a blink morph, which is stated
here because the alternative would be claiming a morph the character does not
have.

**The default package passes exactly the same validator as an imported one.**
`tests/companion/test_three_d_package.py::ImportTests` imports the built-in
package through the ordinary importer and asserts the resulting package digest
and model digest equal the built-in's. There is no built-in bypass;
`validate_package_directory` has a `validate_model` flag for the registry
*listing*, and the renderer refuses a package whose model was not validated, so
the flag can make a listing cheaper and cannot make a draw unsafe.

**Determinism.** The generator produces a byte-identical GLB on Linux and
Windows. Two fixes were needed and both are recorded in the script:

* `zlib.compress` is not portable. The first build produced SHA-256
  `988815ff…` on Windows and `041ece80…` on Fedora — same Python version, same
  inputs, different zlib build, different Huffman tree. The manifest carries that
  digest and the validator checks it, so a package built on one machine failed
  its own integrity check on the other. The generator now emits RFC 1951 fixed
  Huffman with distance-1 run matching, or stored blocks where that is smaller,
  and chooses between them as a deterministic function of the input.
* `math.sin` and `math.cos` are libm calls and glibc and the MSVC runtime
  disagree in the last unit in the last place — enough to change a vertex, an
  accessor's `min`, the length of the JSON chunk and therefore the digest. Every
  float is quantised to 1e-6 before packing: four orders finer than anything
  visible on a 1.7 m figure, ten orders coarser than the disagreement.

Verified: the same script run on Windows and on Fedora both produce
`778228cd…`, and the file round-trips `git add`/`git cat-file` byte-exactly
(303,984 in and out) because `assets/companion/characters/** -text` was already
in `.gitattributes` from the 2D character phase.

## 24. Asset provenance

`assets/companion/characters/default-bunny-3d/PROVENANCE.json`, declared in the
manifest as an asset with `purpose: "provenance"` and therefore digest-checked
like every other file in the package.

| Field | Value |
|---|---|
| creator | ComradeArt |
| creationSource | `scripts/build_default_character_3d.py` |
| generated | true |
| handCreated | false |
| tool | python3 (standard library only) |
| generationWorkflow | geometry, rig, skin weights, morph targets, animation clips, texture and 2D fallback frames computed arithmetically and written directly to GLB and PNG; no modelling, sculpting or animation tool involved |
| modificationHistory | one entry: created, with what it contains |
| derivedFrom | nothing |
| thirdPartyContent | none |
| licence | GPL-3.0-or-later |

**No copyrighted game characters and no commercial assets.** That is structural
rather than asserted: every vertex, weight, keyframe and pixel in the package is
a consequence of code in this repository, under this repository's licence,
derived from nothing. There is no imported mesh, no scan, no photograph and no
motion capture. A test asserts the licence file mentions none of the common asset
marketplaces and that every file in the package is `.png`, `.glb`, `.txt` or
`.json`.

## 25. Package-import security

The §27 flow runs unchanged in shape, with the new steps inside
`validate_package_directory` where the existing importer already called it:

```text
archive → structural validation → manifest validation → digest validation
       → GLB validation → texture validation → skeleton validation
       → animation validation → resource-budget validation
       → staging → activation
```

Validation happens at **staging**, before `os.replace` moves the payload into
place, so a package with a broken model never becomes active. The registry record
is added only after the installed copy re-validates. `selected()` keeps returning
the previous package, so a failed import leaves the previous working character
selected — asserted by
`test_a_failed_import_leaves_the_previous_character_selected`.

Tested: importing a directory, importing a `.zip`, a corrupted GLB refused with
no content left behind, a failed import leaving the previous selection, and
archive traversal refused.

## 26. Renderer isolation

`tests/companion/test_three_d_isolation.py` parses the AST of every module under
`companion/character/three_d/` and fails on any import — module-scope or deferred,
because a deferred import is still an import and is the form the first violation
usually takes — of:

`companion.store`, `companion.runtime`, `companion.task`, `companion.tools`,
`companion.approvals`, `companion.executor`, `companion.reviewer`,
`companion.agents`, `companion.agent_bridge`, `companion.desktop`,
`companion.desktop_bridge`, `companion.speech`, `companion.service`,
`companion.session`, `companion.protocol`, `companion.coordination`,
`companion.events`, `companion.recovery`, `companion.migration`, `companion.cli`,
`companion.gtk_shell`, `companion.voice.worker`, `companion.voice.service`,
`companion.voice.providers`.

It also fails on `socket`, `http`, `urllib`, `requests`, `ssl`, `subprocess`,
`multiprocessing`, `pty`, and on any occurrence of `parec`, `arecord`, `pyaudio`,
`sounddevice` or `AudioCapture` in the source.

What may cross is enumerated as `PERMITTED_COMPANION_IMPORTS` — the presentation
contract and the validated-package contract, eleven modules — so adding a
twelfth is a decision recorded in that test file rather than a line in a diff.

**The §33 slice lives outside the boundary**, at
`companion/character/three_d_slice.py`. It was inside for about an hour, and
worked around the test by synthesising voice events from a duck-typed object —
which is the wrong answer twice over: it weakens the evidence and it hides a
boundary violation behind a shape. A harness that drives the service, the desk
and the voice worker belongs outside the package forbidden to import them.

## 27. Headless behaviour

`import companion.character.three_d` and every module under it opens no graphics
library. `test_importing_the_package_opens_no_graphics_library` runs a subprocess
that imports the package, the GL binding, the renderer and the context module,
and asserts `sys.modules` contains no `gi`, `OpenGL`, `moderngl`, `pyglet` or
`numpy` and that `gl._LOADED` is `None`.

`three_d_environment()` answers "can this machine draw in 3D" by looking for the
*libraries* and the *session*, not by making a context — because §30 forbids
initialising a GPU library to answer a question about whether one is needed.

A `CharacterPresenter` given no context provider — which is every caller written
before this phase, and every headless or text-only client — has the 3D rungs
simply unreachable. `describe()["threeDimensionalRenderer"]` reports why rather
than `None`; that field said `None` for two phases and it was true then.

Ladder on a headless machine: no display → `text-only` (or `audio-only` where
audio exists), with the reason attached. Captions are produced at every rung.

## 28. Protocol and diagnostics

Six operations in a frozen table with no wildcard: `renderer_3d_health`,
`renderer_3d_status`, `renderer_3d_model`, `renderer_3d_metrics`,
`renderer_3d_explain`, `renderer_3d_reload`. Reached through
`bunny-os companion renderer-3d <op>`; the operation name is *built* from a
closed set of subcommand names, never taken from input.

`REFUSED_OPERATIONS` names five that have been proposed and are refused by design
with the reason attached, so a refusal explains itself rather than reading as
"not implemented yet": arbitrary shader load, arbitrary model path, arbitrary
texture path, arbitrary GPU command, arbitrary package mutation.

A test asserts no operation accepts a parameter named `path`, `file`, `shader`,
`texture`, `command`, `source` or `uri`, and that `run_operation` takes exactly
`name`, `root`, `package_id` and `frames`.

These are not companion-service protocol operations. The renderer lives in the
client process; the service holds no renderer, and answering "how is your
renderer" from a process that has none would be a lie with a schema.

A diagnostic session creates at most one context and always releases it —
`ThreeDDiagnostics` is a context manager and `run_operation` uses it as one —
because a diagnostic that kept a GPU context alive between calls would be a
background renderer nobody asked for.

## 29. Security results

*(§28's case list, run: filled in with the test counts below)*

## 30. GTK and Wayland results

*(filled in from `scripts/gtk_3d_probe.py`)*

## 31. Integrated vertical slice

*(filled in from the slice gate)*

## 32. Stress gates

*(filled in after the gates)*

## 33. Performance measurements

*(filled in after the gates)*

## 34. Complete test results

*(filled in after the gates)*

## 35. Known limitations

*(below)*

## 36. NOT_RUN items

*(below)*

## 37. Remaining production-art work

*(below)*

## 38. Remaining physical-hardware validation

*(below)*

## 39. Reproducibility implications

*(below)*
