# OEM programme

Four participation levels. No level is open for applications: Bunny OS has no published stable release, so no OEM relationship can begin. This document defines the terms a relationship would have.

| | Community image builder | Validated hardware integrator | Supported OEM partner | Official Bunny OS device |
|---|---|---|---|---|
| Image source | Own build from public source | Official image plus signed OEM extension | Official image plus signed OEM extension | Official image only |
| Signing | Own keys, `oem-` namespace | Own `oem-` keys for the extension | Own `oem-` keys, reviewed rotation | Bunny OS release keys for the image, `oem-` keys for the extension |
| Hardware testing | None required | Full qualification kit, self-reported | Full qualification kit, evidence reviewed | Full kit, two independent repeat runs, evidence reviewed |
| Updates | Builder's responsibility | OS from Bunny OS, extension from OEM | Same, with coordinated embargo access | Bunny OS, with OEM notified before publication |
| Support | None | OEM, first line | OEM first line, escalation path to project | OEM first line, contracted escalation |
| Branding | May not use Bunny OS marks to imply endorsement | May state "runs Bunny OS" | May state "Supported OEM partner" | May state "Official Bunny OS device" |
| Recovery | Must ship bootable recovery | Verified recovery, validated in the kit | Same, plus driver and firmware recovery guidance | Same, plus documented failure path per model |
| Security disclosure | Encouraged | Required contact, 90-day coordination | Required contact, embargo participation | Required contact, embargo participation, incident SLA |
| Minimum maintenance | None | 24 months from last shipment | 36 months | 36 months, contracted |

## What "certified" means here

Nothing is described as certified. `oem/qualification.py` refuses a certification claim unless a formal process is recorded, at least two repeat runs exist, and the model has no declared limitations. Until such a process exists, the strongest available statement is `qualified` or `qualified-with-limitations`. See `docs/OEM_PROFILES.md`.

## What an OEM cannot change

Update trust roots without an explicit variant separation, privacy defaults, telemetry defaults, security warnings, encryption protections, recovery access, Bunny permission enforcement, and system-broker boundaries. These are refused structurally, not by policy: the profile schema has no field for them and `oem/validation/overlay.py` rejects overlay writes to their paths.

An OEM that requires a different update trust root is an `independent-oem-variant`. Such a variant may not present itself as official Bunny OS and may not claim the official-device level; `oem/validation/profile.py` rejects that combination.
