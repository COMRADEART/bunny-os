//! Workspaces.
//!
//! BUNNY WAYLAND SHELL EXPERIMENT - NOT RELEASE QUALIFIED - DO NOT USE AS THE
//! DEFAULT SESSION.
//!
//! Per-monitor behaviour is stated explicitly rather than left to emerge:
//! workspaces are **global across outputs**. Switching to workspace 2 switches
//! every output at once, matching GNOME rather than the per-output model used
//! by some tiling compositors. The semantics are identical in Regular Mode and
//! Character Mode; the visual mode never changes window management.

use crate::window::ManagedWindow;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WorkspaceScope {
    /// One workspace index shared by every output.
    GlobalAcrossOutputs,
    /// Each output has an independent workspace index. Not implemented in V3.
    PerOutput,
}

#[derive(Debug, Clone)]
pub struct Workspaces {
    count: usize,
    active: usize,
    scope: WorkspaceScope,
}

impl Workspaces {
    pub fn new(count: usize) -> Self {
        Self {
            count: count.max(1),
            active: 0,
            scope: WorkspaceScope::GlobalAcrossOutputs,
        }
    }

    pub fn scope(&self) -> WorkspaceScope {
        self.scope
    }

    pub fn count(&self) -> usize {
        self.count
    }

    pub fn active(&self) -> usize {
        self.active
    }

    /// Switch to a workspace. Out-of-range requests are ignored rather than
    /// clamped, so a stray key binding cannot silently move the user.
    pub fn switch_to(&mut self, index: usize) -> bool {
        if index >= self.count {
            return false;
        }
        self.active = index;
        true
    }

    pub fn switch_next(&mut self) -> usize {
        self.active = (self.active + 1) % self.count;
        self.active
    }

    pub fn switch_previous(&mut self) -> usize {
        self.active = (self.active + self.count - 1) % self.count;
        self.active
    }

    /// Move a window to another workspace. Returns false if the target does not
    /// exist, leaving the window where it was.
    pub fn move_window(&self, window: &mut ManagedWindow, target: usize) -> bool {
        if target >= self.count {
            return false;
        }
        window.workspace = target;
        true
    }

    pub fn is_visible(&self, window: &ManagedWindow) -> bool {
        window.workspace == self.active && window.is_mapped()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::window::{Rect, WindowOrigin};

    fn window(id: u64) -> ManagedWindow {
        ManagedWindow::new(id, "org.bunnyos.Test", Rect::new(0, 0, 100, 100), WindowOrigin::Wayland)
    }

    #[test]
    fn workspaces_are_global_across_outputs() {
        assert_eq!(Workspaces::new(4).scope(), WorkspaceScope::GlobalAcrossOutputs);
    }

    #[test]
    fn switching_out_of_range_is_refused_not_clamped() {
        let mut workspaces = Workspaces::new(4);
        assert!(!workspaces.switch_to(9));
        assert_eq!(workspaces.active(), 0);
    }

    #[test]
    fn switching_wraps_in_both_directions() {
        let mut workspaces = Workspaces::new(3);
        assert_eq!(workspaces.switch_previous(), 2);
        assert_eq!(workspaces.switch_next(), 0);
    }

    #[test]
    fn moving_a_window_to_a_missing_workspace_leaves_it_in_place() {
        let workspaces = Workspaces::new(2);
        let mut w = window(1);
        assert!(!workspaces.move_window(&mut w, 5));
        assert_eq!(w.workspace, 0);
        assert!(workspaces.move_window(&mut w, 1));
        assert_eq!(w.workspace, 1);
    }

    #[test]
    fn only_the_active_workspace_is_visible() {
        let mut workspaces = Workspaces::new(2);
        let mut w = window(1);
        workspaces.move_window(&mut w, 1);
        assert!(!workspaces.is_visible(&w));
        workspaces.switch_to(1);
        assert!(workspaces.is_visible(&w));
    }

    #[test]
    fn a_minimized_window_is_not_visible_even_on_the_active_workspace() {
        let workspaces = Workspaces::new(2);
        let mut w = window(1);
        w.minimize();
        assert!(!workspaces.is_visible(&w));
    }
}
