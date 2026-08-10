# Bunny OS current-state audit

**Audit date:** 2026-07-28  
**Repository:** `COMRADEART/bunny-os`  
**Baseline commit:** `8fc27253e448cfe0cbe267231f816012f831ebf0` (`main`)  
**Implementation branch:** `feature/os-foundation`  
**Audit mode:** read-only until this file was created

## Scope and evidence

This audit inspected the complete tracked Bunny OS tree, every Phase 0 constitution and Phase 1 architecture/ADR artifact, the existing verifier, Git status and history, and non-generated untracked content. Generated dependency and build trees were inventoried by location and size rather than treated as source. It also reviewed the six required release reports from the separate Bunny checkout at `C:\Users\allam\Documents\new\bun-main`, pinned at commit `f27fa63e0406e91149aeacf8437c36b960e09961` on `feature/bunny-desktop-and-release`.

Repository claims below distinguish implemented code from specifications and roadmaps. A named roadmap component is not counted as implemented.

## User-owned workspace state

The baseline worktree was clean for tracked files and contained these untracked paths:

| Path | Observed content | Treatment |
|---|---|---|
| `.selfcheck-tmp/` | Generated Bunny self-check databases, logs, fixtures, transcripts and temporary state | Preserved; not read as Bunny OS source and not modified |
| `desktop/` | Rust `target/` build artifacts only | Preserved; not treated as Bunny OS implementation |
| `node_modules/` | Installed JavaScript dependencies | Preserved; excluded from source inventory |
| `ui/.test/app.js` | Generated/test browser bundle | Preserved; not treated as tracked Bunny OS implementation |

No cleanup, reset, overwrite, or move was performed on these paths.

## Current tracked repository tree

```text
.
├── .gitignore
├── BUNNY_OS_PHASE_0.md
└── docs/
    └── phase-1/
        ├── ACCESSIBILITY_CONFORMANCE_MATRIX.md
        ├── ADVERSARIAL_REVIEW.md
        ├── BUNNY_OS_PHASE_1.md
        ├── PHASE_2_BACKLOG.md
        ├── README.md
        ├── SOURCES.md
        ├── TRACEABILITY_MATRIX.md
        ├── verify.ps1
        ├── adr/
        │   ├── 0001-linux-base-strategy.md
        │   ├── 0002-browser-first-vs-native-shell.md
        │   ├── 0003-runtime-reuse-strategy.md
        │   ├── 0004-service-boundaries.md
        │   ├── 0005-protocol-evolution.md
        │   ├── 0006-event-driven-vs-request-driven.md
        │   ├── 0007-plan-task-persistence.md
        │   ├── 0008-memory-storage-model.md
        │   ├── 0009-permission-policy-model.md
        │   ├── 0010-sandbox-technology-strategy.md
        │   ├── 0011-local-model-runtime.md
        │   ├── 0012-model-router-strategy.md
        │   ├── 0013-personality-provider-separation.md
        │   ├── 0014-plugin-mcp-isolation.md
        │   ├── 0015-application-compatibility.md
        │   ├── 0016-update-and-rollback.md
        │   ├── 0017-x86-64-and-arm64.md
        │   ├── 0018-browser-client-authentication.md
        │   ├── 0019-observability-and-audit-retention.md
        │   └── 0020-custom-kernel-decision.md
        └── diagrams/
            ├── 01-system-context.mmd
            ├── 02-container-services.mmd
            ├── 03-deployment-mode-a-host.mmd
            ├── 04-deployment-mode-b-box.mmd
            ├── 05-deployment-mode-c-shell.mmd
            ├── 06-deployment-mode-d-os.mmd
            ├── 07-deployment-low-resource.mmd
            ├── 08-deployment-workstation.mmd
            ├── 09-trust-boundaries.mmd
            ├── 10-intent-to-execution.mmd
            ├── 11-permission-sequence.mmd
            ├── 12-local-to-cloud-escalation.mmd
            ├── 13-failure-recovery.mmd
            ├── 14-memory-retrieval-update.mmd
            └── 15-plugin-execution.mmd
```

## Implemented components

At the baseline commit, Bunny OS contains no operating-system implementation. The implemented repository-native behavior is limited to:

- the Phase 0 product constitution;
- the provisional Phase 1 architecture/specification and companion evidence documents;
- twenty ADRs and fifteen Mermaid diagram sources;
- `docs/phase-1/verify.ps1`, which structurally validates the documentation set.

The existing documentation verifier passed 24 reported checks when invoked with a process-scoped PowerShell execution-policy bypass. It verified numbered sections, contracts, amendments, prototype IDs, trace rows, ADR structure/status gates, diagram/state-machine presence, WCAG rows, relative links, backlog structure and source identifiers. It does not build code, parse the current Mermaid files, validate an image, boot a VM, or test hardware.

## Placeholder and specified-only components

Every runtime and OS component named in the existing architecture is specified-only at this baseline, including:

- bootc image layer and image builder;
- developer, minimal, desktop and recovery profiles;
- `bunny-system-broker` and its authentication/authorization boundary;
- OS capability discovery and the `bunny-os` CLI;
- systemd system and user units;
- SELinux policies;
- firewall policy;
- first-boot flow;
- update manifest, staging, health checks and rollback;
- recovery image and recovery tools;
- Bunny Desktop/Core OS packaging and integration contract;
- SBOM/provenance generation;
- image, boot, VM, broker, update, rollback, recovery, privacy and security tests;
- Bunny OS CI/CD.

The untracked `desktop/` and `ui/` paths are generated artifacts from another build and do not establish any of these Bunny OS components.

## Existing build, CI, image and packaging state

| Area | Baseline finding |
|---|---|
| Image definitions | None |
| Build manifests/profiles | None |
| Package manifest | None |
| Root filesystem overlay | None |
| Containerfile | None |
| Makefile or task runner | None |
| Bunny OS CI workflows | None |
| systemd units | None |
| SELinux policy | None |
| Update metadata/signing policy | None |
| Recovery image | None |
| SBOM tooling | None |
| VM boot tooling | None |
| Packaging files | None |
| Existing validation | Documentation structure only |

## Broken scripts and host constraints

- Direct execution of `docs/phase-1/verify.ps1` fails on this Windows host because the machine execution policy disables scripts. `powershell -NoProfile -ExecutionPolicy Bypass -File docs/phase-1/verify.ps1` passes and changes policy only for that process.
- `rg.exe` is discoverable but execution is denied in this environment. Inventory used `git ls-files` and PowerShell traversal instead.
- The existing verifier contains mojibake in terminal output under Windows PowerShell's default decoding. Reading the sources explicitly as UTF-8 is required.
- The verifier's own final message says Mermaid parsing is a separate pinned-tool run. No Mermaid CLI is declared by this repository.

## Host build status and missing dependencies

This audit host is Windows and has Node, npm, Python and Rust/Cargo. It does not have:

- Podman or Docker;
- QEMU or `qemu-img`;
- an installed WSL Linux distribution;
- GNU Make or Bash;
- `systemd-analyze`;
- ShellCheck;
- cosign;
- Syft, Grype, or another SBOM/vulnerability scanner;
- a Linux kernel/runtime capable of building or boot-testing a bootc image.

Therefore no baseline image build, systemd analysis, Linux security-policy test, SBOM generation, QEMU smoke test, rollback test, recovery boot, or hardware qualification could be performed locally. These are environment constraints, not passing results.

## Governing architecture constraints

The constitution and accepted ADRs establish these binding constraints:

- Linux remains the upstream kernel; no kernel fork or new kernel is permitted.
- Bunny OS is an image layer on an existing atomic base, not a package-archive distribution.
- The base pattern is Fedora/bootc with an OCI image, transactional deployments and rollback.
- User data, Bunny state and general assistant models live outside the OS image. The Alpha image makes one narrow exception for its immutable, byte-manifested offline speech-recognition model; see `docs/VOICE_IMAGE_PACKAGING.md`.
- Bunny Core remains the intelligence/application layer and cannot replace systemd, the bootloader, kernel, drivers, network stack or mandatory access control.
- A trusted, narrow Broker owns OS authority; model-directed processes receive no root, generic shell, unrestricted sudo, container socket, arbitrary D-Bus forwarding or arbitrary filesystem-write capability.
- SELinux remains enabled for the selected Fedora base.
- Conventional Linux administration and recovery remain available without Bunny.
- Public OS distribution remains evidence-gated; a developer image must not be represented as a consumer release.

Verified upstream evolution changes one tool selection: the standalone `bootc-image-builder` is being deprecated in favor of the unified OSBuild `image-builder` CLI. The new implementation should use the unified builder while retaining bootc as the installed update/rollback backend.

## Bunny artifacts and compatibility

The audited Bunny checkout reports product version `0.2.0`, app protocol version `3`, Tauri `2.11.5`, Tauri CLI `2.11.4`, and source head `f27fa63e0406e91149aeacf8437c36b960e09961`.

The Bunny Desktop release design produces these Linux artifact classes:

- AppImage;
- DEB;
- RPM;
- Tauri updater artifacts and signatures;
- `SHA256SUMS` and Sigstore bundle;
- CycloneDX SBOMs;
- signed Bunny update manifest and Tauri feed;
- Bunny Core and `ccgrep` sidecars embedded in the Tauri bundle.

The desktop host expects the target-suffixed sidecars `bunny-core-x86_64-unknown-linux-gnu` and `ccgrep-x86_64-unknown-linux-gnu` during packaging. At runtime it owns Bunny Box, supervises Bunny Core/app-server, and uses a random-port loopback endpoint with ephemeral authentication. Protocol v3 has a generated JSON Schema and supports additive compatibility; clients must negotiate, query capabilities, tolerate unknown notifications and must not infer authority from method availability.

No signed Linux Bunny Desktop artifact is present in either checkout. The upstream release reports explicitly mark AppImage/DEB/RPM production, signing, clean installation and update/recovery qualification as pending. Bunny OS must therefore consume a digest-pinned verified release artifact when supplied and use an explicit non-functional placeholder in developer images until then. Rebuilding or copying Bunny source into Bunny OS would violate the repository boundary and is not planned.

## Unverified assumptions

- Fedora 44 base image tags and all packages required by the desktop profile will remain available for the pinned snapshot/build date.
- The unified `image-builder` version selected for CI can consume the chosen Fedora bootc image and emit both QCOW2 and a recovery/installer prototype.
- GNOME/Mutter provides the required Wayland, portal and accessibility behavior on the exact Fedora 44 tuple.
- A signed Bunny 0.2.x Linux RPM or AppImage will be supplied with provenance and checksums before any image is called Bunny-integrated.
- GitHub-hosted CI can provide the nested virtualization or privileged Podman access needed for full image builds and QEMU boot smoke tests.
- Secure Boot, TPM2-assisted LUKS, NVIDIA and physical-hardware support remain unverified until named tests run.

## Security gaps

- No broker implementation or local caller authentication exists.
- No exact method allowlist, operation schema, timeout/rate-limit/cancellation enforcement or broker audit log exists.
- No systemd hardening or `systemd-analyze security` evidence exists.
- No SELinux policy or denial test exists.
- No default firewall configuration exists.
- No signed OS update metadata, key rotation/revocation policy implementation or rollback-protection test exists.
- No image secret scan, world-writable-path check, listener check or privacy egress test exists.
- No first-boot state machine or offline/privacy default enforcement exists.
- No recovery path independent of Bunny exists.
- No Secure Boot or TPM result exists.

## Integration gaps

- No versioned Bunny-to-OS contract exists.
- No contract-version compatibility validator exists.
- No OS-native Bunny package adapter exists.
- No user-session service units exist for Bunny Core/app-server/Desktop.
- No OS capability/status/update/recovery transport exists.
- No native settings, notification, power or file-dialog integration is connected through an OS contract.
- The upstream Bunny protocol has no Bunny OS contract version; the two versions must remain independent.
- The required OS-side privileged operations are absent from upstream Bunny, which is correct. They must be exposed only through the OS broker and not duplicated as Bunny Core logic.

## Recommended implementation order

1. Preserve the accepted Fedora/bootc direction in new OS-specific ADRs and define filesystem, boot, update, recovery, user and privilege boundaries.
2. Add a versioned JSON Schema for the Bunny OS contract and the update manifest before implementation freezes field names.
3. Implement the narrow local broker and peer-credential authorization with exact typed operations; add adversarial unit tests before any mutating backend is enabled.
4. Implement read-only capability discovery and the conventional `bunny-os` management CLI.
5. Add hardened systemd units, SELinux policy, firewall defaults, first-boot and health-check scaffolding.
6. Add the Fedora 44 bootc image layer, package manifest, profiles and unified `image-builder` orchestration.
7. Add update/rollback and recovery prototypes with signed-manifest verification separated from artifact transport.
8. Add image inspection, SBOM/provenance, security/privacy tests and CI.
9. Build and boot the developer QCOW2 on a qualified Linux runner; record exact evidence. Do not claim a boot, VM, Secure Boot, TPM, GPU or hardware result that was not observed.

## Baseline conclusion

The repository is a rigorous architecture-document set, not an operating system implementation. Its documentation verifier is green, but every Phase 1 OS runtime, image, integration and security deliverable begins at zero. The implementation can proceed without conflicting with user changes by adding new tracked paths and leaving the four untracked artifact trees untouched.
