"""Two public JSON operations preserve the tester's selection invariants."""
import unittest
from copy import deepcopy
from unittest.mock import patch

from fastapi.testclient import TestClient

from prime_checkup.engine import load_data
from prime_checkup.main import app
from prime_checkup.selection import plan_request, recommend_request
from tests.helpers import clinic


class TwoStepHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def recommend(self, patient):
        response = self.client.post("/recommend", json=patient)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def selection(self, patient, **changes):
        recommendation = self.recommend(patient)
        value = {
            "patient": patient, "context": {}, "mode": "custom",
            "base_package_id": recommendation["package"]["id"],
            "variant_id": recommendation["package"]["variant_id"],
            "catalog_version": recommendation["versions"]["catalog"],
            "selected_procedure_ids": [item["procedure_id"] for item in recommendation["items"]],
        }
        value.update(changes)
        return value

    def test_recommendation_does_not_search_and_preserves_json_engine_parity(self):
        for patient in (clinic(), load_data("examples.json")[0]["input"]):
            with self.subTest(format=patient.get("input_version", "legacy")):
                with patch("prime_checkup.engine.schedule_visit", side_effect=AssertionError("recommend must not search")), \
                     patch("prime_checkup.choice_route.schedule_visit", side_effect=AssertionError("recommend must not search")):
                    response = self.client.post("/recommend", json=patient)
                    expected = recommend_request(patient)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), expected)
                self.assertEqual(response.json()["schedule"]["status"], "not_run")
                self.assertTrue(response.json()["catalog"])
                self.assertTrue(response.json()["package_options"])

    def test_preset_and_custom_json_revalidate_patient_and_reconstruct_composition(self):
        patient = clinic()
        recommended = self.recommend(patient)
        for mode in ("preset", "custom"):
            with self.subTest(mode=mode):
                payload = self.selection(patient, mode=mode)
                if mode == "preset":
                    payload.pop("selected_procedure_ids")
                response = self.client.post("/plan", json=payload)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json(), plan_request(payload))
                self.assertEqual(response.json()["mode"], mode)
                self.assertEqual({item["procedure_id"] for item in response.json()["selected_items"]},
                                 {item["procedure_id"] for item in recommended["items"]})
                payload["patient"] = dict(patient, sex="forged")
                self.assertEqual(self.client.post("/plan", json=payload).status_code, 422)

    def test_custom_removal_and_addition_have_json_engine_parity(self):
        payload = self.selection(clinic())
        payload["selected_procedure_ids"] = ["prime_helicobacter_test", "prime_urology_consult", "prime_urology_consult"]
        response = self.client.post("/plan", json=payload)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, plan_request(payload))
        self.assertEqual(len(result["selected_items"]), 2)
        self.assertTrue(result["removed_recommended_items"])
        self.assertTrue(result["added_items"])
        self.assertEqual(result["package"]["name"], "Индивидуальный набор")
        self.assertEqual(result["price_text"], "Стоимость — у администратора")
        self.assertIsNone(result["total_price"])

    def test_empty_unknown_and_stale_selection_preserve_input_and_errors(self):
        for ids, version, code in (([], None, 200), (["<unknown-service>"], None, 422), (["prime_helicobacter_test"], "outdated-demo", 409)):
            with self.subTest(ids=ids, version=version):
                payload = self.selection(clinic(), selected_procedure_ids=ids)
                if version:
                    payload["catalog_version"] = version
                original = deepcopy(payload)
                response = self.client.post("/plan", json=payload)
                self.assertEqual(response.status_code, code)
                self.assertEqual(response.json(), plan_request(payload))
                self.assertEqual(payload, original)
                if not ids:
                    self.assertEqual(response.json()["status"], "needs_input")
                    self.assertEqual(response.json()["selected_items"], [])
                    self.assertEqual(response.json()["route"], [])
                else:
                    self.assertTrue(response.json()["errors"])

    def test_service_review_can_be_removed_but_global_urgent_still_stops(self):
        patient = clinic(sex="F", birth_date="1982-01-10", pregnant="yes")
        self.assertEqual(self.recommend(patient)["status"], "review")
        payload = self.selection(patient, selected_procedure_ids=["prime_helicobacter_test"])
        self.assertEqual(self.client.post("/plan", json=payload).json()["status"], "ready")
        payload["patient"]["urgent"] = "other_now"
        stopped = self.client.post("/plan", json=payload)
        self.assertEqual(stopped.status_code, 200)
        data = stopped.json()
        self.assertEqual(data["status"], "review")
        self.assertIsNone(data["package"])
        self.assertEqual(data["route"], [])

    def test_json_paths_are_unique_and_do_not_accept_old_html_payload(self):
        for path in ("/recommend", "/plan"):
            routes = [route for route in app.routes if getattr(route, "path", None) == path and "POST" in getattr(route, "methods", [])]
            self.assertEqual(len(routes), 1)
            for body in ("{", "[]", "null"):
                with self.subTest(path=path, body=body):
                    response = self.client.post(path, content=body, headers={"Content-Type": "application/json"})
                    self.assertEqual(response.status_code, 422)
                    result = response.json()
                    self.assertEqual(result["status"], "invalid")
                    self.assertEqual(result["error"], result["errors"][0])
                    self.assertEqual(result["stage"], "recommendation" if path == "/recommend" else "plan")
                    self.assertIsInstance(result["context"], dict)
        response = self.client.post("/plan", data=clinic())
        self.assertEqual(response.status_code, 422)
        self.assertIn("application/json", response.headers["content-type"])

    def test_client_metadata_is_not_trusted_and_free_text_stays_data(self):
        attack = '<script>alert("demo")</script>'
        payload = self.selection(clinic(medications=attack))
        original = deepcopy(payload)
        payload["status"] = "ready"
        self.assertEqual(self.client.post("/plan", json=payload).status_code, 422)
        original["selected_procedure_ids"] = ["prime_helicobacter_test"]
        response = self.client.post("/plan", json=original)
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/json", response.headers["content-type"])
        self.assertEqual(response.json(), plan_request(original))
        medication = next(row for row in response.json()["doctor_summary"] if row["field"] == "medications")
        self.assertEqual(medication["value"], attack)

    def test_wrong_context_and_patient_types_are_structured_errors(self):
        payload = self.selection(clinic(), selected_procedure_ids=["prime_helicobacter_test"])
        for field in ("patient", "context"):
            for value in ([], "unexpected", 5):
                with self.subTest(field=field, value=value):
                    wrong = deepcopy(payload)
                    wrong[field] = value
                    response = self.client.post("/plan", json=wrong)
                    self.assertEqual(response.status_code, 422)
                    result = response.json()
                    self.assertEqual(result["status"], "invalid")
                    self.assertEqual(result["error"], result["errors"][0])


if __name__ == "__main__":
    unittest.main()
