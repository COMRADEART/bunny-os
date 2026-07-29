# Verify a stable RC

Set `BUNNY_STABLE_PUBLIC_KEY` to an independently authenticated public key and `BUNNY_STABLE_CANDIDATE_DIR` to the immutable directory, then run `make verify-stable-rc`. It validates the complete manifest, hashes, safe paths, and detached signature. Missing artifacts fail.
