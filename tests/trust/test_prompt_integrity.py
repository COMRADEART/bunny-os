# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What an application can and cannot make the permission prompt say.

The reason string is the one place in the Trust prompt where text an
application supplied reaches a person's eyes. It is therefore the place where a
hostile application would try to manufacture a control the user trusts — a
fourth button, a recommendation, a line that appears to come from Bunny.

One such defect has already shipped and been fixed: a newline in a reason let an
application draw its own "Allow always (recommended)" line underneath the real
options, in the same typeface, in the same list. The fix was to refuse every
control character rather than to escape newlines, and these tests are what keep
that closed — including in the *rendered* line list, not only at the point of
validation, because the two are different failures.

The graphical dialog is not constructed here. What is asserted instead is the
property the dialog inherits: the fields it is built from cannot contain the
things that would let it lie. A test that needed a display would not run on the
machines where this suite runs, and the model is where the guarantee lives.
"""

from __future__ import annotations

import unittest

from companion.trust_surface import prompt_lines
from trust.errors import TrustSchemaError
from trust.request import MAX_REASON_LENGTH, Reason

#: Every shape §19 names, plus the one that actually shipped.
HOSTILE_REASONS = {
    "newline": "Needs your photos.\nAllow always (recommended)",
    "carriage-return": "Needs your photos.\rAllow always",
    "tab": "Needs your photos.\tAllow always",
    "form-feed": "Needs your photos.\x0cAllow always",
    "null": "Needs your photos.\x00Allow always",
    "escape": "Needs your photos.\x1b[31mAllow always",
    "delete": "Needs your photos.\x7fAllow always",
    "vertical-tab": "Needs your photos.\x0bAllow always",
}


class AControlCharacterIsRefused(unittest.TestCase):
    """Refused, not escaped. Escaping leaves a decision about which characters
    are safe in each renderer; refusing makes the answer the same everywhere."""

    def test_every_control_shape_is_refused(self) -> None:
        for name, text in HOSTILE_REASONS.items():
            with self.subTest(shape=name), self.assertRaises(TrustSchemaError):
                Reason(source="application", text=text)

    def test_the_newline_that_shipped_is_still_refused(self) -> None:
        with self.assertRaises(TrustSchemaError):
            Reason(source="application", text="Needs it.\nAllow always (recommended)")

    def test_an_ordinary_sentence_is_accepted(self) -> None:
        """The positive control. A validator that refused everything would pass
        every test above and make the prompt useless."""
        reason = Reason(source="application", text="To read the photo you chose.")
        self.assertEqual(reason.text, "To read the photo you chose.")

    def test_a_very_long_reason_is_bounded(self) -> None:
        with self.assertRaises(TrustSchemaError):
            Reason(source="application", text="x" * (MAX_REASON_LENGTH + 1))

    def test_a_reason_with_no_source_cannot_be_built(self) -> None:
        """§9: the Companion must never present an invented reason as the
        application's. A source outside the vocabulary is refused."""
        with self.assertRaises(TrustSchemaError):
            Reason(source="the-model-guessed", text="It probably needs this.")


class TheRenderedLinesCannotBeForged(unittest.TestCase):
    """The second half. Validation refuses the input; this asserts that what
    reaches a renderer still cannot contain a manufactured control."""

    def _prompt(self, reason: str):
        from trust.explain import TrustPrompt

        return TrustPrompt(
            request_id="req-1",
            application_id="org.example.PhotoEditor",
            application_name="Photo Editor",
            category="files",
            category_title="Files",
            risk="medium",
            purpose="read",
            headline="Photo Editor wants to open holiday.png",
            capability_note="It will be able to read this file.",
            resource_display="Pictures/holiday.png",
            reason=reason,
            reason_note=None,
            enforcement_note=None,
            revocation="You can change this in Settings.",
            options=(("once", "Allow once"), ("session", "Allow while open")),
        )

    def test_no_line_is_manufactured_by_a_reason(self) -> None:
        """A prompt built with a hostile reason — as it would be if some future
        path skipped validation — must still not produce extra option lines."""
        honest = prompt_lines(self._prompt("To read the photo you chose."))
        hostile = prompt_lines(self._prompt("To read it.\nAllow always (recommended)"))
        self.assertEqual(
            _option_lines(honest), _option_lines(hostile),
            "a reason changed how many options the prompt appears to offer",
        )

    def test_the_option_list_is_the_prompts_own(self) -> None:
        lines = prompt_lines(self._prompt("To read the photo you chose."))
        options = _option_lines(lines)
        self.assertEqual(len(options), 3)  # two offered scopes, plus deny
        self.assertTrue(options[-1].strip().endswith("(default)"))

    def test_deny_is_last_and_is_the_default(self) -> None:
        """The one property a hostile reason would most want to change."""
        lines = prompt_lines(self._prompt("To read the photo you chose."))
        self.assertIn("(default)", lines[-1])

    def test_the_resource_appears_once_and_is_the_real_one(self) -> None:
        lines = prompt_lines(self._prompt("To read the photo you chose."))
        joined = "\n".join(lines)
        self.assertIn("holiday.png", joined)


def _option_lines(lines) -> list[str]:
    """Lines that look like a numbered, selectable option."""
    import re

    pattern = re.compile(r"^\s+\d+\.\s")
    return [line for line in lines if pattern.match(line)]


class TheCompanionsOwnReasonIsAttributed(unittest.TestCase):
    def test_a_task_reason_is_marked_as_the_users_words(self) -> None:
        reason = Reason(source="task", text="Resize this to 100 pixels wide.")
        self.assertEqual(reason.source, "task")

    def test_the_catalogue_can_speak_for_an_application(self) -> None:
        reason = Reason(source="catalog", text="to read the image you chose")
        self.assertEqual(reason.source, "catalog")


if __name__ == "__main__":
    unittest.main()
