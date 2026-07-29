# Bunny OS Phase 1 image build report

## Result: blocked on host; no artifact claimed

The image was not built. This Windows host had no Podman/Docker, Linux image-builder, loop/mount environment, QEMU, or WSL distribution. Therefore there is no OCI digest, QCOW2, recovery image, package inventory from a composed image, artifact checksum, SBOM, vulnerability scan, licence report, or reproducibility comparison to report.

Definitions are present for:

- base `quay.io/fedora/fedora-bootc:44` (release wrapper requires a reviewed `@sha256`);
- developer/minimal/desktop/recovery profiles;
- Fedora-only categorized packages;
- explicit update/Bunny placeholders;
- `sudo image-builder build --bootc-ref <local-image> --bootc-default-fs ext4 qcow2`;
- provenance, checksums, image inspection, SPDX/CycloneDX, Grype, and license-policy outputs.

Exact next command on the documented Fedora builder:

```text
make gate
make build-developer-image
make build-recovery-image
make inspect-image
make sbom
make security-scan
make license-scan
```

Acceptance requires recognized artifacts under `build/out`, complete logs/provenance, reviewed package inventory, no secrets/world-writable system path/unexpected listener, two clean-build comparison, and a digest-pinned release rerun. Status remains **definition ready, artifact unvalidated**.

## Phase 2 update

No Phase 2 image was built. New `shell` and `shell-test` profiles include GNOME 50 integration, GTK/PyGObject/libadwaita, AT-SPI/Orca/mousetweaks, Bunny session/extension/services/schemas/apps/themes/icons/wallpapers, and the existing conventional desktop/recovery tools. `developer` and `desktop` now include the shell package set.

The developer/shell/shell-test/recovery build, inspect, VM, SBOM, scan, and licence Make targets were invoked on 2026-07-28. Shell-backed targets stopped at `bash: No such file or directory` because Bash was not on Make's Windows PATH; the licence scan failed because no SPDX file existed. An explicit MSYS2 Bash `-n` parse of seven scripts passed. Podman, unified image-builder, QEMU, Syft, Grype, and a Linux mount/loop environment remain absent.

No OCI digest, QCOW2, package inventory, checksum, SBOM, scan, or repeated-build result exists. Source integration must not be mistaken for a bootable Phase 2 artifact.

## Phase 3 update

New definitions add beta QCOW2/raw, a bootc-generic live installer ISO with a separate offline payload reference, recovery reuse, Anaconda Web UI/Blivet packages and profile, UEFI menu, ephemeral/no-automount live configuration, media manifest/signing/verification hooks, essential offline applications, and disposable QEMU launchers.

No Phase 3 artifact was built. Therefore no ISO/raw/QCOW2/recovery digest, embedded payload, checksum, detached signature, SBOM, package manifest, scan, provenance, Secure Boot chain, or repeated-build comparison exists. The adjacent manifest generator is not evidence that verification metadata is embedded into the ISO. Status remains definition-only and beta publication blocked; see `BETA_IMAGE_REPORT.md`.

## Phase 5 update

No Phase 4 public-beta image or Phase 5 stable candidate exists. The beta build was attempted on 2026-07-29 and stopped at the required Podman check. Stable build/sign/verify scripts now require a clean immutable commit, new RC version, trusted builder tools, complete artifact set, external private key, authenticated public key, hashes, and detached signature. They were not used to create or publish media.

Stable ISO/raw/QCOW2/recovery ISO, checksums, signatures, SBOM, package manifest, provenance, notes, and notices: **none produced**. Reproducibility, license, malware, image inspection, and signing status remain `NOT RUN`/`BLOCKED`.

## 2026-07-29 validation remediation

The historical results above remain the outcomes of their phase runs. A later
local remediation run provisioned Fedora 44 under WSL with Podman 5.8.4,
unified image-builder 76.0.0, QEMU 10.2.2, libguestfs, Syft 1.50.0, and Grype
0.116.1. It fixed three artifact-path defects found by executing the real gates:

- bootc QCOW2 inspection now mounts the filesystem labelled `root` and locates
  the immutable OSTree deployment instead of using removed `virt-ls -i`
  auto-inspection;
- beta `qcow2` and `raw` outputs are composed with separate image-builder
  invocations, as required by the current CLI;
- the health service can write both state paths used by its active probe.

Disposable validation commit `10c8b3d0aade0dc0d5929eaa134773ac360ae7e3`
produced a beta QCOW2 (2,101,097,472 bytes) and raw disk (10,737,418,240 logical
bytes). Their SHA-256 digests are respectively
`3d49ebc1a3c70af0d454ff490943dbd97238b314bb4b443bb2bbdac27fa61fe1`
and `9123a77c89fbf0062a22931037ed4384e704f57f466944d86a0cbf90402dc46d`.
`qemu-img check` found no QCOW2 errors and bootc-aware libguestfs inspection
passed.

These are local, unsigned, unpinned validation artifacts in a disposable WSL
clone. They are not archived stable candidates and do not close missing live
ISO, independent recovery ISO, signed manifest, reproducibility, installation,
hardware, or protected-approval gates.
