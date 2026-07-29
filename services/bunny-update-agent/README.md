# Bunny update agent

This root-only one-shot service verifies a small, signed channel manifest and stages an exact OCI digest with `bootc`. It accepts only `status`, `check`, `stage`, and `install` as systemd instance names. Bunny processes cannot invoke it directly; the broker performs caller authorization and starts a fixed unit.

Release images must provision at least one Ed25519 public key in `/usr/share/bunny-os/update-keys`, a signed revocation document, and `/etc/bunny-os/update.json`. The developer profile intentionally ships with updates disabled and no release trust key.

