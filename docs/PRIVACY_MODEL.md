# Privacy model

Defaults are local and quiet: no telemetry, advertising ID, cloud account, remote diagnostics, background upload, model download, cloud-model fallback, screen capture, microphone, camera, remote desktop, or indexing outside user-approved locations. First boot writes these choices locally and never requires consent to processing that is not performed.

## Network activity that does occur

"Quiet" is not "silent", and the difference is worth stating rather than letting a reader infer the stronger claim.

A measured quiet boot — no login, no user action — contacts **four NTP servers from the Fedora time pool** on port 123. This is `chronyd` synchronising the clock. No identifier is sent and the exchange is a timestamp, so it is not telemetry, but those operators can see that a device is online and roughly where it is from its source address. Accurate time is a security dependency: certificate validation and update-manifest expiry both fail without it.

Standard link-scoped traffic also occurs: DHCP, ARP, mDNS, and DNS to the configured resolver.

Nothing else was observed. No Bunny endpoint, no analytics, no crash upload, no update check on a developer image, and no model download. See `NETWORK_PRIVACY_TEST_REPORT.md` for the capture, the method, and its limitations — chiefly that it covers one idle virtual boot rather than an installed system doing real work.

Hardware inventory reads kernel/sysfs facts locally and returns them only to the invoking user/broker response; `privacy.transmitted` is always false. Update checks are opt-in in the Phase 1 first-boot flow and disabled in the developer image. Offline operation remains usable after the image exists.

File/folder, screen, camera, and microphone access use desktop portals and visible user grants. Accessibility remains available but does not imply input automation permission. Support bundles contain selected system unit logs and release metadata, redact credential-shaped values, exclude prompts/memory/user-file contents/environments, remain local and readable only by their authenticated requesting user (plus root), and are never uploaded automatically.

Privacy tests inspect defaults, listeners, firewall policy, update configuration, and cloud-free health checks. A packet-capture VM run remains required before release.
