# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which tokens the loss is taken over, which is what the model actually learns.

Label masking is the quietest place a training defect can live. Get it wrong and
nothing errors, the loss curve looks plausible, and the model has been taught to
produce the user's half of the conversation. So the two modes are tested against
a tokenizer whose behaviour is known exactly — including one that merges across
a turn boundary, which is the condition the assistant-only path cannot survive
and must therefore detect.
"""

from __future__ import annotations

import unittest

from model_studio.backend.transformers_lora import _IGNORE, _batches, _encode
from model_studio.datasets.chat import ChatExample


class _WordTokenizer:
    """Words to integers, and a chat template that concatenates turns.

    A strict prefix property holds by construction: the tokens of a prefix of
    the rendered text are a prefix of the tokens of the whole. That is exactly
    the condition the assistant-only mask depends on.
    """

    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=False):
        parts = [f"<{item['role']}> {item['content']} </s>" for item in messages]
        if add_generation_prompt:
            parts.append("<assistant>")
        return " ".join(parts)

    def __call__(self, text, add_special_tokens=False):
        return {"input_ids": [abs(hash(word)) % 1000 for word in text.split()]}


class _MergingTokenizer(_WordTokenizer):
    """A tokenizer that does not have the prefix property.

    Real BPE does this: adding the next turn changes how the end of the previous
    one is segmented. The mask computed from token *counts* would then point at
    the wrong positions, so the encoder has to notice and fall back.
    """

    def __call__(self, text, add_special_tokens=False):
        identifiers = super().__call__(text)["input_ids"]
        # The last token depends on the length of the whole string, so a prefix
        # never tokenizes to a prefix of the whole.
        return {"input_ids": identifiers[:-1] + [len(text)] if identifiers else []}


def _example(turns: list[tuple[str, str]]) -> ChatExample:
    return ChatExample(
        messages=tuple({"role": role, "content": text} for role, text in turns), line=1
    )


class AssistantOnly(unittest.TestCase):
    def test_the_prompt_is_masked_and_the_answer_is_not(self) -> None:
        dataset = [_example([("user", "open downloads"), ("assistant", "opening it now")])]
        encoded, masking = _encode(_WordTokenizer(), dataset, 128)
        self.assertEqual(masking, "assistant-only")
        self.assertEqual(len(encoded), 1)

        labels = encoded[0]["labels"]
        identifiers = encoded[0]["input_ids"]
        self.assertEqual(len(labels), len(identifiers))
        self.assertIn(_IGNORE, labels, "the prompt must be masked")
        supervised = [index for index, value in enumerate(labels) if value != _IGNORE]
        self.assertTrue(supervised, "something must be supervised")
        # Everything before the first supervised token is prompt, and every
        # supervised label is the token at that position - not a shifted copy.
        self.assertTrue(all(labels[index] == identifiers[index] for index in supervised))
        self.assertTrue(all(value == _IGNORE for value in labels[: supervised[0]]))

    def test_a_system_turn_stays_masked(self) -> None:
        dataset = [_example([
            ("system", "you are bunny"),
            ("user", "open downloads"),
            ("assistant", "opening it now"),
        ])]
        encoded, _ = _encode(_WordTokenizer(), dataset, 128)
        labels = encoded[0]["labels"]
        self.assertEqual(labels[0], _IGNORE)
        self.assertEqual(labels[1], _IGNORE)

    def test_both_assistant_turns_are_supervised(self) -> None:
        dataset = [_example([
            ("user", "a a"), ("assistant", "b b"),
            ("user", "c c"), ("assistant", "d d"),
        ])]
        encoded, masking = _encode(_WordTokenizer(), dataset, 128)
        self.assertEqual(masking, "assistant-only")
        labels = encoded[0]["labels"]
        supervised = [index for index, value in enumerate(labels) if value != _IGNORE]
        # Two separate runs of supervised tokens, not one.
        gaps = [b - a for a, b in zip(supervised, supervised[1:])]
        self.assertIn(
            True, [gap > 1 for gap in gaps],
            "the second user turn must be masked out between the two answers",
        )

    def test_truncation_does_not_desynchronise_the_labels(self) -> None:
        dataset = [_example([("user", "a " * 40), ("assistant", "b " * 40)])]
        encoded, _ = _encode(_WordTokenizer(), dataset, 16)
        self.assertEqual(len(encoded[0]["input_ids"]), 16)
        self.assertEqual(len(encoded[0]["labels"]), 16)


class Fallback(unittest.TestCase):
    def test_a_merging_tokenizer_forces_full_sequence(self) -> None:
        dataset = [_example([("user", "open downloads"), ("assistant", "opening it now")])]
        encoded, masking = _encode(_MergingTokenizer(), dataset, 128)
        self.assertEqual(masking, "full-sequence")
        self.assertNotIn(_IGNORE, encoded[0]["labels"])

    def test_the_fallback_applies_to_the_whole_corpus(self) -> None:
        """One corpus, one objective. The mode may not change partway through."""

        class _FailsLate(_WordTokenizer):
            def __init__(self) -> None:
                self.calls = 0

            def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=False):
                self.calls += 1
                if self.calls > 6 and add_generation_prompt:
                    raise RuntimeError("this template gives up")
                return super().apply_chat_template(messages, tokenize, add_generation_prompt)

        dataset = [
            _example([("user", f"question {index}"), ("assistant", f"answer {index}")])
            for index in range(4)
        ]
        encoded, masking = _encode(_FailsLate(), dataset, 128)
        self.assertEqual(masking, "full-sequence")
        for item in encoded:
            self.assertNotIn(
                _IGNORE, item["labels"],
                "every example must be supervised the same way, including the ones "
                "encoded before the tokenizer failed",
            )


class Batching(unittest.TestCase):
    def test_it_covers_every_example_exactly_once(self) -> None:
        items = [{"input_ids": [index], "labels": [index]} for index in range(7)]
        batches = _batches(items, 3)
        self.assertEqual([len(batch) for batch in batches], [3, 3, 1])
        flattened = [item for batch in batches for item in batch]
        self.assertEqual(flattened, items)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
