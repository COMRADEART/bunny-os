#!/usr/bin/bash
# A viewable capture of the small layout.
#
# 1366x768 is the resolution the brief names and the resolution the functional
# run used; its framebuffer capture is diagonally sheared, because virtio-vga's
# scanout stride does not divide a width that is not a multiple of eight. The
# tear is in the picture and not in the session — the accessibility tree from
# that same run reports every control correctly placed and none off-screen.
#
# This run is 1360x768, eight pixels narrower, purely so there is a photograph
# of the small layout that a person can look at. It exercises the same
# breakpoint: `compact` begins at 1200.
set -uo pipefail
export BUNNY_DESKTOP_INTERACT=0
export BUNNY_DESKTOP_SHOTS="160 230"
exec bash /mnt/c/Users/allam/Documents/new/bunny-os/.ops-alpha-desktop.sh a3 1360 768
