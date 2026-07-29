# Privacy model

Defaults are local and quiet: no telemetry, advertising ID, cloud account, remote diagnostics, background upload, model download, cloud-model fallback, screen capture, microphone, camera, remote desktop, or indexing outside user-approved locations. First boot writes these choices locally and never requires consent to processing that is not performed.

Hardware inventory reads kernel/sysfs facts locally and returns them only to the invoking user/broker response; `privacy.transmitted` is always false. Update checks are opt-in in the Phase 1 first-boot flow and disabled in the developer image. Offline operation remains usable after the image exists.

File/folder, screen, camera, and microphone access use desktop portals and visible user grants. Accessibility remains available but does not imply input automation permission. Support bundles contain selected system unit logs and release metadata, redact credential-shaped values, exclude prompts/memory/user-file contents/environments, remain local and readable only by their authenticated requesting user (plus root), and are never uploaded automatically.

Privacy tests inspect defaults, listeners, firewall policy, update configuration, and cloud-free health checks. A packet-capture VM run remains required before release.
