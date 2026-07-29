# Bunny OS desktop performance report

Date: 2026-07-28  
Host scope: Windows source checkout; no GNOME/VM/GPU

`python scripts/performance-baseline.py` completed. Results:

| Operation | Median | p95 | Max |
|---|---:|---:|---:|
| typed intent route | 0.0008 ms | 0.0011 ms | 0.0155 ms |
| metadata search, one fixture entry | 0.1918 ms | 0.4146 ms | 0.5367 ms |
| workspace JSON read | 0.2713 ms | 0.5558 ms | 0.7190 ms |
| settings JSON read | 0.0351 ms | 0.0443 ms | 0.2009 ms |

These measurements establish only that deterministic host logic has no obvious latency regression in a tiny fixture. Login, GTK launch, GNOME overview, real 20,000-entry search, workspace switching, settings/notification/command-surface rendering, idle memory, CPU, GPU, multi-monitor, cold cache, and Bunny IPC were not measured.

Reference targets and the required Fedora 44 measurement method are in `docs/PERFORMANCE.md`. No target is marked passed from these microbenchmarks.
