# Drivers

Fedora's upstream kernel and in-tree drivers remain authoritative. Mesa supplies Intel/AMD/virtual graphics, NetworkManager handles networking, BlueZ Bluetooth, PipeWire/WirePlumber audio, and fwupd firmware. Bunny does not build a kernel, fork a driver, or fetch random vendor installers.

The preflight chooses a safe recommendation and records source, Secure Boot state, Wayland implications, local-model uncertainty, restart guidance, and fallback graphics. Intel/AMD/virtio open paths are `supported_with_limitations` until exact VM/physical tests pass. Unknown hardware uses software rendering or stops if no safe display exists.

Driver logs contain PCI vendor/device identity but omit complete serials. Firmware/license and package provenance are part of the SBOM. Kernel modules must match the image kernel and signed boot policy. A driver update must preserve the previous deployment and safe-graphics entry.

No physical Intel, AMD, NVIDIA, Wi-Fi, Bluetooth, audio, suspend, display, or battery test ran on this host.

