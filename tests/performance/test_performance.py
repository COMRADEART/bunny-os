from __future__ import annotations

import time
import unittest

from bunny_shell.launcher import route_intent


class PerformanceHarnessTests(unittest.TestCase):
    def test_deterministic_intent_router_has_bounded_host_latency(self) -> None:
        start = time.perf_counter()
        for _ in range(1000):
            route_intent("Open network settings")
        self.assertLess(time.perf_counter() - start, 2.0)


if __name__ == "__main__":
    unittest.main()
