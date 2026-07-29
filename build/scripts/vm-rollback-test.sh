#!/usr/bin/env bash
set -euo pipefail

previous="${BUNNY_PREVIOUS_BETA_DISK:-}"
candidate="${BUNNY_STABLE_CANDIDATE_DISK:-}"
test_disk="${BUNNY_ROLLBACK_TEST_DISK:-}"
for command in qemu-system-x86_64 qemu-img; do
  command -v "$command" >/dev/null || { echo "missing rollback VM command: $command" >&2; exit 3; }
done
[[ -f "$previous" && -f "$candidate" ]] || { echo "signed previous-beta and candidate QCOW2 inputs are required" >&2; exit 3; }
[[ -n "$test_disk" && "$test_disk" == *.qcow2 && ! -e "$test_disk" ]] || { echo "BUNNY_ROLLBACK_TEST_DISK must name a new disposable QCOW2" >&2; exit 3; }

echo "Rollback fixture inputs are present. Automated deployment mutation requires the reviewed Linux/KVM harness and preservation manifest collector." >&2
exit 78
