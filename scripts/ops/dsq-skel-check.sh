#!/usr/bin/env bash
D=/ostree/deploy/default/deploy/f41de91266c8a0042674608becc9aab637ae43e7fb697e418414dc647f77a38b.0
Q=/var/tmp/bunny-installables-g/bunny-os-b9c317d35b85.qcow2
guestfish --ro -a "$Q" run : mount-ro /dev/sda4 / : \
  find "$D/etc/skel" : \
  glob-expand "$D/usr/lib/tmpfiles.d/*bunny*" : \
  glob-expand "$D/usr/share/doc/bunny-os/*" 2>&1 | head -30
