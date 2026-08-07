# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Bunny humanoid profile: nineteen logical bones and how to find them.

§7 asks for a profile that does not require one exact DCC naming convention, and
the reason is practical rather than aesthetic: Blender's Rigify, Mixamo, VRM and
a hand-built armature all name the same elbow four different ways, and a
renderer that insisted on one of them would accept characters from one tool.

So a logical bone is resolved in three steps, most explicit first:

1. **The manifest's ``boneMap``.** The package author says which node is the
   left elbow. Always wins; nothing below is consulted for a bone it names.
2. **A built-in alias table.** The names the four common conventions actually
   use, compared case-insensitively with separators removed, so ``LeftUpperArm``,
   ``left_upper_arm``, ``mixamorig:LeftArm`` and ``upper_arm.L`` all land on the
   same logical bone.
3. **Nothing.** An unresolved *optional* bone is absent and the features that
   need it degrade (see :mod:`companion.character.three_d.expression`). An
   unresolved *required* bone fails validation, because a humanoid without a
   head is not a humanoid and the renderer would be guessing at where to put the
   speech bubble.

Resolution is a pure function of names. It reads no file, opens no model, and is
therefore table-testable — which is what makes "does this skeleton satisfy the
profile" a question with an answer rather than an opinion.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Mapping, Sequence

from .errors import ModelSchemaError

#: The nineteen §7 requires. Order is hierarchical parent-before-child, which is
#: also the order a report reads best in.
REQUIRED_BONES: tuple[str, ...] = (
    "root",
    "hips",
    "spine",
    "chest",
    "neck",
    "head",
    "left_upper_arm",
    "left_lower_arm",
    "left_hand",
    "right_upper_arm",
    "right_lower_arm",
    "right_hand",
    "left_upper_leg",
    "left_lower_leg",
    "left_foot",
    "right_upper_leg",
    "right_lower_leg",
    "right_foot",
)

#: §7's optional set. Their absence is a *capability* the package does not have,
#: never an error: a character with no jaw bone does lip-sync through morph
#: targets, and one with neither holds a neutral mouth and says so.
OPTIONAL_BONES: tuple[str, ...] = (
    "left_eye",
    "right_eye",
    "jaw",
    "left_shoulder",
    "right_shoulder",
    "left_toes",
    "right_toes",
    "hair_root",
    "accessory_root",
)

#: Finger and toe bones are optional *and* numerous, so they are matched by
#: pattern rather than enumerated: five digits times three joints times two
#: hands is sixty names nobody should maintain by hand.
_DIGIT_PATTERN = re.compile(
    r"^(left|right)_(thumb|index|middle|ring|little|toe)_(1|2|3|proximal|intermediate|distal)$"
)

#: The parent each required bone must ultimately descend from. Checked as
#: *ancestry* rather than immediate parentage: rigs legitimately insert twist
#: bones, roll bones and shoulder pads between an upper arm and a forearm, and
#: refusing those would refuse most real characters.
BONE_ANCESTRY: Mapping[str, str] = {
    "hips": "root",
    "spine": "hips",
    "chest": "spine",
    "neck": "chest",
    "head": "neck",
    "left_upper_arm": "chest",
    "left_lower_arm": "left_upper_arm",
    "left_hand": "left_lower_arm",
    "right_upper_arm": "chest",
    "right_lower_arm": "right_upper_arm",
    "right_hand": "right_lower_arm",
    "left_upper_leg": "hips",
    "left_lower_leg": "left_upper_leg",
    "left_foot": "left_lower_leg",
    "right_upper_leg": "hips",
    "right_lower_leg": "right_upper_leg",
    "right_foot": "right_lower_leg",
    "left_eye": "head",
    "right_eye": "head",
    "jaw": "head",
    "left_shoulder": "chest",
    "right_shoulder": "chest",
    "left_toes": "left_foot",
    "right_toes": "right_foot",
}

#: Aliases, normalised. The key is the logical bone; the values are alternative
#: *normalised* names (see :func:`normalise_bone_name`). Written as the raw
#: spellings for readability and normalised once at import.
_RAW_ALIASES: Mapping[str, tuple[str, ...]] = {
    "root": ("root", "armature", "rig", "skeleton", "reference", "root_bone"),
    "hips": ("hips", "pelvis", "hip", "mixamorig:Hips", "J_Bip_C_Hips", "torso"),
    "spine": ("spine", "spine_01", "spine1", "abdomen", "mixamorig:Spine", "J_Bip_C_Spine"),
    "chest": ("chest", "spine_02", "spine2", "upperchest", "upper_chest", "mixamorig:Spine1", "J_Bip_C_Chest", "torso_upper"),
    "neck": ("neck", "neck_01", "mixamorig:Neck", "J_Bip_C_Neck"),
    "head": ("head", "head_01", "mixamorig:Head", "J_Bip_C_Head"),
    "left_shoulder": ("leftshoulder", "shoulder.L", "clavicle_l", "mixamorig:LeftShoulder", "J_Bip_L_Shoulder"),
    "right_shoulder": ("rightshoulder", "shoulder.R", "clavicle_r", "mixamorig:RightShoulder", "J_Bip_R_Shoulder"),
    "left_upper_arm": ("leftupperarm", "upper_arm.L", "upperarm_l", "leftarm", "arm.L", "mixamorig:LeftArm", "J_Bip_L_UpperArm"),
    "left_lower_arm": ("leftlowerarm", "forearm.L", "lowerarm_l", "leftforearm", "mixamorig:LeftForeArm", "J_Bip_L_LowerArm"),
    "left_hand": ("lefthand", "hand.L", "hand_l", "mixamorig:LeftHand", "J_Bip_L_Hand"),
    "right_upper_arm": ("rightupperarm", "upper_arm.R", "upperarm_r", "rightarm", "arm.R", "mixamorig:RightArm", "J_Bip_R_UpperArm"),
    "right_lower_arm": ("rightlowerarm", "forearm.R", "lowerarm_r", "rightforearm", "mixamorig:RightForeArm", "J_Bip_R_LowerArm"),
    "right_hand": ("righthand", "hand.R", "hand_r", "mixamorig:RightHand", "J_Bip_R_Hand"),
    "left_upper_leg": ("leftupperleg", "thigh.L", "thigh_l", "leftupleg", "mixamorig:LeftUpLeg", "J_Bip_L_UpperLeg"),
    "left_lower_leg": ("leftlowerleg", "shin.L", "calf_l", "leftleg", "mixamorig:LeftLeg", "J_Bip_L_LowerLeg"),
    "left_foot": ("leftfoot", "foot.L", "foot_l", "mixamorig:LeftFoot", "J_Bip_L_Foot"),
    "right_upper_leg": ("rightupperleg", "thigh.R", "thigh_r", "rightupleg", "mixamorig:RightUpLeg", "J_Bip_R_UpperLeg"),
    "right_lower_leg": ("rightlowerleg", "shin.R", "calf_r", "rightleg", "mixamorig:RightLeg", "J_Bip_R_LowerLeg"),
    "right_foot": ("rightfoot", "foot.R", "foot_r", "mixamorig:RightFoot", "J_Bip_R_Foot"),
    "left_eye": ("lefteye", "eye.L", "eye_l", "mixamorig:LeftEye", "J_Adj_L_FaceEye"),
    "right_eye": ("righteye", "eye.R", "eye_r", "mixamorig:RightEye", "J_Adj_R_FaceEye"),
    "jaw": ("jaw", "jaw_01", "chin", "J_Bip_C_Jaw", "mouth"),
    "left_toes": ("lefttoes", "toe.L", "ball_l", "lefttoebase", "mixamorig:LeftToeBase", "J_Bip_L_ToeBase"),
    "right_toes": ("righttoes", "toe.R", "ball_r", "righttoebase", "mixamorig:RightToeBase", "J_Bip_R_ToeBase"),
    "hair_root": ("hairroot", "hair", "hair_01", "J_Sec_Hair1"),
    "accessory_root": ("accessoryroot", "accessory", "prop", "attachment"),
}

_SEPARATORS = re.compile(r"[\s._:\-]+")


def normalise_bone_name(name: str) -> str:
    """Fold the four conventions onto one comparable string.

    ``mixamorig:LeftForeArm``, ``forearm.L`` and ``Left Lower Arm`` differ only
    in separators, case and a vendor prefix. The one thing that is *not* folded
    away is left/right: ``.L`` and ``.R`` suffixes are rewritten to a ``left``/
    ``right`` prefix so a side never disappears into a separator strip.
    """
    text = str(name).strip()
    if ":" in text:
        text = text.split(":", 1)[1]
    side = ""
    lowered = text.casefold()
    for suffix, mapped in ((".l", "left"), ("_l", "left"), (".r", "right"), ("_r", "right")):
        if lowered.endswith(suffix):
            side = mapped
            text = text[: -len(suffix)]
            break
    folded = _SEPARATORS.sub("", text).casefold()
    return f"{side}{folded}" if side else folded


_ALIASES: dict[str, str] = {}
for _logical, _spellings in _RAW_ALIASES.items():
    for _spelling in _spellings:
        _ALIASES.setdefault(normalise_bone_name(_spelling), _logical)
    _ALIASES.setdefault(normalise_bone_name(_logical), _logical)


@dataclass(frozen=True)
class SkeletonProfile:
    """One resolved skeleton: logical bone -> node index, plus what is absent."""

    profile_id: str
    bones: Mapping[str, int]
    optional_present: tuple[str, ...]
    digits: Mapping[str, int]
    unmapped_nodes: tuple[str, ...]
    resolution: Mapping[str, str]

    def index(self, logical: str) -> int | None:
        return self.bones.get(logical)

    def has(self, logical: str) -> bool:
        return logical in self.bones

    def to_json(self) -> dict[str, object]:
        return {
            "profileId": self.profile_id,
            "bones": dict(sorted(self.bones.items())),
            "requiredPresent": sorted(name for name in self.bones if name in REQUIRED_BONES),
            "optionalPresent": list(self.optional_present),
            "digitCount": len(self.digits),
            "unmappedNodeCount": len(self.unmapped_nodes),
            "resolution": dict(sorted(self.resolution.items())),
        }


def resolve_skeleton(
    joint_names: Sequence[str],
    joint_indices: Sequence[int],
    *,
    bone_map: Mapping[str, str] | None = None,
    profile_id: str = "bunny-humanoid-1",
) -> SkeletonProfile:
    """Map the joints of a skin onto the profile. Raises if a required bone is absent.

    ``joint_names`` and ``joint_indices`` are parallel: the name of each joint
    and the node index it refers to. They come from the validated model, so
    every index in the result is one the renderer already proved exists.
    """
    if len(joint_names) != len(joint_indices):
        raise ModelSchemaError("skeleton joint names and indices disagree in length")
    by_normalised: dict[str, int] = {}
    for name, index in zip(joint_names, joint_indices):
        by_normalised.setdefault(normalise_bone_name(name), index)
    by_exact = {str(name): index for name, index in zip(joint_names, joint_indices)}

    bones: dict[str, int] = {}
    resolution: dict[str, str] = {}
    claimed: set[int] = set()

    for logical, declared in (bone_map or {}).items():
        logical_name = str(logical)
        if logical_name not in REQUIRED_BONES and logical_name not in OPTIONAL_BONES:
            if _DIGIT_PATTERN.fullmatch(logical_name) is None:
                raise ModelSchemaError(f"boneMap names an unknown logical bone: {logical_name}")
        index = by_exact.get(str(declared))
        if index is None:
            index = by_normalised.get(normalise_bone_name(str(declared)))
        if index is None:
            raise ModelSchemaError(
                f"boneMap points {logical_name} at {declared!r}, which is not a joint of the skin"
            )
        bones[logical_name] = index
        resolution[logical_name] = "manifest"
        claimed.add(index)

    for normalised, index in by_normalised.items():
        logical = _ALIASES.get(normalised)
        if logical is None or logical in bones:
            continue
        bones[logical] = index
        resolution[logical] = "alias"
        claimed.add(index)

    digits: dict[str, int] = {}
    for name, index in zip(joint_names, joint_indices):
        normalised = normalise_bone_name(name)
        for logical in (normalised,):
            match = _DIGIT_PATTERN.fullmatch(str(name).casefold().replace(".", "_").replace("-", "_"))
            if match is not None:
                digits.setdefault(str(name), index)
                claimed.add(index)
    for logical, index in list(bones.items()):
        if _DIGIT_PATTERN.fullmatch(logical) is not None:
            digits[logical] = index

    missing = [name for name in REQUIRED_BONES if name not in bones]
    if missing:
        raise ModelSchemaError(
            "skeleton does not satisfy the Bunny humanoid profile; missing: " + ", ".join(missing)
        )

    unmapped = tuple(
        str(name) for name, index in zip(joint_names, joint_indices) if index not in claimed
    )
    optional_present = tuple(name for name in OPTIONAL_BONES if name in bones)
    return SkeletonProfile(
        profile_id=profile_id,
        bones=dict(bones),
        optional_present=optional_present,
        digits=dict(digits),
        unmapped_nodes=unmapped,
        resolution=resolution,
    )


def ancestry_violations(
    profile: SkeletonProfile, parent_of: Mapping[int, int | None]
) -> tuple[str, ...]:
    """Which profile bones do not descend from the bone the profile says they do.

    Ancestry rather than parentage, and *reported* rather than raised: a rig with
    a twist bone between the forearm and the hand is correct, and one whose left
    hand descends from the right forearm is a mislabelled export that will
    animate visibly wrongly. The caller decides which of those it is looking at;
    validation refuses only the second kind, by name, so the message can say so.
    """
    problems: list[str] = []
    for logical, expected_parent in BONE_ANCESTRY.items():
        child = profile.index(logical)
        ancestor = profile.index(expected_parent)
        if child is None or ancestor is None:
            continue
        seen: set[int] = set()
        current: int | None = parent_of.get(child)
        while current is not None and current not in seen:
            if current == ancestor:
                break
            seen.add(current)
            current = parent_of.get(current)
        else:
            problems.append(f"{logical} does not descend from {expected_parent}")
            continue
        if current is None:
            problems.append(f"{logical} does not descend from {expected_parent}")
    return tuple(problems)


def digit_bones(names: Iterable[str]) -> tuple[str, ...]:
    """Which of ``names`` are finger or toe bones by the profile's pattern."""
    return tuple(
        name for name in names
        if _DIGIT_PATTERN.fullmatch(str(name).casefold().replace(".", "_").replace("-", "_"))
    )


__all__ = [
    "BONE_ANCESTRY",
    "OPTIONAL_BONES",
    "REQUIRED_BONES",
    "SkeletonProfile",
    "ancestry_violations",
    "digit_bones",
    "normalise_bone_name",
    "resolve_skeleton",
]
