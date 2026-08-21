#!/usr/bin/bash
# Does the Phase 5 idiom report NO for a string that is definitely present?
#
# Phase 5's symbol-qualifiers.sh runs under `set -uo pipefail` and asks:
#     if strings -a "$target" | grep -qF 'needle'; then YES else NO fi
#
# grep -q exits on the first match. That closes the pipe, strings dies of
# SIGPIPE (141), and pipefail promotes 141 to the pipeline's status -- so the
# `if` takes the else branch on a MATCH. Under pipefail this test can only ever
# say NO.
set -uo pipefail

TARGET=/root/probe-target.bin
podman cp "$(podman create --name p6probe localhost/bunny-os-beta:e906a48793d7 /bin/true)":/usr/bin/podman "$TARGET" >/dev/null 2>&1
podman rm -f p6probe >/dev/null 2>&1

echo "target: $TARGET ($(stat -c %s "$TARGET") bytes)"
echo

echo "== the Phase 5 idiom, verbatim (pipefail ON) =="
if strings -a "$TARGET" | grep -qF 'golang.org/x/crypto/ssh/knownhosts'; then
  echo "  knownhosts -> YES"
else
  echo "  knownhosts -> NO"
fi

echo
echo "== the same idiom with pipefail OFF =="
set +o pipefail
if strings -a "$TARGET" | grep -qF 'golang.org/x/crypto/ssh/knownhosts'; then
  echo "  knownhosts -> YES"
else
  echo "  knownhosts -> NO"
fi
set -o pipefail

echo
echo "== the pipeline's exit status on a match, under pipefail =="
set -o pipefail
strings -a "$TARGET" | grep -qF 'golang.org/x/crypto/ssh/knownhosts'
echo "  status=$?  (0 would be a match; 141 is SIGPIPE reaching pipefail)"

echo
echo "== control: a string that is genuinely absent =="
strings -a "$TARGET" | grep -qF 'this-string-is-definitely-not-in-the-binary'
echo "  status=$?  (1 is a real no-match)"

echo
echo "== counted without a pipeline at all =="
echo "  occurrences: $(grep -c -a -F 'golang.org/x/crypto/ssh/knownhosts' "$TARGET")"

rm -f "$TARGET"
