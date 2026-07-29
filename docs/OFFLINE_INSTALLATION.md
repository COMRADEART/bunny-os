# Offline installation

The selected live ISO embeds the exact bootc payload through unified `image-builder --bootc-installer-payload-ref`. Installation must complete with networking disabled. Network setup is available for diagnostics or an update check, but no cloud provider, firmware download, Flatpak remote, local model, telemetry, or account service is required.

The offline-essential image includes GNOME, Bunny Shell/Desktop placeholder integration, terminal, Files, Settings, text editor, browser, archive manager, PDF/image/media viewers, hardware diagnostics, installer, firmware, and recovery tools. The exact RPM inventory and SBOM must be generated from the composed image.

The media manifest covers delivered artifacts and is detached-signed. Critical signature or checksum failure stops installation. The current repository has build definitions only: no embedded payload, ISO, signature, or offline VM result exists.

