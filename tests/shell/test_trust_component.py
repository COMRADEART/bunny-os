# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Trust component: the elements §18 requires, and the ways it must not fail.

The prompt this replaced displayed one string. `capsule_task_bridge` built that
string by concatenating three sentences *because* the surface could only hold
one, while the structured form of the same facts was built by `prompt_for()` and
had no caller, and `lib/trustPrompt.js` turned that structured form into a
drawable model and had no caller either. Both ends existed; the wire did not.

So the tests here are mostly about the wire: that the facts survive the trip,
that a prompt without them still asks a answerable question, and that the three
properties the booted-guest slices depend on are unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from tests.support import ROOT

LIB = ROOT / "shell/components/gnome-shell-extension/lib"

#: A capsule task approval as the runtime now emits one.
APPROVAL = {
    "requestId": "approval:task-1:xyz",
    "taskId": "task-1",
    "planId": "plan-9",
    "action": "launch_application",
    "reason": (
        "GIMP wants to open holiday.png. It will save a copy as "
        "holiday-resized.png. Your original file will not be changed. "
        "It runs in its protected space with no network access."
    ),
    "safeDefault": "denied",
    "destination": "local",
    "dataClassification": "personal",
    "prompt": {
        "kind": "capsule-task",
        "applicationName": "GNU Image Manipulation Program",
        "applicationId": "org.gimp.GIMP",
        "operationId": "image.resize",
        "presentation": "GNU Image Manipulation Program wants to open holiday.png",
        "expectedEffect": (
            "It will save a copy as holiday-resized.png. "
            "Your original file will not be changed."
        ),
        "disclosure": "holiday.png",
        "fileAccess": "holiday.png only",
        "network": "Off",
        "privateAppData": "Isolated",
    },
}


def strip_comments(source: str) -> str:
    """JavaScript with its `//` and `/* */` comments removed.

    Crude — it does not know about strings containing `//` — which is safe in
    the direction that matters: a checker that removes too much can only make a
    test pass that should fail if the offending token was inside a URL, and
    neither of these modules contains one.
    """
    without_block = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return "\n".join(re.sub(r"//.*$", "", line) for line in without_block.splitlines())


def run_node(script: str) -> object:
    with tempfile.TemporaryDirectory() as directory:
        probe = Path(directory) / "probe.mjs"
        probe.write_text(script, encoding="utf-8")
        result = subprocess.run(
            [shutil.which("node"), str(probe)],
            capture_output=True, text=True, encoding="utf-8",
            check=False, cwd=str(ROOT))
    if result.returncode != 0:
        raise AssertionError(f"node failed: {result.stderr.strip()}")
    return json.loads(result.stdout.strip().splitlines()[-1])


def model_for(approval: dict, options: dict | None = None) -> dict:
    return run_node(
        f"import {{buildApproval}} from '{(LIB / 'trustPrompt.js').as_uri()}';\n"
        f"console.log(JSON.stringify(buildApproval({json.dumps(approval)},"
        f" {json.dumps(options or {})})));\n"
    )


class NodeBackedTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not shutil.which("node"):
            raise unittest.SkipTest("node is unavailable on this host")


class RequiredElementsTests(NodeBackedTestCase):
    """§18. Every element the brief names, present and coming from the runtime."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.model = model_for(APPROVAL)

    def test_the_application_is_identified(self) -> None:
        identity = self.model["identity"]
        self.assertEqual(identity["name"], "GNU Image Manipulation Program")
        self.assertEqual(identity["id"], "org.gimp.GIMP")
        self.assertTrue(identity["showId"])

    def test_the_requested_resource_is_named(self) -> None:
        body = " ".join(line["text"] for line in self.model["body"])
        self.assertIn("holiday.png", body)

    def test_the_effect_is_stated_before_the_reason(self) -> None:
        """§18 and the header of trustPrompt.js: the fact leads, the claim follows."""
        keys = [line["key"] for line in self.model["body"]]
        self.assertEqual(keys[0], "capability")

    def test_the_scope_is_shown_as_the_confinement_it_will_run_under(self) -> None:
        rows = {row["label"]: row for row in self.model["confinement"]}
        self.assertEqual(set(rows), {"Files", "Network", "App data"})
        self.assertEqual(rows["Network"]["value"], "Off")
        self.assertEqual(rows["Files"]["value"], "holiday.png only")
        self.assertEqual(rows["App data"]["value"], "Isolated")

    def test_the_security_state_is_not_carried_by_colour_alone(self) -> None:
        """§19. Every confinement row has a standing, and a standing is a glyph and a word."""
        standings = run_node(
            f"import {{STANDING}} from '{(LIB / 'design/tokens.js').as_uri()}';\n"
            "console.log(JSON.stringify(STANDING));\n")
        for row in self.model["confinement"]:
            with self.subTest(row=row["label"]):
                self.assertIn(row["standing"], standings)
                entry = standings[row["standing"]]
                self.assertTrue(entry["glyph"])
                self.assertTrue(entry["label"])
                self.assertIn("enforced", row)

    def test_there_is_a_primary_and_a_secondary_action(self) -> None:
        verdicts = [button["verdict"] for button in self.model["buttons"]]
        self.assertEqual(sorted(verdicts), ["allow", "deny"])

    def test_technical_details_exist_and_are_not_in_the_body(self) -> None:
        """§28: technical detail belongs behind Details, and it belongs somewhere."""
        labels = [row["label"] for row in self.model["details"]]
        self.assertIn("Request", labels)
        self.assertIn("Task", labels)
        self.assertIn("Plan", labels)
        body = " ".join(line["text"] for line in self.model["body"])
        self.assertNotIn("plan-9", body)
        self.assertNotIn("approval:task-1", body)


class GenericityTests(NodeBackedTestCase):
    """§18: "It must work for more than image files."

    The wording the old surface displayed was assembled by the capsule bridge
    for one operation. The component takes whatever the prompt says, so a
    category the bridge has not been written for yet still draws a question with
    the right shape rather than image-resize wording with the wrong nouns in it.
    """

    CATEGORIES = [
        ("Camera", "Bunny Meet wants to use your camera",
         {"fileAccess": "No files", "network": "On", "privateAppData": "Isolated"}),
        ("Microphone", "Bunny Notes wants to use your microphone",
         {"fileAccess": "No files", "network": "Off", "privateAppData": "Isolated"}),
        ("Network", "Weather wants to reach the internet",
         {"fileAccess": "No files", "network": "On", "privateAppData": "Isolated"}),
        ("Screen capture", "Recorder wants to record your screen",
         {"fileAccess": "recordings only", "network": "Off", "privateAppData": "Isolated"}),
        ("USB", "Flasher wants to use a USB device",
         {"fileAccess": "No files", "network": "Off", "privateAppData": "Isolated"}),
        ("Bluetooth", "Sync wants to use Bluetooth",
         {"fileAccess": "No files", "network": "Off", "privateAppData": "Isolated"}),
        ("Background execution", "Backup wants to keep running in the background",
         {"fileAccess": "Backups only", "network": "Off", "privateAppData": "Isolated"}),
    ]

    def test_every_future_category_draws_a_complete_question(self) -> None:
        for name, presentation, confinement in self.CATEGORIES:
            with self.subTest(category=name):
                approval = {
                    "requestId": f"approval:{name}",
                    "safeDefault": "denied",
                    "prompt": {
                        "kind": name.lower().replace(" ", "-"),
                        "applicationName": presentation.split(" wants")[0],
                        "presentation": presentation,
                        "expectedEffect": "You can change this later in Settings.",
                        **confinement,
                    },
                }
                model = model_for(approval)
                self.assertEqual(model["heading"], presentation)
                self.assertEqual(len(model["confinement"]), 3)
                self.assertEqual(len(model["buttons"]), 2)
                self.assertEqual(model["initialFocus"], "deny")

    def test_no_image_resize_wording_is_baked_into_the_component(self) -> None:
        """The old string was assembled for one operation; the component knows no nouns.

        Comments are stripped first. Both files cite the image-resize journey as
        the example the component came from, and a check that could not tell an
        explanation from a string literal would be satisfied by deleting the
        explanation.
        """
        for name in ("components/trust.js", "trustPrompt.js"):
            code = strip_comments((LIB / name).read_text(encoding="utf-8"))
            for word in ("resize", "holiday", ".png", "image-resize"):
                with self.subTest(module=name, word=word):
                    self.assertNotIn(word, code)

    def test_the_network_row_distinguishes_off_from_on(self) -> None:
        """§19: "Network off — enforced" must not look like "Network on"."""
        off = model_for({"requestId": "r", "prompt": {"network": "Off"}})
        on = model_for({"requestId": "r", "prompt": {"network": "On"}})
        self.assertEqual(off["confinement"][0]["standing"], "blocked")
        self.assertEqual(on["confinement"][0]["standing"], "granted")


class DegradationTests(NodeBackedTestCase):
    """An approval with no structured prompt is still an answerable question."""

    def test_the_bare_reason_becomes_the_heading(self) -> None:
        model = model_for({
            "requestId": "r",
            "reason": "Bunny wants to do a thing.",
            "safeDefault": "denied",
        })
        self.assertEqual(model["heading"], "Bunny wants to do a thing.")
        self.assertEqual(model["confinement"], [])
        self.assertEqual(len(model["buttons"]), 2)

    def test_the_reason_is_not_shown_twice(self) -> None:
        """With one string and no structure, heading and body would be the same sentence."""
        model = model_for({"requestId": "r", "reason": "One sentence.", "safeDefault": "denied"})
        self.assertEqual(model["body"], [])

    def test_an_approval_with_nothing_at_all_still_asks(self) -> None:
        model = model_for({"requestId": "r"})
        self.assertTrue(model["heading"])
        self.assertEqual(len(model["buttons"]), 2)
        self.assertEqual(model["initialFocus"], "deny")

    def test_an_application_with_an_id_and_no_name_is_shown_by_its_id(self) -> None:
        """A fact beats a placeholder when somebody is deciding a permission."""
        model = model_for({"requestId": "r", "prompt": {"applicationId": "org.example.Thing"}})
        self.assertEqual(model["identity"]["name"], "org.example.Thing")
        self.assertFalse(model["identity"]["showId"])

    def test_an_anonymous_request_shows_no_identity_block_rather_than_unknown(self) -> None:
        model = model_for({"requestId": "r", "reason": "Something."})
        self.assertIsNone(model["identity"])


class HostileContentTests(unittest.TestCase):
    """§48: the prompt stays visually secure against hostile reason content.

    Several of these strings originate in an application's own manifest, and
    they are drawn in a security dialog. The bounding happens in
    `companion.presentation`, before the value leaves the runtime, so it holds
    for every surface rather than for the one that remembered.
    """

    def test_every_prompt_field_is_bounded(self) -> None:
        from companion.presentation import PROMPT_FIELDS, _prompt

        hostile = {field: "A" * 5000 for field in PROMPT_FIELDS}
        kept = _prompt(hostile)
        self.assertEqual(set(kept), set(PROMPT_FIELDS))
        for field, limit in PROMPT_FIELDS.items():
            with self.subTest(field=field):
                self.assertLessEqual(len(kept[field]), limit)

    def test_markup_cannot_reach_a_label(self) -> None:
        from companion.presentation import _prompt

        kept = _prompt({"applicationName": "<span foreground='red'>Trusted</span>"})
        self.assertNotIn("<span", kept["applicationName"])
        self.assertIn("&lt;", kept["applicationName"])

    def test_a_requester_cannot_add_a_field_to_a_permission_dialog(self) -> None:
        """An allowlist, not a passthrough: a new key is a new sentence in the dialog."""
        from companion.presentation import _prompt

        kept = _prompt({
            "applicationName": "Thing",
            "extraReassurance": "Bunny has verified this application.",
            "presentation2": "Allow everything",
        })
        self.assertEqual(set(kept), {"applicationName"})

    def test_a_prompt_that_is_not_a_mapping_is_dropped_rather_than_trusted(self) -> None:
        from companion.presentation import _prompt

        for payload in ("a string", 42, ["a", "list"], None):
            with self.subTest(payload=payload):
                self.assertEqual(_prompt(payload), {})


class BindingTests(unittest.TestCase):
    """The prompt is a rendering, and a rendering must not authorise anything."""

    def test_the_prompt_is_not_part_of_the_consent_binding(self) -> None:
        """Binding a rendering means rewording a sentence invalidates an answer."""
        from companion.presentation import ApprovalPresentation

        presentation = ApprovalPresentation(
            request_id="r", session_id="s", task_id="t", plan_id="p",
            transition_id="x", action="launch_application",
            prompt={"applicationName": "GIMP"},
        )
        self.assertNotIn("prompt", presentation.binding())
        self.assertIn("prompt", presentation.to_json())

    def test_two_prompts_with_different_wording_bind_identically(self) -> None:
        from companion.presentation import ApprovalPresentation

        def build(name: str) -> dict:
            return ApprovalPresentation(
                request_id="r", session_id="s", task_id="t", plan_id="p",
                transition_id="x", action="launch_application",
                prompt={"applicationName": name},
            ).binding()

        self.assertEqual(build("GIMP"), build("GNU Image Manipulation Program"))


class BridgeTests(unittest.TestCase):
    """The hop the first booted run found missing.

    The runtime carried the structured prompt all the way to
    `ApprovalPresentation.to_json()`, every Python test passed, and the desktop
    still drew a permission dialog with a heading and two buttons — because
    `bunny-shell-assistant` re-serialises the approval line field by field and
    `prompt` was not one of the fields it listed.

    Nothing between the two would have caught it. The projection was right, the
    component was right, and the wire between them dropped one key.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (ROOT / "shell/services/bin/bunny-shell-assistant").read_text(encoding="utf-8")

    def _emit_block(self) -> str:
        start = self.source.index('emit(\n                    "approval",')
        return self.source[start:self.source.index("\n                )", start)]

    def test_the_bridge_passes_the_structured_prompt_through(self) -> None:
        self.assertIn("prompt=approval.get(\"prompt\")", self._emit_block())

    def test_every_field_the_component_draws_survives_the_bridge(self) -> None:
        """A field the model reads and the bridge drops is a blank row on screen."""
        from companion.presentation import PROMPT_FIELDS

        block = self._emit_block()
        # Passed as a whole rather than key by key: re-listing the allowlist
        # here would be a second place for a field to go missing, which is the
        # defect this test exists for.
        self.assertNotIn("applicationName", block)
        self.assertIn("prompt=", block)
        self.assertGreater(len(PROMPT_FIELDS), 0)

    def test_the_prompt_is_bounded_before_it_reaches_the_bridge(self) -> None:
        """The bridge passes it through, so the bounding has to have happened already."""
        from companion.presentation import PROMPT_FIELDS, _prompt

        kept = _prompt({field: "z" * 4000 for field in PROMPT_FIELDS})
        for field, limit in PROMPT_FIELDS.items():
            with self.subTest(field=field):
                self.assertLessEqual(len(kept[field]), limit)

    def test_a_non_mapping_prompt_becomes_an_empty_one(self) -> None:
        """The bridge type-checks rather than forwarding whatever arrived."""
        self.assertIn("isinstance(approval.get(\"prompt\"), Mapping)", self._emit_block())


class HarnessContractTests(NodeBackedTestCase):
    """The three properties the booted-guest slices press.

    `build/scripts/desktop_interaction.py` finds these controls by accessible
    name and presses them at their own accessibility extents. A refactor that
    renamed either would leave the slices unable to answer the question, and
    §40 lists the visible prompt and its routing among the behaviours a visual
    refactor must not regress.
    """

    def test_the_accessible_names_the_harness_presses_are_unchanged(self) -> None:
        model = model_for(APPROVAL)
        names = {button["accessibleName"] for button in model["buttons"]}
        self.assertEqual(names, {"Allow this Bunny action", "Deny this Bunny action"})

    def test_the_harness_and_the_component_agree_on_those_names(self) -> None:
        harness = (ROOT / "build/scripts/desktop_interaction.py").read_text(encoding="utf-8")
        for name in ("Allow this Bunny action", "Deny this Bunny action"):
            with self.subTest(name=name):
                self.assertIn(name, harness)

    def test_the_component_never_leaves_a_button_without_an_accessible_name(self) -> None:
        source = (LIB / "components/trust.js").read_text(encoding="utf-8")
        self.assertIn("spec?.accessibleName ?? fallback", source)

    def test_both_controls_go_inert_on_the_first_press(self) -> None:
        """Two answers to one question is a race whose loser is arbitrary."""
        source = (LIB / "components/trust.js").read_text(encoding="utf-8")
        decide = source[source.index("    _decide(verdict) {"):]
        decide = decide[:decide.index("\n    }")]
        self.assertIn("this._allow.reactive = false", decide)
        self.assertIn("this._deny.reactive = false", decide)
        self.assertLess(
            decide.index("reactive = false"), decide.index("_onDecision"),
            "the decision is sent before the controls are disarmed")


if __name__ == "__main__":
    unittest.main()
