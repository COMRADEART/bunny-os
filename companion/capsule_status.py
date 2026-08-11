# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What a person is told about an application's protected space, in two layers.

§16 asks for something harder than it looks: the user should be able to
understand that an application is isolated, without being handed Linux
terminology — and an advanced user should still be able to see the mechanism.
Two audiences, one truth, and the failure mode is telling the first audience
something the second can prove wrong.

So both layers are derived from the same :class:`~capsules.isolation.IsolationPlan`
and neither is written by hand. The plain layer is four short lines; the
technical layer is the plan's own fields. A capsule whose network is unshared
says "Network: off" *because* ``net`` is in the plan's unshare list, and the
technical panel shows that list. There is no path by which the friendly sentence
and the expandable detail can disagree, because the friendly sentence is computed
from the detail.

Three rules the summary follows.

**It never claims a restriction the plan does not carry.** If the backend cannot
enforce a granted category, or the host cannot apply a declared limit, or the
network class is one this build does not filter on, the plain layer says so in
plain words rather than omitting it. A status page that showed "Network:
api.example.com only" for a class nothing filters would be the most damaging
sentence in the product.

**It counts what the person can check.** "Access: this image only" is a count of
grant-origin binds, which is the same list Settings shows and the same list the
audit records. A person who opens the technical panel sees the paths.

**It says nothing about what the application is doing.** This is a description of
a boundary, not of behaviour. There is no field here for activity, because the
activity view is :mod:`trust.audit`'s and mixing them would make a quiet
application look safer than a busy one.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from capsules.isolation import IsolationPlan
from capsules.runtime import Capsule
from trust.categories import CATEGORIES

__all__ = [
    "NETWORK_PHRASES",
    "CapsuleStatus",
    "capsule_status",
]

#: How each network class reads to a person. The two this build does not filter
#: on get a phrase that does not imply a boundary — "the internet" rather than
#: "only example.com", because only the first is true.
NETWORK_PHRASES: Mapping[str, str] = {
    "none": "Off",
    "loopback": "This computer only",
    "local-network": "Your local network",
    "allowlisted": "On",
    "internet": "On",
}


@dataclass(frozen=True)
class CapsuleStatus:
    """The two layers, together, so a surface cannot render one without the other."""

    application_id: str
    display_name: str
    running: bool
    #: The four short lines. Ordered; a surface shows them in this order.
    plain: tuple[tuple[str, str], ...]
    #: The sentence under the heading, in the Companion's voice.
    headline: str
    #: Anything the person should know that the plain lines cannot carry: an
    #: unenforced permission, an unapplied limit, a network class nothing
    #: filters on. Empty is the common case and means there is nothing hidden.
    caveats: tuple[str, ...]
    #: The expandable panel. Field names are technical on purpose; this layer is
    #: for somebody who wants the mechanism.
    technical: Mapping[str, Any]

    def as_record(self) -> Mapping[str, Any]:
        return {
            "applicationId": self.application_id,
            "displayName": self.display_name,
            "running": self.running,
            "headline": self.headline,
            "plain": [{"label": label, "value": value} for label, value in self.plain],
            "caveats": list(self.caveats),
            "technical": dict(self.technical),
        }


def _files_phrase(plan: IsolationPlan) -> str:
    """How many of the user's files this capsule can see, and how it reads."""
    grants = [bind for bind in plan.binds if bind.origin == "grant"]
    if not grants:
        return "None of your files"
    directories = [bind for bind in grants if bind.kind == "directory"]
    files = [bind for bind in grants if bind.kind == "file"]
    if len(grants) == 1:
        name = Path(grants[0].source.rstrip("/")).name
        return f"This folder only: {name}" if directories else f"This file only: {name}"
    parts = []
    if files:
        parts.append(f"{len(files)} file{'s' if len(files) != 1 else ''}")
    if directories:
        parts.append(f"{len(directories)} folder{'s' if len(directories) != 1 else ''}")
    return "Only " + " and ".join(parts) + " you chose"


def capsule_status(capsule: Capsule, plan: IsolationPlan) -> CapsuleStatus:
    """Build both layers from one plan.

    Takes the plan rather than building it, so a caller that already has one for
    a launch does not build a second that could differ from the one in effect.
    """
    name = capsule.manifest.display_name
    running = capsule.state.state == "running"

    plain: list[tuple[str, str]] = [
        ("Access", _files_phrase(plan)),
        ("Network", NETWORK_PHRASES.get(plan.network, plan.network)),
        ("Private app data", "Isolated" if plan.confining else "Not isolated"),
        (
            "Devices",
            "Graphics card" if "/dev/dri" in plan.devices else "None",
        ),
    ]

    caveats: list[str] = []
    if not plan.confining:
        caveats.append(
            f"{name} is not in a protected space on this computer. Bunny applies limits and "
            f"records what it does, and restricts nothing else."
        )
    for category in plan.unenforced:
        title = CATEGORIES[category].title if category in CATEGORIES else category
        caveats.append(
            f"{title}: Bunny records this permission and cannot stop {name} using it in this build."
        )
    if plan.unapplied_limits:
        caveats.append(
            "This computer ignores the limits Bunny sets, so it cannot cap how much memory or "
            "processor time " + name + " uses: " + ", ".join(plan.unapplied_limits) + "."
        )
    if not plan.network_enforced and plan.network != "none":
        caveats.append(
            f"{name} was allowed a named set of addresses, and Bunny cannot restrict it to them. "
            f"It can reach anything on the internet."
        )
    for _grant_id, reason in plan.refusals:
        caveats.append(f"One permission could not be applied: {reason}")

    technical: Mapping[str, Any] = {
        "backend": plan.backend,
        "confining": plan.confining,
        "applicationId": capsule.identity.application_id,
        "unitName": capsule.identity.unit_name,
        "pid": capsule.state.pid,
        "cgroupScope": capsule.state.scope_name,
        "namespaces": list(plan.unshare),
        "mounts": [
            {
                "source": bind.source,
                "target": bind.target,
                "writable": bind.writable,
                "origin": bind.origin,
            }
            for bind in plan.binds
        ],
        "devices": list(plan.devices),
        "network": {
            "class": plan.network,
            "domains": list(plan.network_domains),
            "enforced": plan.network_enforced,
        },
        "environmentKeys": sorted(plan.environment),
        "dbusTalk": list(plan.dbus_talk),
        "portalAllow": list(plan.portal_allow),
        "resourceLimits": list(plan.systemd_properties),
        "unappliedLimits": list(plan.unapplied_limits),
        "unenforcedPermissions": list(plan.unenforced),
        "refusals": [{"grantId": gid, "reason": reason} for gid, reason in plan.refusals],
    }

    headline = (
        f"{name} is running in its protected space."
        if running and plan.confining
        else f"{name} runs in its protected space."
        if plan.confining
        else f"{name} runs with limits only on this computer."
    )
    return CapsuleStatus(
        application_id=capsule.identity.application_id,
        display_name=name,
        running=running,
        plain=tuple(plain),
        headline=headline,
        caveats=tuple(caveats),
        technical=technical,
    )
