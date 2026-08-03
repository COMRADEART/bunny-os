<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Environment capability

> **VISUAL OR SHELL DEVELOPMENT**
> **NOT RELEASE QUALIFIED**
> **DO NOT MERGE INTO MAIN WITHOUT AN EXPLICIT PRODUCTION INTEGRATION DECISION**
> **GNOME REMAINS THE SUPPORTED FALLBACK**

The V4 results record five gates as `NOT_AVAILABLE`. This is the measurement
behind that claim, so a reader can check it rather than take it.

Probe: `visual-v4/tools/probe_environment.sh`
Output: `visual-v4/evidence/environment-probe-wsl2-fedora44.txt`
Host: WSL2, Fedora Linux 44, kernel 6.18.33.2-microsoft-standard-WSL2

## What this host has

| Capability | State |
|---|---|
| Wayland server/client | 1.25.0 |
| GTK 4 | 4.22.4 |
| Xwayland | present |
| PipeWire, WirePlumber | present |
| Weston | present |
| Rust, cargo, gcc | present |
| systemd as pid 1, D-Bus session, logind | present |
| dnf and network | working |

## What it does not have, and why that ends V4 here

| Missing | Consequence |
|---|---|
| **`/dev/dri`** | no KMS. No page-flip, no vblank, no connectors. |
| **hardware GL** | renderer is `llvmpipe`, a software rasteriser. |

Those two facts block five gates outright:

| Gate | Why |
|---|---|
| `gpu-rendering` | a software rasteriser cannot qualify GPU rendering |
| `linux-dmabuf` | no DRM device, so no dmabuf path with real format modifiers |
| `frame-pacing` | no page-flip and no vblank, so no clock to pace against |
| `two-output-presentation` | no connectors; nested windows are not outputs presenting frames |
| `output-hotplug` | no outputs exist to add or remove |

Two of those, `gpu-rendering` and `two-output-presentation`, are mandatory under
C7. So **no framework may be selected from measurements taken on this host**, and
no amount of work on the other twenty-six gates changes that.

Also absent, but only a `dnf install` away, and so recorded as `NOT_RUN` rather
than `NOT_AVAILABLE`: `ibus` / `fcitx5`, `orca`, `speech-dispatcher`, `at-spi2`,
`libpipewire` development files, PAM development files, and
`mutter` / `libmutter`.

## The distinction this file exists to protect

`NOT_AVAILABLE` and `NOT_RUN` both score zero and both block a mandatory gate, so
the harness treats them identically. They are recorded separately because they
are cleared differently: `NOT_RUN` is cleared by doing the work, `NOT_AVAILABLE`
is cleared only by different hardware. Collapsing them would hide the fact that
part of V4 is not waiting on effort.

## What would unblock V4

One Linux machine with a real DRM device and two real outputs. On such a host the
five gates above become measurable and the remaining six mandatory gates become
ordinary engineering.

Everything on this branch is written to be executed there unchanged: the
contract, the harness and the probe are all host-independent, and the probe
re-classifies the environment-blocked gates automatically when it finds a DRM
device.
