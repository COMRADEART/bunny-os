# Device revocation and key rotation

```text
make test-device-revocation
```

Revoke a paired device and show the plan: every collection the device could read is rotated, and the new generation is rewrapped for the remaining active devices only.

Then show the honest notes returned with the plan:

- Objects the revoked device already downloaded cannot be retracted; only future objects are protected.
- On suspected compromise the user root key rotates too, because a compromised device may hold a copy.

Refusal:

- Present a keyring that still wraps a collection key for a revoked device: refused, because revocation must rotate and rewrap. This is the enforced meaning of "revocation rotates relevant access".
- Revoke the last remaining active device: refused. That is account deletion, not revocation.
- Revoke an already-revoked device: refused.

Show that adding a device rewraps without rotating, and that the plan states plainly that the new device can read the granted collections' existing objects.
