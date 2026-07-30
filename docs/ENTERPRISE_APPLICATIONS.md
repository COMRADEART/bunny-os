# Enterprise applications

Schema: `schemas/organisation-catalogue.schema.json`. Implementation: `enterprise/catalogue.py`. Tests: `tests/fleet`.

Layered over the project catalogue in `operations/catalogue.py`. An organisation catalogue adds entries for one tenant and may mark project entries required or blocked. It cannot lower a trust requirement.

## Required fields

Source, package id, publisher, version, signature, permissions, deployment state, update policy, removal policy, support owner. Optional: update ring, managed configuration.

## Signature is not optional

`signatureVerified` is `const: true`. An unsigned package is refused at the trusted catalogue interface regardless of who added it or which source it names. There is no "internal build" exemption.

## Permission ceilings follow the package format

A Flatpak entry may declare only permissions the sandbox can enforce; a broader claim is rejected. A native RPM entry may declare no bounded permission set at all, because it has no enforceable boundary, and is instead labelled:

> This package installs natively and has broad system access. It is not confined by the application sandbox and can read or modify system state and user data.

The label cannot be suppressed. `docs/OS_SANDBOX_INTEGRATION.md` already declines to describe any single container primitive as a complete boundary; this is the catalogue-level consequence.

## Deployment states

`required`, `optional-approved`, `blocked`, `deprecated`. A required application cannot be user-removable. A blocked application must be version-pinned. When an organisation both requires and blocks a package, `blocked` wins — a policy error resolves to not installing.

## Managed configuration

Settings only. Credential-shaped keys are refused, so an organisation distributes a credential *source* rather than a credential value. The same rule applies to provider policy in `docs/DEVICE_POLICY.md`.

## Plugins

Plugin control is a policy domain, not a catalogue entry: publisher allowlist and blocklist, plugin allowlist and blocklist, capability ceiling, network policy, version pins, and emergency revocation. A `full-requested` capability ceiling requires an explicit plugin allowlist, because capabilities are never granted silently. Organisation approval still maps to exact Bunny permission grants through the existing approval path in `docs/APPROVAL_CENTRE.md`.
