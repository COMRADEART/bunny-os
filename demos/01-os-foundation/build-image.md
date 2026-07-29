# Build the image

```text
make gate
make build-developer-image
make inspect-image
make sbom
make security-scan
make license-scan
```

Show `build/out/developer/provenance.json`, `SHA256SUMS`, release metadata, package inventory, and both SBOM formats. A release rehearsal sets `BUNNY_RELEASE_BUILD=1` and a reviewed digest-pinned base.

