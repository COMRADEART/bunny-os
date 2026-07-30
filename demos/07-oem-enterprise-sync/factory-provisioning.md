# Factory provisioning and handoff refusal

```text
python oem/bin/bunny-oem describe-checks
python oem/bin/bunny-oem --json provision
make test-factory
```

`describe-checks` lists the 22 conditions that must hold before a device may leave the factory.

`provision` reports `available: false`, `writesPerformed: false`, and exits 78. The reviewed factory executor is not installed and nothing was read or written.

Refusal: build a finalisation record with every check `PASS` except `factory-accounts-removed`, pass it to `bunny-oem finalize --record`, and show `handoffPermitted: false` with the blocking check named. Repeat with a check set to `UNKNOWN` and show that an unperformed check is also a refusal, not a pass. Delete a check entirely and show that a missing check blocks handoff too.
