# Flatpak integration

Flatpak and GNOME portals are image components. Applications default to per-user scope. Broad filesystem, devices, camera, microphone, location, background, and capture access are not granted automatically; portal grants remain visible and revocable through base GNOME/Bunny Settings integrations where enforcement exists.

A Bunny curated remote may be configured only with reviewed HTTPS and signing metadata. Flathub is offered only after an explicit user choice and is not required for offline installation. Invalid signatures stop installation. Remote unavailability produces a clear offline error and never affects the OS deployment.

Application updates are separate from bootc OS updates. Permission and storage views identify the remote, application ID, license, and publisher evidence available from metadata. Bunny does not silently install Flatpaks, browser extensions, or plugins.

