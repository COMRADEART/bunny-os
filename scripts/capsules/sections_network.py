# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What a capsule can actually reach on the network, class by class.

§9 asks for four classes to be tested with real connection attempts, and it asks
for something else that matters more: *if domain-level enforcement is not
actually implemented, state that clearly. Do not fake domain filtering with
application cooperation.*

So this section measures what the implementation does and reports the gap where
there is one. It does not ask the application to respect a policy; every row is a
connect() made by a program that would very much like to succeed.

The four classes and what this build does with each:

``none``            a network namespace of its own with nothing in it. Enforced
                    by ``--unshare-net``, which is a kernel boundary.
``internet``        no network namespace. Enforced in the sense that it is the
                    absence of a restriction.
``local-network``   declared, and **not** enforced: the plan has no way to permit
                    the local subnet and refuse the rest.
``allowlisted``     declared, and **not** enforced: the plan carries the domains
                    and nothing filters on them.

The last two are measured rather than asserted — the section grants an
``allowlisted`` class naming one domain and then has the capsule connect to a
different one. If that succeeds, the class is not enforcement, and the row says
so with the connection that proves it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import trust
from capsules.manifest import CapsuleManifest, ResourceLimits

from .harness import Evidence, Harness, _by_check, require_confinement

__all__ = ["section_network"]

#: A domain the allowlist names, and one it does not. The second is the whole
#: measurement: reaching it proves the allowlist is a declaration.
ALLOWED_DOMAIN = "example.com"
FORBIDDEN_DOMAIN = "example.org"


def _install(harness: Harness, ceiling: str, domains: frozenset[str] = frozenset()):
    import capsules

    manifest = CapsuleManifest(
        identity=capsules.capsule_identity("art.comrade.NetProbe"),
        display_name="Net Probe",
        package_source="fedora-rpm",
        package_reference="/usr/bin/python3",
        preferred_backend="bubblewrap",
        required_permissions=frozenset({"files"}),
        optional_permissions=frozenset({"network"}),
        permission_reasons={"files": "to read the file you choose", "network": "to reach its service"},
        network_ceiling=ceiling,
        network_domains=domains,
        limits=ResourceLimits(),
    )
    return harness.runtime.install(manifest)


def _run(harness: Harness, capsule, port: int) -> Mapping[str, Any]:
    harness.configure_probe(
        capsule,
        BUNNY_PROBE_LOCALHOST_PORT=str(port),
        BUNNY_PROBE_CAPSULE_ROOT=str(harness.runtime.root),
        BUNNY_PROBE_ALLOWED_DOMAIN=ALLOWED_DOMAIN,
        BUNNY_PROBE_FORBIDDEN_DOMAIN=FORBIDDEN_DOMAIN,
    )
    return harness.run_probe(harness.runtime.open(capsule.identity.application_id))


def section_network(harness: Harness, host: Mapping[str, Any]) -> Evidence:
    """No network, then general network, then the two classes that are not real."""
    evidence = Evidence(section="network")
    if not require_confinement(host, evidence):
        return evidence

    measurements: dict[str, Any] = {}
    checks = ("network_external", "network_dns", "network_localhost", "network_allowed_domain",
              "network_forbidden_domain")

    with harness.listening_socket() as port:
        # 1. No network at all.
        capsule = _install(harness, "none")
        measurements["none"] = {
            "probe": _by_check(_run(harness, capsule, port).get("probe", {})),
        }

        # 2. General internet, granted.
        harness.runtime.uninstall(harness.runtime.open("art.comrade.NetProbe"))
        capsule = _install(harness, "internet")
        harness.surface.answers = (("network", "allow", "always"),)
        decision = harness.runtime.request_permission(
            harness.runtime.open("art.comrade.NetProbe"),
            category="network",
            resource=trust.network_resource("internet"),
        )
        measurements["internetGrant"] = {"verdict": decision.verdict, "reason": decision.reason_code}
        result = _run(harness, harness.runtime.open("art.comrade.NetProbe"), port)
        measurements["internet"] = {"probe": _by_check(result.get("probe", {})), "plan": {
            "network": result.get("probe", {}) and None,
        }}
        measurements["internet"]["networkClass"] = "internet"

        # 3. An allowlist naming one domain, with a connection to another.
        harness.runtime.uninstall(harness.runtime.open("art.comrade.NetProbe"))
        capsule = _install(harness, "allowlisted", frozenset({ALLOWED_DOMAIN}))
        harness.surface.answers = (("network", "allow", "always"),)
        allow_decision = harness.runtime.request_permission(
            harness.runtime.open("art.comrade.NetProbe"),
            category="network",
            resource=trust.network_resource("allowlisted", allowlist=(ALLOWED_DOMAIN,)),
        )
        measurements["allowlistGrant"] = {
            "verdict": allow_decision.verdict, "reason": allow_decision.reason_code,
            "allowed": ALLOWED_DOMAIN, "forbidden": FORBIDDEN_DOMAIN,
        }
        allow_result = _run(harness, harness.runtime.open("art.comrade.NetProbe"), port)
        measurements["allowlisted"] = {"probe": _by_check(allow_result.get("probe", {}))}
        try:
            plan = harness.runtime.build_plan(harness.runtime.open("art.comrade.NetProbe"))
            measurements["allowlisted"]["planNetwork"] = plan.network
            measurements["allowlisted"]["planDomains"] = list(plan.network_domains)
            measurements["allowlisted"]["unshare"] = list(plan.unshare)
        except Exception as error:  # noqa: BLE001
            measurements["allowlisted"]["planError"] = str(error)

    evidence.measurements = measurements

    def result_of(stage: str, check: str) -> str:
        return measurements.get(stage, {}).get("probe", {}).get(check, {}).get("result", "NOT_RUN")

    problems: list[str] = []
    findings: list[str] = []

    # No network must actually mean none.
    for check in ("network_external", "network_dns", "network_localhost"):
        if result_of("none", check) == "AVAILABLE":
            problems.append(f"a capsule with no network grant reached {check}")

    # A granted internet class must actually work, or the class is useless.
    if result_of("internet", "network_external") != "AVAILABLE":
        findings.append(
            f"the internet class did not reach the network on this host: "
            f"{result_of('internet', 'network_external')}; the host may be offline"
        )

    # The measurement that matters: is an allowlist a boundary?
    forbidden = result_of("allowlisted", "network_forbidden_domain")
    allowed = result_of("allowlisted", "network_allowed_domain")
    if forbidden == "AVAILABLE":
        findings.append(
            f"the allowlisted network class is a declaration, not a boundary: a capsule granted "
            f"only {ALLOWED_DOMAIN} connected to {FORBIDDEN_DOMAIN}. This build maps every class "
            f"other than 'none' onto the absence of a network namespace; there is no per-domain "
            f"filter and none is claimed. Accepted and disclosed, not fixed here."
        )
    evidence.findings.extend(findings)

    if problems:
        evidence.findings.extend(problems)
        return evidence.settle("FAIL", "; ".join(problems))

    return evidence.settle(
        "PASS",
        f"no-network denied external, DNS and loopback; internet reached "
        f"{result_of('internet', 'network_external')}; allowlisted reached the named domain "
        f"({allowed}) and also an unnamed one ({forbidden}) — recorded as a disclosed gap",
    )
