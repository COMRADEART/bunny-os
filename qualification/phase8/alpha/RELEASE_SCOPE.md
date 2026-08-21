# Supported Alpha scope

What this Alpha is qualified on, stated so a tester knows exactly where the
edge of the map is. "Works on PCs" appears nowhere in this document.

## The artifact

One artifact: `e906a48793d7` — ISO
`823d50caba35afe72452768affd5f6fa0ac8cfc13c164f0e1bc909fa887ab421`
(`bunny-os-0.3.0-live.e906a48793d7-x86_64.iso`), **unsigned**, frozen.

## Virtual machines tested

QEMU/KVM, q35 machine type, UEFI (OVMF), virtio disk/net/vga, 4 vCPU / 4–6
GB RAM, 1920×1080, software GL (llvmpipe). This is the only environment in
which the installation, first-boot, login, desktop, Companion, voice, Trust,
rollback and recovery journeys have actually run.

## Physical machines tested

**None.** Zero physical machines have been qualified
(`qualification/phase8/hardware-matrix.json` — empty machines list). On real
hardware, an Alpha tester is the first person to try that configuration.

## Hardware not tested (a non-exhaustive list of the untested)

Every GPU (all 3D and display behavior beyond llvmpipe), every Wi-Fi and
Bluetooth adapter, every physical microphone and speaker path, discrete
TPMs, multi-monitor, HiDPI panels, touchpads/touchscreens, laptop power
management.

## 3D-supported configurations

None verified. The 3D Companion renderer is measured only on llvmpipe
(software rendering) in a VM. On unsupported or unverified GPUs the
Companion is expected to **fall back** to 2D/pre-rendered with an
announcement; fallback-on-unsupported is a qualified behavior, native GPU 3D
is not.

## Update behavior

**Updates are NOT_SUPPORTED for this release class** — a deliberate,
recorded product decision with the refusal measured, not an accident
(`UPDATE_TRUST_ARCHITECTURE_DECISION.md`). An installed Alpha never receives
updates of any kind, including security updates.

## Recovery limitations

A recovery journey is engineering-qualified (boot-entry repair of an
unencrypted installation, from a separately built unsigned recovery medium
in a VM). **No recovery media ships with this Alpha**, encrypted
installations cannot be recovered without the user's passphrase by design,
and there is no re-image or restore-from-backup.

## Signing status

Unsigned. Verify the ISO digest yourself before booting it; the digest above
is the only identity the artifact has.

## Security-review status

Not reviewed. 8 Critical and 36 High findings are inventoried and
undispositioned, awaiting independent review
(`qualification/phase8/security-review/`).
