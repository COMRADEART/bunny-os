# Failure signatures

`operations/data/failure-signatures.json` is the versioned catalogue. A record contains ID, component, bounded signature, affected versions/hardware, detection method, severity, workaround, fixed version, and regression test. Seed signatures cover bootloader, encryption/initramfs, graphics, NVIDIA signing, Wi-Fi firmware, expired update metadata, health failure, broker absence, shell crash loop, and portal denial.

Matching is component-scoped and advisory. Free-form logs do not become commands, paths, severity, or closure decisions. Signatures may aggregate approved crash metadata but never user identity or content. Every signature change is reviewed and receives a test.
