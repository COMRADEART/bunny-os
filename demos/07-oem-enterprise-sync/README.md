# Phase 7 demonstrations

Safe source-level demonstrations of OEM, enterprise-management, and optional encrypted-sync design. They validate profiles, evaluate records, and run host tests. No device is provisioned, no organisation is enrolled, no fleet is updated, and nothing is encrypted or uploaded.

Every demonstration includes a refusal step, because the refusals are the design.

Start with `demo-10-minutes.md`.

Expected current result: `make gate-phase-7-source` passes, and `make gate-phase-7`, `make gate-oem-pilot`, `make gate-enterprise-pilot`, and `make gate-sync-pilot` all remain blocked because the stable release is `NO-GO`. Never substitute these demonstrations for a pilot approval.

On a host without `make` — including the Windows development host these demonstrations were written on — use the underlying commands instead: `python scripts/task.py test-<area>`, `python scripts/phase7.py source-gate`, and `python scripts/phase7.py pilot-gate --kind <oem|enterprise|sync>`.
