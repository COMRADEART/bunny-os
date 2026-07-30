# Sixty-minute demonstration

Twenty-four steps. Each references the file with the exact commands and refusal steps.

```text
1.  OEM profile validation            build-oem-image.md
2.  Hardware-specific image build     build-oem-image.md
3.  Factory provisioning              factory-provisioning.md
4.  Factory-state cleanup             factory-provisioning.md
5.  Customer first boot               factory-provisioning.md
6.  Organisation enrolment            enrol-device.md
7.  Policy disclosure                 enrol-device.md
8.  Fleet grouping                    update-ring.md
9.  Staged update                     update-ring.md
10. Update pause                      update-ring.md
11. Application deployment            deploy-application.md
12. Restricted plugin policy          apply-policy.md
13. Local-only AI policy              apply-policy.md
14. Device pairing                    device-pairing.md
15. Encrypted sync                    encrypted-sync.md
16. Offline edit conflict             encrypted-sync.md
17. Device revocation                 device-revocation.md
18. Remote organisation-data removal  remote-wipe-simulation.md
19. Full-reset confirmation boundary  remote-wipe-simulation.md
20. Air-gapped policy bundle          offline-policy.md
21. Audit export                      see below
22. Security tests                    security-demo.md
23. Privacy review                    privacy-demo.md
24. Pilot readiness gate              see below
```

Step 5, customer first boot, is a document walkthrough: `oem/validation/finalize.py` requires the first-run marker to record setup as incomplete so the customer creates the first account, and `docs/FIRST_RUN.md` describes what they then see. No device boots.

Step 21, audit export:

```text
make test-fleet
python -c "import json, enterprise.audit as a; print(json.dumps(a.retention_policy(), indent=2))"
```

Show the hash chain detecting a modified entry, a deleted entry leaving a sequence gap, and a cross-organisation verification failing. Show that export is one organisation per file and excludes secrets and user content.

Step 24, the pilot readiness gate:

```text
make gate-phase-7-source
make gate-oem-pilot
make gate-enterprise-pilot
make gate-sync-pilot
make gate-phase-7
```

The source gate passes. All four remaining gates fail and name their unmet conditions. End the demonstration there: the correct outcome of Phase 7 is a working, tested design and a refusal to deploy it.
