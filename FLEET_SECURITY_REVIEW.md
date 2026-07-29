# Fleet security review

Date: 2026-07-29. Scope: `enterprise/fleet.py`, `remote.py`, `roles.py`, `catalogue.py`, `audit.py`, `health.py`. Tests: `tests/fleet`, 81 cases.

## Update trust is not delegable

Rings sit above the existing update channel. The manifest keeps its closed three-value channel enum and its mandatory Ed25519 verification. A ring decides only *when* a device is offered an already-signed manifest and to what fraction of a group.

`signatureVerificationRequired` is not a setting: supplying `false` is a rejection, so there is no representable ring configuration that turns verification off. This is the single most important property in this review, because it means a fully compromised fleet server cannot install arbitrary software.

## Rollback is preserved by construction

A `failed` or `rolled-back` update state report must set `rollbackAvailable: true` and name the `previousVersion` that remains selectable. A report that does not is rejected. A failed fleet update that lost rollback is therefore an unrepresentable state rather than an incident to discover later.

## Remote boundary

Fourteen typed operations. No generic shell, no command execution, no argv, no server-chosen path. Shell-shaped names — shell, exec, command, run, script, bash, sh, powershell, cmd, ssh, python, eval, system — are refused with a specific message so the attempt appears in the audit trail as a refusal rather than a typo.

Destructive operations require an explicit non-empty scope and a UUID audit correlation id before execution. Full reset and cryptographic erase additionally require an organisation-owned device, multi-factor authorisation, and a disclosed prior policy, plus device-side confirmation where policy demands it. A personally owned device is never fully wiped remotely.

## Role separation

No single role is unrestricted for routine work. Destructive operations require step-up authentication with a passkey or hardware key. The console has no view that renders user content, screens, keystrokes, or a shell, and requesting one is refused by name.

## Application trust

`signatureVerified` is `const: true`. An unsigned package is refused at the trusted catalogue interface regardless of source, with no internal-build exemption. Permission ceilings follow the package format: a Flatpak entry may declare only enforceable permissions, and a native RPM entry may declare none and instead carries an unsuppressible broad-access label.

## Audit integrity

Per-organisation hash chain. Each entry hashes its canonical content plus the previous entry's hash, so modification invalidates it and everything after. Monotonic sequence exposes deletion as a gap. Cross-organisation verification fails. Secret and content fields are refused before acceptance.

Verified by test: a modified entry, a deleted entry, a reordered chain, and a cross-tenant chain are all detected.

## Fleet health

Ten categorical fields. No free text, no counts, no durations. Behavioural and identifying fields refused by name, reusing the vocabularies in `operations/redaction.py`. Group attributes cannot describe personal behaviour, so a behavioural metric cannot be rebuilt from group membership.

## Findings

No Blocker or Critical finding.

One Minor, fixed: the behavioural-field refusal in `parse_update_state` ran *after* the generic unknown-field check, so an attempt to report `activeApplication` produced "unknown update state fields" instead of the privacy refusal. Both rejected the input, but the message misrepresented why. The specific check now runs first.

Residual risks, all accepted and documented: a compromised control plane can pin a channel, set aggressive deadlines, and disable organisation applications within the typed surface; a compromised security-administrator account can wipe organisation-owned devices; and an attacker with write access to the audit store from entry N can rewrite the chain from N forward, because off-device anchoring is not implemented.

## Not assessed

No fleet server exists. No policy has been distributed, no update offered, no audit chain operated at scale, and no console assessed. Every control is verified by host tests over synthetic data.
