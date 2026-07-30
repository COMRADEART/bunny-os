from __future__ import annotations

from datetime import datetime, timezone
import os
import unittest
from unittest import mock

from tests.support import request as build_request

from bunny_system_broker import auth as auth_module
from bunny_system_broker import protocol, server
from bunny_system_broker.auth import (
    AuthenticationError,
    PeerIdentity,
    require_local_user,
    require_policy_identity,
)

POLICY_UID = 471
USER_UID = 1000
POLICY_UNIT = "bunny-policy-agent.service"


def peer(uid: int, pid: int = 4242) -> PeerIdentity:
    return PeerIdentity(pid=pid, uid=uid, gid=uid, start_time=99)


def policy_request(method: str = "policy.update.channel.set", **params: object) -> dict:
    payload = build_request(method, params or {"policyId": "POL-0001", "version": 1})
    return payload


class MethodTableSeparationTests(unittest.TestCase):
    def test_policy_operations_match_the_policy_agent_definition(self) -> None:
        from enterprise.policy import TYPED_OPERATIONS

        self.assertEqual(
            tuple(sorted(protocol.POLICY_OPERATIONS)),
            tuple(sorted(TYPED_OPERATIONS)),
            "the broker's duplicated operation list has drifted from enterprise/policy.py",
        )

    def test_the_two_tables_share_only_cancellation(self) -> None:
        overlap = set(protocol.METHODS) & set(protocol.POLICY_METHODS)
        self.assertEqual(overlap, {"request.cancel"})

    def test_policy_agent_cannot_reach_user_operations(self) -> None:
        for method in ("power.reboot", "update.install", "logs.export", "rollback.select"):
            with self.subTest(method=method):
                with self.assertRaises(protocol.ProtocolError) as error:
                    protocol.validate_request(
                        build_request(method), methods=protocol.POLICY_METHODS
                    )
                self.assertEqual(error.exception.code, "unknown_method")

    def test_desktop_client_cannot_reach_policy_operations(self) -> None:
        for method in protocol.POLICY_OPERATIONS:
            with self.subTest(method=method):
                with self.assertRaises(protocol.ProtocolError) as error:
                    protocol.validate_request(build_request(method, {"policyId": "POL-0001", "version": 1}))
                self.assertEqual(error.exception.code, "unknown_method")

    def test_every_policy_operation_validates(self) -> None:
        for method in protocol.POLICY_OPERATIONS:
            with self.subTest(method=method):
                parsed = protocol.validate_request(
                    policy_request(method), methods=protocol.POLICY_METHODS
                )
                self.assertEqual(parsed.params, {"policyId": "POL-0001", "version": 1})
                self.assertTrue(parsed.spec.mutating)

    def test_policy_request_cannot_carry_a_desired_state(self) -> None:
        payload = build_request(
            "policy.update.channel.set",
            {"policyId": "POL-0001", "version": 1, "desiredState": "developer"},
        )
        with self.assertRaises(protocol.ProtocolError) as error:
            protocol.validate_request(payload, methods=protocol.POLICY_METHODS)
        self.assertEqual(error.exception.code, "invalid_params")

    def test_policy_request_rejects_a_malformed_identifier(self) -> None:
        for bad in ("POL-1", "pol-0001", "../etc/passwd", ""):
            with self.subTest(value=bad):
                with self.assertRaises(protocol.ProtocolError):
                    protocol.validate_request(
                        policy_request(policyId=bad, version=1), methods=protocol.POLICY_METHODS
                    )

    def test_policy_request_rejects_a_non_integer_version(self) -> None:
        for bad in (0, -1, True, "2", 2.0):
            with self.subTest(value=bad):
                with self.assertRaises(protocol.ProtocolError):
                    protocol.validate_request(
                        policy_request(policyId="POL-0001", version=bad),
                        methods=protocol.POLICY_METHODS,
                    )

    def test_no_policy_operation_declares_a_polkit_action(self) -> None:
        # A headless agent has no session, so polkit cannot apply. Authorization
        # is peer uid plus systemd unit instead.
        for name, spec in protocol.POLICY_METHODS.items():
            with self.subTest(method=name):
                self.assertIsNone(spec.polkit_action)


class PolicyIdentityTests(unittest.TestCase):
    def test_policy_service_identity_is_accepted(self) -> None:
        with mock.patch.object(auth_module, "proc_unit", return_value=POLICY_UNIT):
            require_policy_identity(peer(POLICY_UID), expected_uid=POLICY_UID, expected_unit=POLICY_UNIT)

    def test_interactive_user_is_refused_on_the_policy_socket(self) -> None:
        with self.assertRaises(AuthenticationError):
            require_policy_identity(peer(USER_UID), expected_uid=POLICY_UID, expected_unit=POLICY_UNIT)

    def test_root_is_refused_on_the_policy_socket_when_it_is_not_the_service_account(self) -> None:
        with self.assertRaises(AuthenticationError):
            require_policy_identity(peer(0), expected_uid=POLICY_UID, expected_unit=POLICY_UNIT)

    def test_wrong_unit_is_refused_even_with_the_right_uid(self) -> None:
        with mock.patch.object(auth_module, "proc_unit", return_value="attacker.service"):
            with self.assertRaises(AuthenticationError) as error:
                require_policy_identity(
                    peer(POLICY_UID), expected_uid=POLICY_UID, expected_unit=POLICY_UNIT
                )
        self.assertIn("policy agent unit", str(error.exception))

    def test_the_user_socket_still_refuses_system_identities(self) -> None:
        # The regression that require_policy_identity must never introduce.
        for uid in (0, 1, POLICY_UID, 999):
            with self.subTest(uid=uid):
                if uid == 0:
                    require_local_user(peer(uid))
                    continue
                with self.assertRaises(AuthenticationError):
                    require_local_user(peer(uid))

    def test_the_user_socket_rule_is_a_separate_function(self) -> None:
        # A shared function with a mode flag is one bug away from opening the
        # user socket; assert they remain distinct callables.
        self.assertIsNot(require_local_user, require_policy_identity)


class ProcUnitTests(unittest.TestCase):
    def test_cgroup_v2_line_is_parsed(self) -> None:
        content = "0::/system.slice/bunny-policy-agent.service\n"
        with mock.patch("builtins.open", mock.mock_open(read_data=content)):
            self.assertEqual(auth_module.proc_unit(1), "bunny-policy-agent.service")

    def test_nested_scope_is_parsed(self) -> None:
        content = "0::/user.slice/user-1000.slice/session-3.scope\n"
        with mock.patch("builtins.open", mock.mock_open(read_data=content)):
            self.assertEqual(auth_module.proc_unit(1), "session-3.scope")

    def test_process_without_a_unit_is_refused(self) -> None:
        with mock.patch("builtins.open", mock.mock_open(read_data="0::/\n")):
            with self.assertRaises(AuthenticationError):
                auth_module.proc_unit(1)

    def test_missing_process_is_refused(self) -> None:
        with mock.patch("builtins.open", side_effect=OSError):
            with self.assertRaises(AuthenticationError):
                auth_module.proc_unit(1)


class InheritedListenerTests(unittest.TestCase):
    def environment(self, **values: str) -> dict[str, str]:
        base = {"LISTEN_PID": str(os.getpid())}
        base.update(values)
        return base

    def test_no_inherited_sockets_returns_empty(self) -> None:
        with mock.patch.dict(os.environ, {"LISTEN_FDS": "0"}, clear=False):
            self.assertEqual(server._inherited_listeners(), {})

    def test_foreign_listen_pid_is_ignored(self) -> None:
        with mock.patch.dict(os.environ, {"LISTEN_FDS": "1", "LISTEN_PID": "1"}, clear=False):
            self.assertEqual(server._inherited_listeners(), {})

    def test_more_than_two_sockets_is_refused(self) -> None:
        with mock.patch.dict(os.environ, self.environment(LISTEN_FDS="3"), clear=False):
            with self.assertRaises(RuntimeError):
                server._inherited_listeners()

    def test_unnamed_pair_is_refused(self) -> None:
        with mock.patch.dict(os.environ, self.environment(LISTEN_FDS="2", LISTEN_FDNAMES=""), clear=False):
            with self.assertRaises(RuntimeError) as error:
                server._inherited_listeners()
        self.assertIn("LISTEN_FDNAMES", str(error.exception))

    def test_unknown_socket_name_is_refused(self) -> None:
        environment = self.environment(LISTEN_FDS="1", LISTEN_FDNAMES="attacker.sock")
        with mock.patch.dict(os.environ, environment, clear=False):
            with self.assertRaises(RuntimeError):
                server._inherited_listeners()

    def test_duplicate_socket_name_is_refused(self) -> None:
        environment = self.environment(LISTEN_FDS="2", LISTEN_FDNAMES="policy.sock:policy.sock")
        with mock.patch.dict(os.environ, environment, clear=False):
            with self.assertRaises(RuntimeError):
                server._inherited_listeners()


class ServerWiringTests(unittest.TestCase):
    def test_default_server_uses_the_user_table_and_rule(self) -> None:
        instance = server.BrokerServer.__new__(server.BrokerServer)
        # Inspect defaults without binding a socket.
        import inspect

        signature = inspect.signature(server.BrokerServer.__init__)
        self.assertIs(signature.parameters["authenticate"].default, require_local_user)
        self.assertIsNone(signature.parameters["methods"].default)
        self.assertEqual(signature.parameters["name"].default, "broker")
        del instance

    def test_policy_socket_is_off_unless_requested(self) -> None:
        from pathlib import Path

        text = Path(server.__file__).read_text(encoding="utf-8")
        self.assertIn('"--policy-socket"', text)
        self.assertIn("default=None", text)


if __name__ == "__main__":
    unittest.main()
