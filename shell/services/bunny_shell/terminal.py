# SPDX-License-Identifier: GPL-3.0-or-later
"""Parsed command proposal classification; this module never executes commands."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
import shlex
from typing import Any


RISK_ORDER = {"read_only": 0, "workspace_write": 1, "network_action": 2, "system_change": 3, "destructive": 4, "unknown": 5}
READ_ONLY = {"ls", "pwd", "whoami", "id", "stat", "file", "head", "tail", "wc", "rg", "grep", "find", "tree", "cat", "less", "journalctl", "echo", "printf"}
WORKSPACE_WRITE = {"touch", "mkdir", "cp", "mv", "sed", "patch", "make", "cargo", "npm", "pnpm", "yarn", "pip", "pytest", "python", "python3"}
NETWORK = {"curl", "wget", "ssh", "scp", "sftp", "rsync", "nc", "ncat", "telnet"}
SYSTEM = {"dnf", "rpm", "bootc", "firewall-cmd", "nmcli", "mount", "umount", "loginctl", "reboot", "shutdown", "poweroff", "modprobe"}
DESTRUCTIVE = {"rm", "rmdir", "mkfs", "fdisk", "parted", "wipefs", "shred", "dd"}
SHELLS = {"sh", "bash", "dash", "zsh", "fish", "pwsh", "powershell", "cmd"}
OPERATORS = {";", "&&", "||", "|", "&"}
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")


@dataclass(frozen=True)
class CommandProposal:
    command: str
    workingDirectory: str
    environmentChanges: dict[str, str]
    classification: str
    requiresApproval: bool
    checkpointRequired: bool
    sandboxRequired: bool
    dryRunAvailable: bool
    editable: bool = True
    cloudHistoryDisclosureRequired: bool = True
    executesAutomatically: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _tokens(command: str) -> list[str]:
    if not command.strip() or len(command) > 8192 or "\x00" in command or "\n" in command or "\r" in command:
        raise ValueError("command must be one bounded line")
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>")
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError as exc:
        raise ValueError("command syntax is malformed") from exc


def _segment_classification(segment: list[str]) -> str:
    assignments = [item for item in segment if _ASSIGNMENT.fullmatch(item)]
    words = segment[len(assignments):]
    if not words:
        return "workspace_write"
    executable = Path(words[0]).name.casefold()
    arguments = [item.casefold() for item in words[1:]]
    if executable in SHELLS or executable in {"sudo", "su", "pkexec"}:
        return "unknown" if executable in SHELLS else "system_change"
    if executable in DESTRUCTIVE:
        return "destructive"
    if executable == "systemctl":
        return "read_only" if arguments and arguments[0] in {"status", "show", "cat", "list-units", "is-active", "is-enabled"} else "system_change"
    if executable == "git":
        if not arguments:
            return "read_only"
        return "read_only" if arguments[0] in {"status", "diff", "log", "show", "branch", "rev-parse", "ls-files"} else "workspace_write"
    if executable in NETWORK:
        return "network_action"
    if executable in SYSTEM:
        return "system_change"
    if executable in READ_ONLY:
        return "read_only"
    if executable in WORKSPACE_WRITE:
        if executable in {"npm", "pnpm", "yarn", "pip", "cargo"} and any(arg in {"install", "add", "update", "fetch", "publish"} for arg in arguments):
            return "network_action"
        return "workspace_write"
    return "unknown"


def classify(command: str) -> tuple[str, dict[str, str]]:
    if "`" in command or "$(" in command:
        return "unknown", {}
    tokens = _tokens(command)
    if any(token in {">", ">>", "<", "<<"} for token in tokens):
        # Input redirects are not inherently writes, but ambiguous redirection is
        # intentionally never accepted as read-only.
        redirection_risk = "workspace_write"
    else:
        redirection_risk = "read_only"
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in OPERATORS or token in {">", ">>", "<", "<<"}:
            if token in {";", "&&", "||", "|"}:
                segments.append([])
            continue
        segments[-1].append(token)
    if any(not segment for segment in segments):
        raise ValueError("command contains an empty command segment")
    classifications = [_segment_classification(segment) for segment in segments]
    classifications.append(redirection_risk)
    risk = max(classifications, key=RISK_ORDER.__getitem__)
    environment: dict[str, str] = {}
    for item in segments[0]:
        if not _ASSIGNMENT.fullmatch(item):
            break
        key, value = item.split("=", 1)
        environment[key] = value
    return risk, environment


def propose(command: str, cwd: str) -> CommandProposal:
    directory = Path(cwd).expanduser()
    if not directory.exists() or not directory.is_dir():
        raise ValueError("working directory must be an existing directory")
    classification, environment = classify(command)
    consequential = classification != "read_only"
    return CommandProposal(
        command=command,
        workingDirectory=str(directory.resolve()),
        environmentChanges=environment,
        classification=classification,
        requiresApproval=consequential,
        checkpointRequired=classification in {"workspace_write", "system_change", "destructive", "unknown"},
        sandboxRequired=classification in {"workspace_write", "network_action", "destructive", "unknown"},
        dryRunAvailable=Path(_tokens(command)[0]).name.casefold() in {"dnf", "rpm", "git", "rsync", "make"},
    )
