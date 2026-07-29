# Verify media

Run `make verify-install-media`, or `bunny-os --json media verify --root <media-root> --manifest <manifest> --signature <sig> --public-key <key>`. Demonstrate a valid result, changed-byte checksum failure, missing critical file, traversal attempt, and bad signature. A critical failure must stop installation.

