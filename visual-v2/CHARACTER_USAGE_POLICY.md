# Bunny guide usage policy

> VISUAL PROTOTYPE ONLY
>
> NOT RELEASE QUALIFIED
>
> DO NOT MERGE INTO MAIN

Bunny Desktop has one canonical guide: a young male technology guide with
dark curly hair, warm brown skin, expressive brown eyes, a black minimalist
hoodie, fitted black pants, and black canvas sneakers with white soles. His
expression is calm, friendly, and intelligent. Clothing has no branding and he
has no weapons, armor, or fantasy accessories.

## Product boundary

Character Mode is an optional visual-assistance layer over the same desktop,
action model, settings, applications, and security behavior as Regular Mode.
Only one pose may appear in a surface. The guide stays inside a bounded
illustration region and never covers text, inputs, progress, evidence,
consequences, or approval controls.

Approved surfaces are Assistant, Welcome, approval education, diagnostics
guidance, offline and error explanation, observed task completion, first-run
tutorials, and privacy education. The guide never appears in the top bar,
dock, wallpaper, terminal, file manager, unrelated application windows,
password prompts, authentication dialogs, or every settings page.

Compact layout, FocusMode, and constrained high-scaling layouts suppress the
illustration without changing the selected mode. Regular Mode instantiates no
loader, loads no pose, and reserves no illustration space.

## State truthfulness

The active pose derives from observed UI state. `task-completed` requires
`resultConfirmed=true`; `celebrating` additionally requires
`milestoneConfirmed=true`. `requesting-approval` appears only alongside an
actual approval request and never replaces native approval controls.

Decorative image actors are hidden from accessibility APIs. The containing
region exposes a concise semantic sentence, never a filename or pose slug.
Reduced motion removes character entrance effects. Assets are loaded lazily;
the loader retains at most three recent file icons and clears them on return to
Regular Mode.
