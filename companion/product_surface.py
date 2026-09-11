# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Host-drawable product surfaces: Visual Keys, appearance, routing, memory,
first-run, and the voice story. Not a GNOME session and not a release GO.

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
from companion.memory_boundary import MemoryDecision, MemoryPolicy
from companion.onboarding.model import ONBOARDING_STEPS
from companion.outcome_router import OutcomeExplanation
from companion.visual_keys import VisualFrame, frame_for
from companion.voice_story import VoiceStoryReport
from companion.visible_trust import FORBIDDEN_LABELS
from installer.companion_flow import FIRST_RUN_STAGES, INSTALL_STAGES

__all__ = [
    "FORBIDDEN_LABELS",
    "forbidden_labels_present",
    "render_appearance_html",
    "render_memory_html",
    "render_onboarding_html",
    "render_router_html",
    "render_visual_html",
    "render_voice_html",
    "visual_demo_frames",
]

_FACES = {
    "idle": "🐰",
    "listening": "👂",
    "thinking": "💭",
    "working": "🛠️",
    "searching": "🔎",
    "downloading": "⬇️",
    "installing": "📦",
    "reading": "📖",
    "coding": "⌨️",
    "error": "✕",
    "success": "✓",
}

#: Ordinary-action journey used by the host demo. Each row is a real
#: presentation phase plus an optional tool activity — not decoration.
_VISUAL_SCRIPT: tuple[tuple[str, str, str, bool, str], ...] = (
    ("idle", "", "Ready when you are.", False, ""),
    ("listening", "", "I'm listening.", True, ""),
    ("planning", "", "Let me think about that.", False, ""),
    ("working", "", "Working on it.", False, ""),
    ("working", "searching", "Looking that up.", False, ""),
    ("working", "downloading", "Downloading — still on this computer.", False, ""),
    ("working", "installing", "Installing. I'll ask before anything touches your files.", False, ""),
    ("working", "reading", "Reading what you pointed at.", False, ""),
    ("working", "coding", "Writing that for you.", False, ""),
    ("error", "", "That didn't work. Nothing else was changed.", False, "failed"),
    ("success", "", "Done.", False, ""),
)


def visual_demo_frames() -> tuple[VisualFrame, ...]:
    frames = []
    for phase, activity, bubble, listening, error in _VISUAL_SCRIPT:
        frames.append(frame_for(
            phase,
            tool_activity=activity,
            listening=listening,
            error_summary=error,
            bubble_text=bubble,
        ))
    return tuple(frames)


def forbidden_labels_present(html: str) -> list[str]:
    return [label for label in FORBIDDEN_LABELS if label in html]


def _css() -> str:
    return """
  :root {
    --ink: #080B12; --panel: #111520; --card: #1B1F2D; --text: #F7F8FA;
    --muted: #8F96A4; --accent: #7C3AED; --danger: #F43F5E; --ok: #34D399;
    --warn: #F59E0B;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; background: var(--ink); color: var(--text);
    font: 16px/1.45 "Source Sans 3", "Segoe UI", sans-serif; }
  .desktop { min-height: 100vh; padding: 40px 48px; }
  .chrome { display: flex; justify-content: space-between; color: var(--muted);
    font-size: 13px; letter-spacing: 0.04em; margin-bottom: 28px; }
  .stage { display: grid; grid-template-columns: 220px 1fr; gap: 28px; align-items: start; }
  .character { width: 180px; height: 180px; border-radius: 40px;
    background: #161320; display: grid; place-items: center;
    box-shadow: 0 0 0 1px #2a2f40, 0 24px 60px rgba(0,0,0,0.45); position: relative; }
  .face { font-size: 72px; line-height: 1; }
  .bubble { position: absolute; left: 190px; top: 24px; min-width: 180px; max-width: 280px;
    background: #F7F8FA; color: #080B12; border-radius: 16px 16px 16px 4px;
    padding: 10px 14px; font-size: 15px; font-weight: 600;
    box-shadow: 0 12px 30px rgba(0,0,0,0.35); }
  .bubble.error { background: #3a1520; color: #fecdd3; }
  .panel { background: var(--panel); border-radius: 20px; padding: 22px 24px 28px;
    box-shadow: 0 24px 60px rgba(0,0,0,0.4); }
  h1 { margin: 0 0 8px; font-size: 22px; font-weight: 650; }
  h2 { margin: 8px 0; font-size: 16px; }
  .muted { color: var(--muted); }
  .grid { display: grid; gap: 12px; }
  .card { background: var(--card); border-radius: 14px; padding: 14px 16px; border: 1px solid #2c3346; }
  .card.chosen { outline: 2px solid var(--accent); }
  .pill { display: inline-block; border-radius: 999px; padding: 2px 10px; font-size: 12px;
    letter-spacing: 0.04em; background: #2a2f40; color: var(--muted); }
  .pill.ok { background: #143326; color: var(--ok); }
  .pill.warn { background: #3a2a10; color: var(--warn); }
  .pill.no { background: #3a1520; color: #fecdd3; }
  .note { margin-top: 24px; color: var(--muted); font-size: 12px; }
  ul.plain { list-style: none; padding: 0; margin: 12px 0 0; display: grid; gap: 8px; }
  .row { display: flex; justify-content: space-between; gap: 16px; }
  .modes { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
"""


def _page(title: str, body: str, *, scene_sky: str = "#0c1018", extra: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html_escape(title)}</title>
<style>
{_css()}
  .desktop {{ background:
    radial-gradient(900px 500px at 80% 10%, {scene_sky} 0%, transparent 55%),
    linear-gradient(180deg, #0c1018 0%, #080B12 100%); }}
  {extra}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def render_visual_html(frame: VisualFrame) -> str:
    """Visual Keys 1–3: bubble, state, reactive scene. Not a chat panel."""
    sky = frame.scene.sky
    bubble_class = "bubble error" if frame.bubble.kind == "error" else "bubble"
    activity = f"· activity {html_escape(frame.tool_activity)}" if frame.tool_activity else ""
    body = f"""
  <div class="desktop" data-key="{html_escape(frame.key)}" data-scene="{html_escape(frame.scene.name)}">
    <header class="chrome"><span>Bunny OS · Companion · Visual Keys</span>
      <span>speech bubble · not a chat · {html_escape(frame.scene.motion)} scene</span></header>
    <div class="stage">
      <aside class="character" data-pose="{html_escape(frame.character)}"
             aria-label="Bunny is {html_escape(frame.label)}">
        <div class="face">{_FACES.get(frame.key, "🐰")}</div>
        <div class="{bubble_class}" role="status">{html_escape(frame.bubble.text)}</div>
      </aside>
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
    return _page(f"Bunny OS · {frame.label}", body, scene_sky=sky, extra=extra)


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
        rows.append(
            f'<li class="row"><span>{html_escape(item.scope)} · {html_escape(item.classification)}</span>'
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
          <p>Session: <strong>{"on" if policy.session else "off"}</strong></p>
          <p>Durable: <strong>{"on" if policy.durable else "off"}</strong></p>
          <p>Cloud context: <strong>{html_escape(policy.cloud_context)}</strong></p>
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
        items.append(f"<li>{mark} {html_escape(item.title)}</li>")
    first_install = INSTALL_STAGES[0].says
    last_first_run = FIRST_RUN_STAGES[-1].says
    snippet = step.body.split(".")[0] + "."
    body = f"""
  <div class="desktop">
    <header class="chrome"><span>Bunny OS · First run</span>
      <span>step {index + 1} of {len(steps)} · not a hardware install</span></header>
    <div class="stage">
      <aside class="character" aria-label="Bunny is greeting you">
        <div class="face">🐰</div>
        <div class="bubble" role="status">{html_escape(snippet)}</div>
      </aside>
      <main class="panel">
        <p class="pill">{html_escape(step.step_id)}</p>
        <h1>{html_escape(step.title)}</h1>
        <p>{html_escape(step.body)}</p>
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
    body = f"""
  <div class="desktop">
    <header class="chrome"><span>Bunny OS · Voice path</span>
      <span>Vosk → action → TTS · honest NOT_RUN</span></header>
    <main class="panel">
      <h1>Speak, act, answer — locally</h1>
      <p>Fixture transcript: <strong>{html_escape(report.transcript)}</strong></p>
      <p class="muted">Intent {html_escape(report.intent_kind or "—")} ·
        tool {html_escape(report.planned_tool or "—")} ·
        approval required: {"yes" if report.requires_approval else "no"}</p>
      <ul class="plain">{"".join(rows)}</ul>
    </main>
    <p class="note">No GGUF or Vosk model bytes are vendored. A missing
      microphone, library or model is NOT_RUN, not PASS. No unrestricted shell.</p>
  </div>
"""
    return _page("Bunny OS · Voice", body)


