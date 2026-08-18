# Phase 6 baseline — the Phase 5 technical state, frozen and measured

Written **before any Phase 6 change**. Machine-readable form: `baseline.json`.

Nothing in this document is copied forward from a previous record. Every digest
was recomputed from the bytes on the reference builder and compared against
what the build itself wrote. The script that did it is
`freeze-baseline.sh`; its output is `freeze.log`, verbatim.

That distinction matters more here than anywhere else in the project. A baseline
assembled by transcribing an earlier baseline proves that two documents agree,
which is not the property anyone needs. The property needed is that **the bytes
still hash to what the build claimed**, and that is what was measured.

---

## 1. Two artifacts, and which one is the subject

Phase 6 binds its evidence to **`e906a48793d7`**, the Phase 4 Alpha Release
Candidate. The Phase 5 build `e501218f2fe0` is its **counterpart**, the N+1 that
makes update and rollback askable questions.

They are not interchangeable, and the reason is not preference:

| | `e906a48793d7` — subject | `e501218f2fe0` — counterpart |
| --- | --- | --- |
| Installation medium | **an ISO exists** | **none** |
| Installation evidence | encrypted install, `findings: []` | none |
| Login / first boot | `g1`, `g10` | none |
| Voice | `voice-phase3-b`, 19 stages | none |
| Trust | `g12` / `g13`, both directions | none |
| Persistence | `g2`→`g3`→`g4`, two reboots | none |
| Security scan bound to it | yes, 80 advisories at module granularity | no |
| Role in Phase 6 | the thing being released | the thing being updated to and rolled back from |

The counterpart having no installation medium is decisive on its own. A release
subject that cannot be written to a USB stick cannot be qualified on physical
hardware, cannot be handed to an Alpha tester, and cannot be installed by
anyone. Building an ISO for it would be a day's work and would then leave the
project with an unqualified image wearing a candidate's name — which is
precisely the trap §18 exists to prevent.

**The Phase 4 artifact is untouched, and that is now measured rather than
asserted.** All three of its files hash to exactly what `SHA256SUMS` and
`BUNNY-MANIFEST.json` recorded, and its ISO hashes to
`823d50ca…` — the same value `qualification/phase5/baseline/baseline.json`
recorded before Phase 5 began.

---

## 2. Subject artifact — identity

| | |
| --- | --- |
| Source commit | `e906a48793d74544b39c14cc3e35e0654f5311e2` |
| Image version | `0.3.0-beta.e906a48793d7` |
| Image reference | `localhost/bunny-os-beta:e906a48793d7` |
| Image manifest digest | `sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d` |
| Profile | `beta` |
| `SOURCE_DATE_EPOCH` | `1786986334` |
| Built | 2026-08-17T17:20:25Z |
| Location | `/root/bunny-build-archive/beta-phase4-rc-e906a48793d7-20260818T014208Z` |

| artifact | sha256 | bytes | recomputed |
| --- | --- | ---: | --- |
| `…qcow2-x86_64.qcow2` | `497add9a77db2db02bf2541e85b04b0e285c1833d2c8220d193d0d413a6ce867` | 2 770 075 648 | **matches** |
| `…raw-x86_64.raw` | `a6ee06dcbc0ed3aa22c9ea07c339882eb97c7f16ce906b654c9a1e1119849d46` | 13 758 365 696 | **matches** |
| `bunny-os.oci.tar` | `205a77f1b6cdf33915bce3afceb0914d6af25f97b434cf2128aec04d199b43dd` | 2 962 257 920 | **matches** |

### Installation medium

| | |
| --- | --- |
| Name | `bunny-os-0.3.0-live.e906a48793d7-x86_64.iso` |
| sha256 | `823d50caba35afe72452768affd5f6fa0ac8cfc13c164f0e1bc909fa887ab421` |
| Bytes | 6 100 916 224 |
| Built from | `localhost/bunny-os-live:e906a48793d7` |
| Recomputed | **matches the Phase 5 baseline record** |

This is the medium a physical machine would boot. It is present on the builder
and it hashes correctly, which is the precondition for §7 being runnable at all
the day a machine exists.

---

## 3. Counterpart artifact — identity

| | |
| --- | --- |
| Build id | `e501218f2fe0.1787016937` |
| Source commit | `e501218f2fe0105e5fc92bdf94fd6b3c87d6c470` |
| Image reference | `localhost/bunny-os-beta:e501218f2fe0` |
| Image manifest digest | `sha256:a0454c56c886fca66017908d38837eef3e8cb9989ffa6ba46ce2db1509d9303d` |
| `SOURCE_DATE_EPOCH` | `1787016937` |
| Built | 2026-08-18T02:13:04Z |
| **Installation medium** | **none exists** |

All three of its files also hash to what its own `SHA256SUMS` recorded.

---

## 4. Build inputs — and one thing that has already moved

| | |
| --- | --- |
| Base image as used | `localhost/bunny-os-retained-base:1f08084a…` |
| Base digest | `sha256:1f08084a9a8545bd528641d4fda14e18408dfb1298acda243eaf583cd907a844` |
| Builder image | `sha256:bf9f00d81c5d707830676193041862dbb5bccc88c18a000cdb674311917d1f3e` |
| Builder source commit | `9c525bf1ca341dcac1bf701d5363adabb07be267` |
| Package snapshot | `fedora-44-beta-20260810-tts` |
| Package manifest digest | `fa89f5e28175abf037acb0e83a5a7fa2868b415db12732c2afff98017fb70ada` |
| Tree clean at build | yes |
| Repeated-build comparison performed | **no** |

**The upstream base tag no longer resolves to the digest this artifact was built
from.** `quay.io/fedora/fedora-bootc:44` in the local store today is
`sha256:f51e9dca…`; the artifact's provenance names `sha256:1f08084a…`. Fedora
rebuilds that tag frequently and does not retain old digests.

That is not a defect and it is not new — it is the reason the retention
mechanism exists. What the freeze measures is that **the retained copy is still
present**, as `localhost/bunny-os-retained-base:1f08084a…`. Without it the
subject artifact's most significant input would be unreconstructible, and §19's
tenth blocking condition — artifact identity independently verifiable — would
already be unmeetable.

---

## 5. Reference suite — CLEAN

| | Runs | Tests | Unexplained failures |
| --- | ---: | ---: | ---: |
| Full reference suite | 8 | 5 988 | **0** |
| Installer sub-suite | 5 | 178 | **0** |
| `tests/companion` | 16 | — | **0** |

Root cause found and fixed: host PSI memory pressure reaching the visual slice
through an unpinned signal. Guarded structurally by
`test_slice_host_invariance.py`. Certified at `30f11a6d`, re-verified at
`c923169d` under `psi_avg10` up to 2.02 — twenty times the threshold that used
to break it.

**This gate measures the tree, not the artifact.** It is recorded in the
baseline because it is a required gate, not because it certifies either image.
Phase 6 does not restate it as evidence about `e906a48793d7`.

---

## 6. Security position at freeze

| | |
| --- | --- |
| Bound to | `e906a48793d7` |
| Route | `grype oci-archive:`, `--only-fixed` |
| Database built | 2026-08-17 |
| Granularity recorded | **module** — the conservative reading |
| Distinct advisories | **80** |
| Critical | **8** |
| Dispositions | 80 × `PENDING_REVIEW` |

The same image and the same scanner report 8 Critical at module granularity and
1 at function granularity, because the current database carries
`qualifiers.go_imports` naming the vulnerable functions and the shipped binaries
do not contain them. Phase 6 carries the **conservative** figure forward,
because a Critical disposition has to be argued against the number that is
hardest to argue against.

---

## 7. Update and rollback at freeze

**Update — the product is inert by design.**

* `/etc/bunny-os/update.json` ships `enabled: false`
* its `manifestUrl` is `updates.invalid.bunny-os.example`
* `/usr/share/bunny-os/update-keys/` holds **only `revoked-keys.json`** — no
  trusted key of any kind
* matrix: **NOT_RUN**, 1 PASS of 13

**Rollback — the product passes; the harness did not measure it.**

* `bootc rollback` + reboot goes `e501218f2fe0` → `e906a48793d7`, agreed by the
  per-deployment `os-release`, the kernel command line and `bootc status`
* all five user-state markers survive
* `vm-rollback-test.sh deployment-rollback` had reported PASS for three runs
  that all booted the default deployment; repaired, it now exits 5 `NOT_RUN`
* matrix: **NOT_RUN**, 0 PASS of 5

---

## 8. Performance — the open question, stated as it stands

A **1.27 percentage-point** unexplained regression in `gnome-shell` idle CPU
(0.80 % at `7edd3fd` → 2.07 % at the RC).

The poller hypothesis is **refuted**: `/proc` reads measure 0.006 % of one core,
two hundred times too small. The surviving candidate is redraw cost under the
software renderer.

Every performance figure this project holds was measured under **llvmpipe**.
None of it transfers to a real GPU, and Phase 6 does not claim it does.

---

## 9. External gates open at freeze

| Gate | State | Why no repository change closes it |
| --- | --- | --- |
| Independent security review | NOT_DONE | It is independent. Intake rejects a reviewer matching a project principal. |
| Physical hardware | NOT_RUN | There is no machine. Every result is QEMU with software rendering. |
| Production signing | NOT_DONE | Needs a production key; §12 forbids it entering this repository. |
| Second signer / owner approvals | NOT_DONE | Needs a second person. |
| Alpha user validation | NOT_RUN | Needs users. |

---

## 10. Known limitations carried in

Eleven, L1–L11, as recorded in `qualification/phase5/baseline/baseline.json` and
`KNOWN_LIMITATIONS.md`. Phase 6 does not close any of them by restating them.

---

## 11. What this freeze establishes

1. Both artifacts are byte-intact and hash to their own records.
2. The subject artifact's installation medium exists and is intact.
3. The subject artifact's base input is still reconstructible from the retained
   copy, although the upstream tag has moved on.
4. The counterpart artifact has **no** installation medium, which is why it is
   not the subject.
5. HEAD (`0d5381c6`) is a tree from which no artifact was ever built, and no
   Phase 6 claim attaches to it.
