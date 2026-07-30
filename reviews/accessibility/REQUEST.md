<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Independent accessibility review — request

This is the review where being wrong harms a person rather than leaving a box
unticked. An inaccessible encryption prompt or recovery tool locks somebody out
of their own machine, permanently, with no recourse.

Bunny OS has **zero** runtime accessibility evidence. Seventeen essential
workflows have never been driven with assistive technology. Static tests pass and
`release/matrix.py` refuses to accept a static pass in the accessibility matrix,
for exactly this reason.

## Exact scope

Seventeen workflows, in the order they matter. The first five are load-bearing:
a user who cannot complete them cannot own the machine.

| # | Workflow | Why it matters |
|---|---|---|
| 1 | Keyboard-only installation | No mouse, no installation |
| 2 | Screen-reader installation | Includes disk selection, which is destructive |
| 3 | Disk selection | Choosing the wrong disk destroys data |
| 4 | Encryption passphrase entry and confirmation | Getting this wrong locks the user out |
| 5 | Recovery-key display and recording | The only route back in after a forgotten passphrase |
| 6 | First-run setup | Account creation, privacy choices |
| 7 | Login | Including at the LUKS prompt before any session exists |
| 8 | Bunny launcher | The primary interaction surface |
| 9 | System settings | |
| 10 | Approval centre | Where a user grants or refuses a Bunny action |
| 11 | Update | |
| 12 | Rollback | Used when the system is already misbehaving |
| 13 | Recovery | Used when the system will not boot |
| 14 | Diagnostics export | Needed to get help |
| 15 | High contrast | |
| 16 | Text scaling | |
| 17 | Reduced motion | |

**In scope:** whether a user of each named assistive technology can complete each
workflow **unaided**, and what happens when they cannot.

**Out of scope:** aesthetic judgements; WCAG conformance statements for a desktop
OS (the criteria were written for the web and the mapping is contested — say what
is broken and for whom, and cite WCAG where it genuinely applies); anything
requiring hardware the project cannot supply.

## Commit

- **Evidence baseline commit:** `80df25b09f6578276d18c8a82f15c47dd8959740`.
- **Your scope commit:** the commit you are given. Record it as `scopeCommit`.

## Artifacts

| Artifact | What it is |
|---|---|
| `docs/ACCESSIBILITY.md` | The design intent |
| `ACCESSIBILITY_EVIDENCE_PLAN.md` | The seventeen workflows, the required recordings, and the redaction rules |
| `operations/data/accessibility-evidence.json` | The evidence record. Currently every workflow is `NOT_RUN`. |
| `installer/` | The installer, including the disk-selection and encryption screens |
| `shell/`, `ui/` | The session, launcher, settings and approval centre |
| `ACCESSIBILITY_QUALIFICATION_REPORT.md` | The current state: 0 of 14 matrix scenarios resolved |
| `FIRST_RUN_ACCESSIBILITY_REPORT.md`, `ACCESSIBILITY_REPORT.md` | The project's static findings |
| `docs/BUILDING.md` | How to build a bootable image to test against |

**What is not provided:** a booted, installable image. Two of the seventeen
workflows — installer screen reader and the encryption prompt — happen before an
installed system exists and need either physical hardware or an interactive VM
session with the installer ISO. The project has neither built the ISO nor
acquired the hardware. If you can supply the environment, say so; if not, record
those two as not run rather than inferring them from the others.

## Threat model

Not an adversary — a set of users the project must not exclude:

1. A blind user with a screen reader, installing on their own machine with no
   sighted assistance.
2. A user with low vision using magnification and high contrast.
3. A user who cannot use a pointing device.
4. A user with a motor impairment for whom timed interactions fail.
5. A user with a vestibular disorder for whom animation causes harm.
6. A user with a cognitive disability for whom an unlabelled destructive action
   is a trap.

The failure that matters most: **a destructive or lock-out action that is
reachable but not comprehensible.** Disk selection and recovery-key recording are
both in that category.

## Questions

1. **Can a screen-reader user complete an encrypted installation unaided**,
   including entering and confirming a passphrase and recording a recovery key?
   Nobody knows. This is the load-bearing question.
2. **Is disk selection safe for a screen-reader user?** Is the target disk
   unambiguously announced, including its size and existing contents, before the
   destructive step?
3. **Is the recovery key readable and recordable** by a user who cannot see it —
   announced in a way that can be transcribed accurately, with a way to have it
   repeated?
4. **Does the LUKS passphrase prompt at boot support assistive technology at
   all?** It runs before any session, and this is where the project's exposure is
   worst.
5. **Can a keyboard-only user reach every control** in the installer, first run,
   settings, and the approval centre — including reaching a control that only
   appears after a state change?
6. **Is the approval centre comprehensible?** A user granting a Bunny action
   needs to understand what they are granting.
7. **Do rollback and recovery work under assistive technology**, given they are
   used when the system is already broken?
8. **Are high contrast, text scaling and reduced motion honoured** across the
   shell, the installer, and the Bunny surfaces — or only in some of them?
9. **What breaks first?** If you have limited time, tell us the single worst
   failure.

## Expected report format

Markdown or PDF, plus a machine-readable record conforming to
`security/reachability/schemas/independent-review-record.schema.json` with
`reviewType: "accessibility"`.

Per workflow, we need:

- the assistive technology and its exact version;
- the environment (VM or physical, image digest, desktop version);
- the operator, and whether they are a daily user of that technology;
- the steps attempted;
- the result: pass, fail, partial, or not run;
- failure severity;
- evidence: recordings or screenshots **only with the operator's consent**, with
  faces, names and personal paths redacted.

`ACCESSIBILITY_EVIDENCE_PLAN.md` gives the required fields. A workflow with no
recorded steps is `NOT_RUN`, and the project's tooling refuses to convert
`NOT_RUN` to `PASS`.

## Severity model

- **critical** — a user of the named technology cannot complete the workflow at
  all, and the workflow is required to own or recover the machine. Installation,
  encryption, recovery-key recording, login, recovery.
- **high** — cannot complete unaided, or can complete only by a route that risks
  data loss.
- **medium** — completable but with significant difficulty; a control is
  unlabelled, mislabelled, or reachable only by an undocumented route.
- **low** — friction; a focus order that is awkward but navigable.
- **informational** — observation.

A `critical` finding here should block a release, and the project has structured
its gates so that it does.

## Expected independence statement

In your own words:

- no employment, contract, consultancy, equity or advisory relationship with
  ComradeArt or Bunny OS beyond this engagement;
- no authorship of the interfaces under review;
- your conclusions are your own and were not edited by the project.

If any operator is a daily user of the assistive technology they tested with, say
so — it materially strengthens the finding, and we would rather know.

## Confidentiality requirements

- The code is source-available; quote it freely.
- **Recordings and screenshots involving a person require that person's explicit
  consent**, and the project will not accept media the operator has not agreed to
  publish. Redact faces, names, hostnames and personal file paths before
  delivery.
- Findings are **not embargoed**. An accessibility failure is not a vulnerability
  and the project would rather it were public and fixed than private and
  outstanding. Publish when you like.

## Prohibited claims

- **"Certified accessible"**, "WCAG compliant", "AA conformant", or any
  conformance badge. This review produces evidence about specific workflows with
  specific technologies.
- **A pass inferred from source inspection.** `release/matrix.py` refuses a
  source-inspection pass in this matrix. If the workflow was not driven, it is
  `NOT_RUN`.
- **A pass for a workflow you could not reach.** The two boot-time workflows may
  be unreachable without hardware. Record them as not run.
- **A generalisation across technologies.** "Screen readers work" is not a
  finding; "Orca 50.2 on GNOME 50 announces the disk-selection list but not the
  disk size" is.
- Any statement that the project is ready for release.

An honest report of seventeen failures is more useful to this project than a
partial pass. There are no users yet, so nothing is at stake in the answer being
bad — and everything is at stake in it being wrong.
