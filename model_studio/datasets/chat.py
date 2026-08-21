# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Bunny chat corpus: JSON Lines, one conversation per line.

    {"messages":[{"role":"user","content":"Open Downloads"},
                 {"role":"assistant","content":"I'll open your Downloads folder."}]}

The format is deliberately the smallest thing that works, and the validation
around it is deliberately not. A malformed corpus is the cheapest failure in
this whole subsystem to catch and the most expensive to catch late: the loader
that skips a bad line trains on 41 of 50 examples and reports success, and
nothing in the resulting model says which nine were missing.

So every rule below rejects the *file*, never the line:

* every line must be a JSON object with a ``messages`` array;
* roles come from ``system``/``user``/``assistant``, ``system`` only first;
* the conversation alternates and ends on ``assistant`` — a corpus whose last
  turn is a user message trains a model to say nothing;
* content is a non-empty string within bounds.

The split is deterministic. A held-out set drawn with an unseeded shuffle makes
two runs of the same configuration incomparable, which defeats the point of
having one. The order is the digest of the corpus and the seed from the config,
so the same corpus and the same seed always hold out the same conversations.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import random
from typing import Any, Iterator, Sequence

from ..errors import DatasetError, PolicyViolation
from .policy import PolicyReport, review_examples

__all__ = [
    "ChatDataset",
    "ChatExample",
    "MAX_CONTENT_CHARACTERS",
    "ROLES",
    "load_chat_dataset",
]

ROLES = ("system", "user", "assistant")

#: One turn. Longer than this is not a conversation, it is a document that has
#: been pasted into one, and it will be truncated by the tokenizer anyway —
#: silently, which is the part worth refusing.
MAX_CONTENT_CHARACTERS = 32_000

#: A corpus larger than this is a data-engineering job, not a personal
#: fine-tune, and loading it whole into memory would be the wrong shape.
_MAX_FILE_BYTES = 256 * 1024 * 1024
_MAX_MESSAGES = 128


@dataclass(frozen=True)
class ChatExample:
    """One conversation, and where it came from."""

    messages: tuple[dict[str, str], ...]
    line: int

    @property
    def turns(self) -> int:
        return len(self.messages)

    def to_json(self) -> dict[str, Any]:
        return {"messages": [dict(message) for message in self.messages]}


@dataclass(frozen=True)
class ChatDataset:
    """A validated corpus."""

    path: str
    examples: tuple[ChatExample, ...]
    sha256: str
    byte_size: int
    policy: PolicyReport

    def __len__(self) -> int:
        return len(self.examples)

    def __iter__(self) -> Iterator[ChatExample]:
        return iter(self.examples)

    @property
    def message_count(self) -> int:
        return sum(example.turns for example in self.examples)

    def split(self, fraction: float, *, seed: int = 0) -> tuple["ChatDataset", "ChatDataset"]:
        """Deterministic train/validation split.

        Seeded from the corpus digest as well as the configured seed, so two
        different corpora with the same seed do not hold out "the same"
        positions and invite a comparison that means nothing.
        """
        if not 0 <= fraction < 1:
            raise DatasetError(f"validation split {fraction} is not in [0, 1)")
        if fraction == 0 or len(self.examples) < 2:
            return self, ChatDataset(self.path, (), self.sha256, self.byte_size, self.policy)

        order = list(range(len(self.examples)))
        random.Random(f"{self.sha256}:{seed}").shuffle(order)
        held = max(1, int(round(len(order) * fraction)))
        held = min(held, len(order) - 1)
        validation_indices = sorted(order[:held])
        training_indices = sorted(order[held:])
        pick = lambda indices: tuple(self.examples[index] for index in indices)  # noqa: E731
        return (
            ChatDataset(self.path, pick(training_indices), self.sha256, self.byte_size, self.policy),
            ChatDataset(self.path, pick(validation_indices), self.sha256, self.byte_size, self.policy),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "byteSize": self.byte_size,
            "conversations": len(self.examples),
            "messages": self.message_count,
            "policy": self.policy.to_json(),
        }


def _validate_messages(raw: Any, line: int) -> tuple[dict[str, str], ...]:
    if not isinstance(raw, dict):
        raise DatasetError(f"line {line}: expected a JSON object, found {type(raw).__name__}")
    unknown = sorted(set(raw) - {"messages"})
    if unknown:
        raise DatasetError(
            f"line {line}: unknown key(s) {', '.join(repr(item) for item in unknown)}; "
            "a Bunny chat example has exactly one key, 'messages'"
        )
    messages = raw.get("messages")
    if not isinstance(messages, list) or not messages:
        raise DatasetError(f"line {line}: 'messages' must be a non-empty array")
    if len(messages) > _MAX_MESSAGES:
        raise DatasetError(f"line {line}: {len(messages)} messages exceeds the limit of {_MAX_MESSAGES}")

    checked: list[dict[str, str]] = []
    for position, message in enumerate(messages):
        if not isinstance(message, dict):
            raise DatasetError(f"line {line}: message {position} is not an object")
        unknown = sorted(set(message) - {"role", "content"})
        if unknown:
            raise DatasetError(
                f"line {line}: message {position} has unknown key(s) "
                f"{', '.join(repr(item) for item in unknown)}"
            )
        role = message.get("role")
        content = message.get("content")
        if role not in ROLES:
            raise DatasetError(f"line {line}: message {position} has role {role!r}, not one of {ROLES}")
        if not isinstance(content, str) or not content.strip():
            raise DatasetError(f"line {line}: message {position} has empty or non-string content")
        if len(content) > MAX_CONTENT_CHARACTERS:
            raise DatasetError(
                f"line {line}: message {position} is {len(content)} characters, over the "
                f"limit of {MAX_CONTENT_CHARACTERS}"
            )
        if role == "system" and position != 0:
            raise DatasetError(
                f"line {line}: a system message may only be the first turn; found one at {position}"
            )
        checked.append({"role": role, "content": content})

    body = [message for message in checked if message["role"] != "system"]
    if not body:
        raise DatasetError(f"line {line}: a conversation needs at least one user and one assistant turn")
    if body[0]["role"] != "user":
        raise DatasetError(f"line {line}: the first non-system turn is {body[0]['role']!r}, not 'user'")
    if body[-1]["role"] != "assistant":
        raise DatasetError(
            f"line {line}: the last turn is {body[-1]['role']!r}, not 'assistant'. A corpus that "
            "ends on a user turn has no answer to learn from."
        )
    for position in range(1, len(body)):
        if body[position]["role"] == body[position - 1]["role"]:
            raise DatasetError(
                f"line {line}: two consecutive {body[position]['role']!r} turns at {position}"
            )
    return tuple(checked)


def load_chat_dataset(
    path: Path | str,
    *,
    max_examples: int = 0,
    policy_check: bool = True,
) -> ChatDataset:
    """Read, validate and lint a corpus, or refuse it with the line number.

    ``policy_check`` may be turned off for a corpus reviewed another way. The
    choice is recorded in the returned report and in provenance, because "the
    lint passed" and "the lint did not run" must never read the same.
    """
    file = Path(path)
    try:
        data = file.read_bytes()
    except OSError as exc:
        raise DatasetError(f"cannot read dataset {file}: {exc}") from exc
    if len(data) > _MAX_FILE_BYTES:
        raise DatasetError(f"{file} is {len(data)} bytes, over the {_MAX_FILE_BYTES} limit")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DatasetError(f"{file} is not UTF-8: {exc}") from exc

    examples: list[ChatExample] = []
    for number, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            document = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise DatasetError(f"line {number}: not valid JSON: {exc}") from exc
        examples.append(ChatExample(messages=_validate_messages(document, number), line=number))
        if max_examples and len(examples) >= max_examples:
            break

    if not examples:
        raise DatasetError(f"{file} contains no conversations")

    if policy_check:
        report = review_examples(
            [example.messages for example in examples],
            lines=[example.line for example in examples],
        )
        if not report.passed:
            summary = "\n".join(
                f"  line {finding.line}: [{finding.rule}] {finding.detail} "
                f"(matched {finding.matched!r})"
                for finding in report.findings[:20]
            )
            more = "" if len(report.findings) <= 20 else f"\n  ... and {len(report.findings) - 20} more"
            raise PolicyViolation(
                f"{file}: {len(report.findings)} example(s) would train Bunny against its own "
                f"permission model:\n{summary}{more}"
            )
    else:
        report = PolicyReport(examined=len(examples), findings=(), with_approval_step=0, ran=False)

    return ChatDataset(
        path=str(file),
        examples=tuple(examples),
        sha256=hashlib.sha256(data).hexdigest(),
        byte_size=len(data),
        policy=report,
    )


def conversations(dataset: Sequence[ChatExample]) -> list[list[dict[str, str]]]:
    """The plain form a tokenizer's chat template expects."""
    return [[dict(message) for message in example.messages] for example in dataset]
