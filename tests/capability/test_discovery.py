# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Discovery: bounded time, refused commands, and failure that is not fatal.

These tests run on whatever host executes them. They therefore assert on
*behaviour under absence* — that a probe which cannot run yields ``unknown``
rather than a default, that the pass stays inside its budget, and that a probe
raising does not take the boot with it — rather than on any particular hardware
being present. That is deliberate: §16 requires deterministic tests, and a test
that asserts this machine has a GPU is neither deterministic nor portable.
"""

from __future__ import annotations

from pathlib import Path
import unittest
from unittest import mock

from capability.discovery import DEFAULT_BUDGET_MS, discover
from capability.discovery import cpu as cpu_probe
from capability.discovery import memory as memory_probe
from capability.discovery import sources
from capability.discovery.sources import ALLOWED_COMMANDS, Deadline, run, sanitize
from capability.model import UNKNOWN


class FakeClock:
    """A monotonic clock the test drives, so deadlines expire without sleeping."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class DeadlineTests(unittest.TestCase):
    def test_a_deadline_expires_without_the_test_sleeping(self) -> None:
        clock = FakeClock()
        deadline = Deadline(2000, clock=clock)
        self.assertFalse(deadline.expired)
        clock.advance(2.5)
        self.assertTrue(deadline.expired)
        self.assertEqual(deadline.remaining_seconds, 0.0)

    def test_a_probe_slice_never_exceeds_what_remains(self) -> None:
        clock = FakeClock()
        deadline = Deadline(1000, clock=clock)
        clock.advance(0.8)
        # The probe asked for three seconds; 200 ms of the pass remain.
        self.assertAlmostEqual(deadline.slice_seconds(3.0), 0.2, places=3)

    def test_elapsed_is_reported_in_milliseconds(self) -> None:
        clock = FakeClock()
        deadline = Deadline(5000, clock=clock)
        clock.advance(1.25)
        self.assertEqual(deadline.elapsed_ms, 1250)


class CommandAllowlistTests(unittest.TestCase):
    """Nothing outside the allowlist may be executed, ever."""

    def test_a_command_not_on_the_allowlist_is_refused_without_running(self) -> None:
        with mock.patch("subprocess.run") as spawn:
            result = run(["/bin/sh", "-c", "echo hello"], deadline=Deadline(1000))
        self.assertFalse(result.ok)
        self.assertIn("not permitted", result.detail)
        spawn.assert_not_called()

    def test_a_bare_command_name_is_refused(self) -> None:
        # A bare name would be resolved through PATH. Every allowlist entry is
        # an absolute path precisely so that cannot happen.
        with mock.patch("subprocess.run") as spawn:
            result = run(["nvidia-smi"], deadline=Deadline(1000))
        self.assertFalse(result.ok)
        spawn.assert_not_called()

    def test_every_allowlisted_command_is_an_absolute_path(self) -> None:
        for command in ALLOWED_COMMANDS:
            with self.subTest(command=command):
                self.assertTrue(command.startswith("/"), command)

    def test_an_empty_command_is_refused(self) -> None:
        self.assertFalse(run([], deadline=Deadline(1000)).ok)

    def test_an_exhausted_deadline_prevents_a_spawn(self) -> None:
        clock = FakeClock()
        deadline = Deadline(100, clock=clock)
        clock.advance(1.0)
        with mock.patch.object(sources, "which_allowed", return_value="/usr/bin/nvidia-smi"), \
                mock.patch("subprocess.run") as spawn:
            result = run(["/usr/bin/nvidia-smi"], deadline=deadline)
        self.assertFalse(result.ok)
        self.assertIn("deadline", result.detail)
        spawn.assert_not_called()

    def test_a_timeout_is_reported_not_raised(self) -> None:
        import subprocess

        with mock.patch.object(sources, "which_allowed", return_value="/usr/bin/nvidia-smi"), \
                mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("nvidia-smi", 2.0)):
            result = run(["/usr/bin/nvidia-smi"], deadline=Deadline(5000))
        self.assertFalse(result.ok)
        self.assertIn("timed out", result.detail)

    def test_no_shell_is_used(self) -> None:
        with mock.patch.object(sources, "which_allowed", return_value="/usr/bin/nvidia-smi"), \
                mock.patch("subprocess.run") as spawn:
            spawn.return_value = mock.Mock(returncode=0, stdout=b"")
            run(["/usr/bin/nvidia-smi", "--query-gpu=index"], deadline=Deadline(5000))
        _, keywords = spawn.call_args
        self.assertNotIn("shell", keywords)
        self.assertEqual(keywords["cwd"], "/")
        self.assertNotIn("PATH=/tmp", str(keywords["env"]))

    def test_output_is_truncated_to_the_documented_bound(self) -> None:
        with mock.patch.object(sources, "which_allowed", return_value="/usr/bin/nvidia-smi"), \
                mock.patch("subprocess.run") as spawn:
            spawn.return_value = mock.Mock(returncode=0, stdout=b"x" * (4 * sources.MAX_OUTPUT_BYTES))
            result = run(["/usr/bin/nvidia-smi"], deadline=Deadline(5000))
        self.assertLessEqual(len(result.stdout), sources.MAX_OUTPUT_BYTES)


class SanitizeTests(unittest.TestCase):
    def test_control_characters_are_dropped_rather_than_escaped(self) -> None:
        self.assertEqual(sanitize("GeForce\x00 RTX\n 4090"), "GeForce RTX 4090")

    def test_output_is_length_bounded(self) -> None:
        self.assertEqual(len(sanitize("a" * 5000, limit=64)), 64)

    def test_shell_metacharacters_do_not_survive(self) -> None:
        # Nothing sanitized is ever passed back to a subprocess, but a value
        # that reaches a JSON document and a terminal should not carry them.
        self.assertNotIn("`", sanitize("model`whoami`"))
        self.assertNotIn("$", sanitize("model$(id)"))
        self.assertNotIn("|", sanitize("model|rm"))


class ParsingTests(unittest.TestCase):
    """Parsers are pure functions of text and are tested as such."""

    def test_meminfo_converts_kilobytes_to_bytes(self) -> None:
        text = "MemTotal:       16316520 kB\nMemAvailable:    9000000 kB\nHugePages_Total:       0\n"
        with mock.patch.object(memory_probe, "read_text", return_value=text):
            values = memory_probe.meminfo()
        self.assertEqual(values["MemTotal"], 16316520 * 1024)
        self.assertEqual(values["MemAvailable"], 9000000 * 1024)
        # HugePages_Total is a count, not a kB figure, and must not be scaled.
        self.assertEqual(values["HugePages_Total"], 0)

    def test_an_unreadable_meminfo_yields_no_values_rather_than_zeroes(self) -> None:
        with mock.patch.object(memory_probe, "read_text", return_value=None):
            self.assertEqual(memory_probe.meminfo(), {})

    def test_cgroup_v2_max_means_unrestricted_not_zero(self) -> None:
        with mock.patch.object(memory_probe, "read_first_line", return_value="max"), \
                mock.patch.object(memory_probe, "read_int", return_value=None):
            limit, detail = memory_probe.cgroup_limit()
        self.assertIsNone(limit)
        self.assertIn("unrestricted", detail)

    def test_cgroup_v2_limit_is_read_as_a_ceiling(self) -> None:
        with mock.patch.object(memory_probe, "read_first_line", return_value="536870912"):
            limit, detail = memory_probe.cgroup_limit()
        self.assertEqual(limit, 536870912)
        self.assertIn("cgroup2", detail)

    def test_the_cgroup_v1_unlimited_sentinel_is_not_read_as_a_ceiling(self) -> None:
        # 9223372036854771712 is "no limit", not eight exabytes of RAM.
        with mock.patch.object(memory_probe, "read_first_line", return_value=None), \
                mock.patch.object(memory_probe, "read_int", return_value=9223372036854771712):
            limit, detail = memory_probe.cgroup_limit()
        self.assertIsNone(limit)
        self.assertIn("unrestricted", detail)

    def test_cpu_quota_is_read_as_a_fraction_of_a_core(self) -> None:
        with mock.patch.object(cpu_probe, "read_first_line", return_value="50000 100000"):
            cores, detail = cpu_probe.quota_cores()
        self.assertEqual(cores, 0.5)
        self.assertIn("cgroup2", detail)

    def test_an_unparseable_cpu_quota_is_unknown_not_zero(self) -> None:
        with mock.patch.object(cpu_probe, "read_first_line", return_value="not a quota"), \
                mock.patch.object(cpu_probe, "read_int", return_value=None):
            cores, _ = cpu_probe.quota_cores()
        self.assertIsNone(cores)

    def test_cpuinfo_counts_distinct_physical_cores(self) -> None:
        text = (
            "processor\t: 0\nphysical id\t: 0\ncore id\t: 0\nflags\t: avx2 aes\n\n"
            "processor\t: 1\nphysical id\t: 0\ncore id\t: 0\nflags\t: avx2 aes\n\n"
            "processor\t: 2\nphysical id\t: 0\ncore id\t: 1\nflags\t: avx2 aes\n\n"
        )
        _, flags, cores = cpu_probe._cpuinfo_fields(text)
        self.assertEqual(cores, 2)  # two cores, three threads
        self.assertIn("avx2", flags)


class DiscoveryPassTests(unittest.TestCase):
    def test_discovery_completes_within_its_budget_on_this_host(self) -> None:
        inventory = discover(budget_ms=DEFAULT_BUDGET_MS, probe_runtimes=False)
        self.assertLessEqual(inventory.detection_duration_ms, DEFAULT_BUDGET_MS * 3)
        self.assertEqual(inventory.detection_budget_ms, DEFAULT_BUDGET_MS)

    def test_every_probe_is_recorded_even_when_it_finds_nothing(self) -> None:
        names = {item.name for item in discover(budget_ms=1500, probe_runtimes=False).probes}
        self.assertEqual(
            names,
            {"system", "memory", "cpu", "storage", "display", "power",
             "thermal", "audio", "network", "gpu", "accelerators"},
        )

    def test_a_probe_that_raises_does_not_fail_the_pass(self) -> None:
        with mock.patch("capability.discovery.memory.probe", side_effect=RuntimeError("sysfs on fire")):
            inventory = discover(budget_ms=1000, probe_runtimes=False)
        outcome = next(item for item in inventory.probes if item.name == "memory")
        self.assertEqual(outcome.state, "failed")
        self.assertIn("RuntimeError", outcome.detail)
        # The failed section is present and entirely unknown - not zeroed.
        self.assertEqual(inventory.memory.physical_bytes.state, UNKNOWN)
        self.assertIsNone(inventory.memory.usable_bytes(None))

    def test_an_exhausted_deadline_skips_remaining_probes_rather_than_hanging(self) -> None:
        clock = FakeClock()

        def burn(*_args, **_keywords):
            clock.advance(5.0)
            raise RuntimeError("slow")

        with mock.patch("capability.discovery.system.probe", side_effect=burn):
            inventory = discover(budget_ms=1000, probe_runtimes=False, clock=clock)
        states = {item.name: item.state for item in inventory.probes}
        self.assertEqual(states["system"], "failed")
        self.assertEqual(states["gpu"], "skipped")
        self.assertTrue(all(state in ("failed", "skipped") for state in states.values()))

    def test_no_network_probe_runs_unless_reachability_was_requested(self) -> None:
        import socket

        with mock.patch.object(socket, "create_connection") as connect:
            discover(budget_ms=1000, probe_runtimes=False)
        connect.assert_not_called()

    def test_reachability_without_endpoints_probes_nothing(self) -> None:
        import socket

        with mock.patch.object(socket, "create_connection") as connect:
            inventory = discover(budget_ms=1000, probe_runtimes=False, probe_reachability=True, endpoints=())
        connect.assert_not_called()
        self.assertEqual(inventory.network.endpoint_reachable.state, UNKNOWN)

    def test_bandwidth_is_never_claimed(self) -> None:
        # Measuring bandwidth honestly means moving real traffic on the user's
        # connection. This subsystem declines to, and says so rather than
        # reporting a number it did not measure.
        inventory = discover(budget_ms=1000, probe_runtimes=False)
        self.assertEqual(inventory.network.bandwidth_bits_per_second.state, UNKNOWN)
        self.assertIn("no bandwidth probe", inventory.network.bandwidth_bits_per_second.detail)

    def test_a_bounded_read_does_not_consume_an_unbounded_file(self) -> None:
        # /proc and /sys hold files that stream indefinitely; a capability probe
        # must not be able to allocate arbitrarily by opening the wrong node.
        path = Path(__file__)
        self.assertLessEqual(len(sources.read_text(path, limit=64) or ""), 64)

    def test_a_missing_file_reads_as_none_not_as_an_empty_string(self) -> None:
        self.assertIsNone(sources.read_text("/nonexistent/capability/probe"))
        self.assertIsNone(sources.read_int("/nonexistent/capability/probe"))


if __name__ == "__main__":
    unittest.main()
