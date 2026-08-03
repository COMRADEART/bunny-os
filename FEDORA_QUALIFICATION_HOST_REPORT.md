<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Fedora qualification host report

> **This provisions qualification infrastructure only. It qualifies no Bunny OS
> artifact, satisfies no prerequisite, and changes no release result.**
> Stable release remains **NO-GO**. Pilots remain **BLOCKED**.

## Status

| Item | State |
|---|---|
| Provisioning infrastructure | **COMPLETE** (FQH-1 … FQH-4) |
| Fedora host provisioned | **NOT_RUN** — no machine exists |
| Measured host evidence (FQH-5) | **NOT_RUN** — cannot precede the machine |
| Visual V4 measurement | **BLOCKED** — waiting on the host |
| Programs E, F, G, H1 | **NOT_RUN** — waiting on the host |
| Program I | **NOT_RUN** — rehearsal not begun |

## Why this exists

V4 stalled on a host that could not perform the measurements being asked of it.
Five gates were recorded `NOT_AVAILABLE` because the machine had no DRM device
and rendered through `llvmpipe`; two of those five are mandatory under C7, so no
framework could be selected however much of the remaining work was done there.

Nothing in the tooling said so until somebody went looking. The readiness gate
exists so the next host is checked before it produces anything.

## The gate

26 conditions, **all mandatory**. No warning tier — a warning is how a missing
mandatory condition becomes a footnote. `READY` exits 0, `BLOCKED` exits 2.

Three refusals carry most of the weight, because each has a plausible substitute:

| Substitute | Refusal |
|---|---|
| `llvmpipe` | renders correctly, proves nothing about the hardware path |
| two nested windows | only connected DRM connectors count as outputs |
| `swtpm` | proves the software path, never the machine |

## A defect found by making the gate refuse

The gate was run against the WSL2 development host, which it had to reject.

It rejected it at **8 of 26** — and in doing so exposed a hole in its own logic.
WSL advertises a Vulkan device named `Microsoft Direct3D12 (NVIDIA GeForce RTX
4050 Laptop GPU)` while OpenGL falls back to `llvmpipe` and `/dev/dri` does not
exist. That name contains no software-rasteriser marker, so the original
substring check **accepted** it: the llvmpipe mistake wearing a better disguise.

The condition now requires a Vulkan device to be backed by a real DRM card node
and rejects translation layers by name. After the fix the same host scores
**8 of 26** with the Vulkan condition correctly refused:

```text
BLOCKED: Vulkan device 'Microsoft Direct3D12 (NVIDIA GeForce RTX 4050 Laptop GPU)'
         is translated or emulated; a paravirtualised device name is not a
         hardware render path
```

The refusal is retained as a negative control in
`infrastructure/fedora-host/evidence-template/negative-control/`, and
`test_a_translated_vulkan_device_is_refused` keeps the fix in place.

A gate nobody has watched refuse is a gate nobody has checked.

## Three further fail-closed gaps, closed before merge

Review found three conditions that could pass on an absence rather than an
observation. Each is now refused, and each has tests.

**A missing OpenGL renderer satisfied `hardware-renderer`.** The check asked only
whether the renderer was a software rasteriser, and a missing renderer answered
no. A host where `glxinfo` was absent or failed therefore passed the mandatory GPU
condition by saying nothing. It now requires a renderer to have been observed.

**Malformed reports could raise instead of refusing.** The conditions index and
call methods on the document, so valid JSON with wrong types could raise
`AttributeError` from inside a lambda. The report is now validated against
`host-environment.schema.json` before evaluation, naming the offending field and
exiting 2 with no traceback. Adding `AttributeError` to the wrapper would have
hidden the same problem one layer down; the schema is the correct boundary.
Validation fails closed — an unavailable `jsonschema` refuses rather than skips.

**`/dev/kvm` alone proved nothing.** A device node says a file exists, not that the
host can run a guest. The collector now runs `virt-host-validate qemu` and records
its exit code, and the condition requires both the node and a zero exit. A null
exit code means not run, and not run is not a pass.

## What was validated, and how

| Component | Validation |
|---|---|
| Readiness gate | 42 tests; an ideal-host fixture broken one condition at a time |
| | the report is schema-validated before evaluation; malformed types block, never crash |
| | `READY` exits 0, `BLOCKED` exits 2, missing file exits 2 |
| | run against a real host that had to fail: 8 of 26, exit 2 |
| Environment collector | run on WSL2; correctly reported `bareMetal: false`, `hypervisor: wsl`, `llvmpipe`, `softwareRasteriser: true`, `connectedOutputs: 0` |
| Package installer | dry-run against live Fedora 44 repositories: 100 packages, 54 already present, 46 available, **0 unavailable** |
| Reset script | `bash -n` clean; dry-run exercised; unknown scope refused |

The WSL2 environment was used as a **negative control and as a Fedora package
mirror**. It produced no qualification evidence and is not a qualification host.

## Roles

One machine performs several programs; the evidence must never blur them.

| Role | Produces |
|---|---|
| `host` | V4 measurements, Orca, PipeWire capture, multi-display, GPU |
| `vm-qualification` | Programs E, F, G in disposable guests |
| `physical-target` | Program I only |

`role` is a required field and the gate refuses a report whose role is not
`host`. **A VM result never enters a physical cell**, including a VM that ran on
the physical qualification host.

## Operational note

Invoking the gate through `wsl.exe` does not propagate its exit code reliably —
observed returning 0 for a `BLOCKED` host. Run it natively, or read the printed
result. Recorded in `OPERATOR_CHECKLIST.md` because a gate whose refusal is
invisible to the caller is the failure mode this whole directory is about.

## What happens next

Provision the host per `infrastructure/fedora-host/OPERATOR_CHECKLIST.md`, then
commit FQH-5 — the measured environment report, readiness result and package
inventory. Only then does the qualification sequence resume:

```text
V4 → H1 → E → F → G → I rehearsal → PH-T → PHQ → PH-E → regenerate gates
```

Preferred first host: Intel or AMD graphics, so upstream Mesa and DRM keep
unrelated driver variables out of the first qualification. NVIDIA is a later
compatibility cell.

## Standing position

GNOME remains the supported architecture and the default host desktop. The
native Bunny shell remains experimental and non-default. PR #19 remains draft and
unmerged, based on the V3 branch. The invalidated `physical-hardware` record
remains invalidated and un-re-digested.

The candidate gate is unchanged: **BLOCKED, 3 of 14**.
