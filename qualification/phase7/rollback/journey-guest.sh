#!/usr/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Runs inside the guest on every boot of the journey disk, driven by the step
# file in the shared stateroot /var. Reports first, acts second, so even a
# boot that dies mid-action leaves the identity evidence on the serial log.
set -uo pipefail
mark() { echo "BUNNY-P7: $*"; }
# Emitted twice: the serial console is shared with the kernel and with
# systemd's own status lines, and run 2 proved any single line can be split
# mid-value. Two copies of a short marker do not both get split.
mark2() { mark "$*"; mark "$*"; }
step="$(cat /var/lib/bunny-p7/step 2>/dev/null || echo absent)"

# Runs 1 and 2 of this journey each lost one marker line to a kernel message
# (an SELinux relabel warning) landing mid-line on ttyS0. The kernel is the
# only writer that interleaves at character level; silence printk to the
# console for the duration of the report. The journal keeps everything.
dmesg -n 1 2>/dev/null || true

mark "BEGIN step=${step}"
mark "cmdline=$(cat /proc/cmdline)"
# The full cmdline above is the record; the short marker below is the one the
# grader reads. The first run of this harness proved a 300-byte serial line is
# not atomic: a kernel SELinux message landed in the middle of the cmdline
# marker and split the ostree= argument across lines. A 64-hex marker printed
# twice survives interleaving; the value still comes from the kernel's own
# /proc/cmdline, so the source stays independent of bootc and of /etc.
bootcsum="$(grep -oE 'ostree=/ostree/boot\.[0-9]+/[^/ ]+/[a-f0-9]{64}/[0-9]+' /proc/cmdline \
  | grep -oE '[a-f0-9]{64}' | head -1)"
mark2 "cmdline-bootcsum=${bootcsum:-UNREADABLE}"
mark2 "etc-identity=$(cat /etc/bunny-p7-etc-identity 2>/dev/null || echo ABSENT)"
mark2 "hostname-file=$(cat /etc/hostname 2>/dev/null || echo ABSENT)"
mark "hostname-transient=$(hostname 2>/dev/null || echo UNKNOWN)"
mark2 "locale=$(grep -h '^LANG=' /etc/locale.conf 2>/dev/null || echo ABSENT)"

# The full JSON is the record; the short markers are what the grader reads —
# run 2 lost the 2 KB single-line JSON to interleaving.
bootc_json="$(bootc status --json 2>/dev/null || true)"
printf '%s\n' "${bootc_json}" | sed 's/^/BUNNY-P7-BOOTC: /'
eval "$(printf '%s' "${bootc_json}" | python3 -c '
import json, sys
try:
    booted = json.load(sys.stdin)["status"]["booted"]
    print("BOOTC_CSUM=%s" % ((booted.get("ostree") or {}).get("checksum") or ""))
    print("BOOTC_IMAGE=%s" % (((booted.get("image") or {}).get("image") or {}).get("image") or ""))
except Exception:
    pass' 2>/dev/null)"
mark2 "bootc-booted-checksum=${BOOTC_CSUM:-UNREADABLE}"
mark2 "bootc-booted-image=${BOOTC_IMAGE:-UNREADABLE}"

echo "BUNNY-P7-OSTREE-STATUS-BEGIN"
ostree admin status 2>&1 | sed 's/^/BUNNY-P7-OSTREE: /'
echo "BUNNY-P7-OSTREE-STATUS-END"

for f in /var/home/p5-user-data.txt /var/home/p7-user-data.txt \
         /var/lib/bunny-os/companion/p5-mode.json \
         /var/lib/bunny-os/companion/p7-scale.json \
         /var/lib/bunny-os/companion/p7-position.json \
         /var/lib/bunny-os/trust/p5-grants.json \
         /var/lib/bunny-os/voice/p5-settings.json \
         /var/lib/bunny-os/p5-settings.txt; do
  if [ -f "$f" ]; then
    line="$(sha256sum "$f")"
  else
    line="ABSENT  $f"
  fi
  echo "BUNNY-P7-SHA: ${line}"
  echo "BUNNY-P7-SHA: ${line}"
done

# Written by prepare.sh into both deployments: BEFORE_UPDATE and
# UPDATE_TARGET, the deploy commits of N and N+1.
if [ -f /etc/bunny-p7/expected.env ]; then
  # shellcheck source=/dev/null
  . /etc/bunny-p7/expected.env
fi
booted_commit="$(cat /etc/bunny-p7-etc-identity 2>/dev/null || echo UNKNOWN)"

case "${step}" in
  restage)
    # The disk may sit on either deployment when the journey begins. The
    # qualified rollback must run N+1 -> N, so this step puts the machine on
    # N+1 first -- and if it is already there, says so and flips nothing.
    if [ "${booted_commit}" = "${UPDATE_TARGET:-}" ]; then
      mark "restage: already on the update target, nothing to flip"
    else
      mark "restage: running bootc rollback to select the update target"
      bootc rollback 2>&1 | sed 's/^/BUNNY-P7-RESTAGE-OUT: /'
      mark "restage exit=${PIPESTATUS[0]}"
    fi
    echo "BUNNY-P7-OSTREE-AFTER-BEGIN"
    ostree admin status 2>&1 | sed 's/^/BUNNY-P7-OSTREE-AFTER: /'
    echo "BUNNY-P7-OSTREE-AFTER-END"
    after_default="$(ostree admin status 2>/dev/null | grep -oE '[a-f0-9]{64}' | head -1)"
    mark2 "ostree-after-default=${after_default:-UNREADABLE}"
    printf 'rollback\n' >/var/lib/bunny-p7/step
    ;;
  rollback)
    mark "running bootc rollback"
    bootc rollback 2>&1 | sed 's/^/BUNNY-P7-ROLLBACK-OUT: /'
    mark "rollback exit=${PIPESTATUS[0]}"
    echo "BUNNY-P7-OSTREE-AFTER-BEGIN"
    ostree admin status 2>&1 | sed 's/^/BUNNY-P7-OSTREE-AFTER: /'
    echo "BUNNY-P7-OSTREE-AFTER-END"
    after_default="$(ostree admin status 2>/dev/null | grep -oE '[a-f0-9]{64}' | head -1)"
    mark2 "ostree-after-default=${after_default:-UNREADABLE}"
    printf 'verify\n' >/var/lib/bunny-p7/step
    ;;
  verify)
    printf 'done\n' >/var/lib/bunny-p7/step
    ;;
  *)
    mark "no action for step=${step}"
    ;;
esac
sync
mark "END step=${step}"
