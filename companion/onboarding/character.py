# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the character preview page has to say before it draws anything.

The preview is the first-run step where a person finds out whether their machine
gets the 3D bunny, and it is the step most likely to lie. Drawing a 3D character
in a preview on a machine that will fall back to 2D at login is a promise the
product then breaks; drawing 2D on a machine that could do 3D undersells it.

So the page is built from the *decision*, not from a render: the same
:mod:`companion.character.policy` call that the session will make, run in dry
mode, plus the thumbnail of whatever package that decision names. If the two
ever disagree it is because something changed between first run and login, and
the reason string says which.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = ["CharacterSurvey", "survey_character"]


@dataclass(frozen=True)
class CharacterSurvey:
    """The package a fresh login would use, and how it was chosen."""

    package_id: str = ""
    package_name: str = ""
    rung: str = "text-only"
    eligible_rung: str = "text-only"
    thumbnail_path: str = ""
    #: The text that stands in for the picture. Present in every case,
    #: including the ones where a picture is present, because §26 says no
    #: essential information may exist only in an image.
    description: str = "Bunny, your local-first companion."
    preserved_user_choice: bool = False
    reasons: tuple[str, ...] = ()
    error: str = ""

    @property
    def draws_character(self) -> bool:
        return bool(self.package_id)

    @property
    def summary(self) -> str:
        if self.error:
            return f"The character could not be prepared: {self.error}"
        if self.preserved_user_choice:
            return f"Bunny will use {self.package_id}, the character you chose."
        if not self.draws_character:
            return (
                "This machine will use the text-only presentation. Everything Bunny does is "
                "still available in words."
            )
        rung = {
            "full-3d": "in full 3D",
            "lightweight-3d": "in lightweight 3D",
            "animated-2d": "as an animated 2D character",
            "static-image": "as a still picture",
        }.get(self.rung, self.rung)
        line = f"Bunny will appear {rung}."
        if self.rung != self.eligible_rung:
            line += " Your machine would permit more, but the higher package is not usable here."
        return line

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "packageId": self.package_id,
            "packageName": self.package_name,
            "rung": self.rung,
            "eligibleRung": self.eligible_rung,
            "thumbnailPath": self.thumbnail_path,
            "description": self.description,
            "drawsCharacter": self.draws_character,
            "preservedUserChoice": self.preserved_user_choice,
            "summary": self.summary,
            "reasons": list(self.reasons),
            "error": self.error,
        }


def survey_character(registry: Any, *, eligible: str = "full-3d") -> CharacterSurvey:
    """Run the default-character policy in dry mode and describe the outcome."""
    from ..character.policy import apply_default_character_policy

    try:
        decision = apply_default_character_policy(registry, eligible=eligible, dry_run=True)
    except Exception as error:  # pragma: no cover - onboarding must not crash
        return CharacterSurvey(eligible_rung=eligible, error=str(error))
    if decision.error:
        return CharacterSurvey(
            eligible_rung=decision.eligible_rung, reasons=decision.reasons, error=decision.error,
        )
    package_id = decision.selected_package_id if decision.preserved_user_choice else decision.package_id
    name, thumbnail, description = _describe(registry, package_id)
    return CharacterSurvey(
        package_id=package_id,
        package_name=name,
        rung=decision.rung,
        eligible_rung=decision.eligible_rung,
        thumbnail_path=thumbnail,
        description=description,
        preserved_user_choice=decision.preserved_user_choice,
        reasons=decision.reasons,
    )


def _describe(registry: Any, package_id: str) -> tuple[str, str, str]:
    """Name, thumbnail path and alternative text for a package, best effort."""
    if not package_id:
        return "", "", "Bunny has no picture on this machine; everything appears as text."
    try:
        from ..character.package import PackageTrustState, validate_package_directory

        records = registry.inspect(package_id)
    except Exception:
        return package_id, "", "Bunny, your local-first companion."
    for record in records:
        try:
            package = validate_package_directory(
                record.path,
                trust_state=(
                    PackageTrustState.BUILT_IN
                    if record.trust_state is PackageTrustState.BUILT_IN
                    else PackageTrustState.VERIFIED_INTEGRITY
                ),
                validate_model=False,
            )
        except Exception:
            continue
        manifest = package.manifest
        thumbnail = ""
        asset_id = str(getattr(manifest, "thumbnail_asset", "") or "")
        if asset_id:
            try:
                thumbnail = str(package.asset_path(asset_id))
            except Exception:
                thumbnail = ""
        if not thumbnail:
            fallback = str(getattr(manifest, "fallback_asset", "") or "")
            if fallback:
                try:
                    thumbnail = str(package.asset_path(fallback))
                except Exception:
                    thumbnail = ""
        return (
            str(getattr(manifest, "character_name", "") or package_id),
            thumbnail if thumbnail and Path(thumbnail).is_file() else "",
            f"{getattr(manifest, 'character_name', 'Bunny')}, your local-first companion.",
        )
    return package_id, "", "Bunny, your local-first companion."
