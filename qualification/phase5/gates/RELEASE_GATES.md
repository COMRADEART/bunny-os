# Release-gate tracker

**Maintained state of every gate the project defines.** The "Required" column
is fixed. §23 of the Phase 5 directive: *"Never change 'required' merely
because it is inconvenient."*

Authority for the machine-checked rows is `scripts/release.py gate`, not this
file. Where this file and the tool disagree, the tool is right and this file is
stale — which is why every machine-checked row names the command that produces
it.

Last reconciled against the tool: Phase 5, at `9a34ee81`. Reference-suite row
certified at `30f11a6d`.

---

## 1. The two questions, kept apart

The directive's §23 table and the project's own gate tool answer **different
questions**, and merging them would produce a number that is true of neither.

* **"Did the qualified journey pass?"** — one scenario, driven end to end on
  the artifact, with evidence. This is what Phase 4 measured and what its
  PASSes mean.
* **"Is the matrix complete?"** — every scenario in a category, including the
  ones nobody has built a harness for. This is what
  `scripts/release.py gate` asks.

Installation is the clearest case. Phase 4 recorded **installation: PASS** and
it is true: an encrypted install ran from the candidate's own ISO and produced
`findings: []`. The installation *matrix* is **NOT_RUN**, and that is also
true: 5 of its 12 scenarios have evidence and 7 do not.

Both are reported below, in separate columns, because a tracker that showed one
of them would be misleading whichever it chose.

---

## 2. The matrix

| Gate | Journey (Phase 4/5 evidence) | Matrix (`release.py`) | Required | Phase 5 movement |
| --- | --- | --- | --- | --- |
| Installation | **PASS** — encrypted install from the RC's own ISO, `findings: []` | **NOT_RUN** — 5 PASS / 7 NOT_RUN of 12 | PASS | none |
| Encryption | **PASS** — two encrypted boots | **NOT_RUN** — 3 PASS / 6 NOT_RUN of 9 | PASS | none |
| First boot | **PASS** — `g1`, wizard at step 1 of 10 | (covered by installation) | PASS | none |
| Login | **PASS** — real greeter, typed password, `g1` + `g10` | (covered by installation) | PASS | none |
| Voice | **PASS** — `voice-phase3-b`, exit 0, 19 stages | — | PASS | none |
| Trust | **PASS** — both directions, `g12` / `g13` | — | PASS | **re-graded** under the extracted grader; both still PASS |
| Persistence | **PASS** — `g2`→`g3`→`g4`, two reboots | **NOT_RUN** — preservation matrix 0 PASS / 10 | PASS | none |
| Companion | **PASS** — modes survive two reboots | — | PASS | none |
| Shutdown | **PASS** — clean ACPI on every boot of the chain | — | PASS | none |
| Reference suite | **CLEAN** — 5/5 full runs, 0 failures | — | **CLEAN** ✓ | **closed** — root cause found and fixed; see §3 |
| Security review | **NOT DONE** | `PENDING_EXTERNAL_REVIEW` | REQUIRED | candidate re-scanned; matrix rebound to `e906a48793d7` at module granularity, 8 Critical unchanged. The review request itself is still bound to `80df25b09f65` and asks the wrong question — see below |
| Physical hardware | **NOT RUN** | `PENDING_HARDWARE` | REQUIRED | none — no machine |
| Production signing | **NOT DONE** | `BLOCKED` (second signer) | REQUIRED | workflow specified; no key created |
| Update | **NOT_RUN** — staged update works; the image ships no update trust root and refuses by design | **NOT_RUN** — 1 PASS / 12 of 13 | REQUIRED | needs a production key, i.e. a second person |
| Rollback | **PASS** by `bootc rollback`, user state intact / **NOT_RUN** by `vm-rollback-test.sh`, which was passing without rolling back | **NOT_RUN** — 0 PASS / 5 | REQUIRED | the harness cannot select a deployment; the product can |
| Owner approvals | **NOT DONE** | `PENDING_OWNER` | REQUIRED | none — not an engineering act |
| Licence | — | **PASS** | PASS | none |
| Independent reproducibility | — | **PASS** | PASS | none |
| Development signing drill | — | **PASS** | PASS | none |
| Independent recovery media | — | **NOT_RUN** | REQUIRED | none |
| Accessibility evidence | — | `PENDING_EXTERNAL_REVIEW`; matrix 0 PASS / 12 NOT_RUN / **2 FAIL** | REQUIRED | none |

Verbatim, at `9a34ee81`:

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

    No artifact may be labelled release-qualified. Building a candidate for
    examination remains permitted; calling one qualified does not.

**Two rows deserve to be read twice.** The accessibility matrix carries two
**FAIL**s, not merely NOT_RUNs — a failing row is a defect, not an absence, and
it is the only outright FAIL anywhere in the matrices. And "Second production
signer available" is `BLOCKED` rather than `NOT_RUN`: it is not waiting on
work, it is waiting on a person.

---

## 3. Reference suite — the one gate Phase 5 could close by itself

Required: **CLEAN**. Entering state: **INTERMITTENT**. **Now: CLEAN.**

Measured on the Fedora reference target, as `bunny`, from an ext4 clone — the
conditions the runbook requires, because `/mnt/c` produces nine false failures
and root produces one more.

| Condition | Runs | Slice failures | Rate |
| --- | ---: | ---: | --- |
| The target class alone | 20 | 0 | **0/20** |
| The whole module alone | 40 | 0 | **0/40** |
| The target after each earlier neighbour, one at a time | 60 | 0 | **0/60** |
| The whole `tests/companion` package | 28 | 2 | **≈2/28** |

Phase 4 recorded "5/5 alone and 1-in-3 in-package". The alone result reproduces
on a 4× larger sample; the in-package rate does not, and **the 1-in-3 figure
should not be quoted as measured**.

### Root cause

**The host's own memory pressure**, arriving through a signal the slice never
pinned.

`CharacterPresenter` builds `base_signals` from `assess_current_machine()` —
the real host — and every field the slice's `_VISUAL` override did not name
survived into every evaluation. `memory_pressure` is read as Linux PSI,
`/proc/pressure/memory` `some avg10 >= 0.1`: a ten-second rolling average of
memory stall that a suite running several thousand tests in one process
crosses, intermittently, for reasons unrelated to this slice. The selector then
correctly degrades to `static-image`, and the two steps that assert
`animated-2d` fail while the three that assert degradation pass for free.

Proved by setting that one field and changing nothing else: the failure list is
byte-identical, with `incidentalRendererFault=None` and `rendererHealthy=True`
— the two tells that the caught in-package instance also recorded, and that
every earlier explanation (a renderer fault, host contention, cross-test
interference) fails to predict.

### The fix, and why it strengthens rather than silences

`_VISUAL` now pins all five host-derived signals the ladder can degrade or cap
on. Pinned in the *slice*, not the presenter: the presenter reading the real
machine is correct, because on a real machine under real pressure the companion
*should* stop animating.

Step 18 *declares* `memory_pressure: True` to prove the selector degrades. On a
machine already under ambient pressure, the rung was static before step 18
asked — **so step 18 was passing without testing anything.** The pin is what
makes steps 17 to 21 measure the selector at all.

Guarded structurally: `test_slice_host_invariance.py` parses `adaptation.py`
and requires every signal the ladder consults to be pinned or declared exempt
with a reason. Negative controls: removing the pin fails 6 of 10; the
degradation checks must still fire; and step 17 must reach `animated-2d` *with
no pressure reason*, so pinning to an arbitrary value would not satisfy it.

### Certification — clean

§8 requires repeated runs, not one. At `30f11a6d`, on the reference target, as
`bunny`, from an ext4 clone:

| | Runs | Failures |
| --- | ---: | ---: |
| `tests/companion` | 8 | **0** |
| Full reference suite (5988 tests) | 5 at the fix, 3 at HEAD | **0** |
| Installer sub-suite (178 tests) | 5 | **0** |

**0 unexplained failures, 0 unexplained errors.**

The eighth companion run recorded `psi_avg10 = 0.71` — seven times the
threshold that used to degrade the rung — and **zero slice failures**. Before
the pin, that is the run that would have failed. A later set at HEAD reached
`psi_avg10 = 2.02`, twenty times over, and also passed. The certification hit
the conditions that cause the defect rather than avoiding them.

Evidence: `qualification/phase5/isolation/certification/verify.log` and
`verify-at-c923169d.log`. The second run asserts the commit it checked out and
the number of tests it discovered — the first version of that script did
neither and reported three clean runs of a different branch, with a suite that
had discovered 1555 tests instead of 5988.

**This gate is now CLEAN.** It is the only required gate Phase 5 could close by
itself, and the only one it closed.

---

## 4. Update and rollback — what was actually in the way

Both matrices are NOT_RUN, and their recorded reasons are exact:

    update:   vm-upgrade-test.sh exits 3: BUNNY_UPDATE_MANIFEST must name a
              signed update manifest. No manifest has been published and no
              registry is reachable.

    rollback: vm-rollback-test.sh exits 3: BUNNY_PREVIOUS_BETA_DISK must name
              an existing QCOW2. There is no previous release to roll back to.

Read together, those two sentences say something the tracker has never said out
loud: **the blocker was never the harness. It was that the project had only
ever had one build.** "Update to the next candidate" and "roll back to the
previous release" are not questions a single artifact can be asked.

Phase 5 built one, so both questions were asked. N is the Phase 4 RC
`e906a487`, retained and verified by digest; N+1 is `e501218f2fe0`.

What was found behind the blocker was not what the tracker expected.

* **Boot parity passes.** Both images reach a healthy target.
* **A staged update is real.** The shipped `bootc` staged N+1 onto a copy of N
  and the disk went from one deployment to two;
  `vm-upgrade-test.sh staged` PASSES.
* **The product rolls back.** `bootc rollback` then reboot brings up N, agreed
  by the per-deployment `os-release`, the kernel command line and
  `bootc status`. All five user-state markers survive it.
* **`vm-rollback-test.sh deployment-rollback` was passing without rolling
  back** — three runs, every one on the default deployment, because it wrote a
  40-byte file where GRUB needs a padded 1024-byte block and its only check was
  that a healthy target was reached. Repaired to identify the deployment that
  booted; it now reports NOT_RUN on the same disk.
* **No manifest scenario can run.** Not for want of a manifest: the image ships
  `enabled: false` and an empty update trust store, so the agent answers
  `not_configured` and would answer `unknown_key` to anything that got past it.
  That is correct for an image with no production key.

Detail and evidence: `../update/UPDATE_AND_ROLLBACK.md`.

**What that will and will not close.** It can close the *mechanism* scenarios:
manifest validation, staging, a booted N+1, a rollback to N, and — §20's
sharpest requirement — whether user data, settings, companion modes, voice
settings, permissions and Trust state survive the trip. *"A rollback that boots
but loses user state is not automatically a PASS."*

It cannot close the scenarios that need infrastructure the project does not
have: `interrupted-download` and `expired-metadata` need a reachable registry;
anything signed for production needs a production key, which §19 keeps out of
this repository by design. Those stay NOT_RUN with their reason named.

**It was recorded here as blocked on host storage. It was not.** The claim was:
Windows `C:` has 8.6 GB free, the guest's 607 GB is an illusion, and a build
writing 30 GB would fail at the block layer. Two things were wrong with it. The
failure that started it was `grype podman:` filling **`/tmp`, which is tmpfs —
RAM**, not a disk. And "the host volume" conflated Windows `C:` with the ext4
volume the builder writes to: the VHDX was already 731.5 GB on disk against
350 GB used, so ~380 GB of it was allocated and free for reuse.

Measured before believing it either way: writing 1 GiB, then 20 GiB, inside WSL
moved the VHDX by **zero bytes** and `C:` free space by **zero bytes** — 7.848 GB
before and after each. The build then ran, exported a 2.96 GB OCI archive and
produced a 13.7 GB raw image without difficulty.

**What has since closed.** The build exists (`e501218f2fe0.1787016937`), boot
parity passes, an update is genuinely staged, and `bootc rollback` brings up the
previous deployment with all five user-state markers intact — §20's sharpest
requirement, met. What did *not* close: the manifest scenarios, because the
image ships no update trust root and refuses by design; `interrupted-download`
and `expired-metadata`, which need a reachable registry; and
`vm-rollback-test.sh`'s own deployment-selection route, which turned out to have
been reporting PASS without rolling back at all. See
`../update/UPDATE_AND_ROLLBACK.md`.

---

## 5. What no amount of engineering in this repository can close

Recorded so that the remaining distance is not mistaken for a backlog.

| Gate | Why it is not an engineering task |
| --- | --- |
| Independent security review | It is independent. Intake rejects any reviewer whose name or organisation matches a project principal. |
| Physical hardware | There is no machine. Every result in this project is QEMU with software rendering. |
| Production signing | A production key, a second signer, and controlled access. §19 forbids the key entering this repository. |
| Owner approvals | A decision, by a person with the authority to make it. |

Four of the six outstanding REQUIRED gates — and the update gate is now a
fifth: it cannot close while the image ships no update trust root, and that
root cannot exist until a production key does, which is the second row of this
table wearing a different hat. Rollback is the only one of the six left that
engineering can move, and what it needs is a harness that can select a
deployment; the product half already passes.

---

## 6. One gate should record how it measured

`build/scripts/security-scan.sh` runs `grype oci-archive: --only-fixed
--fail-on high` and writes `grype.json`; `release/vulnerability.py` turns that
into `vulnerability-report.md`. Neither output records the vulnerability
database version, nor whether Go findings were matched at function or module
granularity.

Those two facts decide the answer. The same route, on the same image, with the
same grype binary, reports **8 Critical** against a July database and **1**
against the 2026-08-17 one — because the newer database carries
`qualifiers.go_imports` naming the vulnerable functions, and the binaries do
not contain them. See `../security/SCAN_ROUTE_DISCREPANCY.md`.

A gate result that does not say how it was measured cannot be compared with
the next one. **No change is made here**: changing the release gate's scanner
invocation during a release phase, on the strength of one observation, is
precisely the kind of edit that should be proposed and reviewed rather than
slipped in. Recorded as a recommendation:

1. record `descriptor.db.built` and `descriptor.db.schemaVersion` from the
   grype output into `vulnerability-report.md`;
2. record whether the run emitted the "none carry function symbols" warning,
   which is the one-line signal for granularity;
3. keep scanning the image, not an SBOM — but state the granularity, because
   the conservative number is the one a Critical disposition must be argued
   against.

---

## 7. Status

**PHASE 5 — RELEASE CANDIDATE BLOCKED.**

Not "ALPHA HARDENED". Phase 5 has now built an artifact —
`e501218f2fe0.1787016937`, see `../build/BUILD_IDENTITY.md` — and the two
repaired assets are verified in it with a negative control. But that build is
new, unqualified, and carries none of the journey evidence the Phase 4
candidate does; a fresh image is not a hardened Alpha either. Five required
gates remain outstanding.

Not "RELEASE GATE READY", because five required gates are outstanding and four
of them cannot be closed from inside this repository.

The Alpha Release Candidate `e906a487` remains **READY as an Alpha Release
Candidate and nothing else**, exactly as Phase 4 left it. Phase 5 has not
changed that verdict and has not touched that artifact.
