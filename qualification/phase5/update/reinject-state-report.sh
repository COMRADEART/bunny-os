#!/usr/bin/bash
# Replace the state report in *both* deployments, and make it say which
# deployment it is running on.
#
# The first version printed
#   bootc status | grep -iE 'booted|image' | head -3
# and all three boots -- the staged one, the rollback default and the rollback
# previous -- answered `image: /run/p5update/candidate:e501218f2fe0`. Read
# literally that says the rollback booted the new image, which would make the
# whole rollback result meaningless. Read carefully it says something else:
# `bootc status` prints a *staged*, a *booted* and a *rollback* section, and a
# grep across all of them cannot attribute the line to any one.
#
# So the report now takes three independent readings, and they have to agree:
#
#   * BUNNY_OS_COMMIT from /usr/lib/os-release -- per-deployment, sealed inside
#     the composefs image, and different in N and N+1;
#   * the ostree deployment checksum the kernel was told to boot, from
#     /proc/cmdline;
#   * bootc status as JSON, read at .status.booted.image.image.image.
#
# An instrument that cannot name what it measured has not measured it.
set -uo pipefail
STAGED=/home/bunny/p5-work/stage/staged.qcow2
ROOT_PARTITION=/dev/sda4
WORK=/home/bunny/p5-work/stage

cat >"${WORK}/state-report.sh" <<'REPORT'
#!/usr/bin/bash
set -uo pipefail
mark() { echo "BUNNY-P5-STATE: $*"; }
mark "boot $(date -Is)"

commit=$(grep '^BUNNY_OS_COMMIT=' /usr/lib/os-release 2>/dev/null | cut -d= -f2)
build=$(grep '^BUNNY_OS_BUILD_ID=' /usr/lib/os-release 2>/dev/null | cut -d= -f2)
mark "os-release commit=${commit:-unknown} build=${build:-unknown}"

cmdline_deployment=$(tr ' ' '\n' </proc/cmdline | grep -E '^ostree=' | head -1)
mark "cmdline ${cmdline_deployment:-<no ostree= argument>}"

booted=$(bootc status --format=json 2>/dev/null \
  | python3 -c 'import json,sys
try:
    d = json.load(sys.stdin)
except Exception as e:
    print(f"unreadable: {e}"); raise SystemExit(0)
s = d.get("status", {})
for name in ("booted", "staged", "rollback"):
    entry = s.get(name) or {}
    image = ((entry.get("image") or {}).get("image") or {}).get("image")
    print(f"{name}={image}", end="  ")
print()' 2>/dev/null)
mark "bootc ${booted:-<no json>}"

for file in \
  /var/home/p5-user-data.txt \
  /var/lib/bunny-os/companion/p5-mode.json \
  /var/lib/bunny-os/trust/p5-grants.json \
  /var/lib/bunny-os/voice/p5-settings.json \
  /var/lib/bunny-os/p5-settings.txt
do
  if [[ -f "${file}" ]]; then
    mark "PRESENT ${file} :: $(head -c 110 "${file}" | tr -d '\n')"
  else
    mark "MISSING ${file}"
  fi
done
mark "end"
REPORT

mapfile -t deployments < <(guestfish --ro -a "${STAGED}" run : mount "${ROOT_PARTITION}" / \
  : glob-expand "/ostree/deploy/*/deploy/*.0/" 2>/dev/null)
echo "deployments found: ${#deployments[@]}"

commands=(run : mount "${ROOT_PARTITION}" /)
labels=(run : mount "${ROOT_PARTITION}" /)
for entry in "${deployments[@]}"; do
  entry="${entry%/}"
  echo "  ${entry}"
  commands+=(: mkdir-p "${entry}/etc/bunny-p5-stage")
  commands+=(: upload "${WORK}/state-report.sh" "${entry}/etc/bunny-p5-stage/state-report.sh")
  commands+=(: chmod 0644 "${entry}/etc/bunny-p5-stage/state-report.sh")
  commands+=(: upload "${WORK}/bunny-p5-state.service" "${entry}/etc/systemd/system/bunny-p5-state.service")
  commands+=(: chmod 0644 "${entry}/etc/systemd/system/bunny-p5-state.service")
  commands+=(: mkdir-p "${entry}/etc/systemd/system/multi-user.target.wants")
  commands+=(: ln-sf /etc/systemd/system/bunny-p5-state.service
             "${entry}/etc/systemd/system/multi-user.target.wants/bunny-p5-state.service")
  labels+=(: lsetxattr security.selinux "system_u:object_r:etc_t:s0" 0
           "${entry}/etc/bunny-p5-stage/state-report.sh")
  labels+=(: lsetxattr security.selinux "system_u:object_r:systemd_unit_file_t:s0" 0
           "${entry}/etc/systemd/system/bunny-p5-state.service")
done

guestfish -a "${STAGED}" "${commands[@]}"
guestfish -a "${STAGED}" "${labels[@]}"
echo "REINJECT-DONE"
