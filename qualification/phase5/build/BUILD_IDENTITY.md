# The Phase 5 build

**The Phase 4 Alpha artifact is untouched.** `build/out/beta` held it —
`sourceCommit e906a48793d7`, the frozen release candidate — and the build
refuses to write into a non-empty output directory. It was **moved**, not
deleted, to `/root/bunny-build-archive/beta-phase4-rc-e906a48793d7-20260818T014208Z`
on the builder, where its `BUNNY-MANIFEST.json`, `SHA256SUMS`, `provenance.json`
and both disk images remain byte-for-byte as Phase 4 left them. Nothing in this
build reuses Phase 4's name, tag, filename or digests.

## Identity

| | |
| --- | --- |
| Source commit | `e501218f2fe0105e5fc92bdf94fd6b3c87d6c470` |
| Build id | `e501218f2fe0.1787016937` |
| `SOURCE_DATE_EPOCH` | `1787016937` |
| Image reference | `localhost/bunny-os-beta:e501218f2fe0` |
| Image id | `70f677701e1a16efd740f075cb05b14a6a04304e38141576e893b23655543d58` |
| Channel | `alpha` (profile `beta` — see `build/scripts/build-alpha-image.sh`) |
| Base | `quay.io/fedora/fedora-bootc:44` |
| Built | 2026-08-18T02:13:04Z |

| artifact | sha256 | bytes |
| --- | --- | ---: |
| `bunny-os-0.1.0-alpha-e501218f2fe0.1787016937-x86_64.qcow2` | `b4dd95f3cb3f7d4b4419c120e04e4375f4a176f0fd0a0ee5f2c91ba5de99dcef` | 2761657344 |
| `bunny-os-0.1.0-alpha-e501218f2fe0.1787016937-x86_64.raw` | `7fadbec459fe9cd92c461db70b676876bd9774c3875c467bbf2b5724245a77f0` | 13721665536 |
| `bunny-os.oci.tar` | `6ea132359756e48e3ff98f941a2c5286537a92210f38581debca4028be556536` | 2953932800 |

The running system reports the same identity: `/usr/lib/os-release` carries
`BUNNY_OS_BUILD_ID=e501218f2fe0.1787016937` and
`BUNNY_OS_COMMIT=e501218f2fe0105e5fc92bdf94fd6b3c87d6c470`, and
`release.json` agrees.

**This is an Alpha build and makes no reproducibility claim.** The build script
says so itself, and `provenance.json` records
`repeatedBuildComparisonPerformed: false`. The three-builder reproducibility
result belongs to the commits that were measured for it, not to this one.

## What it is for

1. **§3.** Two SVG assets were repaired in the tree; only an image can show
   they are repaired *as installed*. See `../assets/ASSET_VERIFICATION.md`.
2. **§20.** Update and rollback need an N+1 to exist. Until this build there
   was exactly one image, so both matrices read `NOT_RUN` for want of a
   second, not for want of a harness.

## The blocker that was not one

This build was recorded as blocked on host storage for the whole first part of
Phase 5. That was wrong, and the way it was wrong is worth keeping.

The original failure was `grype podman:` reporting `no space left on device`.
It was diagnosed as "the host volume has 8.6 GB free", and from then on every
downstream item inherited "blocked on disk" without anyone re-measuring.

Two errors, compounded:

* the failure was against **`/tmp`, which is tmpfs — RAM, 7.8 GB.** `TMPDIR`
  pointed at real disk is the whole fix, and `findmnt -no FSTYPE /tmp` says so
  in one line;
* "the host volume" conflated Windows `C:` with the ext4 volume the builder
  actually writes to. The WSL VHDX was already 731.531 GB on disk with 350 GB
  used inside, so ~380 GB of it was allocated and free. **Measured: writing
  1 GiB, then 20 GiB, inside WSL moved the VHDX by zero bytes and `C:` free
  space by zero bytes** (7.848 GB before and after each). `route/space-probe.sh`
  under `../security/` is that probe.

The build then ran, exported a 2.96 GB OCI archive, and produced a 13.7 GB raw
image without difficulty.

The lesson is the one this phase keeps finding: an inherited claim about the
environment is still a claim, and it needs a measurement like any other.

## Held open

The build was killed three times — at steps 14, 15 and 20 of 35 — before it
completed, each time leaving a log that simply stops with no error in it. WSL
terminates a distro's processes when the last Windows client exits;
`vmIdleTimeout=-1` governs the utility VM, not the distro, and does not help.
`/sbin/init`'s start time read "three seconds ago" on essentially every fresh
`wsl.exe` invocation, which is how that shows up.

`systemd-run` inside the distro does not survive it either: systemd goes with
everything else. A detached Windows-side client does, and
`/home/bunny/p5-ops/hold.sh` is that one job — `exec sleep 86400` and nothing
else. It is deliberately not the watcher: the first attempt combined the two,
the watcher misread an earlier attempt's completion line as this run's, exited,
and took the hold with it while the build was at step 15 and healthy.
