# Reproduction environments

Supported fixture definitions are QEMU/KVM q35/UEFI with disposable disks, VirtualBox UEFI, VMware UEFI where practical, Secure Boot with enrolled test keys on an isolated builder, encrypted-install disks, driver-package validation images, and prior-beta upgrade disks. A result is valid only when it records source commit, image hash/signature, OS/image/kernel version, firmware mode, virtual hardware, disk hashes/layout, encryption state, exact steps, expected and actual results, logs, and cleanup.

Fixtures must never point at a host disk. Automated destructive tests require an explicit disposable marker, virtual-device classification, exact size/ID binding, installation-media exclusion, and a fresh image. A VM success is not physical hardware evidence. No reproduction fixture ran in the current Windows preflight.
