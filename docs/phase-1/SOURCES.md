# Bunny OS Phase 1 — External Evidence Register

**Snapshot date:** 2026-07-26  
**Purpose:** source trail for material external claims in `BUNNY_OS_PHASE_1.md`. Repository-specific claims are separately grounded in `COMRADEART/bunny` at commit `f147f078adfb2a414a8366accd358c42dd431875` and in `BUNNY_OS_PHASE_0.md`.

This register favors standards, upstream documentation, vendor advisories, specifications, and primary research. A benchmark result is evidence about the tested configuration, not a universal product guarantee. A source being listed does not transfer authority to it: Phase 0 remains the governing product document.

## 1. Linux isolation and execution

| ID | Primary source | What it supports | Used in |
|---|---|---|---|
| LNX-01 | [Linux Landlock userspace API](https://docs.kernel.org/userspace-api/landlock.html) | Unprivileged, stackable restriction of ambient filesystem and network rights; ABI and mediation limits | §12.4–§12.5 |
| LNX-02 | [Linux cgroup v2](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html) | Hierarchical process organization and resource-controller semantics | §12.3–§12.5 |
| LNX-03 | [Linux seccomp filter](https://docs.kernel.org/userspace-api/seccomp_filter.html) | System-call attack-surface reduction and user-notification caveats | §12.5 |
| LNX-04 | [bubblewrap README](https://github.com/containers/bubblewrap/blob/main/README.md) | Namespace/mount/seccomp construction; bubblewrap is a low-level mechanism, not a complete policy | §12.2, §12.5 |
| LNX-05 | [Ubuntu AppArmor privilege restrictions](https://documentation.ubuntu.com/security/docs/security-features/privilege-restriction/apparmor/) | Ubuntu's restrictions on unprivileged user namespaces and the need for an installed profile | §12.2, §12.4 |
| LNX-06 | [gVisor platform compatibility](https://gvisor.dev/docs/user_guide/compatibility/) | Compatibility limits, host-side cgroup enforcement, and constrained device support | §12.2, §12.5 |
| LNX-07 | [gVisor GPU guide](https://gvisor.dev/docs/user_guide/gpu/) | `nvproxy` supports selected NVIDIA configurations, requires close driver compatibility, and does not fully isolate host-driver vulnerabilities | §12.2, §12.9 |
| LNX-08 | [Firecracker repository](https://github.com/firecracker-microvm/firecracker) | Current microVM feature set and release status | §12.2, §12.5 |
| LNX-09 | [Firecracker changelog](https://github.com/firecracker-microvm/firecracker/blob/main/CHANGELOG.md) | Generic PCI/VirtIO work landed; it should not be described as wholly paused | §12.2 |
| LNX-10 | [Firecracker GPU/VFIO discussion](https://github.com/firecracker-microvm/firecracker/discussions/4845) | GPU/VFIO work was paused; no stable general GPU-passthrough tier follows from generic PCI support | §12.2, §12.9 |
| LNX-11 | [Linux user namespaces](https://man7.org/linux/man-pages/man7/user_namespaces.7.html) | UID/GID and capability remapping semantics; user namespaces do not remove the shared-kernel attack surface | §12.4–§12.5 |
| LNX-12 | [Podman rootless mode](https://docs.podman.io/en/latest/markdown/podman.1.html) | Rootless container authority is bounded by the launching account, subject to kernel isolation limits | §12.5 |
| LNX-13 | [systemd.exec sandboxing](https://man7.org/linux/man-pages/man5/systemd.exec.5.html) | Service-sandbox directives and their platform/kernel-availability caveats | §12.4, §20 |
| LNX-14 | [Firecracker FAQ](https://github.com/firecracker-microvm/firecracker/blob/main/FAQ.md) | Headless/minimal-device design and explicit non-goals for desktop-style device support | §12.2, §12.9 |

## 2. Atomic OS, desktop applications, portals, and compatibility

| ID | Primary source | What it supports | Used in |
|---|---|---|---|
| OS-01 | [bootc introduction](https://bootc.dev/bootc/) | Transactional in-place operating-system updates using OCI images | §20.1–§20.3 |
| OS-02 | [bootc upgrades and rollback](https://bootc.dev/bootc/upgrades.html) | Staged deployments; `/var` persists while `/etc` is managed per deployment and rollback semantics require explicit testing | §20.1, §20.3 |
| OS-02a | [bootc rollback manual](https://bootc.dev/bootc/man/bootc-rollback.8.html) | Deployment rollback semantics | §20.3 |
| OS-02b | [bootc install-to-disk manual](https://bootc.dev/bootc/man/bootc-install-to-disk.8.html) | Current `--block-setup tpm2-luks` support; encryption is an upstream path to validate rather than a Bunny-built mechanism | §20.1, ADR 0016, H-5 |
| OS-02c | [bootc experimental composefs](https://bootc.dev/bootc/experimental-composefs.html) | Sealed/composefs backend remains experimental and cannot support a production integrity claim | §20.1–§20.3 |
| OS-03 | [rpm-ostree administrator handbook](https://coreos.github.io/rpm-ostree/administrator-handbook/) | Offline staged updates, rollback, and the read-only `/usr` model | §20.1–§20.3 |
| OS-04 | [systemd-sysext](https://www.freedesktop.org/software/systemd/man/devel/systemd-sysext.html) | Overlay-based extension of immutable `/usr` and `/opt` images | §20.1 |
| OS-05 | [Flatpak basic concepts](https://docs.flatpak.org/en/latest/basic-concepts.html) | Default sandbox and portal model | §20.7 |
| OS-06 | [Flatpak command reference](https://docs.flatpak.org/en/latest/flatpak-command-reference.html) | Host/home filesystem, device, and socket permission semantics | §20.7 |
| OS-06a | [Flatpak sandbox permissions](https://docs.flatpak.org/en/latest/sandbox-permissions.html) | Broad filesystem, bus, socket, and device grants can materially weaken the sandbox | §20.7 |
| OS-07 | [XDG Desktop Portal overview](https://flatpak.github.io/xdg-desktop-portal/docs/) | Narrow host services for sandboxed applications | §20.5, §21 |
| OS-08 | [Documents portal](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.Documents.html) | Explicit, mediated document access | §20.5 |
| OS-09 | [ScreenCast portal](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.ScreenCast.html) | Consent, restore tokens, and PipeWire stream handoff | §20.5 |
| OS-10 | [RemoteDesktop portal](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.RemoteDesktop.html) | Mediated keyboard, pointer, and touch control | §20.5 |
| OS-11 | [Flatpak advisory GHSA-cc2q-qc34-jprg](https://github.com/flatpak/flatpak/security/advisories/GHSA-cc2q-qc34-jprg) | CVE-2026-34078: pre-1.16.4 portal symlink sandbox escape and host-code execution | §20.7 |
| OS-12 | [NVD CVE-2026-34078](https://nvd.nist.gov/vuln/detail/CVE-2026-34078) | Independent severity/version record for the April 2026 Flatpak escape | §20.7 |
| OS-13 | [Valve Proton](https://github.com/ValveSoftware/Proton) | Windows-game compatibility layer scope and current upstream | §21 |
| OS-14 | [Steam Runtime](https://github.com/ValveSoftware/steam-runtime) | Containerized runtime used by current Proton/Steam Linux execution | §21 |
| OS-15 | [Steam Deck compatibility review](https://partner.steamgames.com/doc/steamhardware/compat) | Ongoing compatibility review and anti-cheat/middleware constraints | §21 |
| OS-16 | [Wayland architecture](https://wayland.freedesktop.org/) | Compositor/client boundaries and the maintained protocol ecosystem | §20.4–§20.5 |
| OS-17 | [XWayland security model](https://wayland.freedesktop.org/docs/book/Xwayland.html) | A shared X server does not provide Wayland-style client isolation | §20.4, §21 |
| OS-18 | [Linux DRM userspace API](https://www.kernel.org/doc/html/latest/gpu/drm-uapi.html) | Render-node semantics and the remaining kernel-driver ioctl surface | §12.9, §21 |
| OS-19 | [Linux VFIO](https://docs.kernel.org/driver-api/vfio.html) | IOMMU-group/device-assignment constraints | §12.9 |
| OS-20 | [NVIDIA MIG concepts](https://docs.nvidia.com/datacenter/tesla/mig-user-guide/concepts.html) | Hardware-backed GPU partitioning boundaries and supported configurations | §12.9 |
| OS-21 | [Fedora architectures](https://fedoraproject.org/wiki/Architectures) | Fedora's primary architecture posture | §20.2, ADR 0017 |
| OS-22 | [OCI image index](https://github.com/opencontainers/image-spec/blob/main/image-index.md) | Multiarchitecture image selection by OS/architecture/variant | §20.2, ADR 0017 |

## 3. Local inference and model supply chain

| ID | Primary source | What it supports | Used in |
|---|---|---|---|
| INF-01 | [llama.cpp build guide](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md) | Supported acceleration backends and build-time variability | §13.2–§13.4 |
| INF-02 | [llama.cpp OpenVINO backend](https://github.com/ggml-org/llama.cpp/blob/master/docs/backend/OPENVINO.md) | Intel CPU/GPU/NPU support and explicit work-in-progress limitations | §13.2, §13.5, §13.9 |
| INF-03 | [NVIDIA NIM profile selection](https://docs.nvidia.com/nim/large-language-models/latest/deployment/model-profiles-and-selection.html) | Hardware/VRAM-aware profiles and the need to bind capability claims to detected resources | §13.2–§13.4 |
| INF-04 | [Hugging Face pickle security](https://huggingface.co/docs/hub/security-pickle) | Arbitrary-code risk in pickle-based model artifacts and scanner limitations | §13.5, §26 |
| INF-05 | [Berkeley Function Calling Leaderboard v4](https://gorilla.cs.berkeley.edu/leaderboard) | Public function-calling and multi-turn measurements; results are configuration-specific | §13.3–§13.4 |
| INF-06 | [ADVICE: Answer-Dependent Verbalized Confidence Estimation](https://aclanthology.org/2026.acl-long.1098/) | Verbalized confidence can be answer-independent and systematically overconfident | §13.3 |

## 4. Agent security, authorization, and threat modeling

| ID | Primary source | What it supports | Used in |
|---|---|---|---|
| SEC-01 | [NIST: Strengthening AI agent hijacking evaluations](https://www.nist.gov/news-events/news/2025/01/technical-blog-strengthening-ai-agent-hijacking-evaluations) | Indirect prompt injection/agent hijacking as a system-level evaluation problem | §11.6, §26 |
| SEC-02 | [OWASP AI Agent Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html) | Least privilege, deterministic authorization, and tool/memory isolation practices | §11, §12, §26 |
| SEC-03 | [OWASP LLM Prompt Injection Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html) | Defense-in-depth controls and the limits of prompt-layer mitigation | §26 |
| SEC-04 | [Before the Tool Call](https://arxiv.org/abs/2603.20953) | Deterministic pre-action authorization measurements, including permissive-policy and restrictive-policy outcomes | §12.1 |
| SEC-05 | [CaMeL: Defeating Prompt Injections by Design](https://arxiv.org/abs/2503.18813) | Control/data-flow separation, taint-aware enforcement, and measured utility trade-off | §26.1, §26.4 |
| SEC-06 | [Anthropic system card, 2026](https://www-cdn.anthropic.com/bbd8ef16d70b7a1665f14f306ee88b53f686aa75.pdf) | Surface- and attempt-dependent prompt-injection rates and defense-in-depth measurements | §26.1 |
| SEC-07 | [Microsoft STRIDE threat modeling](https://learn.microsoft.com/en-us/windows-hardware/drivers/ifs/designing-with-security-threat-models) | STRIDE categories and structured threat-model method | §26.2 |
| SEC-08 | [NIST SP 800-154](https://csrc.nist.gov/pubs/sp/800/154/ipd) | Data-centric threat modeling | §26.2 |
| SEC-09 | [RFC 6455 — WebSocket](https://www.rfc-editor.org/rfc/rfc6455) | `Origin` and `Host` security semantics for browser-initiated WebSocket connections | §24.4 |
| SEC-10 | [RFC 8252 — OAuth 2.0 for native apps](https://www.rfc-editor.org/rfc/rfc8252) | Loopback redirect guidance, IP literals, ephemeral ports, and PKCE | §24.4 |

## 5. Extensions, MCP, and protocol evolution

| ID | Primary source | What it supports | Used in |
|---|---|---|---|
| EXT-01 | [MCP authorization, 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization) | OAuth 2.1 profile, resource binding, PKCE, and prohibition on token passthrough | §19.3–§19.5, §19.7, §24 |
| EXT-02 | [MCP tools, 2025-06-18](https://modelcontextprotocol.io/specification/2025-06-18/server/tools) | Tool schemas and the requirement to treat annotations as untrusted unless the server is trusted | §19.4, §19.7 |
| EXT-03 | [MCP security best practices](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices) | Confused-deputy risks and per-client consent | §11.8, §19.4 |
| EXT-04 | [MCP tool-annotation update, 2026](https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/) | Annotations are policy hints, not authorization | §19.4 |
| EXT-05 | [WASI releases](https://wasi.dev/releases) | WASI 0.2 compatibility baseline, WASI 0.3 stable release, and version status | §12.7, §19.2 |
| EXT-06 | [WASI 0.3](https://wasi.dev/releases/wasi-p3) | Native async component model and the recency of the 0.3 ecosystem | §19.2 |
| EXT-07 | [CloudEvents specification](https://github.com/cloudevents/spec/blob/main/cloudevents/spec.md) | Event-envelope conventions and interoperability vocabulary | §7.4, §18 |
| EXT-08 | [JSON-RPC 2.0 specification](https://www.jsonrpc.org/specification) | Request/response, notification, error, and correlation semantics | §18, Appendix A |

## 6. Memory, provenance, privacy, and audit

| ID | Primary source | What it supports | Used in |
|---|---|---|---|
| MEM-01 | [MemGhost / WhisperBench](https://arxiv.org/abs/2607.05189) | Single-message stealth memory injection and measured cross-agent persistence | §14.1, §26 |
| MEM-02 | [ConvoMem benchmark](https://arxiv.org/abs/2511.10523) | Long-context versus retrieval performance at different history sizes | §14.1 |
| MEM-03 | [Letta filesystem memory benchmark](https://www.letta.com/blog/benchmarking-ai-agent-memory) | Vendor-run LoCoMo comparison showing simple filesystem/search can compete with specialized memory tools | §14.1 |
| MEM-04 | [LoCoMo audit repository](https://github.com/dial481/locomo-audit) | Reproducible but non-peer-reviewed benchmark-quality audit; should be treated as a caution, not a universal invalidation | §14.9 |
| MEM-05 | [W3C PROV-O](https://www.w3.org/TR/prov-o/) | Entity/activity/agent provenance and derivation relations | §14.3, §27 |
| MEM-06 | [GDPR official text](https://eur-lex.europa.eu/eli/reg/2016/679/oj/eng) | Data minimization, rights of access/erasure, and privacy-by-design obligations | §27 |
| MEM-07 | [NIST Privacy Framework](https://www.nist.gov/privacy-framework) | Privacy-risk management vocabulary | §27 |
| MEM-08 | [NIST SP 800-92 — Log Management](https://csrc.nist.gov/pubs/sp/800/92/final) | Log lifecycle, retention, and operational controls | §25, §27 |
| MEM-09 | [SQLite atomic commit](https://www.sqlite.org/atomiccommit.html) | Transaction and crash-consistency properties | §10, §14, §18 |
| MEM-10 | [SQLite WAL](https://www.sqlite.org/wal.html) | Write-ahead logging concurrency and durability trade-offs | §14, §18 |

## 7. Accessibility and multimodal interaction

| ID | Primary source | What it supports | Used in |
|---|---|---|---|
| A11Y-01 | [WCAG 2.2](https://www.w3.org/TR/WCAG22/) | Keyboard operation, focus, contrast, motion, target size, captions, and AA conformance criteria | §16, §17, §28 |
| A11Y-02 | [ARIA Authoring Practices Guide](https://www.w3.org/WAI/ARIA/apg/) | Tested accessible interaction patterns and keyboard models | §16, §28 |
| A11Y-03 | [WAI audio/video guidance](https://www.w3.org/WAI/media/av/) | Captions, transcripts, audio description, and accessible media alternatives | §17, §28 |
| A11Y-04 | [EN 301 549 v3.2.1](https://www.etsi.org/deliver/etsi_en/301500_301599/301549/03.02.01_20/en_301549v030201a.pdf) | European ICT accessibility requirements used as the regulatory baseline | §28 |
| A11Y-05 | [WebAIM Screen Reader User Survey #10](https://webaim.org/projects/screenreadersurvey10/) | Self-selected 2024 survey showing JAWS/NVDA dominance and low primary Orca share; useful for test-matrix risk, not population prevalence | §28.3 |

## 8. Artifact and update supply chain

| ID | Primary source | What it supports | Used in |
|---|---|---|---|
| SUP-01 | [SLSA v1.2](https://slsa.dev/spec/v1.2/) | Supply-chain levels and build provenance | §20.3, §26 |
| SUP-02 | [SLSA provenance](https://slsa.dev/spec/v1.2/provenance) | Attested build provenance fields | §20.3 |
| SUP-03 | [Sigstore cosign verification](https://docs.sigstore.dev/cosign/verifying/verify/) | Digest, certificate identity, and issuer verification | §20.3 |
| SUP-04 | [The Update Framework specification](https://theupdateframework.github.io/specification/) | Role separation, rollback/freeze protection, threshold signatures, and key rotation | §20.3 |
| SUP-05 | [OCI Image Specification](https://specs.opencontainers.org/image-spec/) | Content-addressed descriptors, manifests, and image-layout contracts | §20.1–§20.3 |
| SUP-06 | [bootc image signature policy](https://bootc.dev/bootc/internals/bootc_lib/spec/enum.ImageSignature.html) | bootc's signature-policy integration surface | §20.3 |
| SUP-07 | [bootc boot-failure detection](https://bootc.dev/bootc/boot-failure-detection.html) | Boot counting and rollback-health integration | §20.3, P17 |
| SUP-08 | [Unified Kernel Image specification](https://uapi-group.org/specifications/specs/unified_kernel_image/) | UKI structure for a future measured/verified boot milestone | §20.1–§20.3 |
| SUP-09 | [dm-verity](https://docs.kernel.org/admin-guide/device-mapper/verity.html) | Block-level verified-read semantics; separate from update atomicity | §20.1–§20.3 |

## Evidence limitations

- Product, kernel, driver, and vulnerability status changes. Every time-sensitive source above must be rechecked before a release decision; the snapshot date is not a promise of continuing accuracy.
- Vendor and benchmark results are configuration-specific. They justify prototype gates and risk budgets, not blanket performance claims.
- The WebAIM survey is self-selected. It supports a compatibility-testing priority, not a statement about every screen-reader user.
- The LoCoMo audit is reproducible community work, not peer-reviewed research. It supports caution about small score differences; it does not justify discarding all memory evaluation.
- Architecture claims remain **specified**, not **implemented**, until the Phase 2 backlog's tests and prototypes pass.
