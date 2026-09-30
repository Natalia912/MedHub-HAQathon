import unittest

from prime_checkup.scheduler import load_fixture, schedule_visit, validate_schedule


class SchedulerTests(unittest.TestCase):
    def test_five_fixture_outcomes_and_complete_routes(self):
        expected = {
            "feasible": "feasible",
            "backtracking": "feasible",
            "no_slot": "infeasible",
            "missing": "needs_data",
            "conflict": "infeasible",
        }
        for case, status in expected.items():
            with self.subTest(case=case):
                fixture = load_fixture(case)
                result = schedule_visit(fixture)
                self.assertEqual(result["status"], status)
                if status == "feasible":
                    self.assertEqual(validate_schedule(fixture, result["route"]), [])
                    self.assertEqual(
                        [(row["procedure_id"], row["start"], row["end"]) for row in result["route"]],
                        [("DEMO_B", 540, 560), ("DEMO_A", 600, 620), ("DEMO_C", 620, 640), ("DEMO_D", 640, 660)],
                    )
                else:
                    self.assertEqual(result["route"], [])
                if case == "no_slot":
                    self.assertIn("NO_AVAILABLE_SLOT: DEMO_B", result["reason"])
                if case == "missing":
                    self.assertEqual(result["errors"][0]["field"], "procedures.DEMO_C.duration_minutes")

    def test_fixtures_are_independent_and_whitelisted(self):
        load_fixture("missing")["procedures"].clear()
        self.assertEqual(len(load_fixture("backtracking")["procedures"]), 4)
        self.assertEqual(load_fixture("backtracking")["procedures"][2]["duration_minutes"], 20)
        with self.assertRaises(ValueError):
            load_fixture("../scheduler_demo")

    def test_bad_data_is_detected_before_search(self):
        mutations = {
            "DEPENDENCY_CYCLE": lambda fixture: fixture["procedures"][0].update(predecessors=["DEMO_D"]),
            "UNKNOWN_ID": lambda fixture: fixture["procedures"][0].update(predecessors=["NOT_IN_CATALOG"]),
            "INVALID_INTERVAL": lambda fixture: fixture["procedures"][0].update(slots=[[600, 590]]),
            "UNKNOWN_RESOURCE": lambda fixture: fixture["procedures"][0].update(resources=["UNKNOWN"]),
        }
        for code, mutate in mutations.items():
            with self.subTest(code=code):
                fixture = load_fixture("backtracking")
                mutate(fixture)
                result = schedule_visit(fixture)
                self.assertEqual(result["status"], "not_run")
                self.assertIn(code, {error["code"] for error in result["errors"]})
                self.assertEqual(result["route"], [])

    def test_limited_search_does_not_claim_impossibility(self):
        self.assertEqual(schedule_visit(load_fixture("feasible"), max_nodes=0)["status"], "unknown")
        self.assertEqual(schedule_visit(load_fixture("feasible"), max_nodes=None)["status"], "feasible")

    def test_actual_backtracking_recovers_after_first_choice_fails(self):
        fixture = load_fixture("backtracking")
        fixture["procedures"][1]["slots"] = [[540, 560], [640, 660]]
        # A sorts before equally constrained B. A at 540 forces B to conflict
        # with D; the search must return to A and place it at 600.
        result = schedule_visit(fixture)
        self.assertEqual(result["status"], "feasible")
        self.assertEqual(result["route"][0]["procedure_id"], "DEMO_B")
        self.assertEqual(validate_schedule(fixture, result["route"]), [])

    def test_resource_busy_is_checked_without_other_patient_procedures(self):
        fixture = load_fixture("feasible")
        fixture["resource_busy"] = {"DEMO_R1": [[540, 560]]}
        self.assertEqual(schedule_visit(fixture)["status"], "infeasible")

    def test_validator_detects_tampered_routes(self):
        fixture = load_fixture("feasible")
        route = schedule_visit(fixture)["route"]
        checks = [
            ("INCOMPLETE", lambda rows: rows.pop()),
            ("DUPLICATE_ID", lambda rows: rows.append(dict(rows[0]))),
            ("DURATION_MISMATCH", lambda rows: rows[0].update(end=550)),
            ("SLOT_MISMATCH", lambda rows: rows[1].update(start=601, end=621)),
            ("RESOURCE_MISMATCH", lambda rows: rows[0].update(resources=["DEMO_R2"])),
            ("DEPENDENCY_VIOLATION", lambda rows: rows[2].update(start=560, end=580)),
            ("PATIENT_OVERLAP", lambda rows: rows[1].update(start=540, end=560)),
            ("RESOURCE_OVERLAP", lambda rows: rows[1].update(start=540, end=560)),
        ]
        from copy import deepcopy
        for code, mutate in checks:
            with self.subTest(code=code):
                changed = deepcopy(route)
                mutate(changed)
                self.assertIn(code, {error["code"] for error in validate_schedule(fixture, changed)})
        busy = load_fixture("feasible")
        busy["resource_busy"] = {"DEMO_R1": [[540, 560]]}
        self.assertIn("RESOURCE_BUSY", {error["code"] for error in validate_schedule(busy, route)})

    def test_touching_intervals_allowed_and_slot_cannot_slide(self):
        fixture = load_fixture("feasible")
        self.assertEqual(schedule_visit(fixture)["status"], "feasible")
        fixture["procedures"][0]["slots"] = [[540, 620]]
        self.assertEqual(schedule_visit(fixture)["status"], "infeasible")

    def test_short_slot_and_patient_window_do_not_change_duration(self):
        for mutation in ("slot", "window"):
            with self.subTest(mutation=mutation):
                fixture = load_fixture("feasible")
                if mutation == "slot":
                    fixture["procedures"][0]["slots"] = [[600, 610]]
                else:
                    fixture["patient_window"] = [540, 650]
                result = schedule_visit(fixture)
                self.assertEqual(result["status"], "infeasible")
                self.assertEqual(result["route"], [])
                self.assertEqual(fixture["procedures"][0]["duration_minutes"], 20)


if __name__ == "__main__":
    unittest.main()
