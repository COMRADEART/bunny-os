//! Session lock state.
//!
//! BUNNY WAYLAND SHELL EXPERIMENT - NOT RELEASE QUALIFIED - DO NOT USE AS THE
//! DEFAULT SESSION.
//!
//! The lock is fail-closed in both directions. A lock request locks immediately
//! rather than when the lock surfaces arrive, and the loss of the locking
//! client leaves the session locked rather than revealing the desktop.

use std::collections::BTreeSet;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LockState {
    Unlocked,
    /// Locked, and the locking client has not yet covered every output.
    LockingIncomplete,
    /// Locked and every active output is covered.
    Locked,
    /// The locking client vanished while locked. The session stays locked and
    /// only an emergency path may recover it.
    LockedClientGone,
}

impl LockState {
    /// Whether desktop content may be presented to the screen.
    pub fn desktop_visible(self) -> bool {
        matches!(self, LockState::Unlocked)
    }
}

#[derive(Debug, Clone)]
pub struct SessionLock {
    state: LockState,
    /// Outputs that currently have a lock surface.
    covered: BTreeSet<String>,
    /// Outputs that exist and therefore must be covered.
    required: BTreeSet<String>,
}

impl SessionLock {
    pub fn new() -> Self {
        Self {
            state: LockState::Unlocked,
            covered: BTreeSet::new(),
            required: BTreeSet::new(),
        }
    }

    pub fn state(&self) -> LockState {
        self.state
    }

    pub fn set_outputs<I: IntoIterator<Item = String>>(&mut self, names: I) {
        self.required = names.into_iter().collect();
        // An output that disappeared no longer needs covering.
        self.covered.retain(|name| self.required.contains(name));
        self.refresh();
    }

    /// A new output appeared. While locked this immediately makes the lock
    /// incomplete: there is now a display with no lock surface on it.
    pub fn output_added(&mut self, name: impl Into<String>) {
        self.required.insert(name.into());
        self.refresh();
    }

    pub fn output_removed(&mut self, name: &str) {
        self.required.remove(name);
        self.covered.remove(name);
        self.refresh();
    }

    pub fn lock(&mut self) {
        // Lock first, ask questions later. Waiting for surfaces would leave the
        // desktop on screen during the gap.
        self.covered.clear();
        self.state = LockState::LockingIncomplete;
        self.refresh();
    }

    pub fn surface_attached(&mut self, output: impl Into<String>) {
        if self.state == LockState::Unlocked {
            return;
        }
        let name = output.into();
        if self.required.contains(&name) {
            self.covered.insert(name);
        }
        self.refresh();
    }

    /// The locking client died. The desktop must not come back.
    pub fn client_lost(&mut self) {
        if self.state != LockState::Unlocked {
            self.state = LockState::LockedClientGone;
        }
    }

    /// Unlock. Only ever called after the authentication helper confirms
    /// success; the compositor itself never validates a password.
    pub fn unlock(&mut self, authenticated: bool) -> bool {
        if !authenticated {
            return false;
        }
        if self.state == LockState::LockedClientGone {
            // The client that could prove authentication is gone. Refuse.
            return false;
        }
        self.state = LockState::Unlocked;
        self.covered.clear();
        true
    }

    /// Outputs that are required but not covered.
    pub fn uncovered(&self) -> Vec<String> {
        self.required
            .difference(&self.covered)
            .cloned()
            .collect()
    }

    fn refresh(&mut self) {
        match self.state {
            LockState::Unlocked | LockState::LockedClientGone => {}
            _ => {
                self.state = if self.required.is_empty() || !self.uncovered().is_empty() {
                    LockState::LockingIncomplete
                } else {
                    LockState::Locked
                };
            }
        }
    }

    /// Whether desktop content may be drawn on the given output.
    pub fn may_present_desktop(&self, output: &str) -> bool {
        match self.state {
            LockState::Unlocked => true,
            // While locked, an output with no lock surface shows the lock
            // fallback, never the desktop underneath.
            _ => {
                let _ = output;
                false
            }
        }
    }
}

impl Default for SessionLock {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn locked_session() -> SessionLock {
        let mut lock = SessionLock::new();
        lock.set_outputs(["eDP-1".to_string()]);
        lock.lock();
        lock.surface_attached("eDP-1");
        lock
    }

    #[test]
    fn locking_hides_the_desktop_before_any_surface_arrives() {
        let mut lock = SessionLock::new();
        lock.set_outputs(["eDP-1".to_string()]);
        lock.lock();
        assert_eq!(lock.state(), LockState::LockingIncomplete);
        assert!(!lock.state().desktop_visible());
        assert!(!lock.may_present_desktop("eDP-1"));
    }

    #[test]
    fn the_lock_completes_when_every_output_is_covered() {
        let lock = locked_session();
        assert_eq!(lock.state(), LockState::Locked);
        assert!(lock.uncovered().is_empty());
    }

    #[test]
    fn hotplugging_an_output_while_locked_leaves_no_uncovered_area_visible() {
        let mut lock = locked_session();
        lock.output_added("DP-1");
        assert_eq!(lock.state(), LockState::LockingIncomplete);
        assert_eq!(lock.uncovered(), vec!["DP-1".to_string()]);
        // Crucially the new output still does not show the desktop.
        assert!(!lock.may_present_desktop("DP-1"));
        lock.surface_attached("DP-1");
        assert_eq!(lock.state(), LockState::Locked);
    }

    #[test]
    fn losing_the_locking_client_does_not_expose_the_desktop() {
        let mut lock = locked_session();
        lock.client_lost();
        assert_eq!(lock.state(), LockState::LockedClientGone);
        assert!(!lock.state().desktop_visible());
        assert!(!lock.may_present_desktop("eDP-1"));
    }

    #[test]
    fn a_crashed_lock_client_cannot_be_unlocked_by_claiming_success() {
        let mut lock = locked_session();
        lock.client_lost();
        assert!(!lock.unlock(true));
        assert_eq!(lock.state(), LockState::LockedClientGone);
    }

    #[test]
    fn a_failed_authentication_does_not_unlock() {
        let mut lock = locked_session();
        assert!(!lock.unlock(false));
        assert_eq!(lock.state(), LockState::Locked);
    }

    #[test]
    fn a_successful_authentication_unlocks() {
        let mut lock = locked_session();
        assert!(lock.unlock(true));
        assert_eq!(lock.state(), LockState::Unlocked);
        assert!(lock.may_present_desktop("eDP-1"));
    }

    #[test]
    fn removing_an_output_while_locked_completes_the_lock() {
        let mut lock = SessionLock::new();
        lock.set_outputs(["eDP-1".to_string(), "DP-1".to_string()]);
        lock.lock();
        lock.surface_attached("eDP-1");
        assert_eq!(lock.state(), LockState::LockingIncomplete);
        lock.output_removed("DP-1");
        assert_eq!(lock.state(), LockState::Locked);
    }
}
