#!/usr/bin/bash
# What does the update agent actually do on the shipped image?
#
# The tracker records the update gate as blocked because
# `BUNNY_UPDATE_MANIFEST must name a signed update manifest`, and then because
# the project had only one build. Both were true. Neither is the reason the
# update path cannot be qualified end to end on this artifact.
#
# The image ships:
#   /etc/bunny-os/update.json           enabled: false, manifestUrl invalid
#   /usr/share/bunny-os/update-keys/    revoked-keys.json and nothing else
#
# So there is no trusted signing key in the image at all. Every manifest, however
# well formed and whoever signed it, must be refused with `unknown_key`; and
# `_configuration()` refuses before that with `not_configured`.
#
# That is the right posture for an image with no production signing key -- but
# it is a *refusal*, and a refusal has to be measured rather than assumed. This
# runs the shipped agent inside a container made from the image, so the code
# under test is the code on the device, at the paths it expects.
set -uo pipefail
OUT=/home/bunny/p5-evidence/update
IMAGE="${1:-localhost/bunny-os-beta:e501218f2fe0}"
mkdir -p "${OUT}"

echo "image: ${IMAGE}"
podman image inspect "${IMAGE}" --format '{{.Id}}' | sed 's/^/image id: /'

echo
echo "== where the agent is installed =="
podman run --rm --entrypoint /usr/bin/bash "${IMAGE}" -c \
  'find / -xdev -name "bunny_update_agent.py" -o -xdev -name "bunny-update-agent*" 2>/dev/null | head -10'

echo
echo "== the trust store, as shipped =="
podman run --rm --entrypoint /usr/bin/bash "${IMAGE}" -c \
  'ls -la /usr/share/bunny-os/update-keys/; echo "---"; cat /usr/share/bunny-os/update-keys/revoked-keys.json'

echo
echo "== the configuration, as shipped =="
podman run --rm --entrypoint /usr/bin/bash "${IMAGE}" -c 'cat /etc/bunny-os/update.json'

echo
echo "== agent: status =="
podman run --rm --entrypoint /usr/bin/bash "${IMAGE}" -c \
  'python3 /usr/lib/bunny-os/update-agent/bunny_update_agent.py status 2>&1 || python3 -c "
import sys, glob
for candidate in glob.glob(\"/usr/**/bunny_update_agent.py\", recursive=True):
    print(\"found\", candidate)
"'

echo
echo "== agent: check (the path a device takes) =="
podman run --rm --entrypoint /usr/bin/bash "${IMAGE}" -c \
  'python3 /usr/lib/bunny-os/update-agent/bunny_update_agent.py check; echo "exit=$?"' \
  2>&1 | tee "${OUT}/agent-check.txt"

echo "UPDATE-PROBE-DONE"
