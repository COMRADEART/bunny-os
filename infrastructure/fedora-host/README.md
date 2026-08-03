<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Fedora qualification host

> **This directory provisions measurement infrastructure. It qualifies no Bunny
> OS artifact, satisfies no prerequisite, and changes no release result.**
> Stable release remains **NO-GO**. Pilots remain **BLOCKED**.

Bunny OS qualification stalled on a host that could not perform the measurements
being asked of it. Visual V4 recorded five gates as `NOT_AVAILABLE` because the
machine had no DRM device and rendered through `llvmpipe`; two of those five are
mandatory, so no framework could be selected however much of the remaining work
was done there.

This directory exists so that the next host is checked *before* it produces
anything, rather than after.

## The readiness gate

```bash
python infrastructure/fedora-host/scripts/collect-environment.py \
    --environment-id FQH-20260803-01 --operator "<name>" --role host \
    --output /var/lib/bunny-qualification/environments/FQH-20260803-01/environment.json

python infrastructure/fedora-host/scripts/host-readiness-gate.py \
    --environment /var/lib/bunny-qualification/environments/FQH-20260803-01/environment.json
```

26 conditions, **all mandatory**. There is no warning tier, because a warning is
how a missing mandatory condition becomes a footnote. `READY` exits 0; `BLOCKED`
exits 2.

The report is validated against `host-environment.schema.json` **before** any
condition reads it. The conditions index and call methods on the document freely,
so a report with the right keys and the wrong types could raise from inside a
lambda — and a traceback is the one outcome a gate must never produce, because a
crash is not a refusal and a caller cannot tell them apart. Validation fails
closed: if `jsonschema` is unavailable the gate refuses rather than skipping.

Three refusals matter more than the rest, because each has an attractive-looking
substitute:

| Substitute | Why it is refused |
|---|---|
| `llvmpipe` | renders correctly and proves nothing about the hardware path |
| two nested windows | only connected DRM connectors count as outputs |
| `swtpm` | proves the software path, never the machine |

A fourth was found by running the gate against a host that had to fail it. WSL
advertises a Vulkan device named `Microsoft Direct3D12 (NVIDIA GeForce RTX 4050
Laptop GPU)` while OpenGL falls back to `llvmpipe` and `/dev/dri` does not exist.
The name contains no software-rasteriser marker, so a substring check accepted
it. The gate now requires a Vulkan device to be backed by a real DRM card node
and rejects translation layers by name. `test_a_translated_vulkan_device_is_refused`
keeps it that way.

## The gate was validated by making it refuse

The tests build an ideal host that satisfies every condition, then break one
thing at a time and assert the gate stops — 42 tests, including malformed reports
of every shape, which block rather than crash, and exit codes, because a gate
that prints `BLOCKED` and exits 0 is a gate a caller can ignore.

The gate was additionally run against the WSL2 development host, which it
correctly refused at **8 of 26**:

```text
BLOCKED: host is virtualised (wsl)
BLOCKED: /dev/dri is absent
BLOCKED: renderer is llvmpipe (LLVM 22.1.8, 256 bits), a software rasteriser
BLOCKED: 0 connected output(s); 2 are required, and nested windows are not outputs
BLOCKED: no physical TPM 2.0
```

That refusal is retained as the negative control in
`evidence-template/negative-control/`. A gate nobody has watched refuse is a gate
nobody has checked.

## The condition that used to be typed

`git-byte-roundtrip` is mandatory, and until `verify-git-byte-policy.py` existed
the collector wrote `null` for it and the checklist asked a human to change that
to `true`. One mandatory condition was therefore satisfiable by typing a word —
the condition guarding the property that PR #20 was written to protect.

The script now runs the guard and writes the field itself. It writes `false` as
readily as `true`, which is the outcome a hand-edit would never produce, and the
checklist no longer contains the instruction. `test_the_checklist_no_longer_asks_for_a_hand_edit`
keeps it that way, because a verifier nobody is told to run leaves the hand-edit
in place.

It also checks that the invalidated `physical-hardware` record is still
invalidated and still wrong, so a host that quietly re-digested it cannot pass
the remaining checks.

## The three roles

One machine performs several programs, and the evidence must never blur them.

| Role | What it is | What it may produce |
|---|---|---|
| `host` | the Fedora workstation | V4 measurements, Orca sessions, PipeWire capture, multi-display and GPU results |
| `vm-qualification` | disposable KVM guests | Programs E, F, G — encryption, SELinux, update, rollback, recovery |
| `physical-target` | the machine itself, installed | Program I only |

`role` is a required field of the environment report and the readiness gate
refuses a report whose role is not `host`.

**A VM result never enters a physical cell**, including a VM that ran on the
physical qualification host. That is the distinction the invalidated
`physical-hardware` record already demonstrates the cost of getting wrong.

## Files

| Path | Purpose |
|---|---|
| `host-environment.schema.json` | what a candidate host is, as data |
| `host-readiness.schema.json` | the gate's output |
| `scripts/collect-environment.py` | observes the host; infers nothing |
| `scripts/host-readiness-gate.py` | the 26 mandatory conditions |
| `scripts/verify-git-byte-policy.py` | measures the byte policy and records its own result |
| `scripts/retention-manifest.py` | manifests retained artefacts; refuses secret-bearing ones |
| `scripts/reset-test-state.sh` | scope-aware, prefix-limited cleanup |
| `tests/` | 71 tests, mostly refusals |
| `PACKAGE_MANIFEST.md` | the toolchain, and how absence is recorded |
| `OPERATOR_CHECKLIST.md` | the order to do things in |
| `SECURITY_BOUNDARY.md` | what must never reach this repository |
| `STORAGE_POLICY.md` | where multi-gigabyte things live, and why not here |
| `RESET_PROCEDURE.md` | what a reset covers per scope |

## What is not here

`FQH-5` — the measured host evidence — is absent, because no Fedora host has been
provisioned. The environment report, readiness result and package inventory for a
real machine are committed only once one exists.

The reports under `reports/` are generated and currently record `NOT_RUN`
throughout. They describe what will be measured, not what has been.
