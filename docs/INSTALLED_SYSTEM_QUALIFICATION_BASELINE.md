<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Installed-system qualification baseline

This is the authority record for everything installed-system qualification
tests. Every scenario, gate and report in `qualification/installed-system/`
binds to the values here through the evidence-context resolver
(`release/installed.py`); a script that decides for itself what was tested is
a defect the adversarial tests refuse.

## The archive authority

```text
Reproducible archive target (Commit C):
  619065e068e2153de461545f5b8950b985db4dfd

Archive-stage evidence for the predecessor target 225a5e1 (Commit D):
  f65b65c6066f54c43b6e8b2ff6e2abfc3254d79e

Reproducibility merge commit on main:
  2763757d1107a0598662be3b2a741f1855ecc7eb

Raw archive digest (target 619065e):
  aec97e705c382304efd8e58c165456e8646edac5f4ea3d27d4f34aee31e79b7a

Base image (retained, by digest):
  ghcr.io/comradeart/bunny-os-base@sha256:1f08084a9a8545bd528641d4fda14e18408dfb1298acda243eaf583cd907a844

Builder image:
  ghcr.io/comradeart/bunny-os-builder@sha256:bf9f00d81c5d707830676193041862dbb5bccc88c18a000cdb674311917d1f3e

Package snapshot (474 packages):
  ghcr.io/comradeart/bunny-os-package-snapshot@sha256:4fa4fbc1f14cf0b5406475778eda708c303143d5c5ec2c5ec783ddfdb3af501b
  manifest b6fbf2ae637a288cc8184ccf9142e47414db5196976a9d53b2d8422df1c2949b

Build epoch:      1785442979 (from reproducibility-lock.json)
Profile:          beta
Architecture:     x86_64
```

Why two targets appear above: 225a5e1 achieved three-builder byte
reproducibility and was then superseded for one measured reason — its archive
could not mint `/etc/brlapi.key` on an installed system, and stage 10 tests
exactly that. The fix is one line in `install-root.py`; target 619065e is the
re-measured result. Evidence about 225a5e1 remains true about 225a5e1;
installed-system evidence binds only to 619065e's archive.

## Artifact roles

```text
Root filesystem artifact:
  The reproduced OCI archive from Commit C (619065e). Immutable; every
  installed system's root traces to it by digest.

Installation artifact:
  A disk image or installation medium that deploys exactly that root
  filesystem. Produced by the pinned installer toolchain; its own digest is
  recorded in the evidence context and in Commit E.

Recovery artifact:
  A separately bootable environment for inspection, unlock, repair and
  rollback. Never shares a root filesystem with the system under test.

Installed-system evidence:
  Collected after the root filesystem is deployed to a disk and booted.
  Environment is qemu-kvm or physical, stated in every record.

Physical-hardware evidence:
  Installed-system evidence from a real machine. A VM record never becomes
  one; the record schema, the context resolver and the adversarial tests all
  refuse the relabelling.
```

## Mechanisms under qualification

```text
Firmware mode:            UEFI (OVMF in virtual scenarios). Development
                          Secure Boot only; no production Secure Boot claim.
Installation mechanism:   bootc install to-disk (--via-loopback for image
                          targets) and bootc install to-filesystem for
                          prepared encrypted layouts — the image installs
                          itself, running from the image.
Disk layouts:             GPT; ESP + /boot + root. Encrypted layout adds
                          LUKS2 under the root filesystem.
Encryption modes:         none; LUKS2 with passphrase. TPM enrolment is not
                          claimed: it is exercised only as far as swtpm
                          allows and is recorded as swtpm, never physical.
Update mechanism:         bootc/ostree staged deployments; update metadata
                          signed with development keys only.
Rollback mechanism:       bootc rollback to the retained previous deployment.
Recovery mechanism:       separately booted recovery environment
                          (scripts/bunny-recovery.py console); recovery ISO
                          production is part of this workstream.
Signing status:           development keys only. No production identity
                          exists, none is created here, and every gate that
                          requires production signing stays blocked.
```

## Current qualification blockers (at baseline creation)

```text
Qualification candidate    BLOCKED — 2 of 14 prerequisites satisfied
Stable release             NO-GO
Installation matrix        NOT_RUN
Encryption matrix          NOT_RUN
Update matrix              NOT_RUN
Rollback matrix            NOT_RUN
Recovery media             NOT_RUN — no recovery ISO existed before this work
Physical hardware          NOT_RUN — no device; framework only
Applied SELinux            never collected before this work
Independent reviews        PENDING — external, unclaimed
Production signing         BLOCKED — no authorized signers
Pilots                     BLOCKED
```

This baseline moves none of them. Evidence does.
