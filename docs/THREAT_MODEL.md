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

