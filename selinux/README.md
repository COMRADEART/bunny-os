# SELinux policy prototype

Fedora SELinux stays enforcing. `bunny_os.te` and `bunny_os.fc` declare the intended Bunny service, app, plugin, and model domains and are compiled in CI. They are intentionally **not installed into the Phase 1 developer image**: a policy that has not passed boot, desktop, broker, updater, plugin, and model AVC testing would either break the image or encourage unsafe broad allows. `docs/KNOWN_LIMITATIONS.md` tracks VM policy qualification as a release blocker.

