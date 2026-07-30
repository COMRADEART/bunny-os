"""Linux peer-credential and Polkit authorization."""

from __future__ import annotations

from dataclasses import dataclass
import os
import socket
import struct
import subprocess


class AuthenticationError(PermissionError):
    pass


@dataclass(frozen=True)
class PeerIdentity:
    pid: int
    uid: int
    gid: int
    start_time: int


def _proc_start_time(pid: int) -> int:
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="ascii") as handle:
            fields = handle.read().split()
        return int(fields[21])
    except (OSError, ValueError, IndexError) as exc:
        raise AuthenticationError("peer process identity is no longer available") from exc


def peer_identity(connection: socket.socket) -> PeerIdentity:
    if not hasattr(socket, "SO_PEERCRED"):
        raise AuthenticationError("SO_PEERCRED is unavailable; broker requires Linux")
    raw = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    pid, uid, gid = struct.unpack("3i", raw)
    if pid <= 0 or uid < 0 or gid < 0:
        raise AuthenticationError("invalid peer credentials")
    try:
        with open(f"/proc/{pid}/status", "r", encoding="ascii") as handle:
            status = handle.read()
    except OSError as exc:
        raise AuthenticationError("peer process disappeared") from exc
    real_uid_line = next((line for line in status.splitlines() if line.startswith("Uid:")), None)
    if real_uid_line is None or int(real_uid_line.split()[1]) != uid:
        raise AuthenticationError("peer credential mismatch")
    return PeerIdentity(pid=pid, uid=uid, gid=gid, start_time=_proc_start_time(pid))


_ENV = {"PATH": "/usr/sbin:/usr/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}


def session_is_active(peer: PeerIdentity) -> bool:
    if peer.uid == 0:
        return True
    result = subprocess.run(
        ["/usr/bin/loginctl", "show-user", str(peer.uid), "--property=State", "--value"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=5,
        check=False,
        env=_ENV,
    )
    return result.returncode == 0 and result.stdout.strip() in {"active", "online"}


def authorize_polkit(peer: PeerIdentity, action_id: str) -> bool:
    if peer.uid == 0:
        return True
    if peer.uid < 1000 or not session_is_active(peer):
        return False
    subject = f"{peer.pid},{peer.start_time},{peer.uid}"
    result = subprocess.run(
        [
            "/usr/bin/pkcheck",
            "--action-id",
            action_id,
            "--process",
            subject,
            "--allow-user-interaction",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
        check=False,
        env=_ENV,
    )
    return result.returncode == 0


def require_local_user(peer: PeerIdentity) -> None:
    if peer.uid != 0 and peer.uid < 1000:
        raise AuthenticationError("system service identities may not use the user broker API")


def proc_unit(pid: int) -> str:
    """Return the systemd unit owning ``pid``, from its cgroup path.

    Used instead of a logind session check, because a headless system daemon
    has no session. The cgroup path is kernel-maintained and cannot be forged
    by the peer process itself.
    """
    try:
        with open(f"/proc/{pid}/cgroup", "r", encoding="ascii") as handle:
            content = handle.read()
    except OSError as exc:
        raise AuthenticationError("peer process disappeared") from exc
    for line in content.splitlines():
        # cgroup v2 emits a single "0::<path>" line.
        _, _, path = line.partition("::")
        if not path:
            continue
        for segment in reversed(path.strip().split("/")):
            if segment.endswith((".service", ".scope")):
                return segment
    raise AuthenticationError("peer process is not owned by a systemd unit")


def require_policy_identity(peer: PeerIdentity, *, expected_uid: int, expected_unit: str) -> None:
    """Authorize a system daemon on the policy socket.

    Deliberately a sibling of ``require_local_user`` rather than a flag on it.
    A shared function with a mode argument is one bug away from opening the
    user socket to system identities, which is exactly what that function
    exists to prevent.

    Two independent facts must hold: the peer runs as the dedicated policy
    service account, and its process is owned by the expected systemd unit.
    Neither alone is sufficient — a uid can be shared by a compromised helper,
    and a unit name proves nothing without the matching account.
    """
    if peer.uid != expected_uid:
        raise AuthenticationError("caller is not the policy agent service identity")
    if peer.uid >= 1000:
        raise AuthenticationError("the policy socket does not accept interactive user identities")
    unit = proc_unit(peer.pid)
    if unit != expected_unit:
        raise AuthenticationError("caller is not running under the policy agent unit")
