# Build the images

On the pinned Fedora 44 builder:

```text
make gate-phase-2
make build-shell-image
make build-shell-test-image
make inspect-shell-image
make shell-sbom
```

For the complete privileged gate use `FULL_GATE=1 make gate-phase-2`. Archive `build/out/shell` and `build/out/shell-test`. A successful OCI build alone is not a desktop-boot result.
