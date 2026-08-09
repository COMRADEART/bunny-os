#!/usr/bin/bash
# Sync the Fedora reference checkout to the Windows working tree's HEAD.
set -uo pipefail
cd /root/bunny-os || exit 1
git fetch winsrc feature/bunny-desktop-shell 2>&1 | tail -3
git reset --hard FETCH_HEAD 2>&1 | tail -2
git clean -fd shell build/scripts tests 2>&1 | tail -5
echo "--- head ---"
git log --oneline -1
git rev-parse HEAD
echo "--- clean? ---"
git status --short | head
