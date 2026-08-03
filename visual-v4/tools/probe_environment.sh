#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Measure what this host can and cannot support, so that every NOT_AVAILABLE in
# the V4 results is backed by an observation rather than an assumption.
#
# This probe answers one question per line and never guesses. It is the evidence
# behind the environment-blocked gates, and re-running it on a different host is
# how those gates stop being environment-blocked.

set -u

echo "# bunny-shell-v4 environment probe"
echo "probed-at: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "kernel: $(uname -r)"
echo "os: $(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME")"
echo

echo "## DRM / KMS"
if [ -d /dev/dri ]; then
  echo "dev-dri: present"
  ls -1 /dev/dri | sed 's/^/  node: /'
else
  echo "dev-dri: ABSENT"
  echo "  consequence: no KMS. No page-flip, no vblank, no connectors."
  echo "  blocks: gpu-rendering, linux-dmabuf, frame-pacing,"
  echo "          two-output-presentation, output-hotplug"
fi
echo

echo "## GPU renderer"
if command -v glxinfo >/dev/null 2>&1; then
  renderer=$(glxinfo -B 2>/dev/null | sed -n 's/^OpenGL renderer string: //p')
  echo "renderer: ${renderer:-unknown}"
  case "$renderer" in
    *llvmpipe*|*softpipe*|*swrast*)
      echo "  classification: SOFTWARE RASTERISER"
      echo "  consequence: a software rasteriser cannot qualify GPU rendering."
      echo "               Any frame timing measured here describes the CPU." ;;
    "") echo "  classification: unknown" ;;
    *)  echo "  classification: hardware-backed (verify against the actual device)" ;;
  esac
else
  echo "renderer: glxinfo unavailable"
fi
echo

echo "## Wayland"
echo "WAYLAND_DISPLAY: ${WAYLAND_DISPLAY:-unset}"
echo "XDG_RUNTIME_DIR: ${XDG_RUNTIME_DIR:-unset}"
for lib in wayland-server wayland-client gtk4; do
  if pkg-config --exists "$lib" 2>/dev/null; then
    echo "$lib: $(pkg-config --modversion "$lib")"
  else
    echo "$lib: MISSING"
  fi
done
echo

echo "## Components the shared contract needs"
for c in Xwayland pipewire wireplumber ibus fcitx5 orca speech-dispatcher \
         gnome-shell mutter weston cargo rustc; do
  p=$(command -v "$c" 2>/dev/null)
  printf '%-18s %s\n' "$c:" "${p:-MISSING}"
done
for lib in libpipewire-0.3 atspi-2 libmutter-16 libmutter-15 pam; do
  if pkg-config --exists "$lib" 2>/dev/null; then
    printf '%-18s %s\n' "$lib:" "$(pkg-config --modversion "$lib")"
  else
    printf '%-18s %s\n' "$lib:" "MISSING"
  fi
done
echo

echo "## Session services"
printf 'pid1: %s\n' "$(ps -p 1 -o comm= 2>/dev/null)"
printf 'dbus-session: %s\n' "${DBUS_SESSION_BUS_ADDRESS:+present}"
printf 'logind: %s\n' "$(command -v loginctl >/dev/null 2>&1 && loginctl --version 2>/dev/null | head -1 || echo MISSING)"
echo

echo "## Verdict"
if [ ! -d /dev/dri ]; then
  echo "This host CANNOT qualify a compositor for production."
  echo "Mandatory gates gpu-rendering and two-output-presentation are unmeasurable."
  echo "Per C7, no framework may be selected from measurements taken here."
else
  echo "This host has a DRM device; re-evaluate the environment-blocked gates."
fi
