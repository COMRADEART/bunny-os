//! Accessibility state and the honest limits of it.
//!
//! BUNNY WAYLAND SHELL EXPERIMENT - NOT RELEASE QUALIFIED - DO NOT USE AS THE
//! DEFAULT SESSION.
//!
//! A compositor is not an accessibility stack. On GNOME, AT-SPI reaches the
//! shell because GNOME Shell exposes its own UI through GTK/Clutter's
//! accessibility implementation. A Smithay compositor inherits none of that.
//!
//! The consequence, stated plainly: shell chrome drawn *by the compositor* is
//! invisible to a screen reader. Bunny's answer is to draw no chrome in the
//! compositor — the top bar, dock, launcher and panels are GTK 4 layer-shell
//! clients, and GTK carries their accessibility. This module tracks the
//! settings the compositor itself must honour and records what remains
//! unreachable.

use crate::diagnostics::Evidence;

#[derive(Debug, Clone, PartialEq)]
pub struct AccessibilityState {
    pub high_contrast: bool,
    pub large_text: bool,
    pub reduced_motion: bool,
    /// Interface scale, where 2.0 is the 200% requirement.
    pub text_scale: f64,
    pub sticky_keys: bool,
    pub slow_keys: bool,
    pub mouse_keys: bool,
    pub magnification: f64,
    /// Whether a visible focus ring is always drawn, including for pointer
    /// users. Off by default in most desktops; on here, because a focus ring
    /// that appears only for keyboard users hides focus bugs.
    pub always_visible_focus: bool,
}

impl Default for AccessibilityState {
    fn default() -> Self {
        Self {
            high_contrast: false,
            large_text: false,
            reduced_motion: false,
            text_scale: 1.0,
            sticky_keys: false,
            slow_keys: false,
            mouse_keys: false,
            magnification: 1.0,
            always_visible_focus: true,
        }
    }
}

impl AccessibilityState {
    /// Whether any animation may play.
    pub fn animations_allowed(&self) -> bool {
        !self.reduced_motion
    }

    /// The duration an animation should take, in milliseconds.
    ///
    /// Reduced motion returns zero rather than a short duration: a fast
    /// animation is still an animation, and the setting means "none".
    pub fn animation_duration_ms(&self, requested: u32) -> u32 {
        if self.reduced_motion {
            0
        } else {
            requested
        }
    }

    pub fn magnification_active(&self) -> bool {
        self.magnification > 1.0
    }
}

/// The accessibility architecture available to a non-GNOME shell, and whether
/// this prototype could actually reach it.
#[derive(Debug, Clone)]
pub struct AccessibilityCapability {
    pub name: &'static str,
    pub mechanism: &'static str,
    pub evidence: Evidence,
    pub note: &'static str,
}

/// Assessed capabilities. Anything not measured says so.
pub fn capabilities() -> Vec<AccessibilityCapability> {
    vec![
        AccessibilityCapability {
            name: "screen reader reaches shell chrome",
            mechanism: "AT-SPI via GTK 4 layer-shell clients",
            evidence: Evidence::Inferred,
            note: "The chrome is GTK, and GTK exposes AT-SPI. A real Orca session was not run in \
                   this environment, so parity is not claimed.",
        },
        AccessibilityCapability {
            name: "screen reader reaches compositor-drawn surfaces",
            mechanism: "none",
            evidence: Evidence::Unsupported,
            note: "Surfaces drawn by the compositor have no accessible representation. V3 avoids \
                   drawing chrome in the compositor for exactly this reason.",
        },
        AccessibilityCapability {
            name: "keyboard navigation of shell surfaces",
            mechanism: "GTK focus handling inside each layer-shell client",
            evidence: Evidence::Inferred,
            note: "Focus order is GTK's. The compositor guarantees only that the character layer \
                   is never focusable and that panels never steal focus.",
        },
        AccessibilityCapability {
            name: "visible focus indicator",
            mechanism: "compositor focus policy plus GTK focus ring",
            evidence: Evidence::Observed,
            note: "The compositor tracks a single focus target and refuses focus changes that no \
                   user action caused.",
        },
        AccessibilityCapability {
            name: "high contrast",
            mechanism: "GTK theme selection in shell clients",
            evidence: Evidence::Inferred,
            note: "Carried from the V2 token set; not re-measured against a contrast analyser in \
                   V3.",
        },
        AccessibilityCapability {
            name: "200% scaling",
            mechanism: "wp-fractional-scale-v1 and GTK text scale",
            evidence: Evidence::Observed,
            note: "Output scaling is implemented and unit tested; a 4K output at 200% resolves to \
                   1920x1080 logical.",
        },
        AccessibilityCapability {
            name: "reduced motion",
            mechanism: "compositor setting honoured by shell clients",
            evidence: Evidence::Observed,
            note: "Reduced motion returns a zero animation duration rather than a shortened one.",
        },
        AccessibilityCapability {
            name: "sticky keys, slow keys, mouse keys",
            mechanism: "libinput and xkbcommon",
            evidence: Evidence::Unavailable,
            note: "These are seat-level features. The nested winit backend does not expose a \
                   libinput seat, so they could not be exercised in this environment.",
        },
        AccessibilityCapability {
            name: "magnification",
            mechanism: "compositor output transform",
            evidence: Evidence::Unsupported,
            note: "A compositor can magnify by scaling its output transform. V3 models the setting \
                   but does not implement the render path.",
        },
        AccessibilityCapability {
            name: "accessible lock screen",
            mechanism: "GTK lock client over ext-session-lock-v1",
            evidence: Evidence::Inferred,
            note: "The lock surface is a GTK client so it carries AT-SPI, but no assistive \
                   technology session was run against a locked screen.",
        },
    ]
}

/// True only if every listed capability was actually observed.
///
/// Used to keep any report from claiming parity on inference.
pub fn parity_claimable() -> bool {
    capabilities().iter().all(|c| c.evidence.is_fact())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reduced_motion_means_no_animation_not_a_fast_one() {
        let state = AccessibilityState {
            reduced_motion: true,
            ..Default::default()
        };
        assert_eq!(state.animation_duration_ms(250), 0);
        assert!(!state.animations_allowed());
    }

    #[test]
    fn focus_is_visible_by_default() {
        assert!(AccessibilityState::default().always_visible_focus);
    }

    #[test]
    fn accessibility_parity_with_gnome_is_not_claimable() {
        // This must stay false until real assistive-technology sessions pass.
        assert!(!parity_claimable());
    }

    #[test]
    fn unmeasured_capabilities_are_marked_rather_than_assumed() {
        let seat_features = capabilities()
            .into_iter()
            .find(|c| c.name == "sticky keys, slow keys, mouse keys")
            .expect("capability listed");
        assert_eq!(seat_features.evidence, Evidence::Unavailable);
    }

    #[test]
    fn compositor_drawn_surfaces_are_declared_unsupported_for_screen_readers() {
        let entry = capabilities()
            .into_iter()
            .find(|c| c.name == "screen reader reaches compositor-drawn surfaces")
            .expect("capability listed");
        assert_eq!(entry.evidence, Evidence::Unsupported);
    }
}
