# Building Bunny OS images

## Builder

Use a Fedora 44 x86-64 host/VM with UEFI/KVM, at least 8 vCPU, 16 GiB RAM, and 100 GiB free storage. Install Git, Make, Podman, unified `image-builder`, `osbuild-selinux`, QEMU, OVMF, libguestfs tools, Syft, ShellCheck, and systemd tooling. `image-builder` requires root for loop/mount operations and reads the root user's local container storage.

```text
make gate
make build-developer-image
make build-shell-image
make build-shell-test-image
make build-recovery-image
make inspect-image
make inspect-shell-image
make vm-smoke
make vm-shell-smoke
make sbom
make shell-sbom
make shell-security-scan
make shell-license-scan
```

Developer builds default to `quay.io/fedora/fedora-bootc:44`, resolve packages from Fedora at build time, and record the result; they are not bit-reproducibility evidence. A release-candidate build must use:

```text
export BUNNY_RELEASE_BUILD=1
export BUNNY_BASE_IMAGE=quay.io/fedora/fedora-bootc@sha256:<reviewed-digest>
export BUNNY_IMAGE_BUILDER_VERSION=<exact-version>
export BUNNY_PODMAN_VERSION=<exact-version>
# Add reviewed build/repositories/fedora-44-snapshot.repo.
make build-developer-image
```

The wrapper rejects a release base without `@sha256`, mismatched/unset tool versions, or a missing immutable Fedora snapshot repository. The package installer disables all other repositories and requires HTTPS plus RPM/repository-metadata signatures. Release engineering must also insert only public update keys, replace the explicit Bunny placeholder with a signed/hashes-verified Linux artifact, run two clean builds, compare semantic inventories and disk contents, sign the OCI/artifacts outside pull-request CI, and archive logs/provenance/SBOM/checksums.

The unified command used after OCI composition is:

```text
sudo image-builder build --bootc-ref localhost/bunny-os-developer:<commit> --bootc-default-fs ext4 qcow2
```

Output is under `build/out/<profile>`. No private signing key is accepted by the Containerfile or stored in this repository. Builds copy only declared directories into the container stage and do not read the adjacent Bunny source repository.

Phase 2 profiles `shell` and `shell-test` compose the same GNOME/Mutter Wayland foundation with Bunny session/extension/services/assets. `shell-test` is the QEMU interactive test artifact; it is not a release channel. Before accepting either, run strict GLib schema compilation, desktop-entry validation, GNOME extension packing/nested load, installed-form systemd verification, image inspection, SBOM/scans, and the manual matrix in `tests/vm/PHASE_2.md`.
