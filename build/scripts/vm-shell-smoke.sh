#!/usr/bin/bash
set -euo pipefail

"${BASH:-/usr/bin/bash}" build/scripts/vm-smoke.sh shell-test
log="build/out/shell-test/vm-smoke-serial.log"
grep -Eiq 'Started GNOME Display Manager|Reached target Graphical Interface' "${log}" || {
  echo "graphical login marker not observed; see ${log}" >&2
  exit 4
}
echo "Shell image reached the graphical login boundary. Bunny session selection and interaction still require the documented manual VM matrix."
