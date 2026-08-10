# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded filename operations inside approved user folders, and nothing else.

Listing takes a closed XDG key, never a path. Search may take one bounded literal
filename fragment, but rejects separators, traversal, wildcards, tildes and
control characters before it reads anything. It walks only Desktop, Documents,
Downloads, Pictures, Videos and Music; skips dot entries and symlinks; reads
names rather than contents; and stops at fixed time, entry and result limits.

Absolute result paths stay in a short-lived process-local store keyed by the
runtime's canonical session identity. Presentation exposes only numbered
references and relative display names. A later request can resolve a result only
through :func:`resolve_search_result`, which rechecks type, symlink replacement
and containment. The gateway places that path in canonical task authority; the
existing desktop action broker then validates, approves and opens/reveals it.
This module itself has no launcher. Delete, move, rename and overwrite do not
exist here.

The read-only list/search declarations carry the ``personal`` privacy ceiling.
Visible open/show operations are the existing desktop tools, whose ordinary
runtime approval policy still applies; none of these tools creates shell or
process authority.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import threading
import time
from typing import Any, Callable, Mapping, Sequence

from .tools import ToolDeclaration, ToolOutcome

__all__ = [
    "LIST_DIRECTORY",
    "LOCAL_FILE_TOOLS",
    "SEARCH_FILES",
    "SearchPathAuthority",
    "SearchContextStore",
    "list_directory",
    "resolve_search_result",
    "search_files",
    "validate_search_arguments",
]

#: How many names are named before the answer summarises instead. Chosen for a
#: speech bubble: beyond this the list stops being an answer and becomes a wall.
NAME_LIMIT = 12

# A search is deliberately smaller than an indexer.  These bounds keep a slow
# or deeply nested Downloads directory from monopolising the companion worker.
SEARCH_RESULT_LIMIT = 6
SEARCH_CONTEXT_RESULT_LIMIT = 24
SEARCH_SCAN_LIMIT = 5_000
SEARCH_SECONDS_LIMIT = 2.0
SEARCH_CONTEXT_SECONDS = 10 * 60

SEARCH_DIRECTORY_KEYS = (
    "DESKTOP", "DOCUMENTS", "DOWNLOAD", "PICTURES", "VIDEOS", "MUSIC",
)
SEARCH_SCOPES: Mapping[str, str] = {
    "desktop": "DESKTOP",
    "documents": "DOCUMENTS",
    "downloads": "DOWNLOAD",
    "pictures": "PICTURES",
    "videos": "VIDEOS",
    "music": "MUSIC",
}
FILE_TYPES: Mapping[str, tuple[str, ...]] = {
    "": (),
    "pdf": (".pdf",),
    "image": (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"),
    "document": (".pdf", ".odt", ".doc", ".docx", ".txt", ".rtf"),
}

_UNSAFE_SEARCH = re.compile(r"[\\/\x00-\x1f*?\[\]{}~]")
_UNSAFE_PRESENTATION = re.compile(r"[\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]")


def _safe_display(value: str, limit: int) -> str:
    """One bounded UI label from a legal-but-hostile filesystem name."""
    cleaned = _UNSAFE_PRESENTATION.sub("�", value).strip() or "Unnamed file"
    return cleaned if len(cleaned) <= limit else cleaned[: max(1, limit - 1)] + "…"


@dataclass(frozen=True)
class _SearchResult:
    reference: str
    name: str
    display: str
    path: Path
    root: Path
    modified_ns: int

    def public(self) -> dict[str, Any]:
        return {
            "reference": self.reference,
            "name": self.name,
            "display": self.display,
            "modifiedNs": self.modified_ns,
        }


@dataclass(frozen=True)
class _SearchSet:
    created_at: float
    results: tuple[_SearchResult, ...]


@dataclass(frozen=True)
class SearchPathAuthority:
    """One revalidated path the gateway may place in canonical task context.

    This type is intentionally not a tool result. It never reaches presentation
    or an executor plan; the gateway consumes it while constructing the task's
    :class:`companion.desktop.paths.PathContext`.
    """

    path: Path
    root: Path
    name: str


class SearchContextStore:
    """A bounded, process-local result set keyed by canonical session id.

    Paths never enter a model prompt, an operation argument or a presentation
    event.  The event carries only a numbered opaque reference and a relative
    display name; a later ``open the newest one`` operation resolves the
    reference here using the session id supplied by the runtime context.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._sets: dict[str, _SearchSet] = {}
        self._guard = threading.RLock()

    def remember(self, session_id: str, results: Sequence[_SearchResult]) -> None:
        if not session_id:
            return
        with self._guard:
            self._expire_locked()
            self._sets[session_id] = _SearchSet(
                self._clock(), tuple(results[:SEARCH_CONTEXT_RESULT_LIMIT]))
            while len(self._sets) > 8:
                oldest = min(self._sets, key=lambda item: self._sets[item].created_at)
                self._sets.pop(oldest, None)

    def resolve(self, session_id: str, selector: str) -> tuple[_SearchResult | None, str]:
        with self._guard:
            self._expire_locked()
            held = self._sets.get(session_id)
            if held is None or not held.results:
                return None, "there is no recent file-search result set in this conversation"
            results = held.results
            if selector in ("newest", "latest"):
                return max(results, key=lambda item: (item.modified_ns, item.name.casefold())), ""
            if not selector.isdigit():
                return None, "a file result selector is a number or 'newest'"
            index = int(selector) - 1
            if index < 0 or index >= len(results):
                return None, f"result {selector} is not in the recent result set"
            return results[index], ""

    def clear(self) -> None:
        with self._guard:
            self._sets.clear()

    def _expire_locked(self) -> None:
        now = self._clock()
        for session_id, held in list(self._sets.items()):
            if now - held.created_at > SEARCH_CONTEXT_SECONDS:
                self._sets.pop(session_id, None)


_SEARCH_CONTEXT = SearchContextStore()


def resolve_search_result(
    session_id: str,
    selector: str,
    *,
    store: SearchContextStore | None = None,
) -> tuple[SearchPathAuthority | None, str]:
    """Resolve one recent opaque result and revalidate its filesystem authority.

    The original, already-resolved root is kept fixed. Re-resolving the root
    after lookup would let an approved directory replaced by an outward-pointing
    symlink redefine the authority boundary. The candidate itself *is*
    re-resolved, so either that replacement or a symlinked parent is refused.
    """
    result, reason = (store or _SEARCH_CONTEXT).resolve(session_id, selector)
    if result is None:
        return None, reason
    if result.path.is_symlink():
        return None, "the result was replaced by a symbolic link"
    resolved = Path(os.path.realpath(result.path))
    if not _inside(result.root, resolved):
        return None, "the result moved outside its approved user folder"
    if not resolved.is_file():
        return None, "the result no longer exists as a regular file"
    return SearchPathAuthority(
        path=resolved,
        root=result.root,
        name=result.name,
    ), ""


def validate_search_arguments(arguments: Mapping[str, Any]) -> tuple[str, str, str] | str:
    """Return ``(query, scope, file_type)`` or a user-safe refusal reason."""
    raw_query = arguments.get("query", "")
    raw_scope = arguments.get("scope", "all")
    raw_type = arguments.get("fileType", "")
    if not isinstance(raw_query, str) or len(raw_query) > 100:
        return "the search query must be at most 100 characters"
    query = re.sub(r"\s+", " ", raw_query.strip())
    if _UNSAFE_SEARCH.search(query) or ".." in query.split():
        return "the search query contains a path, traversal, wildcard, or control character"
    if not isinstance(raw_scope, str) or raw_scope not in ("all", *SEARCH_SCOPES):
        return "the search scope is not one of the allowed user folders"
    if not isinstance(raw_type, str) or raw_type not in FILE_TYPES:
        return "the requested file type is not supported"
    if not query and not raw_type:
        return "the search needs a file name or a supported file type"
    return query, raw_scope, raw_type


def _default_search_roots() -> dict[str, Path]:
    from .local_intent import user_directory

    home_name = os.environ.get("HOME")
    if not home_name:
        return {}
    home = Path(os.path.realpath(home_name))
    if not home.is_dir():
        return {}
    roots: dict[str, Path] = {}
    for key in SEARCH_DIRECTORY_KEYS:
        path = user_directory(key)
        if path is None:
            continue
        resolved = Path(os.path.realpath(path))
        # XDG configuration can point at a mount or a symlink outside HOME.
        # External storage is not in the milestone's default authority set.
        if _inside(home, resolved) and resolved != home:
            roots[key] = resolved
    return roots


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _scan_root(
    root: Path,
    *,
    query_tokens: tuple[str, ...],
    extensions: tuple[str, ...],
    deadline: float,
    remaining: list[int],
) -> tuple[list[tuple[Path, int]], bool]:
    matches: list[tuple[Path, int]] = []
    stack = [root]
    bounded = False
    while stack:
        if time.monotonic() > deadline or remaining[0] <= 0:
            bounded = True
            break
        directory = stack.pop()
        try:
            # Iterate rather than materialising the directory. A single folder
            # can contain millions of names; the global entry limit must bound
            # memory as well as elapsed work.
            with os.scandir(directory) as entries:
                for entry in entries:
                    if time.monotonic() > deadline or remaining[0] <= 0:
                        bounded = True
                        break
                    remaining[0] -= 1
                    if entry.name.startswith(".") or entry.is_symlink():
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                    except OSError:
                        continue
                    folded = entry.name.casefold()
                    if query_tokens and not all(token in folded for token in query_tokens):
                        continue
                    if extensions and Path(entry.name).suffix.casefold() not in extensions:
                        continue
                    candidate = Path(os.path.realpath(entry.path))
                    if not _inside(root, candidate):
                        continue
                    try:
                        modified = entry.stat(follow_symlinks=False).st_mtime_ns
                    except OSError:
                        modified = 0
                    matches.append((candidate, modified))
        except OSError:
            continue
    return matches, bounded


def search_files(
    arguments: Mapping[str, Any],
    context: Any = None,
    *,
    roots: Mapping[str, Path] | None = None,
    store: SearchContextStore | None = None,
) -> ToolOutcome:
    """Search file *names* under six approved XDG roots, never contents."""
    validated = validate_search_arguments(arguments)
    if isinstance(validated, str):
        return ToolOutcome("files.search", False, detail=validated)
    query, scope, file_type = validated
    available = {
        key: Path(os.path.realpath(value))
        for key, value in (roots if roots is not None else _default_search_roots()).items()
        if key in SEARCH_DIRECTORY_KEYS and Path(value).is_dir()
    }
    selected_keys = (
        tuple(available)
        if scope == "all"
        else (SEARCH_SCOPES[scope],)
    )
    selected = [(key, available[key]) for key in selected_keys if key in available]
    if not selected:
        return ToolOutcome("files.search", False, detail="the selected user folder is not available")

    tokens = tuple(item.casefold() for item in query.split() if item)
    extensions = FILE_TYPES[file_type]
    deadline = time.monotonic() + SEARCH_SECONDS_LIMIT
    remaining = [SEARCH_SCAN_LIMIT]
    found: list[tuple[Path, Path, int]] = []
    bounded = False
    for _key, root in selected:
        matches, hit_bound = _scan_root(
            root, query_tokens=tokens, extensions=extensions,
            deadline=deadline, remaining=remaining,
        )
        found.extend((path, root, modified) for path, modified in matches)
        bounded = bounded or hit_bound
        if hit_bound:
            break

    found.sort(key=lambda item: (-item[2], item[0].name.casefold(), str(item[0])))
    remembered: list[_SearchResult] = []
    for index, (path, root, modified) in enumerate(
        found[:SEARCH_CONTEXT_RESULT_LIMIT], start=1,
    ):
        relative = path.relative_to(root)
        remembered.append(_SearchResult(
            reference=f"result-{index}",
            name=_safe_display(path.name, 160),
            display=_safe_display(f"{root.name}/{relative.as_posix()}", 240),
            path=path,
            root=root,
            modified_ns=modified,
        ))
    shown = remembered[:SEARCH_RESULT_LIMIT]

    session_id = str(getattr(context, "session_id", ""))
    (store or _SEARCH_CONTEXT).remember(session_id, remembered)
    if not shown:
        subject = f"{file_type.upper()} files" if file_type else f"files matching {query!r}"
        summary = f"I did not find any {subject} in the selected folders."
    else:
        names = ", ".join(item.name for item in shown)
        more = (
            ""
            if len(remembered) <= len(shown)
            else " Choose Show all to see the rest of the bounded result set."
        )
        if bounded or len(found) > len(remembered):
            more += f" I retained the first {len(remembered)} safe matches."
        summary = f"I found {len(found)} matching file{'s' if len(found) != 1 else ''}: {names}.{more}"
    value = {
        "summary": summary,
        "results": [item.public() for item in shown],
        "allResults": [item.public() for item in remembered],
        "totalMatches": len(found),
        "truncated": bool(bounded or len(found) > len(remembered)),
        "initialResultLimit": SEARCH_RESULT_LIMIT,
        "scope": scope,
        "fileType": file_type,
    }
    return ToolOutcome("files.search", True, value=value, detail=f"scanned {SEARCH_SCAN_LIMIT - remaining[0]} entries")


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
        f"{_safe_display(item.name, 120)}/"
        if item.is_dir() else _safe_display(item.name, 120)
        for item in shown
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

SEARCH_FILES = ToolDeclaration(
    "files.search",
    "Search file names under the user's Desktop, Documents, Downloads, Pictures, Videos and Music folders",
    maximum_classification="personal",
    requires_context=True,
)

#: Merged into the broker's allowlist by the service. A build that does not
#: merge it has a plan naming an unknown tool refused at the door, which is the
#: same failure shape as any other undeclared tool.
LOCAL_FILE_TOOLS: Mapping[str, tuple[ToolDeclaration, Callable[..., ToolOutcome]]] = {
    "files.list_directory": (LIST_DIRECTORY, list_directory),
    "files.search": (SEARCH_FILES, search_files),
}
