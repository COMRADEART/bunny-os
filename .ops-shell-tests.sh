#!/usr/bin/bash
# The desktop shell suite on the reference host, where gjs exists so the
# character's own pixels can be measured.
set -uo pipefail
sudo -u bunny -H bash <<'INNER'
set -uo pipefail
cd /home/bunny/bunny-os || exit 9
echo "=== gjs ==="
command -v gjs && gjs --version
echo "=== tests/shell ==="
python3 -m unittest tests.shell.test_desktop_shell 2>&1 | tail -25
INNER
