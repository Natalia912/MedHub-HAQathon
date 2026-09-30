"""Standalone JSON transport and preserved legacy calculation invariants."""
import unittest
from copy import deepcopy
from unittest.mock import patch

from fastapi.testclient import TestClient

from prime_checkup.cards import get_completed_case
from prime_checkup.engine import build_plan, load_data
from prime_checkup.main import app
from prime_checkup.scheduler import load_fixture, schedule_visit


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.examples = load_data("examples.json")

    def test_normal_rejection_and_json_engine_parity(self):
        examples = [example["input"] for example in self.examples]
        examples += [dict(examples[0], age=39, complaints_state="list", complaints=["fatigue"], family_crc="yes")]
        for payload in examples:
            with self.subTest(payload=payload):
                original = deepcopy(payload)
                response = self.client.post("/predict", json=payload)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), build_plan(payload))
                self.assertEqual(payload, original)
        self.assertEqual(self.client.post("/predict", json=examples[0]).json()["status"], "ready")
        blocked = self.client.post("/predict", json=examples[4]).json()
        self.assertEqual(blocked["status"], "review")
        self.assertIsNone(blocked["package"])
        self.assertEqual(blocked["schedule"]["route"], [])
        self.assertEqual(self.client.post("/predict", json=examples[5]).json()["schedule"]["status"], "infeasible")

    def test_field_errors_match_engine_without_mutating_input(self):
        for field, value in (("age", "35.5"), ("sex", "other"), ("visit_date", "2026-02-30"), ("complaints", ["bad"])):
            with self.subTest(field=field):
                payload = dict(self.examples[0]["input"], **{field: value})
                original = deepcopy(payload)
                response = self.client.post("/predict", json=payload)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json(), build_plan(payload))
                self.assertTrue(any(error["field"].startswith(field) for error in response.json()["errors"]))
                self.assertEqual(payload, original)

    def test_malformed_json_and_non_object_share_error_contract(self):
        for body in ("{", "[]", "null", '"bad"'):
            response = self.client.post("/predict", content=body, headers={"Content-Type": "application/json"})
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()["status"], "invalid")
            self.assertEqual(response.json()["schedule"]["status"], "not_run")
            self.assertTrue(response.json()["errors"])
            self.assertIsInstance(response.json()["items"], list)

    def test_profiles_health_and_native_scheduler_whitelist(self):
        for example in self.examples:
            self.assertEqual(self.client.post("/predict", json=example["input"]).status_code, 200)
        self.assertEqual(self.client.get("/health").json()["status"], "ok")
        expected = {"feasible": "feasible", "backtracking": "feasible", "missing": "needs_data",
                    "no_slot": "infeasible", "conflict": "infeasible"}
        for case, status in expected.items():
            self.assertEqual(schedule_visit(load_fixture(case))["status"], status)
        with self.assertRaises(ValueError):
            load_fixture("../../secret")

    def test_fresh_calculation_even_in_old_offline_mode(self):
        payload = deepcopy(self.examples[0]["input"])
        with patch.dict("os.environ", {"DEMO_MODE": "offline"}):
            first = self.client.post("/predict", json=payload).json()
            payload["age"] = 40
            second = self.client.post("/predict", json=payload).json()
        self.assertEqual(first["package"]["id"], "prime_basic")
        self.assertEqual(second["package"]["id"], "prime_extended")
        self.assertNotEqual(first["items"], second["items"])

    def test_completed_provider_is_a_fixed_synthetic_fixture(self):
        before = get_completed_case()
        self.client.post("/predict", json=self.examples[4]["input"])
        after = get_completed_case()
        self.assertEqual(before, after)
        self.assertFalse(after["medical_validated"])
        self.assertTrue(after["demo"])
        self.assertIsNone(after["reminder_draft"]["due_date"])
        self.assertFalse(after["reminder_draft"]["sent"])


if __name__ == "__main__":
    unittest.main()
