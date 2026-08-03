//! Input handling and key bindings.
//!
//! BUNNY WAYLAND SHELL EXPERIMENT - NOT RELEASE QUALIFIED - DO NOT USE AS THE
//! DEFAULT SESSION.
//!
//! The binding table is a pure value so it can be tested without a seat, and so
//! that the security property that matters — a binding resolves to a typed
//! command, never to a string handed to a shell — is visible in the types.

use crate::security::ShellAction;

/// Modifier state, reduced to what the shell binds against.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct Modifiers {
    pub logo: bool,
    pub shift: bool,
    pub ctrl: bool,
    pub alt: bool,
}

impl Modifiers {
    pub fn logo() -> Self {
        Self {
            logo: true,
            ..Default::default()
        }
    }

    pub fn logo_shift() -> Self {
        Self {
            logo: true,
            shift: true,
            ..Default::default()
        }
    }

    pub fn alt() -> Self {
        Self {
            alt: true,
            ..Default::default()
        }
    }
}

/// A command the shell itself performs. Distinct from [`ShellAction`], which is
/// what the shell asks the rest of the system to do.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ShellCommand {
    OpenCommandPalette,
    OpenLauncher,
    OpenOverview,
    OpenQuickSettings,
    OpenNotificationCenter,
    ToggleVisualMode,
    SwitchWorkspace(usize),
    MoveWindowToWorkspace(usize),
    FocusNextWindow,
    FocusPreviousWindow,
    CloseFocusedWindow,
    ToggleMaximize,
    ToggleFullscreen,
    LockSession,
    ShowDiagnostics,
    Quit,
    /// A privileged request that must be answered by the approval backend.
    Privileged(ShellAction),
}

impl ShellCommand {
    /// How the command palette labels this result.
    pub fn behavior_label(&self) -> &'static str {
        match self {
            ShellCommand::OpenCommandPalette
            | ShellCommand::OpenLauncher
            | ShellCommand::OpenOverview
            | ShellCommand::OpenQuickSettings
            | ShellCommand::OpenNotificationCenter
            | ShellCommand::ShowDiagnostics => "Open",
            ShellCommand::SwitchWorkspace(_)
            | ShellCommand::FocusNextWindow
            | ShellCommand::FocusPreviousWindow => "Switch",
            ShellCommand::ToggleVisualMode
            | ShellCommand::MoveWindowToWorkspace(_)
            | ShellCommand::ToggleMaximize
            | ShellCommand::ToggleFullscreen
            | ShellCommand::CloseFocusedWindow => "Change",
            ShellCommand::LockSession | ShellCommand::Quit => "Power action",
            ShellCommand::Privileged(ShellAction::PowerAction { .. }) => "Power action",
            ShellCommand::Privileged(_) => "Approval required",
        }
    }

    pub fn requires_approval(&self) -> bool {
        matches!(self, ShellCommand::Privileged(_))
    }
}

/// A key binding. `key` is an xkb keysym name, which keeps the table
/// layout-independent.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct KeyBinding {
    pub modifiers: Modifiers,
    pub key: &'static str,
    pub command: ShellCommand,
}

/// The default binding table.
pub fn default_bindings() -> Vec<KeyBinding> {
    let mut bindings = vec![
        KeyBinding {
            modifiers: Modifiers::logo(),
            key: "space",
            command: ShellCommand::OpenCommandPalette,
        },
        KeyBinding {
            modifiers: Modifiers::logo(),
            key: "a",
            command: ShellCommand::OpenLauncher,
        },
        KeyBinding {
            modifiers: Modifiers::logo(),
            key: "s",
            command: ShellCommand::OpenOverview,
        },
        KeyBinding {
            modifiers: Modifiers::logo(),
            key: "k",
            command: ShellCommand::OpenQuickSettings,
        },
        KeyBinding {
            modifiers: Modifiers::logo(),
            key: "n",
            command: ShellCommand::OpenNotificationCenter,
        },
        KeyBinding {
            modifiers: Modifiers::logo(),
            key: "m",
            command: ShellCommand::ToggleVisualMode,
        },
        KeyBinding {
            modifiers: Modifiers::logo(),
            key: "l",
            command: ShellCommand::LockSession,
        },
        KeyBinding {
            modifiers: Modifiers::logo(),
            key: "d",
            command: ShellCommand::ShowDiagnostics,
        },
        KeyBinding {
            modifiers: Modifiers::logo(),
            key: "q",
            command: ShellCommand::CloseFocusedWindow,
        },
        KeyBinding {
            modifiers: Modifiers::logo(),
            key: "Up",
            command: ShellCommand::ToggleMaximize,
        },
        KeyBinding {
            modifiers: Modifiers::logo(),
            key: "f",
            command: ShellCommand::ToggleFullscreen,
        },
        KeyBinding {
            modifiers: Modifiers::alt(),
            key: "Tab",
            command: ShellCommand::FocusNextWindow,
        },
        KeyBinding {
            modifiers: Modifiers {
                alt: true,
                shift: true,
                ..Default::default()
            },
            key: "Tab",
            command: ShellCommand::FocusPreviousWindow,
        },
        KeyBinding {
            modifiers: Modifiers {
                logo: true,
                shift: true,
                ctrl: true,
                ..Default::default()
            },
            key: "Escape",
            command: ShellCommand::Quit,
        },
    ];

    const WORKSPACE_KEYS: [&str; 4] = ["1", "2", "3", "4"];
    for (index, key) in WORKSPACE_KEYS.iter().enumerate() {
        bindings.push(KeyBinding {
            modifiers: Modifiers::logo(),
            key,
            command: ShellCommand::SwitchWorkspace(index),
        });
        bindings.push(KeyBinding {
            modifiers: Modifiers::logo_shift(),
            key,
            command: ShellCommand::MoveWindowToWorkspace(index),
        });
    }

    bindings
}

/// Resolve a key press to a command.
///
/// Returns `None` when nothing is bound, in which case the key goes to the
/// focused client untouched. The shell never consumes a key it does not use.
pub fn resolve(bindings: &[KeyBinding], modifiers: Modifiers, key: &str) -> Option<ShellCommand> {
    bindings
        .iter()
        .find(|binding| binding.modifiers == modifiers && binding.key == key)
        .map(|binding| binding.command.clone())
}

/// Pointer configuration the compositor applies to a seat.
#[derive(Debug, Clone, PartialEq)]
pub struct PointerConfig {
    pub acceleration: f64,
    pub natural_scrolling: bool,
    pub tap_to_click: bool,
}

impl Default for PointerConfig {
    fn default() -> Self {
        Self {
            acceleration: 0.0,
            natural_scrolling: false,
            tap_to_click: true,
        }
    }
}

impl PointerConfig {
    /// libinput accepts acceleration in [-1.0, 1.0]. Values outside that range
    /// are clamped rather than rejected, because a bad setting should not stop
    /// the pointer working.
    pub fn with_acceleration(mut self, value: f64) -> Self {
        self.acceleration = value.clamp(-1.0, 1.0);
        self
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::security::PowerAction;

    #[test]
    fn super_space_opens_the_command_palette() {
        let bindings = default_bindings();
        assert_eq!(
            resolve(&bindings, Modifiers::logo(), "space"),
            Some(ShellCommand::OpenCommandPalette)
        );
    }

    #[test]
    fn an_unbound_key_is_passed_through_to_the_client() {
        let bindings = default_bindings();
        assert_eq!(resolve(&bindings, Modifiers::default(), "e"), None);
        assert_eq!(resolve(&bindings, Modifiers::logo(), "z"), None);
    }

    #[test]
    fn modifiers_must_match_exactly() {
        let bindings = default_bindings();
        // Super+Shift+space is not Super+space.
        assert_eq!(resolve(&bindings, Modifiers::logo_shift(), "space"), None);
    }

    #[test]
    fn workspace_switch_and_move_are_distinct_bindings() {
        let bindings = default_bindings();
        assert_eq!(
            resolve(&bindings, Modifiers::logo(), "2"),
            Some(ShellCommand::SwitchWorkspace(1))
        );
        assert_eq!(
            resolve(&bindings, Modifiers::logo_shift(), "2"),
            Some(ShellCommand::MoveWindowToWorkspace(1))
        );
    }

    #[test]
    fn every_binding_resolves_to_a_typed_command() {
        // The point of this test is that there is no variant carrying a command
        // line, so a binding can never be turned into shell text.
        for binding in default_bindings() {
            match binding.command {
                ShellCommand::Privileged(ShellAction::LaunchDesktopEntry { ref entry_id }) => {
                    assert!(crate::security::is_desktop_entry_id(entry_id));
                }
                _ => {}
            }
        }
    }

    #[test]
    fn privileged_commands_are_labelled_as_needing_approval() {
        let command = ShellCommand::Privileged(ShellAction::RequestPrivilegedOperation {
            operation_id: "install-update".to_string(),
        });
        assert!(command.requires_approval());
        assert_eq!(command.behavior_label(), "Approval required");
    }

    #[test]
    fn power_actions_are_labelled_as_power_actions() {
        let command = ShellCommand::Privileged(ShellAction::PowerAction {
            action: PowerAction::Restart,
        });
        assert_eq!(command.behavior_label(), "Power action");
    }

    #[test]
    fn pointer_acceleration_is_clamped_not_rejected() {
        assert_eq!(PointerConfig::default().with_acceleration(9.0).acceleration, 1.0);
        assert_eq!(PointerConfig::default().with_acceleration(-9.0).acceleration, -1.0);
    }
}
