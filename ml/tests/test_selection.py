"""Business regressions for the stateless recommendation/selection contract."""

from copy import deepcopy
import unittest
from unittest.mock import patch

from prime_checkup.engine import load_data
from prime_checkup.selection import plan_request, plan_selection, recommend, response_http_status


PATIENT = {"input_version": "clinic_v1", "sex": "M", "birth_date": "1988-01-10", "urgent": "none"}
CONTEXT = {"as_of_date": "2026-09-30", "checkup_year": 2026,
           "visit_date": "2026-10-01", "availability": "normal"}


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.patient = deepcopy(PATIENT)
        self.recommendation = recommend(self.patient, CONTEXT)

    def selection(self, ids=None, mode="custom", recommendation=None, **changes):
        recommendation = recommendation or self.recommendation
        value = {"mode": mode, "base_package_id": recommendation["package"]["id"],
                 "variant_id": recommendation["package"]["variant_id"],
                 "catalog_version": recommendation["versions"]["catalog"]}
        if ids is not None:
            value["selected_procedure_ids"] = list(ids)
        value.update(changes)
        return value

    def ids(self, result, field="items"):
        return {item["procedure_id"] for item in result[field]}

    def test_recommendation_does_not_search_or_construct_schedule(self):
        with patch("prime_checkup.engine.schedule_visit", side_effect=AssertionError("recommend must not search")), \
             patch("prime_checkup.engine.make_schedule_fixture", side_effect=AssertionError("recommend must not construct slots")), \
             patch("prime_checkup.choice_route.schedule_visit", side_effect=AssertionError("recommend must not search")):
            result = recommend(self.patient, CONTEXT)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["schedule"]["status"], "not_run")
        self.assertEqual(result["schedule"]["route"], [])
        self.assertEqual(result["route"], [])
        self.assertTrue(result["catalog"])
        self.assertTrue(all(item["why"] and item["rule_id"] and item["source"] for item in result["items"]))
        self.assertTrue(all(item["procedure_id"].startswith("prime_") for item in result["items"]))
        self.assertTrue(all(row["source"] and row["where"] and not row["payment"]["guaranteed"] for row in result["screening"]))

    def test_catalog_has_all_package_sections_but_not_actions_or_screenings(self):
        catalog = load_data("demo_catalog.json")
        expected = {pid for package in catalog["packages"]
                    for key in ("required_ids", "female_ids", "male_ids", "extended_ids")
                    for pid in package.get(key, [])}
        self.assertEqual(self.ids(self.recommendation, "catalog"), expected)
        self.assertNotIn("prime_curator_initial", expected)
        self.assertNotIn("prime_curator_final", expected)
        self.assertTrue(all(pid.startswith("prime_") for pid in expected))
        self.assertTrue(all(entry["source_package_ids"] for entry in self.recommendation["catalog"]))
        variants = {(item["package_id"], item["variant_id"]) for item in self.recommendation["package_options"]}
        self.assertTrue({("prime_child", "mini"), ("prime_child", "extended")} <= variants)

    def test_preset_reconstructs_exact_source_and_rejects_conflicting_list(self):
        request = self.selection(mode="preset")
        result = plan_selection(self.patient, request, CONTEXT)
        self.assertEqual(self.ids(result, "selected_items"), self.ids(self.recommendation))
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["removed_recommended_items"], [])
        self.assertEqual(result["added_items"], [])
        self.assertTrue(all(item["selection_reason"]["rule_id"] == "selected_preset" for item in result["selected_items"]))
        conflict = plan_selection(self.patient, {**request, "selected_procedure_ids": []}, CONTEXT)
        self.assertEqual(response_http_status(conflict), 422)
        self.assertEqual(conflict["errors"][0]["code"], "preset_mismatch")

    def test_custom_removal_is_final_and_warning_keeps_original_reason(self):
        removed = next(item for item in self.recommendation["items"] if item["procedure_id"] == "prime_lung_ct")
        selected = self.ids(self.recommendation) - {removed["procedure_id"]}
        result = plan_selection(self.patient, self.selection(selected), CONTEXT)
        self.assertEqual(self.ids(result, "selected_items"), selected)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["schedule"]["status"], "feasible")
        self.assertEqual(result["removed_recommended_items"][0]["why"], removed["why"])
        self.assertTrue(any(row["code"] == "removed_recommendation" and removed["why"] in row["message"] for row in result["warnings"]))
        self.assertNotIn(removed["procedure_id"], {row["procedure_id"] for row in result["route"]})
        self.assertEqual(result["package"]["name"], "Индивидуальный набор")

    def test_manual_other_package_group_is_not_an_age_contraindication_or_duplicate(self):
        added_id = "prime_blood_panel_40plus_group"
        result = plan_selection(self.patient, self.selection([added_id, added_id]), CONTEXT)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(len(result["selected_items"]), 1)
        item = result["selected_items"][0]
        self.assertEqual(item["procedure_id"], added_id)
        self.assertTrue(item["is_group"])
        self.assertEqual(item["actions"], [])
        self.assertEqual(item["selection_reason"]["explanation"], "Выбрано пользователем из каталога PRIME")
        self.assertIn("prime_extended", item["source_package_ids"])
        self.assertEqual(self.ids(result, "added_items"), {added_id})
        self.assertEqual(result["total_price"], None)
        self.assertEqual(result["price_text"], "Стоимость — у администратора")

    def test_discussion_specialist_is_not_duplicated_after_manual_selection(self):
        patient = {**self.patient, "dysuria": "yes"}
        recommendation = recommend(patient, CONTEXT)
        self.assertIn("prime_urology_consult", {row["procedure_id"] for row in recommendation["proposed_extras"]})
        result = plan_selection(patient, self.selection(["prime_urology_consult"], recommendation=recommendation), CONTEXT)
        self.assertEqual(self.ids(result, "selected_items"), {"prime_urology_consult"})
        self.assertNotIn("prime_urology_consult", {row["procedure_id"] for row in result["proposed_extras"]})
        self.assertTrue(any(row["procedure_id"] is None for row in result["proposed_extras"]))
        removed = plan_selection(patient, self.selection(["prime_helicobacter_test"], recommendation=recommendation), CONTEXT)
        self.assertIn("prime_urology_consult", {row["procedure_id"] for row in removed["proposed_extras"]})
        self.assertNotIn("prime_urology_consult", self.ids(removed, "selected_items"))

    def test_empty_custom_missing_list_unknown_ids_and_stale_catalog(self):
        empty = plan_selection(self.patient, self.selection([]), CONTEXT)
        self.assertEqual(empty["status"], "needs_input")
        self.assertEqual(empty["selected_items"], [])
        self.assertEqual(empty["items"], [])
        self.assertEqual(empty["route"], [])
        self.assertIn("Выберите хотя бы одну услугу", empty["questions"][0]["message"])
        missing = plan_selection(self.patient, self.selection(), CONTEXT)
        self.assertEqual(response_http_status(missing), 422)
        self.assertEqual(missing["errors"][0]["field"], "selected_procedure_ids")
        for mode in ("custom", "preset"):
            with self.subTest(null_array_mode=mode):
                null_array = plan_selection(self.patient, {**self.selection(mode=mode), "selected_procedure_ids": None}, CONTEXT)
                self.assertEqual(response_http_status(null_array), 422)
                self.assertEqual(null_array["errors"][0]["field"], "selected_procedure_ids")
        for pid in ("scr_breast", "DEMO_A", "not_in_catalog", "prime_curator_initial"):
            with self.subTest(pid=pid):
                bad = plan_selection(self.patient, self.selection([pid]), CONTEXT)
                self.assertEqual(response_http_status(bad), 422)
                self.assertEqual(bad["errors"][0]["code"], "unknown_procedure")
        stale = plan_selection(self.patient, self.selection(["prime_helicobacter_test"], catalog_version="old-catalog"), CONTEXT)
        self.assertEqual(response_http_status(stale), 409)
        self.assertEqual(stale["errors"][0]["code"], "catalog_changed")

    def test_direct_plan_cannot_bypass_global_stop_or_missing_urgent(self):
        for urgent, status in (("chest_pain", "review"), ("other_now", "review"), (None, "needs_input")):
            with self.subTest(urgent=urgent):
                patient = {**self.patient, "urgent": urgent} if urgent else {key: value for key, value in self.patient.items() if key != "urgent"}
                result = plan_selection(patient, self.selection(["prime_helicobacter_test"]), CONTEXT)
                self.assertEqual(result["status"], status)
                self.assertIsNone(result["package"])
                self.assertEqual(result["selected_items"], [])
                self.assertEqual(result["route"], [])
                self.assertEqual(result["schedule"]["status"], "not_run")
                if urgent == "other_now":
                    self.assertNotIn("103", str(result["warnings"]))

    def test_removing_locally_restricted_items_clears_only_their_review(self):
        patient = {**self.patient, "sex": "F", "birth_date": "1982-03-01", "pregnant": "yes"}
        recommendation = recommend(patient, CONTEXT)
        flagged = {item["procedure_id"] for item in recommendation["items"] if item["requires_review"]}
        self.assertIn("prime_chest_ct", flagged)
        self.assertIn("prime_mammography_2d3d", flagged)
        self.assertIn("prime_ophthalmology_if_indicated", flagged)
        self.assertNotIn("prime_helicobacter_test", flagged)
        request = self.selection(self.ids(recommendation) - flagged, recommendation=recommendation)
        result = plan_selection(patient, request, CONTEXT)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["schedule"]["status"], "feasible")
        self.assertTrue(all(not item["clinical_flags"] for item in result["selected_items"]))
        self.assertFalse(any(row["code"] == "PRELIMINARY" for row in result["warnings"]))
        self.assertEqual(self.ids(result, "removed_recommended_items"), flagged)
        self.assertEqual(result["questions"], [])

    def test_added_restricted_item_is_kept_with_review_and_unrelated_service_is_clear(self):
        patient = {**self.patient, "sex": "F", "birth_date": "1988-01-10", "pregnant": "unsure"}
        recommendation = recommend(patient, CONTEXT)
        ids = ["prime_helicobacter_test", "prime_mammography_2d3d"]
        result = plan_selection(patient, self.selection(ids, recommendation=recommendation), CONTEXT)
        self.assertEqual(result["status"], "review")
        self.assertEqual(self.ids(result, "selected_items"), set(ids))
        self.assertEqual(result["schedule"]["status"], "not_run")
        self.assertEqual(result["route_status"], "draft")
        self.assertEqual({row["procedure_id"] for row in result["route"]}, set(ids))
        by_id = {item["procedure_id"]: item for item in result["selected_items"]}
        self.assertFalse(by_id["prime_helicobacter_test"]["clinical_flags"])
        self.assertTrue(by_id["prime_mammography_2d3d"]["clinical_flags"])
        self.assertTrue(by_id["prime_mammography_2d3d"]["screening_matches"])
        self.assertTrue(all(row["match_degree"] == "partial" for row in by_id["prime_mammography_2d3d"]["screening_matches"]))

    def test_child_extended_preserves_exact_variant_and_compares_against_recommended_mini(self):
        patient = {**self.patient, "birth_date": "2016-04-04", "for_child": True}
        recommendation = recommend(patient, CONTEXT)
        self.assertEqual(recommendation["package"]["variant_id"], "mini")
        request = self.selection(mode="preset", recommendation=recommendation, variant_id="extended")
        result = plan_selection(patient, request, CONTEXT)
        extended = next(option for option in recommendation["package_options"] if option["package_id"] == "prime_child" and option["variant_id"] == "extended")
        selected, recommended = set(extended["selected_procedure_ids"]), self.ids(recommendation)
        self.assertEqual(self.ids(result, "selected_items"), selected)
        self.assertEqual(self.ids(result, "added_items"), selected - recommended)
        self.assertEqual(self.ids(result, "removed_recommended_items"), recommended - selected)
        self.assertTrue(all(item["selection_reason"]["rule_id"] == "selected_preset" for item in result["added_items"]))
        self.assertEqual(result["recommended_package"]["variant_id"], "mini")
        self.assertEqual(result["alternatives"], [])

    def test_ineligible_preset_is_not_automatically_assigned(self):
        request = self.selection(mode="preset", base_package_id="prime_child", variant_id="mini")
        result = plan_selection(self.patient, request, CONTEXT)
        self.assertEqual(response_http_status(result), 422)
        self.assertEqual(result["errors"][0]["code"], "ineligible_preset")

    def test_busy_day_never_changes_selection_and_next_visit_is_not_invented(self):
        ids = ["prime_curator_consultation_group", "prime_helicobacter_test"]
        static_before = load_data("completed.json")
        result = plan_selection(self.patient, self.selection(ids), {**CONTEXT, "availability": "busy"})
        self.assertEqual(result["schedule"]["status"], "infeasible")
        self.assertEqual(self.ids(result, "selected_items"), set(ids))
        self.assertEqual(self.ids(result, "health_card"), set(ids))
        self.assertTrue(all(row["status"] == "не пройдено" and row["result"] == "нет данных" for row in result["health_card"]))
        self.assertEqual(result["after_results"][0]["action_id"], "prime_curator_final")
        self.assertEqual(result["after_results"][0]["procedure_id"], "prime_curator_consultation_group")
        self.assertIsNone(result["next_visit"][0]["date"])
        self.assertIsNone(result["next_visit"][0]["year"])
        self.assertIsNone(result["next_visit"][0]["basis"])
        self.assertTrue(result["next_visit"][0]["reason"])
        self.assertIsNone(result["reminder_draft"]["due_date"])
        self.assertFalse(result["reminder_draft"]["sent"])
        result["next_visit"][0]["date"] = "2099-01-01"
        next_result = plan_selection(self.patient, self.selection(ids), CONTEXT)
        self.assertIsNone(next_result["next_visit"][0]["date"])
        self.assertEqual(load_data("completed.json"), static_before)

    def test_known_prerequisite_and_category_order_have_different_outcomes(self):
        ids = ["prime_echocardiography"]
        request = self.selection(ids)
        ordinary = plan_selection(self.patient, request, CONTEXT)
        self.assertEqual(ordinary["status"], "ready")
        self.assertEqual(ordinary["schedule"]["status"], "feasible")
        self.assertEqual({row["procedure_id"] for row in ordinary["route"]}, set(ids))
        slots = load_data("prime_slots.json")
        slots["procedures"][ids[0]]["predecessors"] = ["prime_helicobacter_test"]
        result = plan_selection(self.patient, request, CONTEXT, slots=slots)
        self.assertEqual(result["status"], "review")
        self.assertEqual(self.ids(result, "selected_items"), set(ids))
        self.assertEqual(result["schedule"]["status"], "not_run")
        self.assertTrue(any(row.get("prerequisite_id") == "prime_helicobacter_test" for row in result["unresolved_items"]))

    def test_screenings_are_separate_and_paid_match_needs_explicit_selection(self):
        patient = {**self.patient, "birth_date": "1976-01-10", "attached_to": "unknown"}
        recommendation = recommend(patient, CONTEXT)
        self.assertTrue(all(row["where"] == "Уточнить поликлинику прикрепления" for row in recommendation["screening"]))
        target = "prime_hba1c"
        self.assertTrue(any(match["procedure_id"] == target for row in recommendation["screening"] for match in row["prime_matches"]))
        result = plan_selection(patient, self.selection([target, target], recommendation=recommendation), CONTEXT)
        self.assertEqual(self.ids(result, "selected_items"), {target})
        self.assertEqual(len(result["selected_items"]), 1)
        self.assertTrue(all(not item["procedure_id"].startswith("scr_") for item in result["selected_items"]))
        self.assertTrue(all(not row["payment"]["guaranteed"] for row in result["screening"]))
        self.assertEqual(result["next_visit"][0]["date"], None)

    def test_forged_client_result_fields_are_rejected_not_trusted(self):
        request = {"patient": self.patient, "context": CONTEXT, **self.selection(["prime_helicobacter_test"]), "status": "ready"}
        result = plan_request(request)
        self.assertEqual(response_http_status(result), 422)
        self.assertEqual(result["errors"][0]["field"], "status")


if __name__ == "__main__":
    unittest.main()
