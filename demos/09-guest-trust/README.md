# Guest Trust journey demo

This is the one-command path from a development host to a **booted Bunny OS
guest** whose Trust / approval UI is drawn inside GNOME and pressed by
accessible name (`Allow this Bunny action` / `Deny this Bunny action`).

It is **not** a stable release, **not** a pilot GO, and it will not relabel a
missing Fedora image as PASS. Deny-by-default is unchanged. There is no
`Always allow everything` control.

The host-visible Trust demo (no guest) remains `demos/08-visible-trust/`.

## One command

From the repository root:

```text
python3 demos/09-guest-trust/run.py
```

or:

```text
make demo-guest-trust
```

On a Fedora 44 image-builder host with a composed `shell-test` QCOW2 this
boots twice (granted, then denied), waits on `BUNNY_SESSION_READY`, types
the resize request, and presses Allow / Deny at their AT-SPI extents via
the virtio-tablet. It never calls `resolve_approval`.

On a host that cannot compose or boot that image, the same command still
runs: it probes QEMU/KVM/Podman/`image-builder`, runs the host Trust
regressions, and writes `NOT_RUN` / `BLOCKED` with the exact commands a
Fedora builder needs. Missing guest steps are not photographed.

## Fedora 44 image-builder host

Documented builder: x86-64, UEFI/KVM, ≥8 vCPU, 16 GiB RAM, 100 GiB free.
See `docs/BUILDING.md`.

```text
sudo dnf install -y git make podman image-builder osbuild-selinux \
    qemu-system-x86 edk2-ovmf guestfs-tools ShellCheck
# operator must be able to read/write /dev/kvm (kvm group)
make build-shell-test-image
python3 demos/09-guest-trust/run.py
```

`shell-test` is the QEMU interactive artifact. `make build-shell-image`
composes the same Shell/Companion payload as a named profile; either QCOW2
can be selected with `BUNNY_DESKTOP_IMAGE=`.

Exit codes:

| Code | Meaning |
|---|---|
| 0 | Guest journeys PASS, **or** an honest NOT_RUN/BLOCKED probe whose host tests passed (`probePassed=true`). Top-level `passed` is `guestPassed` only, so NOT_RUN yields `passed=false` unless `BUNNY_GUEST_TRUST_PROBE_OK=1`. |
| 1 | Host tests failed |
| 2 | A guest was requested (`BUNNY_GUEST_TRUST_REQUIRE=1`) and could not be booted |

## What the command will not do

- Invent boot logs or screenshots of a guest that did not boot
- Claim `gate-stable-release` PASS or a pilot GO
- Press Allow through the Companion protocol as a stand-in for AT-SPI
- Add an `Always allow everything` control
