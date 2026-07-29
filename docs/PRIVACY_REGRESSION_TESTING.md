# Privacy regression testing

Every candidate verifies telemetry, crash upload, hardware submission, and cloud AI are off; capture/microphone/camera are denied until user action; search has only approved locations; no public Bunny listener, cross-user access, or unexplained traffic exists. Run a quiet packet capture with updates disabled and a second capture for each explicit network feature.

Diagnostics use realistic synthetic identifiers and deterministic redaction plus manual review. Crash aggregation accepts component/version/architecture/stack/driver/kernel/deployment only and has no persistent user ID. Automated source tests do not replace installed-candidate traffic or manual-bundle evidence.
