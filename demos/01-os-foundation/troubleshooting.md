# Troubleshooting

- No image: confirm root Podman storage contains the local tag and unified `image-builder version` works.
- Fedora image filesystem error: retain `--bootc-default-fs ext4`.
- UEFI boot failure: verify OVMF path, q35 machine, artifact hash and serial log; do not switch to legacy BIOS and claim success.
- GNOME unavailable: inspect GDM/systemd/SELinux journals and image package inventory.
- Broker timeout: inspect socket activation, unit sandbox denials and journal metadata; never weaken it to a shell.
- Update refusal: read the stable error and verify key/channel/expiry/sequence/arch/contract/Bunny/repository/digest/space. Do not bypass verification.
- Recovery not selected: validate marker permissions/content and generator journal; use boot menu/prior deployment as conventional fallback.

