# Beta images and channels

Channels are `developer`, `beta`, and future `stable`. Phase 3 defines developer and beta-candidate artifacts only; it does not publish stable metadata.

Supported build definitions are bootc OCI, QCOW2, raw disk, a `bootc-generic-iso` containing the offline beta payload, and the existing recovery QCOW2. OVA is omitted until a real tested need exists. Every published tuple requires checksum, detached signature, media manifest, package manifest, SPDX/CycloneDX SBOM, provenance, license/vulnerability results, installation guide, recovery guide, release notes, known issues, and hardware/VM status.

Builder sequence:

```text
make gate-phase-3
make build-beta-image
make build-live-image
make build-recovery-image
make verify-install-media
make vm-install-smoke
make vm-encrypted-install
make vm-upgrade-test
make sbom
```

Release mode additionally requires a digest-pinned Fedora base, immutable repository snapshot, exact tool versions, signed upstream Bunny artifact, offline media signing key supplied outside the repository, registry signature policy, two clean builds, and disposable-disk VM evidence. No artifact in this checkout currently satisfies these conditions.

