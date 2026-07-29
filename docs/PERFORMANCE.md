# Bunny Shell performance

Targets for the Fedora 44/QEMU reference tuple are: interactive desktop ≤15 s after authentication; launcher and Bunny command surface ≤150 ms warm; local result response ≤100 ms for a 20,000-entry metadata index; settings ≤500 ms warm; workspace switch delegated to Mutter ≤250 ms; notification first render ≤100 ms; Bunny-owned idle aggregate ≤250 MiB RAM and ≤1% of one CPU; no sustained idle GPU work attributable to Bunny.

Targets are acceptance thresholds, not results. On the Windows source host, `make performance-baseline` measured only deterministic Python operations. The 2026-07-28 run recorded:

| Operation | Median | p95 | Max |
|---|---:|---:|---:|
| typed intent routing | 0.0008 ms | 0.0011 ms | 0.0155 ms |
| one-entry metadata search | 0.1918 ms | 0.4146 ms | 0.5367 ms |
| workspace JSON read | 0.2713 ms | 0.5558 ms | 0.7190 ms |
| settings JSON read | 0.0351 ms | 0.0443 ms | 0.2009 ms |

These figures do not measure GTK, GNOME Shell, login, graphics, IPC, actual 20,000-entry search, notification render, idle CPU/memory/GPU, VM, or hardware. Full results must use `systemd-analyze`, `/usr/bin/time`, cgroup accounting, GNOME/Mutter frame tools, and repeated cold/warm runs on the documented VM.
