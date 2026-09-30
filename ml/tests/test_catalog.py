"""Source migration and technical availability; these are not clinical checks."""
import json
import unittest
from pathlib import Path

from prime_checkup.engine import load_data, validate_catalog
from prime_checkup.scheduler import schedule_visit, validate_schedule


ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA = "df733c43d5ab655ef08036366a44bae04e59182f"


class CatalogMigrationTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_data("demo_catalog.json")
        self.slots = load_data("prime_slots.json")
        self.by_id = {item["id"]: item for item in self.catalog["procedures"]}
        self.packages = {item["id"]: item for item in self.catalog["packages"]}

    def test_every_source_row_and_package_metadata_are_preserved(self):
        source = json.loads((ROOT / "reference/df733c4/spec/rules.json").read_text(encoding="utf-8-sig"))
        expected_counts = {"prime_basic": (11, 5, 3, 0), "prime_extended": (9, 6, 6, 0), "prime_child": (8, 0, 0, 5)}
        fields = (("exams", "required_ids"), ("female_exams", "female_ids"), ("male_exams", "male_ids"), ("extended_exams", "extended_ids"))
        for original in source["packages"]:
            package = self.packages[original["id"]]
            with self.subTest(package=package["id"]):
                self.assertEqual(tuple(len(package[key]) for _, key in fields), expected_counts[package["id"]])
                for source_field, catalog_field in fields:
                    ids = package[catalog_field]
                    self.assertEqual([self.by_id[pid]["name"] for pid in ids], original.get(source_field, []))
                    self.assertTrue(all(self.by_id[pid]["active"] for pid in ids))
                for key in ("name", "when", "price", "source", "payment", "name_f", "name_m", "url_f", "url_m", "name_mini", "name_extended", "url_mini", "url_extended"):
                    if key in original:
                        self.assertEqual(package[key], original[key])
                self.assertEqual(package["source_sha"], SOURCE_SHA)

    def test_changed_scopes_have_explicit_migration_and_legacy_refs_are_retired(self):
        migration = load_data("catalog_migration.json")
        records = {entry["old_id"]: entry for entry in migration["records"]}
        for old_id, new_id in (("prime_mammography", "prime_mammography_2d3d"), ("prime_tumor_markers_group", "prime_tumor_markers_expanded_group"), ("prime_colonoscopy", "prime_endoscopy_group"), ("prime_gastroscopy", "prime_endoscopy_group")):
            with self.subTest(old_id=old_id):
                self.assertIn(new_id, records[old_id]["new_ids"])
                self.assertEqual(records[old_id]["relation"], "changed_scope")
                self.assertFalse(self.by_id[old_id]["active"])
                self.assertTrue(self.by_id[new_id]["active"])
                self.assertTrue(records[old_id]["reason"])
        rules = load_data("demo_rules.json")
        validate_catalog(self.catalog, rules)
        fatigue = next(rule for rule in rules["rules"] if rule["id"] == "cmp_fatigue")
        self.assertEqual(fatigue["procedure_ids"], ["prime_vitamin_d", "prime_vitamin_b12", "prime_anemia_group", "prime_thyroid_hormones_group"])
        self.assertTrue(all(not self.by_id[pid]["active"] for pid in fatigue["procedure_ids"]))
        for data in (self.catalog, self.slots, rules):
            self.assertEqual(data["version"], "demo-2")
            self.assertEqual(data["source_sha"], SOURCE_SHA)
        # PowerShell pipelines must never replace explanatory Russian text
        # with question marks while generating these UTF-8 fixtures.
        for data in (self.catalog, self.slots, rules, migration):
            serialized = json.dumps(data, ensure_ascii=False)
            self.assertNotIn("??", serialized)
            self.assertNotIn("\ufffd", serialized)

    def test_curator_is_one_source_service_with_two_distinct_actions(self):
        group_id = "prime_curator_consultation_group"
        group = self.by_id[group_id]
        self.assertTrue(group["is_group"])
        self.assertEqual(group["action_ids"], ["prime_curator_initial", "prime_curator_final"])
        self.assertNotIn(group_id, self.slots["procedures"])
        for package_id in ("prime_basic", "prime_extended"):
            required = self.packages[package_id]["required_ids"]
            self.assertEqual(required.count(group_id), 1)
            self.assertFalse(set(group["action_ids"]) & set(required))
        initial, final = (self.by_id[pid] for pid in group["action_ids"])
        self.assertEqual(initial["name"], "Первичная консультация врача-куратора")
        self.assertEqual(final["name"], "Итоговая консультация врача-куратора")
        self.assertFalse(initial["after_results"])
        self.assertTrue(final["after_results"])
        self.assertEqual(initial["parent_procedure_id"], group_id)
        self.assertEqual(final["parent_procedure_id"], group_id)
        self.assertEqual(self.slots["procedures"][initial["id"]]["category"], -1)
        self.assertEqual(self.slots["procedures"][final["id"]]["predecessors"], [initial["id"]])
        self.assertEqual(self.slots["slots"]["normal"][final["id"]], [])

    def test_group_conditional_and_pregnancy_properties_are_explicit(self):
        self.assertTrue(self.by_id["prime_blood_panel_40plus_group"]["is_group"])
        self.assertTrue(self.by_id["prime_endoscopy_group"]["is_group"])
        self.assertEqual(self.by_id["prime_endoscopy_group"]["action_ids"], [])
        tagged = {pid for pid, item in self.by_id.items() if "pregnancy_review" in item["tags"]}
        self.assertEqual(tagged, {"prime_lung_ct", "prime_chest_ct", "prime_mammography_2d3d"})
        self.assertEqual(self.by_id["prime_helicobacter_test"]["tags"], [])
        conditional = {pid for pid, item in self.by_id.items() if item["conditional"]}
        self.assertEqual(conditional, {"prime_ophthalmology_if_indicated"})
        self.assertIn("requires_indication", self.by_id["prime_ophthalmology_if_indicated"]["tags"])
        child = self.packages["prime_child"]
        self.assertEqual(child["selected_variant"], "mini")
        self.assertTrue(child["extended_is_alternative"])
        self.assertFalse(set(child["required_ids"]) & set(child["extended_ids"]))
        self.assertEqual(child["when"], {"age_min": 1, "age_max": 17})

    def test_every_action_has_consistent_technical_data_and_busy_changes_only_slots(self):
        actions = {pid for pid, item in self.by_id.items() if item["active"] and not item["action_ids"]}
        self.assertEqual(actions, set(self.slots["procedures"]))
        self.assertEqual(actions, set(self.slots["slots"]["normal"]))
        self.assertEqual(actions, set(self.slots["slots"]["busy"]))
        self.assertTrue(all(value == [] for value in self.slots["slots"]["busy"].values()))
        for pid in actions:
            meta = self.slots["procedures"][pid]
            self.assertEqual(meta["duration_minutes"], 20 if self.by_id[pid]["is_group"] else 10)
            self.assertTrue(set(meta["resources"]).issubset(self.slots["resources"]))
            self.assertTrue(set(meta["predecessors"]).issubset(actions))
            self.assertIn(meta["category"], range(-1, 6))

    def test_availability_covers_each_catalog_variant_with_independent_validation(self):
        # This is solely a technical fixture: conditional action inclusion here is
        # an explicit synthetic decision, not a patient's indication or approval.
        variants = []
        for package in self.packages.values():
            for sex_key in ("female_ids", "male_ids"):
                variants.append((package["id"] + ":" + sex_key, package["required_ids"] + package[sex_key]))
            if package["extended_ids"]:
                variants.append((package["id"] + ":synthetic_extended", package["extended_ids"]))
        for variant_id, ids in variants:
            with self.subTest(variant=variant_id):
                actions = {action for pid in ids for action in (self.by_id[pid]["action_ids"] or [pid]) if not self.by_id[action]["after_results"]}
                procedures = []
                for pid in sorted(actions):
                    meta = self.slots["procedures"][pid]
                    predecessors = sorted(set(meta["predecessors"]) | {other for other in actions if self.slots["procedures"][other]["category"] < meta["category"]})
                    procedures.append({"id": pid, "name": self.by_id[pid]["name"], "duration_minutes": meta["duration_minutes"], "resources": meta["resources"], "predecessors": predecessors, "slots": self.slots["slots"]["normal"][pid]})
                fixture = {"id": variant_id, "package": {"id": variant_id, "required_ids": sorted(actions)}, "procedures": procedures, "patient_window": self.slots["patient_window"], "transition_minutes": self.slots["transition_minutes"], "resources": self.slots["resources"]}
                result = schedule_visit(fixture)
                self.assertEqual(result["status"], "feasible", result)
                self.assertEqual({entry["procedure_id"] for entry in result["route"]}, actions)
                self.assertEqual(validate_schedule(fixture, result["route"]), [])


if __name__ == "__main__":
    unittest.main()
