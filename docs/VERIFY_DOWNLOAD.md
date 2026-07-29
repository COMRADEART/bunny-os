# Verify a download

No official download exists. For a future candidate, obtain image, SHA-256 list, detached signature, manifest, and public-key fingerprint through independent trusted channels. Verify the signed manifest first, then every file hash, candidate/source commit, architecture/version, expiry/revocation, SBOM, and release notes. Stop on any mismatch, missing file, reused RC version, unknown key, or downgrade.

`make verify-stable-rc` is fail-closed and requires an external public key plus complete candidate directory. A checksum without signature is insufficient.
