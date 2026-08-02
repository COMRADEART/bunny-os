# Avahi Failure Disposition (dsq-1)

## The exact failure mechanism

Resolved from the prior installed-system evidence disks (the failing
boots' installed journals, read offline):

`avahi-daemon` 0.8 intermittently **aborts in its own shutdown path** when
SIGTERM arrives while interface state is still settling shortly after
startup:

```text
avahi_server_add_address() failed: Bad state          (×3, interfaces going down)
simple-protocol.c:575: simple_protocol_restart_queries: Assertion `server' failed.
ANOM_ABEND ... sig=6
avahi-daemon.service: Main process exited, code=dumped, status=6/ABRT
avahi-daemon.service: Failed with result 'core-dump'
```

In the two failing installations, SIGTERM reached avahi **0.8 s** after it
started (the prior harness powered down almost immediately after boot).
The third installation, where SIGTERM arrived ~5 s after start, tore down
cleanly (`avahi-daemon 0.8 exiting.`) — that margin is the entire
intermittency. This is an upstream avahi fragility: the simple-protocol
client handling races the server object's destruction during shutdown.

Stage 9 checklist: unit and socket activation are healthy (preset-enabled,
`Type=dbus`, socket present); network interface readiness is the trigger
condition, not a cause of failure to *start*; no hostname conflict, no
D-Bus unavailability, no SELinux denial (`avahi_t` context normal, ABEND
is sig=6 from its own assert), no restart loop (no `Restart=`), no
NetworkManager race on the start path.

## Behavior in dsq-1

**Zero avahi failures in 60 boots**, including:

- cell E (network disconnected at the VM boundary, 10/10): avahi starts,
  binds `lo` only, runs, and exits cleanly — the no-network case is
  handled by design and was never the failure mechanism. A missing
  network does not put the unit in `failed`, so there is nothing to
  excuse and nothing excused.
- every cell's poweroff (~75 s after readiness): clean
  `Deactivated successfully` teardown in all 60 records.

## Disposition

`SHUTDOWN_TEARDOWN_CRASH`, confidence **STRONGLY_SUPPORTED**, crash
process `avahi-daemon`. The gate verifies per record that any avahi
failure and any avahi coredump lie after shutdown initiation; a boot-phase
occurrence voids the disposition and blocks. The crash is real (upstream
bug, worth reporting to avahi with the assertion trace) but it is
exercised only when teardown begins within roughly a second of the daemon
starting — a condition produced by the prior harness's immediate
shutdown, not by any supported operating state of the product.
