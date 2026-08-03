<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Reset procedure

A matrix must not inherit state from the one before it. A run that passed only
because a portal permission was still granted from an hour ago is not evidence of
anything.

    bash scripts/reset-test-state.sh --scope <scope> --dry-run
    sudo bash scripts/reset-test-state.sh --scope <scope>

Always dry-run first. The dry run changes nothing and prints every action it
would take.

## Scopes

| Scope | Covers |
|---|---|
| `visual-v4` | compositor processes, portal permissions, accessibility prefs, input-method state |
| `encryption` | libvirt guests, overlays, OVMF vars, LUKS mappings, loop devices, swtpm state |
| `selinux` | guests, overlays, block devices |
| `update` | guests, overlays, block devices, swtpm state |
| `accessibility` | accessibility prefs, compositor processes, portal permissions |
| `hardware-rehearsal` | compositor, portals, accessibility prefs, temporary PAM stack |
| `all` | everything above |

An unknown scope is refused, not interpreted.

## What it will not touch

The script runs as root on a machine holding the operator's real work, so it is
deliberately timid:

- only resources named with the `bunnyqual` prefix it controls;
- unrecognised guests, disks and mounts are **reported and left alone**;
- system PAM configuration is never modified — only a temporary stack it created;
- the operator GNOME session is never killed.

A blanket `cryptsetup close` would reach the operator's own encrypted disks; an
untargeted `virsh undefine` would reach their own VMs. Prefix discipline is what
stops both.

Override the prefix with `BUNNY_QUAL_PREFIX` if the default collides.

## After every reset

The script greps retained evidence for secret patterns and warns on a hit.
Investigate any warning before committing anything from that run: a plaintext
passphrase in an evidence file is a defect in the harness that wrote it.
