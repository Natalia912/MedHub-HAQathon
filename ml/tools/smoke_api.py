"""Real local Uvicorn plus a separately mounted router; synthetic requests only."""
import argparse
from copy import deepcopy
import importlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return json.loads((ROOT / "docs" / name).read_text(encoding="utf-8"))


def mounted():
    """Executed from the parent of ml, using ml.prime_checkup exclusively."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ml.prime_checkup.router import router

    host = FastAPI()
    host.include_router(router, prefix="/prime")

    @host.get("/health")
    def host_health():
        return {"host": True}

    with TestClient(host) as client:
        responses = []
        for endpoint, filename in (("recommend", "recommend-request.json"), ("plan", "preset-request.json"),
                                   ("plan", "plan-request.json"), ("plan", "empty-request.json")):
            reply = client.post("/prime/" + endpoint, json=read(filename))
            responses.append({"file": filename, "http": reply.status_code, "body": reply.json()})
        malformed = client.post("/prime/plan", content="{", headers={"Content-Type": "application/json"})
        duplicate = len([(method, route.path) for route in host.routes for method in (route.methods or [])])
        unique = len({(method, route.path) for route in host.routes for method in (route.methods or [])})
        return {"responses": responses, "malformed": {"http": malformed.status_code, "body": malformed.json()},
                "host_health": client.get("/health").json(), "unique_routes": duplicate == unique,
                "standalone_main_imported": "ml.prime_checkup.main" in sys.modules,
                "modules": {name: module.__file__ for name, module in sys.modules.items()
                            if name.startswith("ml.prime_checkup") and getattr(module, "__file__", None)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="http_smoke.json")
    parser.add_argument("--mounted-child", action="store_true")
    args = parser.parse_args()
    if args.mounted_child:
        print(json.dumps(mounted(), ensure_ascii=False))
        return 0
    if Path(args.output).name != args.output or not args.output.endswith(".json"):
        parser.error("--output must be a JSON filename")
    report_dir = ROOT / "reports" / "packaging"
    report_dir.mkdir(parents=True, exist_ok=True)
    report = {"method": "real Uvicorn child process and separate mounted-router TestClient process",
              "python": sys.version, "executable": sys.executable, "root": str(ROOT), "requests": [], "checks": []}

    def check(name, actual, expected):
        report["checks"].append({"name": name, "actual": actual, "expected": expected,
                                 "verdict": "PASS" if actual == expected else "FAIL"})

    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    command = [sys.executable, "-s", "-m", "uvicorn", "prime_checkup.main:app", "--host", "127.0.0.1", "--port", str(port), "--no-access-log"]
    report.update(command=command, base_url=base, inherited_pythonpath=False)

    def request(path, payload=None, raw=None):
        data = raw if raw is not None else json.dumps(payload).encode() if payload is not None else None
        req = Request(base + path, data=data, headers={"Content-Type": "application/json"} if data else {})
        try:
            reply = urlopen(req, timeout=30)
        except HTTPError as exc:
            reply = exc
        with reply:
            record = {"path": path, "input": payload if raw is None else raw.decode(),
                      "http": reply.status, "body": json.loads(reply.read())}
        report["requests"].append(record)
        return record

    with (report_dir / (Path(args.output).stem + "_server.log")).open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=log,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            for _ in range(100):
                try:
                    health = request("/health")
                    break
                except (URLError, ConnectionError):
                    if process.poll() is not None:
                        raise RuntimeError("Uvicorn exited before /health; see server log")
                    time.sleep(.1)
            else:
                raise RuntimeError("Uvicorn did not become ready")
            check("health", health["body"], {"status": "ok", "demo": True, "medical_validated": False, "engine": "demo-3"})
            responses = []
            for endpoint, filename in (("recommend", "recommend-request.json"), ("plan", "preset-request.json"),
                                       ("plan", "plan-request.json"), ("plan", "empty-request.json")):
                reply = request("/" + endpoint, read(filename))
                responses.append({"file": filename, "http": reply["http"], "body": reply["body"]})
                check(filename + ": HTTP", reply["http"], 200)
                check(filename + ": recorded JSON example", reply["body"], read(filename.replace("request", "response")))
            check("recommend does not schedule", responses[0]["body"]["schedule"]["status"], "not_run")
            check("preset schedule", responses[1]["body"]["schedule"]["status"], "feasible")
            check("empty selection", responses[3]["body"]["status"], "needs_input")
            check("empty selection route", responses[3]["body"]["route"], [])
            normal = read("plan-request.json")
            for name, change, status, code in (
                ("stale", {"catalog_version": "stale"}, 409, "catalog_changed"),
                ("unknown_id", {"selected_procedure_ids": ["scr_breast"]}, 422, None),
                ("missing_selection", {}, 422, "missing"),
                ("preset_mismatch", {"mode": "preset", "selected_procedure_ids": []}, 422, "preset_mismatch"),
            ):
                payload = {**deepcopy(normal), **change}
                if name == "missing_selection":
                    payload.pop("selected_procedure_ids")
                reply = request("/plan", payload)
                check(name + ": HTTP", reply["http"], status)
                if code:
                    check(name + ": code", code in [row["code"] for row in reply["body"]["errors"]], True)
            urgent = deepcopy(normal)
            urgent["patient"]["urgent"] = "chest_pain"
            reply = request("/plan", urgent)
            check("urgent blocks direct plan", [reply["body"]["status"], reply["body"]["package"], reply["body"]["route"], reply["body"]["schedule"]["status"]], ["review", None, [], "not_run"])
            malformed = request("/plan", raw=b"{")
            check("malformed JSON", malformed["http"], 422)
            legacy = {"age": 35, "sex": "F", "complaints_state": "none", "complaints": [], "family_crc": "no", "visit_date": "2026-10-01", "availability": "normal"}
            check("legacy predict", request("/predict", legacy)["body"]["status"], "ready")
            check("GUI is absent", request("/")["http"], 404)
            child = subprocess.run([sys.executable, "-s", "-m", "ml.tools.smoke_api", "--mounted-child"], cwd=ROOT.parent,
                                   env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
            if child.returncode:
                raise RuntimeError(child.stderr)
            host = json.loads(child.stdout)
            report["mounted"] = host
            check("host and standalone complete responses", host["responses"], responses)
            check("host and standalone malformed JSON", host["malformed"], {"http": malformed["http"], "body": malformed["body"]})
            check("host health preserved", host["host_health"], {"host": True})
            check("no duplicate routes", host["unique_routes"], True)
            check("router does not import standalone main", host["standalone_main_imported"], False)
            check("mounted imports from package copy", all(Path(p).resolve().is_relative_to(ROOT) for p in host["modules"].values()), True)
        finally:
            process.terminate()
            process.wait(timeout=20)
    modules = {}
    for name in ("engine", "intake", "selection", "scheduler", "choice_route", "cards"):
        module = importlib.import_module("prime_checkup." + name)
        modules[module.__name__] = module.__file__
    report["modules"] = modules
    check("standalone imports from package copy", all(Path(p).resolve().is_relative_to(ROOT) for p in modules.values()), True)
    report["summary"] = {"http_requests": len(report["requests"]), "mounted_requests": 6,
                         "checks": len(report["checks"]), "failed": sum(row["verdict"] != "PASS" for row in report["checks"])}
    (report_dir / args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"]))
    return int(bool(report["summary"]["failed"]))


if __name__ == "__main__":
    raise SystemExit(main())
