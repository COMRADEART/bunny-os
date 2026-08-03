//! Window model and window-management policy.
//!
//! BUNNY WAYLAND SHELL EXPERIMENT - NOT RELEASE QUALIFIED - DO NOT USE AS THE
//! DEFAULT SESSION.

/// A rectangle in logical coordinates.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Rect {
    pub x: i32,
    pub y: i32,
    pub width: i32,
    pub height: i32,
}

impl Rect {
    pub fn new(x: i32, y: i32, width: i32, height: i32) -> Self {
        Self { x, y, width, height }
    }

    pub fn contains(&self, x: i32, y: i32) -> bool {
        x >= self.x && y >= self.y && x < self.x + self.width && y < self.y + self.height
    }
}

/// How a window came to exist. XWayland windows are tracked distinctly so the
/// compatibility report can never describe an X11 client as a native Wayland
/// client.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WindowOrigin {
    Wayland,
    XWayland,
}

impl WindowOrigin {
    pub fn as_str(self) -> &'static str {
        match self {
            WindowOrigin::Wayland => "wayland",
            WindowOrigin::XWayland => "xwayland",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WindowState {
    Normal,
    Maximized,
    Fullscreen,
    Minimized,
}

/// A managed window.
#[derive(Debug, Clone)]
pub struct ManagedWindow {
    pub id: u64,
    pub app_id: String,
    pub title: String,
    pub origin: WindowOrigin,
    pub workspace: usize,
    pub geometry: Rect,
    /// Geometry to restore when leaving maximized or fullscreen.
    pub restore_geometry: Rect,
    pub state: WindowState,
    /// Set for a modal child; the parent must not be focusable while the modal
    /// child is open.
    pub modal_parent: Option<u64>,
    /// Set for a transient (non-modal) child such as a tool window.
    pub transient_parent: Option<u64>,
}

impl ManagedWindow {
    pub fn new(id: u64, app_id: impl Into<String>, geometry: Rect, origin: WindowOrigin) -> Self {
        Self {
            id,
            app_id: app_id.into(),
            title: String::new(),
            origin,
            workspace: 0,
            geometry,
            restore_geometry: geometry,
            state: WindowState::Normal,
            modal_parent: None,
            transient_parent: None,
        }
    }

    pub fn is_mapped(&self) -> bool {
        self.state != WindowState::Minimized
    }

    pub fn maximize(&mut self, area: Rect) {
        if self.state == WindowState::Normal {
            self.restore_geometry = self.geometry;
        }
        self.geometry = area;
        self.state = WindowState::Maximized;
    }

    pub fn fullscreen(&mut self, output: Rect) {
        if self.state == WindowState::Normal {
            self.restore_geometry = self.geometry;
        }
        self.geometry = output;
        self.state = WindowState::Fullscreen;
    }

    pub fn minimize(&mut self) {
        if self.state == WindowState::Normal {
            self.restore_geometry = self.geometry;
        }
        self.state = WindowState::Minimized;
    }

    pub fn restore(&mut self) {
        self.geometry = self.restore_geometry;
        self.state = WindowState::Normal;
    }

    pub fn move_to(&mut self, x: i32, y: i32) {
        self.geometry.x = x;
        self.geometry.y = y;
    }

    pub fn resize(&mut self, width: i32, height: i32) {
        // A zero or negative size is never applied; a client asking for one
        // keeps its previous size rather than vanishing.
        if width > 0 {
            self.geometry.width = width;
        }
        if height > 0 {
            self.geometry.height = height;
        }
    }

    /// The name shown to the user and to assistive technology.
    ///
    /// Falls back to the application identifier, never to an empty string, so
    /// a window is always identifiable.
    pub fn display_name(&self) -> &str {
        if self.title.is_empty() {
            &self.app_id
        } else {
            &self.title
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn window() -> ManagedWindow {
        ManagedWindow::new(1, "org.bunnyos.Test", Rect::new(10, 20, 300, 200), WindowOrigin::Wayland)
    }

    #[test]
    fn maximize_then_restore_returns_the_original_geometry() {
        let mut w = window();
        let original = w.geometry;
        w.maximize(Rect::new(0, 32, 1920, 1000));
        assert_eq!(w.state, WindowState::Maximized);
        w.restore();
        assert_eq!(w.geometry, original);
    }

    #[test]
    fn fullscreen_from_maximized_does_not_lose_the_original_geometry() {
        let mut w = window();
        let original = w.geometry;
        w.maximize(Rect::new(0, 32, 1920, 1000));
        w.fullscreen(Rect::new(0, 0, 1920, 1080));
        w.restore();
        assert_eq!(w.geometry, original);
    }

    #[test]
    fn a_degenerate_resize_is_ignored() {
        let mut w = window();
        w.resize(0, -5);
        assert_eq!(w.geometry.width, 300);
        assert_eq!(w.geometry.height, 200);
    }

    #[test]
    fn a_minimized_window_is_not_mapped() {
        let mut w = window();
        w.minimize();
        assert!(!w.is_mapped());
        w.restore();
        assert!(w.is_mapped());
    }

    #[test]
    fn display_name_never_empties() {
        let w = window();
        assert_eq!(w.display_name(), "org.bunnyos.Test");
    }

    #[test]
    fn xwayland_origin_is_tracked_separately() {
        let w = ManagedWindow::new(2, "xterm", Rect::new(0, 0, 100, 100), WindowOrigin::XWayland);
        assert_eq!(w.origin.as_str(), "xwayland");
    }
}
