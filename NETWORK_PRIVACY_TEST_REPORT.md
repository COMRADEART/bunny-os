# Network privacy test report

Date: 2026-07-29. Result: **one finding — the system contacts external NTP servers on a quiet boot.** No telemetry, no analytics, and no Bunny-related outbound traffic were observed.

## Method

`build/scripts/vm-network-capture.sh` boots the image under QEMU/KVM with nothing asked of it — no login, no user action, no update triggered — and records every packet with `filter-dump` at the netdev. The dump sits before user-mode NAT, so it captures the guest's own view of what it sent.

`build/scripts/analyse-capture.py` parses libpcap directly rather than shelling to tcpdump, which is not guaranteed on the builder and would put an unpinned tool in an evidence path. It decodes Ethernet, IPv4/IPv6 and transport ports only. **Payloads are never inspected**: the question is whether the device contacted anyone, not what it said.

Destinations inside QEMU's `10.0.2.0/24` user-mode range are the emulator's own gateway and DNS resolver. Multicast, link-local and the limited broadcast address are link-scoped. All are excluded from the external count.

## Result: developer profile, 180-second quiet boot

```text
frames decoded         127
protocols              udp 95, arp 16, icmpv6 5, other 11
ports observed         ntp 24, mdns 27, dns 8, dhcp 4, ephemeral 32
external destinations  4
```

| Destination | Port | Service | Packets |
|---|---|---|---|
| 198.137.202.32 | 123 | NTP | 6 |
| 207.58.172.126 | 123 | NTP | 6 |
| 167.248.62.201 | 123 | NTP | 6 |
| 157.245.125.229 | 123 | NTP | 6 |

## The finding

**Time synchronisation contacts four third-party NTP servers on every boot, before any user action.**

This is ordinary Linux behaviour — `chronyd` reaching the Fedora NTP pool — and it is not telemetry: no identifier is sent and the payload is a timestamp exchange. But it is real outbound traffic to third parties, and it discloses to those operators that a device is online and roughly where it is by source address.

`docs/PRIVACY_MODEL.md` states the defaults include "no telemetry, advertising ID, cloud account, remote diagnostics, background upload". NTP is none of those, so the statement is not false. It is, however, incomplete: a reader could reasonably conclude a freshly booted machine talks to nobody, and it talks to four hosts.

**Recommendation:** disclose NTP explicitly in the privacy model, and state whether the pool is configurable or can be disabled. This is a documentation gap rather than a defect, but "no unexplained network activity" is a stable blocker and unexplained is exactly what this currently is.

## What was not observed

No connection to any Bunny endpoint. No telemetry, analytics, crash upload, update check, or model download. No connection attributable to Bunny Shell, the broker, the sync client, or the policy agent. mDNS and DNS stayed link-local or went to the emulator's resolver.

This is consistent with the design: there is no upload endpoint, `telemetryEnabled` is pinned false, `diagnosticsPolicy` has one legal value, and developer images ship with updates disabled.

## Limitations, which are substantial

- **One profile, one boot, 180 seconds, idle.** An installed system doing real work over days is the case that matters and it has not been tested.
- **No per-feature captures.** `docs/PRIVACY_REGRESSION_TESTING.md` requires a separate capture for each explicit network feature — enabling a cloud provider, an update check, sync. None was run because none of those features can be exercised yet.
- **Virtual, not physical.** No real network interface, no real DHCP server, no captive portal, no IPv6 deployment.
- **The image was not installed.** This is a booted image, not an installation with user data and services running.

## Evidence

`build/out/vm-evidence/developer-quiet-boot.pcap` and `developer-network-privacy.json`. The analyser exits 4 when any external destination is found, so this run is recorded as a finding rather than a pass.
