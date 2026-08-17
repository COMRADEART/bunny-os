# Release-candidate artifact identity

Built 2026-08-17T16:27–16:41Z on the Fedora WSL builder. Every Phase 4
qualification claim binds to the digests below; none of them refers to "the
latest build".

## Commit

    15a9be16c46792203f6f5c09016eafe158b380a9
    working tree at build time: clean (the build refuses otherwise, and
    printed `dirty: 0`)

Two files are modified in the builder's checkout **after** the build, and
neither entered it: `build/inputs/input-publication-lock.json` was written by
the Track 1b publication that ran later, and `build/payload-oci/.keep` is
removed by the live build when it populates that directory. Recorded here
because a reader who runs `git status` on the builder should not have to
wonder.

An earlier build attempt at commit `817d853c` was **discarded, not
qualified**: a concurrently running suite script reset the builder's checkout
while that build was in progress, so the payload's tag and the tree its
layers were copied from could not both be vouched for. The suite script now
fetches a remote ref and checks out inside its own clone. The discarded
attempt's beta payload was never used.

## Inputs

| Input | Identity |
| --- | --- |
| Base image (retained, digest-pinned) | `sha256:1f08084a9a8545bd528641d4fda14e18408dfb1298acda243eaf583cd907a844` at `/var/lib/bunny-retention/base-images/sha256-c466de53…` |
| Builder image | `sha256:bf9f00d81c5d707830676193041862dbb5bccc88c18a000cdb674311917d1f3e` (source commit `9c525bf1ca341dcac1bf701d5363adabb07be267`) |
| Package snapshot | `fedora-44-beta-20260810-tts`, manifest `fa89f5e28175abf037acb0e83a5a7fa2868b415db12732c2afff98017fb70ada` |

All three are now also reachable off this machine — see
`../track-1b/DISPOSITION.md`.

## Artifacts

### Live installation medium — the ISO an alpha tester writes

    2aa1214aed4892884387f0a678926e12a8fc3b4935688db47b2910e52fd221a1
    bunny-os-0.3.0-live.15a9be16c467-x86_64.iso

### Shell-test machine image — voice and desktop qualification

    93eb7de081d60105f9ebeb471f173b7a7774358bed01ca7bb7978cac08805eea
    bootc-fedora-44-qcow2-x86_64.qcow2

### Beta payload — the installed system's container image

    localhost/bunny-os-beta:15a9be16c467
    manifest sha256:a2864eddd244ccc2806fbc7b529cb2a48911ace7ae237d4c984f29af79730a34

## Package versions of the components this phase's fixes touch

    gnome-shell-50.4-1.fc44.x86_64
    mutter-50.4-1.fc44.x86_64
    gnome-settings-daemon-50.1-1.fc44.x86_64
    accountsservice-23.13.9-16.fc44.x86_64
    gdm-50.2-1.fc44.x86_64
    systemd-259.8-1.fc44.x86_64

The first three decide the startup-ordering fix's behaviour; the fourth
decides the user-template fix's.

## Test environment

    builder    Fedora Linux 44 under WSL2, 22 cores, 15 GiB
    guest      qemu-system-x86_64 -machine q35,accel=kvm -cpu max -smp 4 -m 6144
    firmware   /usr/share/edk2/ovmf/OVMF_CODE.secboot.fd
    screen     1920x1080
    date       2026-08-17

## Commits after the artifact

The qualification harness runs from the branch head, which moves past the
artifact commit as evidence is committed. That is safe here and the reason is
mechanical rather than asserted: no install route sources from
`build/scripts/`'s harness files or from `qualification/`, so the *installed
content* of a rebuild at any later Phase 4 commit is unchanged. The routes
that do source from `build/` are `setup-drive.py`, `payload-oci`, the update
and artifact manifests, the revoked-key list and the release payload — none
of which any post-artifact commit touches.
