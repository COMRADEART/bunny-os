# Bunny Companion character renderer — report

The first secure, adaptive character renderer for the companion: a validated
package format, a hardened importer, static and animated 2D renderers, a pure
state mapper over the canonical projection, speech bubbles, generic lip-sync,
capability-driven degradation, crash recovery and one original default package.

Architecture notes: [`docs/COMPANION_CHARACTER_RENDERER.md`](docs/COMPANION_CHARACTER_RENDERER.md).
Reconciliation with the prior implementation:
[`docs/COMPANION_CHARACTER_OVERLAP_MATRIX.md`](docs/COMPANION_CHARACTER_OVERLAP_MATRIX.md).

---

## 1. Exact starting SHA

| | |
| --- | --- |
| Base branch | `feature/companion-runtime-integration` |
| Commit | `8ffc4336bd695df88aeba38f08286db89447736c` |
| Expected | `8ffc433` — **verified in full before any file was touched** |
| Working tree | clean |

## 2. Branch and commit lineage

`feature/companion-character-renderer`, created at `8ffc4336`.

The branch name was already taken by a prior implementation at
`c2f2acf798f54c034281abe7a45996a2100de63c`, based on `2f39d58` (runtime-core)
and checked out in a temporary worktree. Nothing was lost: it is preserved at
`archive/companion-character-renderer-c2f2acf`, the worktree was removed after
confirming it held no uncommitted work, and the name was re-pointed at the
verified base.

No commit was made to `feature/companion-runtime-integration`,
`feature/companion-runtime-core`, `codex/companion-runtime-ux-shell` or
`feature/capability-image-integration`. No path under `qualification/`,
`build/inputs/` or `evidence/` appears in this branch's diff.

## 3. Architecture

```text
canonical companion events → canonical presentation projection
    → character state mapper → validated character package
    → renderer selector → static image | animated 2D | text
    → the companion window
```

The renderer selects no executor, chooses no provider, validates no approval,
executes no tool, reads no task payload, recalculates no capability, stores no
second task state and generates no hidden explanation. The last four are
asserted from the **import graph** on every test run, so a future
`from companion.store import …` fails the build rather than the review.

## 4. File-by-file changes

**New (28):**

```
companion/character/{__init__,errors,schema,image,package,importer}.py   package layer
companion/character/{mapper,integration}.py                             the pure mapper + the one door
companion/character/{renderer,static_renderer,animated_renderer}.py     renderers
companion/character/{controller,adaptation,bubble,lipsync,positioning}.py
companion/character/{surface,diagnostics,defaults,demo,performance}.py
companion/character/vertical_slice.py                                   §20's 24 steps
schemas/companion-character-package-v1.schema.json
assets/companion/characters/default-bunny/{manifest.json,LICENSE.txt,assets/*.png}
scripts/generate-default-character-assets.py
scripts/character_measure.py
docs/COMPANION_CHARACTER_RENDERER.md
docs/COMPANION_CHARACTER_OVERLAP_MATRIX.md
docs/COMPANION_CHARACTER_GENERATION.md
docs/templates/companion-character-prompts.md
COMPANION_CHARACTER_RENDERER_REPORT.md
tests/companion/character_support.py
tests/companion/test_character_{package_validation,importer,image_boundary,
                                mapper,renderers,adaptation,speech_position,
                                cli_vertical}.py
```

**Modified (8):**

| File | Change | Why |
| --- | --- | --- |
| `companion/presentation.py` | `animated-2d` added to `IMPLEMENTED_PRESENTATIONS` | A renderer now exists behind it. One line, moved only when earned. |
| `schemas/companion-presentation-state.schema.json` | `animated-2d` added to the implementation enum | Same reason |
| `companion/gtk_shell.py` | character presenter embedded in the one client | §2's surface, without a second application |
| `companion/cli.py` | `character` and `renderer` command groups, `run-character-slice` | §23's diagnostics |
| `build/scripts/install-root.py` | `copy_python_package`, capability manifests, character assets | Source-only install; the manifests and assets the runtime needs |
| `build/Containerfile` | `COPY assets capability companion` | **Fixes a live defect**; see §7 below |
| `capability/registry.py` | comment corrected | The installed manifest path is now real |
| `.gitattributes` | `assets/companion/characters/** -text` | Manifest-attested bytes must round-trip git |
| `Makefile` | three character targets | |

## 5. Package schema

`schemas/companion-character-package-v1.schema.json`. Every §3 field is present
and required except the three explicitly optional ones (`minimumBunnyOsVersion`,
`generationProvenance`, `sourcePromptMetadata`). Strict `additionalProperties`
at every level, bounded strings and arrays, a SHA-256 per asset, and a static
fallback that cannot be omitted.

Data-only by suffix allowlist: `.png`, `.webp`, `.txt`, `.md`, `.json`.
Everything else is refused, including `.svg` — a scriptable format this build
will not load from an untrusted package.

## 6. Package validator

Refuses, with a distinct typed error each: symlinked root, symlink, device or
special file, hard link, executable mode, repeated path, file-count or
byte-total overrun, missing or oversized manifest, duplicate JSON keys,
undeclared file, missing declared file, size mismatch, digest mismatch, image
dimension or media-type mismatch, binary or executable signature in a text
asset, credential-shaped text, and an empty licence.

Images are validated **structurally before any desktop decoder sees them**: full
PNG container parse with per-chunk CRCs, unknown critical chunks refused,
interlacing refused, and a *bounded* inflate against the declared dimensions.
APNG and animated WebP are rejected outright so a package cannot smuggle a
second, unbounded animation timeline through one frame.

## 7. Importer security

Archives are inspected **before** extraction — entry count, traversal, absolute
and drive-qualified paths, repeats, encryption, compression method, non-regular
file types, executable modes, per-entry and total expansion, per-entry and
whole-archive compression ratios — and bounded again *while writing*, because an
archive can lie about its own sizes. Directories are validated first and then
only the manifest's own paths are copied, each opened `O_NOFOLLOW`.

Installation is atomic and never in place: stage, validate, re-validate,
`os.replace`, validate at the destination, then register. The previous working
version is untouched throughout.

## 8. Package trust model

Eight states. `integrity_verified` and `creator_trusted` are separate fields and
every CLI path that reports a successful validation carries a `warning` saying
integrity is not creator trust. `built-in` cannot be asserted by the user
registry. `character trust` may set only `disabled`, `quarantined` or
`imported-unverified`; the rest are properties of provenance or bytes, not
opinions.

## 9. State mapper

Pure, and led by the canonical phase. `CANONICAL_PHASE_STATES` covers every
member of `PRESENTATION_PHASES` (asserted). Refinement is filtered by
`priority_rank(candidate) <= priority_rank(base)`, with one declared exception
for *narrowings* — `working` drawn as `researching` or `typing`, which §6 groups
as "active work". Client-side facts are consulted only in `_REFINABLE_PHASES`,
which excludes error, blocked, approval and cancellation.

Produces character state, animation id, expression, mouth state, playback mode,
transition policy, bubble anchor, accessibility description, effective
presentation, degradation explanation and the fallback chain actually walked.

## 10. Renderer interface

One `CharacterRenderer` ABC: load, unload, show state, set expression, play,
interrupt, pause, resume, set mouth shape, scale, visibility, opacity, attach
and detach bubble, report frame timing, dropped frames and memory estimate,
report failure, reset, and restore state after restart. Assets are reachable
only through `ValidatedPackage.asset_path`, which re-checks containment under
the package root on every call.

## 11. Static renderer

PNG and WebP, transparent, aspect preserved, bounded decoded dimensions,
scaling, positioning, bubble anchoring, reduced motion and a text-only floor. A
broken asset degrades; it does not terminate anything.

## 12. Animated renderer

Validated frame sequences — one representation, chosen because it reuses the
static decoder and adds no second animation system. Looping and one-shot,
interruptible, completion handling, pause and resume, frame-rate cap,
dropped-frame counting, return-to-idle, unload, resource release and restart.
The interruption queue holds exactly one entry.

## 13. Transition policy

All six transition types. Errors, warnings, approvals, cancellation and
listening interrupt anything including `complete-current`. Reduced motion
collapses everything to `immediate`. A looping animation may not declare a
completion-dependent transition and the schema refuses one that does.

## 14. Bubble integration

The bubble shows the projection's own sentence, chosen by `bubble_request_for`,
never composed. Character-relative anchoring, automatic side selection,
screen-edge avoidance, clamping, maximum width, wrapping, partial and final
captions, keyboard accessibility and screen-reader announcement flags, and
high-contrast styling. Approval and error bubbles are persistent.

## 15. Lip-sync model

Seven generic mouth shapes. Timestamped visemes, phoneme-to-viseme mappings,
amplitude fallback and speaking-state fallback. Monotonic timestamps enforced,
sequence bounded, drift detected and reported, missing shapes fall back, neutral
on end or cancellation, neutral throughout under reduced motion.

**No phoneme accuracy is claimed** — the slice's own output says so — because
none has been measured.

## 16. Adaptive degradation

`animated-2d → static-image → text-only`, ceiling taken from the canonical
recommendation. `from_recommendation` is the only constructor; the prior
`from_execution_plan` is gone and a test asserts it.

Degradation is immediate. Recovery needs three consecutive healthy samples and a
minimum delay. Renderer *health* recovery is separate and slower. Every
degradation event carries `taskContinues: true`.

## 17. Failure recovery

Typed event → release resources → static → text-only → task untouched →
`_RestartGuard` (three restarts a minute, then refusal) → health restored only
after a stable interval. Covers decoder error, missing asset, corrupt frame,
renderer exception, surface loss, package removed, display removed, memory
pressure and repeated crashes.

## 18. Default package

`assets/companion/characters/default-bunny`: original art for Bunny OS,
GPL-3.0-or-later, twelve PNG frames, a manifest and a licence. Static fallback
plus idle, listening, planning, working, reviewing, speaking, success, warning,
error and sleeping; its state map covers every required character state. It goes
through **the same validator** as an imported package — being built in buys no
exemption, and a test asserts the state map is complete.

## 19. Accessibility

Reduced motion, no-animation, text-only, screen-reader descriptions,
colour-independent meaning, adjustable character and bubble scale, disable
flashing, frame-rate cap to 1 fps, high-contrast compatibility, and visual
speaking and listening indicators. No required information exists only in
animation: `text_only_view()` renders the entire surface, including which
renderer is running.

## 20. Test results

Host: Windows 11 (10.0.26200), CPython 3.14.6, `jsonschema` present.

| Suite | Tests | Result |
| --- | ---: | --- |
| `tests/companion` (all) | **531** | OK on ~2 runs in 3; see the flake note below |
| — character tests | 185 | OK, 2 skipped |
| — `test_character_package_validation.py` | 32 | OK |
| — `test_character_speech_position.py` | 30 | OK |
| — `test_character_mapper.py` | 30 | OK |
| — `test_character_renderers.py` | 25 | OK |
| — `test_character_importer.py` | 21 | OK |
| — `test_character_adaptation.py` | 21 | OK |
| — `test_character_cli_vertical.py` | 18 | OK |
| — `test_character_image_boundary.py` | 8 | OK |
| `scripts/task.py test-capability` | 697 | OK |
| `scripts/task.py validate` | 49 schemas, 22 units | **PASS** |
| `companion run-character-slice` | 24 steps | **passed**, 1 `NOT_RUN` |
| `companion run-integration-slice` | 27 steps | passed |

**§18's security list**, 61 tests across the three package files: archive
traversal, absolute paths, symlinks, hard links, device entries, executable
files, executable mode, scriptable SVG, HTML, JavaScript, Python, shell files,
native libraries, external URLs, undeclared assets, hash mismatch, compression
bomb, excessive file count, excessive decoded dimensions, oversized frame,
malformed animation metadata, atomic-install interruption, active-package
replacement, package-root symlink substitution and renderer access outside the
package root.

**§19's functional list** is covered by the mapper, renderer, adaptation and
speech tests, all of which run without a compositor.

**A test-harness limitation worth naming.** This host has no `AF_UNIX`, so the
companion protocol falls back to loopback TCP (documented in the integration
phase as a developer transport). Every service the suite starts and every poll
it makes consumes an ephemeral port with a 120-second `TIME_WAIT`, so running
the full suite repeatedly back-to-back exhausted the range and produced failures
in the slice and IPC tests that had nothing to do with the code. Two changes
removed the pressure rather than hiding it:

- each vertical slice now runs **once per test class** and its result is
  asserted many times, rather than being re-run per test — it is deterministic
  and expensive, so this is better design regardless;
- `ServiceTestCase.consent_wait_seconds` is now longer than the test's own
  answering deadline. At 8 s against a 45 s budget, the runtime's consent could
  lapse while a test was still working through its approvals, and the test then
  failed at an unrelated step. The service must outlast the test, not race it.

The shipped transport is a Unix socket with no port to exhaust. None of this
affects the product; it is recorded because a flaky gate costs real time and the
cause is not obvious from the failure.

**An unresolved flake, stated plainly.** After those two changes the full
companion suite still fails roughly one run in three, always in the
service-driven tests — most often
`test_integration_slice.VerticalSliceTests` (a step reporting that the task did
not reach `success`) or `test_protocol_ipc.OperationTests`. What is known:

- it does **not** reproduce in isolation: `run_slice` passed 8/8 consecutively
  when run directly, and `test_protocol_ipc` passed 6/6 as a module;
- it appears only inside the full in-process suite, where many services have
  been started and closed beforehand;
- it correlates loosely with wall-clock slowdown (failing whole-suite runs took
  100–145 s against 40 s for passing ones) but has also occurred on a fast run,
  so load is not the whole story;
- the character suite (185 tests) has not failed once across every run.

What has been ruled out: timeout budgets (a task completes in ~0.2 s against a
45 s budget, and one loopback round trip measures 8.4 ms), and the consent
race described above.

It is **not** diagnosed, and it is not being reported as if it were. The most
likely remaining mechanisms are ephemeral-port pressure from the loopback
developer transport and residual threads from previously closed services in the
same interpreter — both properties of running this on a host with no `AF_UNIX`.
Confirming that needs a Linux run over the real Unix socket, which is also where
the memory figures have to be taken. Until then this is an open item, listed in
§24.

> **Correction — 2026-08-05 UTC, `feature/companion-linux-validation`.**
>
> The paragraph above is left standing because it is the record of what was
> believed, and both of the mechanisms it calls "most likely" were wrong. The
> flake is diagnosed. It was two defects, and neither was a property of running
> without `AF_UNIX`:
>
> 1. **The store's writer had no retry.** `_read_bytes_stable` already
>    documented that Windows refuses a rename over a path a reader holds open,
>    and retried — but only on the reading side. `os.replace` raised
>    `[WinError 5]`, the store turned it into a `StoreError`,
>    `CompanionService._serve_work` caught that as an ordinary refusal, and the
>    task froze in `waiting_for_executor` with nothing running, nothing queued
>    and no record anywhere. Captured verbatim once the worker was made to keep
>    what it swallowed. Windows-only: on POSIX the rename succeeds.
> 2. **An approval was visible before it was answerable.** The request reaches
>    the store — and so the Approval Centre — before the single worker registers
>    its consent waiter. An answer arriving in that window was dropped and a
>    cancellation released nothing.
>
> The two ruled-out hypotheses were correctly ruled out. Ephemeral-port pressure
> was disproved directly by a controlled experiment: 20 slices over `AF_UNIX`
> and 20 over a forced loopback transport, same machine and same workload, all
> 40 passing with a peak `TIME_WAIT` of zero. Residual threads were disproved by
> the per-iteration inventory: **every** failure occurred with a thread and
> descriptor delta of exactly zero, which is the signature of a race and not of
> accumulation.
>
> The Linux run the paragraph asked for was done and is what made the shape
> clear — not because it reproduced the failure, but because it did not. Fifty-two
> consecutive Linux runs passed while one Windows run in three failed, which is
> what pointed at a platform-specific filesystem behaviour rather than at the
> companion's own logic.
>
> Full account: `COMPANION_LINUX_VALIDATION_REPORT.md`.

## 21. Installed vertical-slice result

`bunny-os companion run-character-slice` — **24/24 passed, 1 `NOT_RUN`.**

A real `CompanionService` over its socket; the validated default package; a
static idle frame; a submitted task; planning, working and progress
reconstructed by folding the canonical event stream; a reviewer observation; an
approval displayed with its bubble anchored and persistent; the approval
resolved through the canonical runtime; speaking; a generic lip-sync timeline
returning to neutral with no drift; synchronised captions; success;
animated-2d degraded to static under memory pressure and static degraded to
text-only with the display gone; recovery held until hysteresis; the renderer
restarted with package, state and presentation restored; and finally the task id,
state and result summary compared before and after — unchanged, `completed`.

`NOT_RUN`: the GTK widget layer, because no compositor is available. Reported as
`NOT_RUN`, never as a pass. The slice's own output carries
`gtkWidgetsExercised: false`.

The slice substitutes one value: a `PresentationRecommendation` describing a
machine with a display, because this host has none and the runtime correctly
recommends `text-only` on it. That substitution is confined to one named
function, stated in the report, and is the only place the slice departs from
what the runtime actually said.

## 22. Performance results

`make companion-character-measure`. **This host only. No Raspberry Pi, ARM,
64 MiB full-system or GPU figure is produced or implied.**

| Measurement | Value |
| --- | --- |
| Package validation | 10.15 ms median (first 10.38, max 11.26) |
| Package import | 108.45 ms (once; an import is not idempotent) |
| Package load | 0.0005 ms median |
| Frame compute | 0.0008 ms median, 0.0091 first, 200 samples |
| State transition | 0.267 ms median |
| Caption update | ~0.27 ms median |
| Degradation latency | 0.30 ms (immediate by design) |
| Recovery latency | 3 samples (the property; wall clock is incidental) |
| Renderer restart | 0.28 ms |
| Idle CPU | 0.297 s over a 0.3 s window |
| Decoded frame bytes | 36,864 per frame, 479,232 total, from validated headers |

**`NOT_RUN`**, with the reason recorded in the output rather than a zero:

| Measurement | Reason |
| --- | --- |
| Static renderer RSS | no `/proc/self/status` on this platform |
| Animated renderer RSS | no `/proc/self/status` on this platform |
| Renderer PSS | no `/proc/self/smaps_rollup` on this platform |
| Frame presentation time | no compositor |
| GTK widget measurements | no compositor |

Memory must be measured on Linux before any memory claim is made. The decoded
frame figure is portable because it is computed from validated image headers
rather than sampled from the process.

## 23. Build-impact classification

**Build-affecting.** This branch installs the `capability` and `companion`
Python packages (source only, 0444, fixtures excluded), the capability service
manifests to `/usr/share/bunny-os/capability/services`, and the character
packages to `/usr/share/bunny-os/companion/characters`; and it adds three
`COPY` lines to the Containerfile.

It is **not** covered by candidate `79bb99d`, Commit C′, the capability H1/H2
hosted evidence, the companion integration line, or any previous visual
prototype measurement. **No reproducibility candidate was created**, per §22.
This line requires its own qualification cycle and has not had one.

**A defect in the integration phase was found and fixed here.**
`install-root.py` on `8ffc433` copied `capability/` and `companion/` into the
image while the Containerfile never copied them into the build context.
`Path.rglob` over a missing directory yields nothing and the `mkdir` succeeds,
so the build would have silently installed two **empty** package directories —
and `bunny-companion.service`'s `ConditionPathExists` would have been satisfied
by the empty directory, started the service, and failed on import at every
restart. Now fixed and covered by a test that asserts the install script and the
Containerfile agree.

## 24. Known limitations

1. The GTK widget layer has no automated test; it needs a compositor.
2. One animation representation (validated frame sequences). Sprite sheets,
   animated WebP and APNG are deliberately refused.
3. No 3D renderer, and `IMPLEMENTED_PRESENTATIONS` will not name one.
4. No speech recognition, so lip-sync input in practice comes from a supplied
   timeline or the speaking-state fallback.
5. No phoneme accuracy claim.
6. Crossfade is declarable but not composited — the renderers switch frames.
7. Memory and PSS unmeasured on non-Linux hosts.
8. The package registry is per-user and unsigned: integrity is verified,
   authorship is not established.
9. One client. The character renders inside the companion window rather than as
   a free-floating surface; the prior separate application was dropped.
10. Sleeping, greeting, waiting-for-user, moving and unavailable are character
    states with no canonical presentation phase that produces them, so they are
    reachable through the package and the API but not through a running task.
11. ~~**The full companion suite is flaky on this host, roughly one run in
    three, in the service-driven tests only.** Undiagnosed; see §20. It does not
    reproduce in isolation and has never affected the character tests. Needs a
    Linux run over the real Unix socket to settle, which the memory
    measurements need anyway.~~
    **Resolved 2026-08-05 UTC on `feature/companion-linux-validation`.** Two
    defects: an unretried `os.replace` in the store's writer, which on Windows
    is refused while a reader holds the path open and froze the task silently;
    and an approval that became visible to clients before the worker was able
    to receive an answer for it. Both are fixed with regression tests that
    construct the interleaving rather than wait for it. The struck-through text
    is kept because the correction is part of the record; see §20.

## 25. Unverified assumptions

- **That GTK 4 renders the frames correctly.** No compositor was available; the
  widget code has never been executed.
- **That `Gtk.Picture.set_filename` handles the shipped PNGs as expected**, and
  that switching filenames at up to 60 fps is a reasonable animation mechanism
  on a real compositor. It is validated as data and never as pixels here.
- **That the frame-rate caps chosen under thermal, CPU and foreground pressure
  (15, 20, 12 fps) are the right numbers.** They are plausible, not measured.
- **That 288 px is a sensible default character size** on a real display.
- **That the decoded-memory estimates hold at the 64 MiB target.** The figure is
  computed correctly; whether it fits has not been tested on such a machine.
- **That the installed paths are right.** `/usr/share/bunny-os/companion/characters`
  has never existed on a built image, because no image has been built from this
  branch.
- **That the three restarts-per-minute guard is the right bound.** Chosen.

## 26. Remaining work for 3D rendering

In order: a GPU capability signal the router will act on (`gpuAvailable` exists;
VRAM does not); mesh, skeleton and material fields in the package schema, with
the same byte-level validation the raster path has — which for glTF means a
container parser, not a trusted library; a renderer that degrades *mid-frame*
under the pressure signals the adaptation layer already computes; a memory
budget that survives the 64 MiB target, which on present evidence it will not,
so the honest first step is a measurement showing which machines could support
it at all; and only then the single line adding `full-3d` to
`IMPLEMENTED_PRESENTATIONS`, which should be last rather than first.

## 27. Remaining work for production character art

The shipped package is deliberately simple: twelve flat PNG frames, two of them
forming a two-frame idle loop. Production art needs more frames per state and a
higher canvas; expression and mouth-shape art distinct from the state frames
(the current mouth shapes reuse the speaking frames); art at multiple scales or
a vector source, since one 96×96 canvas will not serve a 4K display and a
Raspberry Pi equally; a documented style guide so third-party packages are
recognisably compatible; and a licence and provenance review of anything not
drawn in-repository. `scripts/generate-default-character-assets.py` and
`docs/COMPANION_CHARACTER_GENERATION.md` record how the current art was made.

## 28. Reproducibility implications

This branch adds Python source, one JSON schema, twelve PNGs, a manifest and a
licence file to the image, plus three Containerfile `COPY` lines. All are
deterministic bytes installed with fixed modes, so the expected effect is a
changed but stable set of layer digests.

That is an expectation, not a measurement. **No reproducibility run was
dispatched and no candidate was created**, per §22. Before any such claim:

1. this line needs its own qualification cycle, independent of Commit C′ and of
   the companion integration line;
2. `copy_python_package` excludes `__pycache__`, `tests` and `testing`, which
   matters more here than before — the character package ships fixtures and a
   test corpus that must not reach the image;
3. `assets/companion/characters/** -text` is load-bearing for reproducibility as
   well as for correctness: those bytes are attested by the manifest and any
   checkout-time filter changes them;
4. the Containerfile change alters the build context, so the first build from
   this branch is not comparable to any previous one at all;
5. nothing here may be used to support a claim about `79bb99d`, Commit C′, the
   H1/H2 evidence or the integration line, none of which this branch touches.

**This branch requires its own future qualification cycle and has not had one.**
