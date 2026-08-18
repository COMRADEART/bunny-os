# Phase 5 — Alpha Feedback, Performance & Release-Gate Closure

## STATUS: **PHASE 5 — RELEASE CANDIDATE BLOCKED**

**The reference-suite gate is CLEAN.** Five consecutive full runs, 5979 tests
plus 178 installer tests each, zero failures and zero errors; eight consecutive
`tests/companion` runs, zero slice failures. Its root cause was found and fixed.
That is the one required gate Phase 5 could close by itself, and it is closed.

**Phase 5 built an artifact** — `e501218f2fe0.1787016937`, its own identity,
nothing of Phase 4's reused — and the two repaired assets are verified in it
with a negative control. It is not a release candidate and makes no
reproducibility claim; it exists to answer questions one image cannot be asked.

Not `ALPHA HARDENED`. The new build is unqualified: none of the journey
evidence the Phase 4 candidate carries has been re-run against it, and a fresh
image is not a hardened Alpha either.

Not `RELEASE GATE READY`: five required gates remain outstanding and four of
them cannot be closed from inside this repository at all.

Never `STABLE RELEASE`.

**The Phase 4 Alpha Release Candidate `e906a487` is untouched and remains READY
as an Alpha Release Candidate and nothing else.** Its build output was moved
intact when the output directory had to be cleared, its qcow2 still hashes to
the digest its own manifest records, no digest in `qualification/phase4/`
changed, and it was not re-graded under a different name.

---

## 1. Phase 4 baseline

Recorded in full, before any change, in
`qualification/phase5/baseline/BASELINE.md` and `baseline.json`.

| | |
| --- | --- |
| Phase 4 final tree | `e4d01389` |
| **Artifact commit** | **`e906a48793d74544b39c14cc3e35e0654f5311e2`** |
| ISO | `823d50caba35afe72452768affd5f6fa0ac8cfc13c164f0e1bc909fa887ab421` |
| Beta payload | `sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d` |
| Shell-test image | `83c31d0640e4aef6059004d5ff3f954879bd92a3723f4173dc71e53a39963a99` |
| Base (retained) | `sha256:1f08084a9a8545bd528641d4fda14e18408dfb1298acda243eaf583cd907a844` |
| Evidence files | 166 |

Baselines captured: test (5762 run, 3 intermittent), performance (shell 2.07 %
/ 387.4 MiB against 0.80 % / 391.2 MiB at `7edd3fd`), voice (`voice-phase3-b`,
exit 0, 19 stages), Trust (both directions), installation, persistence, and
eleven known limitations L1–L11.

Two corrections from `qualification/phase4/artifact/CORRECTION.md` are carried
into the baseline: the tree was **clean** at build time (`dirty: 0`), and the
payload reference is `localhost/bunny-os-beta:e906a48793d7` singly.

**The candidate is the artifact, not the tree.** Twelve commits separate
`e906a487` from `e4d01389` and eight touch `build/`, a `COPY` root.

---

## 2. Changes made

22 commits so far, counting from `e4d01389`. Every one of them is either a
fix with a negative control or evidence with its scope stated.

| Commit | What |
| --- | --- |
| `eca0efaf` | The VM journey grader extracted to `qualification/grader/`, with fixtures and 31 tests |
| `9a34ee81` | The wallpaper defect: root cause corrected and fixed, swept across all shipped SVGs |
| `f830ca3a` | 153 tests recovered into the reference suite; feedback taxonomy extended |
| `d548d100` | Poller instrumentation; the leading performance hypothesis measured and cleared |
| `49cd25f8`, `8f862ea3` | The slice records *why* the selector degraded — the diagnostic that found the cause |
| `ea3d6bf9` | Security disposition, signing conformance, hardware track, feedback plan, gate tracker |
| **`30f11a6d`** | **The isolation root cause: the host's own memory pressure, and the pin that closes it** |
| `551e4198` | The candidate scanned by a no-copy route; 183 matches are 56 advisories |
| `893ad65d` | The grader's CLI was rewriting the collector's `schemaVersion`; 9 CLI tests |
| `324cae32` | The reference-suite gate certified CLEAN, and the candidate's SBOM |
| `fe971ca7` | The shellcheck gate was linting files that are not in the repository |
| `513c6a9b`, `e501218f` | The report; the reference suite removed from the blocker list once it was closed |
| `a3b684ab` | The seven Criticals did not go away — the scanner stopped reporting them |
| `738e53df` | The disk blocker was never real; the Phase 5 build; the archive scan that corrects the security account |
| `3bf6a6e6` | Boot parity, and the update path's real posture: no trust root in the image |
| *this commit* | A real staged update and a real rollback — and the rollback harness that was passing without one |

**No product behaviour was changed except two asset files.** The poller work
adds measurement and changes no cadence; §10's warning against sacrificing
correctness for a benchmark has more force once the obvious suspect is cleared,
and an optimisation made now would be one made for no measured gain.

Two changes landed in `build/scripts/` **after** the Phase 5 build: the
rollback harness repair and the deployment helpers it needed. They are
measurement, not product, and the artifact predates them — recorded here rather
than left for a reader to discover from a digest that no longer matches.

---

## 3. Qualification-harness improvements

The directive's first priority, and Phase 4's own nomination for the
highest-value work available.

**`qualification/grader/` is a library.** `models.py`, `rules.py`, `core.py`,
`cli.py`, `fixtures/`, `tests/`. It reads recorded evidence and returns
PASS / FAIL / NOT_RUN with a sentence a person can act on. It needs no VM:
extraction wants `guestfish` and `journalctl`, grading wants a directory, and
keeping them apart is what lets the fixture suite run on a laptop.

**The regression that justifies it.** `g7` — a granted Trust journey whose own
record reads `final.state: "error"`, `final.says: "the task failed"`,
`result.files: []`, recorded at the time as `findings: []`. It now grades
**FAIL** on RJ04, RJ06 and RJ12.

Its **machine dimension still passes**, and that is the point. The machine was
healthy. Health was never the question.

`g12` and `g13` still pass under the same grader, so this is a check that
rejects something rather than one that rejects everything — Phase 4's rule for
trusting a strengthened grader, made into a test rather than a shell session.

**Three things Phase 4's harness could not express:**

*NOT_RUN is an answer.* A run that measured nothing does not share a colour
with a run that measured everything and was fine. A PASS names the dimensions
it did not grade, every time.

*A run declares what it is for, before it runs.* `expectation.json` is written
before the machine boots. This is the structural repair for harness defect 3 —
the run that booted, logged in, photographed a desktop and shut down without
running the journey it was asked for, and passed because nothing in its record
said a journey had been requested. Graded as the photograph-only run it is,
`g10` passes; declared as a run that would drive a session, **the same bytes
fail**.

*A finding names its subject* — `product`, `harness` or `machine`. Phase 4
spent an hour treating a stale fixture file as a Trust failure.

**§6, asserted rather than promised.** Grading the committed evidence in place
leaves it byte-identical; five gradings of one run produce one verdict; the
source is parsed with `ast` to refuse `subprocess`, sockets, writes and a
clock. The same rule the collector is held to — it reads the machine disk
through a throwaway overlay.

**Two gaps found by the tests' own coverage check before either shipped:** a
rule with no docstring, and RJ04 and RJ06 — the two rules that fail the false
pass — firing on recorded evidence and on no hand-written case at all.

`vm-login-story.sh` is now a collector that calls the library rather than a
heredoc that reimplements it, so the checks that run are the checks the
fixtures exercise.

`qualification/` is not a `COPY` root, so none of this reaches the image and no
artifact digest moves. The grader work is a **re-analysis of existing
evidence** in §24's sense and needed no rebuild.

---

## 4. Test isolation findings

Full record: `qualification/phase5/isolation/TEST_ISOLATION_INVESTIGATION.md`.

### The rate, measured

| Condition | Runs | Failures | Rate |
| --- | ---: | ---: | --- |
| The target **class** alone | 20 | 0 | 0/20 |
| The target **module** alone | 40 | 0 | 0/40 |
| The target class after each earlier neighbour, separately | 60 | 0 | 0/60 |
| The whole `tests/companion` package | 28 | 2 | **≈2/28** |

All twelve modules that discovery runs before the target were swept, five times
each. The module row closes a gap in my own first design: stages A and C both
ran the *class*, so neither could have seen what `IncidentalRendererFaultTests`
leaves behind.

Phase 4 recorded "5/5 alone and 1-in-3 in-package". The alone result reproduces
on a larger sample; **the 1-in-3 figure does not and should not be quoted as
measured**.

### The cause: the host's own memory pressure

`CharacterPresenter` builds `base_signals` from `assess_current_machine()` —
the **real host** — and every field the slice's `_VISUAL` override did not name
survived into every evaluation. `_VISUAL` pinned the display, graphics
readiness, available memory and GPU. It did not pin `memory_pressure`, which
`signals_from_assessment` reads as Linux PSI:

    pressure = inventory.memory.pressure_some_avg10.get(None)
    memory_pressure = isinstance(pressure, (int, float)) and pressure >= 0.1

`/proc/pressure/memory`, `some avg10` — a **ten-second rolling average of
memory stall**. A suite that has just run several thousand tests in one process
crosses 0.1, intermittently, for reasons that have nothing to do with this
slice. `adaptation.py` then does what it should: `degrade(STATIC_IMAGE,
"memory-pressure", "memory pressure disabled animation")`.

**Proved by setting that one field and changing nothing else:**

| Host | passed | step 17 | fault | healthy |
| --- | --- | --- | --- | --- |
| no memory pressure | True | `animated-2d` | None | True |
| memory pressure | **False** | **`static-image`** | **None** | **True** |

The failing row's `failures` list is byte-identical to every observed failure,
and step 17's recorded reason reads *"memory pressure disabled animation"*.

**`fault=None` and `healthy=True` are the tells**, and they are exactly what
the instance caught on attempt 16 of a package hunt recorded. Every earlier
explanation — a transient renderer fault, host contention, cross-test
interference — predicts a fault. There wasn't one. It also explains the rates,
which no neighbour hypothesis could: **it is the package that makes the host
stall, and no test in it is the cause.**

### What is proved, and what is inferred

Kept apart deliberately, because this project's own history is of a hypothesis
that survived one run and was written up as confirmed.

**Proved.** Setting `memory_pressure` and changing nothing else produces the
observed failure exactly — the same two steps, the same three passes, and both
distinguishing tells (`fault=None`, `healthy=True`). That makes it a
*sufficient* cause, demonstrated on demand.

**Inferred.** That this is what fired in the wild. The signature match is
strong — no other explanation predicts a capped rung with no fault and a
healthy presenter — but "sufficient" is not "necessary", and a cause that
cannot actually occur on this host would not be the cause. Sampling
`/proc/pressure/memory` after a package run reads `avg10 = 0.00`, which is
weak evidence on its own: `avg10` is a ten-second rolling average, the slice
runs partway through the package, and the average has decayed by the time most
runs end. `total` does rise during a run — 6.2 ms of accumulated stall on one
measured run — so stall is occurring; whether it crosses 0.1 at the moment
`assess_current_machine()` is called is being sampled at 200 ms intervals
across whole runs.

**Since measured, and it settles it.** Sampling `/proc/pressure/memory` after
each of eight consecutive `tests/companion` runs on the reference target:
seven read `avg10 = 0.00`, and the eighth read **`avg10 = 0.71`** — seven times
the 0.1 threshold. So the threshold is not merely reachable in principle; this
host crosses it, during exactly the workload that produced the failure, and
crosses it *hard*.

That run recorded **zero slice failures**, because the pin is in place. Before
the pin it is the run that would have failed.

The one thing still not directly observed is a PSI reading taken at the instant
a *failing* run called `assess_current_machine()` — and it cannot be, because
the fix makes that failure impossible. What is now measured is that the cause
occurs, that it occurs under this workload, and that the slice no longer
responds to it.

**Why the fix does not depend on settling that.** `_VISUAL` pins all five
host-derived signals the ladder can degrade or cap on, not just
`memory_pressure`. If the trigger were `thermal_pressure` or a critical
battery reading instead, the same fix covers it, and the structural guard
requires any *future* signal to be pinned or declared. The defect being
repaired is the class — the slice reading the host at all — rather than the one
field.

### The fix, and why it is a strengthening

`_VISUAL` now pins every host-derived signal the ladder can degrade or cap on.
Pinned in the *slice*, not the presenter — the presenter reading the real
machine is correct, because on a real machine under real pressure the companion
*should* stop animating.

**The second-order problem was worse than the failure.** Step 18 *declares*
`memory_pressure: True` to prove the selector degrades. On a machine already
under ambient pressure the rung was static before step 18 asked, so step 18 was
passing without testing anything.

The guard is structural: `test_slice_host_invariance.py` parses `adaptation.py`
with `ast`, collects every `signals.<field>` the ladder consults, and requires
each to be pinned or declared exempt with a reason — so the next signal added
there cannot reopen this the way this one stayed open for four phases. It found
a fourteenth on its first run (`package_supports_3d`), which was checked rather
than waved through.

Negative controls: removing the pin fails 6 of 10; step 18 must still degrade
on declared pressure and step 19 must still reach `text-only`, so a fix that
disabled the assertion fails too; and step 17 must reach `animated-2d` **with
no pressure reason**, so pinning to an arbitrary value would not satisfy it.

### A third coverage finding: the gate was linting files that are not in the repository

`shell_scripts()` walked the filesystem with `rglob("*.sh")`, so the shellcheck
gate checked every `.sh` *present* rather than every `.sh` **committed** — on a
working machine that is dozens of untracked operational scripts, and this
repository's own `.gitignore` carries `.ops-*` for exactly them. Three of them
failed it on `SC2012`.

The effect: **the gate passed in CI and on a fresh clone, and failed on the
machine where the work happens.** That is the wrong way round.

Repaired the same way, with the same sentence, as the evidence-preservation
check before it: *added means committed, so the question is asked of git.* 92
tracked scripts instead of several hundred filesystem files; 93 seconds down to
9. No git, no skip — it falls back to the filesystem, because a gate that
silently checks nothing is worse than one that checks too much. Negative
control run.

This is also why the certification below is unaffected: those runs are from a
fresh `git clone`, which has no `.ops-*` files in it.

### Certification — §8, and it is clean

§8 requires repeated runs, not one: *"Do not declare the suite reliable after
one passing run."*

On the reference target, as `bunny`, from an ext4 clone, at `30f11a6d`:

| | Runs | Failures |
| --- | ---: | ---: |
| `tests/companion` | 8 | **0** |
| Full reference suite (5979 tests) | 5 | **0** |
| Installer sub-suite (178 tests) | 5 | **0** |

**0 unexplained failures, 0 unexplained errors.**

The eighth companion run is the one worth naming: it recorded
`psi_avg10 = 0.71`, seven times the threshold that used to degrade the rung,
and **zero slice failures**. Before the pin it is the run that would have
failed. The certification did not merely avoid the conditions that cause the
defect — it hit them, hard, and passed.

Evidence: `qualification/phase5/isolation/certification/verify.log`, produced
by `verify.sh` beside it.

**The reference-suite gate moves INTERMITTENT → CLEAN.** It is the only
required gate Phase 5 could close by itself, and the only one it closed.

### A separate finding: 153 tests were not being run

Found by running a directory the suite does not run.

`tests/boot` (39 tests) and `tests/operations` (114) had no `__init__.py`, so
`unittest discover` skipped both — silently, which is the difficulty. Every
"the reference suite is green" statement this project has made quietly excluded
them.

**`tests/boot` had no runner at all.** `LIVE_BOOT_ROOT_CAUSE.md` cites it, and
so does a comment inside `systemd/bunny-update-agent@.service`, as the check
that guards a unit's `RuntimeDirectory`/`ReadWritePaths` pairing — the exact
defect that produced 226/NAMESPACE. It had never executed in the suite.

Both pass, which is the only reason this is a coverage finding and not a defect
ledger. 5803 → 5956 discovered at the time; 5979 now, with Phase 5's own tests.

The project had already named this failure mode for hyphenated directories and
repaired it by renaming them — the symptom. `tests/test_suite_coverage.py`
repairs the property: a directory of tests that nothing runs fails, whatever
the reason, and `tests/installer` is the one declared exception with its runner
named. Negative control run.

**That check's own first attempt was wrong**, and the file says so. It
attributed tests by id prefix and reported `tests/fedora_host` and
`tests/grader` as uncovered — both legitimately use `load_tests`, so their ids
name the defining module. It now measures what the loader returns. A check that
fails a legitimate pattern gets deleted rather than fixed.

---

## 5. Performance investigation

**Phase 4's leading hypothesis is refuted as stated.** The reads are not where
the CPU goes.

Instrument: `qualification/phase5/performance/poller-bench.js`, run under bare
`gjs`, importing the **real** mount parser (`lib/services/storage.js` has no
imports, so it runs unmodified). 2000 iterations, one warm pass discarded.

| Reader | µs/call | Share |
| --- | ---: | ---: |
| storage (`/proc/self/mountinfo` + statfs) | **76.6** | 65.6 % |
| cpu (`/proc/stat`) | 18.9 | 16.2 % |
| memory (`/proc/meminfo`) | 16.9 | 14.5 % |
| temperature (`/sys`, path cached) | 4.4 | 3.8 % |
| **total per 2 s tick** | **116.9** | |

**0.0058 % of one core** (a second run gave 0.0063 %). The regression is
**1.27 percentage points**. The reads are smaller by a factor of roughly two
hundred.

Even summing every 2 s poller and adding the 3 s dock and 5 s top bar, the
reads cannot account for more than hundredths of a point. **Whatever moved idle
CPU by 1.27 points, it is not the reading.**

Storage dominates *within* that total — `/proc/self/mountinfo` re-read and
fully re-parsed every two seconds to answer a question whose answer changes on
the timescale of minutes. Worth fixing on its own terms, and **it will not move
the number Phase 4 recorded.** Said in advance so a later improvement is not
credited with a change it did not cause.

### What survives, and what is now in place to measure it

The redraw. `SystemOverview.refresh()` ends in `queue_repaint()` on every tick
regardless of whether the value changed, and the qualification guest has no
GPU: Mutter composites through **llvmpipe**, in software, on the CPU. A Cairo
arc costs there what it does not cost on a machine with a GPU — and in a way a
benchmark that draws nothing cannot see.

So `interval()` now accumulates, per named poller: ticks, wall time, slowest
tick, errors, and **how often the data actually changed**. Eleven timers named,
including both bounded health polls — which are *startup* cost, not idle cost,
and Phase 4's three-timer table did not distinguish them.

Three deliberate refusals in the instrument:

* **CPU is not claimed per tick.** `/proc/self/stat` has 10 ms resolution, so
  nearly every 117 µs tick reads zero, and reading it costs 19 µs — a 16 %
  instrument overhead on the thing being measured. The report gives wall time
  and a share; the probe attributes process CPU across it and says so.
* **A tick that throws is still counted.** A poller whose cost appears only
  when it succeeds hides the expensive failure.
* **`undefined` means "not reported", not "did not change".** A change count of
  zero is exactly the evidence that would justify lengthening a cadence, and a
  poller never asked must not be recorded as having answered no.

The poller inventory itself was corrected: Phase 4's report named three timers;
there are **eleven**, three of them at 2 s.

---

## 6. Performance results

**None on a running shell.** The measurement needs a build, and the build is
blocked (§13). No cadence was changed, no redraw skipped, and no improvement is
claimed.

---

## 7. Companion results

**Not measured this phase.** §11 asks for startup, memory, CPU, idle and
transition figures across pre-rendered, 2D and 3D. Those are guest
measurements and share the build blocker.

The architectural constraints are unchanged and untouched: pre-rendered remains
the default and the cheapest CPU path, the 3D character was not removed, and no
code path was added that rewrites a user's mode preference.

---

## 8. UX fixes

### A. The greeter — documented as an Alpha limitation

`qualification/phase5/ux/GREETER_DISPOSITION.md`. §12A's second branch, taken
deliberately: branding means touching GDM's own session, which is the surface
the Phase 3 P0 lived on, and login is one of nine currently-passing gates that
cost a P0 to earn. The directive's own warning applies — *do not change it
merely for cosmetic reasons if that risks the login/session architecture*.

What "yes" would require is estimated on the record, including the step most
likely to fail silently (the `gdm` user must be able to read the logo) and the
negative control that would be needed, because a branded greeter and one that
silently fell back to stock are the same screenshot to an automated grader.

### B. The desktop background — root cause corrected, and fixed

**Phase 4's recorded diagnosis was wrong.** `KNOWN_LIMITATIONS.md` says *"the
image has no SVG pixbuf loader"*. It has one: `librsvg2-2.62.3-1.fc44` and
`glycin-loaders-2.1.5-1.fc44` are both installed in the artifact
(`p4-build.log` lines 359, 369–371). **Acting on that diagnosis would have
meant adding a package that already ships.**

The loader was never reached. An image loader handed a stream has no filename
and sniffs the leading bytes; shared-mime-info matches `image/svg+xml` on a
literal `<svg` within the first **256** bytes, and `application/xml` on the
`<?xml` at offset 0 whatever follows. 1.2 KB of provenance comment put `<svg`
at byte **1361**.

Measured on the reference target with `Gio.content_type_guess`, content only:

    bunny-nocturne.svg   application/xml     <svg at 1361
    bunny-arc-dark.svg   image/svg+xml       <svg at 0

The two that work have the root element at byte 0; the one that failed did not.
The error string names the wrong answer the sniff gave.

Fixed by moving the prose inside the element. `<svg` is now at byte 139.

**Swept rather than patched, and the sweep found a second one.**
`shell/assets/companion/default-bunny.svg`, `<svg` at byte 528, identical
latent defect, nothing failing because of it — that asset is loaded by path, so
a name was always available. Fixed anyway. All nine shipped SVGs now sniff as
`image/svg+xml` from content alone, measured.

**Regression test**: `tests/shell/test_svg_assets_are_sniffable.py`. The offset
rule needs nothing but the file, so it does not skip on the Windows host where
most edits are made; a stricter rule allows only the declaration and two SPDX
lines above the root; well-formedness is checked because the first attempt at
this very fix put `--` inside an XML comment and no parser would read it — and
the offset check passed it. Where GIO exists, the sniff itself runs, plus a
negative control that must still fail.

**Not qualified on a desktop.** The fix is in source and needs a build to be
seen loading.

---

## 9. Physical hardware results

**NOT RUN.** No physical machine has ever booted Bunny OS. Every result in this
project is QEMU with software rendering.

`qualification/phase5/hardware/HARDWARE_TRACK.md` binds the track to the
candidate's ISO digest — the earlier plan named no artifact because there was
no qualified one — and adds the boot chain, voice-on-hardware and GPU matrix
that the plan predates, with the failure modes named in advance so a run can be
graded rather than narrated.

---

## 10. Voice hardware results

**NOT RUN.** Voice is a PASS in the VM on real audio through a synthetic
source; that establishes nothing about a microphone. Eight checks are specified
in the hardware track, with the note that latency is *compared*, not equated —
and that a hardware figure faster than the VM's would mean the VM number was
measuring the harness.

---

## 11. GPU results

**NOT RUN.** Every 3D measurement this project has is on llvmpipe. Nobody has
seen the 3D renderer on a GPU, and nobody has seen it refuse one.

The matrix is specified. Its most failure-prone row is the retained preference:
a fallback that writes `renderMode: prerendered` into settings has destroyed
the information needed to recover, so the check is on the settings file after
the fallback, not on the screen.

---

## 12. Security disposition

`qualification/phase5/security/SECURITY_DISPOSITION.md`,
`SCAN_ROUTE_DISCREPANCY.md`, `candidate-disposition-matrix.json`, and the raw
scans under `scan/` and `route/`.

**The candidate was scanned three ways and the answers differ by seven Critical
findings.** Resolving that is the substance of this section.

### The first answer was wrong, and wrong in the flattering direction

The first re-scan mounted the image's overlay and scanned it: **56 distinct
advisories, 1 Critical**, against Phase 4's 8. That was recorded here as *a
discrepancy to resolve, not a correction* — three things differed at once and
none had been held still.

Resolved: **nothing about the product improved.**

| scan | route | database | distinct | Critical |
| --- | --- | --- | ---: | ---: |
| Phase 4 | `oci-archive:` | July | 114 | **8** |
| Phase 5 | `oci-archive:` — the gate's own route | 2026-08-17 | 56 | **1** |
| Phase 5 | `dir:` over the mounted overlay | 2026-08-17 | 56 | **1** |
| Phase 5 | `sbom:` over the candidate's own SPDX | 2026-08-17 | 80 | **8** |

The two routes that read the binaries agree **advisory for advisory**, so the
route was never the variable — an intermediate version of this section said it
was, on the strength of the one scan not yet run. What differs is what the
scanner could read, and what the database gave it to read with.

### The mechanism, named

1. `golang.org/x/crypto v0.46.0` is **still in the candidate**, in
   `/usr/bin/skopeo` — from the candidate's own SBOM, which lists what was
   catalogued whether or not anything matched it.
2. The seven advisories are **still Critical in the database, still ranged
   `<0.52.0`**.
3. The **matcher is fine**: those package records, lifted verbatim into a
   minimal SPDX document, produce all seven.
4. The current database carries a **`qualifiers.go_imports`** list on each —
   for `GHSA-5cgq-3rg8-m6cv`, `golang.org/x/crypto/ssh/knownhosts` →
   `hostKeyDB.IsRevoked`. All seven name symbols in the SSH stack.
5. Neither `/usr/bin/skopeo` nor `/usr/bin/podman` **contains those packages**.
   Both link `x/crypto` for its ciphers — cast5, chacha20, cryptobyte, argon2,
   blake2b — and none of `ssh`, `ssh/agent`, `ssh/knownhosts`.
6. So given a binary, grype applies the qualifier and excludes them. Given an
   SBOM with no symbol capture it cannot, warns on stderr that module
   granularity *"may report false positives"*, and reports all seven.

Isolated to one file — same scanner, same database, same minute:

| | distinct | Critical |
| --- | ---: | ---: |
| `grype file:/usr/bin/skopeo` | 12 | **0** |
| `grype sbom:` of a syft catalogue of that same file | 37 | **7** |

The exclusions are not indiscriminate: the one Critical still reported,
`GHSA-p77j-4mvh-x3m3` against `google.golang.org/grpc`, names `Server.Serve`,
`Server.ServeHTTP` and `Server.handleStream` — and podman runs a gRPC server.

**Phase 4's 8 and the function-level 1 are both correct answers to different
questions.** The July database had no symbol qualifiers, so every route
reported at module granularity. Nothing about the image changed.

### The position, correctly stated

At module granularity — the granularity Phase 4's number is in, and the
conservative one — the candidate carries **80 distinct fixable advisories: 8
Critical, 36 High, 29 Medium, 6 Low, 1 Unknown.**

Like for like, Go modules only, nineteen days apart:

| | distinct | Critical | High | Medium |
| --- | ---: | ---: | ---: | ---: |
| Phase 4 (beta, `oci-archive`) | 40 | 8 | 17 | 14 |
| Phase 5 (candidate, SBOM) | 45 | 8 | 18 | 17 |

Five new advisories in nineteen days; **Criticals unchanged at 8**.

### The July feed had no Fedora 44 data

Phase 4's retained scan is 74 `linux-kernel` and 40 `go-module` findings and
**zero rpm**. The identical `oci-archive:` route against the current database
returns **26 distinct rpm advisories**, plus 7 python, and the kernel's 74
generic findings are now largely expressed as RPM advisories against `kernel`,
`kernel-core` and `kernel-modules`.

The route could always read `/usr/share/rpm/rpmdb.sqlite` — a 61 MB file that
is really in the image. There was nothing in the feed to match it against.
Phase 4's *"59 fixable findings, all inherited from the base image"* was an
accurate reading of the data available; it was never a full picture of the
image, and it has not been one at any point since.

### Raw match counts measure the deployment layout

`/usr/bin/podman` and `/sysroot/ostree/repo/objects/8c/c9b024….file` are inode
95288 with a link count of 2 — the same file. A filesystem scan catalogues
every Go binary twice: **44 of the 183 `dir:` matches arrived through an ostree
object path**. Every figure here is distinct advisories.

### What this changes, and what it does not

**It does not change the gate.** Eight Critical findings, all blocking, all
`PENDING_REVIEW`. `release/vulnerability.py` permits a Critical to become
non-blocking only through a completed independent review reference; a
scanner's symbol analysis is a measurement, not a review. Nothing here is a
waiver or a downgrade. The disposition matrix is built from the module-level
result for exactly that reason.

**It changes the question for the reviewer.** §18's review would have been
handed 24 bundles asserting `installed-not-executed` on the strength of an
argument. It can now be handed a checkable claim: *these seven advisories are
scoped by their own upstream data to functions in `golang.org/x/crypto/ssh`,
`.../ssh/agent` and `.../ssh/knownhosts`; the two binaries that carry the
module contain none of those packages; confirm or refute.* That is the
strongest material this project has had for the disposition Phase 4 wanted and
could not justify.

**It leaves a gate defect.** Two runs of the same gate, same image, same
scanner, differ by seven Critical findings depending on what the database
carries and whether symbols were readable — and neither `grype.json` nor
`vulnerability-report.md` records either fact. A result that does not say how
it was measured is not interpretable. Recorded as a recommendation in
`../gates/RELEASE_GATES.md`; `build/scripts/security-scan.sh` is unchanged.

### What the scan still settles

The `dir:`-route scan of a **different** build (`376acf0e076f`, different image
ID, different commit) returns **identical counts**. Two independently built
images with the same vulnerability surface is what "every finding comes from
the base image" predicts, here demonstrated rather than asserted. **Nothing
Bunny builds adds to this surface.** The conclusion survives everything above:
it compares one route against itself.

### Every row is `PENDING_REVIEW`, and that is correct

* `release/cve.py` and `release/vulnerability.py` **reject at parse time** any
  non-blocking disposition of a Critical finding without a completed
  independent review. There is none, so `ACCEPT` and `NOT_APPLICABLE` are not
  statuses a person could write. The generator has no code path producing them
  either.
* `FIX` is unavailable for a different reason: the fixed versions exist and the
  packages are in the base image, not `build/packages/`. **That is a statement
  about which party can act, not the "inherited, therefore not ours" move §17
  forbids.**

The **Bunny impact** column reads *not determined*, deliberately: the measured
reachability evidence covers the July advisory set, and carrying it across
would give an advisory that did not exist when that evidence was gathered a
reachability answer nobody measured for it.

The **owner** column reads "unassigned — the project has one principal and the
review must be independent of them", because intake rejects any reviewer whose
name matches a project principal.

---

## 13. Signing status

`qualification/phase5/signing/SIGNING_CONFORMANCE.md`.

Five of §19's six requirements were already specified in detail. The sixth —
a second signer — is not an engineering task; the ceremony's first entry
condition is *two people*, and there is one.

**No production key was created, and creating one would have been wrong.** No
private key material was handled and no secret appears in Phase 5 evidence.

What Phase 5 adds is a check that the refusals refuse. All five register keys
pushed through the admission path: **5 refused for production, 0 accepted.**
Three negative controls each fire on their own condition — a production id in a
development directory, a two-person role without approval, and a real dev key.

**The fourth control was accepted, correctly, and it is the useful one.** A
record declaring a hardware token and two-person approval satisfies every
check, because the checks read a JSON file. **The register asserts custody; it
does not prove it.** Harmless while it holds only development keys and both the
declaration and the reality are checkable. It becomes the whole of the control
the moment a production key exists, so it is written down now, with what the
ceremony should publish alongside the entry.

---

## 14. Update status

**NOT_RUN as a delivered capability — and the reason is no longer the harness,
the missing manifest, or the missing N+1.** All three of those were recorded
blockers; all three are now gone or shown not to be the obstacle. What is left
is what the image itself ships.

### What the image ships

Both the Phase 4 candidate and the Phase 5 build carry:

```
/etc/bunny-os/update.json
  { "enabled": false,
    "channel": "developer",
    "manifestUrl": "https://updates.invalid.bunny-os.example/developer/x86_64/manifest.json",
    "imageRepositories": ["quay.io/comradeart/bunny-os"] }

/usr/share/bunny-os/update-keys/
  revoked-keys.json          {"schemaVersion": 1, "revokedKeyIds": []}
```

**There is no trusted signing key in the image.** Only the revocation list is
installed, and `build/scripts/install_routes.py` has exactly one route into
that directory — `revoked-update-keys` — so this is by construction, not by
accident.

Running the shipped agent, in a container made from the image, at the paths it
expects:

| action | result |
| --- | --- |
| `status` | `{"configured": true, "state": "idle"}` |
| `check` | `{"error": {"code": "not_configured", "message": "OS update checks are disabled"}}` |
| `stage` | `{"error": {"code": "not_configured", "message": "OS update checks are disabled"}}` |

So the update path refuses at the first gate. Had it not, `_verify_signature`
would refuse every manifest at the second: `KEY_DIR / f"{key_id}.pem"` cannot
exist for any key id.

**This is fail-closed and it is right.** §13 and §19 say there is no production
signing key and that creating one would be wrong; an image that shipped a
trusted key with no ceremony behind it would be worse than one that updates
nothing. But it means the honest status of the update gate is not "blocked on
infrastructure" — it is **the Alpha does not update, by design, and the refusal
is verified**.

### Two defects behind the recorded blocker

Neither would have been found without pushing past "the input is missing".

1. **`vm-upgrade-test.sh` manifest mode could never have passed.** It searches
   the agent for `validate_manifest`, `_validate_manifest` or
   `verify_manifest` and calls `validator(document)`. The only one that exists
   is `_validate_manifest(manifest, config, enforce_new_sequence)` — three
   parameters. A supplied manifest would have produced a `TypeError`, not a
   verdict. The agent also reads `/etc/bunny-os/update.json`,
   `/usr/share/bunny-os/update-keys/` and `/var/lib/bunny-os/update` as
   absolute paths, so the mode cannot run on a builder at all.
2. **`status` reports `"configured": true` on an image where updates are
   disabled.** The field is `CONFIG_PATH.exists()` — it means *the file is
   there*, and it reads as *this machine is set up to update*. Alongside
   `check`'s "OS update checks are disabled", the two answers contradict each
   other. Recorded, not fixed: the built artifact would no longer match its
   commit.

### What did run

`vm-upgrade-test.sh staged` needs a disk with an update already staged. §15
records how one was made and what came of it, because the same disk answers
both questions.

Scenarios needing a reachable registry (`interrupted-download`,
`expired-metadata`) remain NOT_RUN, and no manifest scenario can be run against
this image while the trust store is empty.

---

## 15. Rollback status

**Boot parity: PASS.** For the first time the project has two images, so the
question can be asked at all.

| | disk | sha256 |
| --- | --- | --- |
| N | Phase 4 candidate `e906a48793d7` | `497add9a77db2db02bf2541e85b04b0e285c1833d2c8220d193d0d413a6ce867` |
| N+1 | Phase 5 build `e501218f2fe0` | `b4dd95f3cb3f7d4b4419c120e04e4375f4a176f0fd0a0ee5f2c91ba5de99dcef` |

N's digest is the one `BUNNY-MANIFEST.json` recorded in Phase 4, so the
archived artifact is the artifact — verified, not assumed.

`vm-rollback-test.sh` in `boot-parity` mode boots each and requires a healthy
target. The harness is explicit in its own output that this is **prerequisite
evidence and not a live deployment switch**, and nothing here upgrades that
claim: rolling back to an image that does not boot is not a rollback, so this
is the thing that has to be true first.

### The live switch, and a harness that was passing without one

`qualification/phase5/update/stage-update.sh` boots N with the Phase 5 OCI
directory on a second drive and lets the **shipped `bootc`** stage it. Nothing
is simulated. The disk went from one deployment to two, and
`vm-upgrade-test.sh staged` then **PASSED** — the new deployment boots and a
rollback target is retained, attributed independently by the per-deployment
`os-release` commit.

`vm-rollback-test.sh deployment-rollback` also reported PASS. **It was wrong.**

> Rollback PASSED: the previous deployment was selected and reached a healthy
> target.

Three consecutive runs said that, and every one of those boots came up on the
**default** deployment: identical `os-release commit=e501218f2fe0…`, identical
`ostree=` argument on the kernel command line, `bootc` reporting the rollback
target sitting there untouched.

**Cause.** The selection wrote a 40-byte file where GRUB requires a fixed
1024-byte environment block padded with `#`. GRUB ignored it. **Why it passed
anyway:** the only check was *did the machine reach a healthy target*, and a
machine that never rolled back reaches one perfectly well. That is §5 of this
brief word for word.

**Repair, in two halves**, because fixing only the first would leave a harness
that still could not tell:

1. the block is written in the format GRUB requires;
2. the deployment that booted is **identified**, from the `ostree=` argument the
   kernel prints to the serial console — `bunny_deployment_checksums` reads the
   candidates from the BLS entries, `bunny_require_booted_deployment` asserts
   which came up. The comparison is on the 64-character checksum, because bootc
   rewrites the `boot.N` component when the order changes and comparing whole
   strings would report a correct rollback as a failure.

Run against the same disk, the repaired harness catches it and classifies it
honestly: **exit 5, NOT_RUN**, `previousDeploymentBoots: false`, with the note
that this is a gap in the harness rather than a product failure. Reporting a
harness limitation as a product FAIL would be the mirror image of the mistake
being fixed.

### The product does roll back

`rollback-real.sh` uses the route a device uses — `bootc rollback`, then reboot.

| boot | `os-release` commit | kernel `ostree=` | `bootc booted=` |
| --- | --- | --- | --- |
| 1 | `e501218f2fe0…` (N+1) | `boot.0/…2d358243…` | `…candidate:e501218f2fe0` |
| 2 | **`e906a48793d7…` (N)** | `boot.1/…dd339603…` | `localhost/bunny-os-beta:e906a48793d7` |

Three independent readings agree and the booted/rollback roles have swapped.
**PASS.**

### §20's actual criterion: user state

> *A rollback that boots but loses user state is not automatically a PASS.*

Five files were written **before** the switch — user data, settings, companion
mode, voice settings, Trust grants — and read back on every subsequent boot by a
unit reporting to the serial console.

| boot | deployment | all five present |
| --- | --- | ---: |
| staged deployment | N+1 | yes |
| rollback default | N+1 | yes |
| after `bootc rollback` | **N** | **yes** |

Nothing was lost, and the mechanism is structural rather than lucky: `/var`
belongs to the stateroot, which every deployment shares.

**One honest caveat.** The staging unit stayed enabled and ran again on the
first boot of the rollback run, rewriting the five files, so the copies read
after the rollback are timestamped `03:32` rather than the original `03:15`.
The pre-switch write is observed surviving the *switch*; the post-rollback
reading is of state written on N+1 surviving the rollback to N. Both halves are
measured, on two different writes. A unit that performs a one-shot action should
disable itself when it is done — `rollback.sh` does, `stage.sh` should.

### Where the two gates stand

| | |
| --- | --- |
| Boot parity, N and N+1 | **PASS** |
| Staged update exists (`bootc switch --transport oci`) | **PASS** |
| `vm-upgrade-test.sh` staged | **PASS** |
| `vm-rollback-test.sh` deployment-rollback | **NOT_RUN** — repaired to say so |
| Rollback by `bootc rollback` | **PASS** — attributed three ways |
| User state across the rollback | **PASS** — five of five |
| Manifest verification | **NOT_RUN** — no trust root in the image, by design |
| `interrupted-download`, `expired-metadata` | **NOT_RUN** — need a registry |

Neither gate closes. The update gate cannot while the image ships no trust
root, and that is the correct posture until a production key exists. What
changed is that both now fail for measured reasons rather than inherited ones,
and one harness has stopped reporting a PASS it had not earned.

Full record: `qualification/phase5/update/UPDATE_AND_ROLLBACK.md`.

One more thing the run found: **`bootc switch --transport oci-archive` is
advertised in `--help` and not implemented** — the guest answered `unsupported
transport "oci-archive" for looking up local images`. `--transport oci` against
a directory works, which is what the staging harness uses.

---

## 16. Alpha feedback

**Testers: 0. Records: 0.** `qualification/phase5/feedback/ALPHA_FEEDBACK_PLAN.md`.

The importer, redaction, dedup and ledger have existed since 2026-07-29 and
needed no rebuilding. What was missing is that **the instrument could not name
the product**.

The component taxonomy predates the Companion runtime, the voice runtime, the
Trust prompt and App Capsules — the three subsystems §21 asks testers about by
name. A tester reporting *"Bunny did not hear me"* had to choose between
`Audio`, which is the sound stack, and `Bunny Core`, which is everything.

**A feedback instrument that cannot name the thing being reported does not
return "unknown"; it returns a misclassification that looks like data**, and
the counts get quoted. Four components added in both declarations, bound by a
test that also checks order because the importer's diagnostics quote positions.

`not_reproduced` and `unknown` are asserted to stay distinguishable. One means
somebody tried and failed; the other means nobody tried, and a ledger that
merges them can report "we could not reproduce it" about a report nobody
opened.

**An empty ledger is not evidence of quality**, and no feedback finding appears
anywhere in this report because there is none.

---

## 17. Release-gate matrix

Full tracker with both columns: `qualification/phase5/gates/RELEASE_GATES.md`.

The journey column and the matrix column are kept apart because they answer
different questions. Installation is **PASS** as a journey — an encrypted
install from the candidate's own ISO, `findings: []` — and **NOT_RUN** as a
matrix, 5 of 12 scenarios with evidence. Both are true, and merging them
produces a number true of neither.

| Gate | Current | Required |
| --- | --- | --- |
| Installation | PASS (journey) / NOT_RUN (matrix) | PASS |
| Encryption | PASS (journey) / NOT_RUN (matrix) | PASS |
| First boot | PASS | PASS |
| Login | PASS | PASS |
| Voice | PASS | PASS |
| Trust | PASS — re-graded under the extracted grader | PASS |
| Persistence | PASS (journey) / NOT_RUN (matrix) | PASS |
| Companion | PASS | PASS |
| Shutdown | PASS | PASS |
| **Reference suite** | **CLEAN** — 5/5 full runs, 0 failures; root cause fixed | **CLEAN** ✓ |
| Security review | NOT DONE | REQUIRED |
| Physical hardware | NOT RUN | REQUIRED |
| Production signing | NOT DONE | REQUIRED |
| Update | NOT_RUN — the image ships no update trust root, by design | REQUIRED |
| Rollback | PASS by `bootc rollback`, state intact / NOT_RUN by the harness | REQUIRED |
| Owner approvals | NOT DONE | REQUIRED |

`scripts/release.py gate --kind qualification-candidate` → **BLOCKED**, verbatim
in the tracker. No "required" was changed.

Three rows deserve a second reading. The accessibility matrix carries two
**FAIL**s, the only outright failures anywhere in the matrices. "Second
production signer" is `BLOCKED` rather than `NOT_RUN` — it waits on a person,
not on work. And **rollback carries two verdicts on purpose**: the product
rolls back and keeps user state, measured three ways; the harness that was
supposed to prove it was passing without rolling back at all, and now reports
NOT_RUN. Collapsing those into one row would hide whichever half the reader
most needs.

---

## 18. Remaining blockers

### Engineering, and immediately actionable

1. **Qualify the Phase 5 build.** It exists and boots; none of the journey
   evidence the Phase 4 candidate carries has been re-run against it. That is
   the gap between "a build" and "a candidate".
2. **The review package rebinding.** The re-scan is **done** — see §12. What
   remains is the request itself: it is bound to `80df25b09f65`, intake rejects
   a scope commit other than the candidate's, and its 24 reachability bundles
   are built against the July advisory set rather than the 80 measured now. It
   also predates App Capsules and Trust — the two boundaries a reviewer of
   *this* product would most want to see. And the question it asks is now the
   wrong one: §12 has a specific, checkable claim to put in front of a reviewer
   instead.
3. **Deployment selection in `vm-rollback-test.sh`.** The harness no longer
   passes without rolling back, but it still cannot select a deployment on
   these images. Either teach it the `bootc rollback` route the product
   actually uses, or leave it reporting NOT_RUN and treat
   `qualification/phase5/update/rollback-real.sh` as the rollback harness.
4. **`stage.sh` should disable itself after running.** It re-ran on a later
   boot and rewrote the state markers, which cost the user-state result a clean
   timestamp chain. `rollback.sh` already does this; the pattern should be the
   default for anything one-shot.

### Not engineering

5. **Independent security review** — by definition excludes the people here.
6. **Physical hardware** — a purchase.
7. **Production signing** — a second person. Until there is one, the image ships
   no update trust root, which is why §14 reads NOT_RUN and why that is the
   correct posture rather than a defect.
8. **Owner approvals** — a decision.

**Nothing is blocked on host storage.** That claim stood for a week and was
false; §21 records how it was made and how it was measured away.

---

## 19. Artifact identities

**Phase 5 produced one artifact, with its own identity.** It does not replace,
rename or re-tag the Phase 4 candidate, and Phase 4's output was moved intact
rather than deleted when its output directory had to be cleared.

| | Phase 4 (frozen) | Phase 5 |
| --- | --- | --- |
| Source commit | `e906a48793d74544b39c14cc3e35e0654f5311e2` | `e501218f2fe0105e5fc92bdf94fd6b3c87d6c470` |
| Build id | `e906a48793d7.1786986334` | `e501218f2fe0.1787016937` |
| Image | `localhost/bunny-os-beta:e906a48793d7` | `localhost/bunny-os-beta:e501218f2fe0` |
| Image id | `6f3bbb9af38dae1636ff5c02dc79b07d3b09774bcacddc15308ae8e80bf3c8b2` | `70f677701e1a16efd740f075cb05b14a6a04304e38141576e893b23655543d58` |
| qcow2 | `497add9a77db2db02bf2541e85b04b0e285c1833d2c8220d193d0d413a6ce867` | `b4dd95f3cb3f7d4b4419c120e04e4375f4a176f0fd0a0ee5f2c91ba5de99dcef` |
| raw | `a6ee06dcbc0ed3aa22c9ea07c339882eb97c7f16ce906b654c9a1e1119849d46` | `7fadbec459fe9cd92c461db70b676876bd9774c3875c467bbf2b5724245a77f0` |
| oci.tar | `205a77f1b6cdf33915bce3afceb0914d6af25f97b434cf2128aec04d199b43dd` | `6ea132359756e48e3ff98f941a2c5286537a92210f38581debca4028be556536` |

The Phase 4 tree is at
`/root/bunny-build-archive/beta-phase4-rc-e906a48793d7-20260818T014208Z` on the
builder, and its qcow2 still hashes to the digest its own manifest records —
checked at the top of the rollback run, not assumed.

**The Phase 5 build is not a release candidate and makes no reproducibility
claim.** The build script says so in its own output and `provenance.json`
records `repeatedBuildComparisonPerformed: false`. It exists to answer two
questions Phase 4 could not: whether the two repaired assets are repaired *as
installed*, and what happens when a machine is offered a second image.

§24 is satisfied directly: no Phase 5 result is attached to the Phase 4
artifact except the grader's re-grading of `g7`, `g12` and `g13`, which is
explicitly a **re-analysis of existing evidence**, and the security re-scan,
which is a fresh measurement of that artifact reported under its own identity
and its own date rather than folded into Phase 4's record.

Everything Phase 5 changed after the build — the report, the evidence, the
rollback-harness repair — postdates `e501218f2fe0` and is not in it.

---

## 20. Evidence inventory

`qualification/phase5/` — the Phase 5 record. Nothing in `qualification/phase4/`
was written to; `git status` on it is clean after every grading run and the
grader's own tests assert it byte-for-byte.

| Path | What |
| --- | --- |
| `baseline/BASELINE.md`, `baseline.json` | The Phase 4 baseline, written before any change |
| `gates/RELEASE_GATES.md` | The tracker, both columns, the gate tool's verbatim output, and the one gate change proposed rather than made |
| `isolation/TEST_ISOLATION_INVESTIGATION.md` | Rates, conditions, the controlled injection, what it is not |
| `isolation/certification/verify.log` | The five clean full-suite runs |
| `performance/POLLER_DATA_SOURCE_COST.md` + `poller-bench.js`, `poller-bench-host.txt` | The measurement that refutes the leading hypothesis, and its instrument |
| `security/SECURITY_DISPOSITION.md` | The disposition, the three scans, and the counting |
| `security/SCAN_ROUTE_DISCREPANCY.md` | Why 8 became 1 and is still 8, measured step by step — including this document's own first, wrong answer |
| `security/candidate-disposition-matrix.json` + `build_candidate_matrix.py` | 80 advisories on the **candidate**, all PENDING_REVIEW, regenerable |
| `security/disposition-matrix.json` + `build_disposition_matrix.py` | The July set, 37 rows, kept with its own scope and its measured reachability |
| `security/scan/` | The raw scans: `oci-archive`, mounted filesystem, SBOM, and the two stderr files whose one-line difference is the whole finding |
| `security/route/` | The isolation experiments: the symbol probe, the SBOM control, the advisory qualifiers, the binary probe, the four-route comparison |
| `sbom/retention-manifest.json` | The candidate's SPDX SBOM: 6451 packages, 70 MB, digest-chained on the builder |
| `build/BUILD_IDENTITY.md`, `provenance.json`, `SHA256SUMS`, `normalisation.json` | The Phase 5 artifact, and how Phase 4's was preserved |
| `assets/ASSET_VERIFICATION.md` + `sniff.log`, `sniff-check.py`, `sniff-verify.sh` | The two repaired assets in the built image, with the negative control |
| `update/UPDATE_AND_ROLLBACK.md` + `logs/`, five harness scripts | Boot parity, a real staged update, a real rollback, user state across it, and the harness that was passing without rolling back |
| `signing/SIGNING_CONFORMANCE.md` | Conformance, and the refusals measured |
| `hardware/HARDWARE_TRACK.md` | The track, bound to the candidate |
| `feedback/ALPHA_FEEDBACK_PLAN.md` | The instrument, and the zero |
| `ux/GREETER_DISPOSITION.md` | The §12A decision, with what "yes" would cost |

`qualification/grader/` — the instrument, with fixtures and 40 tests, declared
in `_PHASES_AFTER_THE_RECORD` as a tool rather than a record.

Bulky evidence stays on the builder with a digest chain rather than in the
repository: the 70 MB SBOM, the 2.9 GB staged disk, the archived Phase 4 build
tree. Each is named by digest in the document that relies on it.

---

## 21. Final recommendation

**Do not label anything release-qualified.** The project's own gate says
BLOCKED and its governing sentence stands: *building a candidate for
examination remains permitted; calling one qualified does not.*

**`e906a487` remains a usable Alpha Release Candidate**, with the same warnings
Phase 4 attached and one fewer excuse: the wallpaper defect it shipped is
understood and fixed in source, and the diagnosis it recorded was wrong in a
way that would have wasted the next person's time.

**The next action was recorded for a week as "8.6 GB of disk", and that was
wrong.** Four of this phase's open items — the build, update, rollback, and the
security re-scan — were held behind an environment claim nobody re-measured.
The original failure was `grype podman:` filling **/tmp, which is tmpfs — RAM**,
and the diagnosis then conflated Windows `C:` with the ext4 volume the builder
writes to. Writing 20 GiB inside WSL moves the VHDX by zero bytes. All four
items ran. An inherited claim about the environment is still a claim.

### What this phase is worth being judged on

Phase 4's finding was that its instrument was wrong more often than its product
was. Phase 5's is the same shape and larger: **eleven defects, and ten of them
were in things that measure, describe or decide rather than in things that
run.**

| # | Defect | Subject |
| --- | --- | --- |
| 1 | A grader that could not fail a journey | instrument |
| 2 | 153 tests that nothing executed — one cited in a shipped unit file as the guard on a defect that has actually occurred | instrument |
| 3 | The reference suite reading the host's memory pressure and blaming the product | instrument |
| 4 | A feedback taxonomy that could not name three of the product's four distinguishing subsystems | instrument |
| 5 | The grader's own CLI silently rewriting the collector's `schemaVersion` | instrument |
| 6 | The shellcheck gate linting untracked files, so it was weakest on the machine where the code is written | instrument |
| 7 | **`vm-rollback-test.sh` reporting "the previous deployment was selected" for three runs that never left the default deployment** | instrument |
| 8 | `vm-upgrade-test.sh` manifest mode calling a three-parameter validator with one argument, so it could never have produced a verdict | instrument |
| 9 | The update agent reporting `"configured": true` on a machine where updates are disabled — the field is `CONFIG_PATH.exists()` | instrument |
| 10 | "Blocked on 8.6 GB of disk", inherited for a week, measured false in two minutes | **the record** |
| 11 | The wallpaper, misdiagnosed in `KNOWN_LIMITATIONS.md` as a missing loader | **product** |

**One product defect.** The wallpaper — and even that one's recorded *diagnosis*
was wrong in a way that would have sent the next person to add a package that
already ships.

Number 7 is the one worth dwelling on, because it is §5 of this brief happening
in the present tense. The rollback harness wrote a 40-byte file where GRUB
requires a padded 1024-byte record, so nothing was ever selected; its only check
was whether the machine reached a healthy target; and a machine that has not
rolled back reaches one perfectly well. It printed PASS three times. The repair
is not the grubenv format — that alone would have produced a harness that still
could not tell — it is making the harness **name the deployment that booted**,
from the kernel's own command line. Against the same disk it now says NOT_RUN.

None of the six would have been found by running the suite, because in every
case the suite, or something it depends on, was the thing that was wrong. Three
were found by running an instrument against a case it should fail; two by
running something nothing had run before; one by reading a field the report had
always carried and nothing had ever printed.

**Two were found by my own checks failing on their first run**, which is the
part I would point at. The grader's coverage test found that RJ04 and RJ06 — the
two rules that fail the historical false pass — fired on recorded evidence and
on no hand-written case at all. The suite-coverage check's first version was
itself wrong, accusing two directories that legitimately use `load_tests`; it is
documented as wrong in the file that replaced it, because a check that fails a
legitimate pattern gets deleted rather than fixed.

**Optimise for a release process where a PASS actually means PASS.** Two
numbers I would like a reader to check. `psi_avg10 = 2.02`, on a companion run
at HEAD that passed: the host crossing the threshold that used to break the
slice, twenty times over, which is the difference between a defect avoided and
a defect fixed. And `os-release commit=e906a48793d7…` on the second boot of
`rollback-real.sh` — the line that proves a rollback happened, and whose absence
is what three PASSes had been hiding.

The one that has not moved: **five required gates outstanding, four of them
unreachable from inside this repository.** A clean suite is not a release, and
this phase closed exactly one gate.
