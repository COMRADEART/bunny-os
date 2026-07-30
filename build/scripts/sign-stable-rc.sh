#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail

root="$(git rev-parse --show-toplevel)"
candidate="${BUNNY_STABLE_CANDIDATE_DIR:-$root/build/out/stable-rc}"
key="${BUNNY_STABLE_SIGNING_KEY:-}"

[[ -n "$key" ]] || { echo "BUNNY_STABLE_SIGNING_KEY must name an external protected private key" >&2; exit 1; }
exec python3 "$root/build/scripts/sign-stable-rc.py" --candidate "$candidate" --private-key "$key"
