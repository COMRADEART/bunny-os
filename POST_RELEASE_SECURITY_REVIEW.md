# Post-release security review

Date: 2026-07-29. Status: **not applicable; no release has been published.**

## Why an empty review is still worth writing

A post-release security review examines what a release did *after* it reached users: what was reported, what was exploited, how fast fixes shipped, whether the disclosure process worked. None of that can be written before a release, and writing it anyway would be fabrication.

But the review's *scope* can be fixed now, before there is any incentive to narrow it. That is what this document does.

## What this review will examine, once there is a release

| Area | Question it must answer |
|---|---|
| Reports received | How many, from whom, at what severity, and were any duplicates of known issues |
| Response time | Actual acknowledgement, assessment and fix times against the `SECURITY_POLICY.md` targets |
| Exploitation | Any evidence of exploitation in the wild |
| Update uptake | What fraction of devices took a security update, and how long the tail was |
| Signing | Whether every published artifact verified, and whether any key operation was irregular |
| Supply chain | Whether any dependency shipped with a known vulnerability, and how it was handled |
| Regressions | Whether any security fix broke something else |
| Disclosure | Whether embargoes held and whether coordinated timelines were met |
| Process failures | What the process got wrong, stated plainly |

The last row is the one that matters most and is the easiest to quietly drop.

## Current position

Nothing has been published, so:

- Zero reports received. Not "zero vulnerabilities" — zero reports, because there are no users.
- Zero advisories issued, zero CVEs requested, zero embargoes run.
- Zero key operations performed. The rotation and revocation ceremony has never been rehearsed.
- The disclosure process in `SECURITY_POLICY.md` has never been contacted by anyone.

## The known position that would carry into any release

The last vulnerability scan of a locally built image reported 59 fixable findings, 8 Critical and 28 High, in the Fedora kernel and the bootc-required Podman, Skopeo and Toolbox set. No waiver exists. Any release built today would inherit these, and a post-release review would open with them.

## Independence

This would be a self-review. `PHASE_7_SECURITY_REVIEW.md` makes the same admission. An independent assessment has not been commissioned, and a self-review is the weakest form of assurance available.
