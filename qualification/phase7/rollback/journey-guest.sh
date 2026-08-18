#!/usr/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Runs inside the guest on every boot of the journey disk, driven by the step
# file in the shared stateroot /var. Reports first, acts second, so even a
# boot that dies mid-action leaves the identity evidence on the serial log.
set -uo pipefail
mark() { echo "BUNNY-P7: $*"; }
step="$(cat /var/lib/bunny-p7/step 2>/dev/null || echo absent)"

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
mark "cmdline-bootcsum=${bootcsum:-UNREADABLE}"
mark "cmdline-bootcsum=${bootcsum:-UNREADABLE}"
mark "etc-identity=$(cat /etc/bunny-p7-etc-identity 2>/dev/null || echo ABSENT)"
mark "hostname-file=$(cat /etc/hostname 2>/dev/null || echo ABSENT)"
mark "hostname-transient=$(hostname 2>/dev/null || echo UNKNOWN)"
mark "locale=$(grep -h '^LANG=' /etc/locale.conf 2>/dev/null || echo ABSENT)"

bootc status --json 2>/dev/null | sed 's/^/BUNNY-P7-BOOTC: /'

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
    echo "BUNNY-P7-SHA: $(sha256sum "$f")"
  else
    echo "BUNNY-P7-SHA: ABSENT  $f"
  fi
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
    printf 'rollback\n' >/var/lib/bunny-p7/step
    ;;
  rollback)
    mark "running bootc rollback"
    bootc rollback 2>&1 | sed 's/^/BUNNY-P7-ROLLBACK-OUT: /'
    mark "rollback exit=${PIPESTATUS[0]}"
    echo "BUNNY-P7-OSTREE-AFTER-BEGIN"
    ostree admin status 2>&1 | sed 's/^/BUNNY-P7-OSTREE-AFTER: /'
    echo "BUNNY-P7-OSTREE-AFTER-END"
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
