# Bunny OS installer performance report

Date: 2026-07-28  
Scope: Windows host, deterministic source operations only

| Operation | Median | p95 | Max |
|---|---:|---:|---:|
| synthetic Windows disk metadata parse | 0.0128 ms | 0.0149 ms | 0.0946 ms |
| encrypted alongside partition plan | 0.0106 ms | 0.0118 ms | 0.0706 ms |
| complete protocol plan validation | 0.0050 ms | 0.0054 ms | 0.0278 ms |

Command: `python scripts/installer-performance.py` (500 iterations per operation).

These results only show that small pure-Python host operations have no obvious latency problem. Live boot, installer startup, real disk probe, deployment speed, first installed boot, first-run launch, Bunny Shell login, application installation and update staging are unmeasured. No universal install-time claim is made.
