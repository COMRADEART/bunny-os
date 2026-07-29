# Threat model

## Assets and boundaries

Assets: user files and credentials, Bunny memory/database, plugin trust store, local models, OS image/deployments, update/public and offline private keys, recovery material, and audit logs. Boundaries: browser UI↔app-server; Bunny↔broker; user session↔root service; plugin↔Bunny; model file↔runtime; updater↔registry/image store; bootloader↔kernel; kernel↔userspace; recovery↔encrypted user data.

## Threats and primary controls

| Actor | Representative attack | Controls | Residual risk/test |
|---|---|---|---|
| malicious local user | forge broker identity/read another session | SO_PEERCRED, `/proc` binding, system-UID denial, no user data in reads, Polkit | cross-user Linux VM tests pending |
| compromised Bunny process | request root shell/write/service | exact methods/params, fixed absolute argv, no shell/environment, systemd hardening, rate/timeout/audit | root broker implementation still security-review candidate |
| compromised plugin | escape to files/network/system | Bunny capabilities plus bwrap/systemd/seccomp/SELinux plan | qualified plugin transient units/SELinux pending |
| compromised model file | parser/runtime exploit | data outside image, hash/license/runtime validation upstream, sandboxed model service plan | fuzz/GPU runtime matrix pending |
| compromised update server/network attacker | rollback or malicious image | HTTPS, Ed25519 manifest, expiry, revocation, monotonic sequence, repo/digest allowlist, bootc prior deployment | registry signature enforcement/key ceremony pending |
| malicious website | reach app-server or desktop APIs | loopback token auth upstream, browser/Tauri policy, portals | Bunny upstream tests remain authoritative |
| supply-chain attacker | poison base/package/Bunny artifact | digest release pin, Fedora-only repos, explicit manifests, hashes/SBOM/provenance, signed upstream requirement | repo snapshots/repeated builds absent |
| stolen device/media | offline file/key theft | LUKS2 design, screen lock, Secure Boot path, no escrow | encryption installer and Secure Boot qualification pending |
| compromised session | use valid user grants | active-session Polkit, audit, lock/session separation | active user compromise can access that user's data |
| malicious removable media | autorun/parser/device attack | no Bunny autorun, desktop mediation, firewall, conventional udev | device-class policy/hardware tests pending |

Recovery is powerful by design, so confidentiality depends on firmware/boot policy and LUKS credentials. It never bypasses disk encryption or silently resets data. Availability attacks can still force rollback/recovery; the design prioritizes recoverability and records failures without requiring cloud access.

## Phase 5 public-beta operations update

| Threat | Mitigation | Residual evidence gap |
|---|---|---|
| malicious diagnostic attachment | local structured imports, size/schema limits, redaction before storage, isolated manual review, no automatic execution | no real public-beta bundle review |
| poisoned community hardware report | source attribution, immutable original, physical reproduction before tier promotion | no hardware submissions or physical lab |
| issue-tracker social engineering | untrusted fields never become commands/paths/severity/closure; high-severity merge needs human confirmation | maintainer process not operated publicly |
| compromised application metadata | signed sources, catalogue review, license/SBOM/provenance, protected approvals | stable catalogue unqualified |
| inconsistent update mirrors | signed manifest/digest/repository allowlist, monotonic sequence, reproducible comparison | no signed beta update execution |
| recovery-media downgrade | independent signature/version/revocation verification and migration compatibility check | no recovery ISO |
| malicious dual-boot environment | installation-media/identity binding, unknown/encrypted/hibernated layouts blocked, no general resize | no destructive dual-boot fixture |
| persistent shell-extension crash attack | restart limits, Safe Shell, Bunny-disabled conventional desktop, signature-owned extension | no long-running GNOME candidate test |

Stable qualification adds no public ingestion listener and no automated release publisher. The largest residual risk remains absence of runtime, artifact, signing, migration, recovery, multi-user, network, and physical evidence; unknown rows block release.
