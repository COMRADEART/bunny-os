//! XWayland support, which is optional and off by default.
//!
//! BUNNY WAYLAND SHELL EXPERIMENT - NOT RELEASE QUALIFIED - DO NOT USE AS THE
//! DEFAULT SESSION.
//!
//! The shell must start without XWayland. Enabling it is a security decision,
//! not a convenience one, and the consequences are recorded here next to the
//! code that turns it on.

use crate::diagnostics::Evidence;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum XWaylandState {
    /// Not requested. This is the default.
    Disabled,
    /// Requested but the Xwayland binary is not installed.
    RequestedButUnavailable,
    /// Requested and available.
    Enabled,
}

impl XWaylandState {
    pub fn as_str(self) -> &'static str {
        match self {
            XWaylandState::Disabled => "disabled",
            XWaylandState::RequestedButUnavailable => "requested-but-unavailable",
            XWaylandState::Enabled => "enabled",
        }
    }

    /// Whether the shell can start. It always can: XWayland is never required.
    pub fn shell_can_start(self) -> bool {
        true
    }
}

/// Decide the XWayland state without starting anything.
pub fn resolve(requested: bool, binary_present: bool) -> XWaylandState {
    match (requested, binary_present) {
        (false, _) => XWaylandState::Disabled,
        (true, false) => XWaylandState::RequestedButUnavailable,
        (true, true) => XWaylandState::Enabled,
    }
}

pub fn binary_present() -> bool {
    ["/usr/bin/Xwayland", "/usr/local/bin/Xwayland"]
        .iter()
        .any(|path| std::path::Path::new(path).exists())
}

/// Security and compatibility consequences of enabling XWayland.
///
/// Kept as data so the security report and the test suite read the same list.
pub const CONSEQUENCES: [(&str, &str); 6] = [
    (
        "X11 clients can see each other's input",
        "The X11 security model predates client isolation. Any X11 client connected to the same \
         Xwayland server can read the X11 clipboard, enumerate other X11 windows and, depending on \
         configuration, observe X11 keyboard events. Wayland clients remain isolated; the exposure \
         is between X11 clients.",
    ),
    (
        "Global keyboard grabs become possible again",
        "X11 permits a client to grab the keyboard globally. That is precisely the capability the \
         Wayland design removes.",
    ),
    (
        "Screen capture bypasses the portal for X11 clients",
        "An X11 client can read the X11 root window without a portal dialog, so the consent \
         guarantee that holds for Wayland clients does not hold for X11 ones.",
    ),
    (
        "Scaling is coarser",
        "Xwayland has one X11 screen scale. On a mixed-DPI layout an X11 window is scaled by the \
         compositor rather than rendered at native density, so it looks softer than a Wayland \
         window.",
    ),
    (
        "Application identification is weaker",
        "X11 WM_CLASS is not an app id. Matching an X11 window to a desktop entry is heuristic, \
         which affects the dock's running-application indicators.",
    ),
    (
        "It is a second, large attack surface",
        "Xwayland is an X server. Running it adds that codebase to the session's trusted \
         computing base.",
    ),
];

#[derive(Debug, Clone)]
pub struct XWaylandAssessment {
    pub state: XWaylandState,
    pub evidence: Evidence,
    pub note: &'static str,
}

pub fn assess(state: XWaylandState) -> XWaylandAssessment {
    match state {
        XWaylandState::Disabled => XWaylandAssessment {
            state,
            evidence: Evidence::Observed,
            note: "XWayland was not requested; the shell started without it.",
        },
        XWaylandState::RequestedButUnavailable => XWaylandAssessment {
            state,
            evidence: Evidence::Observed,
            note: "XWayland was requested but the Xwayland binary is absent; the shell started \
                   anyway.",
        },
        XWaylandState::Enabled => XWaylandAssessment {
            state,
            evidence: Evidence::Observed,
            note: "XWayland was requested and the binary is present.",
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn xwayland_is_disabled_unless_requested() {
        assert_eq!(resolve(false, true), XWaylandState::Disabled);
    }

    #[test]
    fn the_shell_starts_in_every_xwayland_state() {
        for state in [
            XWaylandState::Disabled,
            XWaylandState::RequestedButUnavailable,
            XWaylandState::Enabled,
        ] {
            assert!(state.shell_can_start());
        }
    }

    #[test]
    fn a_missing_binary_does_not_block_startup() {
        assert_eq!(resolve(true, false), XWaylandState::RequestedButUnavailable);
        assert!(resolve(true, false).shell_can_start());
    }

    #[test]
    fn every_consequence_is_documented() {
        assert_eq!(CONSEQUENCES.len(), 6);
        for (headline, detail) in CONSEQUENCES {
            assert!(!headline.is_empty());
            assert!(detail.len() > 40);
        }
    }
}
