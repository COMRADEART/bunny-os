# Installer protocol v1

The normative schema is `schemas/installer-protocol.schema.json`. Requests are same-host, authenticated messages; they are not a network API. The frontend cannot request a command, executable, script, device node, mount path, cryptsetup option, or bootloader argument.

## Request envelope

```json
{
  "schemaVersion": 1,
  "requestId": "request-018f1234",
  "installationId": "install-018f1234",
  "operation": "installer.plan.preview",
  "nonce": "c29tZS1mcmVzaC1ub25jZQ",
  "timestamp": "2026-07-28T12:00:00Z",
  "params": { "plan": {} }
}
```

Allowed operations are `installer.initialize`, `installer.probe`, `installer.plan.validate`, `installer.plan.preview`, `installer.install.start`, `installer.install.status`, `installer.install.cancel`, `installer.install.logs`, `installer.install.verify`, and `installer.recovery.prepare`. Unknown, stale, replayed, cross-session, wrong-token, extra-field, and secret-bearing requests fail closed.

## Plan

A plan names schema and installation IDs; mode; a disk reference bound to stable ID, path, and expected size; explicit partition operations; encryption; UEFI boot; conventional primary-user creation with an opaque protected password reference; locale; optional network migration; recovery; and an application profile. `additionalProperties` is false at security boundaries. The plan accepts no arbitrary groups: Anaconda maps the administrative flag to Fedora's conventional elevation policy and never adds Docker or another root-equivalent group.

Plaintext passwords, recovery keys, raw encryption keys, provider credentials, and generic tokens are invalid. At execution time an established installer secret channel supplies an opaque `fd:N` or installer-secret handle out of band. Public responses replace even that reference with `[protected]`.

## State and audit

Each response echoes the request and operation identity. Audit records contain timestamp, stage, operation ID, correlation ID, redacted target reference, result, and redacted error type. They omit user content, complete serials/UUIDs, credentials, and key material. Log export never changes installation state.

Schema changes require a new integer version, compatibility tests, and an adapter update. Security-relevant unknown fields are not ignored.
