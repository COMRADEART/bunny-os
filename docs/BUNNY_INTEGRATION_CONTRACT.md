# Bunny–OS integration contract 1.0.0

This contract is independent from Bunny app protocol v3. A compatible image advertises contract `1.0.0` and accepted Bunny protocol versions including `3`. Major contract changes are breaking; optional minor fields require a new schema that old clients can ignore only where explicitly allowed.

## Installation and process ownership

Bunny OS consumes a signed upstream Linux release into `/opt/bunny/releases/<version>` and changes `/opt/bunny/current` only through an OS/Bunny packaging transaction. The Tauri Bunny Desktop binary supervises its packaged `bunny-core` and `ccgrep` sidecars and starts Core `app-server` with a loopback ephemeral port, token file, ready file, and `--desktop-managed`. Bunny OS does not start duplicate Core/app-server services. `bunny-desktop.service` is a per-user, opt-in autostart wrapper.

Phase 1 has only an explicit placeholder because the reviewed Bunny reports did not qualify signed Linux AppImage/RPM/DEB outputs. The required upstream deliverable is a signed release directory plus `bunny-artifact.json` containing version 0.2.0, protocol 3, source commit, contract range, architecture, paths, hashes, and modes. Bunny OS does not rebuild or copy Bunny source.

## Interfaces

- Discovery: `bunny-os-info --json`; `contractCapabilities` validates against `schemas/bunny-os-contract.schema.json`.
- Privileged operations: one UTF-8 JSON request and response per Unix socket connection, newline delimited, maximum 64 KiB request/1 MiB response.
- System/update status and power/recovery: exact broker allowlist documented in `docs/PRIVILEGED_BROKER.md`.
- OS settings: Desktop opens the conventional settings URI/control-center panel in its own user session; no broker action is needed.
- File/folder dialogs: Tauri invokes XDG Desktop Portal/native dialogs as the logged-in user.
- Notifications: freedesktop notification service in the caller's user session. The schema reserves typed OS notification envelopes; the root broker never injects UI into another session.
- Session/power/resume/lock/logout: logind and desktop-session APIs, subject to the user's session.
- URL scheme: `x-scheme-handler/bunny` through `art.comrade.Bunny.desktop`.

Every request includes exact fields: `contractVersion`, safe request ID, allowlisted method, typed `params`, RFC 3339 timestamp within 30 seconds, and unique nonce. Responses echo contract/version ID and return either typed `result` or a stable safe error. Cancellation names an existing request ID owned by the same UID.

Compatibility is checked at image build (artifact manifest), Desktop launch (manifest status/path), capability discovery, and every broker request. OS and Bunny releases may advance independently inside their declared range.

