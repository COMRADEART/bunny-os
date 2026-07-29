# Diagnostic safety

Before export, fixtures include usernames, email, phone, IP/MAC, API tokens, home paths, Wi-Fi names, hostnames, and recovery-key-like values. Automated checks verify deterministic replacement and forbidden field exclusion. A trained reviewer then inspects the archive names, manifest, text, metadata, and binary attachments in an isolated environment.

Bundles exclude prompts, memories, documents, screenshots, clipboard, credentials, raw keys, and unapproved logs. Export is local by default; upload is a separate explicit action. No sample candidate bundle has been manually inspected.
