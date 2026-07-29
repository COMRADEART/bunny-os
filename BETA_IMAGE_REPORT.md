# Bunny OS Phase 3 beta image report

## Result: definitions added; no beta artifact produced

Definitions now exist for:

- Fedora 44 bootc beta QCOW2/raw payload;
- `bootc-generic-iso` live installer with separate embedded payload ref;
- existing recovery QCOW2;
- Anaconda Web UI/Blivet, offline installer packages and configuration;
- UEFI boot menu with normal, safe graphics, recovery, media verification, and serial entries;
- ephemeral live account, GNOME welcome, internal-media automount disabled;
- deterministic external media manifest, checksum/signing hooks, and strict verification;
- QEMU disposable install/encrypted-install launchers and fail-closed upgrade prerequisite.

No OCI, ISO, QCOW2, raw, recovery, manifest, checksum, signature, SBOM, package inventory, scan, or provenance output was created. The host lacks the builder and the source commit has no release trust inputs. The media manifest has not been embedded and verified inside a completed ISO. Beta candidate publication is blocked.

Make artifact targets were invoked and stopped because Windows Make could not resolve Bash. Direct MSYS2 runs reached explicit prerequisites: beta/live/recovery builds stopped on missing Podman, media verification stopped on absent `build/out/live`, VM install stopped on missing QEMU, upgrade stopped on absent Phase 2 QCOW2, and SBOM stopped on missing Syft. These are blocked attempts, not passes.

Required next command is `FULL_GATE=1 make gate-phase-3` on the documented Fedora/KVM builder after all release inputs are provisioned. Output must be archived from a clean run and must not overwrite evidence.

## 2026-07-29 local validation artifact

A later disposable Fedora 44/WSL validation run built the beta OCI payload and,
after repairing the current image-builder multi-type invocation, produced both
the declared QCOW2 and raw formats. `qemu-img check`, bootc-aware filesystem
inspection, and the QEMU/KVM health smoke passed. See `IMAGE_BUILD_REPORT.md`
and `VM_TEST_REPORT.md` for exact sizes, hashes, and scope.

The final SPDX scan contained 6,077 records. The repaired license policy found
zero unresolved licenses and zero prohibited markers; 306 inferred records
were retained with explicit coverage relationships to licensed RPM owners,
duplicate identities, the Fedora kernel RPM, or the SPDX-described artifact.

The vulnerability gate correctly failed. Grype reported 59 fixable findings:
8 Critical, 28 High, and 23 Medium. The High/Critical records map to the Fedora
kernel and to embedded components in Podman, Skopeo, and Toolbox. Those tools
are present in the beta payload because Fedora's installed `bootc` and
`rpm-ostree` packages require them. No waiver or suppression was added.

The artifact remains a local unsigned validation build, not a public beta. No
live installer ISO, independent recovery ISO, media signature, installation,
upgrade, rollback, reproducibility, physical-hardware, or publication result
was produced.
