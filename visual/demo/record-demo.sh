#!/usr/bin/bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
output_dir="${repo_root}/build/visual/demo"
mkdir -p "$output_dir"

if ! command -v wf-recorder >/dev/null 2>&1; then
  echo "wf-recorder is required to capture the nested visual preview" >&2
  exit 2
fi

echo "Start 'make visual-preview-nested' in a disposable graphical session."
echo "Follow visual/demo/storyboard.json, then press Ctrl+C to stop recording."
wf-recorder --file "$output_dir/bunny-desktop-v1.webm"
