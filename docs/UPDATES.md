# OS updates and rollback

OS updates and Bunny application updates are separate. OS manifest schema is 1; contract is 1.0.0; bootc is the deployment/rollback backend. The fixed sequence is:

1. fetch an HTTPS channel manifest (256 KiB cap, 30-second network timeout);
2. verify Ed25519 signature against image-owned non-revoked key;
3. validate exact schema, channel, expiry, architecture, contract, Bunny compatibility, trusted repository, digest, and monotonic sequence;
4. require installed/download size plus a 2 GiB reserve;
5. invoke `bootc switch <allowlisted-ref>@sha256:<digest>` in a root-only one-shot unit;
6. persist highest sequence atomically and report a staged/reboot-required deployment;
7. reboot only after explicit `update.install` authorization;
8. run offline required health checks and preserve the previous deployment.

Bad signature, unknown/revoked key, rollback sequence, wrong channel/arch/contract/Bunny version, firmware requirement that cannot be safely compared, insufficient disk, interruption, bootc failure, or timeout moves status to `failed` without changing the accepted sequence. A successful `bootc switch` still relies on bootc/registry digest verification. Production registry signature policy and an unsigned-image rejection test are blockers.

Key rotation ships overlapping public keys in a signed old image, changes manifest `keyId`, then later distributes a signed revocation list. Private keys remain offline/protected and never enter PR CI. Developer profile has no key, a `.invalid` URL, and updates disabled. The first-boot preference uses the authenticated broker to create/remove a fixed root-owned marker and enable/disable the timer; denial leaves automatic checks off.

`bootc rollback` selects the prior deployment; the boot menu remains the Bunny-independent fallback. Health failure handling/automatic boot counting must be proven in the VM matrix before beta.
