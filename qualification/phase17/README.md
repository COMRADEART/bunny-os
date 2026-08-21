# Phase 17 — multi-source external evidence operations

Phase 17 composes the Phase 9–16 engines into one artifact-specific view of
the five external authorization-floor sources. It creates no evidence ledger,
does not rebuild or sign artifact `e906a48793d7`, and never turns operational
readiness or fixture success into source satisfaction.

The operator is `tools/external_floor_ops.py`. Every evidence command names a
source, path, artifact, evidence ID, or cut ID as applicable; there is no
implicit “latest” selection. `receive` is the only evidence-mutating command
and delegates verbatim to Phase 9 `register`. `cut` writes only a sealed
cross-source reference record under `cuts/`; it never copies evidence.

Run from the repository root:

```text
python qualification/phase17/tools/external_floor_ops.py prepare --source hardware --out <outside-repository-directory>
python qualification/phase17/tools/external_floor_ops.py inspect --source hardware --path <record.json> --artifact e906a48793d7 --evidence-id HW-001
python qualification/phase17/tools/external_floor_ops.py receive --source hardware --path <record.json> --artifact e906a48793d7 --evidence-id HW-001 --received-on YYYY-MM-DD --submitted-by <operator>
python qualification/phase17/tools/external_floor_ops.py validate --source hardware --path <record.json> --artifact e906a48793d7 --evidence-id HW-001
python qualification/phase17/tools/external_floor_ops.py bind --source hardware --path <record.json> --artifact e906a48793d7 --evidence-id HW-001
python qualification/phase17/tools/external_floor_ops.py evaluate --source hardware --path <record.json> --artifact e906a48793d7 --evidence-id HW-001 --as-of YYYY-MM-DD
python qualification/phase17/tools/external_floor_ops.py cut --cut-id CUT-017 --artifact e906a48793d7 --as-of YYYY-MM-DD
python qualification/phase17/tools/external_floor_ops.py assemble --cut-id CUT-017 --artifact e906a48793d7
python qualification/phase17/tools/external_floor_ops.py floor-status --artifact e906a48793d7
python qualification/phase17/tools/external_floor_ops.py status --artifact e906a48793d7
python qualification/phase17/tools/external_floor_ops.py sync-status --artifact e906a48793d7
python qualification/phase17/tools/verify_phase17.py
```

Current state is derived from the live Phase 9 ledger and owner-engine outputs
in `FLOOR_STATUS.json`; it is not stated here as a constant.
