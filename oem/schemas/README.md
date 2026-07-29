# OEM schema registry

Bunny OS keeps one JSON Schema registry so that `python scripts/task.py validate` checks every schema header and local reference in one place. The OEM schemas therefore live in `schemas/` alongside the rest:

- `schemas/oem-profile.schema.json` — the signed OEM profile, version 1
- `schemas/oem-qualification.schema.json` — the per-model hardware qualification report, version 1

This directory holds OEM-specific *policy data* rather than schemas: the overlay destination and content allowlists are defined as constants in `oem/validation/overlay.py` (`OVERLAY_ALLOWED_ROOTS`, `OVERLAY_FORBIDDEN_ROOTS`, `OVERLAY_ALLOWED_SUFFIXES`, `OVERLAY_FORBIDDEN_SUFFIXES`) so they are enforced by the validator that reads them, not duplicated in a file that could drift.

Every schema is paired with a hand-written validator and a rejection test, following the repository convention described in `schemas/README.md`. Runtime validation never calls `jsonschema.validate`; the schema documents the contract and the validator enforces it.
