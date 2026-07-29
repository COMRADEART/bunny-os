# Security tests

```text
make test-oem
make test-factory
make test-enrolment
make test-policy
make test-fleet
make test-multitenancy
make test-sync
make test-sync-crypto
make test-airgap
```

The sixteen required security cases and where each is covered:

```text
factory credential leakage        tests/factory
unsigned OEM profile             tests/oem
malicious OEM overlay            tests/oem
enrolment-token replay           tests/enrolment
certificate theft                tests/enrolment, tests/fleet
policy downgrade                 tests/airgap, tests/policy
cross-tenant device access       tests/multitenancy
unauthorised remote wipe         tests/fleet
generic command injection        tests/fleet, tests/policy
compromised sync server          tests/sync
device-pairing substitution      tests/cryptography
revoked-device access            tests/sync
metadata leakage                 tests/sync
key-recovery abuse               tests/recovery
stale policy replay              tests/airgap
unsigned offline bundle          tests/airgap
```

Cross-tenant adversarial cases run separately:

```text
make test-multitenancy
```

Eight cases: organisation A reading B's devices, policy cross-assignment, audit cross-access, catalogue cross-access, ring cross-access, role escalation, unscoped or wildcard queries, and backup restoration into the wrong tenant.

Show that `tests/cryptography` asserts the repository contains no hand-rolled cipher under `sync/`, and that no private key material is committed there.
