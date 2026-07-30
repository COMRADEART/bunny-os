# Licensing decision

Date: 2026-07-29. Status: **unresolved. This is a project-owner decision, not an engineering one.**

There is no root `LICENSE` file. `LICENSE_COMPLIANCE_REPORT.md` records this as the highest-priority licence gap, and it blocks OEM and enterprise distribution independently of every other gate: a recipient cannot know what they are permitted to do with the source.

This document sets out the options and their consequences so the decision can be made deliberately rather than by default. **No option has been chosen and no `LICENSE` file has been added.**

## Constraint from upstream

Bunny OS is a Fedora derivative. The base userspace, kernel, systemd, GNOME and the rest arrive under their own licences — predominantly GPL-2.0, GPL-3.0, LGPL, MIT and Apache-2.0 — and those are unaffected by whatever the project chooses for its own source. The choice below governs only the code in this repository: the broker, update agent, installer, shell services, and the Phase 7 `oem/`, `enterprise/` and `sync/` packages.

`build/license-policy.json` already refuses proprietary, commercial-only, no-redistribution and EULA markers in any dependency, so the project has effectively committed to remaining redistributable.

## Options

### GPL-3.0-or-later

Strong copyleft. An OEM shipping a modified Bunny OS must publish their modifications.

*For:* consistent with the project's stated posture — user control, no silent degradation, recovery that does not depend on a vendor. It makes the OEM boundary legally enforceable rather than merely policy: an OEM cannot ship a privately modified variant that weakens a default and keep it closed.

*Against:* the anti-tivoisation and patent terms make some hardware vendors decline outright. If the OEM programme matters, this narrows the field. It also complicates linking for anything an OEM wants to add.

### Apache-2.0

Permissive with an explicit patent grant.

*For:* the widest OEM and enterprise acceptance, and the patent grant is genuinely valuable for a project inviting hardware partners. Easiest path for the separate fleet-server and console repositories.

*Against:* an OEM may ship a modified, closed variant. The trademark policy would then be the only lever preventing a weakened build being sold as Bunny-adjacent, and `docs/TRADEMARK_POLICY.md` is an unreviewed draft.

### Split: GPL-3.0-or-later for the OS layer, Apache-2.0 for the client libraries

`services/`, `installer/`, `shell/` and `build/` under GPL-3.0-or-later; `oem/`, `enterprise/`, `sync/` and the schemas under Apache-2.0.

*For:* matches the actual trust boundaries. The OS layer is where user-protective guarantees live and where copyleft does real work. The Phase 7 packages are integration surfaces that third parties must be able to embed — a fleet server in a separate repository, an enterprise console, an OEM's own tooling — and permissive licensing there removes friction without weakening the OS.

*Against:* two licences is more to explain, and contributors must know which tree they are in. Needs per-directory `LICENSE` files and clear headers.

## Recommendation

The split, and the reason is the Phase 7 architecture rather than licence preference. `docs/adr/ADR-023-fleet-control-plane.md` deliberately puts the fleet server, enrolment service and console in separate repositories with separate trust boundaries. Those components must import the protocol schemas and the policy model to interoperate at all, and a copyleft obligation on `enterprise/` would reach into every deployment of a control plane — including ones the project neither wrote nor supports.

Meanwhile the OS layer is exactly where copyleft protects the thing this project keeps saying it cares about: an OEM cannot take the broker, weaken the permission enforcement, and ship it closed.

## What must happen next

1. Choose. This is the blocking step and nobody else can take it.
2. Add the `LICENSE` file or files and per-directory notices.
3. Add SPDX identifiers to source headers.
4. Confirm the choice is compatible with every dependency in the SBOM — the licence scan checks for prohibited markers but not for outbound compatibility.
5. Have the trademark policy reviewed, since the two interact: the weaker the licence, the more the trademark has to carry.

Until step 1, no OEM agreement can be signed and no enterprise distribution can occur, whatever the state of the technical gates.
