# Release lifecycle

Channels are developer → beta → stable candidate → stable → maintenance → security-only → end of life. Promotion always creates new immutable, signed artifacts; a modified candidate gets a new RC number. Stable candidates freeze features and accept only Blocker, Critical, or explicitly approved High fixes during soak.

No durations or dates are committed yet. Each release record must name source commit, base/package snapshots, artifact hashes/signatures, update metadata, SBOM/provenance, supported hardware/modes, known issues, migration/downgrade policy, recovery image, owners, and EOL. Stable publication is currently prohibited.
