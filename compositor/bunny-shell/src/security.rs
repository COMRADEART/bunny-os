//! Security boundaries enforced inside the compositor.
//!
//! BUNNY WAYLAND SHELL EXPERIMENT - NOT RELEASE QUALIFIED - DO NOT USE AS THE
//! DEFAULT SESSION.
//!
//! The compositor is not a decision maker. It renders trusted backend state and
//! returns explicit user input. Everything in this module exists to make that
//! sentence enforceable rather than aspirational.

use std::collections::BTreeSet;

/// What the shell is allowed to ask the system to do.
///
/// There is deliberately no `RunShellCommand(String)` variant. Typed user text
/// cannot be turned into a process because no type exists to carry it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ShellAction {
    /// Launch an application by desktop entry identifier. The identifier is
    /// looked up in a trusted registry; it is never treated as a command line.
    LaunchDesktopEntry { entry_id: String },
    /// Focus an already-open window.
    FocusWindow { window_id: u64 },
    /// Switch workspace.
    SwitchWorkspace { index: usize },
    /// Change a shell setting the compositor owns.
    SetVisualMode { character_mode: bool },
    /// Ask the trusted backend to do something privileged. The compositor never
    /// performs the operation itself.
    RequestPrivilegedOperation { operation_id: String },
    /// A power action, which always routes through the session backend.
    PowerAction { action: PowerAction },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PowerAction {
    LogOut,
    Suspend,
    Restart,
    PowerOff,
}

/// Rejection reasons for a launch request.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LaunchRefusal {
    /// The identifier is not in the trusted registry.
    UnknownEntry(String),
    /// The identifier contains characters that suggest it is a command line or
    /// a path rather than a desktop entry id.
    NotADesktopEntryId(String),
}

/// A trusted registry of launchable applications, built from desktop entries.
#[derive(Debug, Default, Clone)]
pub struct ApplicationRegistry {
    entries: BTreeSet<String>,
}

impl ApplicationRegistry {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with_entries<I, S>(entries: I) -> Self
    where
        I: IntoIterator<Item = S>,
        S: Into<String>,
    {
        Self {
            entries: entries.into_iter().map(Into::into).collect(),
        }
    }

    pub fn insert(&mut self, entry_id: impl Into<String>) {
        self.entries.insert(entry_id.into());
    }

    pub fn contains(&self, entry_id: &str) -> bool {
        self.entries.contains(entry_id)
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    /// Resolve a launch request into an action.
    ///
    /// This is the only path from user input to a running process, and it
    /// accepts nothing that is not already a known desktop entry.
    pub fn resolve_launch(&self, requested: &str) -> Result<ShellAction, LaunchRefusal> {
        if !is_desktop_entry_id(requested) {
            return Err(LaunchRefusal::NotADesktopEntryId(requested.to_string()));
        }
        if !self.contains(requested) {
            return Err(LaunchRefusal::UnknownEntry(requested.to_string()));
        }
        Ok(ShellAction::LaunchDesktopEntry {
            entry_id: requested.to_string(),
        })
    }
}

/// A desktop entry id is a reverse-DNS-ish name. Anything containing a path
/// separator, whitespace, a shell metacharacter or a NUL is rejected outright.
pub fn is_desktop_entry_id(value: &str) -> bool {
    if value.is_empty() || value.len() > 255 {
        return false;
    }
    value
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || c == '.' || c == '-' || c == '_')
}

/// How dangerous an approval is.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ApprovalSeverity {
    Ordinary,
    Critical,
}

/// A user's answer to an approval request.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ApprovalInput {
    /// The user explicitly pressed approve.
    ExplicitApprove,
    /// The user explicitly pressed deny.
    ExplicitDeny,
    /// The dialog was dismissed, timed out, or a default button was activated.
    NoExplicitInput,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ApprovalOutcome {
    Approved,
    Denied,
}

/// Resolve an approval.
///
/// There is no path to `Approved` other than `ExplicitApprove`. A dismissed,
/// expired or defaulted dialog denies.
pub fn resolve_approval(input: ApprovalInput) -> ApprovalOutcome {
    match input {
        ApprovalInput::ExplicitApprove => ApprovalOutcome::Approved,
        ApprovalInput::ExplicitDeny | ApprovalInput::NoExplicitInput => ApprovalOutcome::Denied,
    }
}

/// Whether an approval card may pre-select an affirmative button.
///
/// A critical approval must never have a default affirmative action, so the
/// user cannot approve by pressing Enter reflexively.
pub fn may_default_to_affirmative(severity: ApprovalSeverity) -> bool {
    match severity {
        ApprovalSeverity::Ordinary => false,
        ApprovalSeverity::Critical => false,
    }
}

/// Screen capture authorisation state.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CaptureAuthorisation {
    /// The portal returned a session token for an explicitly selected source.
    PortalGranted { session_token: String, source: CaptureSource },
    /// No portal authorisation exists.
    None,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CaptureSource {
    Output,
    Window,
    Region,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CaptureRefusal {
    NoPortalAuthorisation,
    IndicatorUnavailable,
}

/// Decide whether a capture may proceed.
///
/// Two conditions, both required: the portal granted it, and the privacy
/// indicator can actually be shown. If the indicator cannot be displayed the
/// capture is refused — capture without a visible indicator is the failure mode
/// this rule exists to prevent.
pub fn authorise_capture(
    authorisation: &CaptureAuthorisation,
    indicator_available: bool,
) -> Result<(), CaptureRefusal> {
    match authorisation {
        CaptureAuthorisation::None => Err(CaptureRefusal::NoPortalAuthorisation),
        CaptureAuthorisation::PortalGranted { .. } if !indicator_available => {
            Err(CaptureRefusal::IndicatorUnavailable)
        }
        CaptureAuthorisation::PortalGranted { .. } => Ok(()),
    }
}

/// Field names whose values must never reach a log, a crash record or a
/// diagnostics snapshot.
pub const NEVER_LOGGED: [&str; 6] = [
    "password",
    "passphrase",
    "secret",
    "token",
    "credential",
    "keyring",
];

/// Redact a log line.
///
/// The compositor never receives a password — the lock screen sends it to an
/// isolated PAM helper — but keystrokes pass through the seat, so any code path
/// that logs user input is a leak waiting to happen. This makes the safe
/// behaviour the easy one.
pub fn redact(line: &str) -> String {
    let lowered = line.to_ascii_lowercase();
    if NEVER_LOGGED.iter().any(|needle| lowered.contains(needle)) {
        return "[redacted: line referenced a credential field]".to_string();
    }
    line.to_string()
}

/// Things the compositor must never do. Recorded as data so the security report
/// and the test suite read from one list.
pub const COMPOSITOR_PROHIBITIONS: [&str; 12] = [
    "run arbitrary shell text",
    "store authentication secrets",
    "bypass approvals",
    "invent backend state",
    "create privileged files directly",
    "access user files without a user action",
    "send telemetry",
    "enable remote access",
    "expose screen content without consent",
    "alter release evidence",
    "alter qualification gates",
    "create production signing keys",
];

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn typed_text_cannot_become_a_process() {
        let registry = ApplicationRegistry::with_entries(["org.bunnyos.Assistant"]);
        for hostile in [
            "rm -rf /",
            "sh -c 'curl evil'",
            "/bin/sh",
            "org.bunnyos.Assistant; rm -rf /",
            "../../bin/sh",
            "org.bunnyos.Assistant\n/bin/sh",
            "$(whoami)",
            "`id`",
            "a|b",
            "a&b",
        ] {
            let result = registry.resolve_launch(hostile);
            assert!(
                matches!(result, Err(LaunchRefusal::NotADesktopEntryId(_))),
                "expected refusal for {hostile:?}, got {result:?}"
            );
        }
    }

    #[test]
    fn an_unknown_but_well_formed_entry_is_still_refused() {
        let registry = ApplicationRegistry::with_entries(["org.bunnyos.Assistant"]);
        assert_eq!(
            registry.resolve_launch("org.example.NotInstalled"),
            Err(LaunchRefusal::UnknownEntry("org.example.NotInstalled".to_string()))
        );
    }

    #[test]
    fn a_known_entry_resolves_to_a_typed_action() {
        let registry = ApplicationRegistry::with_entries(["org.bunnyos.Assistant"]);
        assert_eq!(
            registry.resolve_launch("org.bunnyos.Assistant"),
            Ok(ShellAction::LaunchDesktopEntry {
                entry_id: "org.bunnyos.Assistant".to_string()
            })
        );
    }

    #[test]
    fn approval_requires_explicit_input() {
        assert_eq!(resolve_approval(ApprovalInput::NoExplicitInput), ApprovalOutcome::Denied);
        assert_eq!(resolve_approval(ApprovalInput::ExplicitDeny), ApprovalOutcome::Denied);
        assert_eq!(
            resolve_approval(ApprovalInput::ExplicitApprove),
            ApprovalOutcome::Approved
        );
    }

    #[test]
    fn a_critical_approval_has_no_default_affirmative_action() {
        assert!(!may_default_to_affirmative(ApprovalSeverity::Critical));
        assert!(!may_default_to_affirmative(ApprovalSeverity::Ordinary));
    }

    #[test]
    fn capture_without_portal_authorisation_is_refused() {
        assert_eq!(
            authorise_capture(&CaptureAuthorisation::None, true),
            Err(CaptureRefusal::NoPortalAuthorisation)
        );
    }

    #[test]
    fn capture_without_a_showable_indicator_is_refused() {
        let granted = CaptureAuthorisation::PortalGranted {
            session_token: "token".to_string(),
            source: CaptureSource::Window,
        };
        assert_eq!(
            authorise_capture(&granted, false),
            Err(CaptureRefusal::IndicatorUnavailable)
        );
        assert_eq!(authorise_capture(&granted, true), Ok(()));
    }

    #[test]
    fn credential_bearing_lines_are_redacted() {
        assert_eq!(redact("user typed password hunter2"), "[redacted: line referenced a credential field]");
        assert_eq!(redact("PASSPHRASE=abc"), "[redacted: line referenced a credential field]");
        assert_eq!(redact("window mapped: org.bunnyos.Assistant"), "window mapped: org.bunnyos.Assistant");
    }
}
