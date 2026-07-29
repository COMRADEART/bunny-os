# Network security

firewalld is enabled with `bunny-default`, target `DROP`, no inbound service or port. Stateful replies, loopback, DHCP, and NetworkManager's required host networking are supplied by the Fedora firewall/network stack. SSH is disabled. A user must deliberately add a firewalld service/port with administrative authorization; that change is visible through conventional tools and outside Bunny's broker API.

Bunny Desktop supervises app-server on loopback with an ephemeral port and token file. Local model servers are loopback-only. The privileged broker is AF_UNIX-only and has `IPAddressDeny=any`. Plugins start without network unless Bunny capability policy and the selected sandbox explicitly permit a destination. No mDNS, remote desktop, LAN app-server, or diagnostics receiver is enabled by Bunny OS.

The update agent is the only Bunny OS service designed for outbound HTTPS. Its fixed configuration selects one channel manifest and allowlisted image repository; it honors system resolver/proxy configuration through standard libraries/bootc. Offline failure records a bounded error and does not affect boot or local Bunny use. Developer images use an `.invalid` endpoint and `enabled:false`.

Remote Bunny access is postponed. A future design must add authenticated TLS, explicit firewall policy, session/user binding, revocation, rate limits, and a separate ADR; changing app-server to `0.0.0.0` is not an acceptable shortcut.

