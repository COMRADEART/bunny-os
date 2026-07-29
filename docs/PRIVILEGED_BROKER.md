# Privileged broker

`bunny-system-broker` is a root system service activated only by `/run/bunny/broker.sock`. It uses no network family, shared password, provider credential, shell, dynamic executable, arbitrary environment, caller-supplied path, package install, service creation, kernel module operation, or general D-Bus forwarding.

## Allowlist

Read: system/service/network/update/recovery status, bootc deployment list, and local hardware inventory. Mutations: shutdown/reboot/suspend; check/stage/install a signed OS update; select the previous bootc deployment; schedule a fixed recovery mode; export a redacted diagnostic bundle. Service status is further restricted to a fixed unit-name set.

Every parameter validator rejects unknown keys, wrong types, excessive sizes, NULs, non-allowlisted services, and command-like values. Backend subprocesses use absolute executables, fixed argv structure, a fixed `PATH`/locale/home, no stdin, capped output, process-group cancellation, and per-operation timeouts.

## Authentication and authorization

The socket is connectable by local processes so every regular desktop user can discover safe machine status. Connection is not authentication: the broker obtains unforgeable kernel peer credentials before parsing JSON, rejects system UIDs, verifies `/proc` identity/start time, rate-limits per UID, rejects nonce replay/stale requests, and uses Polkit for every mutation. Read operations never return another user's state.

## Audit and diagnostics

Journald records timestamp, broker version, UID, PID, request ID, method, outcome, and latency—never parameters, environment, tokens, prompt text, or file content. Support export collects only selected unit logs and release metadata, applies credential-pattern redaction, writes into a fixed non-listable system directory, transfers only that 0600 archive to the authenticated requesting UID/GID, and expires it through tmpfiles.

The systemd unit applies empty broker capabilities, `NoNewPrivileges`, strict filesystem protection with two write paths, hidden `/proc`, private devices/tmp, AF_UNIX-only syscalls, no IP, namespace/realtime/SUID restrictions, memory W^X, restart limits, and timeouts. Linux CI must record `systemd-analyze security bunny-system-broker.service`; no score is fabricated on this host.
