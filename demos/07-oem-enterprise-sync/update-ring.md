# Staged fleet update, pause, and withdrawal

```text
python scripts/phase7.py fleet-simulation --devices 500
make test-fleet
```

The simulation walks internal test at 100%, early validation at 10%, general deployment at 50% then 100%, then a pause, then a withdrawal. Show `devicesOffered` dropping to 0 for pause and withdrawal, and `signatureVerificationRequired` staying true at every step.

Refusal:

- Set `signatureVerificationRequired: false`: refused. Signature verification is not a fleet setting.
- Promote `internal-test` straight to `general-deployment`: refused, because it skips early validation.
- Set `forcedRestart: true` with no policy reference: refused.
- Report a `failed` update with `rollbackAvailable: false`: refused, because a failed fleet update must preserve rollback.
- Add `activeApplication` to an update state report: refused with a privacy-specific message, not a generic unknown-field error.

The simulation writes `build/out/phase7/fleet-simulation.json`, which states that it is arithmetic and not production-readiness evidence.
