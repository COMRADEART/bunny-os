<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Security boundary

The qualification host holds real credentials, real disks and the operator's own
work. It also produces files that get committed to a repository. This document
is about the line between those two facts.

## Never committed

Not redacted, not encrypted, not "temporarily" — never written into the
repository at all:

```text
login passwords
LUKS passphrases
PAM test passwords
TPM owner authorization values
Secure Boot private keys
production signing keys
personal account tokens
GitHub tokens
Wi-Fi passphrases
raw hardware serial numbers
```

Serial numbers are recorded as `sha256` in `host.serialHash`. The hash proves two
runs happened on the same machine, which is the only property the evidence model
needs; the serial identifies a physical object somebody owns, which it does not.

## Secrets during a run

Passphrases used by Program E are injected ephemerally and must not appear in:

```text
the repository        the command line        the process list
the journal           the serial log          shell history
evidence files        screenshots             retained artifacts
```

`reset-test-state.sh` greps retained evidence for secret patterns after every
reset and warns on a hit. A warning there is a defect in the harness that
produced the evidence, not a nuisance to be silenced.

## Host posture

The host must stay trustworthy enough for its measurements to mean something:

| Requirement | Why |
|---|---|
| SELinux enforcing | the gate refuses a permissive host; Program F measures against enforcing |
| firewalld enabled | the host runs disposable guests with unknown network behaviour |
| automatic screen lock | the host is also the lock/unlock measurement surface |
| no passwordless remote root | — |
| dedicated non-root operator account | compositors and shell UI never run as root |
| libvirt access via group, not root | every VM operation as root is a larger blast radius than needed |

**GNOME remains the default host desktop.** No experimental Bunny session is
configured as default at any point, on any host, during V4 or V5.

## The reset script

`reset-test-state.sh` runs as root on a machine holding the operator's real work,
so it is deliberately timid:

- it touches only resources named with the `bunnyqual` prefix it controls;
- unrecognised guests, disks and mounts are reported and left alone;
- `--dry-run` changes nothing and is the documented first step;
- an unknown `--scope` is refused rather than interpreted;
- it never modifies system PAM configuration, only a temporary stack it created.

A blanket `cryptsetup close` or an untargeted `virsh undefine` would reach the
operator's own encrypted disks and VMs. That accident is the reason for the
prefix discipline.

## What this infrastructure claims

Nothing about Bunny OS. Provisioning a host qualifies no artifact, satisfies no
prerequisite and moves no gate. A `READY` result means the machine is capable of
being measured on — not that anything has been.
