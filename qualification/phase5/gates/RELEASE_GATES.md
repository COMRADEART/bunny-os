# Release-gate tracker

**Maintained state of every gate the project defines.** The "Required" column
is fixed. §23 of the Phase 5 directive: *"Never change 'required' merely
because it is inconvenient."*

Authority for the machine-checked rows is `scripts/release.py gate`, not this
file. Where this file and the tool disagree, the tool is right and this file is
stale — which is why every machine-checked row names the command that produces
it.

Last reconciled against the tool: Phase 5, at `9a34ee81`.

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
| Reference suite | **INTERMITTENT** | — | **CLEAN** | **quantified** — see §3 |
| Security review | **NOT DONE** | `PENDING_EXTERNAL_REVIEW` | REQUIRED | package rebound to the candidate; disposition matrix built |
| Physical hardware | **NOT RUN** | `PENDING_HARDWARE` | REQUIRED | none — no machine |
| Production signing | **NOT DONE** | `BLOCKED` (second signer) | REQUIRED | workflow specified; no key created |
| Update | **NOT RUN** | **NOT_RUN** — 1 PASS / 12 of 13 | REQUIRED | **blocker identified and removable** — see §4 |
| Rollback | **NOT RUN** | **NOT_RUN** — 0 PASS / 5 | REQUIRED | **blocker identified and removable** — see §4 |
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

## 3. Reference suite — the one gate Phase 5 can close by itself

Required: **CLEAN**. Current: **INTERMITTENT**, now with a number.

Measured on the Fedora reference target, as `bunny`, from an ext4 clone —
the conditions the runbook requires, because `/mnt/c` produces nine false
failures and root produces one more.

| Condition | Runs | Slice failures | Rate |
| --- | ---: | ---: | --- |
| The target class alone | 20 | 0 | **0/20** |
| The target after each earlier neighbour, one at a time | 60 (12 × 5) | 0 | **0/60** |
| The whole `tests/companion` package | 12 | 1 | **1/12** |

Phase 4 recorded "5/5 alone and 1-in-3 in-package". The alone result
reproduces and is now on a 4× larger sample. The in-package rate does not: 1 in
12 here against 1 in 3 there. Both are samples of the same intermittent event
and neither is the true rate; the honest statement is that it is **rare and
in-package only**, and that the Phase 4 figure should not be quoted as
measured.

**What the neighbour sweep settles.** Discovery runs modules in name order, so
only the twelve that sort before `test_character_cli_vertical` can have touched
anything it reads. All twelve were run immediately before it, five times each.
None reproduced it. **It is not one neighbour.**

That leaves a mechanism that depends on how much has happened in the process
before the slice runs, and the diagnosis is in progress. Every failing run
carries the same signature — steps **17 and 21** fail while 18, 19 and 20 pass —
which is the signature of the presenter being **unhealthy** rather than of the
selector being wrong: an unhealthy renderer is capped below `animated-2d`, so
the two steps that assert `animated-2d` fail and the three that assert
degradation succeed trivially.

Phase 5 has already made the failure diagnosable: the slice report has always
carried `incidentalRendererFault`, `retryCleanOfFaults` and the renderer events
with their exception text, and no assertion printed any of it. Four phases of
investigation started from a step number.

**This gate is not closed.** It is quantified, its cause is narrowed, and the
next failure will say why.

---

## 4. Update and rollback — why they were blocked, and what changes

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

Phase 5 changes that, because §3 requires a new build identity for any code
change and Phase 5 changes code. Once a Phase 5 artifact exists:

* N is the Phase 4 RC, `e906a487`, ISO `823d50ca…`, beta payload
  `sha256:c87a6616…` — all retained, all still in the builder's image store.
* N+1 is the Phase 5 artifact.
* `BUNNY_PREVIOUS_BETA_DISK` has a value for the first time.
* A development-signed manifest naming N+1 can be produced; the format is
  already exercised and passing
  (`qualification/installed-system/evidence/collections/update-manifest-valid.json`,
  `keyClass: development`).

**What that will and will not close.** It can close the *mechanism* scenarios:
manifest validation, staging, a booted N+1, a rollback to N, and — §20's
sharpest requirement — whether user data, settings, companion modes, voice
settings, permissions and Trust state survive the trip. *"A rollback that boots
but loses user state is not automatically a PASS."*

It cannot close the scenarios that need infrastructure the project does not
have: `interrupted-download` and `expired-metadata` need a reachable registry;
anything signed for production needs a production key, which §19 keeps out of
this repository by design. Those stay NOT_RUN with their reason named.

**Currently blocked on host storage, not on engineering.** Measured: Windows
`C:` has 8.6 GB free; the WSL guest reports 607 GB, which is the illusion this
project has hit before — its `ext4.vhdx` is 731.5 GB on disk against 350 GB
used, so roughly 380 GB is trapped and reclaimable only by an elevated
compaction. A build writes about 30 GB and would fail with block-layer I/O
errors, exactly as `KNOWN_LIMITATIONS.md` already records happening once.

---

## 5. What no amount of engineering in this repository can close

Recorded so that the remaining distance is not mistaken for a backlog.

| Gate | Why it is not an engineering task |
| --- | --- |
| Independent security review | It is independent. Intake rejects any reviewer whose name or organisation matches a project principal. |
| Physical hardware | There is no machine. Every result in this project is QEMU with software rendering. |
| Production signing | A production key, a second signer, and controlled access. §19 forbids the key entering this repository. |
| Owner approvals | A decision, by a person with the authority to make it. |

Four of the six outstanding REQUIRED gates. The other two — update and
rollback — are engineering, and §4 says what they need.

---

## 6. Status

**PHASE 5 — RELEASE CANDIDATE BLOCKED.**

Not "ALPHA HARDENED", because the reference-suite gate is not clean. Not
"RELEASE GATE READY", because six required gates are outstanding and four of
them cannot be closed from inside this repository.

The Alpha Release Candidate `e906a487` remains **READY as an Alpha Release
Candidate and nothing else**, exactly as Phase 4 left it. Phase 5 has not
changed that verdict and has not touched that artifact.
