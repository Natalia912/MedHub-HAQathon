"""Synthetic result states stay separate from medical validation and planning."""
import unittest
from copy import deepcopy
from unittest.mock import patch

from fastapi.testclient import TestClient

from prime_checkup.engine import load_data
from prime_checkup.main import app
from prime_checkup.cards import get_completed_case


class CompletedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_three_states_have_only_their_fixed_events_and_reminders(self):
        expectations = [
            ("waiting", "pending", "not_ready", None, None, None),
            ("received", "available", "pending", "2026-10-02", None, None),
            ("reviewed", "available", "reviewed", "2026-10-02", "2026-10-03", "2026-10-15"),
        ]
        for case, result_status, review_status, received_on, reviewed_on, due_date in expectations:
            with self.subTest(case=case):
                fixture = get_completed_case(case)
                self.assertEqual(fixture["case_id"], case)
                self.assertIs(fixture["demo"], True)
                self.assertIs(fixture["medical_validated"], False)
                item = fixture["item"]
                self.assertEqual(item["record_id"], "result-demo-1")
                self.assertEqual(item["procedure_id"], "DEMO_A")
                self.assertEqual(item["label"], "Тестовое обследование A")
                self.assertEqual(item["performed_on"], "2026-10-01")
                self.assertEqual(item["source"], "synthetic_fixture")
                self.assertEqual(item["result_status"], result_status)
                self.assertEqual(item["review_status"], review_status)
                self.assertEqual(item["result_received_on"], received_on)
                self.assertEqual(item["reviewed_on"], reviewed_on)
                expected_text = None if case == "waiting" else "Вымышленный результат получен; медицинской интерпретации нет"
                self.assertEqual(item["result_text"], expected_text)
                expected_action = "Обсудить результаты на демонстрационном приёме" if case == "reviewed" else None
                self.assertEqual(item["next_action"], expected_action)
                self.assertEqual(fixture["reminder_draft"], {
                    "status": "draft" if case == "reviewed" else "requires_clinician",
                    "due_date": due_date,
                    "basis": "Заранее заданное действие в вымышленном сценарии" if case == "reviewed" else None,
                    "sent": False,
                })

    def test_history_preserves_only_known_year_and_unknown_outcomes(self):
        history = get_completed_case()["history"]
        self.assertEqual(history, [{
            "record_id": "history-demo-1",
            "screening_id": "scr_breast",
            "procedure_id": None,
            "label": "Маммография",
            "performed_on": None,
            "performed_year": 2025,
            "date_precision": "year",
            "result_status": "unknown",
            "review_status": "unknown",
            "source": "synthetic_spec_example",
            "medical_validated": False,
        }])

    def test_default_and_switching_do_not_mutate_shared_fixture(self):
        fixture = load_data("completed.json")
        snapshot = deepcopy(fixture)
        with patch("prime_checkup.cards.load_data", return_value=fixture):
            first = get_completed_case()
            for case in ("received", "reviewed", "waiting"):
                response = get_completed_case(case)
                self.assertEqual(response["case_id"], case)
                response["item"]["result_text"] = "changed returned copy"
                response["history"][0]["performed_year"] = 2000
                self.assertEqual(fixture, snapshot)
            again = get_completed_case("waiting")
        self.assertEqual(first["case_id"], "waiting")
        self.assertEqual(first, again)
        self.assertEqual(load_data("completed.json"), snapshot)

    def test_unknown_case_is_rejected_before_loading_a_file(self):
        for case in ("unknown", "../../README.md", "", "received.json"):
            with self.subTest(case=case), patch("prime_checkup.cards.load_data") as loader:
                with self.assertRaisesRegex(ValueError, "Неизвестный"):
                    get_completed_case(case)
                loader.assert_not_called()

    def test_history_and_result_states_never_change_the_new_plan(self):
        payload = {
            "age": 42, "sex": "F", "complaints_state": "none", "complaints": [],
            "family_crc": "no", "visit_date": "2026-10-01", "availability": "normal",
        }
        before = self.client.post("/predict", json=payload)
        self.assertEqual(before.status_code, 200)
        plan = before.json()
        # New explicit 2D/3D source variant; history does not remove this item.
        self.assertIn("prime_mammography_2d3d", {item["procedure_id"] for item in plan["items"]})
        for case in ("waiting", "received", "reviewed"):
            with self.subTest(case=case):
                self.assertEqual(get_completed_case(case)["case_id"], case)
                after = self.client.post("/predict", json=payload)
                self.assertEqual(after.status_code, 200)
                self.assertEqual(after.json(), plan)
                self.assertIsNone(after.json()["reminder_draft"]["due_date"])

if __name__ == "__main__":
    unittest.main()
