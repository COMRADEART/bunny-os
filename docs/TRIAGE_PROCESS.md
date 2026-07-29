# Triage process

1. Quarantine and checksum the source export; do not open untrusted attachments on a maintainer workstation.
2. Validate `schemas/beta-feedback.schema.json`, redact before durable storage, and reject user-content or secret fields.
3. Confirm component using the 28-value taxonomy in `operations/taxonomy.py`.
4. Confirm severity: Blocker prevents safe qualification; Critical covers data loss/security/cross-user/common-path failure; High is a major supported-flow failure; Medium has a low-risk workaround; Low is limited; Enhancement is not a contract defect.
5. Reproduce in a disposable fixture and record exact image, kernel, firmware, hardware, storage, encryption, steps, expected result, and actual result.
6. Link a failure signature, assign an owner and target, add a regression test, then verify on a new immutable beta build.
7. Close only with fix version, regression result, and independent verification evidence.

Unknown reproducibility remains `unknown`; it is not evidence that the report is invalid. Issue volume is not converted to a reliability percentage.
