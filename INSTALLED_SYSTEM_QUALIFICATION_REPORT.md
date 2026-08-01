<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Installed-system qualification report

Date: 2026-08-01
Status: **Evidence collected and imported. Qualification candidate remains
BLOCKED at 3 of 14. Stable release remains NO-GO.**

## The two commits

```text
Commit E — installed-system qualification target
  d496e7760316219932c1f8f542061a9d3bfbe789

Commit F — installed-system evidence import
  f314864284b8ec331a564d0bfb084942ea727fa6
```

Commit F carries evidence about Commit E and is not itself a target. Commit
E in turn binds to the archive qualification target
`619065e068e2153de461545f5b8950b985db4dfd`, whose three-builder
reproducibility was re-established before any disk was written.

## What the archive stage established first

```text
Local Fedora WSL + hosted runs 30691438160 and 30691438881
Raw archive        0258f92af988ef180e30d48ea084d555bd959a3af9d5a629268823c3f845966a
                   identical from all three builders
All three pairs    REPRODUCIBLE, 17 of 17
Builder independence PASS
```

That target superseded `225a5e1` for one measured reason: its archive could
not mint `/etc/brlapi.key` on an installed system, which is precisely the
kind of thing this workstream exists to find. The root-filesystem change was
re-qualified through the full local gate and a fresh three-builder run
before installation began.

## What was executed

```text
Installation, eight modes                    PASS
  blank, second blank, offline (container network removed),
  undersized refused before partial deployment,
  existing data protected without authorization and installed with it,
  interruption killed mid-deployment, encrypted prepared with LUKS2

Boot scenarios                               6 PASS, 1 measured FAIL
  pinned artifact, two derived installs, offline install,
  reduced resources (2 vCPU / 4 GiB), no-TPM control        PASS
  software TPM 2.0 attached                                 FAIL

Offline collections                          executed, findings recorded
  first-boot journal, applied SELinux, per-installation identities,
  service state, network capture, signed-update metadata
```

## What it found

Five findings, none of them softened, each with a record behind it.

**The BrlAPI key was never minted.** `bunny-brlapi-key.service` did not run
on any installed system: the unit ships with `WantedBy=sysinit.target`,
nothing enabled it, and systemd disables what no preset names. A braille
display would have been unauthorised for the entire session. This is the
second half of one defect — the first half, an `ExecStart` naming a program
the build never installed, was visible to CI and fixed earlier in this pass.
Only booting an installed system could show the second. Both halves are now
fixed in source; the fix post-dates the qualified archive, so every record
here still reports the failure rather than being backdated.

**The image resets at GRUB when a TPM 2.0 is attached.** Reproduced with
`tpm-crb` and `tpm-tis`, against a control in the same suite: the identical
disk with no TPM reaches `graphical.target`. The declared minimum physical
target is a machine with TPM 2.0.

*Superseded 2026-08-01 by the TPM investigation
(`TPM_GRUB_RESET_ROOT_CAUSE.md`, confidence CONFIRMED): the reset was
shim `fbx64.efi`'s deliberate one-time boot-option-restoration reboot on a
fresh NVRAM with a TPM present — GRUB never ran in the failing boots — and
this harness's `-no-reboot` turned that designed reboot into a dead guest.
The `ISQ-20260801-tpm-present-*` records stay as invalidated harness
evidence; TPM boot qualification now lives under the `tpmq-1` authority
(`TPM_QUALIFICATION_REPORT.md`), where the same image passes 5/5 on both
interfaces with the reboot permitted. The finding's text above is preserved
as written because this report describes what this pass measured and
believed at the time.*

**Encrypted unlock is not qualified.** The refusal path is sound and passes —
a wrong passphrase is consumed, rejected, reprompted, with nothing mounted
and nothing leaked. The correct passphrase is accepted, and the boot then
takes tens of minutes; one run completed at about twenty, two did not finish
within forty-five. LUKS2 picks argon2id costs benchmarked on the machine
that formats the volume, and that machine was a fast builder. One success is
not reproducibility.

**Applied SELinux comparison is BLOCKED.** 81,774 labels read from the
deployed root, 78,844 matched, 58 symlink-versus-target divergences and
12,369 unresolved paths that need reviewed classification. Widening a glob
to lower that count is the one thing the fixture exists to prevent.

**Two units failed at boot** — `gdm.service` and a GNOME screencast unit —
enumerated rather than summarised, because a service report that quietly
drops one is what the adversarial tests refuse.

## Gate position, calculated from evidence

```text
Source gate                    PASS      exit 0
Archive reproducibility        PASS      REPRODUCIBLE, independent
Installation matrix            NOT_RUN   8 rows imported; no matrix complete
Encryption matrix              NOT_RUN   refusal passes, unlock does not
Update matrix                  NOT_RUN   metadata battery passes; staging pending
Rollback matrix                NOT_RUN   executor written, not executed
Recovery media                 NOT_RUN   no recovery ISO code path exists
Applied SELinux                BLOCKED   12,369 unresolved
Engineering accessibility      NOT_RUN   no assistive technology driven
Physical hardware              NOT_RUN   no device; framework only
Independent reviews            PENDING   external, unclaimed
Production signing             BLOCKED   no authorized signer exists
Qualification candidate        BLOCKED   3 of 14
Stable release                 NO-GO
OEM / enterprise / sync pilot  BLOCKED
```

Independent reproducibility moved from BLOCKED to PASS. Nothing else moved,
and every gate was verified by exact exit code.

## What this pass does not establish

No desktop session was driven: the qualified image ships no default
credential and this harness did not add one, so login, GNOME, the Bunny
launcher, approval dialogs and every assistive-technology flow are untested.
No update was staged onto a disk and rolled back — the offline executor
exists and has not been run. No recovery media exists to test. No physical
machine has run Bunny OS; the hardware framework is built and every one of
its tests is explicitly `NOT_RUN`, which is not a pass and must never be
converted into one.

Every VM record states `environment: qemu-kvm`, and the record schema, the
context resolver and the adversarial tests each refuse to let one become
physical evidence by relabelling.
