# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The remote-execution state machine, and the boundary data may not cross."""

from __future__ import annotations

import unittest

from capability.apply.remote import (
    EGRESS_STATE,
    REMOTE_STATES,
    RemoteDispatchGuard,
    RemoteStateError,
    RemoteTask,
    RemoteTaskLedger,
    ProviderIdentity,
    TestProvider,
    idempotency_token,
    new_task,
)
from capability.policy import Policy, RemoteExecutionPolicy


def permissive(**overrides) -> Policy:
    fields = {
        "enabled": True, "require_user_approval": False,
        "allow_sensitive_data": False, "permitted_providers": ("test-provider",),
    }
    fields.update(overrides)
    return Policy(remote_execution=RemoteExecutionPolicy(**fields))


def provider(**overrides) -> ProviderIdentity:
    fields = {
        "provider_id": "test-provider", "authenticated": True,
        "capabilities": ("inference",), "retention": "ephemeral",
        "trains_on_input": False, "maximum_privacy_class": "internal",
    }
    fields.update(overrides)
    return ProviderIdentity(**fields)


def queued(policy: Policy, **overrides) -> RemoteTask:
    task = new_task(
        task_id="task-1", plan_id="plan-1", transition_id="t-1",
        service_id="bunny.inference.local", capability="inference",
        now=0.0, policy=policy, **overrides,
    )
    if task.state == "awaiting_provider":
        task = task.move("queued", now=1.0)
    return task


class InitialStateTests(unittest.TestCase):
    def test_remote_execution_off_produces_a_task_that_can_never_dispatch(self) -> None:
        # ``not_permitted`` has no outgoing transitions, so no sequence of calls
        # walks such a task to dispatching.
        task = new_task(
            task_id="t", plan_id="p", transition_id="x", service_id="s.one",
            capability="inference", policy=Policy(),
        )
        self.assertEqual(task.state, "not_permitted")
        with self.assertRaises(RemoteStateError):
            task.move("queued", now=1.0)

    def test_approval_required_produces_a_task_awaiting_approval(self) -> None:
        task = new_task(
            task_id="t", plan_id="p", transition_id="x", service_id="s.one",
            capability="inference", policy=permissive(require_user_approval=True),
        )
        self.assertEqual(task.state, "awaiting_approval")

    def test_every_state_is_reachable_in_the_vocabulary(self) -> None:
        self.assertEqual(len(set(REMOTE_STATES)), len(REMOTE_STATES))
        self.assertIn(EGRESS_STATE, REMOTE_STATES)


class StateMachineTests(unittest.TestCase):
    def test_an_illegal_transition_is_refused(self) -> None:
        task = queued(permissive())
        with self.assertRaises(RemoteStateError):
            task.move("completed", now=2.0)

    def test_a_completed_task_cannot_be_resurrected(self) -> None:
        task = queued(permissive())
        task = task.move("dispatching", now=2.0).move("active", now=3.0)
        task = task.move("completing", now=4.0).move("completed", now=5.0)
        for target in ("active", "queued", "dispatching"):
            with self.subTest(target=target):
                with self.assertRaises(RemoteStateError):
                    task.move(target, now=6.0)

    def test_history_records_every_state(self) -> None:
        task = queued(permissive()).move("dispatching", now=2.0).move("active", now=3.0)
        self.assertEqual(
            [state for _, state, _ in task.history],
            ["awaiting_provider", "queued", "dispatching", "active"],
        )

    def test_a_lost_task_must_be_reconciled_before_anything_else(self) -> None:
        task = queued(permissive()).move("dispatching", now=2.0).move("lost", now=3.0)
        self.assertEqual(task.move("reconciliation_required", now=4.0).state, "reconciliation_required")
        with self.assertRaises(RemoteStateError):
            task.move("completed", now=4.0)

    def test_lost_is_distinct_from_failed(self) -> None:
        # A failed task may be retried; a lost one must first be reconciled, or
        # the same work runs twice on somebody's bill.
        self.assertIn("lost", REMOTE_STATES)
        self.assertIn("failed", REMOTE_STATES)


class EgressTests(unittest.TestCase):
    """Nothing leaves the machine unless every precondition holds at once."""

    def test_a_fully_permitted_task_dispatches(self) -> None:
        guard = RemoteDispatchGuard(permissive(), provider(), approved=True)
        task = guard.dispatch(queued(permissive()), now=2.0)
        self.assertEqual(task.state, EGRESS_STATE)
        self.assertEqual(task.provider_id, "test-provider")
        self.assertEqual(task.attempt, 1)

    def test_remote_execution_disabled_blocks_dispatch(self) -> None:
        task = queued(permissive())
        guard = RemoteDispatchGuard(Policy(), provider(), approved=True)
        result = guard.dispatch(task, now=2.0)
        self.assertEqual(result.state, "not_permitted")
        self.assertFalse(result.data_has_left)

    def test_a_secret_task_never_leaves(self) -> None:
        task = queued(permissive(), data_classification="secret")
        guard = RemoteDispatchGuard(permissive(), provider(), approved=True)
        refusals = guard.refusals(task)
        self.assertTrue(any("never leaves the device" in item for item in refusals))
        self.assertFalse(guard.dispatch(task, now=2.0).data_has_left)

    def test_sensitive_data_stays_local_unless_policy_permits_it(self) -> None:
        task = queued(permissive(), data_classification="sensitive")
        guard = RemoteDispatchGuard(permissive(), provider(), approved=True)
        self.assertTrue(any("allowSensitiveData" in item for item in guard.refusals(task)))

    def test_an_unauthenticated_provider_is_refused(self) -> None:
        guard = RemoteDispatchGuard(permissive(), provider(authenticated=False), approved=True)
        self.assertTrue(any("not authenticated" in item for item in guard.refusals(queued(permissive()))))

    def test_an_undeclared_provider_fails_closed(self) -> None:
        guard = RemoteDispatchGuard(
            permissive(), provider(retention="unspecified", trains_on_input=None), approved=True,
        )
        self.assertTrue(any("fails closed" in item for item in guard.refusals(queued(permissive()))))

    def test_a_provider_outside_the_allowlist_is_refused(self) -> None:
        guard = RemoteDispatchGuard(
            permissive(permitted_providers=("other",)), provider(), approved=True,
        )
        self.assertTrue(any("permittedProviders" in item for item in guard.refusals(queued(permissive()))))

    def test_a_provider_that_does_not_serve_the_capability_is_refused(self) -> None:
        guard = RemoteDispatchGuard(permissive(), provider(capabilities=("tts",)), approved=True)
        self.assertTrue(any("does not serve" in item for item in guard.refusals(queued(permissive()))))

    def test_a_provider_may_not_receive_above_its_declared_privacy_class(self) -> None:
        policy = permissive(allow_sensitive_data=True)
        task = queued(policy, data_classification="sensitive")
        guard = RemoteDispatchGuard(
            policy, provider(maximum_privacy_class="public"), approved=True,
        )
        self.assertTrue(any("may receive at most" in item for item in guard.refusals(task)))

    def test_a_missing_approval_blocks_dispatch(self) -> None:
        policy = permissive(require_user_approval=True)
        task = new_task(
            task_id="t", plan_id="p", transition_id="x", service_id="s.one",
            capability="inference", policy=policy,
        )
        guard = RemoteDispatchGuard(policy, provider(), approved=False)
        self.assertTrue(any("no approval has been given" in item for item in guard.refusals(task)))
        self.assertFalse(guard.dispatch(task, now=1.0).data_has_left)

    def test_no_network_blocks_dispatch(self) -> None:
        guard = RemoteDispatchGuard(permissive(), provider(), approved=True, network_online=False)
        self.assertTrue(any("no route" in item for item in guard.refusals(queued(permissive()))))

    def test_a_task_without_an_idempotency_token_is_refused(self) -> None:
        from dataclasses import replace

        task = replace(queued(permissive()), idempotency_token="")
        guard = RemoteDispatchGuard(permissive(), provider(), approved=True)
        self.assertTrue(any("idempotency token" in item for item in guard.refusals(task)))

    def test_retries_are_bounded(self) -> None:
        from dataclasses import replace

        task = replace(queued(permissive()), attempt=2, maximum_attempts=2)
        guard = RemoteDispatchGuard(permissive(), provider(), approved=True)
        self.assertTrue(any("attempt limit" in item for item in guard.refusals(task)))


class DataEgressAccountingTests(unittest.TestCase):
    def test_a_task_that_reached_dispatching_is_recorded_as_having_sent_data(self) -> None:
        # A user asking "did my document leave this machine" must not be told no
        # because the request errored afterwards.
        guard = RemoteDispatchGuard(permissive(), provider(), approved=True)
        task = guard.dispatch(queued(permissive()), now=2.0)
        failed = task.move("failed", now=3.0)
        self.assertTrue(failed.data_has_left)

    def test_a_task_that_never_dispatched_has_sent_nothing(self) -> None:
        self.assertFalse(queued(permissive()).data_has_left)

    def test_the_ledger_counts_tasks_that_sent_data(self) -> None:
        ledger = RemoteTaskLedger()
        guard = RemoteDispatchGuard(permissive(), provider(), approved=True)
        ledger.add(queued(permissive()))
        ledger.update(guard.dispatch(ledger.tasks["task-1"], now=2.0))
        self.assertEqual(ledger.data_egress_count(), 1)

    def test_the_ledger_lists_tasks_needing_reconciliation(self) -> None:
        ledger = RemoteTaskLedger()
        guard = RemoteDispatchGuard(permissive(), provider(), approved=True)
        task = guard.dispatch(queued(permissive()), now=2.0).move("lost", now=3.0)
        ledger.add(task)
        self.assertEqual([item.task_id for item in ledger.needing_reconciliation()], ["task-1"])


class IdempotencyTests(unittest.TestCase):
    def test_the_token_is_derived_and_stable(self) -> None:
        # A crash between dispatching and recording it must recompute the same
        # token, or the user is billed twice.
        first = idempotency_token("plan-1", "t-1", "task-1")
        second = idempotency_token("plan-1", "t-1", "task-1")
        self.assertEqual(first, second)

    def test_different_work_produces_different_tokens(self) -> None:
        self.assertNotEqual(
            idempotency_token("plan-1", "t-1", "task-1"),
            idempotency_token("plan-1", "t-1", "task-2"),
        )

    def test_a_new_task_carries_a_token(self) -> None:
        self.assertTrue(queued(permissive()).idempotency_token)


class TestProviderTests(unittest.TestCase):
    def test_the_test_provider_records_submissions_and_sends_nothing(self) -> None:
        transport = TestProvider(identity=provider())
        task = queued(permissive())
        handle = transport.submit(task)
        self.assertIn(task.idempotency_token, handle)
        self.assertEqual(transport.submitted, [(task.task_id, task.idempotency_token)])

    def test_cancellation_is_recorded(self) -> None:
        transport = TestProvider(identity=provider())
        self.assertTrue(transport.cancel("handle-1"))
        self.assertEqual(transport.cancelled, ["handle-1"])


class NoCredentialTests(unittest.TestCase):
    def test_a_remote_task_has_nowhere_to_put_a_credential(self) -> None:
        # The only reliable way to guarantee a key is never logged.
        fields = set(RemoteTask.__dataclass_fields__)
        for forbidden in ("api_key", "token", "secret", "credential", "password", "authorization"):
            with self.subTest(field=forbidden):
                self.assertNotIn(forbidden, fields)

    def test_a_provider_identity_has_nowhere_to_put_a_credential(self) -> None:
        fields = set(ProviderIdentity.__dataclass_fields__)
        for forbidden in ("api_key", "token", "secret", "credential", "password"):
            with self.subTest(field=forbidden):
                self.assertNotIn(forbidden, fields)

    def test_the_serialized_task_carries_no_secret_field(self) -> None:
        document = str(queued(permissive()).to_json()).lower()
        for forbidden in ("apikey", "secret", "password", "authorization"):
            with self.subTest(field=forbidden):
                self.assertNotIn(forbidden, document)


if __name__ == "__main__":
    unittest.main()
