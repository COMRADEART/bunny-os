#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Phase 7 rollback qualification — step 2 of 2: the journey itself.
#
# Refuses to boot anything until the expectation prepare.sh wrote has been
# committed to the repository and still matches the evidence copy byte for
# byte. The point is sequencing, not ceremony: an expectation that can be
# edited after the result is in is not an expectation.
#
# Two persistent boots of the prepared overlay (no snapshot=on here — the
# rollback must survive the reboot), then the verdict, computed by verdict.py
# from the expectation and the two serial logs. This script does not decide
# PASS; it only runs the journey and hands the evidence to the grader.
set -uo pipefail

repo="${BUNNY_REPO:-/root/bunny-os}"
# shellcheck source=build/scripts/vm-lib.sh
source "${repo}/build/scripts/vm-lib.sh"

WORK="${BUNNY_P7_WORK:-/home/bunny/p7-work/rollback}"
EVIDENCE="${BUNNY_P7_EVIDENCE:-/home/bunny/p7-evidence/rollback}"
DISK="${WORK}/journey.qcow2"
EXPECTATION="${EVIDENCE}/expectation.json"
COMMITTED="${repo}/qualification/phase7/rollback/expectation.json"
timeout_seconds="${BUNNY_VM_TIMEOUT:-900}"

bunny_require_commands qemu-system-x86_64 python3 cmp

[[ -f "${DISK}" ]] || { echo "NOT_RUN: no prepared journey disk; run prepare.sh first" >&2; exit 5; }
[[ -f "${EXPECTATION}" ]] || { echo "NOT_RUN: no expectation.json; run prepare.sh first" >&2; exit 5; }

if ! git -C "${repo}" ls-files --error-unmatch \
      qualification/phase7/rollback/expectation.json >/dev/null 2>&1; then
  echo "REFUSED: the expectation is not committed. Commit it, then run the journey." >&2
  exit 2
fi
if ! cmp -s "${EXPECTATION}" "${COMMITTED}"; then
  echo "REFUSED: the committed expectation differs from the one prepare.sh wrote." >&2
  exit 2
fi

firmware="$(bunny_firmware)" || exit 3

boot() {
  local log="$1"
  : >"${log}"
  local status=0
  timeout "${timeout_seconds}" qemu-system-x86_64 \
    -machine q35,accel=kvm:tcg \
    -cpu max -smp 4 -m 6144 \
    -bios "${firmware}" \
    -drive "file=${DISK},format=qcow2,if=virtio" \
    -device virtio-net-pci,netdev=net0 -netdev user,id=net0 \
    -display none -serial "file:${log}" -no-reboot || status=$?
  if [[ ${status} -ne 0 && ${status} -ne 124 ]]; then
    echo "QEMU failed with status ${status}; see ${log}" >&2
    return "${status}"
  fi
  return 0
}

echo "== boot S: restage — put the machine on the update target =="
boot "${EVIDENCE}/boot-restage.log"
grep -a "BUNNY-P7" "${EVIDENCE}/boot-restage.log" \
  | sed 's/^\[[^]]*\] *//;s/^bash\[[0-9]*\]: //' | head -40 | sed 's/^/  /'

echo
echo "== boot R: the machine rolls itself back =="
boot "${EVIDENCE}/boot-rollback.log"
grep -a "BUNNY-P7" "${EVIDENCE}/boot-rollback.log" \
  | sed 's/^\[[^]]*\] *//;s/^bash\[[0-9]*\]: //' | head -40 | sed 's/^/  /'

echo
echo "== boot V: which deployment actually came up? =="
boot "${EVIDENCE}/boot-verify.log"
grep -a "BUNNY-P7" "${EVIDENCE}/boot-verify.log" \
  | sed 's/^\[[^]]*\] *//;s/^bash\[[0-9]*\]: //' | head -40 | sed 's/^/  /'

echo
echo "== verdict =="
python3 "${repo}/qualification/phase7/rollback/verdict.py" \
  "${EXPECTATION}" \
  "${EVIDENCE}/boot-restage.log" \
  "${EVIDENCE}/boot-rollback.log" \
  "${EVIDENCE}/boot-verify.log" \
  --out "${EVIDENCE}/verdict.json"
status=$?
echo "verdict.py exit=${status} (0 PASS, 4 FAIL, 5 NOT_RUN)"
exit "${status}"
