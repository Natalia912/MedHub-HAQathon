"""S19: review concerns stay on the selected service, without drug instructions."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from fastapi.testclient import TestClient
from prime_checkup.main import app


class PreparationReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        fixture = json.loads((Path(__file__).parent / "fixtures/prime_scenarios.json").read_text(encoding="utf-8"))
        cls.scenario = next(s for s in fixture["states"] if s["id"] == "S19-A")

    def plan(self, patient=None, remove_endoscopy=False):
        request = deepcopy(self.scenario["request"])
        if patient is not None:
            request["patient"].update(patient)
        recommendation = self.client.post("/recommend", json=request)
        self.assertEqual(200, recommendation.status_code)
        selection = deepcopy(self.scenario["selection"])
        selection["catalog_version"] = recommendation.json()["versions"]["catalog"]
        if remove_endoscopy:
            selection["mode"] = "custom"
            selection["selected_procedure_ids"].remove("prime_endoscopy_group")
        response = self.client.post("/plan", json={**request, **selection})
        self.assertEqual(200, response.status_code)
        return recommendation.json(), response.json()

    def test_reported_preparation_issues_stop_slots_and_preserve_group(self):
        recommendation, result = self.plan()
        for data in (recommendation, result):
            self.assertEqual("review", data["status"])
            self.assertEqual("not_run", data["schedule"]["status"])
            group = next(i for i in data["items"] if i["procedure_id"] == "prime_endoscopy_group")
            codes = {flag["code"] for flag in group["clinical_flags"]}
            self.assertTrue({"PREPARATION_MEDICATION_REVIEW", "PREPARATION_RETURN_REVIEW"} <= codes)
            self.assertTrue(group["is_group"])
            self.assertTrue({"medications", "companion"} <= {q["field"] for q in data["questions"]})
            original_drug = self.scenario["request"]["patient"]["medications"]
            self.assertTrue(any(row.get("field") == "medications" and row.get("value") == original_drug for row in data["doctor_summary"]))
        self.assertEqual("draft", result["route_status"])
        self.assertFalse(result["reminder_draft"]["sent"])
        self.assertIsNone(result["next_visit"][0]["date"])

    def test_removal_clears_only_selected_service_preparation_review(self):
        _, result = self.plan(remove_endoscopy=True)
        self.assertEqual("ready", result["status"])
        self.assertNotIn("prime_endoscopy_group", [i["procedure_id"] for i in result["selected_items"]])
        self.assertEqual(["prime_endoscopy_group"], [i["procedure_id"] for i in result["removed_recommended_items"]])
        self.assertFalse(any(t["rule_id"] == "clinic_preparation" and t["outcome"] == "matched" for t in result["trace"]))
        self.assertEqual([], result["questions"])

    def test_each_known_preparation_fact_is_separate(self):
        for answers, code in (({"companion": "yes"}, "PREPARATION_MEDICATION_REVIEW"),
                              ({"blood_thinners": "no"}, "PREPARATION_RETURN_REVIEW")):
            with self.subTest(answers=answers):
                _, result = self.plan(answers)
                group = next(i for i in result["items"] if i["procedure_id"] == "prime_endoscopy_group")
                self.assertEqual({code}, {f["code"] for f in group["clinical_flags"]})
                self.assertEqual("not_run", result["schedule"]["status"])


if __name__ == "__main__":
    unittest.main()
