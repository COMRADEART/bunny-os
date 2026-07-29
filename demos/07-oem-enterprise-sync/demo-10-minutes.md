# Ten-minute demonstration

```text
python oem/bin/bunny-oem --json validate-profile --profile oem/profiles/example-validated-integrator.json
python oem/bin/bunny-oem --json provision
make test-policy
make test-multitenancy
python scripts/phase7.py fleet-simulation --devices 500
make gate-oem-pilot
```

1. A signed OEM profile validates.
2. The factory executor reports itself unavailable and exits 78 rather than pretending to provision.
3. Policy refuses to disable update signature verification, and refuses an execution channel in `desiredState`.
4. Organisation A cannot read organisation B's devices.
5. A staged rollout pauses and withdraws, with signature verification required at every step.
6. The OEM pilot gate is blocked, and names the unmet stable-release gates.

The point of the last step is that it fails. Nothing here is a pilot approval.
