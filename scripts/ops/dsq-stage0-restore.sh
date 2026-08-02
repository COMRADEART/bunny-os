#!/usr/bin/env bash
# Restore the 23 EOL-mangled serial.log files from the pre-commit backup
# (whose bytes match the digests attested in each record.json), then verify.
set -u
cd /root/bunny-os || exit 1
BK=/root/tpm-untracked-backup-20260801
restored=0
for f in $(cd qualification/tpm && git ls-files . | grep 'serial\.log$'); do
  t="qualification/tpm/$f"
  b="$BK/$f"
  [ -f "$b" ] || continue
  if ! cmp -s "$t" "$b"; then
    cp -p "$b" "$t"
    restored=$((restored+1))
  fi
done
echo "restored: $restored"
bash scripts/ops/dsq-stage0-crlf-scan.sh | tail -1
