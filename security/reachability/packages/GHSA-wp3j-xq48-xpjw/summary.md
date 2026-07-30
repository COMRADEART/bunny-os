# GHSA-wp3j-xq48-xpjw — github.com/containers/podman/v5 v5.0.0-20260626000000-d5ac989fc69c+dirty

Source commit: `80df25b09f6578276d18c8a82f15c47dd8959740`  
Current conclusion: **Unknown** (blocking)

## What is established

| Question | Answer | Basis |
|---|---|---|
| Is the vulnerable module in the image? | yes | scanner match against the built archive |
| Does it run by default? | no | no unit is enabled; no preset enables one |
| Can an unprivileged user invoke the carrier? | yes | mode 0755, no setuid |
| Can Bunny or a plugin invoke it? | no | typed fixed broker backends, no generic exec path |
| Does sandboxing limit exposure? | yes | SELinux targeted, enforcing |
| Can the package be removed? | no | bootc requires podman and skopeo; rpm-ostree requires skopeo |
| **Is the vulnerable code path compiled in and active?** | **unknown** | **not determined** |

## What is not established

- The carrier binary. The scan records an ostree object: `/sysroot/ostree/repo/objects/8c/c9b0248b19238b5f375ee6f7c986efc7ef8cdd360140254e41c478cd91b933.file`.
- The vulnerable function or subsystem: `unknown`.
- The ELF build ID: `unknown`.
- The stripped state: `unknown`.
- Whether debuginfo maps the vulnerable function into the shipped build.

## Notes

The scan records the carrier as an ostree object, not an installed path: the fedora-bootc base ships an object store and every finding's location is an object in a lower layer. Carrier object: /sysroot/ostree/repo/objects/8c/c9b0248b19238b5f375ee6f7c986efc7ef8cdd360140254e41c478cd91b933.file. Mapping that object to one of the three installed Go binaries requires the image: `ostree ls` or `find /usr -samefile` inside a booted or mounted deployment. Until that is done the carrier is one of: podman-5.8.4-1.fc44.x86_64 at /usr/sbin/podman; skopeo-1.22.2-2.fc44.x86_64 at /usr/sbin/skopeo; bootc-1.16.4-1.fc44.x86_64 at /usr/sbin/bootc.

## Fixed version

`5.6.1`. Fedora 44 ships no build carrying it: `dnf check-update`
returns nothing for the carrier packages, and a base rebuild on 2026-07-29 did not
move the position.
