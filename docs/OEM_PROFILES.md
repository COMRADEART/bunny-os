# OEM profiles and image customisation

Schema: `schemas/oem-profile.schema.json`, version 1. Validator: `oem/validation/profile.py`. Tests: `tests/oem`. CLI: `oem/bin/bunny-oem validate-profile`.

## Tree

```text
oem/
  profiles/     signed profile instances
  schemas/      overlay allowlist policy data
  overlays/     overlay manifests and branding assets
  validation/   profile, overlay, and factory-state validators
  tests/        see tests/oem, which is where the repository keeps test code
```

## Configurable

Default locale, keyboard, timezone, approved drivers, hardware-specific firmware, recovery assets, default applications, support links, hardware documentation, first-run device information, and approved branding extensions.

## Not configurable

Update trust roots without explicit variant separation, privacy defaults, telemetry defaults, security warnings, encryption protections, recovery access, Bunny permission enforcement, and system-broker boundaries.

These are not merely disallowed. `additionalProperties: false` at every schema level means a profile has nowhere to express them, and `scan_for_forbidden_content` rejects a protected setting name appearing as a key *or* a value at any depth.

## Rejections

A profile is rejected when it is unsigned; when its `signature.keyId` is outside the `oem-` namespace or is named to impersonate a release, fleet, or sync namespace; when a package names a repository outside the reviewed set; when any package or driver does not require signature verification; when an out-of-tree kernel module is not in the reviewed set; when a script, command, or credential key appears at any depth; when secret material is embedded; when a protected setting is targeted; when `recoveryProfile` is absent; or when an official-device claim lacks the matching programme level, a signed qualification report, or validated recovery.

## Overlays

Overlays may write only under the eight roots in `OVERLAY_ALLOWED_ROOTS`. Executable, unit, policy, and archive payloads are refused, as are execute and setuid bits, symlinks, absolute paths, `..` components, duplicate destinations, and inline payloads that set a Bunny OS-owned settings key. Code ships as a signed package from a reviewed repository, never as an overlay file.

## Qualification methodology

Schema: `schemas/oem-qualification.schema.json`. Evaluator: `oem/qualification.py`.

Thirteen required tests must pass; six optional tests may report `NOT_APPLICABLE` when the hardware genuinely lacks the component, which becomes a declared limitation. Seven sustained-load scenarios must each record thermal throttling, fan behaviour, power use, crashes, data corruption, and driver resets — including when the answer is "none observed". A report is unusable without validated recovery, a methodology reference, and a signature. A performance claim needs a declared methodology of substance and at least two repeat runs.

No hardware has been qualified. No physical device has run any of these tests.
