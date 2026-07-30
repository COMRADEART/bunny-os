# Thirty-minute demonstration

Run the ten-minute demonstration, then:

```text
python oem/bin/bunny-oem describe-checks
make test-factory
make test-enrolment
make test-device-identity
make test-fleet
make test-sync
make test-sync-crypto
make test-airgap
python -c "import json, enterprise.health as h; print(json.dumps(h.describe_visible_fields(), indent=2))"
python -c "import json, sync.metadata as m; print(json.dumps(m.describe_visible_metadata(), indent=2))"
python scripts/phase7.py pilot-readiness
```

Cover, in order:

1. The 22 factory finalisation checks, and that `UNKNOWN` is a failure.
2. Enrolment disclosure: nine mandatory statements, and refusal when the personal-data boundary is missing.
3. Device identity refusing derivation from a MAC address.
4. Update rings, and refusal to disable signature verification or skip early validation.
5. Remote administration refusing `device.shell`.
6. Sync envelope refusing plaintext metadata and key material.
7. Pairing refusing a substituted device key.
8. Air-gapped bundles refusing an unsigned import and a stale sequence.
9. Exactly what an administrator can see, and exactly what the sync service can see.
10. Pilot readiness reporting NO-GO with its unmet gates named.

Read `demos/07-oem-enterprise-sync/privacy-demo.md` alongside step 9.
