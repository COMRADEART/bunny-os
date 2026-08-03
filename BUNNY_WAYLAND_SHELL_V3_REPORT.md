# Bunny OS Native Wayland Shell — Visual Phase V3 feasibility report

> BUNNY WAYLAND SHELL EXPERIMENT
>
> NOT RELEASE QUALIFIED
>
> DO NOT USE AS THE DEFAULT SESSION

**Branch:** `visual/bunny-wayland-shell-v3`, based on
`visual/bunny-desktop-v2-dual-mode`. Do not merge into `main`. GNOME remains the
supported session.

---

## Verdict

# FEASIBLE WITH MAJOR GAPS

Bunny OS *can* build a native Wayland shell that replaces the GNOME Shell visual
layer while keeping the GTK application ecosystem. The compositor runs, real
applications run inside it, the Bunny chrome works as ordinary clients, both
visual modes work, the session stays isolated, and the shell recovers from a
real crash within a bounded budget.

It is not `FEASIBLE` without qualification, because three capabilities that a
desktop cannot ship without were not demonstrated: **screen sharing is
impossible** with the chosen framework as it stands, **there is no input
method**, and **accessibility was never verified with an assistive technology**.
None of the three is a dead end, but each is real work with real risk, and one
of them may change the framework decision.

It is not `NOT YET FEASIBLE`, because the core question was answered
affirmatively with measured evidence rather than argument.

It is not `INCONCLUSIVE`, because enough was measured to decide.

---

## What the phase set out to prove

| # | Capability | Result | Evidence |
|---|---|---|---|
| 1 | Start a native Wayland compositor | **yes** | Started repeatedly; first frame at 509–879 ms |
| 2 | Display GTK and Wayland applications | **yes** | GTK 4 Demo, GTK 4 Widget Factory and foot connected, mapped and were identified |
| 3 | Manage windows and workspaces | **partly** | Policy implemented and unit tested; interactive move/resize not exercised |
| 4 | Provide the Bunny top bar, dock and launcher | **yes** | All mapped as layer surfaces at the geometry the shell assigned |
| 5 | Support Regular Mode | **yes** | Ran; captured |
| 6 | Support Character Mode | **yes** | Ran; captured; character policy enforced structurally |
| 7 | Secure lock and session boundaries | **partly** | Protocol implemented and advertised; lock client written; no PAM, so no end-to-end lock |
| 8 | Accessibility-compatible interfaces | **not proven** | Architecture exists; no assistive-technology session was run |
| 9 | Multiple displays and fractional scaling | **not proven** | Model unit tested; the nested backend has one output |
| 10 | Recover safely when the shell crashes | **yes** | Real SIGKILL twice: one restart, then recovery |
| 11 | Run without changing the qualified image | **yes** | Enforced by a test that diffs the branch |
| 12 | Preserve GNOME as the supported fallback | **yes** | Additive session; the launcher refuses to start if GNOME goes missing |

Seven yes, two partly, three not proven.

---

## The framework

**Smithay** (Rust) was selected. The evaluation was close — wlroots scored
within four points of it — and the tie was broken on one criterion: Bunny writes
the security-critical shell policy itself, and that code is safer in Rust.

Two things from the evaluation deserve to survive into V4.

**A common claim about Mutter is false.** libmutter *does* support downstream
shells: `gala`, `gnome-kiosk` and `lumina-desktop` all link it in Fedora 44.
Mutter was not rejected because it cannot be used as a library; it was rejected
because building on it answers a different question — whether Bunny can build a
different shell on GNOME's compositor — and leaves Bunny inside GNOME's cadence.
It is the right comparison arm for V4 and the lowest-risk path to a product.

**Smithay scored worst of every candidate on inherited accessibility.** If
accessibility parity becomes the dominant requirement, the same matrix selects
Mutter, not Smithay. That is written into `FRAMEWORK_DECISION.md` as an explicit
condition for reopening the decision.

---

## The decision that shaped everything

**The compositor draws no shell chrome.** The top bar, dock, launcher, command
palette, Quick Settings, notification centre, assistant panel, approval cards,
character layer and lock screen are all ordinary Wayland clients — GTK 4 on
`wlr-layer-shell-v1`, except the lock screen which uses `ext-session-lock-v1`.

This was chosen for accessibility, not aesthetics. A surface drawn inside a
compositor has no accessible representation at all; there is no AT-SPI for
pixels. Drawing the bar and dock inside the compositor would have been easier and
would have made the hardest problem in replacing GNOME Shell permanently
unsolvable.

---

## What was measured

### Protocols — verified with a real client

`wayland-info` was run against the running compositor: **19 globals advertised**,
22 protocols assessed, **zero contradictions**. Nothing is claimed working that a
client could not see, and nothing claimed absent that it could.

Missing and consequential: `screencopy` (absent from Smithay 0.7 entirely),
`input-method`, `linux-dmabuf`, `pointer-constraints`, and
`foreign-toplevel-management` (available but deliberately off pending security
contexts). Full matrix in `visual-v3/PROTOCOL_SUPPORT.md`.

### Applications — 3 of 4 installed applications ran

GTK 4 Demo, GTK 4 Widget Factory and foot all connected, mapped a toplevel and
were identified from the protocol (`org.gtk.Demo4`, `org.gtk.WidgetFactory4`,
`foot`). `xterm` did not map, correctly: V3 never starts an Xwayland server.

Most of the requested ecosystem — Qt, Electron, Chromium, Firefox, a file
manager, a code editor, a media player, Flatpak — was **not installed on the
measurement host and was therefore not tested at all**. Eight of the nine
per-application dimensions could not be exercised. No application was modified to
make the shell look compatible.

### Performance — 2 met, 4 missed, 3 unmeasured

| Metric | Target | Measured | Verdict |
|---|---|---|---|
| Cold shell startup | < 3 s | 879 ms | meets |
| Regular shell memory | < 450 MB | 209 MB | meets |
| Top bar ready | < 2 s | 3.29 s | misses |
| Command palette visible | < 150 ms | 3.34 s | misses |
| Quick Settings visible | < 150 ms | 3.19 s | misses |
| Shell restart | < 3 s | 3.07 s | misses |
| Workspace transition | 60 FPS | — | not measured |
| Idle CPU | < 1% | — | not measured |
| Character asset incremental | < 100 MB | — | not measured |

All on Mesa **llvmpipe**, a software rasteriser, inside WSL2. Startup and memory
are comfortable and would only improve with a GPU.

The chrome-visibility misses share one architectural cause: each panel is a cold
process launch through a Python interpreter, an `LD_PRELOAD` re-execution for
gtk4-layer-shell, and GTK initialisation. A 150 ms target is unreachable for a
cold launch by any toolkit — the target assumes resident chrome, which V4 must
provide.

### Crash recovery — measured against a real kill

The compositor was SIGKILLed twice while running. The supervisor detected a
signalled death both times, restarted once, then stopped and wrote a recovery
marker naming GNOME. A shell that dies instantly every time reached recovery in
0.17 s with two crash records and no credential material in either.

The restart budget is absolute: at most three restarts for the lifetime of a
session, whatever the crash timing. Open clients are **not** preserved, and every
crash record says so.

### Accessibility — architecture yes, proof no

The AT-SPI bus is reachable and the chrome sets 16 accessible labels. But **no
Orca session was run**, so of ten assessed capabilities only three are observed;
four are inferred, one unavailable, two unsupported. `parity_claimable()` returns
false and a test holds it there.

The most serious single omission in the phase is the missing input method: no
on-screen keyboard, no CJK input.

### Multi-display — not exercised

The nested backend has exactly one output. The layout model is unit tested —
4K at 200%, portrait rotation, mixed scaling, hotplug, lock coverage — and that
is evidence about logic, not about hardware.

---

## Security

The compositor renders trusted backend state and returns explicit user input. It
decides nothing, stores no secret and holds no privilege. Three properties are
structural rather than checked:

- **Typed text cannot become a process.** No type carries a command line; a
  launch is a desktop-entry id resolved against a trusted registry. Sixteen
  hostile inputs are tested against it.
- **An approval needs an explicit approval.** Dismissed, expired, defaulted and
  no-input all deny; a card that cannot state its blast radius does not render,
  and an unrenderable card cannot be approved at all. No card has a default
  action.
- **The compositor never sees a password.** An isolated helper answers with a
  boolean. With no PAM service it returns "unavailable", never "success".

Six mutation tests confirm the highest-risk guards are load-bearing: disabling
each one changes the outcome.

---

## Where the evidence corrected me

Three findings came from the measurement disagreeing with what I had written.

**A harness bug nearly produced the worst possible evidence.** When
`wayland-info` failed to run, the protocol report described *every* protocol as
missing. A failed measurement had become indistinguishable from a negative
result. The harness now refuses to publish a matrix it did not measure — and
that guard fired twice more on environmental flakiness.

**My mutation tests were inverted.** The first version asserted each guarantee
still held after I broke it, which is backwards, and reported a failure I
initially read as a code defect. Rewritten to the correct semantics, all six
mutants are killed.

**Frame pacing was fatal, not merely redundant.** Rate-limiting the render loop
killed the winit event loop within a second, every time, with thousands of host
connection resets; unthrottled ran a full 12 s with zero, repeatedly. In a
nested run `submit()` is already paced by the host's frame callback. Pacing was
removed, and page-flip-driven pacing became a V4 requirement.

---

## What must happen before this is a product

In priority order, from `visual-v3/V4_PRODUCTION_REQUIREMENTS.md`:

0. **Re-run the framework decision** with the accessibility answer in hand.
1. **Prove accessibility** with real assistive technology; implement the input
   method and magnification.
2. **A real session backend**: DRM/KMS, libseat, libinput, page-flip pacing,
   damage tracking, multi-GPU.
3. **Screen capture**, which is currently impossible and has no workaround.
4. **Resident shell chrome**, to make the interaction targets reachable.
5. Security work deferred here: security contexts for layer-shell namespaces,
   the PAM helper, the approval backend.

---

## Isolation

Nothing on this branch touches release work. The experimental units live under
`sessions/` rather than `systemd/`, because `build/scripts/install-root.py`
copies `systemd/` into the qualified image wholesale — putting them there would
have changed the qualified image.

A test diffs this branch against the V2 authority and fails if any qualification
evidence, release artifact or gate script changed. The package refuses to build
if a mock fixture, a second session file, or a session entry lacking
`X-Bunny-Default-Session=false` enters the staging tree.

The shell fails closed on four gates: explicit `BUNNY_SHELL_EXPERIMENTAL=1`,
GNOME still selectable, not configured as anyone's default, and no qualification
run in progress.

---

## Test and evidence summary

- **197 tests pass**: 80 Rust unit, 6 Rust process-level, 39 Python security,
  72 Python shell-UI.
- **6 of 6 mutants killed.**
- **20 of 20 rejection requirements** are mapped to the suite that proves each.
- Evidence JSON in `visual-v3/reports/`; generated documents are rendered from
  it so a number in prose cannot drift from the number measured.
- Package: 56 files, `defaultSessionChanged=false`, `gnomeSessionRemoved=false`,
  `qualifiedImageChanged=false`, `mockFixturePackaged=false`.

## Documents

`visual-v3/`: `FRAMEWORK_DECISION.md`, `ARCHITECTURE.md`, `PROTOCOL_SUPPORT.md`,
`SECURITY_MODEL.md`, `ACCESSIBILITY_MODEL.md`, `PERFORMANCE_MODEL.md`,
`PERFORMANCE_REPORT.md`, `COMPATIBILITY_MATRIX.md`, `MULTI_DISPLAY_REPORT.md`,
`CRASH_RECOVERY_REPORT.md`, `KNOWN_LIMITATIONS.md`,
`V4_PRODUCTION_REQUIREMENTS.md`.

The next phase after this verdict is **Visual Phase V4 — production Bunny Shell
architecture and migration plan**. It does not begin from this branch.
