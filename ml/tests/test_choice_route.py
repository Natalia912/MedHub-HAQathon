from copy import deepcopy
import unittest
from unittest.mock import patch

from prime_checkup.choice_route import plan_actions
from prime_checkup.engine import link_actions, load_data, make_item
from prime_checkup.scheduler import load_fixture, validate_schedule


class ChoiceRouteTests(unittest.TestCase):
    def synthetic(self):
        fixture = load_fixture("backtracking")
        by_id = {proc["id"]: {"id": proc["id"], "name": proc["name"]} for proc in fixture["procedures"]}
        items = [{"procedure_id": proc["id"], "name": proc["name"], "after_results": False} for proc in fixture["procedures"]]
        slots = {key: deepcopy(fixture[key]) for key in ("patient_window", "transition_minutes", "resources")}
        slots["procedures"] = {proc["id"]: {**{key: deepcopy(proc[key]) for key in ("duration_minutes", "resources", "predecessors")}, "category": 0}
                               for proc in fixture["procedures"]}
        slots["slots"] = {"normal": {proc["id"]: deepcopy(proc["slots"]) for proc in fixture["procedures"]}}
        return items, slots, by_id, fixture

    def test_actual_chronology_replaces_id_tiebreak_and_is_independently_valid(self):
        items, slots, by_id, fixture = self.synthetic()
        result = plan_actions(items, "synthetic", slots, "normal", by_id)
        self.assertEqual(result["route_status"], "ready")
        self.assertEqual([row["action_id"] for row in result["route"]], ["DEMO_B", "DEMO_A", "DEMO_C", "DEMO_D"])
        self.assertEqual([row["action_id"] for row in result["schedule"]["route"]], [row["action_id"] for row in result["route"]])
        native_route = [{**row, "procedure_id": row["action_id"]} for row in result["schedule"]["route"]]
        self.assertEqual(validate_schedule(fixture, native_route), [])
        self.assertTrue(all("start" not in row and "end" not in row for row in result["route"]))

    def test_removed_category_is_not_an_implicit_mandatory_prerequisite(self):
        items, slots, by_id, _ = self.synthetic()
        slots["procedures"]["DEMO_A"]["category"] = 0
        slots["procedures"]["DEMO_B"]["category"] = 1
        result = plan_actions([items[1]], "custom", slots, "normal", by_id)
        self.assertEqual(result["schedule"]["status"], "feasible")
        self.assertEqual([row["action_id"] for row in result["route"]], ["DEMO_B"])

    def test_missing_known_explicit_prerequisite_preserves_review_without_addition(self):
        items, slots, by_id, _ = self.synthetic()
        original = deepcopy(items[2:])
        result = plan_actions(items[2:], "custom", slots, "normal", by_id)
        self.assertTrue(result["requires_review"])
        self.assertEqual(result["schedule"]["status"], "not_run")
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["route_status"], "unresolved")
        self.assertEqual(result["unresolved_items"][0]["prerequisite_id"], "DEMO_A")
        self.assertEqual(items[2:], original)

    def test_bad_data_is_not_reported_as_busy(self):
        for code in ("DEPENDENCY_CYCLE", "UNKNOWN_ID", "INVALID_INTERVAL"):
            with self.subTest(code=code):
                items, slots, by_id, _ = self.synthetic()
                if code == "DEPENDENCY_CYCLE":
                    slots["procedures"]["DEMO_A"]["predecessors"] = ["DEMO_D"]
                elif code == "UNKNOWN_ID":
                    slots["procedures"]["DEMO_A"]["predecessors"] = ["absent_from_catalog"]
                else:
                    slots["slots"]["normal"]["DEMO_A"] = [[600, 590]]
                result = plan_actions(items, "custom", slots, "normal", by_id)
                self.assertEqual(result["schedule"]["status"], "not_run")
                self.assertIn(code, {error["code"] for error in result["errors"]})
                self.assertEqual(result["route"], [])

    def test_missing_time_data_keeps_complete_order_without_hours(self):
        for missing in ("duration_minutes", "slots"):
            with self.subTest(missing=missing):
                items, slots, by_id, _ = self.synthetic()
                if missing == "slots":
                    del slots["slots"]["normal"]["DEMO_C"]
                else:
                    del slots["procedures"]["DEMO_C"][missing]
                result = plan_actions(items, "custom", slots, "normal", by_id)
                self.assertEqual(result["schedule"]["status"], "needs_data")
                self.assertEqual(result["route_status"], "draft")
                self.assertEqual({row["action_id"] for row in result["route"]}, set(by_id))
                self.assertTrue(all(row["status"] == "draft" for row in result["route"]))
                self.assertEqual(result["schedule"]["route"], [])

    def test_missing_order_data_never_claims_complete_order(self):
        for missing in ("category", "predecessors"):
            with self.subTest(missing=missing):
                items, slots, by_id, _ = self.synthetic()
                del slots["procedures"]["DEMO_C"][missing]
                result = plan_actions(items, "custom", slots, "normal", by_id)
                self.assertEqual(result["schedule"]["status"], "needs_data")
                self.assertEqual(result["route_status"], "unresolved")
                self.assertEqual(result["route"], [])
                self.assertEqual({row["action_id"] for row in result["unresolved_items"]}, set(by_id))
                self.assertTrue(any(row.get("field") == f"procedures.DEMO_C.{missing}" for row in result["unresolved_items"]))

    def test_clinical_review_displays_draft_without_search(self):
        items, slots, by_id, _ = self.synthetic()
        with patch("prime_checkup.choice_route.schedule_visit", side_effect=AssertionError("Search must not run")):
            result = plan_actions(items, "custom", slots, "normal", by_id, requires_review=True)
        self.assertEqual(result["schedule"]["status"], "not_run")
        self.assertEqual(result["route_status"], "draft")
        self.assertEqual(len(result["route"]), 4)
        self.assertTrue(result["requires_review"])

    def test_infeasible_preserves_every_selected_action_in_draft(self):
        items, slots, by_id, _ = self.synthetic()
        slots["slots"]["normal"]["DEMO_B"] = []
        original = deepcopy(items)
        result = plan_actions(items, "custom", slots, "normal", by_id)
        self.assertEqual(result["schedule"]["status"], "infeasible")
        self.assertEqual(result["route_status"], "draft")
        self.assertEqual({row["action_id"] for row in result["route"]}, set(by_id))
        self.assertEqual(items, original)

    def test_curator_service_expands_to_two_stable_actions_with_common_service_id(self):
        catalog, slots = load_data("demo_catalog.json"), load_data("prime_slots.json")
        by_id = {item["id"]: item for item in catalog["procedures"]}
        service_id = "prime_curator_consultation_group"
        items = [make_item(by_id[service_id], {"rule_id": "custom", "explanation": "Selected for technical test"})]
        link_actions(items, by_id)
        result = plan_actions(items, "custom", slots, "normal", by_id)
        self.assertEqual(result["schedule"]["status"], "feasible")
        self.assertEqual([row["action_id"] for row in result["route"]], ["prime_curator_initial"])
        self.assertEqual([row["action_id"] for row in result["after_results"]], ["prime_curator_final"])
        self.assertEqual({row["procedure_id"] for row in result["route"] + result["after_results"]}, {service_id})
        self.assertEqual(result["schedule"]["route"][0]["procedure_id"], service_id)
        self.assertEqual(len(items), 1)

    def test_after_results_dependencies_are_checked_even_without_same_day_slots(self):
        items, slots, by_id, _ = self.synthetic()
        items[-1]["after_results"] = True
        slots["procedures"]["DEMO_D"]["predecessors"] = ["unknown_action"]
        result = plan_actions(items, "custom", slots, "normal", by_id)
        self.assertIn("UNKNOWN_ID", {error["code"] for error in result["errors"]})


if __name__ == "__main__":
    unittest.main()
