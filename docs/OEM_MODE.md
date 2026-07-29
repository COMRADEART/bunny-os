# OEM mode

OEM mode is schema- and plan-level scaffolding only. It uses the same erase/encryption/storage protections on factory-controlled disposable targets, runs hardware diagnostics and image verification, and seals the machine so the first owner creates the permanent user on next boot.

A production OEM flow must use an expiring temporary identity, no reusable password, no private signing key, no provider credential, and no retained diagnostic serial. Sealing removes the OEM account, history, SSH keys, network credentials, test files, logs containing identifiers, and installer session material; then it verifies the first-run marker and powered-off state.

The current source has no OEM executor, sealing test, hardware partner workflow, or consumer image claim. OEM partnerships and manufacturing remain out of scope.

