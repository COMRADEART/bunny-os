# Phase 3 evidence provenance

Phase 3 — User Journey, Persistence & Legacy Issue Closure. Two evidence
generations live here:

- `investigation/` — the runs that found the defects, on the first Phase 3
  artifacts. Superseded for release claims by `binding/`, kept because the
  defect discoveries and the corrected-grading records are these runs.
- `binding/` — the final-artifact runs, on the image that carries every fix
  the investigation produced.
- `track-1b/` — the package-publication disposition (NOT_RUN,
  AUTHENTICATION BLOCKED).
- `suites/` — full-suite results with baseline/current/delta.

## Investigation artifacts

Built at commit **8eb1a9dc** on the Fedora WSL builder (retained-base
pre-pull, digest-verified):

- Live ISO `bunny-os-0.3.0-live.8eb1a9dc4901-x86_64.iso`
  sha256 `073c57b5e34b10d3f182c111e2ca57071afdb22c822a560250d3901fb7e73fac`
- shell-test qcow2
  sha256 `e37f0a56bb0ff754ed4fffb291c520224d609ba590dcbeb5a2516e5a3570260b`
- journey-e target disk
  sha256 `0c29e8a1e2067f00cbbececdd66abaeb091be8e2ef4d8c3f71ce61684516bf7f`
- Installed deployment
  `1ac2a513c13aecf3f15931a7fe490f9e2a4cd6608e4a9d944fce60102112ddd6.0`

The login runs iterated the harness; each run's `result.json` names its
commit as `harness at:` in the runner log, and the corrected journal
gradings (`result-corrected.json`, `journal-lastboot-corrected.log`) exist
for the runs graded before the `-b -1` boot-selection fix (11c549ae).

The persistent machine (`build/out/phase3/machine.qcow2`, on the builder)
was created from the journey-e disk and carries three deliberate offline
modifications beyond what the image shipped, each the subject of a
then-committed product fix: the MDWE drop-in for bunny-first-run
(f810747e's change, applied as a user-level drop-in for the A/B), the
AccountsService record for alex (31c20f4d's installer write, applied by
guestfish with the accountsd_var_lib_t label), and the bunny.desktop
session entry without X-GDM-SessionRegisters (956add5b's change). The
binding machine is created fresh from the final artifacts and carries no
offline modification except the read-only probe.

## Voice regression

`accept-all.sh phase3-a` exit 0 against the 8eb1a9dc shell-test image at
harness d7bb27d5; run artifacts under `/root/bunny-ops/e2e/runs/phase3-a`
on the builder, log `/root/bunny-ops/voice-phase3-a.log`.

## Binding artifacts

Recorded when the final sequence completes; the final build runs at commit
**376acf0e**.
