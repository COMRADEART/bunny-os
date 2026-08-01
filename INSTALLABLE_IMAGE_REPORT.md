<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Installable image report

Date: 2026-08-01
Status: **PRODUCED — the qualified archive wrapped into disk images, root filesystem byte-preserved; installation matrix exercised host-side**

## Result

```text
Archive qualification target  619065e068e2153de461545f5b8950b985db4dfd (Commit C)
Qualified archive digest      0258f92af988ef180e30d48ea084d555bd959a3af9d5a629268823c3f845966a
                              three-builder REPRODUCIBLE, 17 of 17
                              (local Fedora WSL + hosted runs 30691438160
                              and 30691438881), independence PASS
Installed-system target       d496e7760316219932c1f8f542061a9d3bfbe789 (Commit E)

bunny-os-619065e068e2.qcow2   sha256 7739e15f92627afa…
bunny-os-619065e068e2.raw     sha256 d208a60e1378750f…
                              (full digests in qualification/installed-system/
                              evidence/installables.json)

Partitioning                  GPT: ESP + boot + root ext4
Bootloader                    bootupd-managed GRUB2, BLS entries
Firmware                      UEFI
Encryption                    none in the generated images
```

The images are produced by
`qualification/installed-system/scripts/build_installables.sh`. The mechanism
is deliberately a wrapper, not a rebuild: the qualified archive is loaded with
`podman load` — layers and config preserved byte-for-byte — and deployed by
`image-builder build --bootc-ref localhost/bunny-os-beta:619065e068e2
--bootc-default-fs ext4 {qcow2,raw}`. The root filesystem inside each disk
image is the qualified archive's by construction, not by re-derivation.

## Two claims, kept apart

Root-filesystem reproducibility is established evidence — the three-builder
result above. Disk-image byte reproducibility is NOT claimed. The measured
reason the two claims differ is the set of unique-per-generation identifiers
the disk format mints: partition GUIDs, filesystem UUIDs and the ESP volume
id. These are documented properties of the generated images, not defects, and
no line in this report converts one claim into the other.

## Two measured refusals — the immutability guard working

Both occurred during development of the wrapper, and both were the guard
doing its job:

1. A rebuild in Fedora's default container store came out through the naive
   diff walker (mountopt `metacopy=on`) — archive `f49b8fcf1b0b…` did not
   match the qualified `0258f92af988…`, and no disk was emitted.
2. `CONTAINERS_STORAGE_CONF` never reached podman through the build script's
   sudo wrapper, so pointing the rebuild at a corrected store was not a fix
   that could be trusted.

The final design wraps the qualified bytes instead of rebuilding them, which
removes the store configuration from the trust chain entirely.

## Installation matrix

Host-side installations, `bootc install to-disk --via-loopback` and
`bootc install to-filesystem`, driven by
`qualification/installed-system/scripts/install_to_disk.sh` and
`qualification/installed-system/scripts/install_encrypted.sh`:

```text
blank           PASS
blank2          PASS                  second install, for identity comparison
offline         PASS                  podman --network=none; no registry
                                      fallback possible
undersized      REFUSED_AS_EXPECTED   4G target; exit before partial
                                      deployment
existing-data   PROTECTED             without --destructive (runner gate);
                INSTALLED             with explicit --destructive + --wipe
                                      (bootc's own refusal is a second
                                      protection)
interrupted     INTERRUPTED           SIGKILL 25s into deployment; disk
                                      retained for recovery inspection
encrypted       PASS                  prepared GPT + BIOS-boot + ESP + boot +
                                      LUKS2; bootc install to-filesystem;
                                      passphrase via file only; rd.luks.uuid
                                      karg
```

Two installer defects were found and fixed during the matrix:

1. bootc refused with "No root filesystem specified" — the image ships no
   install config, so `--filesystem ext4` is now passed explicitly.
2. grub2-install refused GPT without a BIOS boot partition — a 1 MiB `ef02`
   partition was added to the encrypted layout.

## What this establishes, and what it does not

**Established.** The qualified root filesystem deploys to disk unmodified;
the disk images carry it by digest-verified construction. The installer
refuses undersized targets before partial deployment, refuses existing data
without explicit destructive intent, and completes offline with no registry
fallback available. The encrypted prepared-layout path installs and carries
the correct `rd.luks.uuid` kernel argument.

**Not established.** Disk-image byte reproducibility (excluded above, with
the measured reason). Boot, first-boot behaviour, update, rollback and
recovery of the installed systems — those are installed-system scenarios with
their own evidence. Live-installer media and recovery media are separately
reported (`LIVE_INSTALLER_MEDIA_REPORT.md`, `RECOVERY_MEDIA_REPORT.md`) and
nothing here stands in for them. Physical hardware remains untouched.

## Where the evidence lives

```text
qualification/installed-system/evidence/installables.json
                                          the artifact record: full digests,
                                          mechanism, unique-per-generation
                                          identifiers, source archive digest
qualification/installed-system/evidence/installs/
                                          one record per installation matrix
                                          row
qualification/installed-system/evidence-context.json
                                          binds evidence to Commit E
```

## Gate position

```text
Reproducibility              REPRODUCIBLE — archive stage, unchanged
Installation artifacts       PRODUCED — qcow2 + raw, digests recorded
Installation matrix          rows move only through
                             qualification/installed-system/scripts/
                             import_matrix_results.py — this report moves
                             nothing by itself
Live-installer media         NOT_RUN — stays NOT_RUN
Recovery media               BLOCKED — stays BLOCKED
Qualification candidate      still BLOCKED
Stable release               NO-GO, unchanged
```

This report records artifact production and the host-side installation
matrix. Matrix rows enter the gate only through the importer; no other line
moves.
