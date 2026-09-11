# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Alpha CODE lock: remote_dispatch is not cloud_context.

``cloud_context=none`` must not silently veto an already-granted
``remote_dispatch`` current-request hop. The same hop must still refuse
summary / durable / memory payloads as a whole, not strip them into a leak.

Characterization of ``authorize_remote_generate`` on main after PR #48.
Does not claim Memory Core PR #50, a guest boot, or a live online generate.
"""

from __future__ import annotations

import inspect
import unittest

from companion.memory_boundary import (
    MemoryPolicy,
    authorize_cloud_context,
    authorize_remote_generate,
)

_CURRENT_REQUEST = {
    "user_request": "count the words",
    "instruction": "Write the final answer.",
    "system_policy_reference": "bunny-agent-policy/1",
    "classification": "internal",
    "task_id": "task-1",
    "purpose": "result",
}

_NONE = MemoryPolicy(cloud_context="none")


def _generate(payload: dict[str, object], *, granted: bool = True) -> object:
    return authorize_remote_generate(
        payload,
        classification="internal",
        remote_transfer_ceiling="internal",
        remote_dispatch_granted=granted,
        policy=_NONE,
    )


class RemoteDispatchVsCloudContextNone(unittest.TestCase):
    def test_granted_current_request_is_allowed_when_cloud_context_is_none(self) -> None:
        decision = _generate(dict(_CURRENT_REQUEST))
        self.assertTrue(decision.allowed)
        self.assertIsNotNone(decision.released)
        released = dict(decision.released or {})
        self.assertEqual(released.get("user_request"), "count the words")
        self.assertNotIn("summary_text", released)
        self.assertNotIn("memory_records", released)
        self.assertNotIn("durable", released)

    def test_cloud_context_none_still_refuses_the_same_payload_on_the_memory_gate(self) -> None:
        """The two consents are not the same function."""
        memory = authorize_cloud_context(
            dict(_CURRENT_REQUEST),
            classification="internal",
            policy=_NONE,
            remote_transfer_ceiling="internal",
            allowed_fields=("user_request",),
        )
        hop = _generate(dict(_CURRENT_REQUEST))
        self.assertFalse(memory.allowed)
        self.assertTrue(hop.allowed)

    def test_summary_text_refuses_the_whole_payload(self) -> None:
        decision = _generate({**_CURRENT_REQUEST, "summary_text": "yesterday we talked about secrets"})
        self.assertFalse(decision.allowed)
        self.assertIsNone(decision.released)
        self.assertIn("summary", decision.reason)

    def test_conversation_summary_refuses_the_whole_payload(self) -> None:
        decision = _generate({**_CURRENT_REQUEST, "conversation-summary": "a stored recap"})
        self.assertFalse(decision.allowed)
        self.assertIsNone(decision.released)

    def test_memory_records_refuses_the_whole_payload(self) -> None:
        decision = _generate({**_CURRENT_REQUEST, "memory_records": [{"body": "life story"}]})
        self.assertFalse(decision.allowed)
        self.assertIsNone(decision.released)
        self.assertIn("memory_records", decision.reason)

    def test_durable_refuses_the_whole_payload(self) -> None:
        decision = _generate({**_CURRENT_REQUEST, "durable": {"body": "life story"}})
        self.assertFalse(decision.allowed)
        self.assertIsNone(decision.released)

    def test_ungranted_remote_dispatch_is_refused_even_for_current_request(self) -> None:
        decision = _generate(dict(_CURRENT_REQUEST), granted=False)
        self.assertFalse(decision.allowed)
        self.assertIsNone(decision.released)
        self.assertIn("remote_dispatch", decision.reason)

    def test_security_cosign_hook_records_the_alpha_accept(self) -> None:
        source = inspect.getsource(authorize_remote_generate)
        self.assertIn("SECURITY CO-SIGN HOOK", source)
        self.assertIn("ACCEPTED for Alpha at CODE", source)
        self.assertIn("MUST NOT silently block", source)
        self.assertIn("Do not reverse this `pass` into a refuse", source)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
