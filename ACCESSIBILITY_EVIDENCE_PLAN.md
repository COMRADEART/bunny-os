<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Accessibility evidence plan

Date: 2026-07-30
Current state: **0 of 17 flows driven. No assistive-technology session has ever been
run against Bunny OS.**

```text
$ python scripts/release.py validate-accessibility-evidence
accessibility: 0 passing, 0 failing, 17 not run of 17 flows
assistive technologies exercised: none
  critical flows unresolved: disk-selection, encryption,
    keyboard-only-installation, login, recovery, recovery-key-display,
    screen-reader-installation
  no independent accessibility review is delivered; the project cannot be the
    party that decides its own interfaces are usable
BLOCKED
```

## The seventeen flows

The first five and two others are `critical`: each is required to own or recover the
machine, and no other flow's success compensates for one of them failing.

| # | Flow | Severity if it fails | Needs |
|---|---|---|---|
| 1 | `keyboard-only-installation` | **critical** | an installer ISO |
| 2 | `screen-reader-installation` | **critical** | an installer ISO |
| 3 | `disk-selection` | **critical** | destructive; must be unambiguous |
| 4 | `encryption` | **critical** | passphrase entry and confirmation |
| 5 | `recovery-key-display` | **critical** | the only route back in |
| 6 | `first-run-setup` | high | |
| 7 | `login` | **critical** | includes the LUKS prompt before any session |
| 8 | `launcher` | high | |
| 9 | `settings` | high | |
| 10 | `approval-centre` | high | where a user grants a Bunny action |
| 11 | `update` | high | |
| 12 | `rollback` | high | used when the system already misbehaves |
| 13 | `recovery` | **critical** | used when the system will not boot |
| 14 | `diagnostics-export` | medium | needed to get help |
| 15 | `high-contrast` | medium | |
| 16 | `text-scaling` | medium | |
| 17 | `reduced-motion` | medium | |

## What each run must record

| Field | Required |
|---|---|
| `assistiveTechnology` and `assistiveTechnologyVersion` | yes, and the version must contain a digit |
| `environment` | one of `physical-hardware`, `virtual-machine`, `installed-system`, `live-image` |
| `imageDigest` | yes — a result that does not name what it tested cannot be attributed to a build |
| `operator`, `operatorIsDailyUser` | yes; whether they are a daily user materially strengthens the finding |
| `startedAt`, `completedAt` | yes |
| `steps` | the steps actually attempted |
| `result` | `PASS`, `FAIL`, `PARTIAL` or `NOT_RUN` |
| `failureSeverity` | required for any `FAIL` or `PARTIAL` |
| `evidenceReference` | optional; media only with consent and completed redaction |

## Five refusals

| Refused | Reason |
|---|---|
| `source-inspection` as an environment | it is not an environment; the matrix already refuses a source-inspection pass |
| a `PASS` with no recorded steps | a result without steps is an assertion |
| a `NOT_RUN` carrying steps | a flow that was partly driven is `PARTIAL` |
| media without consent, or with redaction pending | an accessibility recording shows a person using a computer |
| an unversioned assistive technology | "tested with a screen reader" is not a finding |

Two further rules:

- A `PASS` carrying a failure severity is refused: a pass with a failure is a
  partial.
- A flow driven twice keeps its **worst** result. A later pass with a different
  assistive technology does not erase an earlier failure.

## Consent and redaction

Media involving a person requires that person's explicit consent **and** a completed
redaction pass. Faces, names, hostnames and personal file paths are removed before
delivery. `parse_flow_result` refuses a referenced artifact without both.

The project will not accept media the operator has not agreed to publish.

## Why a project self-assessment is not enough

Static accessibility tests pass and are explicitly not sufficient.
`release/matrix.py` refuses a source-inspection pass in the accessibility matrix,
and `release/accessibility.py` requires `independentReviewComplete` even when all
seventeen flows pass.

The project can drive its own flows and should — doing so would produce seventeen
real results and probably a list of failures worth fixing before a reviewer sees
them. It cannot be the party that decides its own interfaces are usable by people
whose needs it does not share.

## The two flows the project cannot reach

`keyboard-only-installation` and `screen-reader-installation` happen before an
installed system exists. Both need an installer ISO plus either physical hardware or
an interactive VM session. The project has neither built the ISO nor acquired the
hardware, so both are recorded as not run rather than inferred from the others.

## Suggested order of attack

1. **Build the live ISO.** That alone makes flows 1–5 reachable in a VM and they are
   five of the seven critical ones.
2. **Drive flows 7–17 against an installed system** with Orca on GNOME 50. Eleven
   flows, no hardware needed beyond a VM.
3. **Commission the independent review** with whatever the project found already
   fixed. `reviews/accessibility/REQUEST.md` is ready to send.
4. **Acquire hardware** for the boot-time flows and for anything the VM cannot
   reproduce.

Step 2 is the largest single reduction in this project's accessibility risk and
needs nothing the project does not have.

## Recording results

```sh
# edit operations/data/accessibility-evidence.json, then
python scripts/release.py validate-accessibility-evidence
python scripts/release.py accessibility-evidence-plan
```

## Consequences while it stays empty

- The `Accessibility` evidence category records `NOT_RUN` and blocks.
- `accessibility-evidence` reports `PENDING_EXTERNAL_REVIEW`.
- The Accessibility protected approval is pending.
- `gate-stable-release` reports `NO-GO`.

## Evidence

- `operations/data/accessibility-evidence.json` — 17 flows, all `NOT_RUN`
- `release/accessibility.py` — the model
- `docs/ACCESSIBILITY.md` — the design intent
- `ACCESSIBILITY_QUALIFICATION_REPORT.md` — the matrix position
- `reviews/accessibility/REQUEST.md` — the review request
- `tests/accessibility_evidence/` — 39 tests
