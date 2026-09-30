"""The packaged APIRouter coexists with a host app and preserves JSON errors."""
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from prime_checkup.main import app as standalone
from prime_checkup.router import router
from tests.helpers import clinic


class RouterMountTests(unittest.TestCase):
    def test_prefixed_mount_matches_standalone_without_changing_host_routes(self):
        host = FastAPI()

        @host.get("/host-only")
        def host_only():
            return {"preserved": True}

        host.include_router(router, prefix="/prime")
        client, direct = TestClient(host), TestClient(standalone)
        self.assertEqual(client.get("/host-only").json(), {"preserved": True})
        patient = clinic()
        recommendation = client.post("/prime/recommend", json={"patient": patient, "context": {}})
        self.assertEqual(recommendation.status_code, 200)
        self.assertEqual(recommendation.json(), direct.post("/recommend", json={"patient": patient, "context": {}}).json())
        result = recommendation.json()
        selected = {"patient": patient, "mode": "preset", "base_package_id": result["package"]["id"],
                    "variant_id": result["package"]["variant_id"], "catalog_version": result["versions"]["catalog"]}
        self.assertEqual(client.post("/prime/plan", json=selected).json(), direct.post("/plan", json=selected).json())
        for path in ("recommend", "plan", "predict"):
            malformed = client.post("/prime/" + path, content="{", headers={"Content-Type": "application/json"})
            self.assertEqual(malformed.status_code, 422)
            self.assertEqual(malformed.json()["status"], "invalid")
            self.assertEqual(malformed.json()["schedule"]["status"], "not_run")
            self.assertTrue(malformed.json()["errors"])


if __name__ == "__main__":
    unittest.main()
