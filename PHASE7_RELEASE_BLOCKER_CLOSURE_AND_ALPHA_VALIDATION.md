<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Phase 7 — Release Blocker Closure & Alpha Validation

## STATUS: **PHASE 7 — ENGINEERING BLOCKERS CLOSED**

External gates remain blocked, by the same owners as before: an independent
reviewer, a physical machine, a key authority, a second person, and Alpha
testers. No repository change can move them, and none pretended to.

---

## 1. Executive summary

Phase 6 ended with three engineering blockers that were the project's to fix
and five external gates that were not. Phase 7's Track A closed every
engineering blocker with measured evidence, and Track B moved external
**readiness** without moving a single external status — because only the
named owners can.

What closed, all against evidence rather than declaration:

* **The rollback harness proves the deployment that actually booted** — four
  identities, three independent sources, user state verified against an
  expectation committed before any boot. It passed on run 4; runs 1–3 are
  preserved because their two NOT_RUNs and one FAIL are the harness's verdict
  semantics working (§5).
* **A recovery journey exists and passes**: a machine proven unable to boot
  was brought back by a separately built recovery medium with its own
  identity, the repair derived from the broken disk's own state (§6).
* **The only two FAILs in the project — `high-contrast` and `text-scaling` —
  are resolved**: the fix was already in the subject artifact's lineage, and
  Phase 7 verified it on the subject artifact itself, numerically and by
  looking at the pixels (§7).
* **The evidence-immutability gap is closed**: phases 4–6 are pinned (5424
  files), and the negative control mutated a real historical file and watched
  the guard fail (§8).
* **A script-executability gate exists** — the committed blob is what is
  checked, five constructed-blob controls keep its failure branches alive,
  and ten stray executable bits on data files were corrected as metadata (§9).
* **The 18 Go High security findings got their per-binary version analysis**,
  bound to the subject artifact's own binaries; six advisories answer
  differently for podman and skopeo, exactly the row-split Phase 6 predicted
  (§12).

The subject artifact is unchanged and unsigned: `e906a48793d7`. No PASS was
transferred anywhere; every new PASS names the artifact it was measured on.

## 2. Phase 6 baseline

`62b8b130` — PHASE 6 — EXTERNAL GATES BLOCKED; reference certification 2 ×
6030 tests, zero failures. The Alpha Release Candidate `e906a487` remained
READY as an Alpha candidate only, explicitly UNSIGNED. Phase 7 changed no
historical evidence; the frozen-evidence guard now proves that class of
statement instead of asserting it.

## 3. Artifact inventory

| Artifact | Identity | Status |
| --- | --- | --- |
| Subject — Alpha RC | `e906a48793d7`, image `sha256:c87a6616…`, qcow2 `497add9a…`, ISO `823d50ca…` | unchanged, unsigned; all digests recomputed from bytes 2026-08-18 (`qualification/phase7/baseline/freeze.log`) |
| Counterpart (N+1) | `e501218f2fe0`, qcow2 `b4dd95f3…` | unchanged; the rollback chain's update target |
| Rollback journey disk | overlay of the Phase 5 staged disk (subject ← N+1 staged) | consumed by the journey; identities bound by origin refspec |
| **Recovery medium** (new) | qcow2 `40dd7d2d1bf6b69ca6199013641b08bbb04a53e94ad12f5c6496c99eb5a3e648`, built at `b812e48e` by `build-image.sh recovery` | its own artifact per §6; **unsigned**; instrumented overlay `ae2dfc92…` recorded separately |

Product code and image contents of the subject did not change in Phase 7, so
the §21 new-build policy was never triggered for it.

## 4. Track A results

| Gate | Result |
| --- | --- |
| Rollback harness proves the booted deployment | **PASS** |
| Rollback user-state preservation vs prior expectation | **PASS** |
| Recovery media journey | **PASS** (defined journey; unsigned medium; limits named) |
| Accessibility `high-contrast` | **PASS** (was FAIL) |
| Accessibility `text-scaling` | **PASS** (was FAIL) |
| Evidence immutability covers phases 4–6 | **PASS** + negative control |
| Script executability | **PASS** + negative control |

Authoritative matrix with evidence links:
`qualification/phase7/gates/ENGINEERING_GATES.md`.

## 5. Rollback qualification

`qualification/phase7/rollback/ROLLBACK_QUALIFICATION.md`. The §3 evidence,
verbatim from `evidence/verdict.json`:

| Identity | Value |
| --- | --- |
| Before-update deployment | `1804c600…` = `localhost/bunny-os-beta:e906a48793d7` (bound by origin refspec, **not** by title — the titles are inverted on this disk and the expectation says so) |
| Update-target deployment | `18fd8a7d…` = `oci:/run/p5update/candidate:e501218f2fe0` |
| Selected rollback target | `1804c600…`, from `ostree admin status` after `bootc rollback` exited 0 |
| Actually booted | `1804c600…`, agreed independently by kernel `ostree=`, `bootc status --json`, and a per-deployment `/etc` identity marker |

User state (§4): `expectation.json` committed before any boot; all eight
markers — companion mode, scale, position, voice configuration, Trust
grants, two user-data files, settings — byte-identical after rollback;
hostname and locale per their recorded rules; the `/etc` identity marker
proves the per-deployment `/etc` itself switched. A healthy machine on the
wrong deployment is FAIL in the grader and in its unit tests, and run 3
demonstrated the FAIL branch on a real boot.

## 6. Recovery qualification

`qualification/phase7/recovery/RECOVERY_QUALIFICATION.md`. The §5 journey —
cannot-boot (measured, control-checked) → recovery boots independently →
installation inspected → boot entry repaired **by derivation from the broken
disk's own /ostree** → repaired disk boots its own deployment — **PASS**,
graded fail-closed. Explicitly not claimed: disaster recovery, encrypted
recovery, the interactive console, and the 11-scenario recovery-media matrix,
which does not flip on one journey.

## 7. Accessibility results

The two FAILs were recorded on image `b09f523`: nothing for a scale factor to
multiply, nothing for a theme to override. The design-system phase built the
mechanism (stylesheet as a function of `textScale` and `highContrast`;
`themeManager` watching the GSettings keys), and that lineage is inside the
subject artifact's build commit. What was missing was measurement on the
subject artifact — Phase 7 ran the sweep against the `e906a48793d7` qcow2:

* settings written via the guest's own gsettings and read back;
* **text-scaling 1.5×**: 19 of 60 comparable AT-SPI controls grew, none
  shrank (the direct measurement of "text gets larger"); 41.5 % of the screen
  changed, 6.0× the run's own noise floor;
* **high-contrast**: 99.6 % of the screen changed (14.4× noise) — the
  wallpaper is replaced by the theme's opaque ground; verified by eye as well
  as by diff;
* the noise floor (6.9 %) is itself explained, not hidden: the diff mask
  (`noise-mask.png`) shows it is the live Companion animation and the system
  gauges;
* regression: the mechanism's tests run in the certified suite and fail if
  the scale multiplication or the high-contrast theme is removed.

Recorded limitation: the first-run GTK dialog keeps its GTK theme at
high-contrast; the scenario measures the shell, and the row's notes say so.
The accessibility matrix now reads **2 PASS / 12 NOT_RUN / 0 FAIL** — still
incomplete, and `test_accessibility_is_not_yet_qualified` still enforces that
honesty. Evidence: `qualification/phase7/accessibility/evidence/a11y-e906a48793d7/`.

## 8. Evidence immutability

The fa49380 record pinned nothing after itself; Phase 6 measured that. The
successor record (`qualification/phase7/immutability/frozen-evidence.json`)
pins **5424 files across 24 trees** — phases 4, 5 and 6 included — enforced
by `tests/release/test_frozen_evidence.py`. Exempt, with reasons: this
phase's own tree and the grader instrument. Negative control, run against the
real record (`negative-control.log`): modify one historical file → FAIL;
stage a file into a frozen tree → FAIL; restore → PASS. Constructed-tree
controls run on every suite execution. The elder guard keeps its own record
and passes unchanged.

## 9. Script infrastructure validation

`tests/release/test_script_executability.py` asks the repository, not the
working tree: executable implies shebang; shebangs are CR-free and name an
allowlisted interpreter; `.sh` blobs are LF throughout (the index column, not
the checkout — `-text` hides working-tree corruption on the host that made
it). Current state: 20 executables well-formed, 131 shell blobs clean, ten
stray executable bits on evidence data files corrected as metadata with both
immutability guards passing before and after
(`qualification/phase7/executability/MODE_CORRECTIONS.md`). Five
constructed-blob negative controls run in every certification.

## 10. Track B — Alpha validation

**NOT_RUN — zero testers, zero records.** What exists now is a protocol a
tester can execute (`qualification/phase7/alpha/ALPHA_TEST_PROTOCOL.md`):
digest binding before anything else, five journeys (first boot, Companion
modes, voice, Trust allow/deny with outcomes verified, reboot persistence),
MEASURED and USER-REPORTED evidence kept separate, and the Phase 6 triage
schema adopted unchanged. Readiness moved; the gate did not.

## 11. Physical hardware results

**NOT_RUN.** No machine exists. The three `expectation.json` records under
`qualification/phase6/hardware/` still await one; one machine will be one
qualified data point, not universal compatibility.

## 12. Security review status

**Independent review: NOT_RUN — no reviewer exists.** Dispositions: all 80
findings remain `PENDING_REVIEW`; the tooling still refuses non-blocking
dispositions without a completed independent review.

What moved: the version half of the Go High analysis Phase 6 named as
outstanding (`qualification/phase7/security/REVIEW_PACKAGE_ADDENDUM.md`).
Bound to the subject artifact's own binaries (ostree objects resolved to
paths by hardlink inode; buildinfo `dep` records): 18 findings, **15
affected-by-version in at least one binary, 3 undetermined pseudo-versions,
0 absent** — and six advisories where podman is at/above the fix while
skopeo is affected, the exact merged-row blindness Phase 6 predicted.
Symbols stay named only for the eight Criticals; the addendum says so.

## 13. Signing status

**NOT_RUN, unchanged.** Zero signature files existed in Phase 6's measurement
and Phase 7 created none — including for the new recovery medium, whose
record marks itself unsigned. No key was created; nothing here may be called
signed.

## 14. Second approval status

**NOT_RUN.** One person. A successful CI run is not a second signer, and no
approval record exists.

## 15. Alpha feedback

None — see §10. Nothing was converted from absence into anything.

## 16. Defect inventory (found by Phase 7, in Phase 7's own instruments and inherited state)

| # | Defect | Class | Disposition |
| --- | --- | --- | --- |
| 1 | A 300-byte serial `cmdline=` marker split mid-line by a kernel SELinux message; grader refused (run 1 NOT_RUN) | HARNESS | fixed (`2c7426f3`): short validated markers ×2 + constructed-log regression |
| 2 | The 2 KB single-line `bootc status --json` lost to the same interleaving (run 2 NOT_RUN) | HARNESS | fixed (`55636756`): `dmesg -n 1` in guest + short markers for every graded identity |
| 3 | Phase 5's `bunny-p5-stage.service` left enabled in the staged deployment's `/etc` powers the machine off on every boot; run 3 lost `bootc rollback` mid-command to it | HARNESS / inherited state | fixed: prepare.sh disables the three P5 leftovers; run 3 preserved as the FAIL demonstration |
| 4 | `recover.sh` first draft instrumented the physical root's `/etc` via `guestfish -i` — a unit no boot would ever read | HARNESS | fixed before first run (`59f412ef`): deployment-`/etc` injection |
| 5 | Ten evidence data files carried executable bits | COSMETIC / repo metadata | fixed as metadata; content untouched, guards green before and after |
| 6 | The first-run GTK dialog does not adopt the high-contrast theme (shell does) | ACCESSIBILITY (observation) | recorded in the matrix row's notes; not claimed fixed |
| 7 | `go-binaries-buildinfo.json` `goVersion` for podman is a spurious byte-pattern capture | COSMETIC | recorded; no conclusion rests on the field |

## 17. Gate matrices

Engineering: `qualification/phase7/gates/ENGINEERING_GATES.md` — all seven
rows PASS. External: `qualification/phase7/gates/EXTERNAL_GATES.md` — all
six rows still with their owners; readiness column updated. The two matrices
are deliberately not merged.

## 18. Remaining blockers

The ten blocking conditions
(`qualification/phase7/conditions/BLOCKING_CONDITIONS.md`, committed before
any result; none weakened, no exception recorded):

| # | Condition | Met? |
| ---: | --- | --- |
| 1 | Accessibility FAILs resolved | **YES** |
| 2 | Rollback harness proves the booted deployment | **YES** |
| 3 | Rollback state vs prior expectation | **YES** |
| 4 | Recovery disposition | **YES** — option A, the journey passes |
| 5 | Independent security review | NO — no reviewer exists |
| 6 | Critical/High dispositions | NO — blocked on 5 |
| 7 | Physical hardware | NO — no machine exists |
| 8 | Production signing | NO — no key, nothing signed |
| 9 | Second signer | NO — one person |
| 10 | Frozen evidence tamper-evident | **YES** — guard + negative control |

Five of ten met — the five that were the project's to meet. The other five
name people, hardware and authority, exactly as recorded in advance.

## 19. Evidence inventory

| Path | What |
| --- | --- |
| `qualification/phase7/conditions/` | the ten conditions, committed first (`7db5962b`) |
| `qualification/phase7/baseline/` | BASELINE.md + freeze.log (all five digests recomputed, all match) |
| `qualification/phase7/gates/` | both matrices |
| `qualification/phase7/immutability/` | frozen-evidence.json (5424 files), build-record.py, negative-control.sh + log |
| `qualification/phase7/executability/` | gate run log + MODE_CORRECTIONS.md |
| `qualification/phase7/rollback/` | harness (prepare / journey-guest / run-journey / verdict), expectation.json, ROLLBACK_QUALIFICATION.md, evidence/ incl. runs 1–3 |
| `qualification/phase7/recovery/` | RECOVERY_DEFINITION.md (written first), harness, RECOVERY_QUALIFICATION.md, evidence/ incl. medium identity |
| `qualification/phase7/accessibility/` | compare_screens.py, update_matrix_rows.py, evidence/a11y-e906a48793d7/ (JSON, screenshots, noise mask) |
| `qualification/phase7/security/` | REVIEW_PACKAGE_ADDENDUM.md, analyze_high_go.py, go-binaries-buildinfo.json, high-go-version-analysis.json |
| `qualification/phase7/alpha/` | ALPHA_TEST_PROTOCOL.md |
| `qualification/phase7/verify-at-head.sh` + `certification/` | the reference-suite certification at the Phase 7 head |
| `tests/release/` | the four new gate/grader suites (frozen evidence, executability, rollback verdict, recovery verdict) |

One Windows-checkout observation, classified ENVIRONMENT: the full suite on
the Windows working tree shows one failure
(`test_provenance_accounts_for_every_selected_tts_byte`, a 605-byte
notice-file size drift consistent with line-ending normalization). The
reference certification runs as `bunny` on ext4, per the runbook; that record
is the authoritative one (§20 / `qualification/phase7/certification/`).

## 20. Final disposition

# PHASE 7 — ENGINEERING BLOCKERS CLOSED

Track A is complete under §9: rollback harness PASS, recovery journey PASS,
both accessibility FAILs resolved — plus the immutability and executability
gates, each with a negative control that actually fired.

The project is **not** a stable release, and this phase does not edge toward
claiming one. The release remains blocked on: independent security review,
Critical/High dispositions, physical hardware, production signing, a second
signer, and Alpha validation. The artifact remains `e906a48793d7` and remains
**UNSIGNED**.

## The standard, and whether it was met

Every PASS above answers the four §FINAL questions: what was tested, on
which artifact, what evidence proves it, and which requirement it satisfies.
Where the answer was "a different artifact" (the design-phase measurement on
`7edd3fd`) the row did not move until the subject artifact was measured.
Where a harness could not tell truth from survival, it said NOT_RUN or FAIL
— four times, on the record — before it was allowed to say PASS.
