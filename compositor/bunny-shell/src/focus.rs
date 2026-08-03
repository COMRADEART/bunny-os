//! Focus policy.
//!
//! BUNNY WAYLAND SHELL EXPERIMENT - NOT RELEASE QUALIFIED - DO NOT USE AS THE
//! DEFAULT SESSION.
//!
//! Focus is decided here and nowhere else. Two rules matter most:
//!
//! 1. Notifications and the assistant panel never steal focus. They are shell
//!    surfaces that appear while the user is working, and taking the keyboard
//!    from a user mid-sentence is both hostile and a security problem — the
//!    next keystrokes would land somewhere the user did not choose.
//! 2. The guide character is never focusable. It carries no controls, so
//!    focusing it would strand keyboard and screen-reader users on an element
//!    they cannot act on.

/// Every kind of surface that can ask for focus.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FocusTarget {
    /// An ordinary application window.
    Window(u64),
    /// A shell surface that legitimately takes focus when the user opens it.
    /// The command palette, the launcher and Quick Settings are user-invoked.
    ShellSurfaceInteractive(ShellSurface),
    /// A shell surface that must never take focus on its own.
    ShellSurfacePassive(ShellSurface),
    /// The lock screen. While locked this is the only focusable thing.
    LockScreen,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ShellSurface {
    TopBar,
    Dock,
    Launcher,
    CommandPalette,
    QuickSettings,
    NotificationCenter,
    NotificationBanner,
    AssistantPanel,
    ApprovalPanel,
    Overview,
    /// The bounded illustration component that draws the guide character.
    CharacterLayer,
}

impl ShellSurface {
    /// Whether this surface is ever allowed to hold keyboard focus.
    ///
    /// The character layer is the one surface that can never be focused under
    /// any circumstances.
    pub fn focusable(self) -> bool {
        !matches!(self, ShellSurface::CharacterLayer)
    }

    /// Whether this surface may take focus *without* a direct user action.
    /// Nothing may.
    pub fn may_steal_focus(self) -> bool {
        false
    }
}

/// Why a focus request was refused.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FocusRefusal {
    /// The session is locked; only the lock screen may hold focus.
    SessionLocked,
    /// The surface is never focusable (the guide character).
    SurfaceNeverFocusable,
    /// The surface asked for focus without a user action.
    WouldStealFocus,
    /// A modal child is open; its parent cannot be focused.
    BlockedByModalChild(u64),
    /// The window is on another workspace or minimized.
    NotVisible,
}

/// What caused the focus request.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FocusCause {
    /// The user clicked, tabbed, or pressed the surface's key binding.
    UserAction,
    /// The surface appeared by itself — a notification arriving, an assistant
    /// state change, an application requesting activation.
    SurfaceRequest,
}

#[derive(Debug, Default)]
pub struct FocusPolicy {
    locked: bool,
    focused: Option<FocusTarget>,
}

impl FocusPolicy {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn focused(&self) -> Option<FocusTarget> {
        self.focused
    }

    pub fn set_locked(&mut self, locked: bool) {
        self.locked = locked;
        if locked {
            // Fail closed: locking drops focus immediately rather than waiting
            // for the lock surface to arrive.
            self.focused = Some(FocusTarget::LockScreen);
        } else {
            self.focused = None;
        }
    }

    pub fn locked(&self) -> bool {
        self.locked
    }

    /// Decide a focus request.
    ///
    /// `modal_child` is the id of a modal window blocking the requested window,
    /// if any. `visible` reports whether the requested window is on the active
    /// workspace and mapped.
    pub fn request(
        &mut self,
        target: FocusTarget,
        cause: FocusCause,
        modal_child: Option<u64>,
        visible: bool,
    ) -> Result<FocusTarget, FocusRefusal> {
        if self.locked && target != FocusTarget::LockScreen {
            return Err(FocusRefusal::SessionLocked);
        }

        match target {
            FocusTarget::ShellSurfacePassive(surface) | FocusTarget::ShellSurfaceInteractive(surface)
                if !surface.focusable() =>
            {
                return Err(FocusRefusal::SurfaceNeverFocusable);
            }
            FocusTarget::ShellSurfacePassive(_) if cause == FocusCause::SurfaceRequest => {
                return Err(FocusRefusal::WouldStealFocus);
            }
            FocusTarget::Window(_) if cause == FocusCause::SurfaceRequest => {
                // An application asking for activation does not get the
                // keyboard. xdg-activation is honoured as attention, not focus.
                return Err(FocusRefusal::WouldStealFocus);
            }
            FocusTarget::Window(_) if !visible => {
                return Err(FocusRefusal::NotVisible);
            }
            FocusTarget::Window(_) => {
                if let Some(child) = modal_child {
                    return Err(FocusRefusal::BlockedByModalChild(child));
                }
            }
            _ => {}
        }

        self.focused = Some(target);
        Ok(target)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_character_layer_can_never_take_keyboard_focus() {
        let mut policy = FocusPolicy::new();
        for cause in [FocusCause::UserAction, FocusCause::SurfaceRequest] {
            let result = policy.request(
                FocusTarget::ShellSurfaceInteractive(ShellSurface::CharacterLayer),
                cause,
                None,
                true,
            );
            assert_eq!(result, Err(FocusRefusal::SurfaceNeverFocusable));
        }
        assert!(policy.focused().is_none());
    }

    #[test]
    fn a_notification_never_steals_focus() {
        let mut policy = FocusPolicy::new();
        let result = policy.request(
            FocusTarget::ShellSurfacePassive(ShellSurface::NotificationBanner),
            FocusCause::SurfaceRequest,
            None,
            true,
        );
        assert_eq!(result, Err(FocusRefusal::WouldStealFocus));
    }

    #[test]
    fn the_assistant_panel_never_steals_focus() {
        let mut policy = FocusPolicy::new();
        let result = policy.request(
            FocusTarget::ShellSurfacePassive(ShellSurface::AssistantPanel),
            FocusCause::SurfaceRequest,
            None,
            true,
        );
        assert_eq!(result, Err(FocusRefusal::WouldStealFocus));
    }

    #[test]
    fn the_command_palette_takes_focus_when_the_user_opens_it() {
        let mut policy = FocusPolicy::new();
        let result = policy.request(
            FocusTarget::ShellSurfaceInteractive(ShellSurface::CommandPalette),
            FocusCause::UserAction,
            None,
            true,
        );
        assert!(result.is_ok());
    }

    #[test]
    fn an_application_cannot_grab_the_keyboard_by_requesting_activation() {
        let mut policy = FocusPolicy::new();
        let result = policy.request(FocusTarget::Window(7), FocusCause::SurfaceRequest, None, true);
        assert_eq!(result, Err(FocusRefusal::WouldStealFocus));
    }

    #[test]
    fn a_modal_child_blocks_its_parent() {
        let mut policy = FocusPolicy::new();
        let result = policy.request(FocusTarget::Window(1), FocusCause::UserAction, Some(2), true);
        assert_eq!(result, Err(FocusRefusal::BlockedByModalChild(2)));
    }

    #[test]
    fn nothing_but_the_lock_screen_is_focusable_while_locked() {
        let mut policy = FocusPolicy::new();
        policy.set_locked(true);
        assert_eq!(policy.focused(), Some(FocusTarget::LockScreen));
        let result = policy.request(FocusTarget::Window(1), FocusCause::UserAction, None, true);
        assert_eq!(result, Err(FocusRefusal::SessionLocked));
        assert_eq!(policy.focused(), Some(FocusTarget::LockScreen));
    }

    #[test]
    fn locking_drops_focus_immediately() {
        let mut policy = FocusPolicy::new();
        policy
            .request(FocusTarget::Window(1), FocusCause::UserAction, None, true)
            .unwrap();
        policy.set_locked(true);
        assert_eq!(policy.focused(), Some(FocusTarget::LockScreen));
    }

    #[test]
    fn an_invisible_window_cannot_be_focused() {
        let mut policy = FocusPolicy::new();
        let result = policy.request(FocusTarget::Window(1), FocusCause::UserAction, None, false);
        assert_eq!(result, Err(FocusRefusal::NotVisible));
    }

    #[test]
    fn no_shell_surface_may_steal_focus() {
        for surface in [
            ShellSurface::TopBar,
            ShellSurface::Dock,
            ShellSurface::Launcher,
            ShellSurface::CommandPalette,
            ShellSurface::QuickSettings,
            ShellSurface::NotificationCenter,
            ShellSurface::NotificationBanner,
            ShellSurface::AssistantPanel,
            ShellSurface::ApprovalPanel,
            ShellSurface::Overview,
            ShellSurface::CharacterLayer,
        ] {
            assert!(!surface.may_steal_focus());
        }
    }
}
