# Package minimisation

Date: 2026-07-29. Profiles reviewed: developer, desktop, beta, shell, live.

**One package removed. The vulnerability count did not change. That is the
result, and it is the reason the rule against removing things to lower a score
exists.**

## The rule that comes first

Five categories are protected and may not be removed:

recovery tools, accessibility tools, required firmware, installer dependencies,
security tooling.

This is enforced in two places rather than documented and hoped for:

- `release/minimisation.py` rejects a removal record whose category is
  protected, at parse time.
- `build/scripts/install-packages.py` reads `build/packages/protected.txt`,
  refuses to remove anything on it, and — after the removal — verifies every
  protected package that was installed beforehand is still installed. A
  dependency cascade that quietly takes `orca` or `cryptsetup` with it fails the
  build instead of shipping.

The build log records the check:

```text
minimisation: removed toolbox; 28 protected packages intact
```

## What was removed

### `toolbox`

| Field | Value |
|---|---|
| Profiles | desktop, beta, shell, live |
| Category | developer-tooling |
| Why it was present | It arrives in `quay.io/fedora/fedora-bootc:44`. It is in no consumer package set; `build/packages/developer.txt` lists it deliberately for the developer profile only. |
| Dependents | none — `rpm -q --whatrequires toolbox` returns nothing |
| Size | 12,651,096 B Go binary |
| Rationale | An interactive container workflow a consumer installation has no use for. Removing it removes 12.6 MB of executable Go from the PATH of every user. |

Verification, all five steps:

| Step | Result |
|---|---|
| Rebuilt | beta rebuilt from the pinned base digest |
| Booted | `vm-smoke` reached the boot marker under KVM |
| Tests run | full source suite plus the closure suites |
| SBOM regenerated | 6077 packages, unchanged |
| Vulnerability scan rerun | 59 fixable, 8 Critical, 28 High — unchanged |

After: `command -v toolbox` finds nothing, and `rpm -q toolbox` reports
`package toolbox is not installed`. Evidence:
`evidence/reachability/beta-minimised-binaries.txt`.

## The finding that matters more than the removal

**Removing the package changed no scan number, and the SBOM still lists it.**

That is not a bug in the removal. It is a property of the artifact being
scanned, and it was worth measuring:

- `/usr/bin/toolbox` is gone and the rpm database entry is gone. Verified in a
  running container from the built image.
- syft still reports `toolbox 0.3-4.fc44`, located at
  `/sysroot/ostree/repo/objects/75/5cc7cf…file` in base layer `sha256:4f84a1cce95eb`.
- The same is true with `--scope squashed` and `--scope all-layers`.

The `fedora-bootc` base ships an ostree object store, and package content lives
there as content-addressed objects. `dnf remove` unlinks the file from `/usr`
and updates the rpm database; it does not and cannot remove the object from a
store baked into a lower layer of the base image.

So the removal is real where it matters for *execution* — the binary is not on
any PATH, not in the package database, not startable — and is not real for
*bytes shipped*. Both statements are true and they are frequently conflated.

Three consequences worth stating plainly:

1. **Minimisation on this base cannot reduce image size or SBOM contents.** Only
   a base rebuilt without the package can.
2. **SBOM-derived and archive-derived scan counts disagree.** Scanning the
   archive directly reports 59 fixable; running grype against the syft SPDX
   document reports 84. The archive scan is the one used for the vulnerability
   position, and the discrepancy is recorded here rather than averaged away.
3. **The carrier paths in every finding are ostree objects**, which is why
   `SECURITY_REACHABILITY_REVIEW.md` had to establish binary presence separately
   rather than reading it off the scan.

## What was deliberately retained

Fifteen packages were reviewed and explicitly kept. The full record with reasons
is `operations/data/package-minimisation.json`. The ones that would most obviously
"help" a scan score, and were kept anyway:

| Package | Category | Why it stays |
|---|---|---|
| `podman` | installer-dependency | `bootc` requires it. It carries 6 of the 24 blocking findings and still cannot go. |
| `skopeo` | installer-dependency | `bootc` and `rpm-ostree` require it. |
| `orca` | accessibility-tool | Screen reader. Removing it makes the system unusable for blind users. |
| `at-spi2-core` | accessibility-tool | Every assistive technology depends on it. |
| `mousetweaks` | accessibility-tool | Pointer accessibility. |
| `cryptsetup` | recovery-tool | Without it an encrypted installation cannot be unlocked, including from recovery media. |
| `smartmontools`, `nvme-cli` | recovery-tool | Storage diagnostics when the installed system will not boot. |
| `linux-firmware` | required-firmware | Wi-Fi, graphics, storage on machines nobody has tested yet. |
| `fwupd` | required-firmware | Firmware security fixes delivered outside the OS. |
| `selinux-policy-targeted` | security-tooling | It is part of the mitigation argument for every unresolved finding. |
| `firewalld`, `bubblewrap` | security-tooling | Inbound policy and the sandbox boundary. |
| `anaconda` | installer-dependency | The installer. |
| `memtest86+` | recovery-tool | A diagnostic on media a user boots when nothing else works. |

## Running the check

```text
make package-minimisation-check
python scripts/release.py package-minimisation-check
```

It fails closed: a removal missing any of the five verification steps, or
touching a protected category, blocks.
