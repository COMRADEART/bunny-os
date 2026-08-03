export function applyPresentationClasses(actor, presentation) {
    actor.add_style_class_name('bunny-v2-root');
    const classes = {
        'bunny-v2-light': presentation.colorScheme === 'light',
        'bunny-v2-high-contrast': presentation.highContrast === true,
        'bunny-v2-compact': presentation.compact,
        'bunny-v2-focus': presentation.focus,
        'bunny-v2-reduced-motion': presentation.reducedMotion,
        'bunny-v2-regular-mode': presentation.visualMode === 'regular',
        'bunny-v2-character-mode': presentation.visualMode === 'character',
    };
    for (const [name, enabled] of Object.entries(classes))
        enabled ? actor.add_style_class_name(name) : actor.remove_style_class_name(name);
}
