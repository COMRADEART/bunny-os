# ADR-014: First-run architecture

- Status: accepted
- Date: 2026-07-28

## Decision

Use a separate, unprivileged `bunny-first-run` user application after installation. Anaconda owns installation and the initial Linux account. First-run owns only per-user preferences and typed requests to conventional system settings or the existing Phase 1 broker.

The resumable flow is welcome, language/region, keyboard, privacy, updates, profile, Bunny introduction, optional provider, optional local model, explicit search locations, permissions, optional backup/recovery, and finish. Closing it never blocks the desktop. Telemetry, cloud AI, remote diagnostics, capture devices, broad indexing, and plugin network remain off/denied by default.

Credential values use Secret Service and are represented only by opaque aliases in state. Provider/model/search/backup steps are skippable. Completion is a private per-user marker written atomically; each Linux user's state is isolated.
