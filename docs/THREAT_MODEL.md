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

## Phase 7 OEM, enterprise, and sync update

Phase 7 adds device identity keys, enrolment tokens and certificates, organisation policy bundles, fleet audit chains, fleet-control signing keys, sync device and collection keys, the user recovery secret, OEM profile signing keys, and factory provisioning credentials as assets. New boundaries: device to control plane, device to sync service, control plane to sync service, tenant to tenant, OEM build host to official image, factory environment to shipped device, and administrator role to administrator role.

| Threat | Mitigation | Residual evidence gap |
|---|---|---|
| malicious organisation administrator reads personal data | fleet health limited to 10 categorical fields; no console user-content view; memory exposure is an unrepresentable policy; enrolment discloses the boundary | no console exists to assess |
| malicious administrator wipes a personally owned device | full reset and cryptographic erase refused unless organisation-owned; prior policy, MFA, scope, audit id, device confirmation | no wipe executor; boundary tested only in source |
| compromised fleet server disables update verification | safety invariants rejected at parse time; `signatureVerificationRequired` cannot be set false; no execution operation | no server exists; no signed fleet delivery observed |
| compromised fleet server replays stale policy | monotonic per-organisation sequence; 90-day bundle expiry | no operated control plane |
| compromised identity provider impersonates an administrator | step-up passkey or hardware key for destructive actions; role separation; audit records the method | no identity provider integrated |
| cross-tenant access | required tenant scope, wildcard refused, unscoped rows refused, per-organisation audit chains | source-level only; no database, no penetration test |
| stolen enrolment token | single-use, 24-hour maximum, consumed-id rejection, no secret in descriptor or argv, nonce replay rejection | no issued token has ever existed |
| malicious OEM weakens defaults or claims official status | closed profile schema; overlay allowlists; protected settings refused as key or value; official claim needs level, signed qualification, validated recovery | no profile signed, no hardware qualified |
| compromised factory leaves credentials on a device | 22-check finalisation; UNKNOWN, NOT_RUN, and missing checks all fail | evaluator trusts a supplied record; no executor inspects the device |
| compromised sync server reads content | on-device AEAD; envelope refuses plaintext description and key material | operational metadata remains visible; no reviewed backend installed |
| compromised sync server substitutes a device key | authenticator recomputed locally from received key material, bound to session, compared out of band | a user who does not compare defeats it |
| compromised sync server rolls back ciphertext | version bound as associated data; lower version and same-version substitution refused | withholding updates remains possible |
| malicious paired device reads ungranted collections | per-collection keys; new devices granted nothing by default | a granted device reads that collection's existing objects |
| key-recovery abuse by operator or organisation | server-assisted recovery of private content refused; organisation recovery limited to 3 organisation-owned collections; no personal escrow | careless phrase storage remains user risk |
| unauthorised remote wipe | ownership constraint, prior policy, MFA, scope, audit id, device confirmation | a compromised security-administrator account can wipe organisation-owned devices |
| policy downgrade | monotonic sequence, policy version and expiry, audit records the version applied | a genuinely newer permissive policy is accepted by design |
| update-ring manipulation forces fleet restarts | forced restart needs an explicit policy reference; deferred ring cannot force; withdrawal zeroes rollout | no operated fleet |
| audit tampering | per-entry hash over canonical content plus previous hash; sequence gaps detectable; signed truncation marker | an attacker with write access from entry N can rewrite forward; no off-device anchoring |

Full detail and the assessment methodology are in `docs/ENTERPRISE_THREAT_MODEL.md`, `PHASE_7_SECURITY_REVIEW.md`, and `PHASE_7_PRIVACY_REVIEW.md`. No control plane, sync service, or console exists, so none has been penetration-tested; every Phase 7 control is verified by host tests over synthetic data.
