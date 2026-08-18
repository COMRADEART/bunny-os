# Phase 5 — Alpha Feedback, Performance & Release-Gate Closure

## STATUS: **PHASE 5 — RELEASE CANDIDATE BLOCKED**

Not `ALPHA HARDENED`: the reference-suite gate requires CLEAN and the suite is
not clean.
Not `RELEASE GATE READY`: six required gates are outstanding and four cannot be
closed from inside this repository.
Never `STABLE RELEASE`.

**The Phase 4 Alpha Release Candidate `e906a487` is untouched and remains READY
as an Alpha Release Candidate and nothing else.** Phase 5 built no artifact,
changed no digest in `qualification/phase4/`, and did not re-grade the
candidate under a different name.

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

Eleven commits, 52 files, +7414/−146.

| Commit | What |
| --- | --- |
| `eca0efaf` | The VM journey grader extracted to `qualification/grader/`, with fixtures and 31 tests |
| `9a34ee81` | The wallpaper defect: root cause corrected and fixed, swept across all shipped SVGs |
| `f830ca3a` | 153 tests recovered into the reference suite; feedback taxonomy extended |
| `d548d100` | Poller instrumentation; the leading performance hypothesis measured and cleared |
| `49cd25f8`, `8f862ea3` | The slice records *why* the selector degraded — the diagnostic that found the cause |
| `ea3d6bf9` | Security disposition, signing conformance, hardware track, feedback plan, gate tracker |
| **`30f11a6d`** | **The isolation root cause: the host's own memory pressure, and the pin that closes it** |
| `852fbdc3`, `fcba6def`, `e2b7bc6f` | This report, the cause, and what is proved against what is inferred |

**No product behaviour was changed except two asset files.** The poller work
adds measurement and changes no cadence; §10's warning against sacrificing
correctness for a benchmark has more force once the obvious suspect is cleared,
and an optimisation made now would be one made for no measured gain.

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
`candidate-disposition-matrix.json`, and the raw scan under `scan/`.

**The candidate itself was scanned.** The first attempt failed for want of disk
— `grype podman:` expands every layer to a tarball. The second succeeded by
mounting the image's overlay in place (`podman create` + `podman mount`, then
`grype dir:`), which copies nothing: free space measured before, during and
after was unchanged.

### 183 is not 183

The scan reports **183 matches**. That is **56 distinct advisories**, each
counted once per affected package. `FEDORA-2026-c53019ed4f` alone accounts for
15, all from one `rpmdb.sqlite`. Quoting 183 would inflate the figure more than
threefold, and 183 is the first number anyone re-running the scan will see.

| Severity | Distinct advisories |
| --- | ---: |
| **Critical** | **1** |
| High | 31 |
| Medium | 19 |
| Low | 5 |
| **Total** | **56** |

The single Critical is `GHSA-p77j-4mvh-x3m3` in `google.golang.org/grpc
v1.72.2`, fixed upstream in 1.79.3.

### A discrepancy with Phase 4, recorded as one

| | Total | Critical | High |
| --- | ---: | ---: | ---: |
| Phase 4 | 59 | 8 | 28 |
| Measured here | 56 | **1** | 31 |

The totals are close; the Criticals are not. **This is not offered as a
correction of Phase 4.** Three things differ at once — the scanner database,
the cataloguing method (`dir:` against `oci-archive:`), and possibly what
Phase 4 counted — and attributing the difference to one of them with three
variables moving would be a guess. One `oci-archive:` scan settles it, and
that needs disk.

It matters more than a counting question: **Critical is the severity that
cannot be dispositioned without an independent review**, so whether the
candidate carries eight or one changes what that review costs.

### What the scan does settle

The same scan of a **different** build (`376acf0e076f`, different image ID,
different commit) returns **identical counts**. Two independently built images
with the same vulnerability surface is exactly what "every finding comes from
the base image" predicts — here demonstrated rather than asserted. **Nothing
Bunny builds adds to this surface.**

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

The **Bunny impact** column on the candidate matrix reads *not determined*,
deliberately. The measured reachability evidence covers the July advisory set;
carrying it across would give an advisory that did not exist when that evidence
was gathered a reachability answer nobody measured for it. The older matrix
keeps its evidence and its scope; this one says what it does not know.

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

**NOT_RUN**, 1 of 13 scenarios passing (`invalid-signature`).

The recorded blocker is exact: *"`vm-upgrade-test.sh` exits 3:
`BUNNY_UPDATE_MANIFEST` must name a signed update manifest."*

**The blocker was never the harness.** Read together with rollback's, those two
sentences say something the tracker had never said out loud: the project had
only ever had **one build**. "Update to the next candidate" is not a question a
single artifact can be asked.

Phase 5 changes that in principle — §3 requires a new build identity for any
code change, and Phase 5 changed code — and could not in practice, because the
build is blocked on storage. Once an artifact exists, N is `e906a487` (retained,
still in the builder's store) and N+1 is the Phase 5 artifact, and a
development-signed manifest can be produced with `dev-update-drill1`, whose
format is already exercised and passing.

Scenarios needing a reachable registry (`interrupted-download`,
`expired-metadata`) stay NOT_RUN regardless.

---

## 15. Rollback status

**NOT_RUN**, 0 of 5.

*"`vm-rollback-test.sh` exits 3: `BUNNY_PREVIOUS_BETA_DISK` must name an
existing QCOW2. There is no previous release to roll back to."*

Same root cause, same unblock. §20's sharpest requirement is recorded as the
acceptance criterion for when it runs: **a rollback that boots but loses user
state is not automatically a PASS** — user data, settings, companion modes,
voice settings, permissions and Trust state each checked individually.

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
| **Reference suite** | **INTERMITTENT — ≈1/14, quantified** | **CLEAN** |
| Security review | NOT DONE | REQUIRED |
| Physical hardware | NOT RUN | REQUIRED |
| Production signing | NOT DONE | REQUIRED |
| Update | NOT RUN | REQUIRED |
| Rollback | NOT RUN | REQUIRED |
| Owner approvals | NOT DONE | REQUIRED |

`scripts/release.py gate --kind qualification-candidate` → **BLOCKED**, verbatim
in the tracker. No "required" was changed.

Two rows deserve a second reading: the accessibility matrix carries two
**FAIL**s, the only outright failures anywhere in the matrices; and "second
production signer" is `BLOCKED` rather than `NOT_RUN` — it waits on a person,
not on work.

---

## 18. Remaining blockers

### Engineering, and immediately actionable once storage is back

1. **The Phase 5 build.** Blocked on host storage — see below. Required by §3
   for the two changed assets, and it unblocks 3, 4 and 6.
2. **The reference suite.** ≈1/14, cause narrowed to a non-health rung cap; the
   diagnostic that will name it is in place and a hunt is running.
3. **Update and rollback.** Need N+1 to exist.
4. **The review package rebinding.** The re-scan is **done** — see §12; the
   overlay-mount route needs no disk. What remains is the request itself: it is
   bound to `80df25b09f65`, and intake rejects a scope commit other than the
   candidate's, so sending it as written would produce a record intake refuses.
   Its 24 reachability bundles are also built against the July advisory set,
   not the 56 measured here. And it predates App Capsules and Trust — the two
   boundaries a reviewer of *this* product would most want to see.
5. **One `oci-archive:` scan**, to settle the 8-against-1 Critical discrepancy.
   This is the one item still genuinely blocked on disk.

### Not engineering

6. **Independent security review** — by definition excludes the people here.
7. **Physical hardware** — a purchase.
8. **Production signing** — a second person.
9. **Owner approvals** — a decision.

### The storage blocker, measured

Windows `C:` has **8.6 GB free**. The WSL guest reports 607 GB, which is the
illusion this project has hit before: `ext4.vhdx` is **731.5 GB** on disk
against **350 GB** used, so roughly 380 GB is trapped and reclaimable only by
an elevated compaction. A build writes about 30 GB.

It has already bitten twice this phase — once as `KNOWN_LIMITATIONS.md`
predicted (podman block-layer I/O errors), and once as grype's layer cache
filling `/tmp`. The second was **worked around rather than waited on**: mounting
the image's overlay in place costs no disk at all, and that is how §12 got its
scan. The build has no equivalent trick; it genuinely needs the space.

---

## 19. Artifact identities

**Phase 5 produced no artifact.** No digest in this report is new, and none in
`qualification/phase4/` was altered.

The Phase 4 identity stands as recorded in §1. §24 is satisfied by
subtraction: there is no Phase 5 result attached to the Phase 4 artifact,
because the only Phase 5 results that touch it — the grader's re-grading of
`g7`, `g12` and `g13` — are explicitly a **re-analysis of existing evidence**,
which §24 permits in those words.

Everything else Phase 5 changed lives outside the image (`qualification/`,
`tests/`) or is a source change awaiting a build (`shell/assets/`,
`shell/components/`, `build/scripts/`).

---

## 20. Evidence inventory

`qualification/phase5/` — 13 files:

| Path | What |
| --- | --- |
| `baseline/BASELINE.md`, `baseline.json` | The Phase 4 baseline, written before any change |
| `gates/RELEASE_GATES.md` | The tracker, both columns, with the gate tool's verbatim output |
| `isolation/TEST_ISOLATION_INVESTIGATION.md` | Rates, conditions, the controlled injection, what it is not |
| `performance/POLLER_DATA_SOURCE_COST.md` | The measurement that refutes the leading hypothesis |
| `performance/poller-bench.js`, `poller-bench-host.txt` | The instrument and its output |
| `security/SECURITY_DISPOSITION.md` | The disposition, both scans, and the counting |
| `security/candidate-disposition-matrix.json`, `build_candidate_matrix.py` | 56 advisories on the **candidate**, all PENDING_REVIEW, regenerable |
| `security/disposition-matrix.json`, `build_disposition_matrix.py` | The July set, 37 rows, kept with its own scope and its measured reachability |
| `security/scan/candidate-fixed.json`, `image-id.txt`, `grype-version.txt` | The raw scan of `e906a48793d7` |
| `signing/SIGNING_CONFORMANCE.md` | Conformance, and the refusals measured |
| `hardware/HARDWARE_TRACK.md` | The track, bound to the candidate |
| `feedback/ALPHA_FEEDBACK_PLAN.md` | The instrument, and the zero |
| `ux/GREETER_DISPOSITION.md` | The §12A decision, with what "yes" would cost |

`qualification/grader/` — the instrument, with fixtures and 31 tests, declared
in `_PHASES_AFTER_THE_RECORD` as a tool rather than a record.

Phase 4's 166 files are unchanged. Verified: `git status` on
`qualification/phase4/` is clean after every grading run, and the grader's own
test suite asserts it byte-for-byte.

---

## 21. Final recommendation

**Do not label anything release-qualified.** The project's own gate says
BLOCKED and its governing sentence stands: *building a candidate for
examination remains permitted; calling one qualified does not.*

**`e906a487` remains a usable Alpha Release Candidate**, with the same warnings
Phase 4 attached and one fewer excuse: the wallpaper defect it shipped is
understood and fixed in source, and the diagnosis it recorded was wrong in a
way that would have wasted the next person's time.

**The next action is 8.6 GB of disk**, and it is not a small thing to say. Four
of this phase's open items are downstream of one elevated compaction: the
build, update, rollback, and the security re-scan that rebinds the review
package to the artifact anyone would actually review.

### What this phase is worth being judged on

Phase 4's finding was that its instrument was wrong more often than its product
was. Phase 5's is narrower and the same shape: **three of the four defects
found this phase were in things that measure, not in things that run.**

* A grader that could not fail a journey — now a library with a fixture that
  fails, a fixture that passes, and 31 tests.
* 153 tests that nothing executed, one of them cited in a shipped unit file as
  the guard on a defect that has actually occurred.
* A feedback taxonomy that could not name three of the product's four
  distinguishing subsystems.
* And a diagnosis in `KNOWN_LIMITATIONS.md` that named the wrong cause of a
  real defect.

None of those would have been found by running the suite, because in three of
the four cases the suite was the thing that was wrong.

**Optimise for a release process where a PASS actually means PASS.** The one
number in this report I would most like a reader to check is the fourth row of
§4's table: the whole `tests/companion` package, 28 runs, 2 failures. It is not
clean, it is not called flaky, and it is not closed.
