<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Shared test contract

> **VISUAL OR SHELL DEVELOPMENT**
> **NOT RELEASE QUALIFIED**
> **DO NOT MERGE INTO MAIN WITHOUT AN EXPLICIT PRODUCTION INTEGRATION DECISION**
> **GNOME REMAINS THE SUPPORTED FALLBACK**

Smithay and libmutter are compared against **one** contract, measured the same
way, or they are not compared at all. Two arms tested to two standards produce a
preference, not a decision.

The contract is machine-readable in
`visual-v4/contract/shared-test-contract.json`: 31 gates, 8 of them mandatory,
across two arms. `visual-v4/tools/v4.py` is the only thing that reads it and
computes a verdict.

## Result states

C1 permits seven, and only one of them satisfies a gate:

| State | Satisfies a gate | Means |
|---|---|---|
| `PASS` | **yes** | measured, and it worked |
| `FAIL` | no | measured, and it did not work |
| `PARTIAL` | no | measured, and it half worked — which is a failure with detail |
| `NOT_IMPLEMENTED` | no | the arm has nothing to measure |
| `NOT_AVAILABLE` | no | the environment cannot support the measurement |
| `NOT_RUN` | no | measurable here, not executed |
| `INCONCLUSIVE` | no | measured, and the measurement cannot be trusted |

There is deliberately no state meaning "would pass". The distinction that does
carry information is `NOT_AVAILABLE` against `NOT_RUN`: the first is a
statement about the host and is cleared by different hardware, the second is a
statement about effort and is cleared by doing the work.

## The eight mandatory gates

C7 names seven blockers. This contract has eight, because a session lock and a
session unlock fail independently and a lock that cannot be unlocked is not half
a success.

| Gate | C7 blocker |
|---|---|
| `secure-session-lock` | secure lock and unlock |
| `pam-unlock` | secure lock and unlock |
| `input-method-v2` | usable input methods |
| `screen-sharing-portal-pipewire` | screen sharing |
| `orca-session` | basic Orca accessibility |
| `gpu-rendering` | GPU rendering |
| `application-launch` | application launch |
| `two-output-presentation` | multi-output presentation |

A framework cannot be selected while any of these is not `PASS`, whatever it
scores.

## What each of the three hardest gates actually requires

These three are the ones most easily claimed and least easily earned, so the
contract states the bar rather than leaving it to a reviewer.

**Screen sharing** passes only when an external client receives actual frames
through PipeWire after explicit portal approval. A negotiated stream carrying no
buffers is a failure, not a partial pass.

**Input methods** pass only when real non-Latin text reaches a real application.
Advertising `text-input-v3` is a protocol advertisement, and the evidence rules
reject protocol advertisement presented as functionality.

**Accessibility** passes only when Orca, or an equivalent assistive technology,
actually navigates the shell. The evidence rules reject labels presented as Orca
evidence, so an accessible-name audit does not satisfy this gate.

## Enforced structurally, not by review

`visual-v4/tools/v4.py` refuses, as errors rather than warnings:

- a `PASS` with no evidence reference — a gate cannot pass on assertion
- duplicate results for one gate
- a missing result, so an absent run cannot read as an absent problem
- a state outside the seven
- a result for a gate the contract does not define
- a dropped arm

`tests/visual_v4/test_framework_closure.py` mutation-tests each of those guards
by breaking it and asserting the harness objects. It also asserts the property
the whole contract exists for: an arm passing everything except one mandatory
gate still scores in the seventies and is still refused.
