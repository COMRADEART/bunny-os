# Stable candidate privacy review

Date: 2026-07-29  
Disposition: `BLOCKED / NO-GO`

Static tests verify redaction of email/IP/MAC/home/token/key shapes, forbidden content fields, local broker socket, disabled update timer, optional crash metadata without persistent IDs, and no fabricated dashboard scores. Defaults keep telemetry/crash/hardware/cloud/capture off.

No installed candidate, packet capture, manual diagnostic bundle, cross-user session, browser/runtime, recovery export, or public crash operation was tested. Privacy Blocker remains because absence of unexplained traffic and cross-user exposure has not been demonstrated.
