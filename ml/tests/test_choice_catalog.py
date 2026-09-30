"""A selectable service is neither an action nor a public screening programme."""
import json
import unittest
from copy import deepcopy
from pathlib import Path

from prime_checkup.choice_catalog import catalog_for_patient, enrich_screening


DATA = Path(__file__).resolve().parents[1] / "prime_checkup" / "data"


class ChoiceCatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads((DATA / "demo_catalog.json").read_text(encoding="utf-8"))
        self.patient = {"age_full": 35, "sex": "F", "values": {"attached_to": "unknown"}}

    def test_union_preserves_gender_and_child_extended_without_actions(self):
        items, options = catalog_for_patient(self.patient, self.catalog)
        ids = [item["procedure_id"] for item in items]
        expected = {procedure_id for package in self.catalog["packages"]
                    for field in ("required_ids", "female_ids", "male_ids", "extended_ids")
                    for procedure_id in package[field]}
        self.assertEqual(set(ids), expected)
        self.assertEqual(len(ids), len(expected))
        self.assertIn("prime_child_extended_labs_group", ids)
        self.assertIn("prime_mammography_2d3d", ids)
        self.assertIn("prime_psa_total_free_group", ids)
        self.assertNotIn("prime_curator_initial", ids)
        self.assertNotIn("prime_curator_final", ids)
        self.assertNotIn("prime_mammography", ids)  # Retired scope is not selectable.
        self.assertFalse(any(pid.startswith(("DEMO_", "scr_")) for pid in ids))
        curator = next(item for item in items if item["procedure_id"] == "prime_curator_consultation_group")
        self.assertEqual(curator["action_ids"], ["prime_curator_initial", "prime_curator_final"])
        self.assertEqual(curator["source_package_ids"], ["prime_basic", "prime_extended"])
        self.assertEqual(len(options), 6)

    def test_presets_are_exact_alternatives_with_boundaries(self):
        packages = {package["id"]: package for package in self.catalog["packages"]}
        for age, sex, expected in ((0, "M", set()), (10, "M", {("prime_child", "mini"), ("prime_child", "extended")}),
                                   (39, "F", {("prime_basic", "female")}),
                                   (40, "M", {("prime_extended", "male")}),
                                   (35, "unknown", set())):
            with self.subTest(age=age, sex=sex):
                _, options = catalog_for_patient({"age_full": age, "sex": sex}, self.catalog)
                self.assertEqual({(option["package_id"], option["variant_id"]) for option in options if option["eligible"]}, expected)
                for option in options:
                    package = packages[option["package_id"]]
                    if option["variant_id"] == "extended":
                        expected_ids = package["extended_ids"]
                    elif option["variant_id"] == "mini":
                        expected_ids = package["required_ids"]
                    else:
                        expected_ids = package["required_ids"] + package[option["variant_id"] + "_ids"]
                    self.assertEqual(option["selected_procedure_ids"], expected_ids)

    def test_service_age_is_not_derived_from_40_plus_package_boundary(self):
        items, _ = catalog_for_patient(self.patient, self.catalog)
        by_id = {item["procedure_id"]: item for item in items}
        self.assertFalse(by_id["prime_blood_panel_40plus_group"]["requires_review"])
        self.assertTrue(by_id["prime_blood_panel_40plus_group"]["is_group"])
        self.assertEqual(by_id["prime_blood_panel_40plus_group"]["applicability"]["status"], "catalog_match")
        self.assertTrue(by_id["prime_child_extended_labs_group"]["requires_review"])
        child_items, _ = catalog_for_patient({"age_full": 10, "sex": "M"}, self.catalog)
        child_by_id = {item["procedure_id"]: item for item in child_items}
        self.assertTrue(child_by_id["prime_lung_ct"]["requires_review"])
        # A general service appearing in a child's package and the female basic
        # addition does not become an exclusively female service by accident.
        self.assertFalse(child_by_id["prime_ecg"]["requires_review"])

    def test_child_extended_mixed_age_groups_need_review_without_splitting(self):
        items, options = catalog_for_patient({"age_full": 10, "sex": "M"}, self.catalog)
        by_id = {item["procedure_id"]: item for item in items}
        for procedure_id in ("prime_child_ecg_neurosonography_group", "prime_child_extended_ultrasound_group"):
            with self.subTest(procedure_id=procedure_id):
                self.assertTrue(by_id[procedure_id]["requires_review"])
                self.assertTrue(by_id[procedure_id]["is_group"])
                self.assertIn("AGE_DEPENDENT_GROUP", [flag["code"] for flag in by_id[procedure_id]["applicability_flags"]])
                self.assertEqual(by_id[procedure_id]["action_ids"], [])
        child_options = {option["variant_id"]: option for option in options if option["package_id"] == "prime_child"}
        self.assertTrue(child_options["extended"]["eligible"])
        self.assertEqual(len(child_options["extended"]["selected_procedure_ids"]), 5)
        self.assertFalse(any(by_id[pid]["requires_review"] for pid in child_options["mini"]["selected_procedure_ids"]))

    def test_gender_variant_is_review_not_a_claimed_diagnosis(self):
        items, _ = catalog_for_patient({"age_full": 35, "sex": "M"}, self.catalog)
        by_id = {item["procedure_id"]: item for item in items}
        self.assertTrue(by_id["prime_transvaginal_ultrasound"]["requires_review"])
        self.assertEqual(by_id["prime_transvaginal_ultrasound"]["applicability_flags"][0]["code"], "sex_variant_requires_review")
        self.assertFalse(by_id["prime_psa_total_free_group"]["requires_review"])
        self.assertIn("pregnancy_review", by_id["prime_mammography_2d3d"]["known_constraints"])
        self.assertNotIn("pregnancy_review", by_id["prime_helicobacter_test"]["known_constraints"])
        self.assertTrue(by_id["prime_ophthalmology_if_indicated"]["requires_review"])

    def test_dangling_and_action_package_references_are_data_errors(self):
        for invalid_id in ("scr_breast", "DEMO_A", "unknown", "prime_curator_initial", "prime_mammography"):
            with self.subTest(invalid_id=invalid_id):
                corrupted = deepcopy(self.catalog)
                corrupted["packages"][0]["required_ids"].append(invalid_id)
                with self.assertRaises(ValueError):
                    catalog_for_patient(self.patient, corrupted)

    def test_screening_is_separate_explicit_and_has_no_guaranteed_payment(self):
        catalog_items, _ = catalog_for_patient(self.patient, self.catalog)
        screening = [{"rule_id": "scr_breast", "outcome": "candidate", "source": "source-rule"},
                     {"rule_id": "scr_cvd", "outcome": "needs_input", "source": "source-rule"}]
        original = deepcopy(screening)
        enriched = enrich_screening(screening, self.patient, catalog_items)
        self.assertEqual(screening, original)
        breast = enriched[0]
        self.assertEqual(breast["where"], "Уточнить поликлинику прикрепления")
        self.assertEqual(breast["payment"]["status"], "public_program_candidate")
        self.assertFalse(breast["payment"]["guaranteed"])
        self.assertEqual(breast["prime_matches"][0]["procedure_id"], "prime_mammography_2d3d")
        self.assertEqual(breast["prime_matches"][0]["match_degree"], "partial")
        self.assertTrue(breast["prime_matches"][0]["explanation"])
        self.assertEqual(breast["source"], "source-rule")
        self.assertEqual(breast["repeat_years_reference"]["years"], 2)
        self.assertNotIn("date", breast["repeat_years_reference"])
        self.assertEqual(enriched[1]["payment"]["status"], "requires_verification")
        for item in enriched:
            self.assertEqual(item["choices"][0]["kind"], "public_program")
            for choice in item["choices"][1:]:
                self.assertTrue(choice["requires_explicit_selection"])
                self.assertTrue(choice["procedure_id"].startswith("prime_"))
        # Independent requests cannot mutate a previous patient's response.
        self.patient["values"]["attached_to"] = "green_clinic"
        changed = enrich_screening(screening, self.patient, catalog_items)
        self.assertIn("Green Clinic", changed[0]["where"])
        self.assertEqual(enriched[0]["where"], "Уточнить поликлинику прикрепления")


if __name__ == "__main__":
    unittest.main()
