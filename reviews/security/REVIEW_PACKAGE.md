# Security architecture review package

Review id: `review-security-architecture`  
State: **package-prepared**  
Reviewer: **not yet identified**  
Organisation: **not yet identified**  
Source commit: `79bb99ddb39d8a5dbc279629f43b23346fb0e5e8`

This package is prepared and has not been sent. It is not a review, and nothing in this
repository may cite it as one. `release/reviews.py` refuses to record a reviewer
affiliated with the project, so this cannot become a self-review by being filled in.

## Scope

The privileged broker, the root update agent, the installer secret channel, the SELinux domains, the update trust chain, and the Phase 7 enrolment, policy and remote-administration boundaries.

## Threat model

docs/THREAT_MODEL.md, docs/ENTERPRISE_THREAT_MODEL.md

## Design documents

- `docs/PRIVILEGED_BROKER.md`
- `docs/USER_AND_PRIVILEGE_MODEL.md`
- `docs/SECURITY_BASELINE.md`
- `docs/UPDATES.md`
- `docs/adr/ADR-003-privileged-broker-authentication.md`
- `docs/adr/ADR-022-enterprise-policy-agent.md`
- `docs/adr/ADR-026-remote-administration-boundary.md`

## Test results

- TEST_REPORT.md
- `tests/security/`
- `tests/broker/`
- `evidence/vulnerability/beta-grype.json`

## Known limitations

KNOWN_LIMITATIONS.md; SECURITY_REACHABILITY_REVIEW.md records 24 Critical/High findings whose reachability could not be resolved without symbol analysis of stripped Go binaries.

## Explicit questions

1. Are the 8 Critical golang.org/x/crypto findings in the vendored podman and skopeo binaries reachable in a Bunny OS deployment where no podman unit is enabled?
2. Does the broker's peer-credential rebinding close the PID-reuse race under adversarial load?
3. Can the two-socket broker design leak authority between the local-user and policy-agent method tables?
4. Is the update trust chain resistant to a fully compromised fleet control plane?
5. Does the installer secret channel leak the primary user's passphrase into any log, journal or crash artifact?

## Expected deliverables

- A written report identifying the reviewer and the review dates
- Findings rated by severity with reproduction steps
- An explicit statement on each of the five questions above
- A per-CVE reachability determination for the 8 Critical findings

## How this package becomes a completed review

1. Identify an external reviewer and record their name and organisation.
2. Set `state` to `commissioned` in `operations/data/independent-reviews.json`.
3. On delivery, place the report in this directory and set `reportReference` to its path.
4. Set `state` to `delivered`. The gate verifies the file exists before accepting it.

Generated from `operations/data/independent-reviews.json`. Edit that file, not this one.
