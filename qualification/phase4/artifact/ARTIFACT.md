# Release-candidate artifact identity

Built 2026-08-17T18:57:00Z on the Fedora WSL builder.

## Commit

    e906a48793d74544b39c14cc3e35e0654f5311e2
    dirty: 1 file(s)

## Base image (retained, digest-pinned)

    retainedDigest  sha256:1f08084a9a8545bd528641d4fda14e18408dfb1298acda243eaf583cd907a844
    retainedLocation /var/lib/bunny-retention/base-images/sha256-c466de539ec94fe2ea996785b8cda08b274316cd6bf21d5e13bd4d9a7f7aee5b

## Builder image

    builderDigest  sha256:bf9f00d81c5d707830676193041862dbb5bccc88c18a000cdb674311917d1f3e
    sourceCommit   9c525bf1ca341dcac1bf701d5363adabb07be267

## Package snapshot

    snapshotId     fedora-44-beta-20260810-tts
    manifestDigest fa89f5e28175abf037acb0e83a5a7fa2868b415db12732c2afff98017fb70ada

## Artifacts

### Live installation medium (the ISO an alpha tester writes)

    823d50caba35afe72452768affd5f6fa0ac8cfc13c164f0e1bc909fa887ab421  build/out/live/bootc-fedora-44-bootc-generic-iso-x86_64/bunny-os-0.3.0-live.e906a48793d7-x86_64.iso

### Shell-test machine image (voice and desktop qualification)

    83c31d0640e4aef6059004d5ff3f954879bd92a3723f4173dc71e53a39963a99  build/out/shell-test/bootc-fedora-44-qcow2-x86_64/bootc-fedora-44-qcow2-x86_64.qcow2

### Beta payload (the installed system's container image)

    localhost/bunny-os-beta:localhost/bunny-os-beta:e906a48793d7
    manifest sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d

## Package versions of the parts this phase changed

    gnome-shell-50.4-1.fc44.x86_64
    mutter-50.4-1.fc44.x86_64
    gnome-settings-daemon-50.1-1.fc44.x86_64
    accountsservice-23.13.9-16.fc44.x86_64
    gdm-50.2-1.fc44.x86_64
    systemd-259.8-1.fc44.x86_64

## Test environment

    builder      Fedora Linux 44 under WSL2, 22 cores, 15 GiB
    guest        qemu-system-x86_64 -machine q35,accel=kvm -cpu max -smp 4 -m 6144
    firmware     /usr/share/edk2/ovmf/OVMF_CODE.secboot.fd
    screen       1920x1080
