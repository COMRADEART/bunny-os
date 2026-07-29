# Bunny Shell security review

Date: 2026-07-28  
Disposition: static/host-tested design acceptable for a developer-image VM attempt; runtime/release approval denied

## Positive controls

- GNOME/Mutter/portals/logind/AT-SPI remain authoritative; no compositor, capture stack, or notification daemon was invented.
- No Phase 2 root service, network listener, generic subprocess API, arbitrary shell, sudo/pkexec wrapper, provider credential store, or Bunny database connection exists.
- Desktop-entry parsing rejects shell syntax, privilege wrappers, unsafe executable/icon paths, unsupported field codes, malformed URL handlers, symlinks, and oversized entries.
- Natural-language routes become typed intents. Bunny requests do not become broker calls. Consequential system actions require confirmation and the existing broker/Polkit path.
- Search is explicit-location, metadata-only, capped, no-cloud, no-home-default, symlink-skipping, and deterministically purgeable.
- Terminal proposals never execute; unknown/shell/substitution commands are high risk and write/system/destructive proposals request checkpoints/approval/sandboxing.
- Workspace and Core snapshot state is private, same-user checked on POSIX, bounded, schema-versioned, and atomic. Credential-shaped workspace keys and unbounded approval grants are rejected.
- Lock projection removes bodies/actions and sensitive titles. Telemetry/clipboard history/plugin network default off.
- User services have no-new-privileges, strict system protection, home read-only except managed state, AF_UNIX only, namespace/MWX protection, restart limits, memory/task caps, and timeouts.
- Safe Shell and base GNOME preserve repair and conventional administration.

## Open findings

| Severity | Finding | Closure |
|---|---|---|
| Blocker | no built/booted Phase 2 image or GNOME runtime evidence | full image/inspection/QEMU interactive matrix |
| High | real Bunny Core summary authentication and action handoff unavailable | signed artifact; protocol/adversarial/replay/cross-user tests |
| High | GNOME extension only syntax/static tested | nested GNOME 50 plus crash/restart/safe-session tests |
| High | inherited broker/SELinux/update/Secure Boot gaps | close Phase 1 security report blockers |
| Medium | GTK action/portal/notification behavior unobserved | portal denial/revocation/lock/flood/malicious-markup tests |
| Medium | Nautilus extension/API compatibility unobserved | explicit selection, URI escaping, cross-user, no-upload tests |
| Medium | settings/search file race and quota behavior host-only | Linux multi-process/fuzz/symlink/TOCTOU tests |
| Medium | clipboard history UI not implemented | keep disabled or design Secret Service/private expiry flow |

No green secure badge is shown; shell status says unknown/unavailable until evidence exists. This review does not approve consumer/beta release.
