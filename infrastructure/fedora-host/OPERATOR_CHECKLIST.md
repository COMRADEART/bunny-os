<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Operator checklist

The order matters. Each step either produces evidence the next one needs, or
proves the machine can produce it at all.

## 1. Install Fedora on bare metal

Fedora Workstation, GNOME, Wayland, SELinux enforcing. Not inside WSL,
VirtualBox, VMware or a nested VM — the readiness gate refuses a virtualised
host, and correctly.

Record the ISO digest and installation date; export them so the collector picks
them up:

```bash
export BUNNY_FEDORA_ISO_DIGEST=sha256:...
export BUNNY_HOST_INSTALLED_ON=2026-08-..
```

Then:

```bash
sudo dnf upgrade --refresh -y && sudo reboot
```

After reboot, confirm the two things most often wrong:

```bash
getenforce                                        # Enforcing
loginctl show-session "$XDG_SESSION_ID" -p Type   # Type=wayland
```

## 2. Connect two displays

Physically. Prefer mixed resolution — 1920×1080 alongside 3840×2160 — because
mixed-DPI scaling is a V4 gate and a matched pair cannot exercise it.

Confirm the kernel sees both:

```bash
grep -l '^connected$' /sys/class/drm/card*/status | wc -l   # expect 2 or more
```

## 3. Create the operator account

A dedicated non-root account. Compositors and shell UI never run as root. Add it
to the libvirt group rather than running every VM operation as root.

## 4. Install the toolchain

```bash
sudo bash infrastructure/fedora-host/scripts/install-packages.sh \
     --report /var/lib/bunny-qualification/environments/FQH-<id>/packages.json
```

An unavailable package is recorded as `UNAVAILABLE`, never skipped silently. If
anything lands there, resolve it — a renamed package looks identical to a missing
one in a later `NOT_RUN`.

## 5. Create the storage tree

See `STORAGE_POLICY.md`. Nothing multi-gigabyte goes in the repository, and no
git worktree is ever created inside `build/`.

```bash
sudo mkdir -p /var/lib/bunny-qualification/{environments,artifacts,vm-images,overlays,evidence,logs,screenshots,captures,recovery-media,temporary}
sudo chown -R "$USER" /var/lib/bunny-qualification
```

## 6. Clone and verify the repository

Clone only after the host baseline exists, so the environment report describes
the machine before Bunny touches it.

```bash
git clone git@github.com:COMRADEART/bunny-os.git && cd bunny-os
git config --get core.autocrlf          # expect empty or false on Linux
python -m unittest discover -s tests/evidence -t .
```

All seven attested files must round-trip. The invalidated `physical-hardware`
record must remain invalidated — `qualification/hardware/INVALIDATED_EVIDENCE.json`
and `operations/data/release-evidence.json` are not edited on the host.

## 7. Run the protected gates

```bash
python scripts/task.py validate
python scripts/task.py test
python scripts/task.py test-installer
python scripts/task.py test-phase5
python scripts/phase7.py source-gate
```

On Fedora the duplicate-boot symlink mutation test executes normally, so the
expected local result is **0 failures, 0 errors**. It could not run on Windows
and was recorded `NOT_RUN` there.

**Do not continue if the Linux source suite is red.**

## 8. Collect the environment and run the readiness gate

```bash
python infrastructure/fedora-host/scripts/collect-environment.py \
    --environment-id FQH-<YYYYMMDD>-<NN> --operator "<name>" --role host \
    --output /var/lib/bunny-qualification/environments/FQH-<id>/environment.json

python infrastructure/fedora-host/scripts/host-readiness-gate.py \
    --environment /var/lib/bunny-qualification/environments/FQH-<id>/environment.json \
    --output    /var/lib/bunny-qualification/environments/FQH-<id>/readiness.json
```

Set `git.byteRoundtripTestsPass` to `true` in the environment report only after
step 6 actually passed. The gate treats `null` as not run, and not run is not a
pass.

`READY` exits 0. **`BLOCKED` exits 2 and means the host may not be used** — not
that the refusal should be worked around.

> When invoking the gate through `wsl.exe`, the exit code does not propagate
> reliably. Read the printed result, or run it natively. This bit us once.

## 9. Commit FQH-5

Only now. The environment report, readiness result and package inventory for a
real machine are the measured-host evidence, and they cannot exist before the
machine does.

## 10. Then, and only then, the qualification work

In this order, per the program sequence:

```text
resume V4  ·  H1 GNOME accessibility  ·  E encrypted unlock
F SELinux  ·  G update/rollback/recovery
I rehearsal → PH-T → PHQ collection → PH-E
regenerate the candidate and stable-release gates
```

Reset between matrices:

```bash
bash infrastructure/fedora-host/scripts/reset-test-state.sh --scope <scope> --dry-run
sudo bash infrastructure/fedora-host/scripts/reset-test-state.sh --scope <scope>
```

Always dry-run first.

## Standing constraints

GNOME stays default. The Bunny shell stays non-default. PR #19 is not merged. No
VM result enters a physical cell. Stable release remains **NO-GO** and pilots
remain **BLOCKED** until the protected gates say otherwise.
