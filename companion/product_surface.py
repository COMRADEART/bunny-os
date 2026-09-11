# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Host-drawable product surfaces: Visual Keys, appearance, routing, memory,
first-run, voice, settings, errors, and Trust. Not a GNOME session and not a
release GO.

These pages exist so a development host can photograph the product vision
without a Fedora guest. Deny-by-default is preserved: there is no
``Always allow everything`` control, no model shop, and no shell.
"""

from __future__ import annotations

from html import escape as html_escape
from typing import Sequence

from companion.appearance import (
    APPEARANCE_MODES,
    AppearanceChoice,
    appearance_blurb,
    appearance_title,
)
from companion.design_tokens import bunny_silhouette_svg, css_custom_properties
from companion.memory_boundary import MEMORY_SCOPE_TITLES, MemoryDecision, MemoryPolicy
from companion.onboarding.model import ONBOARDING_ESSENTIAL_IDS, ONBOARDING_STEPS
from companion.outcome_router import OutcomeExplanation
from companion.settings import settings_nav
from companion.user_copy import UserMessage, disconnected_message, error_message, offline_message
from companion.visual_keys import CORE_VISUAL_KEYS, VisualFrame, frame_for
from companion.voice_story import VoiceStoryReport
from companion.visible_trust import FORBIDDEN_LABELS
from installer.companion_flow import FIRST_RUN_STAGES, INSTALL_STAGES
from trust.explain import DENY_LABEL, SCOPE_LABELS, TrustPrompt

__all__ = [
    "FORBIDDEN_LABELS",
    "CORE_VISUAL_KEYS",
    "forbidden_labels_present",
    "render_appearance_html",
    "render_error_html",
    "render_memory_html",
    "render_onboarding_html",
    "render_router_html",
    "render_settings_html",
    "render_trust_html",
    "render_visual_html",
    "render_voice_html",
    "visual_demo_frames",
]

#: Ordinary-action journey used by the host demo. Each row is a real
#: presentation phase plus an optional tool activity — not decoration.
_VISUAL_SCRIPT: tuple[tuple[str, str, str, bool, str, bool], ...] = (
    ("idle", "", "Ready when you are.", False, "", False),
    ("listening", "", "I'm listening.", True, "", False),
    ("planning", "", "Let me think about that.", False, "", False),
    ("working", "", "Working on it.", False, "", False),
    ("working", "searching", "Looking that up.", False, "", False),
    ("working", "downloading", "Downloading — still on this computer.", False, "", False),
    ("working", "installing", "Installing. I'll ask before anything touches your files.", False, "", False),
    ("working", "reading", "Reading what you pointed at.", False, "", False),
    ("working", "coding", "Writing that for you.", False, "", False),
    ("error", "", "That didn't work. Nothing else was changed.", False, "failed", False),
    ("success", "", "Done.", False, "", False),
    ("waiting_for_approval", "", "I need your OK before I continue.", False, "", False),
    ("blocked", "", "Something needs a look. Nothing has been changed yet.", False, "", False),
    ("idle", "", "You're offline. I'll stay on this computer.", False, "", True),
    ("disconnected", "", "I lost the connection. Work already started is still running.", False, "", False),
)


def visual_demo_frames() -> tuple[VisualFrame, ...]:
    frames = []
    for phase, activity, bubble, listening, error, offline in _VISUAL_SCRIPT:
        frames.append(frame_for(
            phase,
            tool_activity=activity,
            listening=listening,
            error_summary=error,
            bubble_text=bubble,
            offline=offline,
        ))
    return tuple(frames)


def forbidden_labels_present(html: str) -> list[str]:
    return [label for label in FORBIDDEN_LABELS if label in html]


def _bunny_svg(*, ears: str = "rest", mic: bool = False, dim: bool = False) -> str:
    """One silhouette. Pose is ears and glow, never a different character."""
    return bunny_silhouette_svg(ears=ears, mic=mic, dim=dim)


def _css() -> str:
    return f"""
{css_custom_properties()}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; background: var(--surface-primary); color: var(--text-primary);
    font: 16px/1.45 system-ui, "Segoe UI", sans-serif; }}
  .desktop {{ min-height: 100vh; padding: var(--space-xl) var(--space-xxl); }}
  .chrome {{ display: flex; justify-content: space-between; color: var(--text-muted);
    font-size: 13px; letter-spacing: 0.04em; margin-bottom: var(--space-lg); gap: var(--space-md); }}
  .stage {{ display: grid; grid-template-columns: minmax(180px, 220px) minmax(0, 1fr); gap: var(--space-lg); align-items: start; }}
  .character {{ width: 180px; min-height: 180px; height: auto; border-radius: var(--radius-modal);
    background: #161320; display: flex; flex-direction: column; align-items: center; justify-content: center;
    box-shadow: 0 0 0 1px var(--border-strong), 0 24px 60px rgba(0,0,0,0.45);
    position: relative; padding: 16px 12px 18px; gap: 10px;
    transition: box-shadow var(--motion-companion) ease-out, transform var(--motion-companion) ease-out; }}
  .character[data-ears="tilt"] {{ transform: rotate(-4deg); }}
  .character[data-ears="up"] {{ transform: translateY(-4px); }}
  .character[data-dim="true"] {{ filter: grayscale(0.35); }}
  .bunny-face {{ width: 132px; height: 132px; }}
  .bubble {{ position: static; min-width: 0; max-width: 100%;
    background: var(--text-primary); color: var(--surface-primary); border-radius: 16px 16px 16px 4px;
    padding: 10px 14px; font-size: 15px; font-weight: 600;
    box-shadow: 0 12px 30px rgba(0,0,0,0.35); }}
  .bubble.error {{ background: #3a1520; color: #fecdd3; }}
  .bubble.warning, .bubble.approval {{ background: #3a2a10; color: #fde68a; }}
  .bubble.panel {{ max-width: min(420px, 46vw); min-width: 240px; font-weight: 500; }}
  .mic-live {{ position: absolute; right: 10px; top: 10px; left: auto; bottom: auto; font-size: 11px; font-weight: 700;
    letter-spacing: 0.06em; text-transform: uppercase; color: var(--focus);
    background: rgba(8,11,18,0.72); border-radius: 999px; padding: 4px 10px; }}
  .panel {{ background: var(--surface-secondary); border-radius: var(--radius-panel); padding: 22px 24px 28px;
    box-shadow: 0 24px 60px rgba(0,0,0,0.4); min-width: 0; }}
  h1 {{ margin: 0 0 8px; font-size: 22px; font-weight: 650; }}
  h2 {{ margin: 8px 0; font-size: 16px; }}
  .muted {{ color: var(--text-muted); }}
  .grid {{ display: grid; gap: var(--space-md); }}
  .card {{ background: var(--surface-raised); border-radius: var(--radius-card); padding: 14px 16px; border: 1px solid var(--border-strong); }}
  .card.chosen {{ outline: 2px solid var(--accent); outline-offset: 2px; }}
  .pill {{ display: inline-block; border-radius: 999px; padding: 2px 10px; font-size: 12px;
    letter-spacing: 0.04em; background: rgba(255,255,255,0.08); color: var(--text-muted); }}
  .pill.ok {{ background: #143326; color: var(--success); }}
  .pill.warn {{ background: #3a2a10; color: var(--warning); }}
  .pill.no {{ background: #3a1520; color: #fecdd3; }}
  .note {{ margin-top: var(--space-lg); color: var(--text-muted); font-size: 12px; }}
  ul.plain {{ list-style: none; padding: 0; margin: 12px 0 0; display: grid; gap: 8px; }}
  .row {{ display: flex; justify-content: space-between; gap: 16px; flex-wrap: wrap; }}
  .modes {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-md); }}
  .facts {{ display: grid; gap: 8px; margin: 12px 0; }}
  .facts dt {{ font-size: 11px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--text-muted); }}
  .facts dd {{ margin: 0; }}
  .actions {{ display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px; flex-wrap: wrap; }}
  button {{ appearance: none; border: 0; border-radius: var(--radius-control); padding: 8px 16px;
    font: 600 15px/1.2 inherit; min-height: 40px; }}
  .deny {{ background: #3a1520; color: #fecdd3; }}
  .deny.focused {{ outline: 2px solid #FDE68A; outline-offset: 2px; }}
  .allow {{ background: var(--accent); color: var(--text-on-accent); }}
  .allow-once {{ background: transparent; color: var(--text-primary); border: 1px solid var(--border-strong); }}
  @media (max-width: 1366px) {{
    .desktop {{ padding: var(--space-lg) var(--space-xl); }}
    .stage {{ grid-template-columns: 1fr; }}
    .character {{ width: 148px; min-height: 148px; }}
    .bubble {{ max-width: min(420px, 100%); }}
    .modes {{ grid-template-columns: 1fr; }}
  }}
  @media (min-width: 1920px) {{
    .desktop {{ padding: 48px 80px; }}
    .panel {{ max-width: 920px; }}
  }}
"""


def _page(title: str, body: str, *, scene_sky: str = "#0c1018", extra: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html_escape(title)}</title>
<style>
{_css()}
  .desktop {{ background:
    radial-gradient(900px 500px at 80% 10%, {scene_sky} 0%, transparent 55%),
    linear-gradient(180deg, #0c1018 0%, var(--surface-primary) 100%); }}
  {extra}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def _character_block(frame: VisualFrame) -> str:
    bubble_class = "bubble"
    if frame.bubble.kind != "caption":
        bubble_class += f" {frame.bubble.kind}"
    if frame.bubble.surface == "panel":
        bubble_class += " panel"
    mic = '<span class="mic-live" role="status">Mic on</span>' if frame.mic_visible else ""
    return f"""
      <aside class="character" data-pose="{html_escape(frame.character)}"
             data-ears="{html_escape(frame.ears)}" data-dim="{str(frame.dim).lower()}"
             aria-label="Bunny is {html_escape(frame.label)}">
        {_bunny_svg(ears=frame.ears, mic=frame.mic_visible, dim=frame.dim)}
        {mic}
        <div class="{bubble_class}" role="status">{html_escape(frame.bubble.text)}</div>
      </aside>
"""


def render_visual_html(frame: VisualFrame) -> str:
    """Visual Keys: bubble, state, reactive scene. Not a chat panel."""
    activity = f"· activity {html_escape(frame.tool_activity)}" if frame.tool_activity else ""
    body = f"""
  <div class="desktop" data-key="{html_escape(frame.key)}" data-scene="{html_escape(frame.scene.name)}">
    <header class="chrome"><span>Bunny OS · Companion · Visual Keys</span>
      <span>speech bubble · not a chat · {html_escape(frame.scene.motion)} scene</span></header>
    <div class="stage">
      {_character_block(frame)}
      <main class="panel">
        <p class="pill">{html_escape(frame.key)}</p>
        <h1>{html_escape(frame.label)}</h1>
        <p class="muted">Phase <code>{html_escape(frame.presentation_phase)}</code>
          {activity}</p>
        <p>The room is <strong>{html_escape(frame.scene.name)}</strong>.
          Ordinary work stays in this bubble. A long answer would open a task
          panel, not grow the bubble into a chat.</p>
      </main>
    </div>
    <p class="note">Host rendering of the Companion face. Not a booted GNOME
      session, not hardware evidence, not a release GO.</p>
  </div>
"""
    extra = (
        f".character {{ box-shadow: 0 0 0 2px {frame.scene.accent}, "
        f"0 24px 60px rgba(0,0,0,0.45); }}"
    )
    return _page(f"Bunny OS · {frame.label}", body, scene_sky=frame.scene.sky, extra=extra)


def render_appearance_html(choice: AppearanceChoice, *, machine: str) -> str:
    cards = []
    for mode in APPEARANCE_MODES:
        selected = " chosen" if mode is choice.effective else ""
        rec = " · recommended" if mode is choice.recommended else ""
        cards.append(
            f'<article class="card{selected}" data-mode="{html_escape(mode.value)}">'
            f'<p class="pill">{html_escape(mode.value)}</p>'
            f"<h2>{html_escape(appearance_title(mode))}{html_escape(rec)}</h2>"
            f"<p>{html_escape(appearance_blurb(mode))}</p>"
            f"<p class='muted'>eligible {html_escape(choice.eligible_kind)}</p>"
            f"</article>"
        )
    reasons = "".join(f"<li>{html_escape(item)}</li>" for item in choice.reasons[:6])
    body = f"""
  <div class="desktop">
    <header class="chrome"><span>Bunny OS · Appearance</span>
      <span>Full 3D · Lightweight 2D · Minimal · simulated {html_escape(machine)}</span></header>
    <main class="panel">
      <p class="pill">capability recommends · you can override</p>
      <h1>How should Bunny look?</h1>
      <p class="muted">Effective: {html_escape(choice.effective.value)} ·
        chosen: {html_escape(choice.chosen.value)} ·
        recommended: {html_escape(choice.recommended.value)}</p>
      <div class="modes">{"".join(cards)}</div>
      <ul class="plain">{reasons}</ul>
    </main>
    <p class="note">A choice heavier than this machine can honour is kept and
      the drawing is lowered. There is no force-3D. Simulated hardware is labelled.</p>
  </div>
"""
    return _page("Bunny OS · Appearance", body)


def render_router_html(explanations: Sequence[OutcomeExplanation]) -> str:
    cards = []
    for item in explanations:
        tone = "ok" if item.target == "local" else ("warn" if item.target == "remote" else "no")
        cards.append(
            f'<article class="card">'
            f'<p class="pill {tone}">{html_escape(item.target)}</p>'
            f"<h2>{html_escape(item.outcome)}</h2>"
            f"<p>{html_escape(item.headline)}</p>"
            f"<p class='muted'>{html_escape(item.detail)}</p>"
            f"<p class='muted'>locality: {html_escape(item.locality)}</p>"
            f"</article>"
        )
    body = f"""
  <div class="desktop">
    <header class="chrome"><span>Bunny OS · Outcomes</span>
      <span>no model shop · local first · deny by default</span></header>
    <main class="panel">
      <h1>Ask for what you want done, not which engine to use.</h1>
      <div class="grid">{"".join(cards)}</div>
    </main>
    <p class="note">Routing is capability.router. Cloud stays off until allowed.
      A weak machine never argues private work onto a network.</p>
  </div>
"""
    return _page("Bunny OS · Outcomes", body)


def render_memory_html(policy: MemoryPolicy, decisions: Sequence[MemoryDecision]) -> str:
    rows = []
    for item in decisions:
        tone = "ok" if item.allowed else "no"
        verb = "allowed" if item.allowed else "denied"
        title = MEMORY_SCOPE_TITLES.get(item.scope, item.scope)
        rows.append(
            f'<li class="row"><span>{html_escape(title)} · {html_escape(item.classification)}</span>'
            f'<span class="pill {tone}">{verb}</span></li>'
        )
    body = f"""
  <div class="desktop">
    <header class="chrome"><span>Bunny OS · Memory</span>
      <span>deny by default · cloud minimised</span></header>
    <main class="panel">
      <h1>What Bunny may remember</h1>
      <p class="muted">Working memory is the current task. Session, durable and
        cloud stay off until you turn them on.</p>
      <div class="grid">
        <article class="card">
          <p>{html_escape(MEMORY_SCOPE_TITLES["session"])}: <strong>{"on" if policy.session else "off"}</strong></p>
          <p>{html_escape(MEMORY_SCOPE_TITLES["durable"])}: <strong>{"on" if policy.durable else "off"}</strong></p>
          <p>{html_escape(MEMORY_SCOPE_TITLES["cloud"])}: <strong>{html_escape(policy.cloud_context)}</strong></p>
        </article>
      </div>
      <ul class="plain">{"".join(rows)}</ul>
    </main>
    <p class="note">There is no blanket override. Cloud shares need an explicit
      field allow-list and still honour the remote transfer ceiling.</p>
  </div>
"""
    return _page("Bunny OS · Memory", body)


def render_onboarding_html(*, step_index: int = 0) -> str:
    """Consumer first-run copy: Hi I'm Bunny … Ready.

    Uses the production onboarding steps, not a parallel script.
    """
    steps = ONBOARDING_STEPS
    index = max(0, min(int(step_index), len(steps) - 1))
    step = steps[index]
    items = []
    for i, item in enumerate(steps):
        mark = "●" if i == index else "·"
        skippable = "" if item.required or item.step_id in ONBOARDING_ESSENTIAL_IDS else " · skippable"
        items.append(f"<li>{mark} {html_escape(item.title)}{html_escape(skippable)}</li>")
    first_install = INSTALL_STAGES[0].says
    last_first_run = FIRST_RUN_STAGES[-1].says
    frame = frame_for("idle" if step.step_id != "finish" else "success", bubble_text=step.title)
    skip = f'<p class="muted">You can skip this: {html_escape(step.skip)}</p>' if step.skip else ""
    body = f"""
  <div class="desktop">
    <header class="chrome"><span>Bunny OS · First run</span>
      <span>step {index + 1} of {len(steps)} · not a hardware install</span></header>
    <div class="stage">
      {_character_block(frame)}
      <main class="panel">
        <p class="pill">{html_escape(step.step_id)}</p>
        <h1>{html_escape(step.title)}</h1>
        <p>{html_escape(step.body)}</p>
        {skip}
        <p class="muted">Installer still opens with “{html_escape(first_install)}”
          and first-run still ends “{html_escape(last_first_run)}”.</p>
        <ul class="plain muted">{"".join(items)}</ul>
      </main>
    </div>
    <p class="note">Source/demo of the onboarding copy. It does not write a disk
      and does not claim an installed image.</p>
  </div>
"""
    return _page(f"Bunny OS · {step.title}", body)


def render_voice_html(report: VoiceStoryReport) -> str:
    rows = []
    for item in report.steps:
        status = item["status"]
        tone = "ok" if status == "PASS" else ("warn" if status == "NOT_RUN" else "no")
        rows.append(
            f'<li class="row"><span>{item["step"]}. {html_escape(str(item["name"]))}</span>'
            f'<span class="pill {tone}">{html_escape(status)}</span></li>'
        )
    listening = frame_for("listening", listening=True)
    body = f"""
  <div class="desktop">
    <header class="chrome"><span>Bunny OS · Voice path</span>
      <span>Vosk → action → TTS · honest NOT_RUN</span></header>
    <div class="stage">
      {_character_block(listening)}
      <main class="panel">
        <h1>Speak, act, answer — locally</h1>
        <p>Fixture transcript: <strong>{html_escape(report.transcript)}</strong></p>
        <p class="muted">Intent {html_escape(report.intent_kind or "—")} ·
          tool {html_escape(report.planned_tool or "—")} ·
          approval required: {"yes" if report.requires_approval else "no"}</p>
        <ul class="plain">{"".join(rows)}</ul>
      </main>
    </div>
    <p class="note">No GGUF or Vosk model bytes are vendored. A missing
      microphone, library or model is NOT_RUN, not PASS. No unrestricted shell.</p>
  </div>
"""
    return _page("Bunny OS · Voice", body)


def render_settings_html() -> str:
    cards = []
    for item in settings_nav():
        cards.append(
            f'<article class="card" data-section="{html_escape(str(item["id"]))}">'
            f"<h2>{html_escape(str(item['title']))}</h2>"
            f"<p>{html_escape(str(item['blurb']))}</p>"
            f"</article>"
        )
    body = f"""
  <div class="desktop">
    <header class="chrome"><span>Bunny OS · Settings</span>
      <span>user concepts · no credentials · no model shop</span></header>
    <main class="panel">
      <h1>Settings, as you would look for them</h1>
      <p class="muted">Bunny, AI &amp; Models, Privacy, Accessibility — then this
        computer and system, folded away.</p>
      <div class="grid">{"".join(cards)}</div>
    </main>
    <p class="note">This catalog projects existing settings documents. It does
      not add a force-3D switch or an always-allow.</p>
  </div>
"""
    return _page("Bunny OS · Settings", body)


def render_error_html(message: UserMessage | None = None, *, kind: str = "failed") -> str:
    copy = message or error_message(kind=kind)
    if copy.kind == "error":
        frame = frame_for("error", error_summary=copy.headline)
    elif "offline" in copy.headline.casefold():
        frame = frame_for("idle", offline=True, bubble_text=copy.headline)
    elif "lost" in copy.headline.casefold() or "connection" in copy.happened.casefold():
        frame = frame_for("disconnected", bubble_text=copy.headline)
    else:
        frame = frame_for("blocked", bubble_text=copy.headline)
    body = f"""
  <div class="desktop">
    <header class="chrome"><span>Bunny OS · Status</span>
      <span>what happened · what to do · what changed</span></header>
    <div class="stage">
      {_character_block(frame)}
      <main class="panel">
        <h1>{html_escape(copy.headline)}</h1>
        <dl class="facts">
          <div><dt>What happened</dt><dd>{html_escape(copy.happened)}</dd></div>
          <div><dt>What to do</dt><dd>{html_escape(copy.next_step)}</dd></div>
          <div><dt>What changed</dt><dd>{html_escape(copy.changed)}</dd></div>
        </dl>
      </main>
    </div>
    <p class="note">Host rendering of production copy from companion.user_copy.
      Not a guest boot.</p>
  </div>
"""
    return _page(f"Bunny OS · {copy.headline}", body)


def render_trust_html(prompt: TrustPrompt) -> str:
    """Who / what / why / how long, from the production TrustPrompt."""
    first_scope = prompt.options[0][0] if prompt.options else "once"
    duration = {
        "once": "This time only",
        "session": "Until you close this app",
        "always": "Until you change it in Permissions",
    }.get(first_scope, "This time only")
    buttons = []
    for scope, label in prompt.options:
        klass = "allow-once" if scope == "once" else "allow"
        buttons.append(
            f'<button type="button" class="{klass}">{html_escape(label)}</button>'
        )
    buttons.append(
        f'<button type="button" class="deny focused" autofocus>{html_escape(DENY_LABEL)}</button>'
    )
    why = prompt.reason or prompt.reason_note or "It didn't say why."
    frame = frame_for("waiting_for_approval", bubble_text="I need your OK before I continue.")
    body = f"""
  <div class="desktop">
    <header class="chrome"><span>Bunny OS · Permission</span>
      <span>deny by default · no blanket always-allow</span></header>
    <div class="stage">
      {_character_block(frame)}
      <main class="panel">
        <p class="pill">needs your OK</p>
        <h1>{html_escape(prompt.headline)}</h1>
        <dl class="facts">
          <div><dt>Who</dt><dd>{html_escape(prompt.application_name)}</dd></div>
          <div><dt>What</dt><dd>{html_escape(prompt.capability_note)}</dd></div>
          <div><dt>Why</dt><dd>{html_escape(why)}</dd></div>
          <div><dt>How long</dt><dd>{html_escape(duration)}</dd></div>
        </dl>
        <div class="actions">{"".join(buttons)}</div>
      </main>
    </div>
    <p class="note">Labels come from trust.explain.SCOPE_LABELS
      ({html_escape(SCOPE_LABELS["once"])} / {html_escape(SCOPE_LABELS["session"])} /
      {html_escape(DENY_LABEL)}). Don't allow is focused.</p>
  </div>
"""
    return _page("Bunny OS · Permission", body, scene_sky="#2a2210")
