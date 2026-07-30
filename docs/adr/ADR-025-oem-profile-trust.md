# ADR-025: OEM profile trust

- Status: accepted
- Date: 2026-07-29

## Decision

An OEM profile is a signed, closed document. It is signed with a key in the reserved `oem-` namespace, separate from release, fleet, and sync namespaces, and a key id named to impersonate one of those namespaces is refused. Unsigned profiles are always rejected.

The schema is closed at every level. Arbitrary scripts, root commands, embedded secrets, and privacy-default overrides are not disallowed by policy — they have nowhere to be expressed. A deep scan additionally refuses a protected setting name appearing as a key or a value, and refuses secret-shaped material anywhere in the document.

Overlays are the only way an OEM adds files, and they are constrained twice: by destination, to eight allowed roots, and by content, excluding executable, unit, policy, and archive payloads plus execute and setuid bits and symlinks. Code ships as a signed package from a reviewed repository.

## Why a closed schema rather than a review process

A review process catches what a reviewer notices. A closed schema catches what nobody thought to look for. An OEM cannot smuggle a telemetry default past review if the profile has no field for it and the overlay validator refuses writes to the path that would hold it.

*An allowlist of permitted script hooks* was rejected. Any script hook is a root execution channel at image-build or first-boot time, and constraining what a script may do requires understanding the script, which no validator can do. Removing the concept was simpler and stronger.

*Letting OEMs set their own update trust root within an official image* was rejected because it would mean two trust roots for one image identity. An OEM that needs its own root is an `independent-oem-variant` and cannot claim official status; `oem/validation/profile.py` rejects that combination outright.

## On certification

Nothing is called certified. `oem/qualification.py` refuses a certification claim unless a formal process is recorded, at least two repeat runs exist, and the model declares no limitations. An official-device branding claim additionally requires the matching programme level, a signed qualification report, and validated recovery — an OEM image is never approved without recovery validation.

## Consequences

Legitimate OEM needs that fall outside the allowed set require a schema change with review, not a workaround. That friction is intended. No profile has been signed, no hardware qualified, and no image built from a profile.
