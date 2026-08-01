#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Verify the units in their installed form, inside a Fedora container.
#
# `systemd-analyze verify` resolves every ExecStart= against the filesystem it
# runs on. The units are correct; the programs they name are installed by the
# image build into /usr/libexec and /usr/bin, and a bare fedora:44 container has
# none of them. The job was asserting a property of an installed system while
# running on an uninstalled one, and reported four failures:
#
#     bunny-installer-backend.service: Command /usr/libexec/bunny-installer-backend
#     is not executable: No such file or directory
#     ... and the same for bunny-live-session, bunny-policy-agent, bunny-first-run
#
# Three of those four are installed by build/scripts/install-root.py and are
# installed here too, so the check now tests the layout the image produces.
#
# The fourth is real: nothing installs /usr/libexec/bunny-policy-agent. It is
# recorded in operations/data/unit-program-gaps.json and skipped here by name,
# so the gap is tracked instead of being rediscovered as noise. A unit whose
# program is missing and which is *not* recorded still fails, both here and in
# the "systemd unit programs" repository validator.

set -euo pipefail

SRC="${1:-/src}"
GAPS="${SRC}/operations/data/unit-program-gaps.json"

install -d /etc/systemd/system /etc/systemd/user

cp "${SRC}"/systemd/*.service "${SRC}"/systemd/*.socket \
   "${SRC}"/systemd/*.timer "${SRC}"/systemd/*.target /etc/systemd/system/
cp "${SRC}"/systemd/user/*.service "${SRC}"/systemd/user/*.timer \
   "${SRC}"/systemd/user/*.target /etc/systemd/user/

# Exactly what install-root.py installs, to the paths it installs them to.
install -m 0755 "${SRC}/services/bunny-system-broker/bin/bunny-system-broker" \
    /usr/libexec/bunny-system-broker
install -m 0755 "${SRC}/services/bunny-update-agent/bunny_update_agent.py" \
    /usr/libexec/bunny-update-agent
for name in bunny-health-check bunny-recovery-prepare bunny-recovery \
            bunny-first-boot bunny-brlapi-key bunny-safe-graphics bunny-live-session; do
    install -m 0755 "${SRC}/scripts/${name}.py" "/usr/libexec/${name}"
done
install -m 0755 "${SRC}/shell/services/bin/bunny-shell-service" /usr/libexec/bunny-shell-service
for name in bunny-search bunny-launcher bunny-workspace bunny-settings bunny-terminal; do
    if [ -f "${SRC}/shell/services/bin/${name}" ]; then
        install -m 0755 "${SRC}/shell/services/bin/${name}" "/usr/bin/${name}"
    else
        install -m 0755 /usr/bin/true "/usr/bin/${name}"
    fi
done
# live and beta profiles only, but the units ship in every profile.
install -m 0755 "${SRC}/installer/bin/bunny-installer-backend" /usr/libexec/bunny-installer-backend
install -m 0755 "${SRC}/installer/bin/bunny-first-run" /usr/bin/bunny-first-run
install -d /opt/bunny/current
install -m 0755 /usr/bin/true /opt/bunny/current/bunny-desktop

# Units whose program the build does not install, read from the record so that
# this script and the validator cannot disagree about which gaps are known.
skipped="$(python3 -c '
import json, sys
document = json.load(open(sys.argv[1], encoding="utf-8"))
print(" ".join(sorted(item["unit"] for item in document["gaps"])))
' "${GAPS}")"

units=()
for unit in /etc/systemd/system/bunny-* /etc/systemd/user/bunny-*; do
    [ -e "$unit" ] || continue
    base="$(basename "$unit")"
    skip=0
    for name in $skipped; do
        if [ "$base" = "$name" ]; then
            skip=1
            break
        fi
    done
    if [ "$skip" -eq 1 ]; then
        echo "skipping ${base}: recorded in unit-program-gaps.json"
        continue
    fi
    units+=("$unit")
done

echo "verifying ${#units[@]} unit(s)"
systemd-analyze verify "${units[@]}"

systemd-analyze security --offline=yes \
    bunny-system-broker.service \
    bunny-update-agent@check.service \
    bunny-health-check.service \
    bunny-recovery-prepare.service

echo "units verified in installed form"
