# Checked-in guest Trust probe

These files are a run of `python3 demos/09-guest-trust/run.py` on the
2026-09-11 Ubuntu 24.04 cloud host. They are **not** a booted Fedora guest,
not AT-SPI evidence, and not a stable-release GO.

| File | What it is |
|---|---|
| `WALKTHROUGH.md` | Reviewer notes for this capture |
| `report.json` | Machine-readable probe (`guestBoot` `NOT_RUN`, `stableRelease` `NO-GO`) |
| `fedora-container-attempt.txt` | Nested Fedora 44 container: image pull PASS, `dnf install image-builder` BLOCKED on DNS |

What this host proved:

- `/dev/kvm` present and nested virt enabled
- QEMU 8.2.2 with `accel=kvm` (KVM smoke PASS)
- Ubuntu OVMF at `/usr/share/OVMF/OVMF_CODE_4M.fd` (now a `vm-lib.sh` candidate)
- Podman 4.9.3 and guestfish 1.52
- Deadline + harness regressions PASS
- `registry.fedoraproject.org/fedora:44` pulls
- unified `image-builder` is **not** an Ubuntu package
- no Bunny OS QCOW2 exists here, so granted/denied guest journeys are `NOT_RUN`

Re-run the demo to refresh `out/<stamp>/`. Do not treat a missing QCOW2 as a
guest PASS. On a Fedora 44 image-builder host the same command is the
finish line after `make build-shell-test-image`.
