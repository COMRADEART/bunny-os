# Guest Trust journey

This document is evidence. A missing guest is recorded as NOT_RUN or BLOCKED, never as PASS.

- captured: 2026-09-11T02:07:00Z
- host: Ubuntu 24.04.4 LTS
- stable release: NO-GO
- pilots: BLOCKED

## Host probe

- `/dev/kvm`: PASS (writable=yes)
- QEMU: /usr/bin/qemu-system-x86_64
- OVMF: /usr/share/OVMF/OVMF_CODE_4M.fd
- Podman: /usr/bin/podman
- guestfish: /usr/bin/guestfish
- image-builder: ABSENT
- QCOW2: ABSENT
- KVM smoke: PASS — QEMU accepted accel=kvm (timed wait)
- guest boot: **NOT_RUN** — no composed Bunny OS disk; image-builder is a Fedora 44 package and is not available on this host

`report.passed` is the honest-probe flag (host tests passed and the guest status is PASS, NOT_RUN, or BLOCKED). It is **not** a guest Trust PASS and not a stable-release GO.

## Host regressions (no guest required)

- Approval is not a timeout: PASS (5 tests)
- Guest Trust harness contract: PASS (14 tests)
- Accessible names: `Allow this Bunny action` / `Deny this Bunny action`

## Guest journeys (AT-SPI, not resolve_approval)

### granted

- result: **NOT_RUN**

### denied

- result: **NOT_RUN**

## Still needs a Fedora 44 image-builder host

These commands finish the guest photograph. They are not claimed here.

```text
sudo dnf install -y git make podman image-builder osbuild-selinux qemu-system-x86 edk2-ovmf guestfs-tools ShellCheck
# add the operator to the kvm group so /dev/kvm is writable
make build-shell-test-image
python3 demos/09-guest-trust/run.py
# equivalent: make demo-guest-trust
# optional: BUNNY_DESKTOP_IMAGE=build/out/shell/<file>.qcow2 make demo-guest-trust
```

Deny-by-default is unchanged. There is no Always allow everything control.
