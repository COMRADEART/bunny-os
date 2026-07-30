# ADR-026: Remote administration boundary

- Status: accepted
- Date: 2026-07-29

## Decision

Remote administration is a closed set of 14 typed operations. There is no generic remote shell, no command execution, and no operation that accepts a command, argv, script, or arbitrary path. A request naming a shell-shaped operation is refused with a specific message so the attempt is visible in the audit trail rather than looking like a typo.

Destructive operations carry preconditions that scale with ownership. Removing organisation data from a device is routine; fully resetting one requires an organisation-owned device, multi-factor administrator authorisation, a disclosed prior policy, an explicit non-empty scope, and a UUID audit correlation id recorded before execution — plus device-side confirmation where policy demands it.

A personally owned device is never fully wiped or cryptographically erased remotely, regardless of authorisation.

## Why no remote shell

It is the single feature that would make the fleet server the most valuable target on any network it manages. With a typed surface, a fully compromised control plane can annoy a fleet — pin a channel, schedule restarts, disable organisation applications — but cannot execute code or read user data. With a shell, a compromised control plane owns every device.

The convenience argument is real and is declined. Help-desk work is served by the specific operations that help-desk work actually needs: check for updates, restart, lock, and request a redacted diagnostic status.

*An off-by-default shell for advanced environments* was considered and deferred rather than added. Such a capability would need its own design, its own strong authentication, its own audit semantics, and exclusion from the stable consumer profile. None of that is designed, so the capability does not exist. `docs/NETWORK_SECURITY.md` records the analogous decision for remote Bunny access: postponed, with a separate ADR required, and changing a listen address is not an acceptable shortcut.

## Consequences

Genuine remote-administration needs outside the 14 operations require a new typed operation with a code change, a schema update, and a review. Organisations that require arbitrary remote execution are not served by Bunny OS and should be told so plainly rather than sold a workaround.

Role separation limits the boundary further: `enterprise/roles.py` gives no single role routine unrestricted authority, and `organisation-owner` is break-glass with a warning on routine use.
