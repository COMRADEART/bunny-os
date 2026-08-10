# Application distribution

The immutable/image-managed OS contains kernel, drivers, firmware, system libraries, GNOME, Bunny system integration, and recovery. Ordinary graphical applications use per-user Flatpak where practical. GNOME Software is the application centre; Bunny OS does not create a proprietary store.

Source labels are Bunny OS system component, verified Bunny application, Flatpak application, native package, developer tool, and web application. Verified publisher information is shown only when the source supplies evidence. Permission views cover filesystem, camera, microphone, location, network where enforceable, devices, background, notifications, and screen capture. Native packages say `Not enforced by this package format` instead of simulating revocation.

The offline image includes Terminal, Files, Settings, Text Editor, Firefox, Archive Manager, PDF/image/media viewers, diagnostics, recovery, GNOME Software, and Bunny Desktop placeholder integration. It also includes one reviewed Vosk English speech model (a 41,205,931-byte source archive and 70,898,967 installed model bytes) so push-to-talk works without a first-run download. Large office suites and general conversational models remain omitted to avoid image bloat.

Native repositories stay Fedora-only. Developer tools live in the developer image and rootless Toolbx/Podman environments; Bunny receives no container socket. Bunny plugins use their separate manifest/trust/capability/sandbox/update/rollback path and are not root packages.

