# bunny-system-broker

`bunny-system-broker` is the only Bunny OS service allowed to translate a local Bunny request into a system operation. It listens only on a Unix-domain socket, authenticates every caller with `SO_PEERCRED`, rejects stale or replayed requests, validates an exact method schema, applies per-UID rate limits, obtains operation-specific Polkit authorization for every mutation, and records metadata-only audit events in journald.

The broker has no generic command, executable, argv, environment, file destination, package, systemd-unit creation, kernel-module, root-shell, D-Bus forwarding, or network-listener method. Its method table is `src/bunny_system_broker/protocol.py`; a request cannot reach a backend not present there.

Run unit tests from the repository root with `python -m unittest discover -s tests/broker -v`.
