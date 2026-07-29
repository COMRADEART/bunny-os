# Authenticated device pairing

```text
make test-sync-crypto
```

Show the pairing display: the new device name and a key fingerprint in four groups of four characters, with the instruction to compare it on the other device.

Refusal, the important one first:

- Parse a session with key material B while the user confirms the fingerprint derived from key material A. Pairing is refused with "the sync service may have substituted the device key". This is the server-side key substitution defence, and it works because the fingerprint is recomputed locally from the key actually received rather than taken from the server's record.
- Replay a completed session id: refused.
- Present an expired session: refused.
- Offer `one-time-code` when the initiating device required `existing-trusted-device`: refused as a downgrade.
- Pair a device with itself: refused.

Then show that a completed pairing grants zero collections. Selective sync defaults to granting nothing.
