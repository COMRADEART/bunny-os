# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which character a machine starts with, and why it never changes by itself.

The 3D renderer branch shipped two built-in packages and left the 2D one first
in :func:`companion.character.defaults.default_character_paths`, so every machine
drew 2D whatever its graphics were. That was the right call *then* — promoting
3D inside a renderer branch would have changed what existing machines drew as a
side effect of adding a renderer — and it is the wrong default for a product
somebody downloads, where the bundled 3D Bunny is the thing the screenshots show.

Public Alpha replaces the fixed order with a decision, and the decision is
bounded by four rules that together make it a *default-selection policy* rather
than an automatic package change:

**A user's choice outranks the policy, permanently.** The policy records the
digest it selected. On the next run it will only replace a selection that is
either absent or exactly the one it made itself. A selection it did not make is
a person's decision and the policy does not have an opinion about it — not on
the next boot, not after a hardware change, not in recovery.

**Presentation is not selection.** A machine whose GPU stops working draws the
selected character with a lower renderer. It does not become a different
character. The degradation ladder in :mod:`companion.character.adaptation` owns
presentation; this module owns *which package*, and the two never write to each
other's state. That separation is what makes §34's renderer-failure story
survivable: 3D fails, 2D draws, and when 3D comes back the same package is still
selected.

**A package that will not validate is not eligible.** "full-3d eligible" is two
independent facts — the machine can render it, *and* the bundled package passes
the validator — and the policy requires both. A machine that would happily run
3D and a 3D package that fails validation is a machine that gets 2D, with the
validator's message as the reason.

**Recovery restores, it does not choose.** :func:`restore_selected_package`
re-selects what the user picked when capability permits it again. It is the only
function here that can move a selection the policy did not make, it moves it
*back* rather than somewhere new, and it refuses when the package no longer
validates.

The policy state lives in its own file rather than in the character registry.
The registry's schema is validated strictly and its ``selectedDigest`` is the
answer to "what is selected"; adding "and who selected it" there would make
every reader of that file a reader of this policy. One file, one question.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence

from .adaptation import Presentation
from .defaults import default_3d_character_path, default_character_path
from .errors import CharacterError
from .package import PackageTrustState, validate_package_directory

__all__ = [
    "POLICY_FILE_NAME",
    "POLICY_LADDER",
    "DefaultCharacterDecision",
    "PolicyState",
    "apply_default_character_policy",
    "default_character_decision",
    "read_policy_state",
    "restore_selected_package",
]

#: Where the policy's own record lives, beside the character registry.
POLICY_FILE_NAME = "default-character-policy.json"

_STATE_SCHEMA_VERSION = 1

#: The §3 ladder, top first. Each rung names which *bundle* to look for, not a
#: package id: the ids belong to the manifests and reading them from there is
#: the only way the two cannot disagree. They have already disagreed once — the
#: 2D package calls itself ``org.bunny-os.default-bunny`` and the 3D one calls
#: itself ``bunny-default-3d``, so a hard-coded pair would have selected one and
#: failed on the other.
#:
#: The text-only rung names no bundle. It draws no character at all, and
#: pointing it at the 2D package would draw one anyway.
POLICY_LADDER: tuple[tuple[Presentation, str], ...] = (
    (Presentation.FULL_3D, "three-d"),
    (Presentation.LIGHTWEIGHT_3D, "three-d"),
    (Presentation.ANIMATED_2D, "two-d"),
    (Presentation.STATIC_IMAGE, "two-d"),
    (Presentation.TEXT_ONLY, ""),
)

_RANK = {
    Presentation.TEXT_ONLY: 0,
    Presentation.STATIC_IMAGE: 1,
    Presentation.ANIMATED_2D: 2,
    Presentation.LIGHTWEIGHT_3D: 3,
    Presentation.FULL_3D: 4,
}

#: What a recommendation's ``eligible`` string means as a rung. The canonical
#: vocabulary has ``audio-only``, which draws nothing, so it lands on text.
_ELIGIBLE_TO_RUNG: Mapping[str, Presentation] = {
    "text-only": Presentation.TEXT_ONLY,
    "audio-only": Presentation.TEXT_ONLY,
    "static-avatar": Presentation.STATIC_IMAGE,
    "static-image": Presentation.STATIC_IMAGE,
    "animated-2d": Presentation.ANIMATED_2D,
    "lightweight-3d": Presentation.LIGHTWEIGHT_3D,
    "full-3d": Presentation.FULL_3D,
}


@dataclass(frozen=True)
class PolicyState:
    """What the policy did last time, so it can tell its own work apart.

    ``applied_digest`` is the load-bearing field. Absent means the policy has
    never selected anything here and any recorded selection is the user's.
    """

    applied_digest: str = ""
    applied_package_id: str = ""
    applied_rung: str = ""
    #: The last selection the *user* made, recorded when the policy notices one
    #: it did not make. §3's recovery rule needs to know what to restore to, and
    #: reading it off the registry at recovery time is too late — by then the
    #: registry may hold a fallback.
    user_digest: str = ""
    user_package_id: str = ""

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "PolicyState":
        def text(key: str) -> str:
            item = value.get(key, "")
            return item if isinstance(item, str) and len(item) <= 256 else ""

        return cls(
            applied_digest=text("appliedDigest"),
            applied_package_id=text("appliedPackageId"),
            applied_rung=text("appliedRung"),
            user_digest=text("userDigest"),
            user_package_id=text("userPackageId"),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": _STATE_SCHEMA_VERSION,
            "appliedDigest": self.applied_digest,
            "appliedPackageId": self.applied_package_id,
            "appliedRung": self.applied_rung,
            "userDigest": self.user_digest,
            "userPackageId": self.user_package_id,
        }


@dataclass(frozen=True)
class DefaultCharacterDecision:
    """What the policy decided, whether it acted, and every reason it had."""

    #: The package the ladder chose. Empty for the text-only rung, where the
    #: right answer is "draw no character" rather than "draw this one smaller".
    package_id: str = ""
    #: The rung the machine reached, as a presentation name.
    rung: str = "text-only"
    #: The rung the ladder *stopped* at, which differs from ``rung`` when a
    #: package failed to validate and the ladder had to descend past it.
    eligible_rung: str = "text-only"
    #: ``True`` when the policy **changed** the recorded selection. Never true
    #: for a dry run: a caller asking "what would you do" and being told
    #: ``applied: true`` would reasonably conclude something had happened.
    applied: bool = False
    #: ``True`` when the policy would change the selection if allowed to act.
    #: Equal to :attr:`applied` outside a dry run, and the field a preview
    #: surface reads.
    would_apply: bool = False
    #: ``True`` when a selection existed that the policy did not make. The
    #: single most important output: it means the policy deliberately did
    #: nothing.
    preserved_user_choice: bool = False
    selected_package_id: str = ""
    reasons: tuple[str, ...] = ()
    error: str = ""

    @property
    def summary(self) -> str:
        if self.error:
            return f"The default character policy did not run: {self.error}"
        if self.preserved_user_choice:
            return (
                f"You chose {self.selected_package_id}, so that is what Bunny uses. "
                "The default-character policy does not override a choice you made."
            )
        if self.applied:
            return f"Bunny is using the bundled {self.package_id} character ({self.rung})."
        if not self.package_id:
            return "This machine draws no character; Bunny uses the text-only presentation."
        return f"Bunny is already using {self.selected_package_id or self.package_id}."

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "packageId": self.package_id,
            "rung": self.rung,
            "eligibleRung": self.eligible_rung,
            "applied": self.applied,
            "wouldApply": self.would_apply,
            "preservedUserChoice": self.preserved_user_choice,
            "selectedPackageId": self.selected_package_id,
            "summary": self.summary,
            "reasons": list(self.reasons),
            "error": self.error,
        }


def _policy_path(registry: Any) -> Path:
    return Path(getattr(registry, "root", Path("."))) / POLICY_FILE_NAME


def read_policy_state(registry: Any) -> PolicyState:
    """The policy's record, or an empty one. Never raises on a bad file.

    A corrupt policy file must not stop a machine booting a character. An
    unreadable record is treated as "the policy has never run", which is the
    conservative reading: the *worst* it can cause is the policy declining to
    act because it cannot prove a selection was its own.
    """
    path = _policy_path(registry)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return PolicyState()
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return PolicyState()
    if not isinstance(value, Mapping) or value.get("schemaVersion") != _STATE_SCHEMA_VERSION:
        return PolicyState()
    return PolicyState.from_json(value)


def _write_policy_state(registry: Any, state: PolicyState) -> None:
    path = _policy_path(registry)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state.to_json(), indent=2, sort_keys=True) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=".character-policy-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _bundled_path(bundle: str) -> Path | None:
    if bundle == "three-d":
        return default_3d_character_path()
    if bundle == "two-d":
        return default_character_path()
    return None


def _validates(bundle: str, rung: Presentation) -> tuple[str, str]:
    """``(package_id, detail)``. An empty id means this rung is not usable.

    The 3D rungs validate the model too — ``validate_model`` defaults on — which
    is the expensive half and the half that matters: a GLB that will not load is
    exactly the "default package does not validate" case §3 names.

    The package id comes out of the manifest rather than going in as an
    argument, because the manifest is where it is true.
    """
    path = _bundled_path(bundle)
    if path is None or not path.is_dir():
        return "", f"the bundled {bundle} character package is not installed on this machine"
    try:
        package = validate_package_directory(path, trust_state=PackageTrustState.BUILT_IN)
    except CharacterError as error:
        return "", f"the bundled {bundle} character package did not validate: {error}"
    except OSError as error:
        return "", f"the bundled {bundle} character package could not be read: {error}"
    package_id = str(getattr(package.manifest, "package_id", "") or "")
    declared = str(getattr(package.manifest.presentation_type, "value", ""))
    declared_rung = _ELIGIBLE_TO_RUNG.get(declared)
    if declared_rung is None:
        return "", f"{package_id or bundle} declares presentation {declared!r}, which is not a rung"
    if _RANK[declared_rung] < _RANK[rung]:
        return "", (
            f"{package_id or bundle} declares {declared}, which is below {rung.value}; "
            "the ladder descends rather than claiming a rung the package does not offer"
        )
    return package_id, f"{package_id} validated and declares {declared}"


def default_character_decision(
    *,
    eligible: str,
    registry: Any,
    state: PolicyState | None = None,
    validator: Any = None,
) -> DefaultCharacterDecision:
    """Decide, without writing anything.

    ``eligible`` is the ``eligible`` field of a
    :class:`companion.presentation.PresentationRecommendation` — what the machine
    and the accessibility policy permit. Deliberately not recomputed here: §2 of
    the renderer brief forbids a second reading of capability, and a policy that
    measured the GPU itself would be a third.
    """
    state = read_policy_state(registry) if state is None else state
    check = validator or _validates
    reasons: list[str] = []

    eligible_rung = _ELIGIBLE_TO_RUNG.get(eligible, Presentation.TEXT_ONLY)
    reasons.append(f"the machine and policy permit {eligible_rung.value}")

    try:
        current = registry.selected()
    except Exception as error:
        return DefaultCharacterDecision(
            eligible_rung=eligible_rung.value, error=f"the character registry is unreadable: {error}",
        )
    current_digest = str(getattr(current, "package_digest", "") or "")
    current_id = str(getattr(current, "package_id", "") or "")

    # Descend the ladder from the eligible rung until a bundled package for that
    # rung validates. The descent is the difference between "3D eligible" and
    # "3D usable" and its reasons are kept because they are what a user asking
    # "why am I not seeing the 3D bunny" needs to read.
    chosen_id, chosen_rung = "", Presentation.TEXT_ONLY
    for rung, bundle in POLICY_LADDER:
        if _RANK[rung] > _RANK[eligible_rung]:
            continue
        if not bundle:
            chosen_id, chosen_rung = "", rung
            reasons.append("no bundled package is drawn at the text-only rung")
            break
        package_id, detail = check(bundle, rung)
        reasons.append(detail)
        if package_id:
            chosen_id, chosen_rung = package_id, rung
            break

    # A recorded selection the policy did not make is the user's, and that ends
    # the decision. Checked after the ladder so the reasons still explain what
    # the machine *would* have chosen, which is what the settings page shows
    # beside "you chose otherwise".
    #
    # The question is asked of the *record*, not of ``selected()``: the registry
    # falls back to the first built-in when nothing is recorded, so its return
    # value cannot tell "chosen" from "defaulted", and a fallback that happened
    # to differ from the policy's digest would read as a user decision nobody
    # made.
    recorded = _recorded_digest(registry)
    if recorded and recorded != state.applied_digest:
        reasons.append(
            f"{current_id} is selected and this policy did not select it, so it is preserved"
        )
        return DefaultCharacterDecision(
            package_id=chosen_id, rung=chosen_rung.value, eligible_rung=eligible_rung.value,
            applied=False, preserved_user_choice=True, selected_package_id=current_id,
            reasons=tuple(reasons),
        )

    if not chosen_id:
        return DefaultCharacterDecision(
            package_id="", rung=chosen_rung.value, eligible_rung=eligible_rung.value,
            applied=False, selected_package_id=current_id, reasons=tuple(reasons),
        )

    # The policy raises a selection and never lowers one. §3: "renderer
    # degradation may temporarily change presentation level without changing
    # selected package." A machine whose GPU stops working reports a lower
    # ``eligible``, and a policy that acted on it would swap the 3D package out
    # for the 2D one — permanently, because the swap outlives the outage. The
    # right response to a lost GPU is the degradation ladder drawing the same
    # package at a lower rung, which is exactly what it does.
    previous = _ELIGIBLE_TO_RUNG.get(state.applied_rung) if state.applied_rung else None
    if previous is not None and _RANK[chosen_rung] < _RANK[previous]:
        reasons.append(
            f"this policy previously selected {state.applied_package_id} for {previous.value} and "
            f"only {chosen_rung.value} is available now; the package is kept and the renderer "
            "degrades instead"
        )
        return DefaultCharacterDecision(
            package_id=state.applied_package_id, rung=previous.value,
            eligible_rung=eligible_rung.value, applied=False,
            selected_package_id=current_id, reasons=tuple(reasons),
        )

    if current_id == chosen_id:
        reasons.append(f"{chosen_id} is already selected; nothing to do")
        return DefaultCharacterDecision(
            package_id=chosen_id, rung=chosen_rung.value, eligible_rung=eligible_rung.value,
            applied=False, selected_package_id=current_id, reasons=tuple(reasons),
        )
    return DefaultCharacterDecision(
        package_id=chosen_id, rung=chosen_rung.value, eligible_rung=eligible_rung.value,
        applied=False, would_apply=True, selected_package_id=current_id, reasons=tuple(reasons),
    )


def _recorded_digest(registry: Any) -> str:
    """The registry's ``selectedDigest``, or ``""`` when nothing is recorded.

    ``PackageRegistry.selected()`` falls back to the first built-in when nothing
    is recorded, so its return value cannot distinguish "chosen" from
    "defaulted". This reads the record itself, and an unreadable record answers
    ``""`` — which makes the policy free to act. That is the right direction:
    the alternative reading, "something might be selected so do nothing", leaves
    a machine whose registry is corrupt with no character policy at all.
    """
    path = Path(getattr(registry, "registry_path", ""))
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
        return ""
    if not isinstance(value, Mapping):
        return ""
    digest = value.get("selectedDigest")
    return digest if isinstance(digest, str) else ""


def apply_default_character_policy(
    registry: Any,
    *,
    eligible: str,
    dry_run: bool = False,
    validator: Any = None,
) -> DefaultCharacterDecision:
    """Decide and, unless ``dry_run``, act.

    Acting means two writes that must agree: the registry's selection and the
    policy's record of having made it. The record is written **after** the
    selection succeeds — a record without a selection would make the policy
    believe it owned a choice it had not made, and the next run would overwrite
    a user's selection on that belief.
    """
    state = read_policy_state(registry)
    decision = default_character_decision(eligible=eligible, registry=registry, state=state, validator=validator)
    if decision.preserved_user_choice and not state.user_digest:
        # First sight of a user selection: remember it, so recovery has
        # something to restore to.
        try:
            current = registry.selected()
        except Exception:
            current = None
        if current is not None:
            _write_policy_state(registry, PolicyState(
                applied_digest=state.applied_digest,
                applied_package_id=state.applied_package_id,
                applied_rung=state.applied_rung,
                user_digest=str(getattr(current, "package_digest", "") or ""),
                user_package_id=str(getattr(current, "package_id", "") or ""),
            ))
    if dry_run or not decision.package_id:
        return decision
    if not decision.would_apply:
        # The registry already names the package the ladder chose — because it
        # is the first built-in, not because anyone selected it. Claim it, so
        # the *next* run knows which rung this policy settled on and can refuse
        # to lower it. Without this the claim only exists when the ladder had to
        # change something, and a machine whose fallback happens to match the
        # policy would have no record at all.
        if not decision.preserved_user_choice and not state.applied_digest:
            try:
                current = registry.selected()
            except Exception:
                current = None
            digest = str(getattr(current, "package_digest", "") or "")
            if digest and str(getattr(current, "package_id", "")) == decision.package_id:
                _write_policy_state(registry, PolicyState(
                    applied_digest=digest,
                    applied_package_id=decision.package_id,
                    applied_rung=decision.rung,
                    user_digest=state.user_digest,
                    user_package_id=state.user_package_id,
                ))
        return decision
    try:
        selected = registry.select(decision.package_id)
    except Exception as error:
        return DefaultCharacterDecision(
            package_id=decision.package_id, rung=decision.rung, eligible_rung=decision.eligible_rung,
            applied=False, selected_package_id=decision.selected_package_id,
            reasons=decision.reasons + (f"selection failed: {error}",),
            error=str(error),
        )
    _write_policy_state(registry, PolicyState(
        applied_digest=str(getattr(selected, "package_digest", "") or ""),
        applied_package_id=decision.package_id,
        applied_rung=decision.rung,
        user_digest=state.user_digest,
        user_package_id=state.user_package_id,
    ))
    return DefaultCharacterDecision(
        package_id=decision.package_id, rung=decision.rung, eligible_rung=decision.eligible_rung,
        applied=True, would_apply=True, selected_package_id=decision.package_id,
        reasons=decision.reasons,
    )


def restore_selected_package(registry: Any, *, eligible: str = "full-3d") -> DefaultCharacterDecision:
    """Put the user's chosen package back, when this machine can draw it.

    §3's recovery rule. Called from the recovery surface and from safe-mode exit,
    never on a normal start: a machine that quietly re-selected on every boot
    would be running the policy again, which is the thing the policy is written
    not to do.
    """
    state = read_policy_state(registry)
    if not state.user_package_id:
        return DefaultCharacterDecision(
            eligible_rung=eligible,
            reasons=("no user-selected package is recorded, so there is nothing to restore",),
        )
    eligible_rung = _ELIGIBLE_TO_RUNG.get(eligible, Presentation.TEXT_ONLY)
    try:
        matches = registry.inspect(state.user_package_id)
    except Exception as error:
        return DefaultCharacterDecision(
            eligible_rung=eligible_rung.value,
            error=f"{state.user_package_id} is no longer installed: {error}",
            reasons=(f"{state.user_package_id} is no longer installed",),
        )
    reasons = [f"{state.user_package_id} is installed and was the user's choice"]
    for record in matches:
        try:
            package = validate_package_directory(
                record.path,
                trust_state=(
                    PackageTrustState.BUILT_IN
                    if record.trust_state is PackageTrustState.BUILT_IN
                    else PackageTrustState.VERIFIED_INTEGRITY
                ),
            )
        except (CharacterError, OSError) as error:
            reasons.append(f"a version of {state.user_package_id} did not validate: {error}")
            continue
        declared = _ELIGIBLE_TO_RUNG.get(str(getattr(package.manifest.presentation_type, "value", "")), None)
        if declared is not None and _RANK[declared] > _RANK[eligible_rung]:
            reasons.append(
                f"{state.user_package_id} needs {declared.value} and this machine permits "
                f"{eligible_rung.value}; it is left unselected until capability allows it"
            )
            continue
        try:
            registry.select(state.user_package_id, package_digest=record.package_digest)
        except Exception as error:
            reasons.append(f"selection failed: {error}")
            continue
        reasons.append(f"{state.user_package_id} restored")
        return DefaultCharacterDecision(
            package_id=state.user_package_id,
            rung=(declared or eligible_rung).value,
            eligible_rung=eligible_rung.value,
            applied=True, would_apply=True, preserved_user_choice=True,
            selected_package_id=state.user_package_id, reasons=tuple(reasons),
        )
    return DefaultCharacterDecision(
        package_id=state.user_package_id, eligible_rung=eligible_rung.value,
        applied=False, preserved_user_choice=True,
        selected_package_id=state.user_package_id, reasons=tuple(reasons),
    )
