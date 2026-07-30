# OEM readiness report

Date: 2026-07-29. Result: **not ready.** No OEM relationship may begin, no device may be manufactured, and no image may be described as official or certified.

## What exists

| Capability | State |
|---|---|
| Signed OEM profile schema | Version 1, `schemas/oem-profile.schema.json` |
| Profile validator | `oem/validation/profile.py`, 8 check families, 41 tests |
| Overlay validator | `oem/validation/overlay.py`, destination and content allowlists |
| Factory finalisation evaluator | `oem/validation/finalize.py`, 22 checks, 21 tests |
| Hardware qualification evaluator | `oem/qualification.py`, 19 tests plus 7 sustained-load scenarios |
| `bunny-oem` CLI | validate-profile, validate-overlay, qualify, finalize, describe-checks |
| Programme model | Four levels with signing, testing, update, support, branding, recovery, disclosure, and maintenance terms |
| Example profile and overlay | Validate cleanly and are covered by tests |

## What does not exist

- No factory provisioning executor. `bunny-oem provision`, `seal`, and `build-image` report `available: false` and exit 78.
- No OEM image has been built. `make build-oem-image` validates inputs and says so.
- No hardware has been qualified. Zero physical devices, zero repeat runs, zero sustained-load campaigns executed.
- No recovery media has been booted, so no OEM profile can be approved — `oem/qualification.py` refuses a report without validated recovery.
- No OEM signing key exists. `build/keys/` contains no private or public release key.
- No partner process, contract template, or branding approval exists.
- No trademark policy has been reviewed by anyone qualified to review it.

## Certification status

Nothing is certified and nothing may be described as certified. `oem/qualification.py` refuses a certification claim unless a formal process is recorded, at least two repeat runs exist, and the model declares no limitations. No such process exists, so `certificationClaimPermitted` is false for every possible input today.

The strongest defensible statements are `qualified` and `qualified-with-limitations`, and neither has been earned by any hardware.

## Hardware qualification kit

Thirteen required tests: installation, encryption, Secure Boot, graphics, display, Wi-Fi, audio, suspend and resume, storage, updates, rollback, recovery, multi-user. Six optional: TPM, Bluetooth, camera, battery, thermals, Bunny local AI.

Seven sustained-load scenarios, each requiring six recorded observations including negative ones: sustained CPU, sustained GPU, local-model inference, simultaneous compile and model, battery operation, charging, suspend cycles.

Execution status: `NOT_RUN` for every test on every model, because there is no model.

## Recovery obligations

Every OEM profile must name a recovery profile, and an image cannot be approved without validated recovery. This is enforced in two places: `_validate_recovery` refuses a profile with no recovery profile, and `evaluate_qualification` adds a failure when the recovery test did not pass.

No recovery path has been validated on any hardware.

## Update responsibility model

Three options, declared per profile: `official-image`, `official-image-with-signed-oem-extension`, `independent-oem-variant`. An independent variant cannot claim official-device status; that combination is refused.

For each model an OEM must declare who signs, who updates, who supports, who handles drivers, who handles recovery, who handles security advisories, and the compatibility responsibilities. `docs/OEM_PROGRAMME.md` holds the matrix.

## Blockers to OEM readiness

1. No published, signed stable release to base an OEM image on.
2. No factory provisioning executor.
3. No hardware qualified and no recovery validated.
4. No OEM signing key infrastructure or key ceremony.
5. No partner agreement, branding approval, or trademark review.
6. 59 fixable vulnerability findings in the current image dependency set, 8 Critical.
7. Support capacity unconfirmed; an OEM partner would expect security advisories with an SLA the project cannot currently offer.

`make gate-oem-pilot` fails on four of these and will continue to.
