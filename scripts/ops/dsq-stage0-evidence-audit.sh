#!/usr/bin/env bash
# Stage 0 audit: compare git-tracked TPM evidence bytes against the pre-commit
# working copy preserved at /root/tpm-untracked-backup-20260801, and against
# the digests attested in each record.json.
set -u
cd /root/bunny-os
BK=/root/tpm-untracked-backup-20260801
diffcount=0
crlfcount=0
othercount=0
for f in $(cd qualification/tpm && git ls-files .); do
  t="qualification/tpm/$f"
  b="$BK/${f#*/}"
  # backup layout mirrors qualification/tpm/<subpath>; f is relative to qualification/tpm
  b="$BK/$f"
  [ -f "$b" ] || continue
  if ! cmp -s "$t" "$b"; then
    diffcount=$((diffcount+1))
    # is the difference purely EOL?
    if cmp -s <(tr -d '\r' < "$t") <(tr -d '\r' < "$b"); then
      crlfcount=$((crlfcount+1))
    else
      othercount=$((othercount+1))
      echo "NON-EOL DIFF: $t"
    fi
  fi
done
echo "tracked-vs-backup differing files: $diffcount (pure-EOL: $crlfcount, other: $othercount)"
echo "---"
git config core.autocrlf || echo "core.autocrlf unset (WSL repo)"
echo "---"
# check the Windows-side repo config via the origin path
git --git-dir=/mnt/c/Users/allam/Documents/new/bunny-os/.git config core.autocrlf || echo "core.autocrlf unset (Windows repo)"
