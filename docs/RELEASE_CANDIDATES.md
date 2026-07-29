# Stable release candidates

Candidate sequence is `stable-rc1`, `stable-rc2`, `stable-rc3` as needed, then stable. Every RC pins a 40-hex source commit and includes signed ISO/raw/QCOW2/recovery ISO, checksums, detached signatures, SBOM, package manifest, provenance, release notes, known issues, third-party notices, install/update/rollback/recovery/hardware results, and security/privacy/accessibility reviews.

Any code, package, configuration, documentation affecting recovery, or artifact change creates a new RC. During soak there are no features; only approved high-severity fixes. Artifacts are immutable and versions are never reused. Current candidate: none.
