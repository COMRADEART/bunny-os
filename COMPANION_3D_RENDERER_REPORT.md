# Bunny Companion 3D Renderer

## 1. Starting and final SHAs

| | |
|---|---|
| Base branch | `feature/companion-desktop-actions` |
| Starting commit | `fa49380dadf0aa90690c4f2be5b483b16a56c0db` (verified head of the base branch; working tree clean) |
| Branch | `feature/companion-3d-renderer` |
| First source commit | `8bd18d7a62831b553b1505f0967ceaa2dfe0d991` — "A ladder that had two rungs nobody had built" |
| Gate commit | `75bc033b015cddc568ee6b09477327f8c6708498` — every gate iteration records it |
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

The analyser over `fa49380..75bc033` — the base to the gate commit — reports
**54 installed, 6 context-only, 14 unreachable**. Profiles affected: `beta`,
`desktop`, `developer`, `live`, `minimal`, `recovery`, `shell`, `shell-test`.

| Group | Paths | Route | Destination |
|---|---|---|---|
| the built-in 3D character package | 19 | `character-packages`, tree | `/usr/share/bunny-os/companion/characters/default-bunny-3d/` |
| the companion Python package | 33 | `companion-package`, package | `/usr/lib/bunny-os/python/companion/` |
| the two published JSON schemas | 2 | `schemas`, tree | `/usr/share/bunny-os/schemas/` |

**No new install route and no new destination.** The 3D subsystem lands under
the existing `companion` package route and the character package under the
existing `character-packages` tree route, both of which have been in
`install_routes.py` since the character-renderer phase.

**No new RPM.** ADR-030 records this as a decision rather than an accident: the
image already ships Mesa, `gtk4` and `python3-gobject`, and the renderer binds
about fifty OpenGL entry points with `ctypes` rather than adding
`python3-pyopengl` (and, for most of its array paths, NumPy) to every installed
machine.

The six context-only paths are development tools the Containerfile can see and
no route installs: `scripts/build_default_character_3d.py`,
`scripts/gtk_3d_probe.py`, `scripts/companion_stress.py`,
`scripts/ops/renderer3d-collect.py`, `scripts/ops/renderer3d-gates.sh`,
`scripts/ops/renderer3d-memory.py`.

**No image was built and nothing was installed.** The routes above are what the
analyser resolved from `build/scripts/install_routes.py` — the same declaration
`install-root.py` is driven by, which is the point of that file existing — and
`install_routes.audit_installer` passed, so the analyser made a claim rather than
refusing to. Whether the bytes land correctly in a built image is a question
only a build answers, and building one is a reproducibility candidate this phase
was told not to create. §39 says so again.

**Post-gate range:** *(recorded below after the evidence commit)*

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

Nineteen files under `companion/character/three_d/`.
`docs/COMPANION_3D_RENDERER.md` tabulates the seventeen that own a subsystem
responsibility; the other two are `__init__.py`, which holds the schema and
renderer API versions and the two rung names, and `errors.py`, whose typed
refusals all descend from the character package's existing `CharacterError`. The renderer implements the existing
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
| GLB size | 304,380 bytes |
| GLB SHA-256 | `88e9364fc2b3335713cc2fb5e6e2cc557ab7fcaa2f6d9b2ee9b9d459b98c20de` |
| Estimated GPU bytes | 269,264 |
| Height | 1.690 m |
| Package files | 19 |

**The poses were looked at, and three of them were wrong.** The clip table was
first written in Euler angles, and an arm lying along +X rotated about X spins
about its own length and does nothing visible — so every "reach forward" pose
reached sideways instead, and `working`, `typing` and `researching` all read as a
shrug. `success` and `greeting` raised the wrong way for the same reason. None of
it was visible in any test: coverage was fine, the frames differed between
states, and the numbers were all correct.

It was found by rendering all twenty-two clips to a contact sheet and looking at
it. The table now uses `aim(bone_axis, direction)` — the shortest rotation taking
a bone's rest direction to a named direction like `FORWARD`, `UP_HIGH` or
`ACROSS` — so a pose is written as where the limb ends up rather than as
arithmetic, and a wrong pose is wrong in a way the words show. All twenty-two
were re-rendered and checked: folded arms for `blocked`, a raised arm for
`greeting`, `success` and `warning`, forearms forward for `working` and `typing`,
hand to chin for `planning`, `understanding` and `reviewing`.

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
contract and the validated-package contract, twelve modules — so adding a
thirteenth is a decision recorded in that test file rather than a line in a diff.

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

`tests/companion/test_three_d_security.py`: **69 tests, 69 pass, 0 skipped** on
both hosts. None needs a GPU: every refusal happens before anything is
allocated, uploaded or decoded.

Each test changes exactly one thing about a model the validator accepts, so a
refusal is attributable — the baseline is built once by
`tests/companion/three_d_support.py` and the test's callback is the only edit.
Each asserts the *typed* refusal, not merely that something was raised.

| §28 case | Result | Refusal |
|---|---|---|
| malformed GLB | refused | truncated container, wrong magic, non-UTF-8 or invalid JSON, repeated JSON key |
| oversized GLB | refused | `ModelLimitError`, at the declared length, before parsing |
| external texture URL | refused | `ModelSecurityError` "declares a uri" |
| external buffer URI | refused | same, and the same for relative paths and `data:` URIs |
| unsupported extension | refused | by name where known (Draco, meshopt, Basis, instancing, variants), generically otherwise |
| shader injection | impossible | AST test: only `renderer.py` calls `glShaderSource`; alpha mode is a closed-table lookup; no `shader` field exists in the 3D section |
| NaN transform | refused | `ModelSecurityError` "NaN or infinite" |
| infinite transform | refused | same |
| extreme scale | refused | `ModelLimitError` "scale limit" (and "scale floor" for a vanishing one) |
| excessive vertex count | refused | `ModelLimitError` |
| excessive bones | refused | `ModelLimitError` |
| excessive morphs | refused | `ModelLimitError` |
| excessive animations | refused | `ModelLimitError` |
| excessive duration | refused | `ModelLimitError`, against the per-model second limit |
| excessive keyframes | refused | `ModelLimitError`, total and per-sampler |
| texture bomb | refused | `CharacterSecurityError` "expands beyond", in the shared bounded PNG reader |
| malformed compressed texture | refused | `CharacterSecurityError` from the PNG checksum/inflate path |
| skeleton cycle | refused | `ModelSecurityError`, both self-parent and no-root forms |
| missing root | refused | `ModelSchemaError` "missing: root" from the profile resolver |
| invalid bone reference | refused | `ModelSecurityError` "references joint N of M" |
| animation references missing bone | refused | `ModelSchemaError` "out of range" |
| invalid morph reference | refused | wrong delta count, unsupported target attribute |
| archive traversal | refused | `CharacterSecurityError`, in the existing importer |
| package-root symlink | refused | `CharacterSecurityError`, in the existing directory walker |
| hash mismatch | refused | `ModelSecurityError` "digest does not match", before parsing |
| model substitution after approval | refused | same check, asserted against two models that differ by one clip |
| character package replaced while loading | refused | staging validation happens before `os.replace`; the previous selection is retained |
| renderer reading outside package root | impossible | `asset_path` re-resolves and re-checks containment even for a trusted manifest |

Additional refusals beyond §28's list: a second buffer, sparse accessors, matrix
node transforms, non-triangle primitives, package-supplied cameras, unknown
top-level and node fields, unsupported wrap and filter modes, nodes with two
parents, unreachable nodes, buffer views reaching past the binary chunk, and a
configuration attempting to *raise* a hard ceiling.

## 30. GTK and Wayland results

**The compositor was WSLg.** WSLg is WSLg: a Weston-based Wayland compositor
bridged to Windows. It is not native GNOME on Wayland, no result below should be
read as one, and `scripts/gtk_3d_probe.py` records that sentence in its own
output rather than leaving a reader to infer it.

| | |
|---|---|
| Kernel | `6.18.33.2-microsoft-standard-WSL2` |
| Session type | `wayland`, `WAYLAND_DISPLAY=wayland-0` |
| GL renderer | `llvmpipe (LLVM 22.1.8, 256 bits)` |
| GL version | `4.6 (Core Profile) Mesa 26.1.5` |
| GTK | 4.22.4, python3-gobject 3.56.3 |

Evidence: `qualification/companion-3d-renderer/evidence/gtk-wayland.json`.

| §32 item | Result |
|---|---|
| surface creation | **pass** — `Gtk.GLArea` realized, desktop-GL context created |
| transparent presentation | **requested and reported supported** — `alphaSupported: true`; whether the desktop composited it that way was not photographed |
| character visibility | **pass** — frames rendered with the character drawn |
| 3D frame drawing | **pass** — 292 frames in an 8-second window |
| animation playback | **pass** — nine canonical states driven through the widget |
| resize | **pass** — 2 resizes handled, surface size and camera aspect updated |
| scale change | **pass** — 1 scale change |
| dock mode | **pass** — `docked` → `compact`, camera mode followed |
| speech-bubble anchor | **partial** — the anchor is computed and reported; the bubble widget itself is the 2D client's and was not drawn beside the GLArea in this probe |
| lip sync | **pass** — a mouth shape set through the widget reached the geometry |
| reduced motion | **pass** — toggled on and off through the widget |
| renderer restart | **pass** — 1 restart inside the same GTK context, character restored |
| GTK restart | **pass** — the probe's own application start/stop is a GTK lifecycle; the widget unrealizes and releases |
| runtime restart | **NOT_RUN in this probe** — covered by the §31 slice, which restarts the renderer against a live service |
| compositor disconnect | **NOT_RUN** — WSLg's compositor cannot be restarted underneath a client here |

Zero GLib criticals, zero errors, zero context losses.

Frame timing under the compositor's own clock: mean **1.11 ms**, p95 **1.74 ms**
over 292 frames, on a software rasteriser.

One environmental note recorded because it explains the warnings in the log: the
host exposes a `dzn` (D3D12-on-Vulkan) ICD and a PowerVR ICD, and Mesa refuses
both — "Zink requires the nullDescriptor feature", "dzn is not a conformant
Vulkan implementation" — and falls back to `llvmpipe`. There is no `/dev/dri`.
That is why every figure here is a software-rasteriser figure.

## 31. Integrated vertical slice

`companion/character/three_d_slice.py`, run 20 consecutive times as §34's third
gate. **36 steps: 31 ran and passed, 5 NOT_RUN with reasons.**

| Step | Result |
|---|---|
| 1 start the canonical companion service | pass |
| 2 start the companion client | pass |
| 3 confirm 3D renderer eligibility | pass — `llvmpipe`, GL 4.6 core, `accelerated: false` recorded |
| 4 validate and load the default 3D character | pass — 2,452 triangles, 23 joints, 22 clips, 11 morph targets |
| 5 draw the idle character | pass — pixels read back, coverage asserted |
| 6 submit a typed task | pass |
| 7 character enters understanding | pass |
| 8 character enters planning | pass |
| 9 local agent provider runs | pass |
| 10 character enters working | pass |
| 11 provider proposes a harmless desktop action | pass — `desktop.settings.open` |
| 12 Approval Centre appears | pass |
| 13 character enters waiting-for-approval | pass — frame read back at that state |
| 14 user approves | pass |
| 15 desktop action executes | pass |
| 16 character returns to working | pass |
| 17 task completes | pass |
| 18 character enters success | pass |
| 19 voice speaks the result | pass — see §35 on what "voice" means here |
| 20 voice-produced visemes animate the 3D mouth | pass — 7 distinct shapes drawn, neutral at the end |
| 21 start push-to-talk | **NOT_RUN** — no capture device and no local recogniser |
| 22 character enters listening | **NOT_RUN** — same |
| 23 speech recognition finalizes | **NOT_RUN** — same |
| 24 character enters waiting-for-user | **NOT_RUN** — same |
| 25 confirm the transcript | **NOT_RUN** — same |
| 26 a new task begins | pass — a second task id, distinct from the first |
| 27 trigger controlled degradation | pass — full-3d while healthy |
| 28 full 3D → lightweight 3D | pass — on sustained frame time |
| 29 the lightweight rung still draws | pass — pixels read back |
| 30 lightweight 3D → animated 2D | pass |
| 31 task identity unchanged across degradation | pass — id, state and summary compared against the record taken before |
| 32 removing the pressure permits recovery | pass |
| 33 recovery used hysteresis | pass — `stable-recovery` event present |
| 34 restart the 3D renderer | pass |
| 35 restore the character and canonical presentation | pass — pixels read back |
| 36 no task repeated or cancelled | pass — same id, same lifecycle epoch, not cancelled or failed |

The steps that read pixels do so from a real offscreen framebuffer through
`glReadPixels`, so "the character appeared" is a measurement rather than an
assumption. The degradation steps drive the same `AdaptiveRendererSelector` a
desktop uses, through the same signal type.

The slice substitutes one thing and names it: the capability *signals* a machine
with a display and a GPU would produce, confined to a single named dictionary,
because a host with no monitor is correctly told `text-only` and every visual
step would be unreachable. Everything else — the task, the approval, the events,
the result, the graphics context, the pixels — is real.

## 32. Stress gates

**All three gates ran on one exact commit: `75bc033b015cddc568ee6b09477327f8c6708498`.**
Every iteration of every gate records that commit in its own record — per
iteration rather than once per run, so a tree that moved underneath a gate could
not be hidden by a header.

Host: Fedora Linux 44 on WSL2 (kernel `6.18.33.2-microsoft-standard-WSL2`),
Python 3.14.3, Mesa 26.1.5 (`llvmpipe`), GTK 4.22.4. The trees are ext4 copies,
never `/mnt/c` — a package under DrvFs presents every file as 0777 and the
character validator correctly refuses an executable file in a package.

| Gate | Required | Result | Longest consecutive | Net growth | Held resources at end |
|---|---|---|---|---|---|
| 3D-renderer lifecycles | 100 consecutive | **100 / 100** | 100 | none | none |
| complete companion suites | 50 consecutive | **50 / 50** | 50 | none | none |
| installed 3D vertical slices | 20 consecutive | **20 / 20** | 20 | none | none |

`gate-verdicts.json` records **`allPassed: true`**. No leak suspicions in any
gate; no absolute violations; no residual held GPU resource and no retained
renderer object at the end of any run.

Durations: the renderer lifecycle runs in a median **60 ms** (min 55 ms, max
166 ms, 6.2 s for all hundred); the installed slice in a median **759 ms** (min
743 ms, max 1.40 s); a complete companion suite in a median **54.4 s** (min
53.7 s, max 56.2 s, 45 minutes for all fifty).

Warm-up, measured on iteration 1 and excluded from the verdict by the rule
above: the lifecycle gate's first iteration costs 1 descriptor and 99 MiB of RSS
— Mesa mapping `llvmpipe` and three shader programs compiling — and every
iteration after it costs nothing. The suite gate's first iteration additionally
brings up one runtime, one service and one worker of each kind, which is the
first test module constructing its fixtures.

RSS across a whole gate, baseline to final: lifecycle **23 MiB → 148 MiB**,
slice **23 MiB → 207 MiB**, suite **23 MiB → 278 MiB**. All of that growth is in
the first iterations; the per-iteration deltas are zero from iteration 2 onward,
which is what the net-growth column is reporting.

The character covered **15.6 %** of the surface in every one of the hundred
lifecycle iterations — identical to five decimal places, which is what a
deterministic renderer with a seeded procedural behaviour should produce.

**Which user each gate runs as.** Gates 1 and 3 run as `root`: WSLg gives root
the graphical session and the EGL device. Gate 2 runs as `bunny`, because root
ignores read-only-directory permission bits and
`test_store_durability…test_a_read_only_directory_fails_before_any_replacement`
therefore cannot pass as root — and excluding it would mean not running the
complete suite. That single failure is reproduced and recorded in
`linux-suite-root.log` so the difference is visible rather than asserted.

Per-iteration tracking, from `scripts/companion_stress.py`'s inventories:

thread delta, non-daemon thread delta, file-descriptor delta, socket-descriptor
delta, unix companion sockets, live services, live runtimes, temporary
directories, child processes, zombies, **GPU contexts**, **live GPU contexts**,
**renderers**, **active models**, **GL objects**, **textures**, **buffers**,
**vertex arrays**, **shader programs**, **framebuffers**, **animation timers**,
**GTK GL areas**, **renderer workers**, RSS, plus the absolutes (queue depth,
active requests, executor leases, consent waiters, held answers, pending
approvals, locked stores), the ledger's own `leakSuspicions`, task identity,
exit status and duration.

**The verdict rule**, unchanged from the earlier phases: a *growth* between
iterations is a failure and a *cleanup* is not, the verdict is taken on the
**net** rather than on the sum of positives, and **iteration 1 is measured and
does not fail the gate** — a renderer's first run compiles three shader
programs, maps the driver and decodes a texture, and every run after it does
none of that. Summing from iteration 2 means a real leak of one object per run
still totals ninety-nine and still fails.

Two columns are this phase's own and neither is a delta. `glTableLoadedAtEnd` is
§30 in counter form: whether `companion.character.three_d.gl._LOADED` is set at
the end of a run. It is *correct* for the 3D gates and would be *wrong* for a
suite gate that never selected a 3D presentation, so the collector reports the
value rather than a verdict. `leakSuspicions` is the resource ledger's own record
of a driver call that raised during release; it is failed on, because unlike a
counter it names the object that could not be given back.

Evidence: `qualification/companion-3d-renderer/evidence/`.

## 33. Performance measurements

**Read every figure below as a software-rasteriser figure.** The reference host
has no `/dev/dri`; Mesa reports `llvmpipe`, `Accelerated: no`. That makes these
numbers a *floor* rather than an estimate of what a GPU does, which is a useful
thing to know and is not the same thing as knowing what a GPU does.

### Memory, one component at a time

`scripts/ops/renderer3d-memory.py` runs each stage in its own interpreter and
reports its own RSS and PSS, because §35 asks for these to be separated and the
only honest way to separate them is not to have the others in the process. **No
figure below includes GTK, and none includes a local language-model server:
neither was in any of these processes.**

| Stage | RSS | PSS | Above a bare interpreter (RSS) |
|---|---|---|---|
| bare interpreter | 10.9 MB | 6.1 MB | — |
| + `companion.runtime`, `service`, `presentation` | 32.8 MB | 24.2 MB | 22.0 MB |
| + the 3D subsystem imported (no context) | 24.0 MB | 15.5 MB | 13.1 MB |
| + the 3D package validated (GLB, textures, skeleton, clips) | 22.2 MB | 14.2 MB | 11.4 MB |
| + an EGL/llvmpipe context created | 76.3 MB | 48.7 MB | 65.3 MB |
| renderer idle (context + package, nothing uploaded) | 83.3 MB | 53.7 MB | 72.3 MB |
| character loaded (model uploaded to the GPU) | 96.0 MB | 64.9 MB | 85.0 MB |
| character drawn (241 frames offscreen at 288×360) | 191.7 MB | 151.4 MB | 181.0 MB |

What that table says, in order of size:

* **The 3D code is small.** Importing the whole subsystem costs 13.1 MB and
  validating the character costs 11.4 MB — both less than importing the
  companion runtime.
* **The graphics stack is the cost.** Creating a context takes RSS from 22 MB to
  76 MB. That is Mesa mapping `llvmpipe`, and it is mostly *shared*, which is
  what the PSS column is for: 48.7 MB against 76.3 MB.
* **Uploading the character costs 12.6 MB** on top of the context, against a
  model whose declared GPU footprint is 269,264 bytes and whose ledger reports
  283,504 bytes. The difference is the driver's own copies of the buffers, which
  on a software rasteriser live in system memory.
* **Drawing costs the most, and it is llvmpipe's.** 241 frames take RSS from 96 MB
  to 192 MB — the rasteriser's per-thread tile and scratch allocations, which
  scale with surface size and core count. On hardware this line would look
  completely different, and it is the single strongest reason §38 asks for a GPU.

GPU-side, from the model descriptor and the resource ledger: estimated
**269,264 bytes**, ledger-observed **283,504 bytes**, decoded texture memory
**16,384 bytes** (one 64×64 RGBA), model decoded size **303,984 bytes** on disk.

### Timing

From the 20-iteration slice gate (`renderer3d-measurements.json`), 20 samples:

| Measurement | min | median | p95 | max |
|---|---|---|---|---|
| model validation | 15.3 ms | **16.3 ms** | 18.5 ms | 26.7 ms |
| model load (upload to GPU) | 7.4 ms | **8.1 ms** | 9.6 ms | 16.0 ms |
| first frame | 4.6 ms | **5.0 ms** | 7.1 ms | 7.3 ms |
| frame time, mean over a slice | 0.71 ms | **0.77 ms** | 0.85 ms | 1.00 ms |
| frame time, p95 over a slice | 1.56 ms | **2.10 ms** | 2.72 ms | 2.85 ms |
| renderer restart | 12.6 ms | **15.6 ms** | 20.3 ms | 21.3 ms |
| dropped frames | 0 | **0** | 0 | 0 |
| live GPU resources while a slice is drawing | 32 | **32** | 32 | 32 |

From a 241-frame offscreen run at 288×360: first frame **7.4 ms**, mean
**1.17 ms**, p95 **3.09 ms**, max **10.2 ms**, **0 dropped**.

From the GTK probe under WSLg, on the compositor's own clock: mean **1.11 ms**,
p95 **1.74 ms** over 292 frames.

The first frame is the expensive one everywhere, and it is where three shader
programs are compiled and linked. It is measured separately for that reason,
and it is why `FrameHealth` ignores samples taken before twenty frames exist —
otherwise every machine that ever started a renderer would degrade itself on its
own first frame.

Renderer lifecycle (gate 1: create a context, validate, upload, draw nine
states, move the mouth, change rung, restart, release): min **55 ms**, median
**59 ms**, max **166 ms**.

Degradation and fallback latency are not separately timed. The rung change is a
pure function evaluated inside a frame — `AdaptiveRendererSelector.evaluate` on
already-gathered signals — and the *observable* latency is the renderer swap that
follows it, which is the "renderer restart" row above (median 18 ms) for a 3D→3D
change and a `StaticImageRenderer` construction for 3D→2D. Recovery latency is
governed by hysteresis rather than by work: three healthy samples and a 2-second
delay by policy, 20 seconds by the default budget's `recovery_hold_seconds`.
Reporting a millisecond figure for something a policy decides would be dressing a
constant up as a measurement.

Lip-sync latency is not separately timed either: a mouth shape is applied inside
the frame that draws it, so its latency is the frame time.

## 34. Complete test results

### The 3D suites

**229 tests, all passing, zero failures.** On Linux every one runs; on Windows
the graphics ones skip rather than pass.

| Module | Tests | Linux | Windows |
|---|---|---|---|
| `test_three_d_security.py` | 69 | 69 pass | 69 pass |
| `test_three_d_animation.py` | 50 | 50 pass | 50 pass |
| `test_three_d_package.py` | 38 | 38 pass | 38 pass |
| `test_three_d_ladder.py` | 27 | 27 pass | 27 pass |
| `test_three_d_diagnostics.py` | 16 | 16 pass | 8 pass, 8 skip (no graphics) |
| `test_three_d_render.py` | 19 | 19 pass | skipped (no graphics) |
| `test_three_d_isolation.py` | 11 | 11 pass | 11 pass |
| `test_three_d_preservation.py` | 4 | 4 pass | 4 pass |

`test_three_d_render.py` is the file the ladder's claim stands on: it creates a
real OpenGL context, uploads the shipped model, draws frames and reads the
pixels back. It **skips rather than passes** where no context can be made, so it
cannot become a rubber stamp on a machine without graphics.

### The companion suite

| Where | Tests | Result |
|---|---|---|
| Windows 11, Python 3.14.3 | 1,733 | OK, 54 skipped |
| Fedora 44 WSL2, as `root` | 1,748 | 1 failure, 2 skipped — the read-only-directory test, which cannot pass as root |
| Fedora 44 WSL2, as `bunny` | 1,748 | OK, 2 skipped — fifty times consecutively |
| `tests/image` (build-input closure) | 50 | OK |

The Linux runs execute fifteen more tests and skip fifty fewer than Windows,
because the graphics tests run there.

### Changed tests, and why

Four existing tests asserted that 3D was *not* implemented. Each was the line
holding the claim out, so each was changed to say what let it in rather than
deleted:

* `test_only_implemented_presentations_can_be_selected` now asserts the 3D rungs
  are present **and** that `tests/companion/test_three_d_render.py` exists —
  a rung may be claimed only if the file that draws with it does.
* `test_a_capable_machine_is_given_animation_but_never_3d` became
  `test_a_capable_machine_is_now_given_the_3d_rung_it_was_always_eligible_for`,
  and two new tests were added beside it: a machine with no GPU is still not
  eligible, and a mid-memory machine gets the lightweight rung.
* `test_unsupported_presentation_type_is_rejected` used `full-3d` as its example
  of a reserved name. It now uses `skeletal-2d`, which is still reserved, and a
  second test asserts a 2D package cannot claim a 3D presentation.
* `test_renderer_explain_shows_state_fallback_and_trust` asserted the diagnostic
  note named `animated-2d` as the top of what the build implements. There is no
  longer a rung above what is implemented, so it asserts what the note is *for*.

Two schema tests were rewritten to compare the published JSON schema against
`IMPLEMENTED_PRESENTATIONS` rather than repeating a literal list, so the contract
and the implementation cannot drift apart in either direction.

## 35. Known limitations

**Measured only on a software rasteriser.** The reference host reports
`llvmpipe (LLVM 22.1.8, 256 bits)`, OpenGL 4.6 core, `Accelerated: no`, and has
no `/dev/dri`. Every frame time in §33 is a software-rasteriser figure. That is a
genuinely useful measurement — it is the *floor*, and the character draws at it —
but nothing here says what a GPU does, and the degradation thresholds in
`budget.py` were chosen from the ladder's shape rather than from hardware
measurement.

**The 3D character is not the default selection.** Both packages ship; the 2D one
remains what a machine draws out of the box, and the 3D one is selected with
`bunny-os companion character select bunny-default-3d`. §24 requires a package
change to be user-initiated, and promoting the 3D character would have been this
phase changing what every existing machine draws as a side effect of adding a
renderer. Making it the default is a product decision for a later phase.

**The renderer's `none` motion mode is implemented and tested but the ladder does
not select it.** `no_animation` drops to `static-image` instead, because a still
3D render costs more than the static PNG for the same visual result. The mode is
reachable through `set_no_animation` and is exercised by tests.

**Lip sync in the slice is link-driven rather than worker-driven.** The events
are real `VoiceEvent` values through the real `VisemeLink` — its request
matching, ordering, revision matching and neutral reset all run — but the
*producer* is the slice, because this host has no speech-synthesis provider and
therefore no worker to produce them. The worker-to-link half was established by
the voice-closure phase; this phase establishes link-to-3D-mouth. Both halves
exist; they have not been demonstrated in one process on one host.

**No hardware-accelerated GPU-context-loss test.** Context loss is produced by
`simulate_loss` and by destroying the EGL context underneath a live renderer.
A real GPU reset (TDR, driver crash, hot-unplug) has not been observed.

**Skinning is CPU-composed per joint.** One 4x4 per joint per frame in pure
Python. At 23 joints this is not the bottleneck; a 96-joint character wants
re-measuring, and NumPy or a C helper would be the answer if it is.

**No mipmaps.** The character occupies a fixed fraction of a small surface, a mip
chain costs a third more memory, and generating one on llvmpipe is measurable.
Linear minification is the trade.

**PNG only.** A second image decoder is a second set of bombs. A package with
JPEG textures is refused rather than converted.

**One skin per model.** A Bunny character declares exactly one skin. Multi-skin
characters (a rigged prop held by a rigged hand) are refused.

**The upper-body overlay is one bone subtree.** Everything below `chest`.
A package cannot declare its own mask.

**GTK results are from WSLg.** See §30. WSLg is a Weston-based Wayland
compositor bridged to Windows; it is not native GNOME on Wayland and no result
in §30 should be read as one.

## 36. NOT_RUN items

Recorded as NOT_RUN with a reason, never as passes:

| Item | Reason |
|---|---|
| slice steps 21–25 (push-to-talk, listening, recognition, waiting-for-user, transcript) | the runtime advertises speech input and refuses the capture: "no local speech recogniser is installed; capture without recognition would be a recording nobody asked for" |
| hardware-GPU frame times | no `/dev/dri` and no accelerated renderer on the reference host |
| native GNOME Wayland session | not available on this machine |
| X11 session | not available on this machine |
| compositor disconnect during rendering | WSLg's compositor cannot be restarted underneath a client here |
| a booted Bunny OS image drawing the character | no image was built this phase; §39 |
| ARM | no ARM host |
| physical-hardware validation | §38 |

Every NOT_RUN appears in the slice report's `notRun` list and in the gate
evidence, not only in this document.

## 37. Remaining production-art work

The shipped character is a **reference**, and §25 asks for exactly that: a
stylised human-shaped figure of 2,452 triangles, rigged to the profile, with the
eleven face morphs the viseme and expression maps need and one clip per canonical
state. What real production art would add:

* **Geometry and materials.** A sculpted mesh with proper topology, UV layout and
  authored textures rather than a generated gradient; hair and clothing as
  separate rigged pieces rather than proud tubes.
* **Hands.** The profile supports finger bones by pattern; the reference
  character has none, so its hands are boxes and it cannot point, count or
  gesture with fingers.
* **Eyelids.** The reference blinks by flattening the eyeball on the eye bone.
  A production character would have eyelid geometry driven by a blink morph;
  the renderer already prefers a `blink` morph target where one exists.
* **Facial rig.** Eleven analytic morphs cover the states; a production face
  would have thirty to fifty authored shapes and separate brow, lid, cheek and
  lip corners.
* **Animation.** The clips are keyframed by hand in the generator from a few
  poses each. Production clips would be authored or captured, with overlapping
  action, weight and follow-through.
* **The 2D fallback frames.** These are flat arithmetic silhouettes. They are
  legible and they are not art; §22's fallback deserves renders of the same
  character.
* **A second character.** The importer, the profile aliasing and the package
  schema exist so that a character from a different tool can be installed
  without changing the runtime. That path is tested against synthetic models and
  the built-in package; it has not been exercised against a character authored
  in Blender, VRoid or Mixamo by somebody else.

## 38. Remaining physical-hardware validation

Nothing in this phase ran on physical hardware. Specifically not run:

* an Intel, AMD or NVIDIA GPU — so no measurement of the frame times the
  thresholds in `budget.py` were chosen to sit above, and no observation of the
  full rung being *held* rather than immediately degraded;
* a real display server on a laptop panel, so no measurement of transparent
  compositing against a real desktop, of HiDPI scaling, or of the character at
  a physical size;
* battery and thermal transitions on a machine that has them — the degradation
  rules read those signals from the capability inventory and are tested with
  synthetic signals;
* a GPU reset or driver crash;
* an ARM machine.

`PHYSICAL_HARDWARE_EVIDENCE_PLAN.md` is the existing plan for this class of
work; the 3D renderer adds the items above to it.

## 39. Reproducibility implications

**No reproducibility candidate was created and none is claimed.** The directive
forbade creating one during implementation and this phase did not.

What this phase does to the build:

* **52 installed paths, no new route, no new destination, no new RPM.** The
  companion package route and the character-package tree route both already
  existed. Nothing was added to `build/packages/*.txt`.
* **The three-builder reproducibility result recorded at Commit C `225a5e1` /
  Commit D `f65b65c` is not invalidated and is not extended.** It is a statement
  about those commits. A future candidate on this branch would have to be built
  and compared afresh, and [[pinned-base-digests-are-not-durable]] applies: the
  `fedora-bootc:44` base is rebuilt daily and old digests vanish.
* **The new package's determinism is a property of the generator, not of the
  build.** `scripts/build_default_character_3d.py` produces a byte-identical GLB
  on Linux and Windows (`88e9364f…`, 304,380 bytes, verified on both), which
  means a future rebuild of the *asset* is reproducible. Getting there required
  a portable deflate encoder and float quantisation, both recorded in §23 and in
  the script.
* **`assets/companion/characters/** -text`** already covered the new package, so
  its files round-trip git byte-exactly on a Windows checkout — verified:
  `git cat-file` returns the same byte count as the working tree. Without
  that attribute the manifest digest would fail on one of the two platforms,
  which is the failure the 2D character phase had and fixed.
* **Every commit changes the OCI configuration digest** through the revision
  label and `/usr/lib/bunny-os/release.json`. An unchanged layer digest is not an
  unchanged image.

What a future reproducibility phase would need to check about this one: that the
GLB and its PNGs land in the image with the bytes recorded here, and that adding
a 300 KB binary asset to `/usr/share` does not perturb layer ordering — neither
of which this phase measured, because measuring them means building an image and
that is a candidate.

## Completion standard

The twenty conditions, each answered by the section that measured it.

| # | Condition | Where | Result |
|---|---|---|---|
| 1 | one validated original 3D character renders | §23, §30, §31 | **met** — pixels read back from a real context, and drawn under a compositor |
| 2 | the character uses canonical `PresentationState` | §5, §34 | **met** — the presenter-path tests start at `CharacterPresenter` with a projection |
| 3 | no second runtime or projection exists | §26 | **met** — the import graph is read, not asserted |
| 4 | skeletal animation works | §31, §34 | **met** — two times in one clip draw different pictures |
| 5 | animation transitions work | §9, §10 | **met** — crossfade weight 0→1, priority holds, return-to-idle |
| 6 | facial expressions work | §11, §34 | **met** — neutral and happy draw differently |
| 7 | voice visemes animate the 3D mouth | §12, §31 | **met** — through the canonical `VisemeLink`; see §35 on the producer |
| 8 | listening and transcribing states render | §30, §31 | **met** |
| 9 | approval and error states override decorative animation | §9 | **met** — the less urgent state is *held*, not merely ranked lower |
| 10 | character packages cannot execute code | §7, §29 | **met** — no executable asset type, no script field, no active content |
| 11 | packages cannot supply arbitrary shaders | §17, §29 | **met** — asserted from the AST |
| 12 | GPU and context loss degrade safely | §21, §34 | **met** — including a context destroyed underneath a live renderer |
| 13 | full 3D → lightweight 3D → animated 2D works | §20, §31 | **met** |
| 14 | task identity and result unchanged across degradation | §31 step 31, step 36 | **met** |
| 15 | reduced-motion mode works | §20, §34 | **met** — the rung is kept and the motion is removed |
| 16 | headless fallback works | §27 | **met** — and no GPU library is opened to find out |
| 17 | the 100/50/20 gates pass on one commit | §32 | **met** — `allPassed: true` at `75bc033`, all three |
| 18 | Linux compositor rendering is measured | §30 | **met** — on WSLg, recorded as WSLg |
| 19 | memory and frame-time metrics are reported honestly | §33, §35 | **met** — separated per component, and labelled software-rasteriser throughout |
| 20 | no release or reproducibility qualification is claimed | §39 | **met** — no image was built and no candidate created |
