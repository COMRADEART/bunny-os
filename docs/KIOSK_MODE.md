# Kiosk and shared laboratory devices

Implementation: `enterprise/kiosk.py`. Tests: `tests/kiosk`.

## Restricted profiles remove capability, never protection

A kiosk profile may constrain settings panels, terminal availability, application installation, removable media, printing, network configuration, screenshot capture, and developer tools.

It may not touch update signature verification, Secure Boot enforcement, recovery availability, disk encryption, the broker allowlist, polkit requirements, privacy defaults, SELinux mode, or audit logging. Attempting any of these is a rejection naming the specific protection, not a generic error.

## Modes

`single-application`, `restricted-desktop`, `digital-signage`. Single-application mode requires a reverse-DNS application id; the other modes refuse one.

## Always available

A local administrator can always leave kiosk mode at the physical console. `administratorExitEnabled: false` is refused. A kiosk with no exit is a bricked device, and `docs/RECOVERY.md` already requires recovery to work from the local console without a network or an account.

## Other controls

Network allowlist by host pattern, local storage quota with a 64 MB floor, automatic recovery, and an idle session reset between 30 and 7200 seconds.

## Shared laboratory devices

Ephemeral or persistent-named sessions. An ephemeral session must clean up local user data on logout. Storage quotas apply per session.

Local model **weights** may be shared read-only across users, because they are large and identical. Bunny **memory** is never shared: `shareBunnyMemory: true` is refused outright. A shared laboratory device is exactly the situation where cross-user memory exposure would be most harmful, and `docs/MULTI_USER_QUALIFICATION.md` already treats any cross-user Bunny data exposure as a stable blocker.

Per-user separation continues to rely on the existing model in `docs/USER_AND_PRIVILEGE_MODEL.md`: separate XDG directories, separate Secret Service items, separate workspaces, and `assert_private_file` ownership and mode checks.

## Not evidenced

No kiosk or shared device has been deployed. Session cleanup, quota enforcement, and administrator exit have not been observed on hardware.
