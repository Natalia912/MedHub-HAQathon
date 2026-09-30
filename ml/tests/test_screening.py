"""Tests of supplied project rules and cautious normalization, not medical advice."""
import json
import unittest
from copy import deepcopy
from pathlib import Path

from prime_checkup.screening import attach_screening_links, evaluate_screening


def patient(**updates):
    value = {
        "input_format": "clinic_v1", "age_full": 52, "age_year": 52, "sex": "M",
        "pregnant": None, "pregnancy_applicable": False,
        "values": {"conditions": ["none"], "hazardous_work_10y": False},
        "answers": {},
        "registration": {"confirmed_codes": [], "ambiguous_codes": [], "known_negative": True,
                         "source": "explicit_answer"},
        "smoking": {"status": "never", "pack_years": None, "quit_years_ago": None},
        "history": [], "context": {"checkup_year": 2026, "as_of_date": "2026-09-30"},
    }
    value.update(updates)
    return value


def outcome(value, rule_id):
    return next(rule for rule in evaluate_screening(value) if rule["rule_id"] == rule_id)


class ScreeningTests(unittest.TestCase):
    def test_all_seven_source_rules_are_preserved_without_medical_approval(self):
        root = Path(__file__).parents[1]
        source = json.loads((root / "reference/df733c4/spec/rules.json").read_text(encoding="utf-8"))
        active = json.loads((root / "prime_checkup/data/screening_rules.json").read_text(encoding="utf-8"))
        self.assertEqual(source["screening"], active["screening"])
        self.assertEqual(len(evaluate_screening(patient())), 7)
        self.assertTrue(all(row["medical_validated"] is False for row in evaluate_screening(patient())))
        self.assertEqual(evaluate_screening({"input_format": "legacy"}), [])

    def test_calendar_age_is_used_and_irrelevant_registration_is_not_requested(self):
        value = patient(age_full=39, age_year=40, sex="F", pregnancy_applicable=True, pregnant="no")
        self.assertEqual(outcome(value, "scr_breast")["outcome"], "candidate")
        value = patient(age_full=10, age_year=10, registration={})
        self.assertTrue(all(row["outcome"] == "not_eligible" for row in evaluate_screening(value)))
        self.assertTrue(all(row["missing_fields"] == [] for row in evaluate_screening(value)))

    def test_missing_registration_is_unknown_not_negative(self):
        self.assertEqual(outcome(patient(registration={}, values={}), "scr_cvd")["outcome"], "needs_input")
        self.assertEqual(outcome(patient(), "scr_cvd")["outcome"], "candidate")

    def test_broad_conditions_and_imported_codes_do_not_establish_cancer(self):
        for broad, code, rule_id, sex, age in [
            ("breast", "breast_cancer", "scr_breast", "F", 42),
            ("hpv", "cervical_cancer", "scr_cervix", "F", 42),
            ("lungs", "lung_cancer", "scr_lung", "M", 52),
        ]:
            with self.subTest(condition=broad):
                value = patient(sex=sex, age_year=age,
                                values={"conditions": [broad], "hazardous_work_10y": True},
                                registration={"ambiguous_codes": [code], "confirmed_codes": [], "known_negative": False})
                self.assertEqual(outcome(value, rule_id)["outcome"], "needs_input")
                value["registration"]["ambiguous_codes"] = []
                self.assertEqual(outcome(value, rule_id)["outcome"], "needs_input")
                value["registration"]["confirmed_codes"] = [code]
                self.assertEqual(outcome(value, rule_id)["outcome"], "not_eligible")

    def test_knowledge_of_pregnancy_has_its_own_effect_for_hepatitis(self):
        for pregnant, expected in [("no", "candidate"), ("yes", "not_eligible"),
                                   ("unsure", "review"), (None, "needs_input")]:
            with self.subTest(pregnant=pregnant):
                value = patient(sex="F", pregnancy_applicable=True, pregnant=pregnant)
                self.assertEqual(outcome(value, "scr_hepatitis")["outcome"], expected)
        self.assertEqual(outcome(patient(), "scr_hepatitis")["outcome"], "candidate")

    def test_missing_quit_duration_is_not_zero_and_other_missing_smoking_data_are_not_zero(self):
        value = patient(smoking={"status": "quit", "pack_years": 25, "quit_years_ago": None})
        result = outcome(value, "scr_lung")
        self.assertEqual(result["outcome"], "needs_input")
        self.assertIn("quit_years_ago", result["missing_fields"])
        value["smoking"]["quit_years_ago"] = 0
        self.assertEqual(outcome(value, "scr_lung")["outcome"], "candidate")
        value["smoking"]["pack_years"] = None
        result = outcome(value, "scr_lung")
        self.assertEqual(result["outcome"], "needs_input")
        self.assertIn("cigs_per_day", result["missing_fields"])
        self.assertIn("smoke_years", result["missing_fields"])

    def test_smoking_or_work_has_three_valued_logic(self):
        cases = [
            ({}, True, "candidate"),
            ({"status": "never"}, None, "needs_input"),
            ({"status": "never"}, False, "not_eligible"),
            ({"status": "smokes", "pack_years": 25}, None, "candidate"),
            ({"status": "smokes", "pack_years": None}, False, "needs_input"),
            ({"status": "smokes", "pack_years": 10}, True, "candidate"),
            ({"status": "quit", "pack_years": None, "quit_years_ago": 20}, False, "not_eligible"),
        ]
        for smoking, hazardous, expected in cases:
            with self.subTest(smoking=smoking, hazardous=hazardous):
                value = patient(smoking=smoking, values={"hazardous_work_10y": hazardous})
                self.assertEqual(outcome(value, "scr_lung")["outcome"], expected)

    def test_source_operator_conflict_is_local_to_disputed_boundary(self):
        for pack_years, quit, expected in [(20, 14, "candidate"), (20, 15, "review"),
                                          (20, 16, "not_eligible"), (19, 15, "not_eligible")]:
            with self.subTest(pack_years=pack_years, quit=quit):
                value = patient(smoking={"status": "quit", "pack_years": pack_years, "quit_years_ago": quit})
                self.assertEqual(outcome(value, "scr_lung")["outcome"], expected)
        value = patient(smoking={"status": "quit", "pack_years": 20, "quit_years_ago": 15},
                        values={"hazardous_work_10y": True})
        self.assertEqual(outcome(value, "scr_lung")["outcome"], "candidate")

    def test_unavailable_work_question_at_two_age_boundary_requests_rule_review(self):
        from prime_checkup.intake import normalize_input

        raw = {"input_version": "clinic_v1", "sex": "M", "birth_date": "1976-12-01",
               "as_of_date": "2026-09-30", "checkup_year": 2026, "urgent": "none",
               "conditions": ["none"], "registered": ["none"], "smoke_status": "never", "hazardous_work_10y": "yes"}
        value, errors = normalize_input(raw)
        self.assertEqual(errors, [])
        self.assertEqual((value["age_full"], value["age_year"]), (49, 50))
        self.assertEqual(value["answers"]["hazardous_work_10y"]["state"], "not_applicable")
        result = outcome(value, "scr_lung")
        self.assertEqual(result["outcome"], "review")
        self.assertIn("49", result["reason"])
        self.assertIn("50", result["reason"])
        self.assertNotIn("hazardous_work_10y", result["missing_fields"])
        raw.update(smoke_status="smokes", cigs_per_day=20, smoke_years=25)
        value, errors = normalize_input(raw)
        self.assertEqual(errors, [])
        self.assertEqual(outcome(value, "scr_lung")["outcome"], "candidate")

    def test_contradictory_smoking_metadata_is_local_unknown_until_independent_branch_is_true(self):
        from prime_checkup.engine import build_plan

        raw = {"input_version": "clinic_v1", "sex": "M", "birth_date": "1974-02-02", "urgent": "none",
               "conditions": ["none"], "registered": ["none"], "smoke_status": "smokes", "cigs_per_day": 20, "smoke_years": 25,
               "smoking": {"pack_years": 5, "quit_years_ago": 0}, "hazardous_work_10y": "no"}
        result = build_plan(raw)
        self.assertEqual(result["status"], "ready")
        lung = next(rule for rule in result["screening"] if rule["rule_id"] == "scr_lung")
        self.assertEqual(lung["outcome"], "needs_input")
        self.assertIn("smoking", lung["missing_fields"])
        self.assertIsNone(result["input_context"]["smoking"]["pack_years"])
        raw["hazardous_work_10y"] = "yes"
        result = build_plan(raw)
        lung = next(rule for rule in result["screening"] if rule["rule_id"] == "scr_lung")
        self.assertEqual(lung["outcome"], "candidate")

    def test_history_range_and_real_year_are_not_replaced_by_invented_dates(self):
        value = patient(sex="F", age_year=42, history=[{
            "screening_id": "scr_breast", "date_precision": "range", "performed_on": None,
            "performed_year": None, "range_start": "2024-09-30", "range_end": "2026-09-30",
        }])
        original = deepcopy(value)
        result = outcome(value, "scr_breast")
        self.assertEqual(result["outcome"], "needs_input")
        self.assertEqual(value, original)
        value["history"].append({"screening_id": "scr_breast", "date_precision": "year",
                                 "performed_year": 2025, "performed_on": None})
        result = outcome(value, "scr_breast")
        self.assertEqual(result["outcome"], "not_eligible")
        self.assertIn("2025 год", result["reason"])
        self.assertNotIn("due_date", result)
        self.assertIsNone(value["history"][1]["performed_on"])

    def test_absent_history_limits_claim_but_does_not_invent_interval_or_reminder(self):
        result = outcome(patient(), "scr_cvd")
        self.assertEqual(result["outcome"], "candidate")
        self.assertTrue(any("периодичность не установлена" in note for note in result["limitations"]))
        self.assertNotIn("due_date", result)
        self.assertNotIn("repeat_on", result)

    def test_links_do_not_remove_items_hide_pregnancy_or_claim_payment(self):
        items = [{"procedure_id": "prime_mammography_2d3d", "clinical_flags": ["requires_clinician"]},
                 {"procedure_id": "prime_helicobacter_test", "clinical_flags": []}]
        original = deepcopy(items)
        screening = evaluate_screening(patient(sex="F", age_year=42))
        linked = attach_screening_links(items, screening)
        self.assertEqual(items, original)
        self.assertEqual(len(linked), len(items))
        self.assertEqual(linked[0]["clinical_flags"], ["requires_clinician"])
        self.assertEqual(linked[0]["screening_matches"][0]["screening_id"], "scr_breast")
        self.assertEqual(linked[0]["screening_matches"][0]["match_degree"], "partial")
        self.assertEqual(linked[1]["screening_matches"], [])
        linked[0]["clinical_flags"].append("changed_copy")
        self.assertEqual(attach_screening_links(items, screening)[0]["clinical_flags"], ["requires_clinician"])
        for item in linked:
            self.assertNotIn("free", item)
            self.assertNotIn("completed", item)

    def test_undisclosed_group_overlap_stays_unknown(self):
        linked = attach_screening_links([{"procedure_id": "prime_blood_panel_40plus_group"}], evaluate_screening(patient()))
        self.assertEqual(linked[0]["screening_matches"][0]["match_degree"], "unknown")


if __name__ == "__main__":
    unittest.main()
