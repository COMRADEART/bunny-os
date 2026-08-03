export const APPROVED_POSES = Object.freeze([
    'idle-neutral',
    'welcome-wave',
    'typing',
    'pointing-at-interface',
    'thinking',
    'explaining',
    'requesting-approval',
    'task-running',
    'task-completed',
    'warning',
    'error',
    'offline',
    'privacy-mode',
    'celebrating',
]);

const DESCRIPTIONS = Object.freeze({
    'idle-neutral': 'Bunny is ready to help.',
    'welcome-wave': 'Bunny is welcoming you.',
    typing: 'Bunny is preparing a response.',
    'pointing-at-interface': 'Bunny is pointing out an interface control.',
    thinking: 'Bunny is planning the next step.',
    explaining: 'Bunny is explaining how the system works.',
    'requesting-approval': 'Bunny is explaining that approval is required.',
    'task-running': 'Bunny is monitoring an active task.',
    'task-completed': 'Bunny is confirming an observed successful result.',
    warning: 'Bunny is explaining a recoverable concern.',
    error: 'Bunny is explaining a confirmed failure.',
    offline: 'Bunny is explaining that the network is offline.',
    'privacy-mode': 'Bunny is explaining active privacy controls.',
    celebrating: 'Bunny is celebrating a confirmed milestone.',
});


export function poseForState(state, context = {}) {
    if (state.bunnyEnabled === false)
        return null;
    if (context.welcome)
        return 'welcome-wave';
    if (context.privacyExplanation)
        return 'privacy-mode';
    if (context.explaining)
        return 'explaining';

    const assistantState = String(state.assistantState ?? 'Ready').toLocaleLowerCase();
    if (assistantState === 'waiting for approval')
        return state.approvals.length ? 'requesting-approval' : 'thinking';
    if (assistantState === 'completed')
        return state.resultConfirmed === true ? 'task-completed' : 'task-running';
    if (assistantState === 'celebrating')
        return state.resultConfirmed === true && state.milestoneConfirmed === true ? 'celebrating' : 'task-running';
    return {
        ready: 'idle-neutral',
        thinking: 'thinking',
        typing: 'typing',
        running: 'task-running',
        failed: 'error',
        warning: 'warning',
        offline: 'offline',
        'local only': 'idle-neutral',
    }[assistantState] ?? 'idle-neutral';
}


export function descriptionForPose(pose) {
    return DESCRIPTIONS[pose] ?? 'Bunny is providing visual guidance.';
}
