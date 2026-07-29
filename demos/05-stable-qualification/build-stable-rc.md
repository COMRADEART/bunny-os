# Build a stable RC

On a trusted Fedora/KVM builder with a clean immutable commit, set a new `BUNNY_RC_VERSION` and run `make build-stable-rc`. The script requires Podman, image-builder, Syft, OpenSSL, and complete live/beta/recovery outputs. Current host must fail closed.
