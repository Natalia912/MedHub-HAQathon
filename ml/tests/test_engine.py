"""Acceptance checks for catalog mechanics; these do not validate medicine."""
import unittest
from copy import deepcopy

from prime_checkup.engine import (
    DataError,
    add,
    build_plan,
    expand_actions,
    highlight,
    load_data,
    make_item,
    make_schedule_fixture,
    merge_same_ids,
    reason_for,
)
from prime_checkup.scheduler import load_fixture, schedule_visit, validate_schedule


def profile(**changes):
    value = {
        "age": 35,
        "sex": "F",
        "complaints_state": "none",
        "complaints": [],
        "family_crc": "no",
        "visit_date": "2026-10-01",
        "availability": "normal",
    }
    value.update(changes)
    return value


def ids(result):
    return {item["procedure_id"] for item in result["items"]}


class EngineTests(unittest.TestCase):
    def assert_unbuilt(self, result, status):
        self.assertEqual(result["status"], status)
        self.assertIsNone(result["package"])
        self.assertEqual(result["items"], [])
        self.assertEqual(result["schedule"]["route"], [])
        self.assertEqual(result["schedule"]["status"], "not_run")

    def assert_data_error(self, result, field=None):
        self.assertEqual(result["status"], "invalid", result)
        self.assertEqual(result["schedule"]["status"], "not_run")
        self.assertEqual(result["schedule"]["route"], [])
        self.assertTrue(result["errors"])
        self.assertTrue(all(error["scope"] == "data" for error in result["errors"]))
        if field:
            self.assertTrue(any(field in error["field"] for error in result["errors"]), result["errors"])

    def test_packages_and_sex_supplements_have_exact_composition(self):
        catalog = load_data("demo_catalog.json")
        packages = {package["id"]: package for package in catalog["packages"]}
        # df733c4 changes source rows (not atomic service counts): basic 11+5/3,
        # extended 9+6/6. Curator initial/final remains one source service.
        expectations = [
            (35, "F", "prime_basic", 16, {"prime_gynecology_consult", "prime_ecg", "prime_ferritin_iron_folate_group", "prime_transvaginal_ultrasound", "prime_breast_ultrasound"}),
            (35, "M", "prime_basic", 14, {"prime_hba1c", "prime_psa_total_free_group", "prime_prostate_bladder_scrotum_ultrasound_group"}),
            (42, "F", "prime_extended", 15, {"prime_gynecology_consult", "prime_ophthalmology_if_indicated", "prime_tumor_markers_expanded_group", "prime_pap_test", "prime_mammography_2d3d", "prime_female_extended_ultrasound_group"}),
            (42, "M", "prime_extended", 15, {"prime_urology_consult", "prime_ophthalmology_consult", "prime_hba1c", "prime_psa_total_free_group", "prime_prostate_scrotum_ultrasound_group", "prime_abdomen_thyroid_ultrasound_group"}),
            (10, "M", "prime_child", 8, set()),
            (10, "F", "prime_child", 8, set()),
        ]
        for age, sex, package_id, count, supplement in expectations:
            with self.subTest(age=age, sex=sex):
                result = build_plan(profile(age=age, sex=sex))
                # "По показаниям" cannot be silently made mandatory, even in
                # legacy regression mode. The package is a preliminary catalog.
                conditional = package_id == "prime_extended" and sex == "F"
                self.assertEqual(result["status"], "review" if conditional else "ready")
                self.assertEqual(result["package"]["id"], package_id)
                self.assertEqual(result["package"]["title"], "Кандидат по каталогу PRIME")
                self.assertIsNone(result["package"]["price"])
                self.assertEqual(ids(result), set(packages[package_id]["required_ids"]) | supplement)
                self.assertEqual(len(result["items"]), count)
                if conditional:
                    self.assertTrue(result["package"]["preliminary"])
                    self.assertEqual(result["schedule"]["status"], "not_run")
                    self.assertEqual(result["schedule"]["route"], [])
                    item = next(item for item in result["items"] if item["procedure_id"] == "prime_ophthalmology_if_indicated")
                    self.assertTrue(item["conditional"])
                    self.assertFalse(item["required"])
                    self.assertTrue(item["clinical_flags"])
                if package_id == "prime_child":
                    self.assertFalse(ids(result) & set(packages[package_id]["extended_ids"]))

    def test_age_boundaries_use_full_age_from_demo_catalog(self):
        for age, expected in [(1, "prime_child"), (17, "prime_child"), (18, "prime_basic"), (39, "prime_basic"), (40, "prime_extended"), (120, "prime_extended")]:
            with self.subTest(age=age):
                result = build_plan(profile(age=age))
                self.assertEqual(result["package"]["id"], expected)
                self.assertIn("AGE_40", [warning["code"] for warning in result["warnings"]])

    def test_invalid_input_never_coerces_age_or_codes(self):
        cases = [("age", age) for age in (-1, 0, 121, 35.5, 35.0, True, "35", None)]
        cases += [("sex", "X"), ("family_crc", "maybe"), ("availability", "free"), ("visit_date", "2026-02-30"), ("visit_date", "20261001")]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                result = build_plan(profile(**{field: value}))
                self.assert_unbuilt(result, "invalid")
                self.assertTrue(any(error["field"] == field and error["scope"] == "input" for error in result["errors"]))

    def test_complaints_require_consistent_explicit_state(self):
        cases = [
            {"complaints_state": "list", "complaints": []},
            {"complaints_state": "none", "complaints": ["fatigue"]},
            {"complaints_state": "unknown", "complaints": ["chest_pain"]},
            {"complaints_state": "list", "complaints": ["unlisted"]},
            {"complaints_state": "list", "complaints": "fatigue"},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                result = build_plan(profile(**changes))
                self.assert_unbuilt(result, "invalid")
                self.assertTrue(any(error["field"].startswith("complaints") for error in result["errors"]))
        missing = profile()
        del missing["family_crc"]
        self.assert_unbuilt(build_plan(missing), "invalid")

    def test_unknown_answers_are_questions_not_negative_answers(self):
        for field in ("sex", "complaints_state", "family_crc"):
            with self.subTest(field=field):
                result = build_plan(profile(**{field: "unknown"}))
                self.assert_unbuilt(result, "needs_input")
                self.assertEqual([question["field"] for question in result["questions"]], [field])
        combined = build_plan(profile(sex="unknown", complaints_state="unknown", family_crc="unknown"))
        self.assertEqual({question["field"] for question in combined["questions"]}, {"sex", "complaints_state", "family_crc"})
        trace = {item["rule_id"]: item["outcome"] for item in combined["trace"]}
        self.assertEqual(trace["cmp_chest_pain"], "unknown")
        self.assertEqual(trace["cmp_fatigue"], "unknown")
        self.assertEqual(trace["cmp_family_crc"], "unknown")
        self.assertEqual(build_plan(profile())["status"], "ready")

    def test_blocker_precedes_unrelated_unknown_answers(self):
        result = build_plan(profile(sex="unknown", complaints_state="list", complaints=["chest_pain", "fatigue"], family_crc="unknown"))
        self.assert_unbuilt(result, "review")
        self.assertEqual(result["questions"], [])
        trace = {item["rule_id"]: item["outcome"] for item in result["trace"]}
        self.assertEqual(trace, {"cmp_chest_pain": "matched", "cmp_fatigue": "skipped", "cmp_family_crc": "skipped"})
        self.assertIn("требуется обращение к врачу", result["warnings"][0]["message"])

    def test_format_errors_precede_blocker(self):
        result = build_plan(profile(age=35.5, complaints_state="list", complaints=["chest_pain"], family_crc="unknown"))
        self.assert_unbuilt(result, "invalid")
        self.assertEqual(result["trace"], [])
        self.assertEqual(result["questions"], [])

    def test_fatigue_only_highlights_existing_catalog_items(self):
        original = build_plan(profile())
        result = build_plan(profile(complaints_state="list", complaints=["fatigue"]))
        self.assertEqual(ids(result), ids(original))
        highlighted = {item["procedure_id"] for item in result["items"] if item["highlighted"]}
        # The updated catalog groups replace the old standalone targets. Do
        # not infer their hidden components to manufacture a highlight/add.
        self.assertEqual(highlighted, set())
        self.assertEqual(result["items"], original["items"])
        self.assertEqual(result["schedule"]["route"], original["schedule"]["route"])

        # Still exercise the positive highlight action with an explicitly
        # synthetic selection of preserved old IDs; it never becomes a plan.
        by_id = {item["id"]: item for item in load_data("demo_catalog.json")["procedures"]}
        rule = next(rule for rule in load_data("demo_rules.json")["rules"] if rule["id"] == "cmp_fatigue")
        synthetic_ids = [*rule["procedure_ids"], "prime_ecg"]
        items = [make_item(by_id[pid], {"rule_id": "SYNTHETIC_HIGHLIGHT", "explanation": "Явно вымышленный состав для проверки действия highlight"}) for pid in synthetic_ids]
        found, missing = highlight(items, rule)
        self.assertEqual(set(found), set(rule["procedure_ids"]))
        self.assertEqual(missing, [])
        self.assertEqual([item["procedure_id"] for item in items], synthetic_ids)
        self.assertFalse(next(item for item in items if item["procedure_id"] == "prime_ecg")["highlighted"])
        for item in items:
            if item["highlighted"]:
                reasons = [reason for reason in item["reasons"] if reason["rule_id"] == "cmp_fatigue"]
                self.assertEqual(len(reasons), 1)
                self.assertEqual(reasons[0]["source_rule_id"], "cmp_fatigue")
                self.assertEqual(reasons[0]["validation_status"], "demo_unvalidated")
                self.assertIs(reasons[0]["needs_doctor_validation"], True)
                self.assertIs(reasons[0]["medical_validated"], False)

    def test_missing_highlight_targets_remain_only_in_trace(self):
        result = build_plan(profile(age=42, complaints_state="list", complaints=["fatigue"]))
        original = build_plan(profile(age=42))
        self.assertEqual(ids(result), ids(original))
        self.assertFalse(any(item["highlighted"] for item in result["items"]))
        trace = next(item for item in result["trace"] if item["rule_id"] == "cmp_fatigue")
        self.assertEqual(trace["outcome"], "matched")
        self.assertEqual(trace["highlighted_ids"], [])
        self.assertEqual(set(trace["not_found_ids"]), {"prime_vitamin_d", "prime_vitamin_b12", "prime_anemia_group", "prime_thyroid_hormones_group"})

    def test_family_history_is_note_and_never_adds_colonoscopy(self):
        original = build_plan(profile(age=10, sex="M"))
        result = build_plan(profile(age=10, sex="M", family_crc="yes"))
        self.assertEqual(result["items"], original["items"])
        self.assertNotIn("prime_colonoscopy", ids(result))
        warning = next(warning for warning in result["warnings"] if warning["code"] == "cmp_family_crc")
        self.assertEqual(warning["message"], "В демо сработало правило семейного анамнеза; изменение программы требует обсуждения с врачом")
        self.assertEqual(warning["validation_status"], "demo_unvalidated")
        self.assertIs(warning["needs_doctor_validation"], True)
        self.assertIs(warning["medical_validated"], False)

    def test_synthetic_add_deduplicates_by_id_and_keeps_both_reasons(self):
        fixture = load_fixture("backtracking")
        by_id = {procedure["id"]: {**procedure, "source": "synthetic", "validation_status": "demo_unvalidated", "is_group": False, "after_results": False} for procedure in fixture["procedures"]}
        items = []
        for procedure_id in ("DEMO_A", "DEMO_B", "DEMO_C"):
            add(items, procedure_id, by_id, {"rule_id": "DEMO_PACKAGE", "explanation": "Синтетический базовый состав"})
        for rule_id in ("DEMO_ADD_ONE", "DEMO_ADD_TWO"):
            rule = {"id": rule_id, "source": "synthetic", "explanation": "Тестовое добавление D", "action": "add"}
            add(items, "DEMO_D", by_id, reason_for(rule))
        merged = merge_same_ids(items)
        self.assertEqual({item["procedure_id"] for item in merged}, {"DEMO_A", "DEMO_B", "DEMO_C", "DEMO_D"})
        self.assertEqual(len(merged), 4)
        added = next(item for item in merged if item["procedure_id"] == "DEMO_D")
        self.assertEqual({reason["rule_id"] for reason in added["reasons"]}, {"DEMO_ADD_ONE", "DEMO_ADD_TWO"})
        fixture["package"]["required_ids"] = [item["procedure_id"] for item in merged]
        result = schedule_visit(fixture)
        self.assertEqual(result["status"], "feasible")
        self.assertEqual(validate_schedule(fixture, result["route"]), [])
        self.assertEqual(len(result["route"]), 4)
        with self.assertRaises(DataError):
            add(items, "UNKNOWN_ID", by_id, {})
        conflicting = deepcopy(added)
        conflicting["name"] = "Другое определение того же ID"
        with self.assertRaises(DataError):
            merge_same_ids([added, conflicting])

    def test_normal_profiles_have_full_independently_validated_routes(self):
        slots = load_data("prime_slots.json")
        for age, sex in ((35, "F"), (42, "M"), (10, "M")):
            with self.subTest(age=age, sex=sex):
                result = build_plan(profile(age=age, sex=sex))
                self.assertEqual(result["schedule"]["status"], "feasible")
                fixture = make_schedule_fixture(result["items"], result["package"]["id"], slots, "normal")
                self.assertEqual(validate_schedule(fixture, result["schedule"]["route"]), [])
                route_ids = {row["procedure_id"] for row in result["schedule"]["route"]}
                after_ids = {row["procedure_id"] for row in result["schedule"]["after_results"]}
                self.assertFalse(route_ids & after_ids)
                # One catalog service can expand to two linked actions. Both
                # remain accounted for without doubling the service in items.
                action_ids = {item["procedure_id"] for item in expand_actions(result["items"])}
                self.assertEqual(route_ids | after_ids, action_ids)
                for deferred in result["schedule"]["after_results"]:
                    self.assertEqual(deferred["reason"], "после готовности результатов")
                    self.assertNotIn("due_date", deferred)

    def test_busy_preserves_mandatory_composition_and_hides_partial_route(self):
        normal = build_plan(profile())
        busy = build_plan(profile(availability="busy"))
        self.assertEqual(busy["status"], "ready")
        self.assertEqual(busy["package"], normal["package"])
        self.assertEqual(busy["items"], normal["items"])
        self.assertEqual(busy["schedule"]["status"], "infeasible")
        self.assertEqual(busy["schedule"]["route"], [])
        self.assertTrue(busy["schedule"]["reason"])

    def test_unknown_catalog_and_rule_references_are_data_errors(self):
        for location in ("package", "rule", "conflict"):
            with self.subTest(location=location):
                catalog = load_data("demo_catalog.json")
                rules = load_data("demo_rules.json")
                if location == "package":
                    catalog["packages"][1]["required_ids"].append("UNKNOWN_ID")
                elif location == "rule":
                    rules["rules"][0]["procedure_ids"].append("UNKNOWN_ID")
                else:
                    catalog["procedures"][0]["conflicts_with"] = ["UNKNOWN_ID"]
                self.assert_data_error(build_plan(profile(), catalog=catalog, rules=rules))

    def test_conflicting_mandatory_actions_are_never_silently_removed(self):
        # Corrupt active demo-2 IDs: old standalone vitamins are retired.
        catalog = load_data("demo_catalog.json")
        by_id = {procedure["id"]: procedure for procedure in catalog["procedures"]}
        by_id["prime_lipids_glucose_group"]["conflicts_with"] = ["prime_helicobacter_test"]
        result = build_plan(profile(), catalog=catalog)
        self.assert_data_error(result, "items.prime_lipids_glucose_group")
        self.assertTrue({"prime_lipids_glucose_group", "prime_helicobacter_test"}.issubset(ids(result)))

    def test_cycle_unknown_predecessor_and_bad_interval_are_not_infeasible(self):
        for defect in ("cycle", "unknown", "interval"):
            with self.subTest(defect=defect):
                slots = load_data("prime_slots.json")
                if defect == "cycle":
                    slots["procedures"]["prime_lipids_glucose_group"]["predecessors"] = ["prime_helicobacter_test"]
                    slots["procedures"]["prime_helicobacter_test"]["predecessors"] = ["prime_lipids_glucose_group"]
                elif defect == "unknown":
                    slots["procedures"]["prime_lipids_glucose_group"]["predecessors"] = ["UNKNOWN_ID"]
                else:
                    slots["slots"]["normal"]["prime_lipids_glucose_group"] = [[600, 590]]
                self.assert_data_error(build_plan(profile(), slots=slots))

    def test_missing_schedule_fields_do_not_invent_values(self):
        original = build_plan(profile())
        for field in ("duration_minutes", "resources", "predecessors", "category"):
            with self.subTest(field=field):
                slots = load_data("prime_slots.json")
                del slots["procedures"]["prime_lipids_glucose_group"][field]
                result = build_plan(profile(), slots=slots)
                self.assertEqual(result["status"], "ready")
                self.assertEqual(result["items"], original["items"])
                self.assertEqual(result["schedule"]["status"], "needs_data")
                self.assertEqual(result["schedule"]["route"], [])
                self.assertTrue(any(error["field"] == "procedures.prime_lipids_glucose_group." + field for error in result["schedule"]["errors"]))

    def test_missing_or_ambiguous_package_requires_review(self):
        for defect in ("missing", "overlap"):
            with self.subTest(defect=defect):
                catalog = load_data("demo_catalog.json")
                if defect == "missing":
                    catalog["packages"] = [package for package in catalog["packages"] if package["id"] != "prime_basic"]
                else:
                    alternative = deepcopy(catalog["packages"][1])
                    alternative["id"] = "other_basic"
                    catalog["packages"].append(alternative)
                result = build_plan(profile(), catalog=catalog)
                self.assert_unbuilt(result, "review")
                self.assertTrue(result["warnings"])

    def test_regression_malformed_metadata_and_rule_ids(self):
        slots = load_data("prime_slots.json")
        slots["procedures"]["prime_lipids_glucose_group"] = None
        self.assert_data_error(build_plan(profile(), slots=slots), "prime_lipids_glucose_group")

        slots = load_data("prime_slots.json")
        slots["procedures"]["prime_lipids_glucose_group"]["category"] = None
        result = build_plan(profile(), slots=slots)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["schedule"]["status"], "needs_data")
        self.assertEqual(result["schedule"]["route"], [])
        self.assertIn("procedures.prime_lipids_glucose_group.category", [error["field"] for error in result["schedule"]["errors"]])

        rules = load_data("demo_rules.json")
        rules["rules"][0]["id"] = []
        self.assert_data_error(build_plan(profile(), rules=rules), "rules")

    def test_regression_shared_base_and_supplement_id_keeps_both_reasons(self):
        catalog = load_data("demo_catalog.json")
        package = next(package for package in catalog["packages"] if package["id"] == "prime_basic")
        procedure_id = package["required_ids"][0]
        package["female_ids"].append(procedure_id)
        result = build_plan(profile(), catalog=catalog)
        self.assertEqual(result["status"], "ready")
        matches = [item for item in result["items"] if item["procedure_id"] == procedure_id]
        self.assertEqual(len(matches), 1)
        self.assertEqual(len(matches[0]["reasons"]), 2)
        explanations = {reason["explanation"] for reason in matches[0]["reasons"]}
        self.assertEqual(len(explanations), 2)
        self.assertTrue(any("основной состав" in explanation for explanation in explanations))
        self.assertTrue(any("дополнение для выбранного пола" in explanation for explanation in explanations))

    def test_repeated_and_new_inputs_are_calculated_without_mutation(self):
        inputs = profile(age=57, sex="F", family_crc="yes", complaints_state="list", complaints=["fatigue"], visit_date="2000-01-01")
        catalog = load_data("demo_catalog.json")
        rules = load_data("demo_rules.json")
        slots = load_data("prime_slots.json")
        before = deepcopy((inputs, catalog, rules, slots))
        first = build_plan(inputs, catalog=catalog, rules=rules, slots=slots)
        self.assertEqual(first, build_plan(inputs, catalog=catalog, rules=rules, slots=slots))
        self.assertEqual((inputs, catalog, rules, slots), before)
        self.assertEqual(first["package"]["id"], "prime_extended")
        self.assertIn("2000-01-01", first["package"]["reason"])
        changed = build_plan({**inputs, "age": 37})
        self.assertEqual(changed["package"]["id"], "prime_basic")
        self.assertNotEqual(ids(first), ids(changed))
        first["items"][0]["name"] = "Изменённая копия ответа"
        self.assertNotEqual(first, build_plan(inputs))

    def test_health_card_and_reminder_do_not_invent_results_or_due_date(self):
        result = build_plan(profile(age=10, sex="M"))
        self.assertIs(result["medical_validated"], False)
        self.assertIs(result["demo"], True)
        self.assertEqual({entry["procedure_id"] for entry in result["health_card"]}, ids(result))
        for entry in result["health_card"]:
            self.assertEqual(entry["status"], "не пройдено")
            self.assertEqual(entry["result"], "нет данных")
        self.assertEqual(result["reminder_draft"], {"status": "requires_clinician", "due_date": None, "basis": "требует назначения врача", "sent": False})
        completed = load_data("completed.json")["cases"]["reviewed"]
        self.assertIs(completed["demo"], True)
        self.assertIs(completed["medical_validated"], False)
        self.assertEqual(completed["item"]["procedure_id"], "DEMO_A")
        self.assertEqual(completed["item"]["performed_on"], "2026-10-01")
        self.assertEqual(completed["reminder_draft"]["due_date"], "2026-10-15")
        self.assertEqual(completed["reminder_draft"]["basis"], "Заранее заданное действие в вымышленном сценарии")
        self.assertIs(completed["reminder_draft"]["sent"], False)
        self.assertEqual(completed["item"]["result_text"], "Вымышленный результат получен; медицинской интерпретации нет")

    def test_trace_sources_and_collections_preserve_demo_contract(self):
        for inputs in (profile(), profile(family_crc="unknown"), profile(complaints_state="list", complaints=["chest_pain"]), profile(age=-1)):
            with self.subTest(inputs=inputs):
                result = build_plan(inputs)
                for key in ("items", "questions", "warnings", "trace", "health_card", "errors"):
                    self.assertIsInstance(result[key], list)
                self.assertIsInstance(result["schedule"]["route"], list)
                self.assertIsInstance(result["schedule"]["after_results"], list)
                self.assertIs(result["medical_validated"], False)
                for trace in result["trace"]:
                    self.assertIn(trace["outcome"], {"matched", "not_matched", "unknown", "skipped"})
                    self.assertEqual(trace["validation_status"], "demo_unvalidated")
                    self.assertTrue(trace["source"])
                    if trace["rule_id"].startswith("cmp_"):
                        self.assertEqual(trace["source_rule_id"], trace["rule_id"])
                        self.assertIs(trace["needs_doctor_validation"], True)
                        self.assertIs(trace["medical_validated"], False)


if __name__ == "__main__":
    unittest.main()
