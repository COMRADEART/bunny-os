# Stable support matrix

Date: 2026-07-29. Status: **no stable release exists, so nothing in this matrix is in force.**

This document defines the support commitments a stable release would carry. Publishing it before a release is deliberate: a support commitment invented after users arrive is not a commitment, it is a negotiation.

## Release identity

| Field | Value |
|---|---|
| Stable version | none |
| Release date | none |
| Support start | none |
| Full support ends | none |
| Security-only ends | none |
| End of life | none |

## Intended lifecycle

| Stage | Duration | What is provided |
|---|---|---|
| Full support | 12 months from release | Security fixes, bug fixes, hardware enablement, documentation |
| Security-only | 6 further months | Security fixes and Critical regressions only |
| End of life | — | No updates. The update agent reports the release as unsupported |

These durations are **proposed, not committed.** `docs/SUPPORT_POLICY.md` currently promises no stable duration, and `SUSTAINABILITY_REPORT.md` records that one maintainer cannot sustain an 18-month window across a hardware matrix. Committing to these numbers without capacity would be a promise the project cannot keep.

## Architectures

| Architecture | Status |
|---|---|
| x86-64 UEFI | source design target; never qualified on physical hardware |
| x86-64 legacy BIOS | not supported by design |
| aarch64 | not supported; named in the OEM profile schema for future use only |

## Hardware tiers

Defined in `docs/STABLE_HARDWARE_TIERS.md` and classified by `operations/hardware.py`.

| Tier | Count |
|---|---|
| Stable recommended | 0 |
| Stable supported | 0 |
| Best effort | 0 |
| Experimental | 0 |
| Unsupported | 0 |
| Untested | every device |

`operations/data/hardware-evidence.json` contains zero reports. The only runtime evidence that exists is virtual: QEMU q35 with OVMF UEFI and virtio devices, which is a useful development target and not a hardware tier.

## What support would cover

Bunny OS itself, the privileged broker, the update agent, the installer, Bunny Shell, recovery, and the Phase 7 OEM, policy and sync client code.

Not covered: the upstream Fedora base and kernel beyond rebasing, third-party applications from Flathub, OEM-specific drivers outside a supported OEM agreement, and any modified or derivative image.

## Update commitment

A supported release would receive signed updates through the stable channel, with monotonic sequence numbers and mandatory Ed25519 verification. No manifest has ever been published, so this commitment has never been exercised.

## What must exist before this matrix takes effect

A published stable release, a production signing key, a declared support window with an owner, at least one qualified hardware model, and confirmed capacity to respond for the duration of the window. None exists.
