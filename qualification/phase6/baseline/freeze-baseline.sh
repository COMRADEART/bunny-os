#!/usr/bin/bash
# Phase 6 §2 — freeze the technical baseline by MEASURING it.
# Nothing here is copied from a previous record; every digest is recomputed
# from the bytes on disk so the record can be compared with what the build claimed.
set -uo pipefail

OUT=/home/bunny/p6-evidence/baseline
mkdir -p "$OUT"
LOG="$OUT/freeze.log"
: > "$LOG"

P4_DIR=/root/bunny-build-archive/beta-phase4-rc-e906a48793d7-20260818T014208Z
P5_DIR=/root/bunny-os/build/out/beta
ISO_DIR=/root/bunny-os/build/out/live/bootc-fedora-44-bootc-generic-iso-x86_64

say() { printf '%s\n' "$*" | tee -a "$LOG"; }

say "=== Phase 6 baseline freeze — started $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

say ""
say "--- Phase 4 Alpha RC (Phase 6 subject artifact) ---"
say "dir: $P4_DIR"
if [ -d "$P4_DIR" ]; then
  ( cd "$P4_DIR" && find . -type f -printf '%P\t%s\n' | sort ) > "$OUT/p4-inventory.tsv"
  cat "$OUT/p4-inventory.tsv" >> "$LOG"
  for m in BUNNY-MANIFEST.json provenance.json SHA256SUMS normalisation.json; do
    [ -f "$P4_DIR/$m" ] && cp "$P4_DIR/$m" "$OUT/p4-$m"
  done
  say ""
  say "recomputing digests for every image and archive under the Phase 4 dir:"
  ( cd "$P4_DIR" && find . -type f \( -name '*.qcow2' -o -name '*.raw' -o -name '*.tar' -o -name '*.iso' \) -print0 \
      | sort -z | xargs -0 -r sha256sum ) > "$OUT/p4-recomputed.sha256"
  cat "$OUT/p4-recomputed.sha256" >> "$LOG"
  say ""
  say "SHA256SUMS as the build recorded them:"
  cat "$P4_DIR/SHA256SUMS" >> "$LOG" 2>/dev/null
else
  say "ABSENT — the Phase 4 archive directory does not exist"
fi

say ""
say "--- Phase 5 build (update/rollback N+1 counterpart) ---"
say "dir: $P5_DIR"
if [ -d "$P5_DIR" ]; then
  ( cd "$P5_DIR" && find . -type f -printf '%P\t%s\n' | sort ) > "$OUT/p5-inventory.tsv"
  cat "$OUT/p5-inventory.tsv" >> "$LOG"
  for m in BUNNY-MANIFEST.json provenance.json SHA256SUMS normalisation.json; do
    [ -f "$P5_DIR/$m" ] && cp "$P5_DIR/$m" "$OUT/p5-$m"
  done
  say ""
  say "recomputing digests:"
  ( cd "$P5_DIR" && find . -type f \( -name '*.qcow2' -o -name '*.raw' -o -name '*.tar' \) -print0 \
      | sort -z | xargs -0 -r sha256sum ) > "$OUT/p5-recomputed.sha256"
  cat "$OUT/p5-recomputed.sha256" >> "$LOG"
  say ""
  say "SHA256SUMS as the build recorded them:"
  cat "$P5_DIR/SHA256SUMS" >> "$LOG" 2>/dev/null
else
  say "ABSENT"
fi

say ""
say "--- Installation medium for the subject artifact ---"
say "dir: $ISO_DIR"
if [ -d "$ISO_DIR" ]; then
  ls -la "$ISO_DIR" >> "$LOG"
  say ""
  say "recomputing ISO digest (this is the medium a physical machine would boot):"
  ( cd "$ISO_DIR" && find . -type f -name '*.iso' -print0 | sort -z | xargs -0 -r sha256sum ) \
      > "$OUT/iso-recomputed.sha256"
  cat "$OUT/iso-recomputed.sha256" >> "$LOG"
  for m in BUNNY-MANIFEST.json SHA256SUMS provenance.json; do
    [ -f "$ISO_DIR/../$m" ] && cp "$ISO_DIR/../$m" "$OUT/live-$m"
  done
else
  say "ABSENT"
fi

say ""
say "--- Base image identity, as the local store holds it ---"
podman images --digests --format '{{.Repository}}:{{.Tag}} {{.Digest}} {{.ID}}' 2>/dev/null \
  > "$OUT/podman-images.txt"
grep -i -E 'fedora-bootc|bunny' "$OUT/podman-images.txt" >> "$LOG" 2>/dev/null

say ""
say "=== finished $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
touch "$OUT/.done"
