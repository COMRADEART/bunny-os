# Update reliability programme

Measure discovery, signature/metadata validation, download and resume, space preflight, staging, reboot, health, previous-deployment retention, and rollback. Test Beta N→N+1 and N-1→N+1 only after those immutable images exist, plus interrupted download, low disk, offline staging, power interruption, service/graphics/Bunny health failures, bad signatures, expired metadata, and incompatible architectures.

Every attempt records source/target digests and exact outcome; every confirmed defect gains a regression test. The updater already fails closed on untrusted repositories, signatures, rollback sequence, contract mismatch, insufficient disk, and Bunny incompatibility. No beta update path has executed, so reliability is unknown and stable release is blocked.
