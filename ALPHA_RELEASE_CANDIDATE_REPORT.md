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

All four entering defects are closed with evidence on the artifact, and a
fifth thing was closed that nobody had listed: Track 1b, `NOT_RUN` since
Phase 3, is published.

The second finding of the phase is about the qualification itself. **Six
harness defects were found, and four of them had been producing passes** — a
Trust journey graded green while its own screen said "the task failed"; a
login story that booted, photographed a desktop and shut down without running
the journey it was given; a probe that truncated its own audit and reported
kernel threads as a desktop's process table; and a session driver that wrote
an account password into the evidence tree. Every one was found by looking at
what a run actually did rather than at whether it went green.

That is why §21 does not treat a green suite as an answer, and why the
strengthened graders in this phase were each replayed against a run that
*should* fail before being trusted.

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

**Closed: PASS, published 2026-08-17.** All three retained inputs — base
image, builder image, package snapshot — pushed by digest and verified by
reading each manifest back from the registry.

Phase 3 recorded this `NOT_RUN — AUTHENTICATION BLOCKED` and refused two
credential paths because each moved a live credential across an environment
boundary. The path taken is the one that disposition itself named as the
remaining requirement: the token is resolved **inside the builder** by the
operator's own `gh` through WSL interop, so the credential is used where it
lives. Written to a root-only file, read once, deleted by the publishing unit
before anything else ran.

A second blocker replaced the first and is recorded rather than smoothed over:
four attempts failed on `HTTP 503` from `api.github.com` across roughly three
hours. That distinction matters — "the token cannot publish" and "the service
was down" are different findings, and the run that eventually succeeded used
the same token as the first that failed. §5 of the directive said not to
fabricate completion; the honest version is that this took a service outage to
wait out, not a credential fix.

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
| — | `e906a487` | The one install primitive must not write through a hardlink. `shutil.copyfile` follows an existing destination, so installing over an RPM's hardlink group rewrote its sibling — which is how the two accountsservice templates came out identical in the previous build. Unlink first, then copy. |

### Fixes to the qualification itself

Not product changes, but this phase's output all the same, and §17 explains
what each one was hiding.

| Commit | What changed |
| --- | --- |
| `8fe70a53` | A hygiene audit that cannot report kernel threads as a desktop: the probe no longer truncates its own output at 4000 characters, records `truncated` and `stdoutBytes`, and terminates a session with `loginctl terminate-user` rather than parsing a `--output=json` this `loginctl` ignores. |
| `72a7823a` | The login story chooses the account instead of typing at whoever the greeter offers, and photographs the choice. |
| `a07b76a0` | The Trust journey is gradable: the fixture clears the capsule's persistent exports and reports what it removed; the story grades the journey's outcome rather than only the machine's health. |
| `020acd4e` | A denial has to mean the confined program never ran — graded from the journal, with the granted run as the control. |
| `5cdd5139` | A hygiene audit taken while the user is still `closing` cannot say "no leak"; a third audit is taken after the close completes. |
| `82dc0c6f` | A journey must not write down the password it was given — redacted at every depth, in the driver and again at staging. |

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

**PASS.** `journey-e` — an unattended encrypted install driven through the
shipped setup surface — completed with `findings: []`, followed by
`first-boot-e`: two encrypted boots of the installed disk, each unlocking LUKS
and reaching a graphical session.

The install is bound to the named artifact rather than to "the latest build",
which the directive's §14 forbids: the run hashes the medium it is about to
install from, and its log records

    823d50caba35afe72452768affd5f6fa0ac8cfc13c164f0e1bc909fa887ab421
      build/out/live/…/bunny-os-0.3.0-live.e906a48793d7-x86_64.iso

which is the ISO digest in `ARTIFACT.md`, byte for byte. Every result in
§8–§14 descends from this install, so they all inherit that binding.

## 8. Login result

**PASS.** `g1`: a fresh machine from the installed disk, a real GDM login, and
the first-run wizard walked through the product's own surface. `findings: []`,
all five journal checks true, and **11 of 11** first-run choices applied with
no failures (`applied: 11, failures: []`).

### Session lifecycle and process hygiene

The directive's §7 asks what a session leaves behind. `g9` is the first run in
this project able to answer, because the previous attempt's instrument was
broken in two ways at once (§17, defect 6).

| | Logged in | 5 s after logout |
| --- | --- | --- |
| `loginctl` state for `alex` | `active` | `closing` |
| `alex` processes | 64 | 5 |
| Bunny processes | 5 — 2 of them `alex`'s | 3, **all root** |
| Total processes | 229 | 218 |
| Audit truncated? | no | no |

The two Bunny processes belonging to the user — `gdm-wayland-session` running
`bunny-shell-session`, and `bunny-companion-service` — are both gone. The
three that remain are the system broker and the harness's own probe, both
root-owned and both system-wide by design.

**PASS — the session tears down completely.** But not for the reason the
process audit appears to give, and the difference is the finding.

### The five survivors are created by looking for them

`g14` repeated the story with a third audit. Every process count came back
identical — `alex` still `closing`, still five processes — which reads exactly
like a session that never finishes shutting down.

It is not. The machine's own journal settles it:

    17:41:24  Removed slice user-1000.slice - User Slice of UID 1000.
    17:41:24  user-1000.slice: Consumed 9.109s CPU time over 1min 46s, 1.1G memory peak.

That is a complete teardown, with the accounting systemd only prints when a
slice is really removed. Twenty-three seconds later:

    17:41:47  sudo[6238]: root : USER=alex ; COMMAND=/usr/bin/env
              XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=…
    17:41:47  Created slice user-1000.slice
    17:41:47  Starting user@1000.service - User Manager for UID 1000...
    17:41:47  New session '5' of user 'alex' with class 'manager'
    17:41:47  Started mpris-proxy.service - Bluetooth mpris proxy.

**The probe's own `sudo -u alex` made logind build a fresh user manager**,
which brought up `mpris-proxy` and `dbus-broker` with it. Those, plus
`systemd --user` and `(sd-pam)`, are the five "survivors" — and their PIDs
(6242–6265) are far above the real session's (3398, 3680), with process ages
of **0 and 5 seconds** at the two audits. They are newer than the logout that
supposedly failed to kill them.

So the audit cannot answer its own question, because asking it requires
becoming the user, and becoming the user is what creates the processes. The
answer comes from the journal instead: the slice was removed, and nothing of
the Bunny session outlived it.

### Two measurement errors, both mine, both recorded

1. **The delay was in the wrong place.** `phase3-session.py` applies `sleep`
   *after* a step, so `sleep: 40` on the final audit delayed the run's end
   rather than the audit itself — the third audit ran five seconds after the
   second, not forty-five. The `etimes` column is what exposed it: the
   survivors aged 0 → 5, not 0 → 45. Fixed by moving the delay to the
   preceding step.
2. **The instrument perturbs what it measures.** Recorded rather than fixed:
   removing it means an audit that never touches the user's identity, which is
   a redesign of the probe and not something to attempt inside a frozen
   candidate.

Neither changes the result, and both are here because a reader who checks the
process counts will see what looks like a leak and should be able to find out
why it is not.

## 9. Persistence result

**PASS**, across four boots rather than asserted once.

| Run | What it did | Outcome |
| --- | --- | --- |
| `g2` | configured five settings and chose the **compact** companion mode | written |
| `g3` | read them back after a real reboot; chose **minimal** | compact survived |
| `g4` | read back after another reboot | minimal survived |

Each read-back went through the product's own settings surface, not through a
file the harness had written, so what is demonstrated is that the system
restores the choice — not that a value can be round-tripped.

## 10. Companion result

**PASS.** Limitation C is closed. The chrome level persists in the one
authoritative settings document, the window opens in the compact shape for a
compact or minimal install, and the presenter sizes the figure by the design
tokens' ratios.

On the artifact: g2 chose **compact**, g3 read it back after a real reboot and
chose **minimal**, g4 read minimal back after another. The first-run applier
records the level (`character.companion_mode = full` is visible in g9's
applied-state capture, one of the 11 applied choices) rather than the apology
it used to write.

The fix is one field in the canonical document — `character.companionMode`,
`full`/`compact`/`minimal` — not a renderer-specific store. The directive's §4
asked for that
explicitly and it would have been the easy thing to get wrong.

**Boundary, stated plainly:** the mode is honoured by the companion *window*
and its figure. The shell's centre-stage desktop character keeps its stage
geometry, which is a negotiated layout (`lib/layout.js`: the character owns
the middle and the card columns negotiate around it). Re-deciding that
geometry per mode is a layout change this hardening phase does not make —
the directive's §9 forbids redesigning the renderer architecture and its §20
freezes it. So a
person who chooses `compact` gets a compact companion window and a
persisted, applied preference; they do not get a smaller centre-stage
figure. That is a limitation, recorded in §18, not a claim.

## 11. Voice result

PENDING — the Stage 2 primary acceptance (`accept-all.sh`) against the
release-candidate shell-test image (`83c31d06…`).

**Baseline**: the same acceptance on the Phase 3 image, `voice-phase3-b`,
`exit=0` across its seventeen stages — boot, audio devices in the session,
microphone and utterances, three spoken requests, what opened and which engine
spoke, the speaker's own recording read back, interruption, performance, voice
settings, the provider-unavailable ladder (Pocket → Kitten → every provider
unavailable → restored), and offline. The RC run is compared stage for stage
against that, not merely on its exit code.

## 12. Trust result

**PASS, both directions**, on the artifact, against a harness that was first
shown capable of failing them.

| | Granted (`g12`) | Denied (`g13`) |
| --- | --- | --- |
| Prompt drawn and answered | yes | yes |
| Decision recorded | `granted` | `denied` |
| Capsule started | **yes** | **no** |
| Produced | `holiday-resized.png`, `100×50` | nothing |
| Final state | `idle` | `idle` |
| Final words | "Done. I made Pictures/holiday-resized.png at 100 pixels wide. Your original wasn't changed." | "the request was declined" |
| Input digest after | unchanged | unchanged |
| Untouched neighbour | unchanged | unchanged |
| `findings` | `[]` | `[]` |

Both ran under the strengthened grader, which was first replayed over the
recorded runs and shown to **fail** g7 and **pass** g8 — so a pass here is a
pass from a check that rejects something.

One detail makes g13's `produced: []` mean what it says. Its fixture reports
clearing `…/exports/holiday-resized.png` — the file **g12 had just created**.
So the denied run began with the output absent and ended with it absent. Had
the fixture not cleared it, "nothing was produced" would have been
indistinguishable from "the previous run's file is still sitting there".

The granted result matches the Phase 3 baseline exactly —
`journey-b38d51000543-granted` recorded `files: ["holiday-resized.png"]`,
`pixels: [100, 50]` — and the sandbox's own journal line is
`bunny-image-tool: wrote holiday-resized.png at 100x50`.

**The denial is the stronger of the two results.** "Nothing was produced" is a
weak claim, because a task that crashed before writing also produces nothing.
What makes this a security outcome is that **no capsule unit was ever
started** — and that is a measurement rather than an absence of
instrumentation, because the granted run shows the same journal line present.
Denial prevents execution, not merely output.

### Getting here took two harness fixes, and the first attempt was a false pass

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

**Confirmed by measurement, not left as an inference.** The repaired fixture
reports what it removes, and on `g12` it named exactly the predicted file:

    clearedExports: ['/home/alex/.local/share/bunny/capsules/
                      art-comrade-bunnyimagetool.88d8725406aed402/exports/
                      holiday-resized.png']

That path is the diagnosis. Clearing it is the whole difference between g7's
"the task failed" and g12's "Done."

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

**PASS**, and it is the strongest result in this report because it was never
run as its own test.

Every login story ends by pressing the machine's ACPI power button from the
host and grading what follows. The story writes an `unclean-shutdown` finding
if the next boot's journal shows the previous one was cut off, so a run that
ends `findings: []` is also a statement that the press worked. On the release
candidate that happened on **every** boot of the qualification chain — journey-e,
first-boot-e's two encrypted boots, and g1 through g10 — with no
`unclean-shutdown` finding anywhere.

The discriminator this phase discovered is present too: `GNOME Shell started`
appears in the journal of the Bunny-session runs (checked explicitly on g7),
which is the message whose *absence* was the defect. Startup completes,
`Main.actionMode` leaves `NONE`, `_filterKeybinding` stops dropping every
accelerator, and the power key is delivered along with everything else.

Before the fix this was not merely failing, it had never once worked: the
defect was present from the first boot the Bunny desktop ever ran.

**p4-power-11**, on the installed Phase 3 machine with the fixed extension
shadowed over the image copy, was the first Bunny-session boot in the
project's history to end `findings: []`. The chain then reproduced that on the
artifact itself, a dozen times, without being asked to.

## 14. Multi-user result

**PASS.** Limitation B is closed, on the artifact, end to end.

`g5` created two accounts through AccountsService's `CreateUser` — the call
gnome-control-center's Users entry and gnome-initial-setup both make — one
standard (`robin`), one administrator (`sam`). Both records came back carrying
`Session=bunny`, and each from the correct template: the standard account from
`standard`, the administrator from `administrator`. That distinction matters
because the two template files are byte-identical in content but not in
purpose, and an earlier build had them crossed by a hardlink (§20).

`g10` then logged `robin` in **at the real greeter**, and the result is a
photograph rather than an inference: the desktop says *"Good evening, Robin"*,
with the Bunny shell, dock, Quick Access and the Companion, and the first-run
wizard opening at step 1 of 10. `findings: []`, `sessionOpened` true for
`robin(uid=1001)`, every journal check true.

### The first attempt failed, and the failure was the harness's

`g6` — the same story before the fix — exited 6. GDM opens on the last user's
password prompt, so the story typed robin's password into alex's field and
recorded a machine that had logged nobody in. The story now walks back to the
user list, chooses a row, and **photographs the choice** before typing
(`t150-user-chosen`, showing "Robin Second" with an empty focused password
field). A blind login is not evidence about a second account; it is evidence
about whichever account the greeter happened to offer.

## 15. Performance measurements

PENDING for the artifact run (g11). The comparator is chosen in advance so the
result cannot be graded against whichever baseline flatters it.

**Instrument.** The probe's `performance` verb: CPU as a *delta* in
`utime + stime` clock ticks read from `/proc` across a fixed idle interval, not
`ps`'s `%cpu`, which is an average since process start and on a session that
has just completed a permission journey is a number about the journey. RSS from
`VmRSS`.

**Baseline** — `qualification/design/performance.json`, candidate `7edd3fd`,
the same verb and the same 20-second interval, so the two are comparable
without adjustment:

| Process | Processes | CPU idle | RSS |
| --- | --- | --- | --- |
| `gnome-shell` | 4 | 0.80 % | 391.2 MiB |
| `companion` | 1 | 0.35 % | 61.6 MiB |
| `orca` | — | 0.00 % | — |

`qualification/voice-release/evidence/final/logs/cpu-idle.json` also carries an
idle sample (gnome-shell 7.75 %, 322.3 MiB) but over a 60-second window from a
different instrument on the voice image, so it is **not** used as the
comparator; it is named here so that a reader who finds it knows why.

g11 samples twice — once when the session settles and again after a further
idle gap — because a single sample cannot distinguish "idle" from "still
starting up", and the difference between the two is itself worth recording.

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

### Every dimension against its Phase 3 baseline

Not just the suites. Each row names the record it is compared against, so a
claim of "no regression" can be checked rather than believed.

| Dimension | Phase 3 baseline | Release candidate `e906a487` |
| --- | --- | --- |
| Encrypted install | journey-e passed | **PASS** — `findings: []` from the RC ISO |
| Encrypted boot | first-boot-e passed | **PASS** — two boots |
| First login + wizard | login stories passed | **PASS** — g1, 11/11 choices applied |
| Setting persistence | passed | **PASS** — g2→g3→g4 across two reboots |
| Companion mode | *no persisted representation* | **PASS** — compact and minimal both survive a reboot |
| ACPI power key | **never worked, on any boot** | **PASS** — clean shutdown on every boot of the chain |
| Second account | *lands in stock GNOME* | **PASS** — robin gets the Bunny desktop |
| Trust — denied | `files: []` (`journey-b38d51000543-denied`) | **PASS** — `files: []`, and no capsule ever started |
| Trust — granted | `files: ["holiday-resized.png"]`, `pixels: [100, 50]` | **PASS** — identical: `["holiday-resized.png"]`, `[100, 50]` |
| Voice acceptance | `voice-phase3-b exit=0`, 17 stages | PENDING |
| Idle cost | shell 0.80 % / 391.2 MiB; companion 0.35 % / 61.6 MiB (`7edd3fd`) | PENDING g11 |
| Reference suite | 5737 passed, 24 skipped | PENDING uncontended |
| Installer suite | 172 passed | PENDING uncontended |

Three rows are not "no regression" but "worked for the first time": the power
key, the second account and the companion modes were the phase's brief.

## 17. Failure classification

Every failure below carries a mechanism. None is filed as "flaky", "expected"
or "minor" — §16 of the directive forbids those words without a technical
explanation, and a label is not one.

### The four suite failures at `9b1a9354` (contended run)

| # | Test | Classification |
| --- | --- | --- |
| 1–3 | `test_character_cli_vertical` × 3 | **Measurement changed by host contention.** PENDING confirmation by the uncontended run. |
| 4 | `test_no_file_was_added_to_an_earlier_phase_tree` | **Correct failure; repaired structurally.** |

**1–3, the mechanism.** All three fail on the same two slice steps —
`step 17 (trigger controlled presentation pressure)` and `step 21 (recover
only after hysteresis)`. Both assert that the effective presentation is
`animated-2d`. The slice pins the environment with `_VISUAL`, which overrides
`display_available`, `graphics_ready`, `available_memory_bytes` and
`gpu_available` — and **deliberately does not override `dropped_frame_ratio`**,
because a frame-drop measurement the test supplied itself would prove nothing.
`companion/character/adaptation.py` degrades the presentation rung on real
dropped frames. So a host running a 4-vCPU QEMU guest at the same time changes
the quantity the test measures, and the rung falls below `animated-2d`. The
test is not lying; it is measuring a real thing under conditions that make it
true. **This is the claim the uncontended run exists to confirm or refute**,
and if it fails uncontended it is a defect, not contention.

**4, the mechanism.** The check asserts that no file has been added to an
earlier phase's evidence tree. Phase 4 committed its own tree, which is a new
phase and not an earlier one. Every phase since the record was cut has
declared itself in `_PHASES_AFTER_THE_RECORD`; Phase 4 had not yet. Repaired
by declaring `qualification/phase4/` (`39234768`) — a structural repair, not a
weakened assertion: the check still fails for a real edit to an earlier tree.
This is the fourth time in this project a gate has failed *because the
property it guards got better*, which is a pattern worth naming rather than
patching each time.

### Six harness defects, found by qualifying rather than by testing

None is a product defect. All six are listed because each one had been
silently producing a *result*, and four of them were producing a **pass**.

| # | What it did | How it was caught |
| --- | --- | --- |
| 1 | The story graded machine health only, so a granted Trust journey that produced nothing scored `findings: []`. | Reading g7's screen: "the task failed", against `findings: []`. |
| 2 | The journey fixture reset `~/Pictures` but not the capsule's persistent `exports`, so a granted journey could never succeed twice on the same machine. | The sandbox's own journal line, `the output already exists`. |
| 3 | `launch_login_as.sh` hardcoded `BUNNY_LOGIN_INTERACT=0`, so g12 booted, logged in, photographed the desktop and shut down without running the journey it was asked for. | g12 finishing in 3.5 minutes when g7 had taken 16. |
| 4 | The session driver recorded each request verbatim, writing an account password into the evidence tree in plaintext. | `tests/evidence/test_no_credentials_in_evidence.py`, on its first run against real staged evidence. |
| 5 | The hygiene audit ran five seconds after logout, while `loginctl` still said `closing` — unable to distinguish a teardown in progress from a leak. | Reading the audit rather than its verdict. |
| 6 | The probe truncated its own output at 4000 characters and reported 27 kernel threads as a desktop's process table; the `logout` verb parsed a `loginctl --output=json` this `loginctl` ignores, so nothing was terminated and the "after" audit compared a logged-in machine with itself. | Found in Phase 4's first hygiene attempt; fixed at `8fe70a53`. |

Defects 1, 3, 4 and 6 each produced a green result from a run that had not
done what it claimed. That is the failure mode this phase should be judged
against, and it is the reason §21 does not treat a green suite as an answer.

### The infrastructure failure: the chain died three times, and not from what it looked like

A harness failure rather than a product one, so it is classified here rather
than counted against the candidate.

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

### The qualification harness grades without being graded

`build/scripts/vm-login-story.sh` decides whether every VM run in §7–§14
passed, and **no automated test covers that decision**. Nothing in `tests/`
references it. That is not incidental to this phase: it is why a granted Trust
journey could be recorded `findings: []` while its own screen said "the task
failed", and why the defect survived until somebody looked at a screenshot.

The grading logic lives inside a Python heredoc in a shell script, which is
where it is convenient to run and not where it can be tested. This phase
validated the strengthened version the only way available without a refactor —
replaying it over the two runs already recorded, and checking that it fails g7
and passes g8 — and that replay is a manual act, not a gate.

**Extracting the grader into an importable module with fixtures from the
recorded runs is the single highest-value piece of work this report can point
at.** It is a refactor, so it is not done here: the directive's §20 freezes
the candidate, and this phase's own finding is that changing the instrument
during qualification is how false results arise.

### The greeter is not Bunny's

Read off `g10`'s and `g12`'s greeter screenshots: the login screen is stock
GNOME with Fedora's logo and a generic avatar. Everything after login is
Bunny — the shell, the dock, the Companion, the wallpaper — and the first
screen a person meets says Fedora. Not a defect in anything that was built
this phase, and not fixable without changing the image (§20), so it is
recorded rather than fixed.

### The desktop background fails to load

`gnome-shell` logs, on every Bunny-session boot:

    Failed to load background 'file:///usr/share/backgrounds/bunny-os/bunny-nocturne.svg':
    Unknown image format: application/xml

The desktop looks right because the shell falls back to its own dark fill, so
this cost nothing visible and was found in a journal rather than on a screen.
The SVG is being served as `application/xml` and GdkPixbuf declines it.
Recorded, not fixed, for the §20 reason.

### The host build volume

§5E: 11 GB free on the host volume. A standing risk that did not affect any
run in this phase, with the durable fix named and left to the operator.

## 19. Evidence inventory

Everything below is committed under `qualification/phase4/`. Counts are filled
in when the last run lands.

### `artifact/` — what was built, and what the record got wrong

| File | What it is |
| --- | --- |
| `ARTIFACT.md` | The identity record as written: commit, pinned base, builder image, package snapshot, every artifact digest, package versions of the parts this phase changed, and the test environment. |
| `CORRECTION.md` | Its two wrong lines, corrected without editing it (§20). |
| `p4-build.log` | The build's own log, retained because it is what settles the `dirty: 0` question. Its stage markers are the only record of when each artifact was produced. |

### `power-key/` — eleven boots, and the finding they produced

`p4-power-1` … `p4-power-11`, each with `result.json`, `interaction.json` and
`journal-lastboot.log`, plus `FINDING.md` narrating what they establish
together. They include the runs that were *wrong* and why — a killed
`gsd-media-keys` that produced a clean shutdown for the wrong reason
(`p4-power-3`), a control that was not a control because
`gnome-extensions disable` persists in dconf (`p4-power-5`), and two runs whose
injected extension was silently ignored by composefs (`p4-power-9`,
`p4-power-10`). A record that keeps only the run that worked cannot be checked.

### `release-candidate/` — the qualification chain on the artifact

`journey-e` and `first-boot-e` (the install and its two encrypted boots), then
one directory per login story: `result.json`, `journal-lastboot.log` and a
redacted `interaction.json`, with screenshots kept for the runs whose claim is
visual — the account-creation and second-account stories, and the Trust
journeys.

`g5/REDACTION.md` declares the two credential values removed from that
record and why redaction rather than correction was the right answer there.

### `track-1b/` — the retained-input publication

`DISPOSITION.md`, `publication.log` and `input-publication-lock.json`.

### Not published, deliberately

The machine disks, packet captures and framebuffer dumps stay on the builder:
they are the products of these runs rather than evidence about them, and
`tests/evidence/test_no_credentials_in_evidence.py` states that scope rather
than leaving it as a gap somebody has to notice.

## 20. Exact release artifact digest

**Settled.** The artifact commit is **e906a487**, built from a clean tree.
ISO, shell-test and payload digests come from the build's own output and are
reproduced in `qualification/phase4/artifact/ARTIFACT.md`.

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

PENDING the last runs. The evidence the decision rests on is recorded here in
advance of it, so the verdict can be checked against something rather than
taken.

### Two different questions, and only one of them is this phase's

**"Is this a qualified release?"** is answered by the project's own gates, run
against this tree, and both say no:

    $ python scripts/release.py gate --kind qualification-candidate
    qualification candidate gate: BLOCKED
      ok      PASS                     Licence gate passed
      BLOCKED PENDING_EXTERNAL_REVIEW  Vulnerability gate passed
      ok      PASS                     Independent reproducibility passed
      ok      PASS                     Development signing drill passed
      BLOCKED NOT_RUN                  Independent recovery media passed
      BLOCKED NOT_RUN                  Installation matrix passed
      BLOCKED NOT_RUN                  Encryption matrix passed
      BLOCKED NOT_RUN                  Update matrix passed
      BLOCKED NOT_RUN                  Rollback matrix passed
      BLOCKED PENDING_HARDWARE         Physical hardware evidence passed
      BLOCKED PENDING_EXTERNAL_REVIEW  Accessibility evidence passed
      BLOCKED PENDING_EXTERNAL_REVIEW  Independent reviews passed
      BLOCKED BLOCKED                  Second production signer available
      BLOCKED PENDING_OWNER            Protected approvals complete

    $ python scripts/release.py gate --kind stable-release
    stable release gate: NO-GO

The gate's own closing line is the governing sentence: *"No artifact may be
labelled release-qualified. Building a candidate for examination remains
permitted; calling one qualified does not."*

None of those blockers is Phase 4's to clear, and none was in its scope: an
independent security review of 59 fixable findings inherited from
`fedora-bootc:44` (8 Critical, 28 High, every one from the upstream base and
none added by Bunny), a physical machine, production signing keys, a second
signer, four qualification matrices, and owner approvals.

**"Did Phase 4 do what it was asked?"** is the question this report answers,
and it is scored against §1's chain — known defects → fix → regression test →
fresh build → clean install → full qualification → alpha release candidate.

### What would make this BLOCKED rather than READY

Stated before the results, so the bar cannot move to meet them:

1. Any of the four entering defects not fixed, or fixed without evidence.
2. The candidate not installable from its own medium onto a clean machine.
3. A Trust journey whose security outcome is wrong in either direction —
   a denial that runs the program, or a grant that cannot.
4. Voice regressing against the Phase 3 baseline.
5. An uncontended suite failure that is a real defect rather than a
   measurement artefact.
6. Any claim in this report that its own evidence does not support.
