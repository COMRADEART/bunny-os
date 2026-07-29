# Encrypted sync and offline conflict

```text
make test-sync
python -c "import json, sync.metadata as m; print(json.dumps(m.describe_visible_metadata(), indent=2))"
python -c "import json, sync.crypto as c; print(json.dumps(c.backend_status(), indent=2))"
```

Show the metadata table: what the service can see and what it cannot. Then show `backend_status()` reporting `available: false` — no reviewed cryptographic backend is installed, so nothing is encrypted and nothing is uploaded. A stub returning plausible ciphertext would be worse than this refusal.

Refusal:

- Add a `title` or `filename` to an envelope: refused as plaintext metadata.
- Add a `wrappedKey` or `passphrase`: refused, because the operator never receives a decryption key.
- Offer object version 3 when the device holds version 5: refused as server rollback.
- Offer a different ciphertext at the same version: refused as substitution.
- Claim "zero knowledge" in documentation text: refused, because object size, upload time, version count, and device count remain visible.

Offline conflict: edit a memory on device A while deleting it on device B, then resolve. The deletion is kept and the edit is queued for review. A deleted sensitive memory is never silently resurrected. Repeat with a file and show a conflict copy instead, with nothing overwritten.
