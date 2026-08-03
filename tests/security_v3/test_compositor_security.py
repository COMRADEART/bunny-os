"""Security boundaries: capture consent, lock behaviour, clipboard, logging.

BUNNY WAYLAND SHELL EXPERIMENT — NOT RELEASE QUALIFIED — DO NOT USE AS THE
DEFAULT SESSION.

Covers rejections 9 (a lock-screen crash exposing the desktop), 10 (password
content written to logs), 11 (screen capture without portal authorization),
12 (a missing privacy indicator during capture), 13 (clipboard content
persisted to disk) and 15 (output hotplug leaving an uncovered lock-screen
area).
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

from tests.support import ROOT

sys.path.insert(0, str(ROOT / "apps/common"))

from bunny_shell_v3.lock import (
    AuthenticationHelper,
    AuthResult,
    LockScreenPolicy,
    LockState,
    REQUIRED_LOCK_FEATURES,
    SessionLock,
    redact,
)
from bunny_shell_v3.portals import (
    CaptureRefusal,
    CaptureRequest,
    CaptureSource,
    ClipboardPolicy,
    REQUIRED_PORTALS,
    authorise_capture,
    indicator_obscurable_by_character,
    unrestricted_compositor_screenshot_permitted,
)


class ScreenCaptureTests(unittest.TestCase):
    def granted(self) -> CaptureRequest:
        return CaptureRequest(
            app_id="org.example.Meeting",
            source=CaptureSource.WINDOW,
            portal_token="portal-session-token",
            user_selected_source=True,
        )

    def test_capture_without_portal_authorisation_is_refused(self) -> None:
        """Rejection 11."""
        request = CaptureRequest(
            app_id="org.example.Meeting",
            source=CaptureSource.OUTPUT,
            portal_token=None,
            user_selected_source=True,
        )
        self.assertIs(
            authorise_capture(request, indicator_available=True),
            CaptureRefusal.NO_PORTAL_AUTHORISATION,
        )

    def test_capture_without_an_explicitly_selected_source_is_refused(self) -> None:
        request = CaptureRequest(
            app_id="org.example.Meeting",
            source=CaptureSource.OUTPUT,
            portal_token="token",
            user_selected_source=False,
        )
        self.assertIs(
            authorise_capture(request, indicator_available=True), CaptureRefusal.NO_SOURCE_SELECTED
        )

    def test_capture_is_refused_when_the_indicator_cannot_be_shown(self) -> None:
        """Rejection 12: a missing privacy indicator during capture."""
        self.assertIs(
            authorise_capture(self.granted(), indicator_available=False),
            CaptureRefusal.INDICATOR_UNAVAILABLE,
        )

    def test_a_fully_authorised_capture_is_granted(self) -> None:
        grant = authorise_capture(self.granted(), indicator_available=True)
        self.assertNotIsInstance(grant, CaptureRefusal)
        self.assertEqual(grant.indicator_key, "screen-capture")

    def test_no_application_may_screenshot_through_the_compositor(self) -> None:
        for app_id in ("org.example.App", "org.bunnyos.Assistant", ""):
            self.assertFalse(unrestricted_compositor_screenshot_permitted(app_id))

    def test_character_mode_cannot_obscure_the_capture_indicator(self) -> None:
        # The indicator lives in the top bar, which the character may never
        # occupy, so this holds by construction.
        self.assertFalse(indicator_obscurable_by_character())

    def test_every_required_portal_is_named(self) -> None:
        interfaces = {interface for interface, _ in REQUIRED_PORTALS}
        self.assertEqual(
            interfaces,
            {
                "org.freedesktop.portal.Screenshot",
                "org.freedesktop.portal.ScreenCast",
                "org.freedesktop.portal.FileChooser",
                "org.freedesktop.portal.OpenURI",
                "org.freedesktop.portal.Settings",
            },
        )

    def test_no_bunny_portal_backend_claims_to_be_implemented(self) -> None:
        for manifest in sorted((ROOT / "portals").glob("*/portal.json")):
            data = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertFalse(
                data["implementedInV3"], f"{manifest.parent.name} must not claim implementation"
            )


class LockScreenTests(unittest.TestCase):
    def locked(self) -> SessionLock:
        lock = SessionLock()
        lock.set_outputs({"eDP-1"})
        lock.lock()
        lock.surface_attached("eDP-1")
        return lock

    def test_locking_hides_the_desktop_before_any_surface_exists(self) -> None:
        lock = SessionLock()
        lock.set_outputs({"eDP-1"})
        lock.lock()
        self.assertIs(lock.state, LockState.LOCKING_INCOMPLETE)
        self.assertFalse(lock.may_present_desktop("eDP-1"))

    def test_a_crashed_lock_client_does_not_expose_the_desktop(self) -> None:
        """Rejection 9: a lock-screen crash exposing the desktop."""
        lock = self.locked()
        lock.client_lost()
        self.assertIs(lock.state, LockState.LOCKED_CLIENT_GONE)
        self.assertFalse(lock.state.desktop_visible)
        self.assertFalse(lock.may_present_desktop("eDP-1"))
        self.assertFalse(lock.unlock(AuthResult.SUCCESS))

    def test_hotplugging_an_output_while_locked_leaves_no_uncovered_desktop(self) -> None:
        """Rejection 15: output hotplug leaving an uncovered lock-screen area."""
        lock = self.locked()
        lock.output_added("DP-1")
        self.assertIs(lock.state, LockState.LOCKING_INCOMPLETE)
        self.assertEqual(lock.uncovered(), ["DP-1"])
        self.assertFalse(lock.may_present_desktop("DP-1"))
        lock.surface_attached("DP-1")
        self.assertIs(lock.state, LockState.LOCKED)
        self.assertEqual(lock.uncovered(), [])

    def test_removing_an_output_completes_a_partial_lock(self) -> None:
        lock = SessionLock()
        lock.set_outputs({"eDP-1", "DP-1"})
        lock.lock()
        lock.surface_attached("eDP-1")
        self.assertIs(lock.state, LockState.LOCKING_INCOMPLETE)
        lock.output_removed("DP-1")
        self.assertIs(lock.state, LockState.LOCKED)

    def test_a_failed_authentication_counts_and_does_not_unlock(self) -> None:
        lock = self.locked()
        self.assertFalse(lock.unlock(AuthResult.FAILURE))
        self.assertEqual(lock.failed_attempts, 1)
        self.assertIs(lock.state, LockState.LOCKED)

    def test_an_unavailable_helper_never_unlocks(self) -> None:
        lock = self.locked()
        self.assertFalse(lock.unlock(AuthResult.HELPER_UNAVAILABLE))
        self.assertIs(lock.state, LockState.LOCKED)

    def test_the_compositor_never_validates_a_password(self) -> None:
        helper = AuthenticationHelper()
        # No PAM service configured: the answer is "unavailable", never
        # "success". An unimplemented helper cannot be mistaken for a working
        # one.
        self.assertIs(helper.authenticate("bunny", "hunter2"), AuthResult.HELPER_UNAVAILABLE)
        self.assertIs(helper.authenticate("", ""), AuthResult.HELPER_UNAVAILABLE)

    def test_the_helper_repr_cannot_leak_a_secret(self) -> None:
        """Rejection 10, in its traceback form."""
        helper = AuthenticationHelper(service="bunny-shell")
        helper.authenticate("bunny", "hunter2")
        self.assertNotIn("hunter2", repr(helper))

    def test_credential_lines_are_redacted(self) -> None:
        for line in (
            "user typed password hunter2",
            "PASSPHRASE=abc",
            "keyring unlocked with secret",
            "auth token = xyz",
        ):
            self.assertEqual(redact(line), "[redacted: line referenced a credential field]")
        self.assertEqual(redact("window mapped: org.gtk.Demo4"), "window mapped: org.gtk.Demo4")

    def test_notifications_are_hidden_on_the_lock_screen_by_default(self) -> None:
        policy = LockScreenPolicy()
        self.assertFalse(policy.may_show_notification_content(unlocked=False))
        self.assertTrue(policy.may_show_notification_content(unlocked=True))

    def test_the_lock_screen_never_shows_the_guide_character(self) -> None:
        self.assertFalse(LockScreenPolicy().may_show_character())

    def test_the_lock_screen_offers_every_required_feature(self) -> None:
        policy = LockScreenPolicy()
        self.assertIn("password-authentication", REQUIRED_LOCK_FEATURES)
        self.assertTrue(policy.power_actions)
        self.assertTrue(policy.accessibility_controls)
        manifest = json.loads(
            (ROOT / "shell-ui/lock-screen/component.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["surfaceMechanism"], "ext-session-lock-v1")
        self.assertTrue(manifest["failsClosed"])
        self.assertFalse(manifest["characterPermitted"])


class ClipboardTests(unittest.TestCase):
    def test_clipboard_content_is_never_persisted_to_disk(self) -> None:
        """Rejection 13."""
        policy = ClipboardPolicy()
        self.assertFalse(policy.persists_to_disk)
        self.assertFalse(policy.survives_owner_exit)

    def test_sensitive_clearing_is_evaluated_but_not_silently_enabled(self) -> None:
        self.assertFalse(ClipboardPolicy().sensitive_clearing_enabled)
        self.assertIn("deliberately not enabled", ClipboardPolicy().describe())

    def test_ownership_and_lifetime_are_documented(self) -> None:
        text = ClipboardPolicy().describe()
        self.assertIn("owned by the offering client", text)
        self.assertIn("writes none to disk", text)


if __name__ == "__main__":
    unittest.main()
