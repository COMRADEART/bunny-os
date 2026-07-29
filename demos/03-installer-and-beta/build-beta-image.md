# Build beta media

On the Fedora 44 builder, configure the digest-pinned base, repository snapshot, exact tools, signed Bunny artifact, and offline media key. Run `make build-beta-image`, then `make build-live-image` and `make build-recovery-image`. Archive `build/out` without overwriting a prior evidence run.

Expected source-only result here: blocked before artifacts because Podman/image-builder and Linux loop/mount support are absent.

