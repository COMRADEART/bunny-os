# Compatibility

Bunny OS contract 1.x requires exact current contract `1.0.0` on the broker wire and accepts Bunny protocol v3. The Phase 1 upstream target is Bunny 0.2.0, Tauri-supervised Core/app-server sidecars, x86-64 Linux. OS, Bunny, broker, recovery, manifest, and database versions advance independently.

A Bunny artifact is acceptable only when its schema is valid, status is `verified`, architecture matches, protocol is 3, contract range includes 1.0.0, source commit is recorded, every path stays inside the release directory, every digest/mode matches, and no credential is embedded. A placeholder may exercise launch/error/contract paths but is never a Bunny runtime pass.

OS update manifests may constrain minimum/maximum Bunny semver; incompatible updates fail before bootc. Major contract 2 would require a parallel broker/schema and an explicit Bunny migration. OS code never migrates the upstream database by guessing its schema.

