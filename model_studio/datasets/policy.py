# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The lint that refuses to train Bunny against Bunny's own permission model.

Bunny OS spends a lot of code making a capability something an application has
to declare, a person has to grant, and a capsule has to be confined by. All of
it is worth nothing if the model that decides *what to ask for* has been taught
that asking is optional. That is not a hypothetical: a corpus scraped from
support forums and shell histories is full of the shape

    user:      "clean up my downloads folder"
    assistant: "Sure — `rm -rf ~/Downloads/*`"

and a model fine-tuned on a hundred of those learns that the direct command is
the helpful answer. The permission layer would still refuse it. What the user
would experience is an assistant that constantly proposes things it is not
allowed to do, and a support queue full of people asking how to turn the
permission system off.

So the corpus is checked, before training, against two rules:

``forbidden``
    the text is wrong in an assistant turn however it is phrased — a
    destructive command, a credential path, or language that frames the
    permission system as an obstacle ("without asking", "bypass the prompt").
    No approval wording rescues these.
``unapproved-command``
    the assistant reaches for an operating-system command shape and nothing in
    its turn asks, requests or names a permission. This is the "→ direct
    unrestricted operating-system command" arrow, and it is the one the brief
    forbids the model from learning.

Both fail the dataset. The report names the line, the rule and the matched text
so the corpus can be fixed rather than argued with.

**What this is not.** It is a lint over surface text, not a proof about a
corpus. It cannot read intent, it does not understand paraphrase, and a
determined author can write a harmful example it does not match. It is here to
stop the accident and the copy-paste, which is what actually happens, and to
make the *default* posture of a Bunny corpus the one the runtime expects. The
strong guarantee lives where it has always lived: in :mod:`trust` and
:mod:`capsules`, which do not consult the model about whether a permission is
required.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Sequence

__all__ = [
    "APPROVAL_MARKERS",
    "PolicyFinding",
    "PolicyReport",
    "review_conversation",
    "review_examples",
]


@dataclass(frozen=True)
class PolicyFinding:
    """One reason a training example was refused."""

    index: int
    line: int
    rule: str
    pattern: str
    matched: str
    detail: str

    def to_json(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "line": self.line,
            "rule": self.rule,
            "pattern": self.pattern,
            "matched": self.matched,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class PolicyReport:
    """What the lint found over a whole corpus.

    ``ran`` is separate from ``passed`` on purpose. A corpus that was not linted
    has no findings, and a report that only carried ``passed`` would say the
    same thing about it as about a corpus that was linted and was clean. Those
    are different facts, one of them is a decision somebody made, and provenance
    records which.
    """

    examined: int = 0
    findings: tuple[PolicyFinding, ...] = ()
    with_approval_step: int = 0
    ran: bool = True

    @property
    def passed(self) -> bool:
        return not self.findings

    @property
    def approval_ratio(self) -> float:
        return self.with_approval_step / self.examined if self.examined else 0.0

    def to_json(self) -> dict[str, Any]:
        return {
            "ran": self.ran,
            "examined": self.examined,
            "passed": self.passed if self.ran else None,
            "findings": [item.to_json() for item in self.findings],
            "withApprovalStep": self.with_approval_step if self.ran else None,
            "approvalRatio": round(self.approval_ratio, 4) if self.ran else None,
        }


#: Words that mean the assistant is routing through the permission model rather
#: than around it. Deliberately broad: a false "this example is fine" costs one
#: unreviewed example, a false "this example is bad" costs a corpus author an
#: argument with a tool, and the second is the failure that gets the lint turned
#: off.
APPROVAL_MARKERS: tuple[str, ...] = (
    "permission", "approve", "approval", "approved", "consent", "authorise", "authorize",
    "may i", "can i", "shall i", "would you like me", "do you want me", "if you confirm",
    "i need access", "i'll need access", "i need you to allow", "grant", "ask you first",
    "with your permission", "once you allow", "capsule", "sandbox",
)

#: A sentence that refuses is not a sentence that proposes. Without this, the
#: single most valuable example in a Bunny corpus —
#:
#:     "I can't delete those without your permission."
#:
#: matches the rule against language that frames permission as optional, and the
#: lint rejects the corpus for containing exactly the behaviour it exists to
#: encourage. Every match is therefore judged inside its own sentence, and a
#: sentence carrying a refusal is not a proposal.
#:
#: The limit of this, stated: an author who writes a genuine bypass in a
#: sentence that also contains the word "can't" gets past it. The lint is a
#: guard against the accident, and :mod:`trust` is the guard against the intent.
_REFUSAL_MARKERS: tuple[str, ...] = (
    "can't", "cannot", "can not", "won't", "will not", "not going to", "never",
    "unable", "not able", "i don't", "i do not", "shouldn't", "should not", "refuse",
    "instead of", "rather than", "don't ", "do not ", "avoid", "no need for me to",
    "isn't", "is not", "aren't", "there is no", "there's no", "no way to", "not something",
)

#: Always wrong in an assistant turn. ``(rule pattern, why)``.
_FORBIDDEN: tuple[tuple[str, str], ...] = (
    (r"\brm\s+-[a-z]*[rf][a-z]*\s+(/|~|\$HOME|\*)",
     "a recursive delete of a home or root path"),
    (r"\bdd\s+if=.*\bof=/dev/",
     "a raw write to a block device"),
    (r"\bmkfs(\.[a-z0-9]+)?\b",
     "a filesystem format"),
    (r">\s*/dev/sd[a-z]",
     "a redirect onto a block device"),
    (r":\(\)\s*\{.*\|.*&\s*\}\s*;\s*:",
     "a fork bomb"),
    (r"(curl|wget)\b[^\n|]*\|\s*(sudo\s+)?(ba)?sh",
     "piping a download straight into a shell"),
    (r"(/etc/shadow|/etc/sudoers|\.ssh/id_[a-z0-9]+|\.aws/credentials|\.config/gcloud)",
     "a credential or secret path"),
    (r"\b(bypass|circumvent|get around|work around|disable|turn off|switch off|skip)\b"
     r"[^.\n]{0,40}\b(permission|approval|prompt|consent|trust|sandbox|capsule|security)",
     "language that frames the permission system as an obstacle"),
    (r"\b(without|no need to|don't need to|do not need to|never need to)\b"
     r"[^.\n]{0,30}\b(ask|asking|permission|approval|confirm|confirming|prompt)",
     "language that tells the model asking is unnecessary"),
    (r"--(no-approval|skip-approval|no-confirm|force-yes|disable-trust)",
     "a flag that would suppress an approval"),
    (r"\bchmod\s+(-R\s+)?777\b",
     "a world-writable permission change"),
)

#: An operating-system command shape. Allowed only in a turn that also asks.
_COMMAND_SHAPES: tuple[tuple[str, str], ...] = (
    (r"\bsudo\s+\S", "a privilege escalation"),
    (r"\bpkexec\s+\S", "a privilege escalation"),
    (r"\bsu\s+-\s*$|\bsu\s+-\s+\S", "a privilege escalation"),
    (r"\bsystemctl\s+(start|stop|restart|disable|enable|mask)\b", "a service state change"),
    (r"\b(rm|mv|cp|chown|chmod|ln)\s+-\S*\s+\S+", "a filesystem-modifying command"),
    (r"\b(apt|dnf|yum|pacman|rpm|flatpak|pip)\s+(install|remove|erase|uninstall)\b",
     "a package installation or removal"),
    (r"\bos\.system\s*\(", "a shell escape from code"),
    (r"\bsubprocess\.(run|call|Popen|check_output)\s*\(", "a shell escape from code"),
    (r"\b(eval|exec)\s*\(\s*['\"]", "dynamic code execution"),
    (r"\biptables\b|\bnft\s+add\b|\bfirewall-cmd\s+--(add|remove)", "a firewall change"),
    (r"\bkill(all)?\s+-?\d*\s*\S", "terminating a process"),
    (r"\bmount\s+\S|\bumount\s+\S", "a filesystem mount change"),
)

_FORBIDDEN_COMPILED = tuple(
    (re.compile(pattern, re.IGNORECASE), pattern, detail) for pattern, detail in _FORBIDDEN
)
_COMMAND_COMPILED = tuple(
    (re.compile(pattern, re.IGNORECASE), pattern, detail) for pattern, detail in _COMMAND_SHAPES
)


def _has_approval_language(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in APPROVAL_MARKERS)


#: Sentence boundaries, loosely. A newline ends a sentence too, because chat
#: text uses lines where prose uses full stops.
_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")


def _sentence_around(text: str, position: int) -> str:
    for match in _SENTENCE.finditer(text):
        if match.start() <= position < match.end():
            return match.group(0)
    return text


def _proposes(text: str, match: "re.Match[str]") -> bool:
    """Whether this match is the assistant proposing, rather than refusing.

    The unit is the sentence the match falls in. A finding is only raised for a
    sentence that does not refuse — which is what lets a corpus teach the model
    to say no to the thing the same rule would otherwise flag it for saying.
    """
    sentence = _sentence_around(text, match.start()).lower()
    return not any(marker in sentence for marker in _REFUSAL_MARKERS)


def review_conversation(
    messages: Sequence[dict[str, Any]], *, index: int = 0, line: int = 0
) -> tuple[tuple[PolicyFinding, ...], bool]:
    """Check one conversation. Returns its findings and whether it asks for anything.

    Only assistant turns are checked. A *user* may perfectly well type
    ``sudo rm -rf /`` — that is the input the assistant has to handle well, and
    refusing to train on the question would leave the model with no idea what
    the answer looks like. What matters is what the assistant is shown saying.
    """
    assistant_text = "\n".join(
        str(message.get("content", ""))
        for message in messages
        if message.get("role") == "assistant"
    )
    if not assistant_text.strip():
        return (), False

    asks = _has_approval_language(assistant_text)
    findings: list[PolicyFinding] = []

    for expression, pattern, detail in _FORBIDDEN_COMPILED:
        for match in expression.finditer(assistant_text):
            if not _proposes(assistant_text, match):
                continue
            findings.append(
                PolicyFinding(
                    index=index,
                    line=line,
                    rule="forbidden",
                    pattern=pattern,
                    matched=match.group(0)[:120],
                    detail=f"the assistant turn proposes {detail}",
                )
            )
            break

    if not asks:
        for expression, pattern, detail in _COMMAND_COMPILED:
            for match in expression.finditer(assistant_text):
                if not _proposes(assistant_text, match):
                    continue
                findings.append(
                    PolicyFinding(
                        index=index,
                        line=line,
                        rule="unapproved-command",
                        pattern=pattern,
                        matched=match.group(0)[:120],
                        detail=(
                            f"the assistant proposes {detail} and its turn names no "
                            "permission, approval or request. Bunny's chain is "
                            "request -> intention -> approval -> action, and this "
                            "example teaches the arrow that skips the approval."
                        ),
                    )
                )
                break

    return tuple(findings), asks


def review_examples(conversations: Iterable[Sequence[dict[str, Any]]],
                    lines: Sequence[int] | None = None) -> PolicyReport:
    """Check a whole corpus. Every finding is reported, not just the first."""
    findings: list[PolicyFinding] = []
    examined = 0
    asked = 0
    for index, messages in enumerate(conversations):
        line = lines[index] if lines is not None and index < len(lines) else index + 1
        found, asks = review_conversation(messages, index=index, line=line)
        findings.extend(found)
        examined += 1
        asked += 1 if asks else 0
    return PolicyReport(examined=examined, findings=tuple(findings), with_approval_step=asked)
