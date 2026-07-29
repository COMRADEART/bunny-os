# Firmware policy

Bunny OS redistributes only firmware accepted by Fedora's package/legal process in `linux-firmware` and updates supported device firmware through fwupd after user/admin action. Package inventory/SBOM records the exact files and licenses. No firmware is fetched silently by Bunny and no incompatible distribution repository is added.

Intel/AMD graphics, Wi-Fi, Bluetooth, storage-controller and laptop firmware follow Fedora packages. Proprietary NVIDIA drivers/firmware beyond that base are not bundled. A later optional path needs license/redistribution review, module signing/Secure Boot design, update coupling, removal/recovery and physical tests.

