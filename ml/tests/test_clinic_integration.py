"""Clinic intake business regression through Python and JSON transport."""
import json
import unittest
from copy import deepcopy
from pathlib import Path

from fastapi.testclient import TestClient

from prime_checkup.cards import get_completed_case
from prime_checkup.engine import build_plan, expand_actions, load_data, make_schedule_fixture
from prime_checkup.main import app
from prime_checkup.scheduler import validate_schedule
from prime_checkup.selection import recommend_request
from tests.helpers import clinic


class ClinicIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.sample_path = Path(__file__).parents[1] / "reference/df733c4/ml/sample_inputs.json"
        cls.samples = json.loads(cls.sample_path.read_text(encoding="utf-8"))

    def test_all_nine_unchanged_imported_inputs_reach_shared_engine_through_http(self):
        before = self.sample_path.read_bytes()
        self.assertEqual(len(self.samples), 9)
        for index, sample in enumerate(self.samples, 1):
            with self.subTest(example=index):
                source_input = deepcopy(sample["input"])
                result = build_plan(source_input)
                api = self.client.post("/predict", json=source_input)
                self.assertEqual(api.status_code, 200, api.text)
                self.assertEqual(api.json(), result)
                self.assertNotEqual(result["status"], "invalid")
                self.assertEqual(result["errors"], [])
                self.assertEqual(result["input_context"]["input_format"], "df733c4")
                self.assertEqual(result["input_context"]["as_of_date"], "2026-09-30")
                self.assertEqual(result["input_context"]["checkup_year"], 2026)
                self.assertFalse(result["medical_validated"])
                self.assertEqual(source_input, sample["input"])
                if sample["screen"].get("red_flag"):
                    self.assertIsNone(result["package"])
                else:
                    self.assertEqual(result["package"]["id"], sample["screen"]["package"])
        self.assertEqual(self.sample_path.read_bytes(), before)

    def test_age_full_selects_basic_while_screening_uses_age_year(self):
        result = build_plan(clinic(sex="F", birth_date="1986-12-01", pregnant="no"))
        self.assertEqual(result["input_context"]["age_full"], 39)
        self.assertEqual(result["input_context"]["age_year"], 40)
        self.assertEqual(result["package"]["id"], "prime_basic")
        breast = next(rule for rule in result["screening"] if rule["rule_id"] == "scr_breast")
        self.assertEqual(breast["outcome"], "candidate")

    def test_known_urgent_stops_before_optional_or_missing_answers(self):
        messages = {}
        for urgent in ("chest_pain", "other_now"):
            with self.subTest(urgent=urgent):
                response = self.client.post("/predict", json={"input_version": "clinic_v1", "urgent": urgent})
                self.assertEqual(response.status_code, 200)
                result = response.json()
                self.assertEqual(result["status"], "review")
                self.assertIsNone(result["package"])
                self.assertEqual(result["items"], [])
                self.assertEqual(result["questions"], [])
                self.assertEqual(result["schedule"]["status"], "not_run")
                self.assertEqual(result["schedule"]["route"], [])
                messages[urgent] = " ".join(w["message"] for w in result["warnings"])
                self.assertTrue(any(w.get("source") for w in result["warnings"]))
        self.assertNotEqual(messages["chest_pain"], messages["other_now"])
        self.assertNotIn("103", messages["other_now"])

    def test_unknown_and_missing_urgent_are_not_negative_answers(self):
        for value in (None, "unknown"):
            with self.subTest(urgent=value):
                payload = clinic()
                if value is None:
                    payload.pop("urgent")
                else:
                    payload["urgent"] = value
                result = build_plan(payload)
                self.assertEqual(result["status"], "needs_input")
                self.assertIsNone(result["package"])
                self.assertEqual(result["schedule"]["status"], "not_run")
                self.assertIn("urgent", [q["field"] for q in result["questions"]])
        self.assertEqual(build_plan(clinic())["status"], "ready")

    def test_pregnancy_flags_are_explicit_ids_and_independent_of_screening_links(self):
        for pregnant in ("yes", "unsure"):
            with self.subTest(pregnant=pregnant):
                result = build_plan(clinic(sex="F", birth_date="1982-03-01", pregnant=pregnant))
                self.assertEqual(result["status"], "review")
                self.assertTrue(result["package"]["preliminary"])
                self.assertEqual(result["schedule"]["status"], "not_run")
                self.assertEqual(result["schedule"]["route"], [])
                items = {item["procedure_id"]: item for item in result["items"]}
                flagged = {pid for pid, item in items.items()
                           if any(flag["code"] == "PREGNANCY_REVIEW" for flag in item["clinical_flags"])}
                self.assertEqual(flagged, {"prime_chest_ct", "prime_mammography_2d3d"})
                self.assertEqual(items["prime_helicobacter_test"]["clinical_flags"], [])
                self.assertTrue(items["prime_mammography_2d3d"]["screening_matches"])
                self.assertTrue(items["prime_mammography_2d3d"]["clinical_flags"])

    def test_pregnant_mammography_json_keeps_both_independent_annotations(self):
        response = self.client.post("/predict", json=clinic(sex="F", birth_date="1982-03-01", pregnant="yes"))
        self.assertEqual(response.status_code, 200)
        result = response.json()
        mammography = next(item for item in result["items"] if item["procedure_id"] == "prime_mammography_2d3d")
        self.assertTrue(mammography["clinical_flags"])
        self.assertTrue(mammography["screening_matches"])
        for flag in mammography["clinical_flags"]:
            self.assertTrue(flag["message"])
        for match in mammography["screening_matches"]:
            self.assertEqual(match["screening_id"], "scr_breast")
            self.assertTrue(match["explanation"])
        self.assertEqual(result["status"], "review")
        self.assertEqual(result["schedule"]["status"], "not_run")

    def test_applicable_missing_pregnancy_requests_clarification_after_preliminary_package(self):
        payload = clinic(sex="F", birth_date="1991-01-10")
        result = build_plan(payload)
        self.assertEqual(result["status"], "review")
        self.assertEqual(result["package"]["id"], "prime_basic")
        self.assertTrue(result["package"]["preliminary"])
        self.assertEqual(result["schedule"]["status"], "not_run")
        self.assertEqual(result["input_context"]["answers"]["pregnant"]["state"], "unanswered")
        self.assertIn("pregnant", [question["field"] for question in result["questions"]])

    def test_extras_are_discussion_only_and_consultations_are_not_duplicated(self):
        cases = [
            (dict(sex="F", birth_date="1991-01-10", pregnant="no", discharge="yes"), "prime_gynecology_consult", False),
            (dict(sex="M", birth_date="1974-01-10", dysuria="yes"), "prime_urology_consult", False),
            (dict(sex="M", birth_date="1988-01-10", dysuria="yes"), "prime_urology_consult", True),
        ]
        for changes, specialist, expected_extra in cases:
            with self.subTest(specialist=specialist, changes=changes):
                result = build_plan(clinic(**changes))
                extras = result["proposed_extras"]
                self.assertTrue(any(extra["name"] == "Обследование на половые инфекции" for extra in extras))
                self.assertEqual(any(extra["procedure_id"] == specialist for extra in extras), expected_extra)
                self.assertTrue(all(extra["scheduled"] is False for extra in extras))
                self.assertTrue(all(extra["validation_status"] == "demo_unvalidated" for extra in extras))
                if expected_extra:
                    self.assertNotIn(specialist, [item["procedure_id"] for item in result["items"]])
                    self.assertNotIn(specialist, [row["procedure_id"] for row in result["schedule"]["route"]])

    def test_zero_age_and_adult_child_flag_cannot_bypass_package_bounds(self):
        for payload in (clinic(for_child=True, birth_date="2026-05-10"), clinic(for_child=True)):
            with self.subTest(birth_date=payload["birth_date"]):
                result = build_plan(payload)
                self.assertIn(result["status"], ("review", "needs_input"))
                self.assertIsNone(result["package"])
                self.assertEqual(result["schedule"]["route"], [])
        child = build_plan(clinic(for_child=True, birth_date="2016-04-04"))
        self.assertEqual(child["package"]["id"], "prime_child")
        self.assertTrue(child["alternatives"])
        self.assertFalse(set(child["alternatives"][0]["procedure_ids"]) & {i["procedure_id"] for i in child["items"]})

    def test_new_questionnaire_does_not_apply_legacy_fatigue(self):
        result = build_plan(clinic(conditions=["legs"], conditions_other="Усталость — вымышленный текст для врача"))
        trace = next(row for row in result["trace"] if row["rule_id"] == "cmp_fatigue")
        self.assertEqual(trace["outcome"], "skipped")
        self.assertFalse(any(item["highlighted"] for item in result["items"]))
        self.assertTrue(any(row["field"] == "conditions_other" for row in result["doctor_summary"]))
        bad = self.client.post("/predict", json=clinic(complaints=["fatigue"]))
        self.assertEqual(bad.status_code, 422)
        self.assertTrue(any(error["field"] == "complaints" for error in bad.json()["errors"]))

    def test_conditional_extended_female_item_is_preserved_without_route(self):
        result = build_plan(clinic(sex="F", birth_date="1984-01-10", pregnant="no"))
        self.assertEqual(result["status"], "review")
        self.assertEqual(result["package"]["id"], "prime_extended")
        self.assertEqual(result["schedule"]["status"], "not_run")
        self.assertEqual(result["schedule"]["route"], [])
        conditional = next(item for item in result["items"] if item["procedure_id"] == "prime_ophthalmology_if_indicated")
        self.assertTrue(conditional["conditional"])
        self.assertFalse(conditional["required"])
        self.assertIn("INDICATION_REQUIRED", [flag["code"] for flag in conditional["clinical_flags"]])

    def test_ready_male_plan_has_every_action_and_independently_validated_schedule(self):
        result = build_plan(clinic())
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["schedule"]["status"], "feasible")
        fixture = make_schedule_fixture(result["items"], result["package"]["id"], load_data("prime_slots.json"), "normal")
        self.assertEqual(validate_schedule(fixture, result["schedule"]["route"]), [])
        expected_day = {item["procedure_id"] for item in expand_actions(result["items"]) if not item["after_results"]}
        self.assertEqual({row["procedure_id"] for row in result["schedule"]["route"]}, expected_day)
        after = result["schedule"]["after_results"]
        self.assertTrue(after)
        self.assertTrue(all(row["reason"] == "после готовности результатов" for row in after))
        self.assertTrue(any(item["action_ids"] and len(item["actions"]) == 2 for item in result["items"]))
        self.assertEqual(len(result["health_card"]), len(result["items"]))
        busy = build_plan(clinic(availability="busy"))
        self.assertEqual(busy["items"], result["items"])
        self.assertEqual(busy["schedule"]["status"], "infeasible")
        self.assertEqual(busy["schedule"]["route"], [])

    def test_unknown_screening_does_not_block_or_change_prime_composition(self):
        known = build_plan(clinic())
        missing_input = clinic()
        missing_input.pop("conditions")
        missing_input.pop("registered")
        unknown = build_plan(missing_input)
        self.assertEqual(unknown["status"], "ready")
        self.assertEqual(unknown["schedule"]["status"], "feasible")
        self.assertEqual([item["procedure_id"] for item in known["items"]], [item["procedure_id"] for item in unknown["items"]])
        self.assertIn("needs_input", [rule["outcome"] for rule in unknown["screening"]])
        self.assertIsNone(unknown["reminder_draft"]["due_date"])
        self.assertFalse(unknown["reminder_draft"]["sent"])

    def test_engine_and_json_share_normalized_business_result(self):
        payload = clinic(dysuria="yes", family_history=["none"], medications="Вымышленный препарат")
        api = self.client.post("/predict", json=payload)
        self.assertEqual(api.status_code, 200, api.text)
        self.assertEqual(build_plan(payload), api.json())
        self.assertEqual(api.json()["status"], "ready")
        self.assertTrue(api.json()["screening"])

    def test_nine_imported_recommendations_match_the_shared_engine(self):
        for index, sample in enumerate(self.samples, 1):
            with self.subTest(example=index):
                original = deepcopy(sample["input"])
                submitted = self.client.post("/recommend", json=original)
                self.assertEqual(submitted.status_code, 200, submitted.text)
                self.assertEqual(submitted.json(), recommend_request(original))
                self.assertEqual(submitted.json()["input_context"]["input_format"], "df733c4")
                self.assertEqual(original, sample["input"])

    def test_json_preserves_free_text_and_reports_field_errors(self):
        attack = '<script>alert("synthetic")</script>'
        payload = clinic(medications=attack)
        response = self.client.post("/predict", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/json", response.headers["content-type"])
        result = response.json()
        self.assertEqual(next(row["value"] for row in result["doctor_summary"] if row["field"] == "medications"), attack)
        payload["birth_date"] = "2026-02-30"
        response = self.client.post("/predict", json=payload)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), build_plan(payload))
        self.assertTrue(any(error["field"] == "birth_date" for error in response.json()["errors"]))
        self.assertEqual(payload["birth_date"], "2026-02-30")
        self.assertEqual(payload["medications"], attack)

    def test_new_answers_never_generate_results_or_mutate_fixed_cards(self):
        before = {case: get_completed_case(case)
                  for case in ("waiting", "received", "reviewed")}
        fixture_before = deepcopy(load_data("completed.json"))
        for payload in (clinic(), clinic(dysuria="yes"), clinic(sex="F", birth_date="1982-01-10", pregnant="yes")):
            result = self.client.post("/predict", json=payload).json()
            self.assertTrue(all(row["status"] == "не пройдено" and row["result"] == "нет данных" for row in result["health_card"]))
            self.assertIsNone(result["reminder_draft"]["due_date"])
            self.assertFalse(result["reminder_draft"]["sent"])
        for case, original in before.items():
            self.assertEqual(get_completed_case(case), original)
        self.assertEqual(load_data("completed.json"), fixture_before)
        self.assertEqual(before["waiting"]["history"][0]["performed_year"], 2025)
        self.assertIsNone(before["received"]["reminder_draft"]["due_date"])
        self.assertEqual(before["reviewed"]["reminder_draft"]["due_date"], "2026-10-15")

    def test_action_conflicts_and_broken_clinical_metadata_are_data_errors(self):
        for field, value in (("conflicts_with", ["prime_lung_ct"]), ("conditional", "false"), ("tags", "pregnancy_review")):
            with self.subTest(field=field):
                catalog = load_data("demo_catalog.json")
                initial = next(item for item in catalog["procedures"] if item["id"] == "prime_curator_initial")
                initial[field] = value
                result = build_plan(clinic(), catalog=catalog)
                self.assertEqual(result["status"], "invalid")
                self.assertEqual(result["schedule"]["status"], "not_run")
                self.assertEqual(result["schedule"]["route"], [])
                self.assertEqual(result["errors"][0]["scope"], "data")

    def test_unknown_answer_code_is_rejected_by_json(self):
        code = '<invalid-code>'
        payload = clinic(conditions=[code])
        response = self.client.post("/predict", json=payload)
        self.assertEqual(response.status_code, 422)
        self.assertTrue(any(error["field"] == "conditions" for error in response.json()["errors"]))
        self.assertEqual(payload["conditions"], [code])

if __name__ == "__main__":
    unittest.main()
