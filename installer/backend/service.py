# SPDX-License-Identifier: GPL-3.0-or-later
"""Authenticated, allowlisted local installer protocol service.

The reference executor is deliberately simulation-only.  A production live
image must inject the reviewed Anaconda adapter; otherwise install.start fails
closed before the first write boundary.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import secrets
from typing import Any, Callable, Mapping

from installer.plans.validation import validate_plan
from installer.protocol import InstallerRequest, parse_request
from installer.storage.models import DiskInfo
from installer.storage.safety import assert_confirmed

from .audit import record
from .state import InstallationState


class AuthenticationError(PermissionError):
    pass


class BackendUnavailable(RuntimeError):
    pass


class InstallerService:
    def __init__(
        self,
        *,
        live_uid: int,
        probe: Callable[[], list[DiskInfo]],
        production_adapter: object | None = None,
    ) -> None:
        if live_uid < 1000:
            raise ValueError("the installer frontend must use a non-system user")
        self.live_uid = live_uid
        self._session_token = secrets.token_urlsafe(32)
        self._probe = probe
        self._adapter = production_adapter
        self._nonces: deque[str] = deque(maxlen=1024)
        self._disks: list[DiskInfo] = []
        self._plan: Mapping[str, Any] | None = None
        self._state = InstallationState()
        self._logs: list[dict[str, Any]] = []

    def issue_session_token(self, *, peer_uid: int) -> str:
        if peer_uid not in {0, self.live_uid}:
            raise AuthenticationError("cross-session token request")
        return self._session_token

    def _authenticate(self, request: InstallerRequest, *, peer_uid: int, session_token: str) -> None:
        if peer_uid != self.live_uid:
            raise AuthenticationError("request is not from the live installer user")
        if not secrets.compare_digest(session_token, self._session_token):
            raise AuthenticationError("invalid installer session")
        if request.nonce in self._nonces:
            raise AuthenticationError("replayed installer request")
        self._nonces.append(request.nonce)

    def _log(self, request: InstallerRequest, result: str, detail: object | None = None) -> None:
        target = None
        if self._plan and isinstance(self._plan.get("targetDisk"), Mapping):
            target = str(self._plan["targetDisk"].get("id"))
        self._logs.append(
            record(
                stage=self._state.stage,
                operation_id=request.request_id,
                correlation_id=request.installation_id,
                target_reference=target,
                result=result,
                detail=detail,
            )
        )

    def handle(
        self,
        payload: Mapping[str, Any],
        *,
        peer_uid: int,
        session_token: str,
        now: datetime | None = None,
        secret_values: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        request = parse_request(payload, now=now or datetime.now(timezone.utc))
        self._authenticate(request, peer_uid=peer_uid, session_token=session_token)
        try:
            result = self._dispatch(request, secret_values or {})
        except Exception as error:
            self._log(request, "denied" if isinstance(error, (ValueError, AuthenticationError, BackendUnavailable)) else "failed", {"errorType": type(error).__name__})
            raise
        self._log(request, "ok")
        return {"schemaVersion": 1, "requestId": request.request_id, "operation": request.operation, "result": result}

    def _dispatch(self, request: InstallerRequest,
                  secret_values: Mapping[str, str] | None = None) -> object:
        secret_values = secret_values or {}
        operation = request.operation
        if operation == "installer.initialize":
            return {"protocolVersion": 1, "backend": "anaconda-adapter" if self._adapter else "simulation-only", "destructiveExecutionAvailable": self._adapter is not None}
        if operation == "installer.probe":
            self._disks = self._probe()
            self._state.status = "probed"
            return {"disks": [disk.to_dict() for disk in self._disks]}
        if operation in {"installer.plan.validate", "installer.plan.preview"}:
            plan = request.params.get("plan")
            if not isinstance(plan, Mapping):
                raise ValueError("plan must be an object")
            errors = validate_plan(plan, self._disks)
            if errors:
                return {"valid": False, "errors": list(errors), "writesPerformed": False}
            self._plan = plan
            self._state.status = "planned"
            result: dict[str, object] = {"valid": True, "errors": [], "writesPerformed": False}
            if operation.endswith("preview"):
                result["operations"] = list(plan.get("partitions", []))
                result["rollbackAfterWrite"] = False
            return result
        if operation == "installer.install.start":
            if self._plan is None:
                raise ValueError("a validated plan is required")
            target = self._plan.get("targetDisk")
            selected = next((disk for disk in self._disks if isinstance(target, Mapping) and disk.id == target.get("id")), None)
            if selected is None:
                raise ValueError("the validated target disk is no longer present")
            if self._plan.get("mode") in {"erase_disk", "oem"}:
                assert_confirmed(
                    selected,
                    acknowledgement=str(request.params.get("acknowledgement", "")),
                    second_confirmation=request.params.get("secondConfirmation") is True,
                )
            encryption = self._plan.get("encryption")
            if isinstance(encryption, Mapping) and encryption.get("enabled") and request.params.get("recoveryKeyConfirmed") is not True:
                raise ValueError("encrypted installation requires recovery-key confirmation")
            if self._adapter is None:
                raise BackendUnavailable("destructive executor is unavailable; no disk writes were performed")
            # The per-installation half of the adapter, completed only now:
            # the account and locale ride the validated plan, and the secret
            # material arrived beside this request over the descriptor channel
            # — the JSON protocol itself refuses to carry it. Nothing here
            # logs, stores, or echoes a resolved value.
            user_plan = self._plan.get("user")
            reference = user_plan.get("passwordSecretRef") if isinstance(user_plan, Mapping) else None
            password = secret_values.get(str(reference or ""))
            if password is None:
                raise ValueError("the account password did not arrive over the protected channel")
            passphrase = None
            if isinstance(encryption, Mapping) and encryption.get("enabled"):
                passphrase_reference = str(request.params.get("passphraseSecretRef", ""))
                passphrase = secret_values.get(passphrase_reference)
                if passphrase is None:
                    raise ValueError("the encryption passphrase did not arrive over the protected channel")
            if hasattr(self._adapter, "configure_installation"):
                from installer.backend.kickstart import crypt_password

                locale_plan = self._plan.get("locale")
                network_plan = self._plan.get("network")
                self._adapter.configure_installation(  # type: ignore[attr-defined]
                    choices={
                        "locale": dict(locale_plan) if isinstance(locale_plan, Mapping) else {},
                        "account": {
                            "username": str(user_plan.get("username", "")),
                            "displayName": str(user_plan.get("displayName", "")),
                            "deviceName": str(network_plan.get("hostname", ""))
                            if isinstance(network_plan, Mapping) else "",
                        },
                    },
                    password_hash=crypt_password(password),
                    passphrase=passphrase,
                    on_stage=self._observe_stage,
                )
            self._state.start()
            try:
                self._adapter.start(plan=self._plan, confirmations=dict(request.params))  # type: ignore[attr-defined]
            except Exception:
                self._state.fail("adapter-start-failed")
                raise
            else:
                # The executor returning without an exception is the
                # completion evidence; an executor whose stage reports fell
                # short of the ladder still finished the walk it reported.
                while self._state.status == "installing":
                    self._state.advance("finished")
            return self._state.public()
        if operation == "installer.install.status":
            return self._state.public()
        if operation == "installer.install.cancel":
            self._state.cancel()
            return self._state.public()
        if operation == "installer.install.logs":
            return {"entries": list(self._logs[-500:]), "redacted": True}
        if operation == "installer.install.verify":
            return {"verified": self._state.status == "complete", "status": self._state.public()}
        if operation == "installer.recovery.prepare":
            if self._state.status != "complete":
                raise ValueError("recovery preparation requires a completed installation")
            return {"prepared": False, "reason": "production adapter must verify recovery deployment"}
        raise ValueError("operation is not implemented")

    def _observe_stage(self, stage: str, detail: str) -> None:
        """One executor stage report advances the ladder by one rung."""
        try:
            self._state.advance(f"{stage}: {detail}"[:256])
        except ValueError:
            # The ladder is finite and the executor's report count is its own;
            # a report past the top changes nothing.
            pass
