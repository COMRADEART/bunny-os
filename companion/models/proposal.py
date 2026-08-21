# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Where a model's output stops being text and starts being a request — and
where it is made to leave its opinions about permission at the door.

    MODEL OUTPUT IS NOT AUTHORITY

That is the rule this milestone exists to hold, and this module is the one
place it is enforced for adapter-produced proposals. Everything downstream —
``ToolBroker``, :data:`companion.capsule_tasks.OPERATIONS`, ``TrustGate``, the
user, the capsule — is unchanged and untouched by the model bridge. This is a
gate *in front of* that path, not a new way around it.

Three properties, in the order they matter:

**The admitted type cannot represent authority.** :class:`AdmittedProposal` has
three fields and none of them is a permission, a grant, a capability, a trust
level or an approval. This is not a convention the code follows; it is a shape
that cannot hold the thing. A caller downstream that wanted to read
``proposal.approved`` would not compile.

**An attempt to claim authority is refused, not sanitised.** A proposal
carrying ``approved: true``, ``capability: "filesystem.write"`` or
``trusted: true`` does not get those keys quietly dropped — it is refused with
:data:`AUTHORITY_CLAIMED` and the keys are named. Stripping would be safe and
silent; refusing is safe and *loud*, and the difference is whether anyone ever
finds out that a model has started doing this.

**The operation is a lookup, never a string that becomes a command.** A
proposal names one of the entries in the closed table, or it is refused. There
is no path by which ``{"action": "delete_file", "path": "/important/file"}``
becomes an argv: ``delete_file`` is not in the table, so it is refused at
:data:`UNKNOWN_OPERATION` before anything else about the proposal is read.

What this module does *not* do is decide whether an admitted proposal may run.
It produces an intent. Whether that intent is permitted is the trust layer's
answer, given by asking the person — and an admitted proposal that the user
declines is a proposal that does not run, which
``tests/model_bridge/test_denied_action.py`` proves against the real gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..capsule_tasks import OPERATIONS, CapsuleTaskFailure, operation

__all__ = [
    "AUTHORITY_CLAIMED",
    "AUTHORITY_KEYS",
    "AdmittedProposal",
    "MALFORMED_PROPOSAL",
    "PARAMETERS_REFUSED",
    "ProposalRefusal",
    "UNKNOWN_OPERATION",
    "admit_proposal",
]

UNKNOWN_OPERATION = "UNKNOWN_OPERATION"
AUTHORITY_CLAIMED = "AUTHORITY_CLAIMED"
MALFORMED_PROPOSAL = "MALFORMED_PROPOSAL"
PARAMETERS_REFUSED = "PARAMETERS_REFUSED"

#: Words a proposal may not use as a key, anywhere in it. The list is
#: deliberately wide: these are not parameters any operation in the table has,
#: so nothing legitimate is lost by refusing them, and the cost of missing one
#: is a model discovering a field name that gets read somewhere.
#:
#: Matching is on the *normalised* key — lowercased, with separators removed —
#: so ``is_approved``, ``isApproved`` and ``IS-APPROVED`` are the same attempt.
AUTHORITY_KEYS: frozenset[str] = frozenset({
    "approved", "approval", "approve", "approvals", "preapproved", "autoapprove",
    "permission", "permissions", "permitted", "permit",
    "capability", "capabilities", "cap", "caps",
    "trusted", "trust", "trustlevel", "trustedby",
    "granted", "grant", "grants", "granting",
    "authorized", "authorised", "authorization", "authorisation", "authority",
    "allow", "allowed", "allowlist", "deny", "denied",
    "bypass", "override", "escalate", "elevate", "elevated", "privileged",
    "privilege", "privileges", "sudo", "root", "admin", "asroot", "runas",
    "consent", "consented", "policy", "policies", "sandbox", "unsandboxed",
    "confirm", "confirmed", "skipconfirmation", "skipapproval", "noprompt",
    "isapproved", "istrusted", "hasapproval", "haspermission",
})

#: The two key names a proposal may use to name its operation. Two rather than
#: one because models emit both, and a proposal that cannot even be read as a
#: proposal gets refused as malformed rather than as an unknown operation —
#: which sends a reader to the wrong problem.
_OPERATION_KEYS = ("operation", "action")

#: Keys that are structural rather than parameters.
_STRUCTURAL_KEYS = frozenset({"operation", "action", "operationId", "parameters", "arguments", "args"})

_MAX_KEYS = 32
_MAX_KEY_LENGTH = 64


def _normalise(key: str) -> str:
    return "".join(character for character in key.lower() if character.isalnum())


@dataclass(frozen=True)
class ProposalRefusal:
    """Why a proposal is not becoming an intent."""

    code: str
    message: str
    #: The offending keys, when the refusal is about keys.
    keys: tuple[str, ...] = ()

    @property
    def admitted(self) -> bool:
        return False

    def to_json(self) -> dict[str, Any]:
        return {"admitted": False, "code": self.code, "message": self.message,
                "keys": list(self.keys)}


@dataclass(frozen=True)
class AdmittedProposal:
    """A model's suggestion, reduced to something that cannot claim anything.

    Three fields. There is deliberately no ``approved``, no ``permissions``, no
    ``capability`` and no ``trusted``: the authority to act does not travel with
    a proposal, and a type that could carry it is a type somebody would
    eventually read.
    """

    operation_id: str
    parameters: Mapping[str, Any]
    #: What the model said, in its own words, for the record. Never parsed.
    source: str = "model"

    @property
    def admitted(self) -> bool:
        return True

    def to_json(self) -> dict[str, Any]:
        return {
            "admitted": True,
            "operationId": self.operation_id,
            "parameters": dict(self.parameters),
            "source": self.source,
        }


def _authority_keys_in(document: Any, *, depth: int = 0) -> tuple[str, ...]:
    """Every authority-shaped key anywhere in the proposal, at any depth."""
    if depth > 4 or not isinstance(document, Mapping):
        return ()
    found: list[str] = []
    for key, value in document.items():
        if isinstance(key, str) and _normalise(key) in AUTHORITY_KEYS:
            found.append(key)
        found.extend(_authority_keys_in(value, depth=depth + 1))
    return tuple(sorted(set(found)))


def admit_proposal(raw: Any, *, source: str = "model") -> AdmittedProposal | ProposalRefusal:
    """Turn a model's proposal into an intent, or refuse it with a reason.

    Never raises for a bad proposal. A model producing nonsense is an ordinary
    event — that is what a small fine-tuned model does — and the caller needs a
    reason to show, not a traceback.
    """
    if not isinstance(raw, Mapping):
        return ProposalRefusal(
            MALFORMED_PROPOSAL,
            f"a proposal is an object, not {type(raw).__name__}",
        )
    if len(raw) > _MAX_KEYS:
        return ProposalRefusal(
            MALFORMED_PROPOSAL, f"a proposal has at most {_MAX_KEYS} keys; this has {len(raw)}"
        )
    for key in raw:
        if not isinstance(key, str) or len(key) > _MAX_KEY_LENGTH:
            return ProposalRefusal(MALFORMED_PROPOSAL, "a proposal's keys are short strings")

    # Authority first, before anything is read for meaning. A proposal that
    # tried to grant itself something is refused whether or not the rest of it
    # would have been valid.
    claimed = _authority_keys_in(raw)
    if claimed:
        return ProposalRefusal(
            AUTHORITY_CLAIMED,
            "the proposal carries "
            + ", ".join(repr(key) for key in claimed)
            + ". A model proposes; it does not approve, permit, grant or trust. "
            "Authority comes from Bunny's policy, the capability system and the "
            "person at the keyboard, and a proposal that tried to supply it is "
            "refused rather than cleaned up and run.",
            keys=claimed,
        )

    operation_id = ""
    for key in _OPERATION_KEYS:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            operation_id = value.strip()
            break
    if not operation_id:
        return ProposalRefusal(
            MALFORMED_PROPOSAL,
            f"the proposal names no operation (expected one of {_OPERATION_KEYS})",
        )

    if operation_id not in OPERATIONS:
        return ProposalRefusal(
            UNKNOWN_OPERATION,
            f"{operation_id!r} is not an operation Bunny performs. The operations are "
            f"a closed table ({', '.join(sorted(OPERATIONS))}); a model may suggest "
            "which one applies and cannot add one.",
        )

    parameters = raw.get("parameters")
    if parameters is None:
        parameters = raw.get("arguments")
    if parameters is None:
        parameters = raw.get("args")
    if parameters is None:
        # Flat form: the parameters are the proposal's other keys.
        parameters = {
            key: value for key, value in raw.items() if key not in _STRUCTURAL_KEYS
        }
    if not isinstance(parameters, Mapping):
        return ProposalRefusal(
            MALFORMED_PROPOSAL, f"parameters are an object, not {type(parameters).__name__}"
        )

    try:
        validated = operation(operation_id).validate(parameters)
    except CapsuleTaskFailure as failure:
        return ProposalRefusal(
            PARAMETERS_REFUSED,
            f"{operation_id}: {failure}",
        )

    return AdmittedProposal(
        operation_id=operation_id,
        parameters=validated,
        source=source,
    )
