# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage 9 — systematic NSS account-availability sweep of repo-shipped units.

The chronyd correction in ``systemd/chronyd.service.d/50-bunny-nss-order.conf``
closed the one measured occurrence of the altfiles NSS race. The mechanism is
not chrony-specific: ``/etc/nsswitch.conf`` is a symlink to
``/etc/authselect/nsswitch.conf``, ``authselect-apply-changes.service`` rewrites
that file on first boot, and for the width of the rewrite no account provided
by ``/usr/lib/passwd`` through the ``altfiles`` source resolves. Any unit
resolving a ``User=`` satisfied that way, spawning inside the window, exits
``217/USER`` and does not retry.

The correction is generalised here from "chronyd is a one-off" to "every
repo-shipped unit that resolves an altfiles-backed identity must carry the
nss-user-lookup.target ordering drop-in". This is the systematic sweep
``KNOWN_LIMITATIONS.md`` and ``NEXT_PHASE.md`` explicitly recorded as absent.

These tests are build-time: they scan the repo's own ``systemd/`` tree. They
cannot see base-image units, which the repo does not enumerate at build time;
``scripts/nss_account_sweep.py`` is the runtime complement an operator runs
against an installed system. The two are paired by design.

Conventions follow ``test_corrections.py``: each test names the way the
property could be faked and rejects that, rather than asserting the fix "is
present". A sweep that passes because no at-risk unit exists is vacuous, so a
mutation test proves the sweep flags a synthetic at-risk unit lacking the
drop-in — the same load-bearing pattern the evidence-gate mutation tests use.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

# The operator-facing scanner is importable from scripts/. Placed on sys.path
# here, not at repo import time, so the test suite does not gain a scripts/
# import root that shadows other packages.
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import nss_account_sweep  # noqa: E402

SYSTEMD_DIR = ROOT / "systemd"
SYSTEMD_USER_DIR = ROOT / "systemd" / "user"
CHRONYD_DROPIN = SYSTEMD_DIR / "chronyd.service.d" / "50-bunny-nss-order.conf"

#: The identities the repo bakes into /etc/passwd. root is always there; the
#: repo's service account bunny-policy is the other one its units use
#: (systemd/bunny-policy-agent.service). bunny-policy's provisioning is a
#: separate known gap recorded elsewhere — this set only states that *if* the
#: account is provisioned, it lives in /etc/passwd, not /usr/lib/passwd, and so
#: does not route through altfiles. A numeric UID/GID needs no NSS lookup at
#: all and is safe regardless.
ETC_PASSWD_IDENTITIES: frozenset[str] = frozenset({"root", "bunny-policy"})


def directives(unit: Path, name: str) -> list[str]:
    """Every value assigned to ``name`` in ``unit``, ignoring comments.

    Mirrors the helper in test_corrections.py so the two test files cannot
    drift on parsing behaviour.
    """
    values: list[str] = []
    if not unit.is_file():
        return values
    for line in unit.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith(";"):
            continue
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key.strip() == name:
            values.append(value.strip())
    return values


def all_repo_service_units() -> list[Path]:
    """Every repo-shipped ``*.service`` the sweep is responsible for.

    Includes the user units under ``systemd/user/``: a ``User=`` there resolves
    through the same NSS stack at user-session start, and the same window
    applies during the user manager's first boot.
    """
    units: list[Path] = []
    for pattern in ("*.service",):
        units.extend(sorted(SYSTEMD_DIR.glob(pattern)))
    if SYSTEMD_USER_DIR.is_dir():
        units.extend(sorted(SYSTEMD_USER_DIR.glob("*.service")))
    return units


def repo_unit_identities() -> list[nss_account_sweep.UnitIdentity]:
    """The ``User=``/``Group=`` declared by every repo-shipped service unit."""
    out: list[nss_account_sweep.UnitIdentity] = []
    for path in all_repo_service_units():
        directives_map = nss_account_sweep.parse_unit_directives(path)
        user_values = directives_map.get("User", [])
        group_values = directives_map.get("Group", [])
        user = user_values[-1] if user_values else None
        group = group_values[-1] if group_values else None
        if user is None and group is None:
            continue
        out.append(nss_account_sweep.UnitIdentity(
            unit_path=path, unit_name=path.name, user=user, group=group))
    return out


class CanonicalPatternTests(unittest.TestCase):
    """The nss-user-lookup.target ordering pattern, asserted against the one
    unit that currently carries it. This preserves the existing chronyd
    assertion in test_corrections.py and restates it in terms of the canonical
    pattern the sweep generalises."""

    def test_chronyd_drop_in_carries_the_canonical_nss_ordering(self):
        """The pattern: Wants= + After= nss-user-lookup.target;
        After= authselect-apply-changes.service; NO Requires= on authselect;
        NO Before= from the consuming unit."""
        wants = " ".join(directives(CHRONYD_DROPIN, "Wants")).split()
        after = " ".join(directives(CHRONYD_DROPIN, "After")).split()
        before = " ".join(directives(CHRONYD_DROPIN, "Before")).split()
        requires = " ".join(directives(CHRONYD_DROPIN, "Requires")).split()

        self.assertIn(
            "nss-user-lookup.target", wants,
            "the passive target must be pulled in by Wants=, or After= on it "
            "orders nothing because the target is not in the transaction")
        self.assertIn(
            "nss-user-lookup.target", after,
            "the consuming unit must be ordered after the target systemd "
            "documents for 'identity sources are settled'")
        self.assertIn(
            "authselect-apply-changes.service", after,
            "the measured window is authselect's; the record should name the "
            "unit whose window was actually observed as well as the contract")
        self.assertNotIn(
            "authselect-apply-changes.service", requires,
            "Requires= on a unit with ConditionPathIsReadWrite=/etc converts "
            "a timing race into an availability failure wherever the condition "
            "does not hold")
        self.assertEqual(
            before, [],
            "a drop-in that adds Before= edges can close an ordering cycle "
            "through the units it orders after")

    def test_chronyd_drop_in_uses_no_arbitrary_sleep(self):
        """The fix is ordering, not a sleep that happens to outlast the
        window. A sleep would hide the race rather than close it, and would
        slow every boot whether the window occurs or not."""
        for directive in ("SleepSec", "ExecStartPre", "ExecStartPost"):
            for value in directives(CHRONYD_DROPIN, directive):
                self.assertNotRegex(
                    value, re.compile(r"\bsleep\b"),
                    f"the drop-in uses {directive}={value}, an arbitrary sleep "
                    "that masks the race instead of ordering against it")


def build_time_kind(identity: str | None) -> str:
    """Classify a repo unit identity at build time.

    The repo does not ship ``/usr/lib/passwd``, so the build-time sweep cannot
    consult it. The classification is therefore conservative: an identity is
    safe only if it is provably not routed through altfiles — i.e. it is a
    numeric UID/GID (no NSS lookup) or it names an account the repo bakes into
    ``/etc/passwd`` (resolved by the ``files`` source, which authselect does
    not rewrite). Anything else is at-risk: the repo cannot prove it is in
    ``/etc/passwd``, so a future base-image ``/usr/lib/passwd`` entry of the
    same name would route it through the altfiles window.

    This is stricter than the runtime classifier in ``nss_account_sweep.py``,
    which has both passwd databases to hand. The two agree on the safe set;
    the build-time classifier simply folds 'unknown' into 'at-risk' because a
    build-time test must not assume an identity it cannot locate is safe.
    """
    if identity is None:
        return "none"
    stripped = identity.strip()
    if not stripped:
        return "none"
    if stripped.lstrip("-").isdigit():
        return "numeric"
    if stripped in ETC_PASSWD_IDENTITIES:
        return "etc"
    return "at-risk"


class RepoUnitSweepTests(unittest.TestCase):
    """The systematic sweep: every repo unit with ``User=``/``Group=`` is
    classified, and every at-risk one must carry the ordering drop-in.

    Today all repo-shipped units are safe: every identity is ``root``,
    ``bunny-policy`` or numeric, and none routes through the altfiles source
    that the authselect rewrite transiently removes. The sweep documents that
    and fails if a future unit adds an altfiles-backed ``User=`` without the
    ordering drop-in — generalising chronyd from a one-off into the class."""

    def test_repo_ships_units_for_the_sweep_to_have_subjects(self):
        """A regression that removes every User=/Group= from the repo would
        make this sweep vacuous. The repo does ship units with identities
        (root, bunny-policy), and the sweep must have subjects."""
        identities = repo_unit_identities()
        self.assertTrue(
            identities,
            "no repo unit declares User=/Group=; the sweep has nothing to "
            "scan and cannot generalise the chronyd correction")

    def test_every_repo_unit_identity_is_safe_today(self):
        """Today every repo-shipped unit resolves an identity in /etc/passwd
        (root, bunny-policy) or a numeric UID. None routes through altfiles.
        Documents the current state and fails if a future unit names an
        account the repo cannot prove is in /etc/passwd."""
        identities = repo_unit_identities()
        at_risk: list[tuple[str, str, str]] = []
        for identity in identities:
            for field_name, value in (("User", identity.user),
                                      ("Group", identity.group)):
                if build_time_kind(value) == "at-risk":
                    at_risk.append((identity.unit_name, field_name, value))
        self.assertEqual(
            at_risk, [],
            f"repo units declare at-risk identities {at_risk}; each needs "
            "either an account provably in /etc/passwd, a numeric UID, or a "
            "drop-in under systemd/<unit>.service.d/ with Wants= + After= "
            "nss-user-lookup.target and After=authselect-apply-changes.service")

    def test_at_risk_repo_unit_would_be_required_to_carry_the_drop_in(self):
        """If a repo unit did resolve an at-risk identity, the sweep would
        require the ordering drop-in. Today there are none, so this is a guard
        that the build-time classification and the scanner's drop-in detector
        agree on the pattern. Proved by a synthetic at-risk repo unit in a
        tempdir in SweepIsLoadBearingTests; this test asserts the agreement
        holds against the real repo tree for any unit the classifier flags."""
        identities = repo_unit_identities()
        missing: list[str] = []
        for identity in identities:
            at_risk = (build_time_kind(identity.user) == "at-risk" or
                       build_time_kind(identity.group) == "at-risk")
            if not at_risk:
                continue
            present, _ = nss_account_sweep.has_nss_ordering_dropin(
                SYSTEMD_DIR, identity.unit_name)
            if not present:
                missing.append(identity.unit_name)
        self.assertEqual(
            missing, [],
            f"at-risk repo units {missing} lack the nss-user-lookup.target "
            "ordering drop-in")

    def test_no_repo_unit_uses_an_arbitrary_sleep_as_nss_workaround(self):
        """A sleep (SleepSec= or ExecStartPre=/ExecStartPost= sleep) is the
        wrong fix for an NSS race: it masks the window instead of ordering
        against the contract, and it delays every boot whether the window
        occurs or not. No repo-shipped unit may use one."""
        offenders: list[str] = []
        for unit in all_repo_service_units():
            directives_map = nss_account_sweep.parse_unit_directives(unit)
            for key in ("SleepSec", "ExecStartPre", "ExecStartPost"):
                for value in directives_map.get(key, []):
                    if re.search(r"\bsleep\b", value):
                        offenders.append(f"{unit.name}: {key}={value}")
        self.assertEqual(
            offenders, [],
            f"repo units use arbitrary sleeps as an NSS workaround: "
            f"{offenders}; order against nss-user-lookup.target instead")


class SweepIsLoadBearingTests(unittest.TestCase):
    """A sweep that passes because no at-risk unit exists is vacuous. These
    mutation tests prove the sweep flags a synthetic at-risk unit that lacks
    the drop-in, and accepts one that carries it — the same load-bearing
    pattern the evidence-gate mutation tests use."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.system_dir = self.root / "usr/lib/systemd/system"
        self.system_dir.mkdir(parents=True, exist_ok=True)
        (self.root / "etc").mkdir(parents=True, exist_ok=True)
        (self.root / "usr/lib").mkdir(parents=True, exist_ok=True)
        # /etc/passwd has root; /usr/lib/passwd has an altfiles-backed account.
        (self.root / "etc/passwd").write_text(
            "root:x:0:0:root:/root:/bin/bash\n", encoding="utf-8")
        (self.root / "usr/lib/passwd").write_text(
            "chrony:x:994:992::/var/lib/chrony:/usr/sbin/nologin\n",
            encoding="utf-8")
        self.addCleanup(self.tmp.cleanup)

    def _write_unit(self, name: str, user: str) -> Path:
        path = self.system_dir / name
        path.write_text(
            "[Service]\nExecStart=/usr/bin/true\n"
            f"User={user}\nGroup={user}\n",
            encoding="utf-8")
        return path

    def _write_ordering_dropin(self, unit_name: str) -> None:
        dropin_dir = self.system_dir / f"{unit_name}.d"
        dropin_dir.mkdir(parents=True, exist_ok=True)
        (dropin_dir / "50-nss-order.conf").write_text(
            "[Unit]\nWants=nss-user-lookup.target\n"
            "After=nss-user-lookup.target\n"
            "After=authselect-apply-changes.service\n",
            encoding="utf-8")

    def test_flags_altfiles_backed_unit_without_the_drop_in(self):
        """A unit whose User= resolves through /usr/lib/passwd and which has
        no drop-in is reported at-risk. If this passes, the sweep is not
        vacuously green."""
        self._write_unit("at-risk.service", "chrony")
        report = nss_account_sweep.scan_system(self.root)
        self.assertFalse(report.passed, "the sweep passed on a unit that "
                         "resolves an altfiles-backed User= with no ordering "
                         "drop-in; the sweep is vacuous")
        self.assertEqual(len(report.at_risk), 1)
        self.assertEqual(report.at_risk[0].unit_name, "at-risk.service")

    def test_accepts_altfiles_backed_unit_with_the_drop_in(self):
        """The same unit with the ordering drop-in is not at-risk: the sweep
        rewards the fix rather than flagging the identity by name."""
        self._write_unit("guarded.service", "chrony")
        self._write_ordering_dropin("guarded.service")
        report = nss_account_sweep.scan_system(self.root)
        self.assertTrue(
            report.passed,
            f"the sweep flagged a unit that carries the drop-in: "
            f"{[r.unit_name for r in report.at_risk]}")
        self.assertEqual(report.altfiles_backed, 1)

    def test_does_not_flag_etc_passwd_backed_unit(self):
        """root is in /etc/passwd; it must never be reported, with or without
        a drop-in. This is the property that keeps the sweep from noise."""
        self._write_unit("safe.service", "root")
        report = nss_account_sweep.scan_system(self.root)
        self.assertTrue(report.passed)
        self.assertEqual(report.altfiles_backed, 0)

    def test_does_not_flag_numeric_identity(self):
        """A numeric UID does not go through NSS and cannot be affected by the
        altfiles window."""
        path = self.system_dir / "numeric.service"
        path.write_text(
            "[Service]\nExecStart=/usr/bin/true\nUser=471\nGroup=471\n",
            encoding="utf-8")
        report = nss_account_sweep.scan_system(self.root)
        self.assertTrue(report.passed)
        self.assertEqual(report.altfiles_backed, 0)

    def test_drop_in_missing_wants_is_not_accepted(self):
        """Wants= is load-bearing: without it the passive target is not in the
        transaction and After= orders nothing. The detector must reject a
        drop-in that has only After=."""
        self._write_unit("wantsless.service", "chrony")
        dropin_dir = self.system_dir / "wantsless.service.d"
        dropin_dir.mkdir(parents=True, exist_ok=True)
        (dropin_dir / "50-broken.conf").write_text(
            "[Unit]\nAfter=nss-user-lookup.target\n"
            "After=authselect-apply-changes.service\n",
            encoding="utf-8")
        present, _ = nss_account_sweep.has_nss_ordering_dropin(
            self.system_dir, "wantsless.service")
        self.assertFalse(
            present,
            "the detector accepted a drop-in without Wants=; the passive "
            "target is not pulled in and the After= is vacuous")

    def test_drop_in_with_requires_on_authselect_is_not_accepted(self):
        """Requires= on authselect converts the race into an availability
        failure on systems where the condition does not hold. The detector
        must reject it."""
        self._write_unit("required.service", "chrony")
        dropin_dir = self.system_dir / "required.service.d"
        dropin_dir.mkdir(parents=True, exist_ok=True)
        (dropin_dir / "50-broken.conf").write_text(
            "[Unit]\nWants=nss-user-lookup.target\n"
            "After=nss-user-lookup.target\n"
            "After=authselect-apply-changes.service\n"
            "Requires=authselect-apply-changes.service\n",
            encoding="utf-8")
        present, _ = nss_account_sweep.has_nss_ordering_dropin(
            self.system_dir, "required.service")
        self.assertFalse(
            present,
            "the detector accepted a drop-in with Requires= on "
            "authselect; that turns a timing race into an availability "
            "failure where the condition does not hold")

    def test_drop_in_with_before_is_not_accepted(self):
        """A Before= on the consuming unit risks an ordering cycle through the
        units it orders after. The detector must reject it."""
        self._write_unit("cyclic.service", "chrony")
        dropin_dir = self.system_dir / "cyclic.service.d"
        dropin_dir.mkdir(parents=True, exist_ok=True)
        (dropin_dir / "50-broken.conf").write_text(
            "[Unit]\nWants=nss-user-lookup.target\n"
            "After=nss-user-lookup.target\n"
            "After=authselect-apply-changes.service\n"
            "Before=multi-user.target\n",
            encoding="utf-8")
        present, _ = nss_account_sweep.has_nss_ordering_dropin(
            self.system_dir, "cyclic.service")
        self.assertFalse(
            present,
            "the detector accepted a drop-in with Before=; a drop-in that "
            "adds Before= edges can close an ordering cycle")


class ClassifierUnitTests(unittest.TestCase):
    """The runtime classifier, exercised in isolation so the operator script's
    behaviour does not depend on argv or on a real installed system."""

    def test_none_identity_is_none(self):
        self.assertEqual(
            nss_account_sweep.classify_runtime(None, ("root",), ("chrony",)),
            "none")

    def test_numeric_identity_is_safe(self):
        self.assertEqual(
            nss_account_sweep.classify_runtime("471", (), ()),
            "numeric")
        self.assertEqual(
            nss_account_sweep.classify_runtime("-1", (), ()),
            "numeric")

    def test_etc_passwd_identity_is_safe(self):
        self.assertEqual(
            nss_account_sweep.classify_runtime("root", ("root",), ("chrony",)),
            "etc")

    def test_altfiles_identity_is_at_risk(self):
        self.assertEqual(
            nss_account_sweep.classify_runtime("chrony", ("root",), ("chrony",)),
            "altfiles")

    def test_unknown_identity_is_reported_not_assumed_safe(self):
        """A name in neither database is never silently treated as safe: it
        could be a DynamicUser, a typo, or a missing database. The classifier
        returns 'unknown' so the caller can report it."""
        self.assertEqual(
            nss_account_sweep.classify_runtime("nobody-knows", ("root",), ()),
            "unknown")

    def test_etc_takes_precedence_over_altfiles(self):
        """If a name is in both databases, the files source resolves it first
        and authselect does not rewrite /etc/passwd, so it is safe."""
        self.assertEqual(
            nss_account_sweep.classify_runtime(
                "shared", ("root", "shared"), ("shared",)),
            "etc")


if __name__ == "__main__":
    unittest.main()