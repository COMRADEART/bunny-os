# Automated installation

The schema `schemas/automated-install.schema.json` supports test and development fixtures only. It requires all three independent gates: `automation.enabled=true`, `testEnvironment=true`, and confirmation text `BUNNY_OS_DISPOSABLE_TEST_DISK`. The target is bound to a probed disk ID and byte size and must be classified virtual.

Allowed fields are locale, keyboard, timezone, disposable target, erase/encrypted-erase profile, network skip, and application profile. Passwords and recovery keys are intentionally absent. A future Anaconda test adapter must receive secrets through protected file descriptors/credentials and must refuse a real/removable/installation-media/mounted/read-only target.

Configuration is local or detached-signed; path traversal, unknown fields, remote URLs, scripts, commands, package repositories, and `%post` shell snippets are invalid. The current repository does not enable unattended execution.

