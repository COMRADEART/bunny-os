# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What a sentence is asking for, as a closed set of possibilities.

Everything the desktop can be asked to *do* is in this file, and the shape of
it is the point: recognition returns one of a fixed number of intents carrying
already-validated constants, and it can return nothing. There is no branch that
takes a fragment of what the user typed and turns it into a thing to run.

That is not a stylistic preference. The runtime already has the machinery to
launch an application, open a settings panel and reveal a folder — nine bounded
actions with approval classes, privacy ceilings and adapters. The one way to
make that machinery dangerous is to let the words a person typed choose the
argument, so here the words choose a *key* and the key selects a constant that
was written in this source file. ``"open files"`` cannot become
``application_id="anything-you-like"`` because the recognised intent has no
field the sentence can reach.

## Why a table and not a model

This is the executor that runs on a machine with no provider configured and no
network — which is every machine this has been booted on. It is deterministic,
which is what lets "the same request produces the same plan" be a test rather
than an aspiration.

It is deliberately not clever. It recognises a small number of phrasings for a
small number of acts, and when it does not recognise something it says so and
lists what it can do. An intent recogniser that guessed would be worse than one
that declines, because the failure of a guess is an action nobody asked for.

When a provider *is* configured, the capability layer selects it instead and a
model plans the work; this file is not in that path. What both paths share is
the far end: a planned operation naming a declared tool with structured
arguments, which is the only way anything reaches a desktop adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Mapping

__all__ = [
    "APPLICATIONS",
    "FOLDERS",
    "Intent",
    "KNOWN_INTENTS",
    "capability_sentence",
    "recognise",
]


#: The applications an intent may name, and the desktop id each one means.
#:
#: The keys are what a person says; the values are what the machine is asked
#: for. Both halves are written here, which is what makes the mapping auditable
#: — and the value is still validated against the installed application
#: registry downstream by :func:`companion.desktop.entries.valid_application_id`
#: and by the adapter, because a desktop id in this table is a claim about what
#: the id *is*, not a claim that this machine has it.
APPLICATIONS: Mapping[str, tuple[str, ...]] = {
    # spoken form -> candidate desktop ids, most preferred first
    "files": ("org.gnome.Nautilus.desktop",),
    "file manager": ("org.gnome.Nautilus.desktop",),
    "nautilus": ("org.gnome.Nautilus.desktop",),
    "terminal": ("org.gnome.Terminal.desktop", "org.gnome.Console.desktop"),
    "console": ("org.gnome.Console.desktop", "org.gnome.Terminal.desktop"),
    "settings": ("org.gnome.Settings.desktop", "gnome-control-center.desktop"),
    "system settings": ("org.gnome.Settings.desktop", "gnome-control-center.desktop"),
    "text editor": ("org.gnome.TextEditor.desktop",),
    "browser": ("firefox.desktop", "org.mozilla.firefox.desktop"),
    "firefox": ("firefox.desktop", "org.mozilla.firefox.desktop"),
    "web browser": ("firefox.desktop", "org.mozilla.firefox.desktop"),
    "software": ("org.gnome.Software.desktop",),
    "calculator": ("org.gnome.Calculator.desktop",),
}

#: The folders an intent may name, as XDG user-directory keys.
#:
#: Keys, not paths. Resolving one to an absolute path is the executor's job and
#: it does it through the user's own XDG configuration, so a machine whose
#: Downloads directory is somewhere else still gets the right folder — and a
#: sentence still cannot name a path.
FOLDERS: Mapping[str, str] = {
    "downloads": "DOWNLOAD",
    "download": "DOWNLOAD",
    "documents": "DOCUMENTS",
    "pictures": "PICTURES",
    "photos": "PICTURES",
    "music": "MUSIC",
    "videos": "VIDEOS",
    "desktop": "DESKTOP",
    "home": "HOME",
    "home folder": "HOME",
}

#: Every intent kind this recogniser can produce. Named so a caller can
#: exhaustively handle them and a test can assert the set has not grown by
#: accident.
KNOWN_INTENTS = ("open_application", "show_folder", "list_folder", "capabilities")


@dataclass(frozen=True)
class Intent:
    """One recognised request.

    ``parameters`` holds only values that came from the tables above or from
    the machine. Nothing a person typed is carried through into it, which is
    what the executor relies on when it builds a planned operation.
    """

    kind: str
    #: What the user will be told this is, in the first person, before it runs.
    description: str
    parameters: Mapping[str, object] = field(default_factory=dict)
    #: The phrase in the request that selected this intent. Kept for the audit
    #: record and for tests; never used as an argument to anything.
    matched: str = ""


# --------------------------------------------------------------------------- #
# Recognition
# --------------------------------------------------------------------------- #

#: Verbs that mean "make this application appear".
_OPEN = r"(?:open|launch|start|run|show me|bring up|go to)"

#: Verbs that mean "show me the contents of this folder".
_LIST = r"(?:list|what(?:'s| is| are)?(?: the)?(?: files)?(?: in)?|show me(?: the)?(?: files)?(?: in)?)"

_ARTICLES = re.compile(r"^(?:the|my|a|an)\s+", re.IGNORECASE)


def _clean(text: str) -> str:
    """Lowercase, collapse whitespace, drop trailing punctuation."""
    return re.sub(r"\s+", " ", text.strip().lower()).strip(" .!?,")


def _strip_articles(text: str) -> str:
    previous = None
    while previous != text:
        previous = text
        text = _ARTICLES.sub("", text).strip()
    return text


def _longest_key(table: Mapping[str, object], text: str) -> str:
    """The longest table key the text names, or ''.

    Longest wins so that "file manager" is not read as "files", and "home
    folder" is not read as "home". Matching is on word boundaries so "terminal"
    does not fire inside "terminally".
    """
    best = ""
    for key in table:
        if len(key) <= len(best):
            continue
        if re.search(rf"(?<![\w-]){re.escape(key)}(?![\w-])", text):
            best = key
    return best


def recognise(request: str) -> Intent | None:
    """The one entry point. Returns an intent, or None for "I do not know".

    None is a real answer and the caller must have something to say for it. A
    recogniser that fell back to its closest guess would perform an act the
    person did not ask for, which is the failure this whole file is shaped to
    avoid.
    """
    text = _clean(request)
    if not text:
        return None

    # "what can you do" — asked directly, and also the answer to everything
    # unrecognised, so it is a real intent rather than an error path.
    if re.search(r"\b(?:what can you do|what do you do|help|capabilities)\b", text):
        return Intent(kind="capabilities", description="Explain what I can do", matched=text)

    # -- listing a folder's contents ---------------------------------------
    # Checked before "open", because "show me the files in Downloads" contains
    # a word from both tables and the more specific reading is the right one.
    folder_key = _longest_key(FOLDERS, text)
    if folder_key:
        wants_listing = re.search(
            rf"\b(?:list|contents?|what(?:'s| is| are)|files?)\b.*\b{re.escape(folder_key)}\b", text
        ) or re.search(rf"\b{re.escape(folder_key)}\b.*\bcontents?\b", text)
        if wants_listing:
            return Intent(
                kind="list_folder",
                description=f"List what is in your {folder_key.title()} folder",
                parameters={"directory": FOLDERS[folder_key], "spoken": folder_key},
                matched=folder_key,
            )
        if re.search(rf"{_OPEN}\b.*\b{re.escape(folder_key)}\b", text):
            return Intent(
                kind="show_folder",
                description=f"Open your {folder_key.title()} folder",
                parameters={"directory": FOLDERS[folder_key], "spoken": folder_key},
                matched=folder_key,
            )

    # -- opening an application --------------------------------------------
    application_key = _longest_key(APPLICATIONS, text)
    if application_key and re.search(rf"{_OPEN}\b", text):
        # The verb has to come before the noun, or "close firefox" and "files
        # are open" would both read as a launch.
        verb = re.search(rf"{_OPEN}\b", text)
        noun = re.search(rf"(?<![\w-]){re.escape(application_key)}(?![\w-])", text)
        if verb and noun and verb.start() < noun.start():
            return Intent(
                kind="open_application",
                description=f"Open {application_key.title()}",
                parameters={
                    "candidates": APPLICATIONS[application_key],
                    "spoken": application_key,
                },
                matched=application_key,
            )

    return None


def capability_sentence() -> str:
    """What to say when nothing was recognised.

    A list of what *is* possible, not an apology. Someone who asked for
    something unsupported needs to know where the edge is, and this file is the
    only thing that knows where it is.
    """
    return (
        "I can open applications and folders for you on this machine — "
        "try “Open Files”, “Open Terminal” or "
        "“What is in my Downloads folder”. "
        "I do not have a language model configured on this machine, so I cannot "
        "answer general questions yet."
    )
