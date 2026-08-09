# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Reading the names in one of the user's own folders, and nothing else.

The assistant is asked "what is in my Downloads folder" more naturally than
almost anything else, and answering it needs a tool that reads a directory. This
is that tool, kept as small as a tool that touches personal files can be:

**It takes a key, not a path.** The argument is one of the XDG directory names
in :data:`companion.intents.FOLDERS` — ``DOWNLOAD``, ``DOCUMENTS`` and five
others. There is no argument that can express ``/etc`` or ``../..``, so there is
no traversal to defend against; the closed vocabulary *is* the defence.

**It reads names, not contents.** A file name is already personal, which is why
the declaration carries the ``personal`` ceiling and why the runtime will refuse
to hand this tool data classified above it. Contents are a different question
with a different answer and this tool cannot be asked it.

**It is bounded.** A folder with forty thousand files produces a sentence, not
forty thousand names, because the caller is a speech bubble on a desktop.

The tool declares no ``interrupts_user`` and no destination, so the runtime's
approval logic does not require consent for it — which is the intended
classification: listing your own folder in your own session is the "low risk"
end of the ladder, next to opening an installed application. Deleting or moving
one of those files is a different act, is not implemented, and would arrive with
its own declaration and its own approval class.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from .tools import ToolDeclaration, ToolOutcome

__all__ = ["LIST_DIRECTORY", "LOCAL_FILE_TOOLS", "list_directory"]

#: How many names are named before the answer summarises instead. Chosen for a
#: speech bubble: beyond this the list stops being an answer and becomes a wall.
NAME_LIMIT = 12


def list_directory(arguments: Mapping[str, Any]) -> ToolOutcome:
    """The names in one XDG user directory.

    The key is validated against the intent tables rather than trusted, so a
    plan that named ``ETC`` — which no recogniser can produce — is refused here
    too rather than relying on the recogniser being the only caller.
    """
    from .intents import FOLDERS
    from .local_intent import user_directory

    key = str(arguments.get("directory", ""))
    if key not in set(FOLDERS.values()):
        return ToolOutcome(
            "files.list_directory", False,
            detail=f"{key!r} is not one of the user directories this tool can read",
        )

    path = user_directory(key)
    if path is None:
        return ToolOutcome(
            "files.list_directory", False,
            detail="that folder does not exist on this machine",
        )

    try:
        entries = sorted(
            (item for item in path.iterdir() if not item.name.startswith(".")),
            key=lambda item: (not item.is_dir(), item.name.lower()),
        )
    except OSError as exc:
        return ToolOutcome(
            "files.list_directory", False, detail=f"the folder could not be read: {exc.strerror}",
        )

    if not entries:
        return ToolOutcome(
            "files.list_directory", True,
            value=f"Your {path.name} folder is empty.",
            detail="0 entries",
        )

    shown = entries[:NAME_LIMIT]
    names = ", ".join(
        f"{item.name}/" if item.is_dir() else item.name for item in shown
    )
    remainder = len(entries) - len(shown)
    sentence = (
        f"Your {path.name} folder has {len(entries)} "
        f"item{'' if len(entries) == 1 else 's'}: {names}"
    )
    if remainder > 0:
        sentence += f", and {remainder} more"
    return ToolOutcome(
        "files.list_directory", True, value=sentence + ".", detail=f"{len(entries)} entries",
    )


LIST_DIRECTORY = ToolDeclaration(
    "files.list_directory",
    "List the names of the files in one of the user's own folders",
    # Names of a person's files are personal. Declared so the runtime refuses to
    # hand this tool anything classified above it rather than discovering the
    # mismatch after the fact.
    maximum_classification="personal",
)

#: Merged into the broker's allowlist by the service. A build that does not
#: merge it has a plan naming an unknown tool refused at the door, which is the
#: same failure shape as any other undeclared tool.
LOCAL_FILE_TOOLS: Mapping[str, tuple[ToolDeclaration, Callable[[Mapping[str, Any]], ToolOutcome]]] = {
    "files.list_directory": (LIST_DIRECTORY, list_directory),
}
