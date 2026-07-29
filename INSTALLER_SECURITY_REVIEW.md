# Bunny OS installer security review

Date: 2026-07-28  
Disposition: source/static design accepted for destructive-fixture implementation review; beta approval denied

## Positive controls

- Anaconda/Blivet/cryptsetup/bootc/Fedora bootloader are selected instead of a Bunny raw-disk command engine.
- The frontend is unprivileged and the protocol has ten typed operations with strict fields, timestamps, nonces, session binding, and no generic command.
- Password/recovery/raw/provider secrets are rejected from protocol and first-run JSON; encryption uses protected references and public responses redact them.
- The only storage probe is a fixed, timeout/output-bounded `lsblk` argv. Device paths are syntax-constrained and serials/UUIDs are hashed.
- Plans bind disk ID/path/size, exclude installation media, and block read-only/mounted/small/unknown-sector/RAID/multipath targets.
- Erase requires disk-specific text plus a second confirmation; existing ESPs and entries are preserved by policy.
- Simulation `install.start` fails before writes without a production adapter.
- Structured logs redact credential/key/serial/UUID/content fields and are bounded.
- Media verification rejects symlinks/traversal, oversized/malformed manifests, bad detached signature, missing critical files, and hash mismatch.
- Live media disables GNOME automount and uses a fixed unprivileged ephemeral identity.

## Open findings

| Severity | Finding | Required closure |
|---|---|---|
| Blocker | no production Anaconda adapter or destructive execution evidence | narrow D-Bus adapter review and full disposable-disk integration/fault suite |
| Blocker | no live/beta image or UEFI/LUKS/Secure Boot VM | compose, inspect, sign, boot and test positive/negative chains |
| High | service peer credentials/token-file delivery not implemented end to end | AF_UNIX SO_PEERCRED, protected token/FD channel, cross-session/race/replay tests |
| High | Anaconda profile/bootc generic ISO compatibility unverified | exact Fedora 44 installed-form validation and package pinning |
| High | cleanup after partial partition/encryption/bootloader failure unexecuted | power/fault injection with mapping close, unmount, boot-order restoration evidence |
| High | media manifest is generated adjacent to artifacts, not proven embedded into ISO | embed and verify critical boot/root/recovery/Bunny files before installation |
| Medium | JSON Schema meta-validator unavailable | pinned Draft 2020-12 validator in CI/builder |
| Medium | first-run/GTK/live-session runtime untested | multi-user, symlink/TOCTOU/quota/lock/crash and accessibility suite |
| Medium | inherited broker/update/SELinux/signing blockers | close Phase 1/2 security reviews |

## Adversarial tests

Host tests pass for generic command, extra/secret/stale/malformed requests, token/cross-user/replay, target substitution, path traversal, media signature/hash failure, secret redaction, unsafe search roots, untrusted remotes, proprietary driver auto-selection, and source `shell=True` absence. They do not exercise kernel peer credentials, D-Bus policy, Polkit, actual devices, symlink races on Linux, compromised Blivet metadata, process environment, journal, or installation filesystem.

No secret or destructive target was used in this review.

