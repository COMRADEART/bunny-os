# Phase 2 VM matrix

Boot the `shell-test` QCOW2 with q35/UEFI, 4 vCPU, 8 GiB RAM, 64 GiB virtio storage, virtio GPU/network, and serial capture. Validate GDM offers Bunny, GNOME, and Bunny Safe Shell; perform launcher, panel, terminal, settings, notification, approval, workspace, update/recovery, logout/reboot, monitor hotplug/scaling, Bunny-unavailable, broker-unavailable, and search-unavailable scenarios. Record exact versions and logs. A serial boot marker is not evidence for interactive desktop behavior.
