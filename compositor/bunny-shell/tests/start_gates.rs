//! Process-level tests of the experimental shell's start gates.
//!
//! BUNNY WAYLAND SHELL EXPERIMENT - NOT RELEASE QUALIFIED - DO NOT USE AS THE
//! DEFAULT SESSION.
//!
//! The unit tests in `config.rs` prove the decision function. These prove the
//! binary actually applies it, which is the property that matters when the
//! session file launches it.

use std::process::Command;

fn shell() -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_bunny-shell"));
    // Start from a clean environment so a developer's own exports cannot make
    // the test pass.
    command.env_remove("BUNNY_SHELL_EXPERIMENTAL");
    command.env_remove("BUNNY_SHELL_IS_DEFAULT_SESSION");
    command.env_remove("BUNNY_QUALIFICATION_RUN");
    command.env("BUNNY_SHELL_ALLOW_MISSING_GNOME", "1");
    command
}

#[test]
fn it_refuses_to_start_without_explicit_experimental_mode() {
    let output = shell().arg("--frames").arg("1").output().expect("run");
    assert_eq!(output.status.code(), Some(2));
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains("BUNNY_SHELL_EXPERIMENTAL=1"), "{stderr}");
}

#[test]
fn it_refuses_when_made_the_default_session() {
    let output = shell()
        .env("BUNNY_SHELL_EXPERIMENTAL", "1")
        .env("BUNNY_SHELL_IS_DEFAULT_SESSION", "1")
        .arg("--frames")
        .arg("1")
        .output()
        .expect("run");
    assert_eq!(output.status.code(), Some(2));
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains("must not be configured as the default session"), "{stderr}");
}

#[test]
fn it_refuses_during_a_qualification_run() {
    let output = shell()
        .env("BUNNY_SHELL_EXPERIMENTAL", "1")
        .env("BUNNY_QUALIFICATION_RUN", "dsq-3")
        .arg("--frames")
        .arg("1")
        .output()
        .expect("run");
    assert_eq!(output.status.code(), Some(2));
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains("qualification run is in progress"), "{stderr}");
}

#[test]
fn every_run_prints_the_experiment_notice() {
    let output = shell().arg("--self-check").output().expect("run");
    let text = format!(
        "{}{}",
        String::from_utf8_lossy(&output.stderr),
        String::from_utf8_lossy(&output.stdout)
    );
    for line in [
        "BUNNY WAYLAND SHELL EXPERIMENT",
        "NOT RELEASE QUALIFIED",
        "DO NOT USE AS THE DEFAULT SESSION",
    ] {
        assert!(text.contains(line), "missing {line:?} in:\n{text}");
    }
}

#[test]
fn self_check_reports_the_gates_without_starting_anything() {
    let output = shell().arg("--self-check").output().expect("run");
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.contains("start-authorised           : no"), "{stdout}");
    assert!(stdout.contains("xwayland-state             : disabled"), "{stdout}");
    assert!(
        stdout.contains("accessibility-parity-claim : not claimable"),
        "{stdout}"
    );
}

#[test]
fn xwayland_is_never_required_for_startup() {
    // Requested but the shell must still report it can start. Rejection 14.
    let output = shell()
        .env("BUNNY_SHELL_EXPERIMENTAL", "1")
        .env("BUNNY_SHELL_XWAYLAND", "1")
        .arg("--self-check")
        .output()
        .expect("run");
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.contains("start-authorised           : yes"), "{stdout}");
}
