# Phase 6 — External Release Gate Closure, Hardware Qualification & Alpha Validation

## STATUS: **PHASE 6 — EXTERNAL GATES BLOCKED**

---

## 1. Executive summary

Phase 6 closed one required gate, moved two blocking conditions, and found three
things the record had wrong. It did not reach `RELEASE GATE READY` and could not
have: five of the ten blocking conditions need a person or a machine that does
not exist, and they were recorded as unmet **before** any Phase 6 measurement
ran.

**The gate that closed.** Updates are now explicitly `NOT_SUPPORTED` for the
alpha release class — outcome B of §10 — decided by a named accountable owner,
bound to an artifact digest, with an expiry and a review condition. The refusal
was **measured**, not asserted: 18 of 18 checks against the artifact's own image,
with a negative control that failed as it was required to.

**What was found that the record had wrong.**

1. **The artifact is unsigned.** Not development-signed. `find` across the whole
   build tree and the ten-build archive returns **zero** `.sig` files. The build
   scripts sign only when `BUNNY_MEDIA_SIGNING_KEY` is set; it was not, and
   nothing failed or warned. "Development-signed" has been carried since Phase 4
   and describes a drill against constructed inputs, not this artifact.
2. **Phase 5's security evidence was wrong about which binaries carry the
   vulnerable code**, and the probe that produced it could only ever have given
   one answer. `strings … | grep -q` under `set -o pipefail` reports NO on a
   *match*: grep exits at the first hit, strings dies of SIGPIPE, and pipefail
   promotes 141 to the pipeline status. Reproduced with a control.
3. **The Phase 5 build has no installation medium.** Only qcow2, raw and an OCI
   archive. That is decisive for which artifact Phase 6 could bind to.

**What Phase 6 deliberately did not do.** It did not mark a single update-matrix
scenario `NOT_APPLICABLE`. That move was available, it would have turned a
blocking row green, and it was refused: the matrix records what was executed,
and nothing was.

`python scripts/release.py gate --kind qualification-candidate` produces
**byte-identical** output at `0d5381c6` and at `dc60d33b` — same sha256
`d1fd9ff5…`, verified by cloning the repository at both commits and diffing,
with a control that flips one row to confirm the comparison can detect a
change.

**The Phase 4 Alpha Release Candidate `e906a487` remains READY as an Alpha
Release Candidate and nothing else.** Its digests were re-verified from the
bytes; nothing was relabelled.

---

## 2. Phase 5 baseline

Frozen before any Phase 6 change, and **measured rather than transcribed** —
every digest recomputed from the bytes on the builder and compared with what the
build itself recorded. `qualification/phase6/baseline/BASELINE.md`,
`baseline.json`, and the verbatim `freeze.log`.

| | |
| --- | --- |
| Phase 5 final commit | `0d5381c6` |
| Phase 5 status | RELEASE CANDIDATE BLOCKED |
| Reference suite | CLEAN — 8 runs × 5 988 tests, 0 unexplained failures |
| Security | 80 advisories, 8 Critical, all `PENDING_REVIEW` |
| Update | inert by design; matrix 1 PASS of 13 |
| Rollback | product PASS; harness NOT_RUN |
| Known limitations | 11, L1–L11 |

**Every digest matched.** The Phase 4 artifact is untouched — now measured, not
asserted.

**One thing the freeze found that no record held:** the upstream base tag
`quay.io/fedora/fedora-bootc:44` no longer resolves to the digest the subject
artifact was built from (`sha256:1f08084a…`); it now resolves to
`sha256:f51e9dca…`. The retained local copy is present and is the only thing
keeping that input reconstructible.

---

## 3. Artifact inventory

| | Subject | Counterpart |
| --- | --- | --- |
| Name | Alpha Release Candidate | Phase 5 build |
| Commit | `e906a48793d7…` | `e501218f2fe0…` |
| Image digest | `sha256:c87a6616…` | `sha256:a0454c56…` |
| Installation medium | **ISO, `823d50ca…`** | **none** |
| Journey evidence | installation, encryption, login, voice, Trust, persistence | none |
| Role | the thing being released | the N+1 for update and rollback |

The counterpart having no installation medium settles it. A release subject that
cannot be written to a USB stick cannot be qualified on hardware, cannot be
handed to a tester, and cannot be installed by anyone.

---

## 4. Security review package

`qualification/phase6/security/REVIEW_PACKAGE.md`, self-checking via
`verify_package.py` — which re-derives every count, confirms nothing was quietly
dispositioned, asserts the package's central claim, and **names the three claims
it cannot close** rather than skipping them silently.

**The exposure question is now measured per Critical**, where Phase 5 recorded
"not determined for this scan". Two dimensions decide a Go finding and Phase 5
measured one:

| | `/usr/bin/podman` | `/usr/bin/skopeo` |
| --- | --- | --- |
| `golang.org/x/crypto` | **v0.53.0** — past the v0.52.0 fix | v0.46.0 — vulnerable |
| `x/crypto/ssh*` packages linked | **28, incl. `knownhosts`** | **0** |

Seven of the eight Criticals fail one of the two tests on every binary — and
they fail **different** ones. No binary is simultaneously on a vulnerable
version and carrying the affected code.

**One survives both:** `GHSA-p77j-4mvh-x3m3`, gRPC **v1.72.2** in
`/usr/bin/podman`, below the v1.73.0 fix, with all three named symbols
(`Server.Serve`, `Server.ServeHTTP`, `Server.handleStream`) linked. That is
exactly and only what the binary-reading scan reported. The reviewer's question
is therefore concrete: **does anything Bunny ships cause podman to serve gRPC?**

The project offers **no disposition**. All 80 rows remain `PENDING_REVIEW`, and
the tooling has no code path that could emit anything else without a completed
review.

**Stated as outstanding rather than glossed:** the version-and-symbol analysis
was done for the 8 Criticals and **not** for the 19 Go High findings. Given what
it changed about the Criticals, it will likely move several of those rows.

---

## 5. Independent review result

**NOT_RUN.** No reviewer exists. Intake (`validate-independent-reviews`) rejects
any reviewer matching a project principal and binds the record to a commit.

An internal re-scan is not an independent review and none is presented as one.

---

## 6–8. Physical hardware, renderer and voice results

**NOT_RUN, all three.** There is no machine. Every result this project has ever
produced is QEMU with software rendering.

What Phase 6 added is the thing §17 requires and that was missing: three
journeys with **`expectation.json` written before execution** — 23 steps across
boot chain, renderer and voice — committed while no machine exists, which is the
only moment an expectation can be written honestly.

Each encodes a defect this project already found somewhere else: a live boot
recorded as an installation result; an llvmpipe number presented as a real-GPU
result; a fallback that destroys the preference it fell back from; a loopback
mistaken for a microphone; a player resolved to a sibling of a multi-call
binary; cancellation measured only by its effect; a permission prompt drawn but
unpressable; denial tested after grant.

A well-specified plan is not progress against a gate that needs hardware, and it
is not offered as such.

---

## 9. Update trust decision

**Outcome B — updates are `UNSUPPORTED` for the alpha release class.**

Decided 2026-08-18 by Raviteja Allamsetti, product and security owner.
`UPDATE_TRUST_ARCHITECTURE_DECISION.md`;
`operations/data/update-support-policy.json`; admitted by
`python scripts/release.py update-support-policy`.

A was unavailable — an update trust root needs a production key and the ceremony
needs a second person. C leaves the gate blocked and the product's behaviour
undescribed; users get no updates either way, the only difference being whether
anyone said so.

All seven §10 questions are answered. The two that matter most:

* **Root of trust: none.** The trust store holds one file, `revoked-keys.json`,
  and zero `.pem` files.
* **Rotation: no path.** Trust is conferred by a `.pem` inside the image, so
  distrusting a compromised key requires an OS update — the mechanism that is
  unavailable. Named as a design gap that must be resolved *before* any key is
  ever issued.

`release/updatepolicy.py` refuses a policy whose approver is a role, which binds
to a branch rather than a digest, which answers a question too briefly to be
checkable, which cannot expire, or **whose negative control passed**. Thirty
tests, each exercising one refusal.

---

## 10. Update results

**Gate: `NOT_SUPPORTED`. Matrix: `NOT_RUN`, 1 PASS of 13, unchanged and
unwaived.**

The refusal was qualified against the artifact's own image, in a container with
no network: **18 of 18 checks AS_INTENDED**.

* shipped configuration refuses `check`, `stage` and `install` — `not_configured`
* the trust store holds zero keys; any manifest is `unknown_key`
* a revoked key is refused before the key lookup
* **negative control:** a manifest signed by a key installed into the image's own
  store **verifies** — without this, every refusal above is equally explained by
  a missing `openssl`
* altering one field of a signed manifest gives `bad_signature`
* with a valid key installed, the disabled configuration **still** refuses — two
  independent controls
* enabled with no reachable source: `download_failed`, closed
* downgrade and replay: `rollback_attack`

**Control for the instrument:** planting a key and enabling updates flips 7 of
the 18 to UNEXPECTED, and leaves the five checks that do not depend on an empty
store alone. The probe can fail; it was not failing here because there was
nothing to fail on.

**The probe caught itself.** Its first version asked `status` after
`check`/`stage`/`install`, read the leftover failure record, named
`configured: true` in its expectation and asserted only the exit code — passing
while measuring something else. Fifth instance of that shape in this project.
`A0` now asks first and asserts the value; the ordering is itself a test.

Two things found that were in no record: `status` returns the stored outcome
when one exists and only computes `idle` when none does, so it answers two
different questions depending on when it is asked; and `_verify_signature` is
the **last** call in `_validate_manifest`, so a manifest's fields are parsed and
compared before it is known to be authentic — bounded, unreachable here, and
handed to the reviewer rather than left to be found.

---

## 11. Rollback results

**Product: PASS. Matrix: NOT_RUN.** Blocking condition 8 — that the evidence
binds to the intended artifact chain — is **met**.

`bootc rollback` + reboot goes `e501218f2fe0` → `e906a48793d7`, agreed by the
per-deployment `os-release`, the kernel command line and `bootc status`. All
five user-state markers survive.

The harness half remains NOT_RUN and honestly so: `vm-rollback-test.sh
deployment-rollback` had reported PASS for three runs that all booted the default
deployment. Repaired to identify the booted deployment from the kernel's own
`ostree=` argument, it now exits 5 `NOT_RUN` on the same disk.

---

## 12. Production signing

**NOT_RUN, and worse than recorded.**

```
find /root/bunny-os/build/out /root/bunny-build-archive -name '*.sig'
(no results)
```

**Zero signature files**, across the subject artifact, its ISO, and all ten
retained builds. `build-beta-image.sh` and `build-live-image.sh` sign the media
manifest **only when `BUNNY_MEDIA_SIGNING_KEY` is set**; it was not set, nothing
failed, and nothing warned.

On §12's actual requirement the stable path is correct: `sign-stable-rc.py`
re-hashes every artifact against the manifest, **refuses on mismatch**, and signs
artifacts individually — not a tree. But no `STABLE-CANDIDATE.json` exists
anywhere, and the subject artifact uses the other manifest format. **The release
signing path and the artifact being released have never met.**

No production key exists; Phase 5 measured all five register keys refused for
production with four constructed negative controls.

---

## 13. Second approval

**NOT_RUN.** One person. An approval record must name a first signer and a
second reviewer who are different people.

Phase 6 produced several green runs. §13: *"Do not infer approval from a
successful test run."* None of them is an approval.

---

## 14. Alpha-user findings

**NOT_RUN. Testers: 0. Findings: 0.** Unmet, not vacuously met.

The instrument existed and was verified in Phase 5. Phase 6 bound it to a
digest, added the §15 triage taxonomy as a closed vocabulary
(`alpha/triage-schema.json`, where `ENVIRONMENT` requires a measurement and
`ACCEPTED` requires a named person), and rewrote the consent record.

Three consent items are new, and are the ones most likely to change whether
someone agrees to install:

* **it will never be updated** — no mechanism, no key, no path in this release;
* **security fixes will never reach you** — 8 Criticals unremediable in the
  field; remediation means reinstalling;
* **the artifact is unsigned** — authenticity is unverifiable by any means the
  project provides.

---

## 15. Performance findings

**NOT_RUN — and runnable, which is not the same as blocked.** Every other open
item needs a person or a machine; this one needs a VM boot, and it was not run.
The distinction is recorded rather than blurred.

The 1.27-point regression stands unexplained. The poller hypothesis stays
refuted (0.006 % of one core — 200× too small) and is not resurrected. The
measurement set is defined, with the one condition most likely to be skipped
made explicit: **hidden and visible idle measured separately and never
averaged**, because that difference is the only signal that could answer the
question.

---

## 16. Qualification harness status

New qualification logic in Phase 6 carries implementation + tests + recorded
evidence, per §17.

| Instrument | Tests | Evidence |
| --- | ---: | --- |
| `refusal_probe.py` | 12 | run + negative control |
| `release/updatepolicy.py` | 30 | the committed policy |
| `symbol_probe.py`, `exposure_probe.py` | — | `symbols.json`, `exposure.json`, self-checked by `verify_package.py` |
| `verify_package.py` | — | asserts the package's own central claim |

`summarise()` refuses a run that is **missing a required check**, so a probe
narrowed after the fact cannot stay green — and `updatepolicy` refuses a run
whose check count is below what the policy declares, so narrowing the probe
invalidates the policy that rests on it.

`NOT_RUN` remained a real outcome throughout. Nothing was converted from *not
executed* into *passed by absence of failure*.

### Reference suite, certified at the Phase 6 head

On the Fedora reference target, as `bunny`, from an ext4 clone:

    expected commit: 2e01d443e08dcecc715406dbb26ec1df1057b1d4
    checked out:     2e01d443e08dcecc715406dbb26ec1df1057b1d4
    commit assertion: OK
    discovered tests: 6030
    test-count floor: OK (6030 >= 5900)
    Ran 6030 tests in 230.565s   run 1 exit: 0
    Ran 6030 tests in 228.189s   run 2 exit: 0

**2 runs × 6 030 tests, zero failures.** 6 030 is 5 988 plus the 42 tests Phase 6
added. Evidence: `qualification/phase6/certification/verify-2e01d443.log`.

The script asserts the commit it actually checked out and a test-count floor,
because the Phase 5 equivalent once defaulted to `FETCH_HEAD`, ran a different
branch, and reported clean runs of 1 555 tests where the suite has ~6 000.

**Its own defect, found and fixed mid-phase.** Two invocations against different
commits both truncated and appended to one `verify.log`, producing a record
carrying one commit's header above the other's test output. Caught because the
per-run lines did not add up. It now takes a lock directory and **refuses a
concurrent run with exit 6** rather than interleaving, and writes a per-commit
log and done-marker. The refusal was exercised: a second run printed
`REFUSED: another certification run holds …` and did not proceed. **No result
was reported from the contaminated log.**

Repository validation: **PASS**, 16 validators.

**Windows is not the reference target, and this phase re-confirmed why.** A
native Windows run shows `test_provenance_accounts_for_every_selected_tts_byte`
failing by 605 bytes: four `assets/voice/licenses/*` files are `i/lf w/crlf` —
correct in the repository, CRLF only in this working tree. The repository is
right and the checkout is not.

### The evidence-immutability guard protects less than its name suggests

`tests/companion/test_three_d_preservation.py` asserts that no file is added to
an earlier phase's evidence tree. Phase 6 declared `qualification/phase6/` in
its exempt list, exactly as phases 3, 4 and 5 each declared their own — the
maintenance the guard is designed for.

Negative-controlling that edit found something. A file staged under
`qualification/phase5/` **does not fail the guard**, because
`qualification/phase5/` is itself on the exempt list. Staging one under
`qualification/tpm/` does fail it.

The record was cut at `fa49380` and pins **4 676 files across thirteen trees**.
Phase 4's, Phase 5's and now Phase 6's trees are declared later phases and are
**not pinned by anything**. The guard's name promises more than its coverage
delivers.

**This does not weaken any Phase 6 claim, but it does change what supports one.**
The statement that Phase 4 and Phase 5 evidence is unmodified rests on
`git diff 0d5381c6..HEAD -- qualification/phase4 qualification/phase5` returning
empty — not on this test, which would have passed either way.

Recorded as a finding, not fixed. Extending the record to cover phases 4–6 is a
change to a check during a release phase, and the argument for whether those
trees *should* be pinned — they are still being written to — is the same
argument the exempt list's own comments make.

---

## 17. Remaining limitations

1. **Five gates need people or hardware** — independent review, physical
   hardware, production signing, second signer, Alpha testers.
2. **The artifact is unsigned**, and the signing path has never been applied to
   a real build.
3. **44 Critical/High findings are undispositioned**, and cannot be
   dispositioned without an independent review.
4. **The 19 Go High findings lack the version-and-symbol analysis** the 8
   Criticals now have.
5. **`repeatedBuildComparisonPerformed: false`** for the subject artifact —
   condition 10 unmet.
6. **The upstream base tag has moved.** Only the retained local copy keeps the
   artifact's base input reconstructible.
7. **The accessibility matrix carries two FAILs** — the only outright FAILs in
   the project. Phase 6 did no accessibility work.
8. **Independent recovery media: NOT_RUN.** No signed recovery ISO.
9. **The committed-evidence validator tracks candidate `79bb99ddb39d`**, not the
   subject artifact — 26 records agree on a candidate that is not the one being
   released.
10. **The refusal qualification ran in a container, not a booted system.** It
    does not exercise systemd activation, the timer, or a real network stack.
11. **The evidence-immutability guard does not cover phases 4, 5 or 6.** Their
    trees are declared later phases and nothing pins them; the guard's record
    ends at `fa49380`.
12. **The Phase 5 build has no installation medium**, and no journey evidence.
13. **Eleven known limitations L1–L11** carry forward unchanged.

---

## 18. Release-gate matrix

Full matrix with evidence and blocking status:
`qualification/phase6/gates/RELEASE_GATES.md`.

| Gate | Result | Blocking? |
| --- | --- | --- |
| Installation, Encryption, First boot, Login, Voice, Trust, Persistence, Companion, Shutdown | **PASS** | no |
| Reference suite | **PASS** (CLEAN) | no |
| Rollback — product | **PASS** | no |
| Rollback — matrix | **NOT_RUN** | **yes** |
| **Update** | **NOT_SUPPORTED** | no |
| Update — matrix | **NOT_RUN** (unwaived) | no |
| Security findings | **BLOCKED** | **yes** |
| Independent security review | **NOT_RUN** | **yes** |
| Physical hardware | **NOT_RUN** | **yes** |
| Production signing | **NOT_RUN** | **yes** |
| Second signer / approvals | **NOT_RUN** | **yes** |
| Alpha user validation | **NOT_RUN** | **yes** |
| Artifact identity | **CONDITIONAL** | **yes** |
| Independent recovery media | **NOT_RUN** | **yes** |
| Accessibility evidence | **FAIL** | **yes** |
| Licence, Independent reproducibility, Dev signing drill | **PASS** | no |

**Blocking conditions: 3 of 10 met** (6, 7, 8). Conditions 1, 3, 4, 5 and 9 were
recorded unmet **in advance**, at `97aaf208`. **No condition was weakened after
a result was seen. No exception was recorded.**

---

## 19. Artifact identities and digests

**Subject — `e906a48793d7`**

| | |
| --- | --- |
| Commit | `e906a48793d74544b39c14cc3e35e0654f5311e2` |
| Image | `sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d` |
| qcow2 | `497add9a77db2db02bf2541e85b04b0e285c1833d2c8220d193d0d413a6ce867` |
| raw | `a6ee06dcbc0ed3aa22c9ea07c339882eb97c7f16ce906b654c9a1e1119849d46` |
| oci.tar | `205a77f1b6cdf33915bce3afceb0914d6af25f97b434cf2128aec04d199b43dd` |
| ISO | `823d50caba35afe72452768affd5f6fa0ac8cfc13c164f0e1bc909fa887ab421` |
| Base | `sha256:1f08084a9a8545bd528641d4fda14e18408dfb1298acda243eaf583cd907a844` |
| Builder | `sha256:bf9f00d81c5d707830676193041862dbb5bccc88c18a000cdb674311917d1f3e` |
| `SOURCE_DATE_EPOCH` | `1786986334` |
| Signatures | **none** |

**Counterpart — `e501218f2fe0.1787016937`**

| | |
| --- | --- |
| Commit | `e501218f2fe0105e5fc92bdf94fd6b3c87d6c470` |
| Image | `sha256:a0454c56c886fca66017908d38837eef3e8cb9989ffa6ba46ce2db1509d9303d` |
| qcow2 | `b4dd95f3cb3f7d4b4419c120e04e4375f4a176f0fd0a0ee5f2c91ba5de99dcef` |
| raw | `7fadbec459fe9cd92c461db70b676876bd9774c3875c467bbf2b5724245a77f0` |
| oci.tar | `6ea132359756e48e3ff98f941a2c5286537a92210f38581debca4028be556536` |
| Installation medium | **none** |

All re-verified from the bytes on 2026-08-18; `qualification/phase6/baseline/freeze.log`.

---

## 20. Evidence inventory

| Path | What |
| --- | --- |
| `qualification/phase6/baseline/` | BASELINE.md, baseline.json, freeze.log, freeze-baseline.sh |
| `qualification/phase6/conditions/` | the ten blocking conditions, committed first |
| `qualification/phase6/gates/` | the authoritative gate matrix |
| `qualification/phase6/security/` | REVIEW_PACKAGE.md, PIPEFAIL_CORRECTION.md, three probes, verify_package.py, `evidence/` |
| `qualification/phase6/update/` | REFUSAL_QUALIFICATION.md, refusal_probe.py, `evidence/` + negative control |
| `qualification/phase6/hardware/` | HARDWARE_QUALIFICATION.md, three `expectation.json` |
| `qualification/phase6/alpha/` | ALPHA_VALIDATION.md, triage-schema.json |
| `qualification/phase6/signing/` | SIGNING_POSITION.md |
| `qualification/phase6/performance/` | PERFORMANCE_FOLLOW_UP.md |
| `qualification/phase6/certification/` | the reference-suite run at the Phase 6 head |
| `UPDATE_TRUST_ARCHITECTURE_DECISION.md` | the §10 decision |
| `operations/data/update-support-policy.json` | machine-readable policy |
| `release/updatepolicy.py` | the admission path |
| `tests/update/` | 42 new tests |

Phase 4 and Phase 5 evidence is **unmodified**. The one correction to Phase 5's
security evidence is a correction *record* in Phase 6's directory naming what it
corrects; Phase 5's files are untouched.

---

## 21. Final disposition

# PHASE 6 — EXTERNAL GATES BLOCKED

**Ten gates block.** They divide as follows, and the division matters more than
the total:

| Group | Gates | Closable here? |
| --- | --- | --- |
| Need a person or a machine | independent security review, physical hardware, production signing, second signer / approvals, Alpha validation | **no** |
| Downstream of the review | security findings — measured, but only a reviewer can disposition them | **no** |
| Engineering, out of scope this phase | rollback matrix, independent recovery media | yes |
| A recorded defect | accessibility — the project's only outright `FAIL` | yes |
| Artifact identity | `CONDITIONAL` — needs a repeated-build comparison for this artifact | yes |

Not `CONDITIONAL RELEASE CANDIDATE`: that would require the conditions to be
nameable and bounded, and "no reviewer, no machine, no key, no second person, no
testers" is not a condition list, it is the absence of a release process.

Not `RELEASE GATE READY`, and not `STABLE RELEASE`.

**The Phase 4 Alpha Release Candidate `e906a487` remains READY as an Alpha
Release Candidate and nothing else.** Phase 6 re-verified its digests, bound its
evidence to it, and changed its verdict in exactly one respect: it is now known
to be **unsigned**.

---

## The standard, and whether it was met

> The product was repeatedly stronger than the measurement systems used to
> certify it. Phase 6 must not repeat that mistake.

It repeated it once and caught it. The refusal probe's first version passed
while measuring the wrong thing — the same shape as the four harnesses before
it — and was caught by reading the observed column instead of the verdict
column.

It found the mistake twice more in inherited work: a shell idiom that could only
answer "no", and an artifact described as signed that carries no signature.

Against the eight-point standard:

| | |
| --- | --- |
| The artifact is known | **yes** — re-verified from the bytes |
| Independently reviewed | **no** — no reviewer |
| Runs on real hardware | **no** — no machine |
| Security posture explicitly dispositioned | **no** — measured, not dispositioned; that is the reviewer's act |
| Can be signed and verified | **no** — no key, and nothing has been signed |
| Update behaviour securely qualified or explicitly unsupported | **yes** — explicitly unsupported, and the refusal measured |
| Alpha users have tested the identified artifact | **no** — no testers |
| Every PASS backed by evidence measuring the thing claimed | **yes**, and two inherited *claims* failed that test and were withdrawn — no formal gate PASS was withdrawn, because neither claim had ever been one |

One of eight closed in this phase. The value of the other seven is that they are
now unmet **for stated, specific reasons**, against an artifact whose identity
was measured rather than assumed.
