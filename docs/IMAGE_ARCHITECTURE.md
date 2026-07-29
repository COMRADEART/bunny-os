# Image architecture

## Artifact chain

1. Build the reviewed `build/Containerfile` from `quay.io/fedora/fedora-bootc:44`; release mode requires the resolved `@sha256` base reference.
2. Install only explicit profile package sets and Bunny OS-owned files.
3. Record RPM inventory, source commit, source date epoch, base reference, profile, independent component versions, and build tool.
4. Store the derived image in local container storage.
5. Run unified `image-builder build --bootc-ref … --bootc-default-fs ext4 qcow2`.
6. Hash disk artifacts and generate external SPDX/CycloneDX SBOMs from the OCI image.

Build definitions are deterministic and isolated, but bit-for-bit reproducibility is **not yet demonstrated**: Fedora repository snapshots are not pinned and no repeated-build comparison ran. Release reports must carry that fact.

## Deployment state

- Image-managed: `/usr`, `/opt/bunny`, `/usr/lib/bunny-os`, system unit definitions.
- Persistent configuration: `/etc`, merged by the deployment backend.
- Persistent system/application state: `/var`.
- Persistent users: `/home`.
- Boot state: GPT, UEFI ESP and `/boot`, created by image-builder/bootc tooling.

bootc provides transactional staged deployments rather than an application-level file copier. A new deployment does not overwrite the booted deployment; failure leaves the previous boot entry. `bootc status` is the authoritative deployment view.

## Signatures and rollback

The Phase 1 updater verifies an Ed25519 channel manifest using an image-owned public trust store, rejects revoked/unknown keys, enforces expiry and monotonic sequence, checks architecture/contract/repository/digest, and then invokes a fixed `bootc switch`. Production must additionally configure registry signature enforcement and prove it with an unsigned-image negative test. Developer images are intentionally non-updating.

Recovery is both a Bunny-independent target inside each deployment and a separately buildable recovery QCOW2 prototype. The in-image target can inspect deployments, select rollback, inspect filesystems safely, disable Bunny/plugin startup, and export redacted diagnostics.

