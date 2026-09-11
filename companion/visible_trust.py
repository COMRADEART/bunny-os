# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Trust prompt as a host-drawable surface, without a GNOME session.

The guest harness presses buttons named ``Allow this Bunny action`` and
``Deny this Bunny action``. This module is the same contract on a development
host: it builds the question with :func:`trust.explain.build_prompt`, draws it
as HTML (and a text fallback), and accepts an answer only by those accessible
names. Nothing here can grant a permission — it returns a
:class:`~trust.gate.UserAnswer` naming a ticket, and the gate checks the ticket.

There is no ``Always allow everything`` option. Deny is the default. Escape,
an unknown name, and silence all deny.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape as html_escape
from pathlib import Path
from typing import Any, Mapping

import trust
from companion.trust_surface import (
    ALLOW_ACCESSIBLE_NAME,
    DENY_ACCESSIBLE_NAME,
    prompt_lines,
)
from trust.audit import TrustAudit
from trust.declaration import PermissionDeclaration
from trust.decision import Decision, Resolution
from trust.explain import DENY_LABEL, TrustPrompt, build_prompt
from trust.gate import PromptTicket, TrustGate, UserAnswer
from trust.store import TrustStore

__all__ = [
    "ALLOW_ACCESSIBLE_NAME",
    "DENY_ACCESSIBLE_NAME",
    "FORBIDDEN_LABELS",
    "JOURNEY_REQUEST",
    "AccessibleNameSurface",
    "JourneyFrame",
    "VISIBLE_STATES",
    "demo_declaration",
    "demo_prompt",
    "drive_by_accessible_name",
    "render_html",
    "render_text",
]

#: The sentence the guest journey types. Kept identical so a host demo and a
#: booted-guest story are the same request.
JOURNEY_REQUEST = "Resize this to 100 pixels wide."

#: Labels that must never appear. An "always allow everything" control would
#: be the whole security model gone.
FORBIDDEN_LABELS = frozenset({
    "Always allow everything",
    "alwaysAllowEverything",
    "Allow all",
    "Always allow all",
})

#: Frames the host demo photographs, in order. Each one is a real state the
#: shell would show; they are not decorative.
VISIBLE_STATES = (
    "idle",
    "thinking",
    "waiting_for_approval",
    "granted",
    "denied",
    "failed",
)

_STATUS = {
    "idle": "Ready. Type a request or press the microphone.",
    "thinking": "Thinking…",
    "waiting_for_approval": "Waiting for permission…",
    "granted": "Permission recorded. Done. I made Pictures/holiday-resized.png "
               "at 100 pixels wide. Your original wasn't changed.",
    "denied": "the request was declined",
    "failed": "the task failed",
}

_CHARACTER = {
    "idle": "idle",
    "thinking": "thinking",
    "waiting_for_approval": "warning",
    "granted": "success",
    "denied": "idle",
    "failed": "error",
}


def demo_declaration() -> PermissionDeclaration:
    return PermissionDeclaration(
        application_id="org.bunny.ImageTool",
        required=frozenset({"files"}),
        optional=frozenset(),
        reasons={"files": "so it can resize the picture you pointed at"},
    )


#: Request ids may only use ``[A-Za-z0-9._-]``. Colons look like the guest
#: approval ids and are refused by the schema — a lesson paid for once already.
_DEMO_REQUEST_ID = "visible-trust-holiday"
_DEMO_PATH = Path("/home/bunny/Pictures/holiday.png")


def demo_prompt(*, pictures: Path | None = None) -> TrustPrompt:
    """The image-resize question, built by the production explainer.

    ``pictures`` is used when the caller has a real fixture. Otherwise the
    resource is the canonical holiday path with ``must_exist=False`` so a host
    without that file can still render the same sentence.
    """
    if pictures is not None:
        target = pictures / "holiday.png"
        if not target.exists():
            pictures.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"\x89PNG\r\n\x1a\nvisible-trust-fixture\n")
        resource = trust.path_resource(target)
    else:
        resource = trust.path_resource(_DEMO_PATH, must_exist=False)
    request = trust.PermissionRequest.build(
        request_id=_DEMO_REQUEST_ID,
        application_id="org.bunny.ImageTool",
        category="files",
        session_id="visible-trust-demo",
        resource=resource,
        purpose="read",
        reason=trust.Reason(source="task", text=JOURNEY_REQUEST),
    )
    resolution = Resolution(
        verdict="prompt",
        reason_code="needs-user",
        offered_scopes=("once", "session"),
    )
    return build_prompt(
        request, resolution, demo_declaration(), application_name="Bunny Image Tool",
    )


def drive_by_accessible_name(name: str) -> str:
    """Map an AT-SPI / ARIA name to a verdict. Unknown names deny.

    The guest harness presses by these strings. A rename here without a
    matching rename in the shell would break the booted slices; a name that
    is not one of the two is treated as a person walking away.
    """
    if name == ALLOW_ACCESSIBLE_NAME:
        return "allow"
    return "deny"


@dataclass
class AccessibleNameSurface:
    """Answers only by the accessible names the guest harness presses.

    Constructing this is an explicit statement that a demo or test is driving
    the prompt. It is not selected automatically — see
    :func:`companion.trust_surface.select_consent_surface`.
    """

    press: str
    asked: list[TrustPrompt] = field(default_factory=list)

    def ask(self, prompt: TrustPrompt, ticket: PromptTicket) -> UserAnswer | None:
        self.asked.append(prompt)
        verdict = drive_by_accessible_name(self.press)
        if verdict == "allow":
            scope = prompt.options[0][0] if prompt.options else "once"
            return UserAnswer(ticket_id=ticket.ticket_id, verdict="allow", scope=scope)
        return UserAnswer(ticket_id=ticket.ticket_id, verdict="deny")


@dataclass(frozen=True)
class JourneyFrame:
    """One photographed state of the visible Trust journey."""

    state: str
    title: str
    status: str
    character: str
    prompt_visible: bool
    focused: str
    html: str
    text: str


def render_text(prompt: TrustPrompt, *, state: str = "waiting_for_approval") -> str:
    """The question as a person would read it on a console."""
    lines = [
        f"Bunny OS  ·  character={_CHARACTER[state]}  ·  {state}",
        _STATUS[state],
        "",
    ]
    if state == "waiting_for_approval":
        lines.extend(prompt_lines(prompt))
        lines.append("")
        lines.append(f"focused: {DENY_ACCESSIBLE_NAME}")
        lines.append(f"buttons: {DENY_ACCESSIBLE_NAME}, {ALLOW_ACCESSIBLE_NAME}")
    return "\n".join(lines)


def render_html(
    prompt: TrustPrompt,
    *,
    state: str = "waiting_for_approval",
    request: str = JOURNEY_REQUEST,
) -> str:
    """A self-contained Trust dialog. Deny is focused. No always-allow."""
    if state not in VISIBLE_STATES:
        raise ValueError(f"unknown visible state: {state!r}")
    body_rows = []
    if prompt.resource_display and prompt.resource_display not in prompt.headline:
        body_rows.append(("resource", prompt.resource_display))
    body_rows.append(("capability", prompt.capability_note))
    if prompt.reason:
        body_rows.append(("reason", prompt.reason))
    elif prompt.reason_note:
        body_rows.append(("reason", prompt.reason_note))
    if prompt.enforcement_note:
        body_rows.append(("enforcement", prompt.enforcement_note))
    confinement = (
        ("Files", "holiday.png only"),
        ("Network", "Off — enforced"),
        ("App data", "Isolated"),
    )
    prompt_block = ""
    if state == "waiting_for_approval":
        rows = "".join(
            f'<p class="row {html_escape(kind)}">{html_escape(text)}</p>'
            for kind, text in body_rows
        )
        confinement_html = "".join(
            f'<li><span class="k">{html_escape(key)}</span>'
            f'<span class="v">{html_escape(value)}</span></li>'
            for key, value in confinement
        )
        prompt_block = f"""
        <section class="trust" role="alertdialog"
                 aria-labelledby="trust-heading"
                 aria-describedby="trust-body"
                 data-safe-default="denied">
          <p class="identity">Bunny Image Tool · curated</p>
          <h1 id="trust-heading">{html_escape(prompt.headline)}</h1>
          <div id="trust-body">
            {rows}
            <ul class="confinement">{confinement_html}</ul>
          </div>
          <div class="actions">
            <button type="button" class="deny focused"
                    autofocus
                    aria-label="{html_escape(DENY_ACCESSIBLE_NAME)}"
                    aria-keyshortcuts="Escape Enter">{html_escape(DENY_LABEL)}</button>
            <button type="button" class="allow"
                    aria-label="{html_escape(ALLOW_ACCESSIBLE_NAME)}">Allow</button>
          </div>
        </section>
        """
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Bunny OS · Trust · {html_escape(state)}</title>
<style>
  :root {{
    --ink: #080B12;
    --panel: #111520;
    --card: #1B1F2D;
    --text: #F7F8FA;
    --muted: #8F96A4;
    --accent: #7C3AED;
    --danger: #F43F5E;
    --ok: #34D399;
    --warn: #F59E0B;
    --ring: #FDE68A;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; background: var(--ink); color: var(--text);
    font: 16px/1.45 "Source Sans 3", "Segoe UI", sans-serif; }}
  .desktop {{ min-height: 100vh; padding: 48px 56px; background:
    radial-gradient(900px 500px at 80% 10%, #2a1848 0%, transparent 55%),
    linear-gradient(180deg, #0c1018 0%, #080B12 100%); }}
  .chrome {{ display: flex; justify-content: space-between; color: var(--muted);
    font-size: 13px; letter-spacing: 0.04em; margin-bottom: 36px; }}
  .stage {{ display: grid; grid-template-columns: 220px 1fr; gap: 36px; align-items: start; }}
  .character {{ width: 180px; height: 180px; border-radius: 40px;
    background: #161320; display: grid; place-items: center;
    box-shadow: 0 0 0 1px #2a2f40, 0 24px 60px rgba(0,0,0,0.45); }}
  .character[data-pose="thinking"] {{ box-shadow: 0 0 0 2px var(--accent), 0 24px 60px rgba(0,0,0,0.45); }}
  .character[data-pose="warning"] {{ box-shadow: 0 0 0 2px var(--warn), 0 24px 60px rgba(0,0,0,0.45); }}
  .character[data-pose="success"] {{ box-shadow: 0 0 0 2px var(--ok), 0 24px 60px rgba(0,0,0,0.45); }}
  .character[data-pose="error"] {{ box-shadow: 0 0 0 2px var(--danger), 0 24px 60px rgba(0,0,0,0.45); }}
  .face {{ font-size: 72px; line-height: 1; }}
  .panel {{ background: var(--panel); border-radius: 20px; padding: 22px 24px 28px;
    box-shadow: 0 24px 60px rgba(0,0,0,0.4); min-height: 360px; }}
  .ask {{ color: var(--muted); font-size: 14px; margin: 0 0 8px; }}
  .user {{ margin: 0 0 16px; font-size: 20px; }}
  .status {{ margin: 0 0 20px; color: var(--muted); }}
  .trust {{ background: var(--card); border-radius: 16px; padding: 20px 22px 18px;
    border: 1px solid #2c3346; }}
  .identity {{ margin: 0 0 6px; color: var(--muted); font-size: 13px; letter-spacing: 0.03em; }}
  h1 {{ margin: 0 0 12px; font-size: 22px; font-weight: 650; }}
  .row {{ margin: 0 0 8px; }}
  .row.reason {{ color: var(--muted); }}
  .row.enforcement {{ color: var(--warn); }}
  .confinement {{ list-style: none; padding: 10px 0 0; margin: 12px 0 0;
    border-top: 1px solid #2c3346; display: grid; gap: 6px; }}
  .confinement li {{ display: flex; justify-content: space-between; font-size: 14px; }}
  .confinement .k {{ color: var(--muted); }}
  .actions {{ display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px; }}
  button {{ appearance: none; border: 0; border-radius: 10px; padding: 8px 16px;
    font: 600 15px/1.2 inherit; cursor: default; }}
  .deny {{ background: #3a1520; color: #fecdd3; }}
  .deny.focused {{ outline: 2px solid var(--ring); outline-offset: 2px; }}
  .allow {{ background: var(--accent); color: white; }}
  .note {{ margin-top: 28px; color: var(--muted); font-size: 12px; }}
</style>
</head>
<body data-state="{html_escape(state)}" data-character="{html_escape(_CHARACTER[state])}">
  <div class="desktop">
    <header class="chrome"><span>Bunny OS · host-visible Trust demo</span>
      <span>deny-by-default · no blanket always-allow</span></header>
    <div class="stage">
      <aside class="character" data-pose="{html_escape(_CHARACTER[state])}"
             aria-label="Bunny is {_CHARACTER[state]}">
        <div class="face">{_face(_CHARACTER[state])}</div>
      </aside>
      <main class="panel">
        <p class="ask">You asked Bunny</p>
        <p class="user">{html_escape(request)}</p>
        <p class="status" aria-live="polite">{html_escape(_STATUS[state])}</p>
        {prompt_block}
      </main>
    </div>
    <p class="note">The Deny control is focused (Return and Escape refuse).
      This is a host rendering of the production TrustPrompt. It is not a
      booted GNOME session, not hardware evidence, and not a release GO.
      There is no blanket always-allow control.</p>
  </div>
</body>
</html>
"""


def _face(pose: str) -> str:
    return {
        "idle": "🐰",
        "thinking": "🤔",
        "warning": "⚠️",
        "success": "✓",
        "error": "✕",
    }.get(pose, "🐰")


def frames_for(prompt: TrustPrompt) -> Mapping[str, JourneyFrame]:
    """Every photographed state, bound to the same prompt."""
    out: dict[str, JourneyFrame] = {}
    for state in VISIBLE_STATES:
        out[state] = JourneyFrame(
            state=state,
            title=f"Bunny OS · Trust · {state}",
            status=_STATUS[state],
            character=_CHARACTER[state],
            prompt_visible=state == "waiting_for_approval",
            focused=DENY_ACCESSIBLE_NAME if state == "waiting_for_approval" else "",
            html=render_html(prompt, state=state),
            text=render_text(prompt, state=state),
        )
    return out


def forbidden_labels_present(html: str) -> list[str]:
    return [label for label in FORBIDDEN_LABELS if label in html]


def decide_journey(press: str, root: Path) -> tuple[Decision, TrustPrompt]:
    """Run the production gate against one accessible-name press.

    Deny-by-default is preserved: an unknown name, including any attempt to
    press a forbidden label, is a denial.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    pictures = root / "Pictures"
    pictures.mkdir(exist_ok=True)
    fixture = pictures / "holiday.png"
    if not fixture.exists():
        fixture.write_bytes(b"\x89PNG\r\n\x1a\nvisible-trust-fixture\n")
    store = TrustStore(root / "trust-store", session_id="visible-trust-demo").load()
    audit = TrustAudit(root / "trust-audit.jsonl", names={"org.bunny.ImageTool": "Bunny Image Tool"})
    surface = AccessibleNameSurface(press=press)
    gate = TrustGate(
        store=store,
        audit=audit,
        surface=surface,
        names={"org.bunny.ImageTool": "Bunny Image Tool"},
    )
    request = trust.PermissionRequest.build(
        request_id=_DEMO_REQUEST_ID,
        application_id="org.bunny.ImageTool",
        category="files",
        session_id="visible-trust-demo",
        resource=trust.path_resource(fixture),
        purpose="read",
        reason=trust.Reason(source="task", text=JOURNEY_REQUEST),
    )
    decision = gate.check(request, declaration=demo_declaration())
    prompt = surface.asked[0] if surface.asked else demo_prompt(pictures=pictures)
    return decision, prompt


def as_record(prompt: TrustPrompt, *, pressed: str, decision: Any) -> dict[str, Any]:
    return {
        "request": JOURNEY_REQUEST,
        "headline": prompt.headline,
        "spoken": prompt.spoken,
        "accessibleNames": [DENY_ACCESSIBLE_NAME, ALLOW_ACCESSIBLE_NAME],
        "focused": DENY_ACCESSIBLE_NAME,
        "pressed": pressed,
        "allowed": bool(getattr(decision, "allowed", False)),
        "reasonCode": getattr(decision, "reason_code", ""),
        "forbiddenLabels": list(FORBIDDEN_LABELS),
    }
