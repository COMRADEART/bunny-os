# Alpha Release Candidate — Phase 4 (Hardening)

Recorded 2026-08-17. Branch `feature/bunny-companion-capsules-trust`,
opened at **b0b92482** (the Phase 3 close).

> **STATUS: DRAFT — the qualification runs named below are still executing.**
> Sections carrying results are marked PENDING until their record exists.
> Nothing in this file is a claim until the record it names is committed.

---

## 1. Release summary

Phase 4 was a hardening phase: no features, four known defects to close, one
release candidate to build and qualify from a fresh installation.

The headline is that the largest of the four was not the defect it was
reported as. "The ACPI power key does nothing in a Bunny session" turned out
to be **every keybinding in every Bunny session, from the first boot the
desktop ever ran** — the power key was simply the one somebody had pressed.

## 2. Starting commit

`b0b92482` — Phase 3's close. Suites at that commit: Linux reference 5737
passed / 24 skipped, installer 172 passed.

## 3. Final commit

PENDING — the release-candidate artifact commit is **e906a487**; the final
tree commit is recorded when this report is committed.

## 4. Known issues entering Phase 4

From `PHASE3_USER_JOURNEY_REPORT.md` §10/§18 and `KNOWN_LIMITATIONS.md`:

| # | Issue | Phase 3 disposition |
| --- | --- | --- |
| A | ACPI power key inert in a Bunny session | Open defect, FIX OR EXPLAIN |
| B | A second user account lands in stock GNOME | Limitation |
| C | `compact`/`minimal` companion modes have no persisted representation | Limitation |
| D | Track 1b retained-input publication | NOT_RUN — AUTHENTICATION BLOCKED |
| E | Host C: near-full; a suite run was killed mid-flight | Environment |

## 5. Root causes

### A. The power key, and what it really was

Measured across eleven boots (`qualification/phase4/power-key/`, with the
full narrative in that directory's `FINDING.md`).

The Bunny desktop is a GNOME Shell extension. It was constructed **during**
gnome-shell's startup, and one of its first acts is to dismiss the overview
GNOME opens at login. In GNOME 50.4 — read out of the shipped
`libshell-18.so`, not from documentation — `overviewControls.js`'s
`runStartupAnimation()` awaits `this.layout_manager.ensureAllocation()`, a
promise that settles only when the controls actor is first allocated. Hiding
the overview before that allocation leaves the promise unsettled for ever:

```
desktop built during startup
  → overview hidden before its first allocation
    → ensureAllocation() never settles
      → layout.js never reaches _startupAnimationComplete()
        → 'startup-complete' never fires
          → main.js never flips Main.actionMode from NONE to NORMAL
            → windowManager.js's _filterKeybinding drops EVERY keybinding
```

`_filterKeybinding` filters unconditionally while `Main.actionMode` is
`NONE`. Nothing logs, because a filtered binding is not an error.

The discriminator is `GNOME Shell started`, the message main.js emits from
inside its own `startup-complete` handler; its absence *is* the stalled
startup. Two volume-up presses injected from the host produced **no
accelerator of any kind** (p4-power-8), which is what proves the scope:
it was never the power key that was filtered.

Two symptoms had already been worked around in Bunny's own code without the
cause being found — the shell's leftover cover pane, and GNOME's panel being
hidden "after the startup deadline". Both are consequences of a startup that
never completes.

### B. The second user

`Session=bunny` was written exactly once, by the installer, for the account
the kickstart creates (`installer/backend/anaconda.py`, `_place_handoff`).
Nothing else in the tree wrote it, and the earlier mechanism
(`DefaultSession=` in GDM's `custom.conf`) had been deleted in Phase 3
because it was measured to be a fiction — GDM's schema has no such key. Two
populations were affected: accounts added later through the shell's own Users
entry, and — worse — **every** account on an OEM device, where the first user
is created by gnome-initial-setup and never passes through the installer.

### C. compact / minimal

The setup wizard offers five companion modes and the settings document could
represent three. `compact` and `minimal` were applied to nothing and recorded
honestly as not applied, then lost.

### D. Track 1b

The Phase 3 blocker (no credential path across the environment boundary) was
resolved: the operator's `gh` token carries `write:packages` and reaches the
builder through the interop call recorded in the Phase 3 disposition. The
blocker moved rather than cleared — see §17.

### E. The build environment

The WSL VHDX had grown to 731.5 GB against 268 GB of real content. Nothing
inside the guest was out of space; the host disk was.

64 GB of already-allocated extents were released inside the guest (superseded
build outputs and the two discarded RC images named in §20 — never the pinned
base, never evidence). That is a reclaim *within* the VHDX: a VHDX does not
shrink when its guest deletes files, so the host figure did not move.

Measured rather than assumed, because "the host disk is nearly full" and "the
build environment is unreliable" are different claims:

| | Host C: free | VHDX size | Guest `/` used |
| --- | --- | --- | --- |
| Before the qualification chain | 10.99 GB | 731.53 GB | 345 GB of 1007 GB |
| After six journeys of it | 10.97 GB | 731.53 GB | — |

The VHDX did not grow by a byte across six VM journeys, because the guest
reuses blocks the file has already claimed. So the low host figure is a
**standing risk, not an active fault**: it does not fail today's runs, and it
would fail the first operation that needs genuinely new extents. The durable
fix is to sparsify the VHDX (`wsl --manage … --set-sparse true`), which would
return roughly 380 GB; it is a privileged operation on the operator's machine
and is left for the operator rather than performed here.

**This was not what was breaking the runs**, which matters more than the disk.
See §17: the qualification chain died twice with `qemu: terminating on signal
15 from pid 1 (/sbin/init)`, which reads exactly like an out-of-space kill and
is not one.

## 6. Fixes

| # | Commit | What changed |
| --- | --- | --- |
| A | `f17fb19c` | `enable()` defers the desktop's construction to `startup-complete` while the shell is still starting; `disable()` cancels a pending deferred build. |
| A | `0d9866a4` | `_dismissOverviewOnce()` refuses to run while `Main.layoutManager._startingUp`, and deliberately does not set its once-flag in that path — the desktop already connects a `startup-complete` retry, and a flag set early would make that retry a no-op. |
| B | `e215bb22`, `89b51564` | accounts-daemon **user templates** (`config/accountsservice/{standard,administrator}.template`) shipped to `/usr/share/accountsservice/user-templates/`, seeding `Session=bunny` for every account the daemon creates. |
| C | `9783ceec` | `character.companionMode` (`full`/`compact`/`minimal`) in the one settings document, with `Settings.presentation_mode()` resolving the wizard's five-way answer; the presenter sizes the figure by the design tokens' ratios; the first-run applier writes the level instead of apologising; the accessibility page's text-only toggle restores the mode it replaced instead of promoting it to `full`. |
| — | `39234768` | The evidence-immutability check declares Phase 4's own tree, as every phase since the record was cut has done. |

Both A fixes are kept though either alone suffices: the second names the
exact upstream contract that was violated and would catch a future caller
that hides the overview from somewhere else.

### Measured before shipping, not assumed

The B fix was verified against the builder's own `accountsservice-23.13.9`
before it could ship wrong, and the obvious spelling is wrong twice over:
the installed filename must be the bare account type (`standard`, **not**
`standard.template`, which the daemon silently ignores), and a template
reaches only accounts the *daemon* creates — an account made with `useradd`
from a shell is never templated. Both facts are in the templates' own
comments and asserted by `tests/first_login/test_session_templates.py`.

## 7. Installation result

PENDING — journey-e (unattended encrypted install driven through the shipped
setup surface) against the release-candidate medium.

## 8. Login result

PENDING — first-boot-e (two encrypted boots), then g1: fresh machine, real
GDM login, first-run wizard walked.

## 9. Persistence result

PENDING — g2 configures five settings and the compact companion mode; g3
reads them back after a real reboot and selects minimal; g4 reads minimal
back after another reboot.

## 10. Companion result

PENDING for the artifact runs. Settled in source and on the Linux reference
target: the chrome level persists in the one authoritative document, the
window opens in the compact shape for a compact or minimal install, and the
presenter sizes the figure by the design tokens' ratios.

**Boundary, stated plainly:** the mode is honoured by the companion *window*
and its figure. The shell's centre-stage desktop character keeps its stage
geometry, which is a negotiated layout (`lib/layout.js`: the character owns
the middle and the card columns negotiate around it). Re-deciding that
geometry per mode is a layout change this hardening phase does not make —
§9 forbids redesigning the renderer architecture and §20 freezes it. So a
person who chooses `compact` gets a compact companion window and a
persisted, applied preference; they do not get a smaller centre-stage
figure. That is a limitation, recorded in §18, not a claim.

## 11. Voice result

PENDING — the Stage 2 primary acceptance (`accept-all.sh`) against the
release-candidate shell-test image.

## 12. Trust result

PENDING — the first attempt did not establish it, and found two harness
defects on the way. Both are fixed; the journeys are being re-run.

**The prompt itself is right.** g7 drew it, and it was read rather than
asserted: *"Bunny Image Tool wants to open Pictures/holiday.png"*, the
consequence in plain words ("It will save a copy as holiday-resized.png. Your
original file will not be changed."), the grant enumerated — `Files:
Pictures/holiday.png only`, `Network: Off`, `App data: Isolated` — and Allow
and Deny both reachable. It was pressed by pointer and the decision recorded
as `granted`.

**Then the task failed, and the run was recorded as a pass.** The journey's own
record says `decision: "granted"`, `final.state: "error"`, `final.says: "the
task failed"`, `result.files: []`, `result.pixels: null` — and `result.json`
says `findings: []`.

### What actually happened, and what did not

The capsule was not broken. The journal has one line from inside the sandbox:

    bwrap[7043]: bunny-image-tool: the output already exists
    …service: Main process exited, code=exited, status=2/INVALIDARGUMENT

`scripts/bunny-image-tool.py` refuses to overwrite an existing output, which is
correct and is the behaviour that keeps a resize from destroying a previous
one. **The product did the right thing.** What was stale was the machine: a
capsule writes its result into its own `exports` directory, which lives under
the user's XDG data home (`~/.local/share/bunny/capsules/**/exports`) and
therefore survives a reboot, while the journey's fixture reset only
`~/Pictures`. The machine this chain runs on is deliberately persistent — its
history is the persistence evidence for §9 — so a granted journey that had
ever run before could never succeed again.

That also explains the otherwise puzzling `result.files: []`: the harness
globs Pictures, and nothing was ever exported there.

### Two harness defects, both fixed

| Defect | Fix |
| --- | --- |
| The fixture reset `~/Pictures` but not the capsule's persistent `exports`, so the granted journey was not repeatable on a machine that had run it once. | `_FIXTURE_PROGRAM` now clears stale `*-resized*.png` from `**/exports` too, and **reports what it removed** as `clearedExports` — this diagnosis would have been one field long. |
| The story graded machine health only — booted, session opened, journal present, clean shutdown — and never asked whether the journey did what it went there to do. A granted journey that produced nothing scored `findings: []`. | The grader now reads the journey's own record: a granted journey must produce output and must not end in an error state; a denied journey must produce nothing; a journey with no decision is a finding. The verdict is written into `result.json` as `journeyVerdict` so it is visible without re-deriving it. |

The denied case's *final state* is deliberately left ungraded: no record in
this repository establishes whether a refusal should surface as an error or as
a calm decline, and a check written from a guess would fail a correct refusal.
It is recorded so the next denied run settles it by measurement.

**A journey that cannot fail is not a test.** That is the finding here, and it
is worth more than the run it invalidated.

## 13. Shutdown result

PENDING for the artifact. On the installed Phase 3 machine with the fixed
extension shadowing the image copy, **p4-power-11** is the first Bunny-session
boot in this project's history to end with `findings: []`: startup completes,
the press is delivered, and the machine powers off cleanly.

## 14. Multi-user result

PENDING — g5 creates a standard and an administrator account through
AccountsService's `CreateUser` (the call gnome-control-center's Users entry
and gnome-initial-setup both make) and reads back the record GDM consults;
g6 logs the second account in **at the real greeter** and the journal says
which session it actually got.

## 15. Performance measurements

PENDING.

## 16. Full regression results

PENDING for the uncontended run, which is the one that counts. Recorded so far,
against the Phase 3 close as baseline:

| | Baseline `b0b92482` | Contended `9b1a9354` | Uncontended |
| --- | --- | --- | --- |
| Reference suite | 5737 passed, 24 skipped | 5756 run, **4 failed**, 24 skipped | PENDING |
| Installer sub-suite | 172 passed | 178 passed | PENDING |

The counts rose because this phase added tests (the startup deferral, the
session templates, the copy primitive and its negative control, the companion
mode, the text-only toggle, and the evidence credential gate). A rising total
with a stable pass set is the expected shape; it is stated because a changed
denominator is exactly what makes "the suite is green" unfalsifiable.

The four failures are classified individually in §17. None is dismissed as
flaky without a mechanism.

## 17. Failure classification

PENDING for the suite rows — completed once the uncontended run exists.

One class is already settled, and it is a harness failure rather than a
product one, so it is classified here rather than counted against the
candidate.

### The qualification chain died three times, and not from what it looked like

**Symptom.** `qemu-system-x86_64: terminating on signal 15 from pid 1
(/sbin/init)`, mid-journey, with no other diagnostic. The chain unit
disappeared with it.

**What it looked like.** An out-of-space kill. The host volume had 11 GB free
of 952 GB and the WSL VHDX was 731.5 GB, so the available story was the
familiar one from `wsl-vhdx-cannot-grow` — a full host disk that the guest
cannot see, presenting as I/O failure. That story was wrong, and acting on it
would have meant a privileged 380 GB disk operation to fix a problem that was
not there. It was falsified by measurement: across six VM journeys the VHDX
did not grow by a byte (§5E), because a guest reuses blocks its image has
already claimed.

**Second wrong answer.** The WSL utility VM's idle shutdown, which
`vmIdleTimeout=-1` in `.wslconfig` already disables — and the file was
verified present, unmangled and at the path WSL reads. `journalctl
--list-boots` then showed a **single** boot spanning every one of the deaths:
the VM never restarted, so no VM-level timeout could have been responsible.

**Actual cause.** WSL tears down a *distribution* when its last attached
client exits, independently of the utility VM's lifetime; `/sbin/init` is
WSL's own init, and signal 15 from pid 1 is that teardown. Every launch had
been made from a client that exited as soon as it had issued the command, so
the launching client's own exit is what killed what it had just launched —
about fifteen seconds later, which is why the deaths looked like a crash
partway into a boot. `systemd-run` does not protect against this: a transient
system unit is still the distribution's process.

**Why it survived the first time.** The chain's first run lasted 55 minutes
because an unrelated client happened to be attached throughout. That is the
worst kind of intermittency — a fault whose absence has a cause nobody has
noticed.

**Fix.** The client that starts the chain holds itself attached until the
chain finishes (`start-and-hold.sh`). The chain then ran to completion.

**Classification: environment, mechanism identified, mitigated in the
harness.** No product code is implicated, and no product result was measured
through a killed run — g7's aborted attempt was discarded and re-run from a
recovery boot (`g6r`) rather than repaired, because a disk left mid-session by
an infrastructure kill is not a state the product was asked to be in.

## 18. Remaining limitations

PENDING for the artifact runs' contribution — carried forward from
`KNOWN_LIMITATIONS.md` with this phase's additions. Settled so far:

### The compact/minimal boundary

Stated in full in §10: the mode is honoured by the Companion window and its
figure, not by the shell's centre-stage character, whose geometry is a
negotiated layout this hardening phase does not re-open.

### The Alpha UX pass: one cosmetic defect, deliberately not fixed

Read off the booted release candidate rather than inferred — the Quick Access
tile for Diagnostics is drawn as **"Diagnostic-"/"s"**, hyphenated across two
lines.

The cause is exact. `lib/widgets.js`'s `iconTile()` sets
`set_line_wrap_mode(2)`, which is Pango's `WORD_CHAR`: wrap on word
boundaries, and fall back to breaking *inside* a word when no boundary fits.
"Diagnostics" is a single word wider than a tile, so every wrap is the
fallback, and Pango inserts a hyphen at a mid-word break. The two-line wrap
was intended and is working; the hyphenated break is the part nobody chose.
The comment above that line records this label being fixed once already, as a
`Diagnosti…` ellipsis — so this is the third time the same tile has been too
narrow for its own name.

It is **not fixed in this candidate, on purpose.** `shell/` is a build COPY
root: changing it produces a different image, which discards the qualified
artifact and every run in §7–§14 with it. Re-qualifying a release candidate to
remove a hyphen is not a trade this phase will make. The fix — suppressing
hyphen insertion, or giving the tile a name that fits — belongs to the next
build, and it is recorded here with its cause so it costs minutes then.

### The host build volume

§5E: 11 GB free on the host volume. A standing risk that did not affect any
run in this phase, with the durable fix named and left to the operator.

## 19. Evidence inventory

PENDING.

## 20. Exact release artifact digest

PENDING — the artifact commit is **e906a487**; ISO, shell-test and payload
digests are recorded from the build's own output and reproduced in
`qualification/phase4/artifact/ARTIFACT.md`.

    ISO         823d50caba35afe72452768affd5f6fa0ac8cfc13c164f0e1bc909fa887ab421
    shell-test  83c31d0640e4aef6059004d5ff3f954879bd92a3723f4173dc71e53a39963a99
    payload     localhost/bunny-os-beta:e906a48793d7
                manifest sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d

**Two lines of that record are wrong**, and are corrected in
`qualification/phase4/artifact/CORRECTION.md` rather than edited, because a
committed evidence file is not rewritten:

- `dirty: 1 file(s)` was measured a minute *after* the last artifact was
  produced, by the recording script rather than by the build. The build's own
  measurement, taken immediately after `git reset --hard` and immediately
  before the first image, is `dirty: 0` at `e906a487` — with a fatal guard
  asserting the commit. The build log is retained beside the record as
  `p4-build.log` so this is checkable rather than asserted. **The artifact was
  built from a clean tree.**
- The payload reference was printed doubled
  (`localhost/bunny-os-beta:localhost/bunny-os-beta:e906a48793d7`), which is
  not pullable. The single form is above.

Both are defects of the recorder, now fixed at source in
`build/scripts/rc-identity.sh`: it prefers the build log's build-time
measurement, *names* dirty files instead of counting them, warns when the log
names a commit that is not HEAD, and prints the repository tag once. The
warning path was exercised deliberately before this was written.

Two earlier builds were made and **discarded**, and are named here so that no
digest from either can be mistaken for the candidate:

| Commit | Why it is not the candidate |
| --- | --- |
| `9b1a9354` | Built from a builder repo that a concurrently-running suite `git reset --hard`-ed mid-build. The tree it was built from is not a tree that ever existed. |
| `15a9be16` | The two accountsservice templates were crossed in the image: `shutil.copyfile` wrote *through* an RPM hardlink group, so `standard` and `administrator` held identical bytes. Fixed at `e906a487`. |

## 21. Alpha release decision

PENDING.
