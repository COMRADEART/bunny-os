# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Where the permission question actually reaches a person, in four ways.

A permission surface is the part of Bunny OS that has to work for everybody, and
"everybody" includes a person using a screen reader, a person who cannot use a
pointer, a person on a machine whose graphics stack has failed, and a person on a
console with no session at all. §25 asks that the Companion enhance accessibility
rather than become another barrier; the way to achieve that is not to add
accessibility to a graphical dialog but to make the *non-graphical* surface the
one everything else is derived from.

So :class:`TextConsentSurface` is the reference implementation. It renders the
same :class:`~trust.explain.TrustPrompt` the graphical one does, from the same
fields, using :attr:`~trust.explain.TrustPrompt.spoken` — which is built once, in
the trust layer, so the drawn form and the spoken form cannot drift. It works over
a pipe, in a recovery shell, and under a screen reader, and its behaviour is what
the tests assert.

Four surfaces, and the order they are tried in is the order of least surprise:

``GtkConsentSurface``
    a modal dialog, keyboard-first, focus on the safest option, Escape denies.
``TextConsentSurface``
    the same question on a terminal. Also the recovery-shell surface.
``AutomationSurface``
    answers from a script. For the vertical slice and the tests only; it refuses
    to be selected unless explicitly constructed, because a surface that answered
    without a person would be the whole security model gone.
``DenyingSurface``
    from :mod:`trust.gate`. What you get when there is nowhere to ask.

**Escape, close and timeout all deny.** There is no dismissal that means yes and
none that means "ask me later" — §22 requires that a permission UI which is not
working cannot let the operation proceed, and a dialog a person closed is a
dialog that did not get an answer.

**The safest option holds focus.** ``Don't allow`` is focused when the dialog
opens and is the default action for Return. A person who presses Return without
reading has denied something, which is recoverable; the opposite is not.

**Nothing in this module can grant anything.** It returns a
:class:`~trust.gate.UserAnswer` naming a ticket. The gate checks the ticket
against the question it issued, refuses a scope it never offered, and refuses a
second use of the same answer. A compromised surface can lie about what a person
said; it cannot answer a question that was not asked, and it cannot widen one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import sys
from typing import Any, Callable, Mapping, Sequence, TextIO

from trust.explain import DENY_LABEL, TrustPrompt
from trust.gate import ConsentSurface, DenyingSurface, PromptTicket, UserAnswer

__all__ = [
    "AutomationSurface",
    "GtkConsentSurface",
    "TextConsentSurface",
    "prompt_lines",
    "select_consent_surface",
]


def prompt_lines(prompt: TrustPrompt, *, width: int = 72) -> tuple[str, ...]:
    """The whole question as lines, in reading order.

    Used by the text surface, by the diagnostic that prints a pending prompt, and
    by the test that asserts the graphical dialog shows the same facts. Reading
    order *is* focus order and *is* the order a screen reader announces, because
    they are the same list.
    """
    lines: list[str] = [prompt.headline, ""]
    if prompt.resource_display and prompt.resource_display not in prompt.headline:
        lines.append(prompt.resource_display)
    lines.append(prompt.capability_note)
    if prompt.reason:
        lines.append(prompt.reason)
    elif prompt.reason_note:
        lines.append(prompt.reason_note)
    if prompt.enforcement_note:
        lines.extend(["", prompt.enforcement_note])
    lines.append("")
    for index, (_scope, label) in enumerate(prompt.options, start=1):
        lines.append(f"  {index}. {label}")
    lines.append(f"  {len(prompt.options) + 1}. {DENY_LABEL}   (default)")
    return tuple(lines)


@dataclass
class TextConsentSurface:
    """The question on a terminal. Deny is the default and the only fallback.

    ``input_stream`` and ``output_stream`` are injected so the tests drive it over
    a pipe, which is also how it behaves in a recovery shell. End-of-input, an
    unparseable answer and an out-of-range number all deny — the surface never
    re-prompts in a loop, because a loop is how an automated caller grinds a
    person's terminal until something is allowed.
    """

    input_stream: TextIO = field(default_factory=lambda: sys.stdin)
    output_stream: TextIO = field(default_factory=lambda: sys.stderr)
    #: Set when the surface should not read at all — no controlling terminal.
    #: It then denies immediately and says so, rather than blocking a service.
    interactive: bool = True

    def ask(self, prompt: TrustPrompt, ticket: PromptTicket) -> UserAnswer | None:
        write = self.output_stream.write
        for line in prompt_lines(prompt):
            write(line + "\n")
        if not self.interactive:
            write("No one is here to answer, so Bunny said no.\n")
            self.output_stream.flush()
            return None
        write("Choose a number: ")
        self.output_stream.flush()
        try:
            raw = self.input_stream.readline()
        except (OSError, ValueError):
            return None
        if not raw:
            return None
        choice = raw.strip()
        if not choice:
            return UserAnswer(ticket_id=ticket.ticket_id, verdict="deny")
        try:
            index = int(choice)
        except ValueError:
            return UserAnswer(ticket_id=ticket.ticket_id, verdict="deny")
        if 1 <= index <= len(prompt.options):
            scope = prompt.options[index - 1][0]
            return UserAnswer(ticket_id=ticket.ticket_id, verdict="allow", scope=scope)
        return UserAnswer(ticket_id=ticket.ticket_id, verdict="deny")


@dataclass
class AutomationSurface:
    """Answers from a script. Never selected automatically.

    Exists so the vertical slice and the security tests can drive a whole task
    without a person, and it is deliberately awkward to reach: it is not in
    :func:`select_consent_surface`'s ladder at all, and constructing one is an
    explicit statement in a test file that somebody can grep for.
    """

    answers: Sequence[tuple[str, str, str]] = ()
    asked: list[TrustPrompt] = field(default_factory=list)

    def ask(self, prompt: TrustPrompt, ticket: PromptTicket) -> UserAnswer | None:
        self.asked.append(prompt)
        remaining = list(self.answers)
        for index, (category, verdict, scope) in enumerate(remaining):
            if category == prompt.category:
                del remaining[index]
                self.answers = remaining
                return UserAnswer(ticket_id=ticket.ticket_id, verdict=verdict, scope=scope)
        return None


@dataclass
class GtkConsentSurface:
    """A modal dialog. Constructed lazily so importing this module needs no GTK.

    The layout is the one in :func:`prompt_lines`, in that order, with one button
    per offered scope and ``Don't allow`` last and focused. It is a *modal* window
    because a permission question that can be lost behind another window is a
    question that gets answered by whoever finds it later.

    An exception anywhere in here — no display, a broken theme, a missing
    libadwaita — propagates to :class:`~trust.gate.TrustGate`, which turns it into
    a denial carrying ``surface-failed``. That is deliberate: the gate is where
    "the permission window didn't work, so Bunny said no" is decided, and this
    class must not decide it a second, differently.
    """

    timeout_seconds: float = 110.0

    def ask(self, prompt: TrustPrompt, ticket: PromptTicket) -> UserAnswer | None:  # pragma: no cover - needs a display
        import gi  # type: ignore

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, GLib, Gtk  # type: ignore

        chosen: dict[str, Any] = {"verdict": "deny", "scope": "once"}
        loop = GLib.MainLoop()

        dialog = Adw.MessageDialog(heading=prompt.headline, body="\n".join(prompt_lines(prompt)[2:-len(prompt.options) - 2]))
        for scope, label in prompt.options:
            dialog.add_response(scope, label)
        dialog.add_response("deny", DENY_LABEL)
        dialog.set_response_appearance("deny", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("deny")
        dialog.set_close_response("deny")

        def on_response(_dialog: object, response: str) -> None:
            if response != "deny":
                chosen["verdict"] = "allow"
                chosen["scope"] = response
            loop.quit()

        dialog.connect("response", on_response)
        GLib.timeout_add_seconds(int(self.timeout_seconds), lambda: (loop.quit(), False)[1])
        dialog.present()
        loop.run()
        if chosen["verdict"] == "deny":
            return UserAnswer(ticket_id=ticket.ticket_id, verdict="deny")
        return UserAnswer(ticket_id=ticket.ticket_id, verdict="allow", scope=str(chosen["scope"]))


def select_consent_surface(
    *,
    environment: Mapping[str, str] | None = None,
    text_only: bool = False,
    isatty: Callable[[], bool] | None = None,
) -> ConsentSurface:
    """Pick the surface this machine can actually put a question on.

    ``text_only`` is the accessibility preference from
    :class:`companion.presentation.AccessibilityPreferences` and wins over
    everything: a person who asked for a text-only Companion asked for a text-only
    permission prompt too, and quietly giving them a graphical one would be the
    setting not working.

    The ladder ends at :class:`~trust.gate.DenyingSurface` rather than at a
    graphical surface that might not open. Ending at "deny" is the whole of §22.
    """
    env = dict(environment if environment is not None else os.environ)
    tty = isatty if isatty is not None else (lambda: bool(sys.stdin) and sys.stdin.isatty())
    graphical = bool(env.get("WAYLAND_DISPLAY") or env.get("DISPLAY"))
    if text_only or not graphical:
        if tty():
            return TextConsentSurface()
        # No display and no terminal: a service starting before the session, a
        # cron job, a headless build. There is nowhere to ask.
        return DenyingSurface()
    return GtkConsentSurface()
