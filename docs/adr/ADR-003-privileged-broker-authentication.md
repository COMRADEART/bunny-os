# ADR-003: Privileged broker authentication

- Status: accepted
- Date: 2026-07-28

Use a systemd-activated Unix-domain socket at `/run/bunny/broker.sock`. Linux `SO_PEERCRED` supplies PID/UID/GID; the broker revalidates UID and process start time in `/proc` to resist PID reuse. Requests have a 30-second timestamp window and per-UID replay-protected nonce. There is no password, token file, TCP listener, or inherited client environment.

Read-only machine status is available to regular local users and contains no per-user data. System-service UIDs are rejected. Mutating operations require an active/online logind user plus exact Polkit action (`power`, `update`, `rollback`, `recovery`, or `diagnostics`). Root recovery tools may call the same fixed backend.

D-Bus was not selected as the Phase 1 wire transport because Bunny already needs a small versioned JSON contract and cancellation across languages. Polkit remains the native authorization authority. Short-lived signed tokens would add key lifecycle and replay complexity without improving same-host peer identity. Socket mode `0666` permits connection attempts, not authorization: the kernel supplies unforgeable peer credentials and the broker validates every request before execution.

