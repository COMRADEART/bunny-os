# ADR-002: Image and update model

- Status: accepted
- Date: 2026-07-28

Use an OCI bootable container with `bootc` deployments and OSTree-compatible transactional state. Produce VM disks with the unified OSBuild `image-builder`; the former standalone `bootc-image-builder` is deprecated and archived ([OSBuild migration notice](https://osbuild.org/docs/bootc/)). Fedora bootc images need an explicit default filesystem, so Phase 1 selects ext4 in `image-builder`.

The OS is **image-managed**, not absolutely immutable. `/usr` and `/opt/bunny` are authored by a content-addressed image and replaced transactionally. Privileged recovery/debug mechanisms can still alter state; `/etc` and `/var` are persistent. Documentation therefore avoids claiming that every root-visible byte is immutable.

Alternatives rejected for Phase 1: a custom A/B partition controller (duplicated state machine), Btrfs snapshots alone (package-managed mutable root), `systemd-sysupdate` alone (more custom composition/integration), and direct OSTree/rpm-ostree composition (less direct OCI release artifact). Migration remains possible because the contract and persistent paths do not expose bootc internals to Bunny.

Signed manifest metadata selects channel, sequence, compatibility, trusted repository, and exact OCI digest. Registry signature policy and production key provisioning remain release gates. `bootc switch` stages the deployment; `bootc rollback` selects the previous one. The updater never runs arbitrary manifest commands.

