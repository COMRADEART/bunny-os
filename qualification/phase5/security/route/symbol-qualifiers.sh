#!/usr/bin/bash
# What symbol does each advisory name, and is it in the binary?
#
# The database record for GHSA-5cgq-3rg8-m6cv carries
# qualifiers.go_imports = [{path: golang.org/x/crypto/ssh/knownhosts,
# symbols: [hostKeyDB.IsRevoked]}]. That is the data that lets grype exclude an
# advisory when the binary does not link the named symbol -- and it is why the
# same scanner, same route, gives 8 Criticals against a July database and 1
# against an August one.
#
# This lists the qualifier for each of the eight, then asks the binary
# directly. `go version -m` reads the module list; the Go symbol table is what
# grype reads, and `nm`/`strings` is the cheap approximation of it available
# here. Neither is offered as a reachability determination -- that is the
# independent reviewer's job -- but a named symbol that is absent from the
# binary is a far more specific thing to review than "installed-not-executed".
set -uo pipefail
OUT=/home/bunny/p5-evidence/security-symbols
DELTA=/home/bunny/p5-evidence/security-delta
IMAGE="${1:-localhost/bunny-os-beta:e906a48793d7}"
mkdir -p "${OUT}"

echo "== the qualifier each advisory carries =="
python3 /home/bunny/p5-ops/qualifier-report.py "${DELTA}" | tee "${OUT}/qualifiers.txt"

container=$(podman create "${IMAGE}" /bin/true) || exit 4
cleanup() {
  podman umount "${container}" >/dev/null 2>&1
  podman rm -f "${container}" >/dev/null 2>&1
}
trap cleanup EXIT
mountpoint=$(podman mount "${container}") || exit 5

for binary in skopeo podman; do
  target="${mountpoint}/usr/bin/${binary}"
  [[ -f "${target}" ]] || continue
  echo
  echo "== /usr/bin/${binary} =="
  echo "  size $(stat -c %s "${target}") bytes"
  echo "  does it carry the knownhosts package at all?"
  if strings -a "${target}" | grep -qF 'golang.org/x/crypto/ssh/knownhosts'; then
    echo "    YES -- the package path appears in the binary"
    strings -a "${target}" | grep -F 'knownhosts' | sort -u | head -8 | sed 's/^/      /'
  else
    echo "    NO -- 'golang.org/x/crypto/ssh/knownhosts' does not appear"
  fi
  echo "  named symbol hostKeyDB.IsRevoked:"
  if strings -a "${target}" | grep -qF 'hostKeyDB'; then
    echo "    present"
  else
    echo "    absent"
  fi
  echo "  x/crypto packages the binary does carry (first 12):"
  strings -a "${target}" | grep -oE 'golang\.org/x/crypto/[a-z0-9/]+' | sort -u | head -12 \
    | sed 's/^/      /'
done | tee "${OUT}/binary-probe.txt"

echo "SYMBOL-QUALIFIERS-DONE"
