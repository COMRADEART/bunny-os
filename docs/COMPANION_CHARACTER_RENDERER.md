# The Bunny Companion character renderer

The character is presentation. It draws what the canonical companion runtime
already decided, and it can decide nothing itself. Everything below follows from
taking that seriously.

```text
canonical companion events
        ↓  (companion/presentation.py — already exists, unchanged)
canonical presentation projection
        ↓  (companion/character/integration.py — the only door)
character state mapper
        ↓  (companion/character/mapper.py — pure)
validated character package
        ↓  (companion/character/package.py — every byte checked)
renderer selector
        ↓  (companion/character/adaptation.py — consumes the allowance)
static image  |  animated 2D  |  text
        ↓  (companion/character/surface.py — GTK-free)
the companion window
```

---

## 1. What the renderer cannot do

Not by convention — by what it is given.

| It cannot | Because |
| --- | --- |
| Select an executor | It has no runtime handle and no protocol operation |
| Choose an AI provider | There is no provider in this build at all |
| Validate approvals | It receives an `ApprovalPresentation`; the runtime checks bindings |
| Execute tools | `ToolBroker` refuses every caller that is not runtime/executor/recovery |
| Read arbitrary task payloads | It is handed a `PresentationState` and imports nothing else |
| Recalculate hardware capability | It reads `recommendation`; nothing here probes |
| Store a second task state | It has no store and no writable path |
| Generate hidden status explanations | Every sentence comes from the projection |

`tests/companion/test_character_cli_vertical.py` and
`test_character_mapper.py` assert the last four from the **import graph**, so a
future `from companion.store import …` fails the build rather than the review.

## 2. The package format

`schemas/companion-character-package-v1.schema.json`, implemented by
`companion/character/schema.py`. Every §3 field is present: schema version,
package and character id, name, version, creator, licence, copyright, renderer
type, supported renderer versions, asset inventory with a SHA-256 per asset,
static fallback, thumbnail, animation map, expression map, generic mouth-shape
map, bubble anchor, character bounds, safe margins, canvas dimensions, frame
rate, loop policy, declared decoded-memory requirement, minimum presentation
requirement and optional generation provenance.

**Every package must carry a static fallback**, and the manifest is refused
without one. Packages are data-only: `safe_package_path` permits `.png`,
`.webp`, `.txt`, `.md` and `.json` and refuses everything else by suffix,
including `.svg` — a scriptable format this build will not load from an
untrusted package, whatever the shipped shell asset does.

## 3. The validator

`validate_package_directory` walks the tree without following links and refuses,
in order: a symlinked root; a symlink, device or special file anywhere; a
hard-linked file; an executable mode bit; a repeated path; a file count or byte
total over the limit; a missing or oversized manifest; duplicate JSON keys; an
undeclared file; a missing declared file; a size that disagrees with the
manifest; a digest that disagrees with the manifest; an image whose real
dimensions or media type disagree with what was declared; a text asset
containing NUL, an executable signature or credential-shaped content; and an
empty licence file.

Only then is a package digest computed, over the canonical manifest plus every
asset's path, digest and size.

**Images are validated structurally before any desktop decoder sees them.**
`companion/character/image.py` parses the whole PNG container, checks every
chunk CRC, rejects unknown critical chunks, refuses interlacing, and performs a
*bounded* inflate of the scanlines against the size the header declares — so a
PNG that expands beyond its own dimensions is refused rather than decompressed.
WebP is bounded the same way at the RIFF level. **APNG and animated WebP are
rejected outright**: a package must not be able to smuggle a second, unbounded
animation timeline through a single frame.

## 4. The importer

`CharacterPackageImporter.import_package` accepts a directory or a `.zip`.

For an archive it inspects before extracting: entry count, path traversal,
drive-qualified and absolute paths, repeated names, encryption, unsupported
compression methods, non-regular file types (symlink, device, FIFO), executable
modes, per-entry and total expansion, and per-entry and whole-archive
compression ratios. Extraction is bounded again *while writing*, because an
archive can lie about its own sizes.

For a directory it validates first and then copies only the paths the validated
manifest names, opening each with `O_NOFOLLOW`.

Installation is atomic and never in place:

1. extract or copy into a staging directory under the registry root;
2. validate the staged tree as `imported-unverified`;
3. re-validate as `verified-integrity`;
4. `os.replace` the staged payload to its final versioned path;
5. validate again *at the destination*;
6. only then record it in the registry.

The previous working version is untouched throughout, and a re-import of the
same bytes is idempotent while a re-import of *different* bytes to the same path
is refused.

## 5. Trust

```text
built-in  locally-created  imported-unverified  verified-integrity
incompatible  disabled  quarantined  corrupt
```

**Integrity is not creator trust**, and the code keeps them in separate fields:
`integrity_verified` and `creator_trusted`. An imported package reaches
`verified-integrity` and `creator_trusted=False`, and every CLI path that
reports a successful validation says so in a `warning` field — because the
moment a user is most likely to conclude otherwise is the moment they are told
the package is valid.

`built-in` cannot be asserted by the user registry; a record claiming it is
rejected. `bunny-os companion character trust` can set `disabled`,
`quarantined` or `imported-unverified` and nothing else: the other states are
properties of where a package came from or what its bytes are, not opinions.

## 6. The state mapper

Pure, and led by the canonical phase. `CANONICAL_PHASE_STATES` maps every member
of `companion.presentation.PRESENTATION_PHASES` to a character state — a test
compares the two vocabularies — and the mapper may then only **refine**.

Refinement is subordinate by construction. Candidates are gathered and filtered:

```python
permitted = [c for c in candidates
             if priority_rank(c) <= priority_rank(base) or c in _NARROWINGS[base]]
```

A refinement that is less urgent than the canonical phase is discarded. The one
exception is a *narrowing* — `working` drawn as `researching` or `typing` — which
§6 groups with working as "active work". This check found two real bugs during
development: a window drag rendering a paused task as "repositioning", and an
unhealthy renderer rendering it as "degraded".

Client-side facts (listening, transcribing, speaking, repositioning) are only
consulted at all in `_REFINABLE_PHASES`, which excludes error, blocked,
approval and cancellation. **A decorative animation therefore cannot hide an
approval, warning or error** — not because it loses a comparison, but because it
is never considered.

§5's fallback chains are declared per state and every one ends in
`static_fallback`; the chain actually walked is reported in `fallbackChain` and
shown by `bunny-os companion renderer explain`.

## 7. Renderers

One interface, `CharacterRenderer`, with two implementations. Both may reach
assets only through `ValidatedPackage.asset_path`, which re-checks containment
under the package root on every call.

**Static** is the guaranteed fallback: PNG and WebP, transparent, aspect
preserved, bounded decoded dimensions, scaling, positioning, bubble anchoring,
reduced motion, and a text-only floor below it.

**Animated 2D** is a validated frame sequence — one representation, chosen
because it reuses the static decoder and adds no second animation system.
Looping and one-shot playback, interruption, pause and resume, a frame-rate cap,
dropped-frame counting, return-to-idle, unload and restart. The interruption
queue holds **exactly one** entry.

## 8. Transitions

`immediate`, `crossfade`, `complete-current`, `interruptible`, `queue-next`,
`return-to-idle`. Errors, warnings, approvals, cancellation and listening are
`SAFETY_STATES` and interrupt anything, including a `complete-current`
animation. Reduced motion collapses every transition to `immediate` and holds a
single frame. A looping animation may not declare a completion-dependent
transition, and the schema refuses one that does.

## 9. Speech bubbles

The bubble shows the projection's own sentence — a caption, a result summary or
an error summary — chosen by `bubble_request_for`, which never composes one.
Placement is anchored to the character's bubble anchor, tries the preferred side
then the alternatives, avoids screen edges, clamps into the work area, and wraps
to a scaled maximum width.

An approval bubble is **persistent**: no timeout, because a question that faded
would lapse into a denial with nobody having seen it. So is an error bubble —
initially it was not, and a message about something going wrong disappeared
after six seconds.

## 10. Lip-sync

Generic mouth shapes only: `neutral`, `closed`, `open-small`, `open-medium`,
`open-wide`, `rounded`, `smile`. Accepts timestamped viseme events, a
phoneme-to-viseme mapping, an audio-amplitude fallback and a speaking-state
fallback. Timestamps must be monotonic and the sequence is bounded. Drift is
detected against an audio clock and reported. A missing shape falls back through
`neutral` and `closed`. Speech ending or being cancelled returns the mouth to
neutral. Reduced motion holds neutral throughout.

**No phoneme accuracy is claimed**, here or in the slice's output, because none
has been measured.

## 11. Adaptive rendering

```text
animated-2d → static-image → text-only
```

The ceiling comes from `PresentationState.recommendation` — the canonical
runtime's own answer, produced from the capability runtime's signals.
`CapabilityPresentationPlan.from_recommendation` is the *only* constructor; the
donor's `from_execution_plan`, which re-parsed the capability plan, was removed
and a test asserts it is gone.

Degradation is immediate and considers display availability, static and animated
renderer health, reduced motion, graphics readiness, memory pressure, the
package's own declared memory against the budget, critical battery, and the
decoded-fallback floor. Thermal, CPU and foreground-workload pressure cap the
frame rate rather than dropping a rung.

Recovery is held by hysteresis: three consecutive healthy samples *and* a
minimum delay since the last degradation. Renderer *health* recovery is separate
and slower, because a fault deserves a longer look than a busy moment.

**Degradation never touches the task.** Every degradation event carries
`taskContinues: true`, and the runtime is in another process with no handle held
here.

## 12. Failure recovery

§15's ladder, in `CharacterPresenter`:

1. record a typed `renderer.failed` event;
2. release renderer resources;
3. fall back to static;
4. fall back to text-only if static fails as well;
5. leave the task alone — there is no path from here to it;
6. `_RestartGuard` permits three restarts a minute and then refuses, recording
   `renderer.restart-refused` rather than looping;
7. health is restored only after a stable interval, and the selector's own
   hysteresis still applies on top.

Covered: decoder error, missing asset, corrupt frame, renderer exception, GTK
surface loss, package removed, display removed, memory pressure and repeated
crashes.

## 13. The default package

`assets/companion/characters/default-bunny` — original art drawn for Bunny OS,
GPL-3.0-or-later, twelve PNG frames plus a manifest and a licence file. It
provides a static fallback and idle, listening, planning, working, reviewing,
speaking, success, warning, error and sleeping, and its state map covers every
required character state.

It goes through **exactly the same validator** as an imported package —
`registry.built_ins()` calls `validate_package_directory`, and a built-in that
failed would simply not be offered. Being shipped buys it no exemption.

`assets/companion/characters/**` is marked `-text` in `.gitattributes`. Its
assets are attested by the manifest's own digests, and a checkout-time EOL
filter changes those bytes: `LICENSE.txt` is 308 bytes committed and 314 in a
Windows checkout, which failed the built-in package's integrity check in 23
tests.

## 14. Accessibility

Reduced motion and no-animation hold a single frame; there are no animations or
transitions declared in the stylesheet at all. Text-only is a first-class
presentation, not a degraded one: `describe_phase` and the package's
`accessibility_description` give every state in words, and
`CompanionViewModel.text_only_view()` renders the whole surface as text
including which renderer is running. Descriptions are colour-independent — a
test matches whole words so the phrasing is not distorted by a substring check.
Character and bubble scale are adjustable and bounded; the frame-rate cap is
adjustable to 1 fps; flashing can be disabled; high contrast is honoured through
named system palette colours. An approval or error never loops.

## 15. Positioning

Centre, dock left, dock right, bottom left, bottom right, compact floating, with
user-selected scale and dock, safe-area calculation and bubble-safe placement.
Display removal moves the character to what remains.

**No absolute Wayland positioning is claimed.** GNOME does not expose it, the
directive drives size and shape, and `absolute_placement_available` is `False`
with no code path that sets it otherwise. The character never takes keyboard
focus: `set_position` raises if handed a decision that would.

## 16. Known limitations

1. **The GTK widget layer has no automated test.** It needs a compositor.
   Everything below it is covered through `CharacterPresenter`.
2. **One animation representation.** Validated frame sequences only; sprite
   sheets, animated WebP and APNG are deliberately refused.
3. **No 3D renderer**, and `IMPLEMENTED_PRESENTATIONS` refuses to name one.
4. **No speech recognition**, so the lip-sync input in practice comes from a
   supplied timeline or the speaking-state fallback.
5. **No phoneme accuracy claim.**
6. **Crossfade is declarable but not composited** — the static and animated
   renderers switch frames; a true cross-fade needs a compositing surface.
7. **Memory and PSS are unmeasured on non-Linux hosts**, reported `NOT_RUN`.
8. **The registry is per-user and unsigned.** Integrity is verified against the
   manifest; nothing establishes who wrote the package.
