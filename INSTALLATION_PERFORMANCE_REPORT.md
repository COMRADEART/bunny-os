# Installation performance baseline

Date: 2026-08-16  
Result: **a driven installation completes in three to four minutes** on the
reference virtual machine. This is a baseline for regression comparison, not
a target and not a claim about hardware.

## Numbers

Wall-clock from QEMU launch to the driver's terminal outcome on serial, then
the external disk verification, derived from artifact timestamps (±2 s):

| Run | Launch → driver outcome | Disk verification | Notes |
|---|---|---|---|
| Journey A (encrypted) | 3 min 57 s | 2 min 59 s | verification opens LUKS (argon2id at 3 GiB appliance memory) |
| Journey B (encrypted, 200 % text, 1024×768) | 3 min 28 s | 1 min 50 s | accessibility features cost nothing measurable |
| Journey C (unencrypted) | 3 min 02 s | 30 s | |
| Journey C offline (no NIC) | 3 min 06 s | 31 s | no offline penalty |
| Journey D (refusal) | 54 s | — | refuses before the install stage |

Within those runs, the journey-A screenshots put the driver at the storage
screen by t60 and inside the install stage by t150: medium boot to a usable
setup surface is roughly a minute, the guided flow under a minute more, and
the installation itself — partitioning through bootloader and teardown —
around two minutes.

First boot of the installed system (encrypted): the LUKS prompt is answerable
by 35 s and the greeter is on screen within five minutes of power-on
including the passphrase wait; the harness measures target-reached, not a
stopwatch, so no finer number is claimed.

## Environment, so the numbers transfer honestly

QEMU/KVM nested inside WSL2 (Fedora 44 builder), q35, 4 vCPU, 6 GiB RAM,
OVMF firmware, virtio disk backed by an ext4 file on NVMe, virtio-vga with
no display attached. Software rendering throughout. Physical-hardware
numbers do not exist yet (`PHYSICAL HARDWARE VALIDATED` is unreached across
the phase) and nothing here predicts them.

## Caveats

One sample per journey; no variance is claimed. Timestamps are file-mtime
anchors, not instrumented spans. The payload deploys from the medium's local
container store, so disk throughput dominates; a slow USB medium on real
hardware will move the middle number, not the flow.
