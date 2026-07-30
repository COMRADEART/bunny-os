# GO-2026-5970 — golang.org/x/text v0.21.0

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

- The carrier binary. The scan records an ostree object: `/sysroot/ostree/repo/objects/75/5cc7cfe2e3b547556eb117093d626800f1dcb3751e3b31952cec86177bdcab.file`.
- The vulnerable function or subsystem: `unknown`.
- The ELF build ID: `unknown`.
- The stripped state: `unknown`.
- Whether debuginfo maps the vulnerable function into the shipped build.

## Notes

The scan records the carrier as an ostree object, not an installed path: the fedora-bootc base ships an object store and every finding's location is an object in a lower layer. Carrier object: /sysroot/ostree/repo/objects/75/5cc7cfe2e3b547556eb117093d626800f1dcb3751e3b31952cec86177bdcab.file. Mapping that object to one of the three installed Go binaries requires the image: `ostree ls` or `find /usr -samefile` inside a booted or mounted deployment. Until that is done the carrier is one of: podman-5.8.4-1.fc44.x86_64 at /usr/sbin/podman; skopeo-1.22.2-2.fc44.x86_64 at /usr/sbin/skopeo; bootc-1.16.4-1.fc44.x86_64 at /usr/sbin/bootc. This advisory's carrier object is the one the previous phase identified as toolbox, which package minimisation removed: `rpm -q toolbox` reports not installed and /usr/bin/toolbox is absent from the minimised image. The object survives in a base layer because dnf remove cannot remove an object from a lower layer's store. If the carrier attribution is confirmed, this finding's invocation analysis differs from the other 23 — there is no installed executable to invoke. It remains Unknown because the attribution is not confirmed and question 7 is unanswered either way.

## Fixed version

`0.39.0`. Fedora 44 ships no build carrying it: `dnf check-update`
returns nothing for the carrier packages, and a base rebuild on 2026-07-29 did not
move the position.
