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
