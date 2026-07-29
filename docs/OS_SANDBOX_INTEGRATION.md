# OS sandbox integration

Bunny's capability policy remains the application-level decision point; the OS supplies independent enforcement. No single container primitive is described as a complete hostile-code boundary.

| Control | Files | Network | Process/resource | Syscalls/devices | Phase 1 state |
|---|---:|---:|---:|---:|---|
| bubblewrap/user namespaces | yes | namespace | PID namespace | bind/device selection | installed; `bunny-os-info` runs a fixed self-test before saying runtime-verified |
| systemd user/transient units | path directives | IP policy | cgroup quotas/lifecycle | syscall/address-family/device policy | available integration target; plugin transient-unit wiring remains upstream work |
| seccomp/systemd filters | no | address families | no | yes | integration services use static filters |
| Landlock | yes | limited | no | no | detected only; Bunny runtime support must negotiate ABI and self-test |
| Flatpak portals | portal-mediated | permission | app lifecycle | device/desktop portals | selected for desktop file/screen/camera/microphone access |
| rootless Podman | mount namespace | namespace | cgroups | seccomp/devices | developer profile only; not treated as a perfect security boundary |
| SELinux | labels | labels/ports | domains | object classes | enforcing base; Bunny domain policy is compile-test prototype pending AVC qualification |

Plugin runners should receive distinct transient scopes, minimal bind mounts, no provider credentials, default-denied network, explicit CPU/memory/process limits, and a dedicated SELinux domain when qualified. Local model servers bind loopback, receive only selected model directories, and do not inherit Bunny provider tokens. Desktop remains a normal user process and cannot reach another user's session.

