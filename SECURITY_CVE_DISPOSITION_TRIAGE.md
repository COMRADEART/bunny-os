<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# CVE disposition triage — 24 Critical/High Unknown advisories

Date: 2026-09-11  
Audience: Gatekeeper / release decision authority  
Scope: the 24 unique Critical and High advisories currently dispositioned
`Unknown` that `python scripts/release.py cve-disposition` reports as blocking
stable.  
This document **does not convert any proof class.** Official records remain
`Unknown`. A recommended disposition is a next-action label for review, not a
gate input.

Evidence baseline for the 24 bundles: commit `80df25b09f6578276d18c8a82f15c47dd8959740`,
base `quay.io/fedora/fedora-bootc:44@sha256:fb71f099f40360b5e1e2e78e845ccf4f0f80fbe1b09de721d8954cddb89ee9c4`.
Phase 5 function-granularity scans cited below were taken against candidate
`e906a48793d7` and are **additional scanner observations**, not a substitute for
the independent review `release/cve.py` requires.

Related:

- `CVE_REACHABILITY_DISPOSITION_REPORT.md`
- `CVE_BINARY_ANALYSIS_REPORT.md`
- `SECURITY_REACHABILITY_REVIEW.md`
- `security/reachability/packages/<ADVISORY>/` (24 × 9 files)
- `security/reachability/findings/<ADVISORY>.json`
- `docs/adr/ADR-027-base-image-security-decision.md`
- `qualification/phase8/conditions/ALPHA_RELEASE_BLOCKING_CONDITIONS.md`
- `qualification/phase5/security/SCAN_ROUTE_DISCREPANCY.md`

---

## How to read this

| Term | Meaning here |
|---|---|
| Current disposition | Official proof class in `security/reachability/findings/` — **Unknown** for all 24. `Unknown` blocks stable. |
| Recommended disposition | One of `fix` \| `mitigate` \| `accept` \| `false-positive`. This is the path Gatekeeper should pursue. It is **not** written into the analysis records. |
| `false-positive` (candidate) | Scanner artefact *candidate* with an evidence checklist. **Do not convert `Unknown` until the checklist is complete and an independent reviewer signs the record.** Prefer honest `Unknown` over a false `Not present`. |
| `fix` | Fedora must rebuild the carrier RPM against a patched module. Bunny cannot patch vendored Go in `fedora-bootc`. Operational controls already present do not clear the gate. |
| `mitigate` | Not used as a primary recommendation. `Reachable but mitigated` still blocks stable until a release approver records explicit acceptance (`release/cve.py` `NON_BLOCKING_CLASSES`). |
| `accept` | Not recommended for any row. No Critical may become non-blocking without a completed independent review. |

`build/out/qualification/cve-reachability-disposition.json` is produced by
`cve-disposition` and is **not** present in this checkout until that verb is
run. The committed inputs are `operations/data/vulnerability-disposition.json`
and `security/reachability/findings/`.

---

## Release impact (gates, not judgement)

| Gate | What Unknown does |
|---|---|
| **Stable** | **All 24 block.** `scripts/release.py cve-disposition` treats `Unknown` as blocking. `gate-stable-release` check `vulnerability-position` is NO-GO while any Critical/High remains unresolved. `Reachable but mitigated` also blocks until separately accepted. |
| **Alpha** (Phase 8/9 authorization of a frozen artifact) | **The 8 Criticals block** under condition 2: a Critical with `UNKNOWN` / `REQUIRES_REVIEW` blocks Alpha. The 16 Highs do **not** by themselves satisfy condition 2. Alpha is **also** blocked by condition 1 (no completed independent security review) regardless of High rows. |
| Functional-alpha development branch | A different track (`FUNCTIONAL_ALPHA_REPORT.md`). It does not waive `gate-stable-release`. |

Owner of a non-blocking Critical conversion: independent reviewer recorded in
`operations/data/independent-reviews.json`. Internal documents in this
repository are not that review (`SECURITY_REVIEW.md`, this file included).

---

## Recommended-disposition counts

These counts are triage labels. Official class remains 24 × `Unknown`.

| Recommended | Count | Advisories |
|---|---:|---|
| `false-positive` (candidate) | 10 | 7 Critical `x/crypto` SSH-scoped + 2 High `x/crypto` dropped at function granularity + `CVE-2020-27815` |
| `fix` | 14 | grpc Critical, podman, buildkit, docker AuthZ, selinux, fulcio, otel, x/net, x/text, grpc High |
| `mitigate` | 0 | — |
| `accept` | 0 | — |

---

## Carrier map (four ostree objects)

From `CVE_BINARY_ANALYSIS_REPORT.md` and `security/reachability/findings/index.json`.
Object → installed binary is **not confirmed** except the kernel NEVRA. Inferences
are labelled as such.

| Ostree object (short) | Advisories | Modules | Installed candidate |
|---|---:|---|---|
| `…8f/bfb47329…` | 15 | `x/crypto`, `opencontainers/selinux`, `sigstore/fulcio`, `docker/docker`, `x/net` (+ later `x/text` v0.32.0 matches) | likely **skopeo** (`/usr/sbin/skopeo`, also `/usr/bin/skopeo` in Phase 5). Unconfirmed. **bootc not probed.** |
| `…8c/c9b0248b…` | 7 | `moby/buildkit`, `containers/podman/v5`, `google.golang.org/grpc`, `go.opentelemetry.io/otel` (+ `x/text` v0.38.0 matches) | likely **podman** (`/usr/sbin/podman`). Unconfirmed. |
| `…75/5cc7cfe2…` | 1 listed | `golang.org/x/text` **v0.21.0** | previously identified as **toolbox**; package not installed (`evidence/reachability/beta-minimised-binaries.txt`). Object remains in a lower ostree layer. |
| `…ea/cf5a37b7…` | 1 | `linux-kernel` | `kernel-core-7.1.5-200.fc44.x86_64` |

Installed Go binaries (minimised image): podman 5.8.4-1.fc44, skopeo 1.22.2-2.fc44,
bootc 1.16.4-1.fc44. Toolbox RPM: not installed. Modes: 0755 root:root, no setuid
(`evidence/reachability/beta-permissions.txt`).

**Do not treat “toolbox leftover” as clearing `GO-2026-5970`.** Phase 5
`candidate-fixed.json` still matches `golang.org/x/text` **v0.32.0** on
`/usr/bin/skopeo` and **v0.38.0** on `/usr/bin/podman`; advisory fixed version is
`0.39.0`. The v0.21.0/toolbox object is one match among several.

---

## Common reachability sketch (23 Go-module rows)

Measured in every Go bundle under `security/reachability/packages/<ADVISORY>/`:

| Factor | Measured | Source |
|---|---|---|
| Default enablement | **no** — no podman/bootc symlink under `/etc`; no preset enables them | `activation-analysis.json`, `evidence/reachability/beta-facts.txt` |
| Network listener | **no** auto-start — `podman.socket` is unix `%t/podman/podman.sock`, absent from `sockets.target.wants` | same |
| Privilege to invoke carrier | **unprivileged user** — 0755, no setuid, on PATH | `beta-permissions.txt` |
| Bunny / plugin | **no** generic exec; typed broker backends | `sandbox-analysis.json` |
| Desktop | **no** matching `Exec=` | `desktopActivationEvidence` |
| MAC | **SELinux targeted, enforcing** | `sandbox-analysis.json` |
| Package removal | **no** — `bootc` requires podman and skopeo; `rpm-ostree` requires skopeo | `beta-facts.txt` |
| Vulnerable function compiled in and active? | **unknown** | all `finding.json` `vulnerableFunctionOrSubsystem` |

Sandbox residual (every Go sandbox analysis): a local user may invoke the
binaries directly; SELinux confines a rootless invocation and does not remove
the code. Confinement is blast radius, not a reachability answer. No SELinux
denial testing against a deliberate invocation was performed.

Kernel row differs: reached by syscalls, privilege `kernel`, JFS extended
attributes — see `CVE-2020-27815`.

---

## Full table

CVE IDs in the first column are scanner-attributed (GHSA/GO URL or
`qualifiers.cves`). Several `finding.json` records still have `"cveId": "unknown"`.
Do not treat the CVE column as NVD-verified.

Abbreviations: **FP-cand** = `false-positive` candidate (checklist required).
**Q7** = “is the vulnerable path compiled in and active?”

| Advisory / CVE | Package / carrier (as installed, if known) | Sev | Current | Recommended | Evidence present / required | Reachability sketch | Release impact | Owner | Conf. |
|---|---|---|---|---|---|---|---|---|---|
| **GHSA-5cgq-3rg8-m6cv** CVE-2026-42508 | `golang.org/x/crypto` v0.46.0 in ostree `…8fbfb473…`; candidates skopeo/podman/bootc. SSH `knownhosts` / `hostKeyDB.IsRevoked`. | Crit | Unknown | **FP-cand** | Present: bundle `security/reachability/packages/GHSA-5cgq-3rg8-m6cv/`; Phase 5 `qualifiers.go_imports` + `route/binary-symbol-probe.txt` (skopeo+podman lack `ssh/knownhosts`). Required: bootc probe; debuginfo+build tags; independent reviewer. | Local user → skopeo/podman/bootc. No default unit. Q7 unknown. SSH stack **not seen** in skopeo/podman strings; bootc unprobed. Go inlining ⇒ absent symbol ≠ absent code. | Blocks **stable**. Blocks **alpha** (Critical). | Security (review) + Platform (image/debuginfo) | med |
| **GHSA-89gr-r52h-f8rx** CVE-2026-39831 | same `x/crypto` v0.46.0 / `…8fbfb473…`. SSH `CertChecker` / `Dial` / `NewServerConn`. | Crit | Unknown | **FP-cand** | Same bundle family; same Phase 5 SSH qualifier set (`route/advisory-symbol-qualifiers.txt`). Required: same checklist as 5cgq, plus confirm `golang.org/x/crypto/ssh` absent from **bootc**. | Same activation. FIDO/U2F physical-presence bypass is an SSH-server/client path. | Blocks stable + alpha. | Security + Platform | med |
| **GHSA-f5wc-c3c7-36mc** CVE-2026-39832 | same. SSH **agent** `client.Add` / `keyring.Add`. | Crit | Unknown | **FP-cand** | Same. Required: agent package presence in each of podman, skopeo, **bootc**. | Same. Agent-forwarding path; Bunny does not ship an SSH agent unit. | Blocks stable + alpha. | Security + Platform | med |
| **GHSA-jppx-rxg9-jmrx** CVE-2026-39833 | same. SSH agent `keyring.Add`. | Crit | Unknown | **FP-cand** | Same. | Same. | Blocks stable + alpha. | Security + Platform | med |
| **GHSA-rm3j-f69w-wqmq** CVE-2026-39834 | same. SSH `channel.Write` / session/kex symbols. | Crit | Unknown | **FP-cand** | Same. Infinite loop on large channel writes — SSH transport. | Same. | Blocks stable + alpha. | Security + Platform | med |
| **GHSA-vgwf-h737-ff37** CVE-2026-39830 | same. SSH `Client.Listen*` / mux. | Crit | Unknown | **FP-cand** | Same. Client deadlock on unexpected responses. | Same. | Blocks stable + alpha. | Security + Platform | med |
| **GHSA-x527-x647-q7gg** CVE-2026-46595 and/or CVE-2024-45337 (scanner URLs disagree; `finding.json` cveId unknown) | same. SSH `NewServerConn` / `serverAuthenticate`. | Crit | Unknown | **FP-cand** | Same SSH qualifier. Reconcile CVE alias before review closes. | Same. VerifiedPublicKeyCallback skip is an SSH **server** authenticate path. | Blocks stable + alpha. | Security + Platform | med |
| **GHSA-p77j-4mvh-x3m3** CVE-2026-33186 | `google.golang.org/grpc` v1.72.2 in ostree `…8cc9b024…`; **survives** Phase 5 binary-reading scan. Qualifier: `Server.Serve`, `ServeHTTP`, `handleStream`. Phase 5: podman runs a gRPC server. | Crit | Unknown | **fix** | Present: bundle `…/GHSA-p77j-4mvh-x3m3/`; Phase 5 still reports this Critical at function granularity. Required: Fedora podman with grpc ≥ 1.79.3 **or** independent review that the auth-bypass `:path` is not reachable from any podman API Bunny or a local user can hit. | Local user / `podman.socket` (not enabled) → podman gRPC. Unprivileged invocability **yes**. SELinux yes. Q7: **not determined**, but scanner function-match is the opposite of the seven SSH Criticals. | Blocks stable + alpha. Highest-priority Critical to **fix**. | **upstream Fedora** (podman rebuild) + Security (reachability of Serve) | high that module is in podman; med that the bypass is hittable on Bunny |
| **GHSA-65gg-3w2w-hr4h** | `github.com/containers/podman/v5` `v5.0.0-2026…+dirty` in `…8cc9b024…`. Installed RPM **podman-5.8.4-1.fc44** (scanner pseudo-version ≠ NEVRA). Fix 5.5.2 — version correspondence for a `Not present` claim would need review; do not invent “already fixed”. | High | Unknown | **fix** | Bundle `…/GHSA-65gg-3w2w-hr4h/`. Survives candidate `oci-archive:`/`dir:` scans. Required: confirm `podman machine` TLS path compiled into 5.8.4; Fedora rebuild. | Activation: user runs `podman machine …`. Not default-enabled. Bunny does not invoke it. Residual: any local user can. | Blocks **stable**. Does **not** alone block Alpha condition 2. | Fedora + Security | med |
| **GHSA-wp3j-xq48-xpjw** | same podman/v5 carrier. `podman kube play` symlink traversal. Fix 5.6.1. | High | Unknown | **fix** | Bundle `…/GHSA-wp3j-xq48-xpjw/`. Survives function-granularity candidate scans. Required: Fedora podman ≥ 5.6.1 or review of kube-play code in 5.8.4. | Activation: `podman kube play` on attacker-controlled YAML. No unit. Local user. | Blocks stable. Not Alpha condition 2. | Fedora + Security | med |
| **GHSA-x744-4wpc-v9h2** CVE-2026-34040 | `github.com/docker/docker` v28.5.1 in `…8fbfb473…`. Phase 5: still matched on **`/usr/bin/skopeo`** binary scan (AuthZ plugin bypass / oversized bodies). | High | Unknown | **fix** | Bundle `…/GHSA-x744-4wpc-v9h2/`. Function-level match on skopeo is **not** an SSH-style exclusion. Required: whether AuthZ plugin code is reachable from skopeo CLI (may be vendored dead API) — that is review, not a current FP. Fedora skopeo rebuild. | No dockerd unit in facts. Local user invokes skopeo. AuthZ plugins are a **dockerd** feature; reachability from skopeo is Q7. | Blocks stable. Not Alpha condition 2. | Fedora + Security | med (present in skopeo binary match); low that AuthZ is a skopeo feature |
| **GHSA-4c29-8rgm-jvjj** | `github.com/moby/buildkit` v0.25.1 in `…8cc9b024…` (podman object). Malicious frontend file escape. Fix 0.28.1. | High | Unknown | **fix** | Bundle `…/GHSA-4c29-8rgm-jvjj/`. Present on candidate binary/archive scans; **absent** from skopeo-only binary scan → podman-side. Required: is `podman build` / buildkit frontend compiled in 5.8.4? | Activation: `podman build` with attacker frontend. Not default. Local user. | Blocks stable. Not Alpha condition 2. | Fedora + Security | med |
| **GHSA-4vrq-3vrq-g6gg** | same buildkit. Git URL subdir → restricted files. | High | Unknown | **fix** | Bundle `…/GHSA-4vrq-3vrq-g6gg/`. Same carrier as 4c29. | Activation: `podman build` with attacker Git URL. | Blocks stable. Not Alpha condition 2. | Fedora + Security | med |
| **GHSA-cgrx-mc8f-2prm** | `github.com/opencontainers/selinux` v1.12.0 in `…8fbfb473…`. Scanner URL also cites runc GHSA-fh74-hm69-rqjw (gadget/procfs). Fix 1.13.0. **Matched on skopeo binary scan.** | High | Unknown | **fix** | Bundle `…/GHSA-cgrx-mc8f-2prm/`. Function-level match on skopeo. Required: map advisory to selinux vs runc; whether gadgets exist in skopeo’s link of this module. Do **not** call FP solely because the URL names runc. | Container-runtime escape class. Skopeo is not runc; podman uses a runtime (`crun` is 0755 in `beta-permissions.txt`). Q7 unknown. | Blocks stable. Not Alpha condition 2. | Fedora + Security | med |
| **GHSA-f5mr-q85p-6hh6** | `github.com/sigstore/fulcio` v1.7.1 in `…8fbfb473…`. OIDC discovery SSRF / JWKS substitution. Fix 1.8.6. **Skopeo binary scan still matches.** | High | Unknown | **fix** | Bundle `…/GHSA-f5mr-q85p-6hh6/`. Server-shaped bug in a client binary is a **review** question (`Present but unreachable` if Fulcio HTTP server is not linked). Not an FP without debuginfo. | No Fulcio unit. Local user → skopeo (cosign/sigstore client paths possible). | Blocks stable. Not Alpha condition 2. | Fedora + Security | med |
| **GHSA-f83f-xpx7-ffpw** | same fulcio v1.7.1. Excessive memory during token parsing. Fix 1.8.3. Skopeo binary match. | High | Unknown | **fix** | Bundle `…/GHSA-f83f-xpx7-ffpw/`. Same as f5mr. | Same. DoS if token-parse path is compiled in and fed untrusted input. | Blocks stable. Not Alpha condition 2. | Fedora + Security | med |
| **GHSA-mh2q-q3fh-2475** | `go.opentelemetry.io/otel` v1.36.0 in `…8cc9b024…`. Baggage header allocation DoS. Fix 1.41.0. Candidate function-granularity still reports it; also in skopeo-binary scan JSON (confirm carrier). | High | Unknown | **fix** | Bundle `…/GHSA-mh2q-q3fh-2475/`. Required: which binary exports otel baggage parsing; whether untrusted headers reach it. | Local user / whatever telemetry podman or skopeo enables. No Bunny listener. | Blocks stable. Not Alpha condition 2. | Fedora + Security | med |
| **GHSA-q4h4-gmj2-qvw2** CVE-2026-46597 | `x/crypto` v0.46.0 / `…8fbfb473…`. “Invoking byte arithmetic underflow/panic.” **Dropped** from Phase 5 candidate `oci-archive:`/`dir:` (with the seven Criticals). Not in `advisory-symbol-qualifiers.txt` (that file lists Criticals only). | High | Unknown | **FP-cand** | Bundle `…/GHSA-q4h4-gmj2-qvw2/`. Weaker than the seven Criticals: no committed `go_imports` dump for this GHSA. Required: pull qualifier; bootc probe; reviewer. | Same SSH/crypto activation sketch. | Blocks stable. Not Alpha condition 2. | Security + Platform | **low–med** |
| **GHSA-w879-237q-wc7r** CVE-2026-39829 | `x/crypto` v0.46.0. Pathological RSA/DSA DoS. Also dropped from Phase 5 binary-reading candidate scans. | High | Unknown | **FP-cand** | Bundle `…/GHSA-w879-237q-wc7r/`. RSA/DSA may exist **outside** SSH (skopeo/podman do carry other `x/crypto` packages). Checklist must prove the **vulnerable functions**, not merely “SSH absent”. | If the vuln is in rsa/dsa used for image signatures, function-level drop may be a matcher artefact **or** a real exclusion. Unknown. | Blocks stable. Not Alpha condition 2. | Security + Platform | **low–med** |
| **GO-2026-5026** | `golang.org/x/net` v0.48.0 in `…8fbfb473…`. Punycode ToASCII/ToUnicode accepts ASCII-only labels. Fix 0.55.0. **Skopeo binary scan matches.** | High | Unknown | **fix** | Bundle `…/GO-2026-5026/`. IDNA is plausible in registry/HTTPS clients (skopeo, bootc). Required: Fedora rebuild; confirm bootc also carries v0.48.0. | Network name processing if those APIs are linked. Local user or bootc update fetch (timer **not** enabled). | Blocks stable. Not Alpha condition 2. | Fedora + Security | med–high module in skopeo; med Q7 |
| **GO-2026-5942** | `golang.org/x/net` v0.48.0. SVCB/HTTPS RR parse panic. Fix 0.56.0. Skopeo binary match. | High | Unknown | **fix** | Bundle `…/GO-2026-5942/`. DNS HTTPS RR parsing — possible in modern HTTP stacks. | Same as 5026. | Blocks stable. Not Alpha condition 2. | Fedora + Security | med |
| **GO-2026-5970** | `golang.org/x/text` **several versions**. July unique row: v0.21.0 on `…755cc7cfe2…` (toolbox leftover). Phase 5 also: **v0.32.0 `/usr/bin/skopeo`**, **v0.38.0 `/usr/bin/podman`**. Fix **0.39.0** — 0.32 and 0.38 are still in range. | High | Unknown | **fix** | Bundle `…/GO-2026-5970/` documents the toolbox hypothesis. **Do not convert to Not-present on toolbox absence.** Required: Fedora skopeo/podman with x/text ≥ 0.39.0; optional: confirm toolbox object is not an installed executable (already `rpm -q toolbox` not installed). | Infinite loop in `norm.Iter` on invalid UTF-8. If linked, any text-norm path. Toolbox invocation: **no installed `/usr/bin/toolbox`**. Skopeo/podman invocation: **yes**. | Blocks stable. Not Alpha condition 2. | Fedora (primary) + Platform (carrier confirmation) | **high** that installed binaries still match; toolbox-only story is **false** as a full disposition |
| **GHSA-hrxh-6v49-42gf** | `google.golang.org/grpc` v1.72.2 in `…8cc9b024…`. xDS RBAC + HTTP/2. Fix 1.82.1. Candidate function-granularity still reports; skopeo-binary JSON also lists it (verify whether skopeo or shared scan). | High | Unknown | **fix** | Bundle `…/GHSA-hrxh-6v49-42gf/`. Same Fedora podman/skopeo grpc bump as the Critical, likely a **higher** floor (1.82.1 vs 1.79.3). Required: is xDS compiled into podman? | If only xDS is vulnerable, may be `Present but unreachable` after review. Until then **fix**. | Blocks stable. Not Alpha condition 2. | Fedora + Security | med |
| **CVE-2020-27815** | `linux-kernel` / `kernel-core-7.1.5-200.fc44.x86_64`. Ostree `…eacf5a37b7…`. Scanner “fixed in **4.9.249**”. 2020 JFS xattr bug. | High | Unknown | **FP-cand** | Bundle `…/CVE-2020-27815/`; notes in `CVE_REACHABILITY_DISPOSITION_REPORT.md`. Required checklist below. **Being almost certainly fine is not evidence.** | Kernel/syscall. Local attacker who can set JFS xattrs. Privilege: kernel. JFS may not be a supported Bunny filesystem — **unverified**. | Blocks **stable**. Not Alpha condition 2. | Security + Platform (kernel config/changelog) | med (artefact looks strong; CONFIG_JFS / Fedora changelog **not** done) |

---

## False-positive candidate checklists

None of these checklists is complete today. Completing one still requires
`release/cve.py` fields (`Not present` needs matching versions, build
configuration, symbol-or-source mapping, **and** a reviewer). Symbol absence in
a stripped or Go binary is **insufficient** (`CVE_BINARY_ANALYSIS_REPORT.md`).

### A. Seven Critical `golang.org/x/crypto` SSH advisories

`GHSA-5cgq-3rg8-m6cv`, `GHSA-89gr-r52h-f8rx`, `GHSA-f5wc-c3c7-36mc`,
`GHSA-jppx-rxg9-jmrx`, `GHSA-rm3j-f69w-wqmq`, `GHSA-vgwf-h737-ff37`,
`GHSA-x527-x647-q7gg`.

Already present:

- [x] Module v0.46.0 recorded in ostree `…8fbfb473…` (`evidence/vulnerability/beta-grype.json`)
- [x] Phase 5 `qualifiers.go_imports` names SSH / agent / knownhosts symbols (`qualification/phase5/security/route/advisory-symbol-qualifiers.txt`)
- [x] `strings` probe: `golang.org/x/crypto/ssh/knownhosts` and `hostKeyDB.IsRevoked` **absent** from `/usr/bin/skopeo` and `/usr/bin/podman` (`qualification/phase5/security/route/binary-symbol-probe.txt`)
- [x] Phase 5 `oci-archive:` and `dir:` of candidate `e906a48793d7` report **1** Critical (grpc), not 8 (`SCAN_ROUTE_DISCREPANCY.md`)
- [x] Grype’s own SBOM warning: module granularity “may report false positives”
- [x] Nine of ten bounded reachability questions answered in each package bundle

Still required before converting `Unknown`:

- [ ] Repeat the symbol probe on **`/usr/sbin/bootc`** (not in `binary-symbol-probe.txt`)
- [ ] Map ostree `…8fbfb473…` → exact installed path (`find -samefile` / `ostree ls` on a mounted image)
- [ ] Acquire matching debuginfo/debugsource (`security/reachability/sources/ACQUISITION.md`); `acquisition-manifest.json` **does not exist**
- [ ] Per-advisory mapping of the named function into the shipped build (Go inlining)
- [ ] Reconcile `GHSA-x527-x647-q7gg` CVE aliases (CVE-2024-45337 vs CVE-2026-46595)
- [ ] Independent reviewer in the delivered-review set; Critical self-review is refused

Until then official class stays **Unknown** (blocks stable and Alpha).

### B. Two High `x/crypto` rows dropped at function granularity

`GHSA-q4h4-gmj2-qvw2`, `GHSA-w879-237q-wc7r`.

Already present:

- [x] Absent from Phase 5 candidate `oci-archive:` / `dir:` match sets (same drop as the seven Criticals)
- [x] Present at SBOM/module granularity (`candidate-sbom-fixed.json`, July `beta-grype.json`)

Still required:

- [ ] `go_imports` / affected symbols for these two GHSAs (not in `advisory-symbol-qualifiers.txt`)
- [ ] For `GHSA-w879-237q-wc7r`: show the RSA/DSA DoS is not in a **non-SSH** `x/crypto` package that skopeo/podman **do** link (probe lists argon2, blake2b, chacha20, …)
- [ ] bootc probe; debuginfo; reviewer

Confidence is **lower** than cluster A. Prefer `Unknown` over conversion.

### C. `CVE-2020-27815` (JFS / version classifier)

Already present:

- [x] Installed `7.1.5-200.fc44.x86_64` vs scanner fixed version `4.9.249` (`security/reachability/packages/CVE-2020-27815/finding.json`)
- [x] Documented as classifier artefact in `CVE_REACHABILITY_DISPOSITION_REPORT.md` and the bundle `notes`

Still required:

- [ ] Fedora `kernel` changelog / CVE mapping for 7.1.5-200.fc44 (JFS xattr fix presence)
- [ ] `CONFIG_JFS` / whether JFS is built in `kernel-core` of this NEVRA
- [ ] Confirm the ostree object is the running `vmlinuz` / modules, not a leftover
- [ ] Reviewer. Do **not** record `Remediated` or `Not present` on version-arithmetic alone

---

## `fix` cluster — Fedora rebuild (14 advisories)

ADR-027 waiting condition 2: Fedora ships podman/skopeo (and by implication
bootc) with `golang.org/x/crypto` ≥ 0.52.0 and `google.golang.org/grpc` ≥
1.79.3. Several Highs need **higher** floors (grpc 1.82.1, x/net 0.56.0, x/text
0.39.0, buildkit 0.28.1, fulcio 1.8.6, otel 1.41.0, docker 29.3.1, selinux
1.13.0, podman 5.6.1).

`dnf check-update podman skopeo` was empty at the 2026-07-29 base rebuild; a
new digest did not move counts. Bunny cannot apply these versions from
`build/packages/`.

Independent review remains a **parallel** path for individual Highs that are
present in a binary but not reachable (Fulcio server, docker AuthZ, xDS). That
path is `Present but unreachable`, not `false-positive`, and still needs the
reviewer. This triage does not pre-assign that class.

Priority order for Fedora/Platform tracking:

1. **GHSA-p77j-4mvh-x3m3** (only Critical that survives function-granularity)
2. Podman-native Highs (`65gg`, `wp3j`) and buildkit (`4c29`, `4vrq`)
3. grpc High `hrxh` (may ride the same podman rebuild if the floor is 1.82.1)
4. skopeo-matched Highs: x/net, fulcio, docker, selinux, x/text ≥ 0.39.0
5. otel

---

## What this triage does not do

- Does not edit `security/reachability/findings/*.json` conclusions
- Does not create a waiver or reduce severity
- Does not acquire debuginfo or mount the image
- Does not run `analyse-symbols` (still blocked: binaries not on this host)
- Does not satisfy `vulnerability-gate` or `gate-stable-release`

`python scripts/release.py cve-disposition` is expected to keep reporting
`Unknown 24` / `BLOCKED` until an independent review or a Fedora rebuild
changes the inputs.

---

## Pointers for the reviewer

Each advisory: `security/reachability/packages/<ID>/{summary.md,finding.json,installed-package.json,source-package.json,binary-analysis.json,activation-analysis.json,sandbox-analysis.json,evidence-manifest.json,review-questions.md}`.

Acquisition plan (unexecuted): `security/reachability/sources/ACQUISITION.md`.

Request: `reviews/security/REQUEST.md`.
