#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Regenerate the installation medium's initramfs, explicitly, and prove it.
#
# ## Why this step exists at all
#
# The ISO's /images/pxeboot/initrd.img is not built by image-builder. osbuild
# copies it, byte for byte, out of the container image:
#
#   copying '/run/osbuild/inputs/tree/lib/modules/7.1.5-200.fc44.x86_64/initramfs.img'
#        -> '/run/osbuild/tree/images/pxeboot/initrd.img'
#
# So the initramfs that boots the medium is whatever sits at
# /usr/lib/modules/<kver>/initramfs.img when the image is committed. Nothing in
# the Bunny build ever wrote that file: it arrived prebuilt in fedora-bootc:44,
# generated with `--add ostree` and nothing else, and no package installed by
# this build triggers a regeneration. Adding
# installer/config/bunny-live-dracut.conf changed no bytes of it — a
# dracut.conf.d file is a set of instructions for the next dracut run, and there
# was no next run.
#
# That is the whole reason the medium never booted. See LIVE_BOOT_ROOT_CAUSE.md.
#
# ## Fail closed
#
# Every failure here stops the build. There is no `|| true`, no fallback to the
# initramfs that was already there, and no path on which an ISO is assembled
# from an unqualified artifact. That matters more than usual because dracut's
# exit code cannot be trusted on its own — measured, in this container, with the
# stock configuration and no Bunny changes at all:
#
#   dracut-install: ERROR: installing '/root'
#   dracut[E]: FAILED: /usr/lib/dracut/dracut-install -D … -f /root
#   exit=0
#
# It does return 1 for a module it cannot find, so the exit code is checked. It
# is simply not sufficient, which is why check-live-initramfs.py opens the
# artifact afterwards and that is the real gate.
#
# Usage:
#   regenerate-live-initramfs.sh --profile <profile> --source-date-epoch <n>
#                                [--source-commit <sha>] [--report <path>]
set -euo pipefail

profile=""
epoch=""
source_commit="unknown"
report="/usr/share/bunny-os/live-initramfs.json"
scripts_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile) profile="${2:?}"; shift 2 ;;
    --source-date-epoch) epoch="${2:?}"; shift 2 ;;
    --source-commit) source_commit="${2:?}"; shift 2 ;;
    --report) report="${2:?}"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

# The payload image is deliberately untouched. Its initramfs boots an ostree
# deployment off a disk, which is what the base already builds it for; giving it
# dmsquash-live would add a live-boot path nothing on an installed system uses.
if [[ "${profile}" != "live" ]]; then
  echo "==> initramfs regeneration: profile is '${profile}', not 'live'; nothing to do"
  echo "    (only the installation medium needs live-root support)"
  exit 0
fi

[[ "${epoch}" =~ ^[0-9]+$ ]] || {
  echo "BLOCKED: --source-date-epoch must be an integer Unix timestamp" >&2; exit 2; }

conf_path="/usr/lib/dracut/dracut.conf.d/95-bunny-live.conf"
modules_dir="/usr/lib/dracut/modules.d"

echo "==> 1. the dracut configuration must already be installed"
# Ordering is the point. install-root.py places this file; if this step ever
# runs before that one, the initramfs is regenerated from the base's
# configuration and comes out exactly as broken as the one being replaced —
# while every log line says the initramfs was rebuilt.
if [[ ! -f "${conf_path}" ]]; then
  echo "BLOCKED: ${conf_path} is not installed." >&2
  echo "It is placed by build/scripts/install-root.py from" >&2
  echo "installer/config/bunny-live-dracut.conf on the live profile. Regenerating" >&2
  echo "without it would rebuild the same initramfs that never booted." >&2
  exit 2
fi
requested="$(sed -n 's/^[[:space:]]*add_dracutmodules+=[[:space:]]*"\(.*\)".*/\1/p' \
             "${conf_path}" | tr -s ' \t' ' ' | sed 's/^ //; s/ $//')"
if [[ -z "${requested}" ]]; then
  echo "BLOCKED: ${conf_path} requests no modules via add_dracutmodules+=" >&2
  echo "A configuration file that asks for nothing is not a configuration." >&2
  exit 2
fi
echo "    ${conf_path}"
echo "    requests: ${requested}"

echo "==> 2. resolving the kernel the ISO will boot"
# Deterministic, and never a glob that "usually" matches one thing. osbuild
# copies lib/modules/<kver>/vmlinuz and lib/modules/<kver>/initramfs.img as a
# pair; if this build root held two kernels there would be no way to know from
# here which pair image-builder would take, and a GRUB entry pointing at one
# kernel with the other's initramfs is unbootable in a way nothing downstream
# would notice.
mapfile -t kernels < <(find /usr/lib/modules -mindepth 2 -maxdepth 2 -name vmlinuz \
                        -printf '%h\n' | sed 's|.*/||' | sort)
if [[ ${#kernels[@]} -eq 0 ]]; then
  echo "BLOCKED: no /usr/lib/modules/*/vmlinuz in this build root." >&2
  echo "The live profile must install a kernel; without one the medium has" >&2
  echo "nothing to boot and image-builder would fail later and less clearly." >&2
  exit 2
fi
if [[ ${#kernels[@]} -gt 1 ]]; then
  echo "BLOCKED: ${#kernels[@]} kernels are installed and the mapping is ambiguous:" >&2
  printf '  %s\n' "${kernels[@]}" >&2
  echo "osbuild copies one kernel/initramfs pair into the ISO and this build" >&2
  echo "cannot tell which. Pin the kernel rather than letting the ISO choose." >&2
  exit 2
fi
kver="${kernels[0]}"
initramfs="/usr/lib/modules/${kver}/initramfs.img"
echo "    kernel release: ${kver}"
echo "    target artifact: ${initramfs}"

echo "==> 3. the requested modules must exist before dracut is asked for them"
# dracut does refuse an unknown module, but the failure names a module rather
# than the package that should have provided it, and it happens after several
# minutes of work. Checking here means a missing dracut-live is reported as a
# missing dracut-live.
missing=()
for module in ${requested}; do
  found="$(find "${modules_dir}" -mindepth 1 -maxdepth 1 -type d \
            -regextype posix-extended -regex ".*/[0-9]{2}${module}" -print -quit)"
  if [[ -z "${found}" ]]; then
    missing+=("${module}")
    continue
  fi
  owner="$(rpm -qf --queryformat '%{NAME}-%{VERSION}-%{RELEASE}' \
            "${found}" 2>/dev/null || echo 'not owned by a package')"
  printf '    %-16s %s  (%s)\n' "${module}" "${found}" "${owner}"
done
if [[ ${#missing[@]} -gt 0 ]]; then
  echo "BLOCKED: ${#missing[@]} dracut module(s) requested by ${conf_path}" >&2
  echo "are not installed in this build root:" >&2
  printf '  %s\n' "${missing[@]}" >&2
  echo "" >&2
  echo "dracut would silently omit a capability the kernel command line depends" >&2
  echo "on, and the ISO would build and not boot. Providers on Fedora:" >&2
  echo "  dmsquash-live, livenet -> dracut-live; livenet also needs dracut-network" >&2
  echo "  ostree                 -> ostree" >&2
  exit 2
fi

echo "==> 4. regenerating"
work="/var/tmp/bunny-initramfs"
rm -rf "${work}"
mkdir -p "${work}"
trap 'rm -rf "${work}"' EXIT

if [[ ! -s "${initramfs}" ]]; then
  echo "BLOCKED: ${initramfs} is missing or empty before regeneration." >&2
  echo "The base image is expected to ship one; its absence means this build" >&2
  echo "root is not shaped the way the rest of this script assumes." >&2
  exit 2
fi
cp -a "${initramfs}" "${work}/original.img"

# --reproducible and SOURCE_DATE_EPOCH so two builds of one commit produce the
# same bytes; the base's own initramfs was built with --reproducible and this
# keeps that property rather than trading it for the missing modules.
# --no-hostonly on the command line as well as in the configuration: dmsquash-live's
# check() is `[[ ${hostonly-} ]] && return 1`, so a host-only build does not
# produce a smaller initramfs, it produces one without the module that matters.
dracut_command=(dracut --force --no-hostonly --reproducible
                --kver "${kver}" "${work}/new.img")
echo "    ${dracut_command[*]}"
# `set -o pipefail` at the top is what makes this correct: the pipeline's status
# is dracut's, not tee's, so `$?` is the number that matters.
#
# An earlier version of this line followed it with
# `status="${PIPESTATUS[0]:-${status}}"`, which looks more careful and is the
# opposite. `status=$?` is itself a command, and running it resets PIPESTATUS to
# the assignment's own (0) — so on the one path that matters, a dracut that had
# just failed, the next line read 0 and the build continued to assemble an ISO
# around an unqualified initramfs. In a script whose entire purpose is to fail
# closed.
status=0
SOURCE_DATE_EPOCH="${epoch}" "${dracut_command[@]}" 2>&1 | tee "${work}/dracut.log" || status=$?
if [[ "${status}" -ne 0 ]]; then
  echo "BLOCKED: dracut exited ${status}. Full output above and in ${work}/dracut.log." >&2
  exit 2
fi
if [[ ! -s "${work}/new.img" ]]; then
  echo "BLOCKED: dracut exited 0 but wrote no initramfs to ${work}/new.img." >&2
  exit 2
fi

echo "==> 5. preserving segments the base appended after dracut"
# An initramfs is a chain of concatenated cpio archives. The one fedora-bootc
# ships is three: microcode (plain), the dracut image (zstd), and a 171-byte
# gzip archive holding dev/random and dev/urandom as character devices. dracut
# writes the first two and knows nothing about the third, so regenerating drops
# it. Two device nodes that a systemd initrd shadows the moment it mounts
# devtmpfs — but "probably harmless" is not a reason to change something this
# step did not set out to change. The point of the exercise is to add the
# missing modules and alter nothing else.
python3 "${scripts_dir}/preserve-initramfs-tail.py" \
  --original "${work}/original.img" --regenerated "${work}/new.img" \
  --report "${work}/tail.json"

install -D -m 0644 "${work}/new.img" "${initramfs}"
touch --no-dereference --date="@${epoch}" "${initramfs}"

echo "==> 6. qualifying the artifact that will enter the ISO"
python3 "${scripts_dir}/check-live-initramfs.py" \
  --initramfs "${initramfs}" \
  --expect-kver "${kver}" \
  --json "${work}/qualification.json"

echo "==> 7. recording provenance"
python3 - "${report}" "${work}" "${kver}" "${initramfs}" "${epoch}" \
         "${source_commit}" "${requested}" <<'PYTHON'
import json, subprocess, sys, hashlib
from pathlib import Path

report, work, kver, initramfs, epoch, commit, requested = sys.argv[1:8]
work = Path(work)


def rpm(*arguments):
    try:
        return subprocess.run(["rpm", *arguments], capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return None


dracut_log = (work / "dracut.log").read_text(encoding="utf-8", errors="replace")
qualification = json.loads((work / "qualification.json").read_text(encoding="utf-8"))
tail = json.loads((work / "tail.json").read_text(encoding="utf-8"))

payload = {
    "schemaVersion": 1,
    "sourceCommit": commit,
    "sourceDateEpoch": int(epoch),
    "kernelRelease": kver,
    "artifact": initramfs,
    "sha256": hashlib.sha256(Path(initramfs).read_bytes()).hexdigest(),
    "sizeBytes": Path(initramfs).stat().st_size,
    "requestedModules": requested.split(),
    "dracutVersion": subprocess.run(["dracut", "--version"], capture_output=True,
                                    text=True, check=False).stdout.strip(),
    "packages": {
        name: rpm("-q", "--queryformat", "%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}", name)
        for name in ("kernel", "kernel-core", "kernel-modules", "dracut",
                     "dracut-live", "dracut-network", "ostree", "squashfs-tools")
    },
    # dracut prints these with the stock configuration too, in this container,
    # with no Bunny change involved: it detects a WSL container and tries to
    # install /root, which is a directory. Recorded rather than treated as
    # fatal, because failing on them would block every build for a fault that
    # predates this step and does not affect the artifact — and recorded rather
    # than dropped, because the next person to read a dracut log should not have
    # to rediscover that these lines are expected.
    "dracutErrorLines": sorted({
        line.strip() for line in dracut_log.splitlines()
        if "dracut[E]" in line or "dracut-install: ERROR" in line
    }),
    "preservedTail": tail,
    "qualification": {
        "status": qualification["status"],
        "failures": qualification["failures"],
        "dracutModuleCount": len(qualification["dracutModules"]),
        "segments": qualification["segments"],
    },
}
out = Path(report)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
print(f"    wrote {out}")
print(f"    sha256 {payload['sha256']}")
PYTHON

touch --no-dereference --date="@${epoch}" "${report}"
echo "==> initramfs regeneration complete for ${kver}"
