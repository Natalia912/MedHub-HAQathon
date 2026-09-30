"""Input provenance and arithmetic regressions; no claim of medical validation."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from prime_checkup.intake import DEFAULTS, field_applicable, normalize_input


BASE = {"input_version": "clinic_v1", "sex": "F", "birth_date": "1986-12-01", "urgent": "none"}


class IntakeTests(unittest.TestCase):
    def normalized(self, raw):
        result, errors = normalize_input(raw)
        self.assertEqual(errors, [])
        self.assertIsNotNone(result)
        return result

    def test_all_nine_original_exports_and_no_mutation(self):
        path = Path(__file__).resolve().parents[1] / "reference/df733c4/ml/sample_inputs.json"
        samples = json.loads(path.read_text(encoding="utf8"))
        self.assertEqual(len(samples), 9)
        original = deepcopy(samples)
        for sample in samples:
            with self.subTest(sample=sample["name"]):
                result = self.normalized(sample["input"])
                self.assertEqual(result["input_format"], "df733c4")
                self.assertEqual(result["context"]["as_of_date"], "2026-09-30")
                self.assertEqual(result["context"]["checkup_year"], 2026)
                self.assertNotIn("family_crc", result)
                self.assertIsNone(result["values"].get("conditions") if "conditions" not in sample["input"] else None)
        self.assertEqual(samples, original)

    def test_two_ages_context_and_birth_year_only(self):
        result = self.normalized(BASE)
        self.assertEqual((result["age_full"], result["age_year"]), (39, 40))
        self.assertEqual(result["context"]["defaulted"], list(DEFAULTS))
        birthday = self.normalized({**BASE, "as_of_date": "2026-12-01"})
        self.assertEqual(birthday["age_full"], 40)
        year_only = self.normalized({"input_version": "clinic_v1", "birth_year": 1986, "urgent": "none"})
        self.assertIsNone(year_only["age_full"])
        self.assertEqual(year_only["age_year"], 40)

    def test_bad_types_dates_conflicting_formats_and_extra_fields(self):
        variations = [
            {"birth_year": 1985}, {"birth_date": "2026-02-30"}, {"birth_date": "2027-01-01"},
            {"birth_date": "1986-1-1"}, {"birth_year": 1986.5}, {"birth_year": True},
            {"age": 39}, {"age": 39, "input_version": "legacy"}, {"sex": "x"},
            {"extra_field": 1}, {"pregnancies": 1.5}, {"for_child": "false"},
            {"conditions": ["invented"]}, {"conditions": ["none", "breast"]},
            {"conditions": "none"}, {"smoking": {"pack_years": True}},
            {"cigs_per_day": True}, {"cigs_per_day": float("nan")},
            {"last_screening": {"scr_breast": 2027}}, {"last_period": "2026-10-01"},
            {"checkup_year": 1985}, {"input_version": "invented"},
        ]
        for change in variations:
            with self.subTest(change=change):
                result, errors = normalize_input({**BASE, **change})
                self.assertIsNone(result)
                self.assertTrue(errors)
                self.assertTrue(all(error["scope"] == "input" for error in errors))

    def test_urgent_is_parseable_without_optional_answers(self):
        for urgent in ("chest_pain", "other_now", "none", "unknown", None):
            with self.subTest(urgent=urgent):
                result = self.normalized({"input_version": "clinic_v1", "urgent": urgent})
                self.assertEqual(result["urgent"], None if urgent == "unknown" else urgent)
                self.assertIsNone(result["age_full"])
                self.assertEqual(result["questions"], [])

    def test_missing_negative_unknown_and_not_applicable_are_different(self):
        for extra, state, value in (({}, "unanswered", None), ({"family_history": []}, "unanswered", None),
                                    ({"family_history": ["none"]}, "answered", ["none"]),
                                    ({"family_history": ["unknown"]}, "unknown", None)):
            with self.subTest(extra=extra):
                patient = self.normalized({**BASE, **extra})
                self.assertEqual(patient["answers"]["family_history"]["state"], state)
                self.assertEqual(patient["values"]["family_history"], value)
        imported = self.normalized({**BASE, "input_version": "df733c4", "family_history": ["none"]})
        self.assertEqual(imported["answers"]["family_history"]["state"], "unknown")
        self.assertIsNone(imported["values"]["family_history"])
        male = self.normalized({**BASE, "sex": "M", "pregnant": "no", "discharge": "yes"})
        self.assertEqual(male["answers"]["pregnant"]["state"], "not_applicable")
        self.assertIsNone(male["values"]["discharge"])
        self.assertEqual(male["answers"]["discharge"]["value"], "yes")

    def test_contradictions_need_question_without_inventing_answer(self):
        adult_child = self.normalized({**BASE, "for_child": True})
        self.assertEqual(adult_child["age_full"], 39)
        self.assertEqual(adult_child["questions"][0]["field"], "for_child")
        baby = self.normalized({**BASE, "birth_date": "2026-09-01", "for_child": True})
        self.assertEqual(baby["age_full"], 0)
        pregnancy = self.normalized({**BASE, "sex": "M", "pregnant": "yes"})
        self.assertIsNone(pregnancy["pregnant"])
        self.assertTrue(any(question["field"] == "pregnant" for question in pregnancy["questions"]))
        registration = self.normalized({**BASE, "conditions": ["none"], "registered": ["breast_cancer"]})
        self.assertFalse(registration["registration"]["known_negative"])
        self.assertTrue(any(question["field"] == "registered" for question in registration["questions"]))

    def test_registration_broad_codes_are_not_diagnoses(self):
        for broad, precise in (("breast", "breast_cancer"), ("hpv", "cervical_cancer"), ("lungs", "lung_cancer")):
            with self.subTest(broad=broad):
                patient = self.normalized({**BASE, "input_version": "df733c4", "conditions": [broad],
                                           "registered": [precise], "provenance": {"registered": "confirmed_clinician"}})
                self.assertEqual(patient["registration"]["confirmed_codes"], [])
                self.assertEqual(patient["registration"]["ambiguous_codes"], [precise])
                self.assertEqual(patient["values"]["conditions"], [broad])
                explicit = self.normalized({**BASE, "registered": [precise], "provenance": {"registered": "confirmed_clinician"}})
                self.assertEqual(explicit["registration"]["confirmed_codes"], [precise])
                self.assertEqual(explicit["registration"]["ambiguous_codes"], [])
        missing = self.normalized(BASE)
        negative = self.normalized({**BASE, "conditions": ["none"]})
        self.assertFalse(missing["registration"]["known_negative"])
        # A broad history answer does not answer the separate registration question.
        self.assertFalse(negative["registration"]["known_negative"])
        explicit_negative = self.normalized({**BASE, "conditions": ["none"], "registered": ["none"]})
        self.assertTrue(explicit_negative["registration"]["known_negative"])

    def test_smoking_missing_quit_is_not_zero_and_derived_values_not_trusted(self):
        raw = {**BASE, "smoke_status": "quit", "cigs_per_day": 20, "smoke_years": 25,
               "smoking": {"pack_years": 25, "quit_years_ago": 0}}
        missing = self.normalized(raw)["smoking"]
        self.assertEqual(missing["pack_years"], 25)
        self.assertIsNone(missing["quit_years_ago"])
        zero = self.normalized({**raw, "quit_years_ago": 0})["smoking"]
        self.assertEqual(zero["quit_years_ago"], 0)
        self.assertEqual(zero["questions"], [])
        for field in ("cigs_per_day", "smoke_years"):
            with self.subTest(field=field):
                partial = {key: value for key, value in raw.items() if key != field}
                self.assertIsNone(self.normalized(partial)["smoking"]["pack_years"])
        standalone = self.normalized({**BASE, "smoking": {"pack_years": 25, "quit_years_ago": 0}})
        self.assertIsNone(standalone["smoking"]["pack_years"])
        changed = self.normalized({**raw, "smoking": {"pack_years": 30}})
        self.assertEqual(changed["questions"], [])
        self.assertTrue(any(question["field"] == "smoking" for question in changed["smoking"]["questions"]))
        self.assertIsNone(changed["smoking"]["pack_years"])

    def test_smoking_uncertainty_does_not_block_prime(self):
        from prime_checkup.engine import build_plan

        base = {"input_version": "clinic_v1", "sex": "M", "birth_date": "1976-01-01", "urgent": "none"}
        cases = [
            {"smoke_status": "smokes", "cigs_per_day": 20, "smoke_years": 25, "smoking": {"pack_years": 26}},
            {"smoke_status": "quit", "cigs_per_day": 20, "smoke_years": 40, "quit_years_ago": 20},
        ]
        for extra in cases:
            with self.subTest(extra=extra):
                patient = self.normalized({**base, **extra})
                self.assertEqual(patient["questions"], [])
                self.assertTrue(patient["smoking"]["questions"])
                self.assertIsNone(patient["smoking"]["pack_years"])
                self.assertIsNotNone(build_plan({**base, **extra})["package"])

    def test_semantically_stale_values_do_not_create_global_questions(self):
        cases = [
            {"sex": "M", "birth_date": "1976-01-01", "pregnancies": 1, "births": 2},
            {"sex": "M", "birth_date": "1991-01-01", "smoke_status": "never", "smoke_years": 40},
            {"sex": "M", "birth_date": "2016-01-01", "for_child": True, "smoke_status": "quit", "smoke_years": 25, "quit_years_ago": 15},
        ]
        for extra in cases:
            with self.subTest(extra=extra):
                patient = self.normalized({**BASE, **extra})
                self.assertEqual(patient["questions"], [])
                self.assertEqual(patient["smoking"]["questions"], [])

    def test_history_preserves_year_or_range_without_precise_date(self):
        cases = [
            ({"last_screening": ["scr_breast"]}, "range", None),
            ({"input_version": "df733c4", "last_screening": {"scr_breast": 2025}}, "range", None),
            ({"input_version": "df733c4", "last_screening": {"scr_breast": 2025}, "provenance": {"last_screening": "known_year"}}, "year", 2025),
            ({"last_screening": {"scr_breast": 2025}, "provenance": {"last_screening": "known_year"}}, "year", 2025),
            ({"last_screening": {"scr_breast": None}}, "unknown", None),
        ]
        for extra, precision, year in cases:
            with self.subTest(extra=extra):
                record = self.normalized({**BASE, **extra})["history"][0]
                self.assertEqual(record["date_precision"], precision)
                self.assertEqual(record["performed_year"], year)
                self.assertIsNone(record["performed_on"])
                self.assertEqual(record["result_status"], "unknown")
                self.assertEqual(record["review_status"], "unknown")

    def test_applicability_parent_changes_do_not_leak_values(self):
        child = self.normalized({**BASE, "birth_date": "2016-04-04", "for_child": True,
                                 "smoke_status": "smokes", "cigs_per_day": 20, "smoke_years": 1})
        self.assertIsNone(child["smoking"]["status"])
        self.assertIsNone(child["smoking"]["pack_years"])
        self.assertEqual(child["answers"]["cigs_per_day"]["state"], "not_applicable")
        changed = self.normalized({**BASE, "smoke_status": "never", "cigs_per_day": 20, "quit_years_ago": 2})
        self.assertIsNone(changed["values"]["cigs_per_day"])
        self.assertEqual(changed["smoking"]["pack_years"], 0)
        self.assertIsNone(changed["smoking"]["quit_years_ago"])
        self.assertIsNone(field_applicable("pregnant", {"sex": "F"}, None))
        self.assertFalse(field_applicable("pregnant", {"sex": "M"}, 30))
        self.assertIsNone(field_applicable("births", {"sex": "F", "pregnancies": "abc"}, 30))
        self.assertIsNone(field_applicable("registered_on", {"conditions": [42]}, 30))
        self.assertIsNone(field_applicable("pregnant", {"sex": "F"}, "abc"))

    def test_legacy_keeps_original_contract_and_no_new_answers(self):
        raw = {"age": 35, "sex": "F", "complaints_state": "none", "complaints": [],
               "family_crc": "no", "visit_date": "2026-10-01", "availability": "normal"}
        for versioned in (raw, {**raw, "input_version": "legacy"}):
            patient = self.normalized(versioned)
            self.assertEqual(patient["values"], raw)
            self.assertEqual(patient["input_format"], "legacy")
            self.assertIsNone(patient["pregnant"])
            self.assertIsNone(patient["urgent"])
            self.assertIsNone(patient["age_year"])
        for bad in (35.5, 0, 121):
            self.assertTrue(normalize_input({**raw, "age": bad})[1])


if __name__ == "__main__":
    unittest.main()
