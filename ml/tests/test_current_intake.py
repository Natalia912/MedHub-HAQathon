"""Current 744d7f7 intake facts, independently of the 48-state scenario runner."""
from copy import deepcopy
import unittest

from fastapi.testclient import TestClient

from prime_checkup.intake import CURRENT_SOURCE_SHA, REGISTRATION_MAP, SCREENINGS, normalize_input
from prime_checkup.main import app
from prime_checkup.screening import evaluate_screening


def current(**changes):
    patient = {"input_version": "clinic_v2", "sex": "M", "birth_date": "1974-05-12",
               "for_child": False, "urgent": "none", "conditions": ["none"],
               "registered": ["none"], "family_history": ["none"],
               "smoking": {"pack_years": 0}, "hazardous_work_10y": False,
               "last_screening": {code: "never" for code in sorted(SCREENINGS)}}
    patient.update(changes)
    return patient


class CurrentIntakeTests(unittest.TestCase):
    def normalized(self, raw):
        result, errors = normalize_input(raw)
        self.assertEqual(errors, [])
        return result

    def screening(self, patient, rule_id):
        return next(item for item in evaluate_screening(patient) if item["rule_id"] == rule_id)

    def test_current_nested_smoking_keeps_missing_and_zero_distinct(self):
        for quit_value, expected in ((None, "needs_input"), (0, "candidate"),
                                     (14, "candidate"), (15, "review"), (16, "not_eligible")):
            with self.subTest(quit_value=quit_value):
                smoking = {"pack_years": 25}
                if quit_value is not None:
                    smoking["quit_years_ago"] = quit_value
                patient = self.normalized(current(smoking=smoking))
                self.assertEqual(patient["smoking"]["pack_years"], 25)
                self.assertEqual(patient["smoking"]["quit_years_ago"], quit_value)
                self.assertEqual(patient["smoking"]["status"], "reported_exposure")
                result = self.screening(patient, "scr_lung")
                self.assertEqual(result["outcome"], expected)
                if quit_value is None:
                    self.assertIn("smoking.quit_years_ago", result["missing_fields"])

    def test_raw_current_and_derived_legacy_smoking_are_different(self):
        for version in ("clinic_v1", "df733c4"):
            patient = self.normalized(current(input_version=version, smoking={"pack_years": 25, "quit_years_ago": 0}))
            self.assertIsNone(patient["smoking"]["pack_years"])
        incomplete = current(input_version="df733c4", smoking=None, smoke_status="smokes",
                             cigs_per_day=20, quit_years_ago=0)
        patient = self.normalized(incomplete)
        self.assertIsNone(patient["smoking"]["pack_years"])
        self.assertEqual(patient["smoking"]["quit_years_ago"], 0)
        without_zero = deepcopy(incomplete)
        without_zero.pop("quit_years_ago")
        self.assertIsNone(self.normalized(without_zero)["smoking"]["quit_years_ago"])
        self.assertEqual(self.screening(patient, "scr_lung")["outcome"], "needs_input")

    def test_hazardous_false_string_no_and_unknown_are_not_truthy(self):
        for version, value in (("clinic_v2", False), ("df733c4", "no")):
            patient = self.normalized(current(input_version=version, hazardous_work_10y=value,
                                               smoke_status="never" if version == "df733c4" else None))
            self.assertEqual(patient["values"]["hazardous_work_10y"], "no")
            self.assertEqual(self.screening(patient, "scr_lung")["outcome"], "not_eligible")
        patient = self.normalized(current(smoking={"pack_years": 25}, hazardous_work_10y=True))
        self.assertEqual(self.screening(patient, "scr_lung")["outcome"], "candidate")

    def test_never_history_preserves_all_seven_programs_without_dates(self):
        for changes in ({}, {"sex": "F"}, {"birth_date": "2016-05-12", "for_child": True},
                        {"input_version": "df733c4", "birth_date": "2016-05-12", "for_child": True}):
            with self.subTest(changes=changes):
                raw = current(**changes)
                original = deepcopy(raw)
                patient = self.normalized(raw)
                self.assertEqual(raw, original)
                self.assertEqual({row["screening_id"] for row in patient["history"]}, SCREENINGS)
                for row in patient["history"]:
                    self.assertEqual(row["performed_status"], "never")
                    self.assertEqual(row["date_precision"], "not_applicable")
                    self.assertIsNone(row["performed_year"])
                    self.assertIsNone(row["performed_on"])
                    self.assertEqual((row["result_status"], row["review_status"]), ("unknown", "unknown"))

    def test_known_year_unknown_and_imported_range_do_not_become_never(self):
        for version, supplied, precision, year in (("clinic_v2", 2025, "year", 2025),
                                                  ("clinic_v2", "unknown", "unknown", None),
                                                  ("clinic_v2", None, "unknown", None),
                                                  ("df733c4", 2025, "range", None)):
            with self.subTest(version=version, supplied=supplied):
                patient = self.normalized(current(input_version=version, sex="F",
                                                   last_screening={"scr_breast": supplied}))
                record = patient["history"][0]
                self.assertEqual(record["date_precision"], precision)
                self.assertEqual(record["performed_year"], year)
                self.assertIsNone(record["performed_on"])
                self.assertNotEqual(record.get("performed_status"), "never")

    def test_independent_registration_requires_explicit_answer(self):
        for version in ("clinic_v1", "clinic_v2", "df733c4"):
            with self.subTest(version=version):
                raw = current(input_version=version)
                raw.pop("registered")
                patient = self.normalized(raw)
                self.assertFalse(patient["registration"]["known_negative"])
                self.assertEqual(self.screening(patient, "scr_cvd")["outcome"], "needs_input")
                raw["registered"] = ["none"]
                self.assertTrue(self.normalized(raw)["registration"]["known_negative"])

    def test_legacy_broad_registration_and_separate_negative_codes(self):
        patient = self.normalized(current(input_version="df733c4", sex="F", birth_date="1984-05-12",
            conditions=["breast"], registered_on=["breast"], registered=["breast_cancer"],
            registered_absent=sorted(set(REGISTRATION_MAP.values()) - {"breast_cancer"}),
            provenance={"registered": "df733c4:REGISTERED_AS", "registered_absent": "patient_reported"},
            pregnant="no"))
        self.assertEqual(patient["registration"]["confirmed_codes"], [])
        self.assertEqual(patient["registration"]["ambiguous_codes"], ["breast_cancer"])
        self.assertNotIn("breast_cancer", patient["registration"]["negative_codes"])
        self.assertEqual(self.screening(patient, "scr_breast")["outcome"], "needs_input")
        self.assertEqual(self.screening(patient, "scr_cvd")["outcome"], "candidate")

    def test_six_unsure_answers_and_risk_context_are_preserved(self):
        for sex, sex_field in (("F", "discharge"), ("M", "dysuria")):
            raw = current(sex=sex, risk_group={"pregnancy": "unknown", "planned_surgery": "no"},
                          anesthesia_reaction="unsure", blood_thinners="unsure", allergy="unsure",
                          companion="unsure", **{sex_field: "unsure"})
            patient = self.normalized(raw)
            for field in (sex_field, "anesthesia_reaction", "blood_thinners", "allergy", "companion"):
                self.assertEqual(patient["answers"][field]["state"], "unknown")
                self.assertEqual(patient["answers"][field]["value"], "unsure")
            risk = next(row for row in patient["doctor_summary"] if row["field"] == "risk_group")
            self.assertEqual(risk["value"], raw["risk_group"])

    def test_child_preparation_facts_survive_but_adult_questions_do_not(self):
        patient = self.normalized(current(birth_date="2016-05-12", for_child=True,
            anesthesia_reaction="no", blood_thinners="no", companion="yes"))
        summary = {row["field"]: row for row in patient["doctor_summary"]}
        for field in ("anesthesia_reaction", "blood_thinners", "companion"):
            self.assertEqual(summary[field]["state"], "answered")
        self.assertEqual(patient["answers"]["smoking"]["state"], "not_applicable")
        self.assertIsNone(patient["smoking"]["pack_years"])
        self.assertEqual(patient["answers"]["hazardous_work_10y"]["state"], "not_applicable")

    def test_current_validation_and_known_source_through_public_api(self):
        client = TestClient(app)
        response = client.post("/recommend", json={"patient": current()})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["input_context"]["source_sha"], CURRENT_SOURCE_SHA)
        self.assertEqual(data["versions"]["engine"], "demo-3")
        self.assertEqual(data["versions"]["catalog"], "demo-2")
        for changes in ({"urgent": "other_now"}, {"smoke_status": "smokes"},
                        {"registered": ["diabetes"], "registered_absent": ["diabetes"]},
                        {"risk_group": ["invented"]}, {"last_screening": {"scr_cvd": 0}}):
            with self.subTest(changes=changes):
                response = client.post("/recommend", json={"patient": current(**changes)})
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["status"], "invalid")

    def test_adult_age_boundary_is_a_local_screening_question(self):
        before = self.normalized(current(birth_date="2008-10-01", for_child=True))
        self.assertEqual((before["age_full"], before["age_year"]), (17, 18))
        self.assertEqual(self.screening(before, "scr_hepatitis")["outcome"], "review")
        after = self.normalized(current(birth_date="2008-10-01", for_child=False, as_of_date="2026-10-01"))
        self.assertEqual((after["age_full"], after["age_year"]), (18, 18))
        self.assertEqual(self.screening(after, "scr_hepatitis")["outcome"], "candidate")

    def test_other_context_is_preserved_without_a_listed_condition(self):
        raw = current(conditions_other="Синтетическое сообщение вне списка, без клинической интерпретации")
        response = TestClient(app).post("/recommend", json={"patient": raw})
        self.assertEqual(response.status_code, 200)
        result = response.json()
        summary = next(row for row in result["doctor_summary"] if row["field"] == "conditions_other")
        self.assertEqual(summary["value"], raw["conditions_other"])
        self.assertEqual(summary["state"], "answered")
        self.assertEqual(result["proposed_extras"], [])

    def test_current_last_period_cannot_precede_birth_date(self):
        client = TestClient(app)
        for supplied, expected_http in (("1991-05-11", 422), ("2026-09-10", 200)):
            with self.subTest(supplied=supplied):
                response = client.post("/recommend", json={"patient": current(
                    sex="F", birth_date="1991-05-12", pregnant="no", last_period=supplied)})
                self.assertEqual(response.status_code, expected_http)
                if expected_http == 422:
                    self.assertEqual(response.json()["errors"][0]["field"], "last_period")

    def test_current_missing_unknown_and_never_history_have_explicit_meaning(self):
        for supplied, outcome in (({}, "needs_input"), ({"scr_hepatitis": "unknown"}, "needs_input"),
                                  ({"scr_hepatitis": "never"}, "candidate")):
            with self.subTest(supplied=supplied):
                response = TestClient(app).post("/recommend", json={"patient": current(last_screening=supplied)})
                self.assertEqual(response.status_code, 200)
                result = response.json()
                self.assertEqual(result["status"], "ready")
                hepatitis = next(row for row in result["screening"] if row["rule_id"] == "scr_hepatitis")
                self.assertEqual(hepatitis["outcome"], outcome)
                if outcome == "needs_input":
                    self.assertIn("last_screening.scr_hepatitis", hepatitis["missing_fields"])
                self.assertIsNone(result["reminder_draft"]["due_date"])
        for version in ("clinic_v1", "df733c4"):
            patient = self.normalized(current(input_version=version, last_screening={}))
            result = self.screening(patient, "scr_hepatitis")
            self.assertEqual(result["outcome"], "candidate")
            self.assertTrue(any("периодичность не установлена" in text for text in result["limitations"]))


if __name__ == "__main__":
    unittest.main()
