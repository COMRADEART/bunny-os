# Bunny Companion, App Capsules and the Trust Layer

**Branch** `feature/bunny-companion-capsules-trust`
**Commits** `fc1e58a` (trust/capsules/catalog), `adce2c5` (surfaces, slice, tests)
**Branch point** `262b06d`
**Date** 2026-08-10
**Status** Source implemented. Tested on one host. **Not runtime validated, not hardware validated, not release qualified.**

Those five words are the repository's own maturity ladder (`NEXT_PHASE.md`,
"Maturity ladder, 2026-07-30") and this document keeps them apart everywhere. A
claim in this report is one of:

| Label | Means |
|---|---|
| **Implemented** | The source exists and is reviewed against the brief. |
| **Tested** | An automated test asserts the property and passes on the host below. |
| **Runtime validated** | Observed working on a booted Bunny OS image. |
| **Hardware validated** | Observed on physical hardware. |
| **Release qualified** | Inside a passing `gate-stable-release`. |

Nothing in this phase reaches the third row. That is not a hedge — it is the
accurate position, and §36 asks for exactly this distinction.

---

## 1. Repository assessment

Bunny OS at the branch point is a mature systems project with a consumer-experience
gap. Phases 1–7 are source-complete: a bootc image layer, a privileged broker with
Polkit per operation, an update agent, a recovery target, a GNOME Shell 50
extension desktop, a full companion runtime (task lifecycle, event stream,
approvals, capability engine, character renderer, voice, speech input, agent
providers, desktop actions), an installer, and 4,608 tests. Two images have
booted. `gate-stable-release` is `NO-GO`; all three pilot gates are `BLOCKED`.

What did **not** exist was any notion of *an application*. Searching the tree
before this work:

* No per-application sandbox. `installer/applications/policy.py` (41 lines)
  produced an application record with a `permissions` list and an honest
  `"Not enforced by this package format"` label — a policy statement, not a
  mechanism. Nothing built a mount namespace, a device set or a D-Bus filter.
* No user-facing permission model. `capability/apply/approval.py` asks a person
  about *Bunny's own* privileged operations — remote dispatch, paid providers,
  destroying user work. `companion/approvals.py` binds those to a task. Neither
  has a concept of a third-party application holding a standing permission to a
  file.
* No application catalogue. `enterprise/catalogue.py` is a fleet-deployment
  manifest; `companion/desktop/catalogue.py` is the nine desktop *actions* the
  companion may perform. Neither describes software a person might install.
* No per-application storage, lifecycle, reset or uninstall.
* The desktop surfaces existed (`shell/components/gnome-shell-extension`,
  ~5,000 lines of GJS) with no surface for a permission question or for watching
  autonomous work.

So the gap was precisely §6–§16 of the brief, and almost nothing in it duplicated
something already present.

### What was already right and was reused unchanged

Four decisions in the existing code shaped this phase and were adopted rather
than revisited:

1. **Silence means denial.** `capability/apply/approval.py`'s module docstring
   states it as the single most important line: *an unanswered request involving
   remote execution, money, destruction of user work, or interruption of
   something in progress is denied.* The trust gate inherits it verbatim for
   application permissions.
2. **A declared capability is not an available one.** `companion/desktop/catalogue.py`
   has a seven-word standing ladder — declared, available, eligible, approved,
   executing, completed, undone. `capsules/backends.py` uses the same shape for
   isolation backends, because "bwrap is installed" and "this kernel permits user
   namespaces" are different facts and a design that conflates them ships a
   sandbox that confines nothing.
3. **A projection decides nothing.** `companion/presentation.py` folds events into
   what a window may draw and holds no authority. `TaskWorkspace` and the Settings
   projections follow it exactly.
4. **Data tables, not `if` chains.** `companion/states.py` puts the task lifecycle
   in a transition table so an unintended move cannot be added by adding one
   branch. `capsules/lifecycle.py` and `trust/categories.py` are the same idea.

---

## 2. Existing-system reuse map

| Existing component | Decision | What was done |
|---|---|---|
| `capability/apply/approval.py` — approval interface, `SENSITIVE_ACTIONS`, unanswered-denies rule | **reuse** | The rule is restated and enforced in `trust/gate.py`. Bunny's own privileged operations continue to use this store unchanged. |
| `companion/approvals.py` — task-bound consent, six invalidation checks | **reuse** | Untouched. Application permissions are a different question (an app holding a standing grant) and live in `trust/`; task consent for Bunny's own actions is still this. |
| `companion/presentation.py` — phases, fidelity ladder, projection discipline | **extend** | `IMPLEMENTED_PRESENTATIONS` is now also consumed by `shell/.../companionPresence.js`; a test asserts the JS ladder is a subset so the two cannot drift. New tokens cover every `PRESENTATION_PHASES` entry. |
| `companion/desktop/paths.py` — canonical path resolution, containment by component | **reuse pattern, not code** | `trust/resources.py` implements the same three checks and says why it is not shared: the desktop module refuses dot-directories a user may legitimately pick in a file chooser, and sharing the code would mean sharing the refusals. |
| `companion/desktop/*` — nine bounded desktop actions, typed adapters, no general execution surface | **reuse** | Unchanged. Capsule launching is a separate authority and does not route through it. |
| `companion/store.py` — durable append, atomic replace, Windows rename retry | **reuse pattern, not code** | `trust/persistence.py` is one implementation for the three new packages, documented as deliberately not shared with the event-stream version. See §4 for the pre-existing duplication this does not fix. |
| `services/bunny-system-broker` — root operations behind a UDS with Polkit | **reuse** | `sensitive_system` is the permission category that routes here. No new privileged path was created. |
| `companion/states.py` — transition table discipline | **reuse pattern** | `capsules/lifecycle.py`. |
| `shell/themes/tokens.json` | **extend** | Additive v2. Every v1 value is unchanged and a test asserts it. |
| `shell/components/gnome-shell-extension/lib/*` | **extend** | Three new importless modules. No existing module was edited. |
| `installer/first_run/state.py`, `installer/frontend/app.py` | **extend** | `installer/companion_flow.py` holds the conversation as data; the existing state machine and GTK app are untouched and can adopt it incrementally. |
| `installer/applications/policy.py` — flatpak-first application record | **superseded, not removed** | Its honest enforcement labelling is the ancestor of `CategoryDescriptor.enforced_by_default`. Left in place; it is still what the Phase 3 installer tests assert against. |
| `enterprise/catalogue.py` — fleet deployment | **unchanged** | Different problem (fleet policy, not consumer choice). |

Nothing was deleted. Nothing was replaced.

---

## 3. Architecture

```
                        a person
                           │
    ┌──────────────────────┼──────────────────────────────┐
    │                      │                              │
 GNOME Shell         Trust prompt                   Task workspace
 extension        (GTK modal / text)              (panel / bubble)
 companionPresence.js  trustPrompt.js              taskWorkspace.js
    └──────────────────────┼──────────────────────────────┘
                           │  values only, no authority
    ┌──────────────────────┴──────────────────────────────┐
    │  companion/trust_surface.py   companion/capsule_bridge.py
    │  companion/capsule_settings.py                       │
    └──────────────────────┬──────────────────────────────┘
                           │
        ┌──────────────────┼───────────────────┐
        │                  │                   │
   ┌────▼─────┐      ┌─────▼──────┐      ┌─────▼──────┐
   │  trust/  │◄─────│  capsules/ │◄─────│  catalog/  │
   │          │      │            │      │            │
   │ decides  │      │ builds the │      │ declares   │
   │ nothing  │      │ sandbox    │      │ the ceiling│
   │ enforces │      │ from grants│      │ fetches    │
   │ nothing  │      │            │      │ nothing    │
   └────┬─────┘      └─────┬──────┘      └────────────┘
        │                  │
        │            ┌─────▼─────────────────────────────┐
        │            │  Flatpak · Bubblewrap · systemd   │
        │            │  namespaces · cgroups · portals   │
        │            │  SELinux · Polkit · bunny-broker  │
        └───────────►│  ← the only things that enforce   │
                     └───────────────────────────────────┘
```

The load-bearing property is the bottom row. `trust/` stores decisions and
produces sentences; it enforces nothing. `capsules/` translates grants into a
mount plan; it executes nothing by default. Everything that actually restricts an
application is a Linux primitive that existed before Bunny OS did. §22's
requirement — *if the Companion crashes, applications must remain sandboxed* — is
satisfied structurally: the Companion was never what held the sandbox closed.

### Package boundaries, and what each may not do

| Package | May | May not |
|---|---|---|
| `trust/` | store grants, produce sentences, audit | mount, spawn, import `capsules` or `companion` |
| `capsules/` | plan a sandbox, render argv, manage a directory | decide a permission, import the companion runtime, import `catalog` |
| `catalog/` | describe software | fetch, install, execute, import `capsules` |
| `companion/capsule_bridge.py` | join all three | be imported by any of them |

Verified by import: `capsules/` imports `trust`, `catalog/` imports `trust`, and
neither imports `companion`. The bridge is the only file where task authority
meets capsule authority, which is the same arrangement
`companion/desktop_bridge.py` uses and for the same stated reason.

---

## 4. Dependency review

**No new third-party dependency was introduced.** Nothing was added to
`build/packages/*.txt`, no Python package was added, and the image size is
unchanged by this phase.

Per §30, each *existing system* dependency the design now relies on:

| Dependency | Why necessary | Why existing code cannot do it | Security impact | Image impact | Fallback |
|---|---|---|---|---|---|
| `bubblewrap` (`bwrap`) | Only mature unprivileged sandbox for non-Flatpak applications | Nothing in the tree builds a mount namespace | Reduces attack surface; setuid-free with user namespaces | Already in `build/packages/common.txt` | If absent: `CapsuleUnavailable`, application does not start |
| `flatpak` | Applications that ship their own sandbox and portal-aware runtime | Same | Bunny narrows the packaged permissions with `--nofilesystem=host` first | Already present | Falls through to bubblewrap, then refuses |
| `systemd-run` (user scope) | Carries the cgroup, therefore the limits and the background lifetime | Nothing applied per-application resource limits | Bounds one application's effect on the desktop | Already present | Refuses; there is no "run without limits" path |
| `xdg-desktop-portal` | Camera, microphone, screen, location, notifications | Existing portal use is for the companion's own actions | These five are enforced by the portal saying no | Already present | Categories report `unenforced`; the prompt says so |
| Python stdlib only for the three new packages | — | — | No new parsing surface | Zero | — |

Two dependencies were **considered and rejected**:

* **A game engine or 3D framework for the Companion.** §30 asks for measured
  requirements. `companion/character/` already implements the full ladder down to
  text-only on `llvmpipe`; no measurement in this repository shows a need.
* **An Electron-style runtime for the permission dialog.** A modal that must
  appear during a permission check is the worst possible place for a 100 MB
  runtime and a second rendering stack. The dialog is `Adw.MessageDialog`.

### Duplication this phase did not fix

`os.replace`-based atomic write appears in 20 files across the repository
(`capability/apply/audit.py`, `companion/store.py`, `companion/settings.py`,
`installer/first_run/state.py`, and 16 others). `trust/persistence.py` is one
implementation for the three new packages rather than a twenty-first copy, but
consolidating the existing twenty is a separate, riskier change touching modules
with passing evidence attached. It is recorded as a candidate, not done.

---

## 5. Keep / defer / remove

§32 asks for a classification with justification for every REMOVE. After
inspection, **there is one REMOVE recommendation and it is a build artefact, not
a feature.**

| Classification | Component | Justification |
|---|---|---|
| **KEEP** | `trust/`, `capsules/`, `catalog/`, `companion/capsule_bridge.py`, `companion/trust_surface.py`, `companion/capsule_settings.py`, `installer/companion_flow.py`, the three shell modules | This phase's deliverable. |
| **KEEP** | Everything in `capability/`, `companion/`, `services/`, `shell/`, `installer/`, `selinux/`, `systemd/` | Directly required. |
| **KEEP** | `qualification/` (4,695 files), `evidence/`, `reviews/` | §32 is explicit: do not remove evidence merely because it is not visually impressive. This is the record that makes every gate result checkable. |
| **INTERNAL** | `build/`, `scripts/`, `release/`, `infrastructure/`, `tools/bunny-os` | Infrastructure, not user-facing, all load-bearing. |
| **DEFER** | `enterprise/`, `oem/`, `sync/`, `operations/fleet*` — Phase 7 OEM, fleet, encrypted sync, multi-tenancy | 454 tests, every pilot gate deliberately `BLOCKED` on a stable release that does not exist. `NEXT_PHASE.md` already says working on more of it adds surface to a system that cannot ship. Do not delete: it is complete, reviewed, and cheap to keep. |
| **DEFER** | `visual/`, `visual-v2/`, `visual-v4/` (tools only on `main`; prototypes live on branches) | The V4 Smithay-versus-libmutter question needs Linux hardware with a working Wayland stack. Unchanged by this phase. |
| **ARCHIVE** | `demos/`, the ~150 root `*_REPORT.md` files | Historical and evidentiary. Reading them is how the current position is checkable. |
| **REMOVE** | `desktop/src-tauri/target/**` — 242 tracked files of Rust build output (`.fingerprint`, `CACHEDIR.TAG`, `.cargo-lock`, `invoked.timestamp`) | A committed build cache. It is not a source, not evidence, and not reproducible; it makes `git ls-files desktop` return 242 paths of which zero are code. `ARCHITECTURE.md` describes Bunny Desktop as an upstream Tauri artifact delivered signed into `/opt/bunny/releases`, so this tree is not even the build input. **Not removed in this phase** — it is unrelated to the brief and deleting 242 tracked files belongs in its own commit with its own review. |

`apps/` and `ui/` contain no tracked source (only `__pycache__` and one file);
they are not classified because there is nothing in them to classify.

---

## 6. Bunny visual design architecture

The visual system is `shell/themes/tokens.json`, extended additively to v2. Every
v1 value is unchanged and a test asserts three of them, so an existing surface
renders identically.

What v2 adds, and why each token is named for a decision rather than for a look:

* **`elevation`** — four levels, and only one of them (`modal`) is raised
  unasked. That is the Trust prompt, and it is the only thing in Bunny OS
  permitted to interrupt.
* **`focus`** — 2 px ring, 2 px offset, on every focusable control in every
  theme. Never removed for aesthetics. A keyboard-only session is a supported
  way to use Bunny OS.
* **`scrim`** — `solid` at high contrast rather than lighter, because a light
  dim leaves a modal indistinguishable from the page behind it.
* **`companion.phase`** — one entry per `PRESENTATION_PHASES` value, tested for
  completeness, so a phase the runtime can produce always has something to draw.
  Only `attention` intensity may pulse, and only when the motion budget is
  non-zero.
* **`risk`** — high and critical carry `marker: true`, a *shape* beside the
  heading. Colour alone fails for a person who cannot distinguish those hues, and
  a permission prompt is the worst place for that failure.
* **`standing`** — `unenforced` is a badge that coexists with `granted`, because
  "allowed, and not actually restricted" is two facts and one row.
* **`opacity.surfaceReducedTransparency: 1.0`** — fully opaque, not merely less
  transparent.

Motion: 100 ms acknowledgement, 180 ms navigation, **0 ms** under reduced motion —
zero, not shorter. The fidelity ladder degrades 3D → lightweight 3D → animated 2D
→ static → text-only, one tier per measured problem, with no path back up in the
same evaluation (hysteresis; a machine oscillating between tiers looks worse than
the lower tier does). Reduced motion pins the animation budget and **leaves the
fidelity alone** — a person who asked for less movement did not ask for a worse
picture.

The direction is clean, bright, spacious and calm, built from this project's own
evergreen-and-mint palette. No Apple asset, layout, icon, typeface or animation
was referenced or reproduced.

---

## 7–9. Installer, first run, Companion integration

`installer/companion_flow.py` holds both flows as data with an **authority** per
stage:

* `companion` — Bunny explains and may act.
* `installer` — the underlying installer decides and performs; Bunny narrates.
* `user` — nothing proceeds until a person does a *specific named thing*.

§3's safety rule is `may_proceed()`, which returns `False` for a `user`-authority
stage until its own confirmation string is present. `confirm_erase` requires
typing the disk name; `encryption` requires entering the passphrase twice. No
Companion state, preference or Next button substitutes, and a caller wanting to
skip one would have to add the confirmation string — a thing a reviewer sees in a
diff. Eight tests cover it, including that one stage's confirmation does not
unlock another's, and that a stage cannot half-require one.

The installer opens with the Companion on a light background saying *"Hi. I'm
Bunny. I'll help set up your computer."* — asserted by test. Progress shows seven
real installer phases (`prepare`, `copy`, `security`, `user`, `capsules`,
`preferences`, `finalise`), not a spinner. Every stage carries `advanced`: the
device nodes, the GPT layout, the LUKS parameters, the exact `wipefs`/`sgdisk`/
`mkfs` commands — folded away, present, because an installer nobody can debug is
worse than a dense one.

First run is six stages, all `companion` authority, all non-destructive by
construction (tested). It explains capsules and permissions before asking the
person to try anything.

**Status: implemented and tested as a data model. The GTK rendering of these
stages is not written** — `installer/frontend/app.py` and
`installer/first_run/app.py` still render their existing step list. Adopting the
flow is a follow-on and is listed in §20.

---

## 10. App Capsule runtime

One persistent, protected environment per **installed application** — keyed on the
application id, so opening reconnects rather than rebuilds. Seven directories
(`data`, `config`, `cache`, `tmp`, `runtime`, `exports`, `inbox`), which is what
makes "clear temporary data", "reset", "delete data" and "uninstall" four
different buttons instead of one. The three removal sets are nested and a test
asserts it.

The isolation plan **starts empty**. There is no default home mount that later
checks subtract from — a forgotten check leaves a capability absent rather than
leaving the home directory mounted. A capsule with no grants gets its own seven
directories, a tmpfs `/tmp`, six device nodes, no network namespace access, no
D-Bus destination and an eight-key environment.

Four refusals, each with a test:

1. A path inside another capsule **raises** (`CapsuleContainmentError`) rather
   than being skipped — §20 forbids mounting one application's data into another,
   and a recorded refusal would let the launch proceed.
2. A credential directory (`.ssh`, `.gnupg`, browser profiles, 18 names) is
   refused *even when the user granted it*. A person can pick `~/.ssh` in a file
   chooser; the capsule still does not get it.
3. A path that stopped being what it was — deleted, now a directory, now a FIFO —
   is re-resolved and re-typed at plan time.
4. Two grants landing on one sandbox path raise rather than being resolved.

A granted file appears at `/run/bunny/files/<digest>/<name>`, never at its real
path, so an application does not learn the account name or the folder layout from
the argument it is given. Tested.

**A launch that cannot be isolated does not happen.** No user namespaces means
`CapsuleUnavailable` naming what is missing. The non-confining `systemd-scope`
backend is never selected automatically; reaching it requires
`allow_unconfined=True` at the call site.

**Nothing runs by default.** The default executor builds the plan, renders the
argument vector, records both and starts no process — and the capsule reaches
`stopped`, not `running`, because reporting an application as running when
nothing started would put a false statement in the one place a person looks.

---

## 11. Bunny Trust permission layer

Seventeen categories (§11's list exactly). Each names the Linux mechanism that
enforces it **and** whether this build applies it — two fields, because
collapsing them is how a security model becomes a diagram. Two categories are
currently `enforced_by_default: False` (`clipboard`, `bluetooth`), and the prompt
says so *to the person being asked*, in words, at the moment of deciding.

Scopes are per category and the omissions are the design: `credentials` and
`sensitive_system` offer `once` and nothing else; `camera`, `microphone` and
`screen_capture` stop at `session`; `gpu`, `notifications`, `startup` and
`background` have no `once`.

Deny-by-default in its **strong form**: an application cannot ask for a category
its catalogue entry never declared. Not a prompt a careful user declines — no
prompt, refused before any surface sees it. That closes the class of attack where
a prompt is timed, worded or repeated until somebody clicks wrong.

The decision procedure is eight ordered checks and every test asserts the **reason
code**, not just the verdict — because "denied because you said no" and "denied
because the store was corrupt" are the same verdict and completely different
facts.

The gate is the only path from a question to a permission:

* A ticket binds an answer to the exact question, including the resource
  identifier and the offered scopes. A stale ticket → `answer-mismatch`.
* A ticket is consumed once. Second use → `replayed`.
* A scope outside what was offered → `scope-not-offered`.
* A surface that raises → `surface-failed`. Silence → `unanswered`. A timeout →
  `expired`. **None of these writes a grant**, so a broken dialog cannot silently
  make the next launch refuse without asking.
* `TrustGate.block()` is the only way to create a grant without a prompt, and it
  can only ever create a **deny**. There is deliberately no matching allow, and a
  test asserts no such method exists.

Reasons carry provenance, and there are exactly four sources: `catalog`,
`application`, `task`, `unknown`. **There is no source meaning the model inferred
it**, asserted by test. An absent reason renders as *"It didn't say why."*

Audit records carry the resource **digest** and the short **display string**,
never the identifier. A test writes `~/Documents/divorce-draft.odt` through the
whole flow and asserts the absolute path and its parent directory are absent from
the activity file.

---

## 12. Curated App Catalogue

Metadata that ships in the image and changes only by a reviewed commit. **No code
path in the package downloads or executes anything** — §13's "arbitrary
repositories must not automatically become trusted applications" is enforced by
there being nothing that could make one. `vendor-rpm` and `github-release`
require a pinned signing identity or the entry will not construct.

The catalogue does two jobs. It establishes the permission **ceiling** — an entry
is a security artefact, not a listing — and it makes a choice honest.

§14's hardest requirement is negative, and the mechanism is that
`differences` is a curator-written paragraph the surface can only read out. Ten
entries ship. Adobe Photoshop is listed with `delivery: not-available` and the
sentence *"Adobe does not publish a Linux build. Bunny cannot install it, cannot
put it in a capsule and cannot promise anything about it. It is listed so you know
it exists and what it would cost."* Hiding the commercial option is the
dishonesty an open-source project falls into by default, and it is tested against.

Three delivery states keep a listing from implying an install: `capsule`,
`browser` (usable, isolation is the browser's, Bunny says so), `not-available`.

---

## 13. Task execution integration

`companion/capsule_bridge.py`. The route is fixed and one-way; §33's scenario runs
end to end in `tests/capsule_task/test_vertical_slice.py`.

Tested properties:

* Only the file the person named is asked about — one request, purpose `read`.
  §9's example (a graphics application must not get all of Pictures because one
  image was opened) is a property of the method.
* A refusal stops the task before any work, with no export written.
* The tool is handed the sandbox path, never the user's real path.
* A second run reuses the same capsule and the standing grant.
* The original is byte-identical afterwards, and the completion sentence only
  says *"Your original file wasn't changed"* when the export results say it was
  not.
* An overwrite is reachable only with `overwrite=True`, keeps a copy aside, and
  then `original_preserved` is `False` — so the sentence cannot claim otherwise.
* A collision numbers (`cat (1).png`) rather than replacing. Silently replacing
  somebody's file with an automated result is the most damaging thing this code
  could do.
* Every export is verified by digest and removed if it does not match.

---

## 14. Settings surfaces

`companion/capsule_settings.py` projects the App Capsules section: per
application, its state, backend, permission rows, reachable paths, storage per
directory, unenforced categories, recent activity, and four maintenance actions
each with its stated consequence.

Two things it is careful about. Every permission row carries `enforced` and the
enforcement mechanism — a tidy list of toggles without that distinction would tell
somebody their microphone is blocked when it is only recorded. And the revoke note
says *when* it takes effect: `immediate` and `next-launch` are different promises
and get different sentences.

Reachable paths come from the **isolation plan**, not the grant list, because they
differ: a grant whose file was deleted, or which resolved into a credential
directory, is refused at plan time and must not be shown as reachable.

Broken capsules are listed rather than dropped — §23 needs a recovery path and a
page that hid them would offer none.

**Status: implemented and tested as a projection. The GTK Settings page that
renders it is not written.**

---

## 15. Test suite

248 new tests. Full repository suite after this phase: **4,856 tests, 90 skipped,
1 failure**.

| Suite | Tests | Covers |
|---|---|---|
| `tests/trust/test_policy.py` | 17 | The eight ordered checks, by reason code |
| `tests/trust/test_gate.py` | 15 | Ticket binding, replay, scope widening, broken surface, silence, expiry |
| `tests/trust/test_security.py` | 24 | Canonicalisation, symlinks, reason provenance, audit disclosure, store corruption |
| `tests/trust/test_surfaces.py` | 17 | Text surface, deny-by-default, surface selection |
| `tests/capsules/test_isolation.py` | 23 | Empty start, environment, grants→mounts, the four refusals, backend honesty |
| `tests/capsules/test_runtime.py` | 28 | Identity, lifecycle table, persistence, launch, the four maintenance operations |
| `tests/capsules/test_security.py` | 18 | Export traversal, original preservation, cross-capsule, destructive containment |
| `tests/app_catalog/test_catalog.py` | 25 | Shipped entries, loading strictness, choice honesty |
| `tests/capsule_task/test_vertical_slice.py` | 28 | §33 end to end, workspace projection, Settings projection |
| `tests/shell/test_companion_surfaces.py` | 35 | The three JS modules under node, plus the tokens |
| `tests/installer/test_companion_flow.py` | 18 | Authority, confirmations, conversation |

Run with `make test-capsule-phase`.

**The one failure is pre-existing.** `tests.companion.test_neural_tts.BundledAssetTests.test_provenance_accounts_for_every_selected_tts_byte`
reports 436,604,323 vs 436,603,718 bytes. It fails identically at the branch
point `262b06d`, is a 605-byte difference in the voice assets on a Windows
checkout, and is the line-ending class of failure `KNOWN_LIMITATIONS.md` already
records. Nothing in this phase touches `assets/voice`.

**Three tests skipped on this host.** The symlink tests need privilege Windows
does not grant unelevated. They are `NOT_RUN` here, not `PASS`, and re-running the
suite on Linux is item 1 of §20.

### Two defects found while writing the tests

1. **A reason could carry a newline.** `_CONTROL` excluded `\x0a`, so an
   application could supply `"Needs the camera\n\nAllow always (recommended)"` and
   draw a forged second line under the real sentence in the same typeface. Fixed:
   every control character is refused.
2. **A standing allow was re-written on every use.** Each check created a fresh
   `Grant` duplicating the existing one, so the database grew once per launch.
   Fixed: an allow authorised by an existing grant references it.

---

## 16–19. Security, VM, performance, accessibility

Separate documents, so each can be read and disputed on its own:

* `APP_CAPSULE_SECURITY_REVIEW.md`
* `CAPSULE_VM_VALIDATION_PROCEDURE.md`
* `CAPSULE_PERFORMANCE_REPORT.md`
* `TRUST_ACCESSIBILITY_REPORT.md`

---

## 20. What works, and what remains unproven

### Implemented and tested

Permission model, deny-by-default, fail-closed behaviour, grant store, audit,
plain-language explanation, isolation planning, the four refusals, argument-vector
rendering, capsule lifecycle and persistence, the four maintenance operations,
uninstall with grant revocation, the catalogue and its choice honesty, the §33
task slice, result export with original preservation, the workspace and Settings
projections, the text consent surface, the installer/first-run conversation with
its authority rule, the three shell modules and the design tokens.

### Implemented, not tested

The GTK consent dialog (`GtkConsentSurface.ask`) — needs a display. The
`SubprocessExecutor` — needs a Linux kernel with user namespaces.

### Not implemented

* The GTK rendering of the installer and first-run stages. The data model exists;
  the windows still show the old step list.
* The GTK Settings page for App Capsules. The projection exists; no window reads it.
* Wiring the three shell modules into `extension.js`. They are complete and
  tested; nothing imports them yet, deliberately — editing a shell extension that
  has cost a boot per mistake, on a host that cannot run it, is how the desktop
  stops loading.
* Bluetooth and clipboard **enforcement**. Declared, recorded, honestly labelled
  as unenforced everywhere they appear.
* An installed-application discovery path. Capsules are created from catalogue
  entries; nothing scans for already-installed software.
* Real package installation. `ensure_capsule` writes the manifest and provisions
  the directories; it does not run `flatpak install` or `dnf`.

### Never observed

**Nothing in this phase has run on a booted Bunny OS image.** In particular:

* No `bwrap` process has been started from a rendered plan. Whether bubblewrap
  honours the argument vector is unmeasured.
* No portal has denied anything.
* No cgroup limit has been applied.
* No permission dialog has been drawn.
* No screen reader has read a prompt.
* No person has used any of it.

The security review lists which specific claims that leaves standing on source
inspection alone.

### The next six things, in order

1. **Run the suite on Linux as `bunny` on ext4.** Three symlink tests are
   `NOT_RUN` on Windows. Cheap, and the memory of this project says a Windows host
   hides real failures.
2. **Boot a Bunny OS image and run one capsule for real.** `SubprocessExecutor`,
   one catalogue entry, one file grant. This single step moves the phase from
   *tested* to *runtime validated* and is what every remaining claim waits on.
3. **Render the plan against a real `bwrap`** and verify from inside the sandbox
   that the home directory is absent, the granted file is present read-only, and
   `/dev/video0` is not there.
4. **Wire the shell modules and the Settings page**, on Linux, one at a time.
5. **Measure a real cold launch.** The numbers in the performance report are
   Bunny's own overhead, not an application's start.
6. **Then** the accessibility validation with real Orca, which is the item most
   likely to find something.

Nothing above needs money or hardware. Items 2–5 need the Fedora WSL builder that
already exists.

---

## What this phase does not change

`gate-stable-release` is still `NO-GO`. All three pilot gates are still
`BLOCKED`. The vulnerability position (8 Critical, 28 High, all from
`quay.io/fedora/fedora-bootc:44`) is untouched. No physical hardware, no second
signer, no independent review, no production key. This phase added a consumer
experience to a system that still cannot ship, and saying so is more useful than
the alternative.
