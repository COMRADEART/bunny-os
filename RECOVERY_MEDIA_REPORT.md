<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Recovery media report

Date: 2026-08-01
Status: **BLOCKED — no recovery ISO code path exists in the repository**

## Result

```text
Recovery ISO code path        NONE — three consumers demand one;
                              build-image.sh recovery produces qcow2 only
Standing qualification record RECOVERY_MEDIA_QUALIFICATION_REPORT.md:
                              11 of 11 scenarios NOT_RUN — unchanged and
                              not contradicted here
Commit E                      records no recoveryArtifactDigest —
                              deliberately, for exactly this reason
```

There is no recovery ISO to test. The `recovery` mode of `build-image.sh`
produces a qcow2 disk image, which is not separately bootable media and does
not satisfy any consumer that demands an ISO. The standing
`RECOVERY_MEDIA_QUALIFICATION_REPORT.md` records 11 of 11 scenarios NOT_RUN;
this report agrees with it and adds nothing that would let a scenario move.

## Method

No method ran. Commit E's evidence context omits `recoveryArtifactDigest`
because recording a digest for an artifact that does not exist would be a
fabrication the adversarial tests exist to refuse. The omission is the
evidence.

## What a recovery ISO must be able to do

When the code path exists, the medium it produces must:

```text
1.  boot independently of the installed system
2.  discover installations on attached disks
3.  detect encryption on discovered installations
4.  request the unlock credential securely
5.  list deployments of a discovered installation
6.  identify the active and previous deployment
7.  inspect bootloader state
8.  inspect SELinux state
9.  perform a documented rollback
10. collect diagnostics
```

and it must modify no disk without explicit authorization. These are the
requirements the 11 standing scenarios encode; none of them can be attempted
until the ISO exists.

## What this establishes, and what it does not

**Established.** Only the gap, precisely: no recovery ISO code path exists,
no recovery scenario has run, and Commit E's evidence context is honest about
both. The interrupted-installation disk retained by the installation matrix
(`INSTALLABLE_IMAGE_REPORT.md`) is a future test subject for recovery
inspection — retained, not inspected.

**Not established.** Every recovery capability listed above. Nothing about
recovery is claimed, partially claimed, or claimed by analogy to other
mechanisms. The `scripts/bunny-recovery.py` console named in the baseline as
the recovery mechanism has no bootable carrier and therefore no
installed-system evidence here.

## Where the evidence lives

```text
RECOVERY_MEDIA_QUALIFICATION_REPORT.md    the standing 11-scenario record,
                                          all NOT_RUN
qualification/installed-system/evidence-context.json
                                          Commit E context; no
                                          recoveryArtifactDigest recorded
```

## Gate position

```text
Recovery media               BLOCKED — no recovery ISO exists; this report
                             changes nothing
Installation matrix          rows move only through
                             qualification/installed-system/scripts/
                             import_matrix_results.py; recovery-media rows
                             stay NOT_RUN/BLOCKED
Qualification candidate      still BLOCKED
Stable release               NO-GO, unchanged
```

The recovery line moves when a recovery ISO exists and its scenarios run —
not before, and not through this document.
