# Licensing and trademark review package

Review id: `review-licensing-trademark`  
State: **package-prepared**  
Reviewer: **not yet identified**  
Organisation: **not yet identified**  
Source commit: `79bb99ddb39d8a5dbc279629f43b23346fb0e5e8`

This package is prepared and has not been sent. It is not a review, and nothing in this
repository may cite it as one. `release/reviews.py` refuses to record a reviewer
affiliated with the project, so this cannot become a self-review by being filled in.

## Scope

The GPL-3.0-or-later / Apache-2.0 split selected by the owner, its outbound compatibility against the dependency set, and the trademark policy draft.

## Threat model

Not applicable. The exposure is distribution risk: an incompatible outbound licence or an unenforceable mark surfaces only once someone else ships the software.

## Design documents

- LICENSE
- `LICENSES/GPL-3.0-or-later.txt`
- `LICENSES/Apache-2.0.txt`
- `docs/LICENCE_DECISION.md`
- `docs/LICENSING.md`
- `docs/TRADEMARK_POLICY_DRAFT.md`
- THIRD_PARTY_NOTICES.md

## Test results

- `evidence/build/beta-license-scan.log`
- `evidence/sbom/beta-license-report.json`
- LICENSE_COMPLIANCE_REPORT.md

## Known limitations

The licence scan checks for prohibited markers in dependencies. It does not check outbound compatibility of GPL-3.0-or-later against every licence in the 6077-record SBOM, and no lawyer has reviewed the split or the trademark draft.

## Explicit questions

1. Is GPL-3.0-or-later outbound-compatible with every licence present in the beta SBOM, including the Apache-2.0 and GPL-2.0-only components?
2. Does the split create a combined-work problem where an Apache-2.0 package under enterprise/ imports a GPL-3.0-or-later module?
3. Is the trademark policy draft enforceable, and does it adequately separate 'built from Bunny OS source' from 'is Bunny OS'?
4. Do the GPL-3.0 anti-tivoisation terms conflict with shipping Secure Boot with a vendor-controlled key on OEM hardware?
5. What source-distribution obligations attach to an OEM shipping a modified image, and is the current build tooling sufficient to discharge them?

## Expected deliverables

- A written opinion identifying the reviewing firm or counsel
- An explicit statement on outbound compatibility
- A judgement on the anti-tivoisation question, which is load-bearing for the OEM programme
- Recommended changes to the trademark draft before it is published

## How this package becomes a completed review

1. Identify an external reviewer and record their name and organisation.
2. Set `state` to `commissioned` in `operations/data/independent-reviews.json`.
3. On delivery, place the report in this directory and set `reportReference` to its path.
4. Set `state` to `delivered`. The gate verifies the file exists before accepting it.

Generated from `operations/data/independent-reviews.json`. Edit that file, not this one.
