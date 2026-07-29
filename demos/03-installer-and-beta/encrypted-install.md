# Encrypted installation

Use `make vm-encrypted-install` only with a fresh 80 GiB virtual disk. In Anaconda, select erase with LUKS2, enter the passphrase through the UI, record and confirm the recovery key outside the VM, install, reboot, and test password, wrong password, and recovery key. Scan logs, process arguments, environment, and target filesystem for secrets before marking passed.

