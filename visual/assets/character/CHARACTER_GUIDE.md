# Bunny OS character guide

Bunny OS has one primary visual guide character. He provides a consistent,
human presence across onboarding, assistant education, approval explanations,
diagnostics, tutorials, empty states, and selected system-status screens.

## Canonical appearance

- Adult male technology guide with a youthful appearance.
- Premium stylized 3D-animation aesthetic.
- Dark curly hair, warm brown skin, expressive brown eyes.
- Black minimalist hoodie, fitted black pants, and black canvas sneakers with
  white soles.
- Friendly, intelligent, and calm expression.
- No clothing branding, weapons, armor, or fantasy accessories.

Every asset contains exactly one full-body character. Never place two guide
assets in one composition or generate a multi-pose sheet for product use.

## Interface props

The guide may interact with restrained translucent Bunny OS elements: command
panels, approval cards, progress indicators, system diagrams, code previews,
and completion marks. Props use Bunny Violet, Bunny Sky, and the semantic color
appropriate to the state. They contain recognizable geometry only—never
generated prose, pseudo-code, or unreadable text.

The prop supports the message; it does not replace the real interface. Keep
actual labels, controls, evidence, and consequences in native UI components.

## Placement

Use the guide intentionally in Bunny Welcome, the assistant empty state,
first-run explanations, approval education, diagnostics guidance, offline and
error guidance, and successful task completion. Operational interfaces remain
clean and professional.

- Do not make the guide a permanent desktop decoration.
- Do not show him in every system panel.
- Do not let the illustration cover controls or evidence.
- Prefer one guide moment per screen and preserve generous negative space.
- Hide decorative character art from assistive technology. When the pose adds
  information, give the containing UI a concise state description instead.
- Do not animate continuously. If a transition is used, honor reduced motion.

## State intent

| Asset | Intended message |
| --- | --- |
| `idle-neutral` | Calm default presence when no stronger state is needed. |
| `welcome-wave` | First-run or returning-user welcome. |
| `typing` | The assistant is composing or working with structured input. |
| `pointing-at-interface` | Draw attention to one nearby control or concept. |
| `thinking` | Deliberation without implying an action has begun. |
| `explaining` | Teach a system relationship or workflow. |
| `requesting-approval` | Explain that explicit user authority is required. |
| `task-running` | Work is active; pair with real progress and cancellation UI. |
| `task-completed` | Confirm a successful task result. |
| `warning` | Ask the user to pause and understand a recoverable risk. |
| `error` | Support troubleshooting with calm, evidence-first language. |
| `offline` | Explain limited connectivity without implying the desktop is unusable. |
| `privacy-mode` | Explain active privacy controls and observable device state. |
| `celebrating` | Mark a meaningful milestone with restrained joy. |

`requesting-approval` never substitutes for approval controls and never
preselects consent. `task-completed` and `celebrating` must only appear after
the underlying result has actually been observed.

