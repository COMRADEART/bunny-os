# Device pairing

Implementation: `sync/pairing.py`. Tests: `tests/cryptography`.

## The attack this is built around

Server-side key substitution. A compromised sync service offers its own public key as the new device's key and thereafter receives every collection key wrapped for it. Transport security cannot prevent this, because the service terminates the transport.

## The defence

Both devices compute a short authenticator from the actual key material plus the pairing session id. The user compares them out of band. If the service substituted a key, the authenticators differ and pairing is refused.

The authenticator is never taken from the server's record. `parse_session` recomputes it locally from the key material the device actually received, which is what makes substitution detectable rather than merely detectable-in-principle.

A mismatch is reported as a substitution warning, not a typo:

> Pairing refused: the confirmed code does not match the code derived from the key this device received. The sync service may have substituted the device key. Do not retry without verifying the other device out of band.

## Methods, strongest first

`existing-trusted-device`, `passkey-backed-account`, `verified-qr-exchange`, `recovery-secret`, `one-time-code`.

A session may not downgrade to a weaker method than the initiating device required.

## Other prevented failures

Session replay, via a consumed-session-id set. Expiry, with a 10-minute maximum lifetime. Self-pairing. Silent addition, because completion requires a confirmed authenticator. QR substitution, because the QR carries the session and key material that feed the authenticator rather than an opaque approval token.

## What the user is shown

The new device name and the key fingerprint, grouped in four blocks of four characters from a 32-character alphabet that excludes visually ambiguous letters, so it can be read aloud reliably. Comparison is constant-time and tolerant of case and surrounding whitespace.

## After pairing

The new device holds no collection keys. Selective sync defaults to granting nothing, and the user chooses which collections to grant. See `docs/ENCRYPTED_SYNC.md`.
