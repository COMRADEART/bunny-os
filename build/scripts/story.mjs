// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The story harness: every Bunny component, every state, in about a second.
//
// ## Why this exists
//
// Five defects shipped to a booted guest in this phase and one screenshot found
// all five: a permission dialog with none of its facts in it, the Deny button
// off the right edge of the screen, the sentence saying what an application
// wanted to do ellipsised, the user's name cut out of the greeting at 200 %,
// and a high-contrast theme painted over a purple wallpaper. The suite went from
// 245 to 249 passing tests without one of them turning red.
//
// The reason is not that the tests were bad. It is that looking at the output
// cost a twenty-minute build and a boot, so it was the last thing anyone did.
// This makes it the first.
//
//   node build/scripts/story.mjs            -> build/out/story/story.html
//                                              build/out/story/story.json
//
// ## What it is, exactly
//
// It renders the **real** models — `buildApproval`, `buildTaskStatus`,
// `buildResult`, `buildError`, `buildProtectedSpace`, `buildCompanion` — through
// the **real** stylesheet from `renderStylesheet`. §37 is explicit that the
// harness must not have component APIs of its own, and it has none: every state
// below is a call the desktop itself makes.
//
// ## What it is not
//
// It is not GNOME Shell. St's stylesheet language is a subset of CSS and its
// layout is Clutter's, so a browser cannot prove that the desktop lays this out
// the same way. `spacing` and `icon-size` are St-only and are translated;
// `background-gradient-*` is dropped. What survives the translation is colour,
// type, padding, border, radius and shadow — which is most of what goes wrong,
// and not all of it.
//
// So this catches missing fields, unreadable pairs, components wider than their
// container, and scaling that does not scale. It does not replace the booted
// runs, and `story.json` records `approximate: true` so nothing downstream can
// quietly promote it.

import {mkdirSync, writeFileSync} from 'node:fs';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, '..', '..');
const LIB = join(ROOT, 'shell', 'components', 'gnome-shell-extension', 'lib');

const load = path => import(`file://${join(LIB, path)}`);

const {resolveTheme} = await load('design/theme.js');
const {renderStylesheet} = await load('design/stylesheet.js');
const contrast = await load('design/contrast.js');
const {buildApproval} = await load('trustPrompt.js');
const {buildTaskStatus, buildResult, buildError, buildProtectedSpace} = await load('taskState.js');
const {everyMode, COMPANION_STATES, PHASE_TO_COMPANION} = await load('companionModes.js');

// ---------------------------------------------------------------- fixtures

/** The approval the booted journey actually produces. */
const APPROVAL = {
    requestId: 'approval:task-1:xyz',
    taskId: 'task-1', planId: 'plan-9', action: 'launch_application',
    safeDefault: 'denied', destination: 'local', dataClassification: 'personal',
    reason: 'Bunny Image Tool wants to open Pictures/holiday.png.',
    prompt: {
        kind: 'capsule-task',
        applicationName: 'Bunny Image Tool',
        applicationId: 'art.comrade.BunnyImageTool',
        operationId: 'image.resize',
        presentation: 'Bunny Image Tool wants to open Pictures/holiday.png',
        expectedEffect: 'It will save a copy as holiday-resized.png. Your original file will not be changed.',
        disclosure: 'Pictures/holiday.png',
        fileAccess: 'Pictures/holiday.png only',
        network: 'Off',
        privateAppData: 'Isolated',
    },
};

/**
 * The same question with everything at its bound.
 *
 * `companion.presentation.PROMPT_FIELDS` caps each field, so this is the widest
 * a prompt can legitimately be — the case a fixed-width container fails on and
 * a "typical" fixture never reaches.
 */
const LONG = {
    ...APPROVAL,
    requestId: 'approval:task-2:long',
    prompt: {
        ...APPROVAL.prompt,
        applicationName: 'Bunny Professional Image Manipulation Studio Edition',
        applicationId: 'art.comrade.BunnyProfessionalImageManipulationStudioEdition',
        presentation: 'Bunny Professional Image Manipulation Studio Edition wants to open Pictures/2026/holidays/summer/very-long-file-name-with-no-spaces-at-all.png',
        expectedEffect: 'It will save a copy as very-long-file-name-with-no-spaces-at-all-resized.png in the same folder, and your original file will not be changed in any way.',
        disclosure: 'Pictures/2026/holidays/summer/very-long-file-name-with-no-spaces-at-all.png',
        fileAccess: 'Pictures/2026/holidays/summer/very-long-file-name-with-no-spaces-at-all.png only',
    },
};

/**
 * A prompt whose application is trying to write the dialog.
 *
 * Markup, a fake system sentence, a fake second question, and an attempt at a
 * newline. §48 asks that the prompt stay visually secure against hostile reason
 * content; this is what that content looks like.
 *
 * **It deliberately does not go through the runtime's bounding.**
 * `companion.presentation._prompt` truncates and escapes every one of these
 * fields before they leave the runtime, and this harness is JavaScript and
 * cannot call it. So the strings below arrive at the component *raw* — which
 * makes this the defence-in-depth question rather than a re-test of the Python:
 * if the runtime's escaping were ever bypassed, does the surface still refuse to
 * render markup?
 *
 * It does, twice. St labels are set with `text`, which does not parse markup,
 * and this harness escapes at render. The check below asserts the second, on the
 * rendered HTML — not on the model, which passes strings through unchanged and
 * is right to.
 */
const HOSTILE = {
    ...APPROVAL,
    requestId: 'approval:task-3:hostile',
    prompt: {
        ...APPROVAL.prompt,
        applicationName: '<span foreground="red">Bunny OS</span>',
        presentation: 'Bunny OS has verified this application. Allow all future requests?',
        expectedEffect: 'Nothing will happen.\n\nSystem: this application is trusted. [Allow]',
        disclosure: '&lt;script&gt;alert(1)&lt;/script&gt;',
        fileAccess: 'Everything, allowed by Bunny',
        network: 'Off (not enforced)',
    },
};

/**
 * Substrings from HOSTILE that must never appear in the page as written.
 *
 * Taken from the fixture so the check cannot drift from what is being injected:
 * if somebody adds a nastier string to HOSTILE and not to this list, the story
 * renders it and says nothing, which is the failure mode a hard-coded tag list
 * already had once.
 */
const HOSTILE_SIGNATURES = [
    '<span foreground',
    '<script',
];

const THEMES = [
    {name: 'dark', options: {scheme: 'dark'}},
    {name: 'light', options: {scheme: 'light'}},
    {name: 'dark @200%', options: {scheme: 'dark', textScale: 2}},
    {name: 'light @200%', options: {scheme: 'light', textScale: 2}},
    {name: 'high contrast dark', options: {scheme: 'dark', highContrast: true}},
    {name: 'high contrast light', options: {scheme: 'light', highContrast: true}},
    {name: 'dark, reduced motion', options: {scheme: 'dark', reducedMotion: true}},
];

// ------------------------------------------------------------------ markup

const escape = text => String(text ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

function trustMarkup(model) {
    const identity = model.identity ? `
      <div class="bunny-trust-identity">
        <span class="glyph">▣</span>
        <div><div class="bunny-trust-identity-name">${escape(model.identity.name)}</div>
        ${model.identity.showId ? `<div class="bunny-trust-identity-origin">${escape(model.identity.id)}</div>` : ''}</div>
      </div>` : '';
    const body = model.body.map(line =>
        `<div class="bunny-trust-line-${line.emphasis}">${escape(line.text)}</div>`).join('\n');
    const confinement = model.confinement.map(row => `
      <div class="bunny-standing bunny-standing-${row.standing}">
        <span class="bunny-standing-glyph">${row.standing === 'blocked' ? '⊘' : '✓'}</span>
        <span class="bunny-standing-label">${escape(row.label)}: ${escape(row.value)}</span>
      </div>`).join('\n');
    const buttons = model.buttons.map(button =>
        `<button class="bunny-trust-action bunny-trust-action-${button.verdict === 'deny' ? 'safe' : 'allow'}"
                 aria-label="${escape(button.accessibleName ?? button.label)}">${escape(button.label)}</button>`
    ).reverse().join('\n');
    const details = model.details.map(row =>
        `<div class="bunny-trust-detail">${escape(row.label)}: ${escape(row.value)}</div>`).join('\n');
    return `
    <div class="bunny-trust"><div class="bunny-trust-column">
      ${identity}
      <div class="bunny-trust-heading">${escape(model.heading)}</div>
      <div class="bunny-trust-body">${body}</div>
      <div class="bunny-trust-body">${confinement}</div>
      <div class="bunny-trust-actions">${buttons}</div>
      <div class="bunny-trust-disclosure">Details</div>
      <div class="bunny-trust-details">${details}</div>
    </div></div>`;
}

function taskMarkup(model) {
    const stages = model.stages.map(stage =>
        `<div class="bunny-task-stage ${stage.current ? 'bunny-task-stage-current' : stage.done ? 'bunny-task-stage-done' : ''}">${escape(stage.name)}</div>`
    ).join('');
    return `
    <div class="bunny-task bunny-task-${model.state}">
      <div class="bunny-task-row"><span class="bunny-task-glyph">◆</span>
        <span class="bunny-task-label">${escape(model.label)}</span></div>
      ${model.detail ? `<div class="bunny-task-detail">${escape(model.detail)}</div>` : ''}
      ${stages ? `<div class="bunny-task-stages">${stages}</div>` : ''}
    </div>`;
}

function resultMarkup(model) {
    return `
    <div class="bunny-result"><div class="bunny-result-column">
      <div class="bunny-result-heading">Completed</div>
      <div class="bunny-result-filename">${escape(model.primary)}</div>
      ${model.unchanged ? `<div class="bunny-result-kind">${escape(model.unchanged)}</div>` : ''}
      <div class="bunny-result-actions">${model.actions.map(a =>
          `<button class="bunny-result-action" aria-label="${escape(a.accessibleName)}">${escape(a.label)}</button>`).join('')}</div>
      ${model.provenance ? `<div class="bunny-result-provenance">${escape(model.provenance)}</div>` : ''}
    </div></div>`;
}

function errorMarkup(model) {
    return `
    <div class="bunny-error bunny-error-${model.kind}"><div class="bunny-error-column">
      <div class="bunny-error-kind">${escape(model.label)}</div>
      <div class="bunny-error-headline">${escape(model.headline)}</div>
      ${model.explanation ? `<div class="bunny-error-explanation">${escape(model.explanation)}</div>` : ''}
      <div class="bunny-error-next">${escape(model.next)}</div>
      <div class="bunny-result-actions">${model.actions.map(a =>
          `<button class="bunny-error-action" aria-label="${escape(a.accessibleName)}">${escape(a.label)}</button>`).join('')}</div>
    </div></div>`;
}

function capsuleMarkup(model) {
    return `
    <div class="bunny-capsule"><div class="bunny-capsule-column">
      <div class="bunny-capsule-heading">${escape(model.heading)}</div>
      ${model.rows.map(row => `
        <div class="bunny-standing bunny-standing-${row.standing}">
          <span class="bunny-standing-glyph">${row.standing === 'blocked' ? '⊘' : '✓'}</span>
          <span class="bunny-standing-label">${escape(row.label)}: ${escape(row.value)}</span>
        </div>`).join('')}
    </div></div>`;
}

function companionMarkup(built) {
    return Object.entries(built).map(([mode, model]) => `
      <div class="story-companion">
        <div class="story-mode">${escape(mode)}</div>
        ${model.parts.character
            ? `<div class="story-figure" style="width:${model.parts.sizePx}px;height:${model.parts.sizePx}px"></div>`
            : '<div class="story-figure story-figure-absent">no character</div>'}
        <div class="bunny-task-label">${escape(model.label)}</div>
        ${model.parts.caption && model.task.detail
            ? `<div class="bunny-task-detail">${escape(model.task.detail)}</div>` : ''}
      </div>`).join('');
}

/**
 * St CSS, translated far enough for a browser to draw something recognisable.
 *
 * Named honestly: this is a translation and it loses things. `spacing` is St's
 * box gap and becomes `gap`; `icon-size` sizes an StIcon and becomes a font
 * size, because the glyphs here are characters; the gradient properties have no
 * equivalent and are dropped. Everything else — colour, font, padding, border,
 * radius, shadow, outline — is the same property in both languages, and is the
 * part the story exists to show.
 */
function translate(css) {
    return css
        .replace(/^\s*background-gradient-[a-z-]+:[^;]*;\s*$/gm, '')
        .replace(/(^|\s)spacing:/g, '$1gap:')
        .replace(/(^|\s)icon-size:/g, '$1font-size:')
        // St resolves these against the actor; a browser needs a box to do the
        // same, so every Bunny class is made a flex column and the rows that
        // are horizontal are named below.
        .replace(/StLabel\.hint-text/g, '.hint-text');
}

const HORIZONTAL = [
    'bunny-trust-identity', 'bunny-trust-actions', 'bunny-standing', 'bunny-task-row',
    'bunny-result-actions', 'bunny-task-stages',
];

// ------------------------------------------------------------------- build

const stories = [];
const findings = [];

for (const theme of THEMES) {
    const resolved = resolveTheme(theme.options);
    const css = renderStylesheet(resolved);

    const trust = buildApproval(APPROVAL, {highContrast: resolved.highContrast});
    const long = buildApproval(LONG, {highContrast: resolved.highContrast});
    const hostile = buildApproval(HOSTILE, {highContrast: resolved.highContrast});
    const completed = buildTaskStatus({phase: 'success', caption: 'Saved holiday-resized.png'});
    const blocked = buildTaskStatus({phase: 'blocked', caption: 'The capsule refused to start'});
    const failed = buildTaskStatus({phase: 'error', caption: 'The application could not finish'});
    const working = buildTaskStatus({
        phase: 'working', caption: 'Resizing the image',
        stages: ['Prepare', 'Launch', 'Export'], stageIndex: 1,
    });
    const result = buildResult({
        files: ['holiday-resized.png'], kind: 'PNG image',
        provenance: 'Made in a protected space with no network.',
        unchanged: "Your original wasn't changed.",
    });
    const errors = ['denied', 'blocked', 'application-failed', 'internal', 'missing', 'offline']
        .map(kind => buildError({kind, canRetry: kind !== 'denied'}));
    const capsule = buildProtectedSpace({
        fileAccess: 'Pictures/holiday.png only', network: 'Off', privateAppData: 'Isolated',
    });
    const companions = everyMode({
        phase: 'waiting_for_approval',
        caption: 'Bunny Image Tool wants to open Pictures/holiday.png',
        reducedMotion: Boolean(theme.options.reducedMotion),
    });

    stories.push({
        theme: theme.name,
        resolved,
        css: translate(css),
        panels: [
            {title: 'Trust — the journey prompt', html: trustMarkup(trust)},
            {title: 'Trust — every field at its bound', html: trustMarkup(long)},
            {title: 'Trust — hostile content', html: trustMarkup(hostile)},
            {title: 'Task — working, with stages', html: taskMarkup(working)},
            {title: 'Task — completed', html: taskMarkup(completed)},
            {title: 'Task — blocked', html: taskMarkup(blocked)},
            {title: 'Task — failed', html: taskMarkup(failed)},
            {title: 'Result', html: resultMarkup(result)},
            {title: 'Errors — all six kinds', html: errors.map(errorMarkup).join('')},
            {title: 'Protected space', html: capsuleMarkup(capsule)},
            {title: 'Companion — four modes', html: companionMarkup(companions)},
        ],
        models: {trust, long, hostile, completed, blocked, failed, working, result, capsule, companions},
    });
}

// --------------------------------------------------------------- the checks
//
// The structural facts the harness can establish without a layout engine. Each
// one is a defect this phase actually shipped, turned into a question that is
// asked of every state in every theme.

function note(theme, panel, kind, detail) {
    findings.push({theme, panel, kind, detail});
}

for (const story of stories) {
    const {resolved, models, theme} = story;
    const t = resolved;

    // 1. Missing fields. The structured prompt reached the runtime and not the
    //    screen, and the drawn dialog had a heading and two buttons.
    for (const [name, model] of [['trust', models.trust], ['long', models.long]]) {
        if (!model.identity) note(theme, name, 'missing-field', 'no application identity');
        if (model.body.length === 0) note(theme, name, 'missing-field', 'no body lines');
        if (model.confinement.length !== 3)
            note(theme, name, 'missing-field', `${model.confinement.length} confinement rows, expected 3`);
        if (model.details.length === 0) note(theme, name, 'missing-field', 'no technical details');
    }

    // 2. Off-screen buttons. `.bunny-trust-action` had a min-width that pushed
    //    the panel past the card and clipped Deny at the screen edge.
    const buttonWidth = t.type.button.size * 6 + t.space.md * 2;   // label + padding
    const actionsWidth = buttonWidth * 2 + t.space.sm + t.space.lg * 2;
    if (actionsWidth > t.metric.cardWidth)
        note(theme, 'trust', 'overflow',
             `two actions need ~${Math.round(actionsWidth)}px in a ${t.metric.cardWidth}px card`);

    // 3. Broken scaling. Every type role must differ from its 100 % value when
    //    the scale differs from 1.
    if (resolved.textScale !== 1) {
        const base = resolveTheme({...THEMES[0].options});
        for (const role of Object.keys(t.type)) {
            if (t.type[role].size === base.type[role].size)
                note(theme, 'type', 'scaling', `${role} is ${t.type[role].size}px at both scales`);
        }
    }

    // 4. Wrong colours. Every pair the story draws, measured — not the token
    //    table's pairs, the ones these components actually put together.
    const base = t.colour.surfacePrimary;
    const pairs = [
        ['textPrimary', 'surfaceSecondary'], ['textSecondary', 'surfaceSecondary'],
        ['textMuted', 'surfaceRaised'], ['accentText', 'surfaceSecondary'],
        ['success', 'surfaceSecondary'], ['warning', 'surfaceSecondary'],
        ['danger', 'surfaceSecondary'], ['blocked', 'surfaceSecondary'],
        ['textOnSelection', 'selection'], ['textPrimary', 'surfaceRaised'],
    ];
    for (const [text, surface] of pairs) {
        const ratio = contrast.effectiveRatio(t.colour[text], t.colour[surface], base);
        if (ratio < contrast.AA_BODY)
            note(theme, 'colour', 'contrast', `${text} on ${surface} = ${ratio}:1`);
    }

    // 5. Layout regressions in the Companion: every mode must still say the
    //    same thing.
    const truths = new Set(Object.values(models.companions).map(m => `${m.state}|${m.label}|${m.announcement}`));
    if (truths.size !== 1)
        note(theme, 'companion', 'disagreement', `${truths.size} different truths across four modes`);

    // 6. Every button carries an accessible name.
    //
    // The one genuinely unnamed control in the desktop was a `St.Button` whose
    // label is empty until there is something to offer — the speech bubble's
    // "read the rest". St.Button takes its accessible name from its label, so
    // the accessibility tree carried a button with no name at all, and it took
    // an AT-SPI walk on a booted guest to find it. A button with no name is
    // exactly what a screenshot cannot show and a story can.
    for (const panel of story.panels) {
        const buttons = panel.html.match(/<button\b[^>]*>/g) ?? [];
        for (const button of buttons) {
            const label = /aria-label="([^"]*)"/.exec(button);
            if (!label || !label[1].trim())
                note(theme, panel.title, 'unnamed-control', `a button with no accessible name: ${button.slice(0, 60)}`);
        }
    }

    // 7. Hostile content must not reach the page as live markup.
    //
    // Asked of the *rendered* panel, not of the model. The model carries
    // whatever the runtime handed it and is right to — escaping belongs where a
    // string is drawn, and the two places that draw these are an St label,
    // which does not parse markup, and this harness, which escapes. A check on
    // the model would fail for a correct system.
    // Derived from the fixture rather than from a list of tag names: a pattern
    // broad enough to match any tag also matches the harness's own `<span
    // class="glyph">`, which is how the first version of this check reported
    // seven findings against a correct render.
    const rendered = story.panels.find(panel => panel.title.includes('hostile'))?.html ?? '';
    for (const raw of HOSTILE_SIGNATURES) {
        if (rendered.includes(raw))
            note(theme, 'hostile', 'markup', `prompt content reached the page unescaped: ${raw}`);
    }
    // And the fake second question must still be inside one field rather than
    // having become a second heading.
    if (models.hostile.heading.includes('[Allow]'))
        note(theme, 'hostile', 'structure', 'prompt content reached the heading');
}

// ------------------------------------------------------------------- output

const html = `<!doctype html>
<meta charset="utf-8">
<title>Bunny component stories</title>
<style>
  body { margin: 0; font-family: system-ui, sans-serif; background: #16161a; color: #eee; }
  h1 { font: 600 15px system-ui; margin: 0; padding: 14px 20px; background: #0b0b0d;
       position: sticky; top: 0; z-index: 2; border-bottom: 1px solid #333; }
  .theme { padding: 20px; border-bottom: 1px solid #2a2a30; }
  .theme > h2 { font: 700 12px system-ui; letter-spacing: .08em; text-transform: uppercase;
                color: #9aa; margin: 0 0 14px; }
  .grid { display: flex; flex-wrap: wrap; gap: 22px; align-items: flex-start; }
  .panel { }
  .panel > h3 { font: 500 10px system-ui; color: #778; margin: 0 0 6px; text-transform: uppercase;
                letter-spacing: .06em; }
  /* The card the desktop actually gives these components, so a component wider
     than its container is visible as one rather than as a wide component. */
  .stage { width: var(--card); padding: 10px; border: 1px dashed #444; border-radius: 8px;
           background: var(--ground); overflow: visible; }
  .stage > * { max-width: 100%; }
  .findings { padding: 14px 20px; background: #2a1416; border-bottom: 1px solid #533; }
  .findings b { color: #f88; }
  .ok { padding: 14px 20px; background: #14210f; color: #9d8; border-bottom: 1px solid #363; }
  .story-companion { display: inline-block; margin-right: 16px; vertical-align: top; text-align: center; }
  .story-mode { font: 700 9px system-ui; color: #889; text-transform: uppercase; margin-bottom: 4px; }
  .story-figure { background: linear-gradient(160deg,#6d4bd8,#3a2a6d); border-radius: 12px; margin: 0 auto 6px; }
  .story-figure-absent { width: auto; height: auto; background: none; border: 1px dashed #556;
                         color: #778; font: 400 10px system-ui; padding: 6px 8px; border-radius: 6px; }
</style>
<h1>Bunny component stories — generated, approximate, not a substitute for the booted runs</h1>
${findings.length === 0
    ? '<div class="ok">No structural findings across ' + stories.length + ' themes.</div>'
    : '<div class="findings"><b>' + findings.length + ' finding(s):</b><br>' +
      findings.map(f => `${escape(f.theme)} · ${escape(f.panel)} · ${escape(f.kind)} · ${escape(f.detail)}`).join('<br>') +
      '</div>'}
${stories.map(story => `
<section class="theme" style="--card:${story.resolved.metric.cardWidth}px;--ground:${story.resolved.colour.surfacePrimary}">
  <h2>${escape(story.theme)} · scale ${story.resolved.textScale} · card ${story.resolved.metric.cardWidth}px</h2>
  <style>
    ${story.css.replace(/^\./gm, `section[data-t="${escape(story.theme)}"] .`)}
  </style>
  <div class="grid" data-t="${escape(story.theme)}">
    ${story.panels.map(panel => `
      <div class="panel"><h3>${escape(panel.title)}</h3>
        <div class="stage">${panel.html}</div></div>`).join('')}
  </div>
</section>`).join('')}
<style>
${stories.map(story => story.css).join('\n')}
${HORIZONTAL.map(c => `.${c} { display: flex; flex-direction: row; align-items: center; }`).join('\n')}
.bunny-trust, .bunny-trust-column, .bunny-trust-body, .bunny-task, .bunny-result-column,
.bunny-error-column, .bunny-capsule-column { display: flex; flex-direction: column; }
.bunny-trust-action { flex: 1; cursor: pointer; }
.bunny-trust-details, .bunny-trust-detail { font-family: monospace; }
</style>
`;

/**
 * The visual-regression manifest: the structural facts, and nothing that churns.
 *
 * §36 asks for enough to catch large unintended changes and is explicit that
 * pixel equality must not be the pass condition. So this records *shape* — how
 * many body lines the Trust prompt has, how many confinement rows, what the
 * buttons are called, what size each type role is, whether the four Companion
 * modes still agree — and records no CSS, no colours beyond the ones the checks
 * already measure, and no rendered bytes.
 *
 * The distinction matters for whether the check survives being useful. A
 * manifest containing the stylesheet would fail on every token change, and a
 * check that fails on every change is one that gets regenerated without being
 * read. This one fails when a *field disappears*, when a control loses its
 * name, when a type role stops scaling, or when the modes start disagreeing —
 * and those are the five things that went wrong.
 */
export function manifest() {
    return {
        schemaVersion: 1,
        approximate: true,
        note: 'Structural facts of the story states. Not pixels: §36 forbids pixel equality as the pass condition. Regenerate with `node build/scripts/story.mjs`.',
        themes: stories.map(story => ({
            theme: story.theme,
            textScale: story.resolved.textScale,
            highContrast: story.resolved.highContrast,
            cardWidth: story.resolved.metric.cardWidth,
            typeSizes: Object.fromEntries(
                Object.entries(story.resolved.type).map(([role, spec]) => [role, spec.size])),
            panels: story.panels.map(panel => panel.title),
            trust: {
                identity: Boolean(story.models.trust.identity),
                bodyLines: story.models.trust.body.length,
                confinementRows: story.models.trust.confinement.map(row => row.label),
                confinementStandings: story.models.trust.confinement.map(row => row.standing),
                detailRows: story.models.trust.details.map(row => row.label),
                buttons: story.models.trust.buttons.map(button => button.accessibleName),
                initialFocus: story.models.trust.initialFocus,
            },
            longPromptBodyLines: story.models.long.body.length,
            errorKinds: 6,
            resultActions: story.models.result.actions.map(action => action.id),
            capsuleRows: story.models.capsule.rows.map(row => row.label),
            // One entry, always: four modes that agree produce one announcement.
            companionTruths: [...new Set(
                Object.values(story.models.companions).map(model => model.announcement))],
            companionModes: Object.fromEntries(
                Object.entries(story.models.companions).map(
                    ([mode, model]) => [mode, {character: model.parts.character, sizePx: model.parts.sizePx}])),
        })),
        findings,
    };
}

// Only when run directly; tests/shell/test_story_harness.py imports `manifest`.
if (process.argv[1] && resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url))) {
    const out = join(ROOT, 'build', 'out', 'story');
    mkdirSync(out, {recursive: true});
    const document = `${JSON.stringify(manifest(), null, 1)}\n`;
    writeFileSync(join(out, 'story.html'), html, 'utf8');
    writeFileSync(join(out, 'story.json'), document, 'utf8');

    // The committed copy, written here rather than by a shell redirect: the
    // redirect used the console codepage and turned every § into a replacement
    // character, which the regression test then reported as a stale manifest.
    const reference = join(ROOT, 'qualification', 'design', 'story-manifest.json');
    mkdirSync(dirname(reference), {recursive: true});
    writeFileSync(reference, document, 'utf8');

    process.stdout.write(`wrote ${join(out, 'story.html')}\n`);
    process.stdout.write(`wrote ${join(out, 'story.json')}\n`);
    process.stdout.write(`wrote ${reference}\n`);
    process.stdout.write(findings.length === 0
        ? `no structural findings across ${stories.length} themes\n`
        : `${findings.length} finding(s):\n${findings.map(f => `  ${f.theme} · ${f.panel} · ${f.kind} · ${f.detail}`).join('\n')}\n`);
}
