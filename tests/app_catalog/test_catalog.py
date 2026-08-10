# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The curated catalogue, and the two dishonesties §14 exists to prevent.

Overselling a free alternative is the obvious one. Hiding the commercial option
is the one an open-source project falls into by default, and it is tested here
too: a person who asks for Photoshop is told Photoshop exists, what it costs and
that there is no Linux build — because a person who is not told will go and look
somewhere Bunny cannot see.
"""

from __future__ import annotations

import json
from pathlib import Path
import unittest

import catalog
from catalog.entry import CatalogEntry
from catalog.errors import CatalogSchemaError, CatalogUnknown
from catalog.registry import CatalogRegistry, default_catalog_directory
from catalog.selection import COMMITMENTS, MachineFacts, choices_for
from trust.categories import CATEGORIES

from tests.capsule_support import World


class ShippedCatalogueTests(unittest.TestCase):
    """The entries that are actually in the image."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = catalog.load_catalog()

    def test_the_catalogue_loads(self) -> None:
        self.assertGreater(len(self.registry), 0)

    def test_every_entry_declares_only_categories_that_exist(self) -> None:
        for entry in self.registry:
            for category in entry.required_permissions | entry.optional_permissions:
                self.assertIn(category, CATEGORIES, entry.entry_id)

    def test_every_declared_permission_has_a_stated_reason(self) -> None:
        """A curated entry that declares a permission without saying what it is
        for produces a prompt that says nobody said why — which is honest, and is
        a gap in the curation rather than a feature."""
        missing: list[str] = []
        for entry in self.registry:
            for category in sorted(entry.required_permissions | entry.optional_permissions):
                if category not in entry.permission_reasons:
                    missing.append(f"{entry.entry_id}:{category}")
        self.assertEqual(missing, [], "curated entries missing a permission reason")

    def test_every_entry_that_cannot_be_sandboxed_says_why(self) -> None:
        for entry in self.registry:
            if not entry.sandbox_compatible:
                self.assertTrue(entry.sandbox_note.strip(), entry.entry_id)

    def test_no_entry_is_installable_without_a_provenance_story(self) -> None:
        for entry in self.registry:
            if entry.installable:
                self.assertNotEqual(entry.trust_status, "unverified", entry.entry_id)
                if entry.package_source in ("vendor-rpm", "github-release"):
                    self.assertTrue(entry.signing_identity.strip(), entry.entry_id)

    def test_a_declaration_from_the_catalogue_is_a_ceiling(self) -> None:
        declaration = self.registry.declaration_for("org.gimp.GIMP")
        self.assertTrue(declaration.known)
        self.assertFalse(declaration.declares("microphone"))

    def test_an_application_with_no_entry_declares_nothing(self) -> None:
        declaration = self.registry.declaration_for("com.attacker.Thing")
        self.assertFalse(declaration.known)
        self.assertEqual(declaration.required, frozenset())

    def test_the_shipped_files_match_the_published_schema(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "schemas/app-catalog-entry.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["schemaVersion"]["const"], catalog.CATALOG_SCHEMA_VERSION)
        for path in sorted(default_catalog_directory().glob("*.json")):
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(document["schemaVersion"], catalog.CATALOG_SCHEMA_VERSION, path.name)
            for record in document["entries"]:
                for key in ("entryId", "applicationId", "name", "publisher", "purpose"):
                    self.assertIn(key, record, f"{path.name}:{record.get('entryId')}")


class LoadingTests(unittest.TestCase):
    def test_a_malformed_entry_fails_the_load_rather_than_being_skipped(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.json"
            path.write_text(
                json.dumps({"schemaVersion": 1, "entries": [{"entryId": "x"}]}), encoding="utf-8"
            )
            with self.assertRaises(CatalogSchemaError):
                CatalogRegistry.load(Path(directory))

    def test_two_entries_for_one_application_fail_the_load(self) -> None:
        base = dict(
            application_id="org.example.Thing",
            name="Thing",
            publisher="Somebody",
            purpose="Do a thing.",
            capabilities=("do-thing",),
            package_source="fedora-rpm",
            package_reference="/usr/bin/thing",
            license_id="MIT",
            cost="free",
            trust_status="distribution",
            update_mechanism="bootc-image",
            option_kind="open-source",
            preferred_backend="bubblewrap",
        )
        with self.assertRaises(CatalogSchemaError):
            CatalogRegistry.from_entries(
                [CatalogEntry(entry_id="one", **base), CatalogEntry(entry_id="two", **base)]
            )

    def test_an_unknown_entry_id_is_a_named_refusal(self) -> None:
        with self.assertRaises(CatalogUnknown):
            catalog.load_catalog().entry("no-such-entry")


class ChoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = catalog.load_catalog()

    def choices(self, capability: str, **facts):  # type: ignore[no-untyped-def]
        return choices_for(capability, self.registry, machine=MachineFacts(**facts))

    def test_the_commercial_option_is_shown_not_hidden(self) -> None:
        names = [choice.name for choice in self.choices("remove-background").choices]
        self.assertIn("Adobe Photoshop", names)

    def test_a_commercial_option_with_no_linux_build_is_blocked_and_explained(self) -> None:
        photoshop = next(
            choice for choice in self.choices("remove-background").choices if choice.name == "Adobe Photoshop"
        )
        self.assertEqual(photoshop.delivery, "not-available")
        self.assertFalse(photoshop.installable)
        self.assertIn("Linux", photoshop.blocked_reason)

    def test_a_subscription_says_so_before_anything_is_installed(self) -> None:
        photoshop = next(
            choice for choice in self.choices("remove-background").choices if choice.name == "Adobe Photoshop"
        )
        self.assertEqual(photoshop.commitment, "subscription")
        self.assertEqual(photoshop.commitment_note, COMMITMENTS["subscription"])

    def test_every_choice_carries_the_curators_difference_paragraph(self) -> None:
        for choice in self.choices("edit-image").choices:
            self.assertTrue(choice.entry.differences.strip(), choice.name)

    def test_nothing_generates_a_comparison_at_runtime(self) -> None:
        """The differences a person reads are exactly the curated bytes."""
        for choice in self.choices("edit-image").choices:
            record = choice.as_record()
            self.assertEqual(record["differences"], choice.entry.differences)

    def test_an_installed_option_is_offered_first(self) -> None:
        result = self.choices("remove-background", installed_application_ids=frozenset({"org.gimp.GIMP"}))
        self.assertEqual(result.choices[0].name, "GIMP")
        self.assertTrue(result.choices[0].installed)

    def test_a_web_option_is_offerable_and_not_installable(self) -> None:
        photopea = next(choice for choice in self.choices("edit-image").choices if choice.name == "Photopea")
        self.assertEqual(photopea.delivery, "browser")
        self.assertFalse(photopea.installable)
        self.assertEqual(photopea.blocked_reason, "")

    def test_a_web_option_is_blocked_when_the_machine_is_offline(self) -> None:
        photopea = next(
            choice for choice in self.choices("edit-image", online=False).choices if choice.name == "Photopea"
        )
        self.assertTrue(photopea.blocked_reason)

    def test_a_fit_note_is_only_made_when_the_fact_is_known(self) -> None:
        """A choice list that said 'needs more memory than you have' without
        having read the memory would be inventing."""
        unknown = self.choices("edit-image")
        for choice in unknown.choices:
            self.assertFalse(any("GB of memory" in note for note in choice.fit_notes), choice.name)
        known = self.choices("edit-image", memory_bytes=2 * 1024**3)
        self.assertTrue(any(any("GB of memory" in note for note in c.fit_notes) for c in known.choices))

    def test_a_capability_nobody_provides_says_so(self) -> None:
        result = choices_for("summon-a-unicorn", self.registry)
        self.assertTrue(result.nothing_found)
        self.assertEqual(result.choices, ())

    def test_a_capability_slug_that_is_not_a_slug_is_refused(self) -> None:
        with self.assertRaises(CatalogSchemaError):
            choices_for("../../etc/passwd", self.registry)

    def test_every_commitment_value_has_a_sentence(self) -> None:
        for choice in self.choices("edit-image").choices:
            self.assertIn(choice.commitment, COMMITMENTS)


class RuntimeIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.world = World.build()
        self.addCleanup(self.world.close)

    def test_the_catalogue_supplies_the_names_the_prompts_use(self) -> None:
        names = self.world.registry.names()
        self.assertEqual(names["org.gimp.GIMP"], "GIMP")

    def test_an_entrys_high_risk_permissions_are_the_ones_always_asked_about(self) -> None:
        entry = self.world.registry.entry("bunny-files")
        self.assertIn("usb", entry.high_risk_permissions)
        self.assertNotIn("notifications", entry.high_risk_permissions)


if __name__ == "__main__":
    unittest.main()
