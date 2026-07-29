# Stable release checklist

Last updated: 2026-07-29. `BLOCKED` is a release blocker; `PASS-SOURCE` is not stable evidence.

| Category | Status | Owner | Evidence | Blocker | Target | Last updated |
|---|---|---|---|---|---|---|
| Architecture | PASS-SOURCE | Engineering | Phase 1–3 static gates | runtime unqualified | stable-rc1 | 2026-07-29 |
| Kernel | BLOCKED | Kernel | kernel record NOT_RUN | no selected/tested branch | stable-rc1 | 2026-07-29 |
| Installer | BLOCKED | Installer | source journal/tests | no production/destructive run | stable-rc1 | 2026-07-29 |
| Encryption | BLOCKED | Installer/Security | design only | no LUKS boot/recovery | stable-rc1 | 2026-07-29 |
| Secure Boot | BLOCKED | Security | none | no signed positive/negative boot | stable-rc1 | 2026-07-29 |
| Updates | BLOCKED | Maintenance | routes rejected | no signed beta update | stable-rc1 | 2026-07-29 |
| Rollback | BLOCKED | Maintenance | source preservation tests | no supported execution | stable-rc1 | 2026-07-29 |
| Recovery | BLOCKED | Recovery | source definition | no independent recovery ISO | stable-rc1 | 2026-07-29 |
| Hardware | BLOCKED | Hardware | zero reports | no physical evidence | stable-rc1 | 2026-07-29 |
| Drivers | BLOCKED | Hardware | empty regression ledger | no runtime matrix | stable-rc1 | 2026-07-29 |
| Bunny integration | BLOCKED | Engineering | placeholder contract tests | no signed functional artifact | stable-rc1 | 2026-07-29 |
| Applications | BLOCKED | Applications | unqualified catalogue | no SBOM/signature/runtime review | stable-rc1 | 2026-07-29 |
| Multi-user | BLOCKED | Security | source evidence rules | no installed isolation run | stable-rc1 | 2026-07-29 |
| Local-only | BLOCKED | Engineering | source evidence rules | no installed offline run | stable-rc1 | 2026-07-29 |
| Privacy | BLOCKED | Privacy | redaction source tests | no traffic/bundle/cross-user runtime | stable-rc1 | 2026-07-29 |
| Security | BLOCKED | Security | source review | unresolved runtime/supply-chain blockers | stable-rc1 | 2026-07-29 |
| Accessibility | BLOCKED | Accessibility | static tests | essential runtime flows untested | stable-rc1 | 2026-07-29 |
| Performance | BLOCKED | Performance | host microbenchmarks only | no boot/power/pressure/soak | stable-rc1 | 2026-07-29 |
| Documentation | PASS-SOURCE | Documentation | Phase 5 guide audit | release-specific evidence absent | stable-rc1 | 2026-07-29 |
| Support | BLOCKED | Maintenance | no-duration policy | capacity/duration unapproved | stable-rc1 | 2026-07-29 |
| Maintenance | BLOCKED | Maintenance | alert-only source | no operated patch/release process | stable-rc1 | 2026-07-29 |
| Signing | BLOCKED | Release/Security | fail-closed scripts | no key ceremony/signatures | stable-rc1 | 2026-07-29 |
| Licensing | BLOCKED | Legal/Release | source policy | no release SBOM/license report | stable-rc1 | 2026-07-29 |
| Publication | BLOCKED | Release | NO-GO report | protected gate fails | stable | 2026-07-29 |
