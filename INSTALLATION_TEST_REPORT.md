# Bunny OS Phase 3 installation test report

Date: 2026-07-28  
Host: Windows source checkout; no Linux installer, block devices, or VM

| Area | Result |
|---|---|
| Phase 1/2 preflight | PASS static: 92 tests, one Linux-only skip; 24 structural checks |
| repository validation | PASS: 27 JSON, 13 schemas, 130 Python, 9 desktop, 8 XML/SVG |
| Phase 3 installer unit suite | PASS: 60 tests |
| combined source tests | PASS: 152, one skip |
| `gate-phase-3` | PASS static mode |
| schema meta-validation | SKIP: `jsonschema` unavailable |
| Bash syntax | PASS for seven new Phase 3 scripts under MSYS2 Bash |
| real disk discovery | NOT RUN |
| erase/encrypted/alongside/manual execution | NOT RUN; production adapter absent |
| media signature | mocked-process unit tests only; no signed artifact |
| clean VM install | BLOCKED: no ISO/QEMU/KVM |
| encrypted VM install | BLOCKED |
| Phase 2 upgrade/rollback | BLOCKED: no Phase 2 disk or signed deployment |
| recovery | BLOCKED |
| physical hardware | NOT PERFORMED |

The 12 fixture classes are synthetic lsblk metadata, not disk images. They qualify parsing and safety policy only. No partition table, filesystem, LUKS header, EFI variable, boot entry, user account, or deployment was changed.

Static coverage and limitations are detailed in `PHASE_3_REPORT.md`. Installation definition of done is not met.
