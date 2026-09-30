"""Execute the frozen Scenarios.docx expectations through the public API.

Run from this ml folder: python -m tools.run_scenarios
No medical decisions or second scheduling implementation live in this runner.
"""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import traceback
from unittest.mock import patch

from fastapi.testclient import TestClient

from prime_checkup.main import app
from prime_checkup.intake import normalize_input
from prime_checkup.scheduler import schedule_visit, validate_schedule


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/prime_scenarios.json"
HISTORY = ROOT / "reports/scenarios"
OUTPUT = ROOT / "reports/packaging"
VERDICTS = ("PASS", "FAIL", "BLOCKED", "OUT_OF_SCOPE", "NOT_RUN")

# Names in the frozen document coverage index refer to groups of checks.
# These aliases only locate evidence; they never decide the expected outcome.
COVERAGE_ALIASES = {
    "recommend.package": ["recommend.package_id", "recommend.variant_id"],
    "recommend.screening": ["recommend.scr_"],
    "demo_flags": ["recommend.demo_boundary", "plan.demo_boundary"],
    "context_dates": ["context_dates"],
    "selection_exact": ["plan.selected_ids"],
    "diff_exact": ["plan.removed_ids", "plan.added_ids", "diff_from_original"],
    "health_card_unperformed": ["card_selected_only_unperformed", "empty_card_unperformed"],
    "screening_not_prime": ["screening_separate", "screening_not_prime"],
    "stop_has_no_route_or_card": ["stop_no_route_or_card", "urgent_stops_both", "urgent_question_both"],
    "next_visit_without_date": ["plan.next_visit_array", "plan.no_invented_dates"],
    "no_price_calculation": ["unknown_price", "custom_price_text", "no_price_calculation"],
    "schedule_invariants": ["schedule_invariants", "complete_action_disposition", "independent_schedule_validator", "route_matches_chronology", "review_no_search", "after_results_no_time", "stop_no_route_or_card"],
    "review_not_run": ["review_no_search", "plan.schedule_status"],
    "removed_warning_original_reason": ["removal_warning_why", "removed_warning_original_reason"],
    "normalized": ["normalized."], "history": ["history."],
}


def verdict_for(values):
    return next((key for key in ("FAIL", "BLOCKED", "NOT_RUN", "OUT_OF_SCOPE") if key in values), "PASS")


def document_coverage(fixture, run):
    """Aggregate 124 original statements, preserving partial/out-of-scope cards."""
    result = []
    for card in fixture["cards"]:
        states = [state for state in run["states"] if state["card_id"] == card["id"]]
        checks = [check for state in states for check in state["assertions"]]
        bindings = states[0]["specification"]["assertion_checks"]
        rows = []
        for assertion in card["assertions"]:
            evidence, missing = [], []
            for name in bindings[assertion["id"]]:
                aliases = COVERAGE_ALIASES.get(name, [name])
                matches = [check for check in checks if any(check["name"] == alias or
                            (alias.endswith((".", "_")) and check["name"].startswith(alias)) for alias in aliases)]
                evidence.extend(matches)
                if not matches:
                    missing.append(name)
            evidence = {check["id"]: check for check in evidence}
            verdicts = [check["verdict"] for check in evidence.values()] + (["NOT_RUN"] if missing else [])
            rows.append({**assertion, "verdict": verdict_for(verdicts), "evidence_ids": list(evidence),
                         "unverified_check_names": missing,
                         "clinical_question_remains_open": assertion["basis"] == "CLINICIAN_REVIEW",
                         "reason": "Вердикт проверяет поведение программы; врачебное решение не подменяется тестом."})
        result.append({"id": card["id"], "title": card["title"], "states": [s["id"] for s in states],
                       "assertions": rows, "verdict": verdict_for([r["verdict"] for r in rows])})
    return result


def cross_state_checks(fixture, run):
    """Compare already captured public responses; no extra HTTP or clinical oracle."""
    states = {s["id"]: s for s in run["states"]}
    results = []

    def check(name, expected, actual):
        results.append({"id": name, "expected": expected, "actual": actual,
                        "verdict": "PASS" if actual == expected else "FAIL", "basis": "PROJECT"})

    def response(sid, endpoint):
        return next((r["response"] for r in states[sid]["requests"] if r["endpoint"] == endpoint), {}) or {}

    check("S23.preset_repeat_after_custom", response("S23-A", "/plan"), response("S23-C", "/plan"))
    for sid in ("S16-B", "S16-C"):
        result = response(sid, "/plan")
        states[sid]["comparison_facts"] = {
            "selected": sorted(i["procedure_id"] for i in result.get("selected_items", [])),
            "screening": {r["rule_id"]: r["outcome"] for r in result.get("screening", [])},
            "history": result.get("input_context", {}).get("history"),
        }
    check("S16.attachment_preserves_composition_outcomes_history", states["S16-B"]["comparison_facts"], states["S16-C"]["comparison_facts"])
    rec = response("S01-A", "/recommend")
    check("catalog.all_43_exact_ids", sorted({m["procedure_id"] for m in fixture["catalog_mapping"]}),
          sorted(i["procedure_id"] for i in rec.get("catalog", [])))
    check("catalog.six_exact_presets", {key: sorted(value["procedure_ids"]) for key, value in fixture["presets"].items()},
          {p["package_id"] + ":" + p["variant_id"]: sorted(p["selected_procedure_ids"]) for p in rec.get("package_options", [])})
    check("versions.confirmed_public", fixture["expected_versions"],
          {key: rec.get("versions", {}).get(key) for key in fixture["expected_versions"]})
    check("health.confirmed_engine", fixture["expected_versions"]["engine"], run["health"].get("engine"))
    return results


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dotted(value, path):
    for key in path.split("."):
        if isinstance(value, dict):
            value = value.get(key)
        elif isinstance(value, list) and key.isdigit() and int(key) < len(value):
            value = value[int(key)]
        else:
            return None
    return value


def verify_expectations(frozen, fixture):
    """Permit only documented transcription corrections; retain original oracle."""
    original = read_json(frozen)
    if original["fixture_sha256"] == sha256(FIXTURE):
        return
    path = HISTORY / "mapping_amendments.json"
    if not path.exists():
        raise SystemExit("Expected fixture changed without a documented mapping amendment.")
    change = read_json(path)
    assert change["original_sha256"] == original["fixture_sha256"]
    assert change["amended_sha256"] == sha256(FIXTURE)
    expected = deepcopy(original["fixture"])
    for amendment in change["amendments"]:
        assert amendment["classification"] == "MAPPING/CONTRACT" and amendment["source_doc_ref"] and amendment["reason"]
        keys = amendment["path"].split(".")
        parent = expected
        for key in keys[:-1]:
            parent = parent[int(key)] if isinstance(parent, list) else parent[key]
        assert parent[keys[-1]] == amendment["before"]
        parent[keys[-1]] = amendment["after"]
    assert expected == fixture, "Unlisted expected-property changes are not permitted"


def manifest():
    """Only package-local files; copied folders need no git checkout or old app."""
    paths = [FIXTURE, ROOT / "tests/fixtures/Scenarios.docx"]
    for directory in ("prime_checkup", "tests", "tools", "docs", "reference"):
        paths.extend(path for path in (ROOT / directory).rglob("*")
                     if path.is_file() and "__pycache__" not in path.parts)
    for filename in ("pyproject.toml", "requirements.txt", "README.md"):
        if (ROOT / filename).is_file():
            paths.append(ROOT / filename)
    return {"scope": "standalone ml package", "sha256": {
        path.relative_to(ROOT).as_posix(): sha256(path) for path in sorted(set(paths))}}


class StateRun:
    def __init__(self, state, client):
        self.state, self.client = state, client
        self.result = {"id": state["id"], "card_id": state["card_id"],
                       "specification": deepcopy(state), "requests": [], "assertions": [],
                       "normalized": None, "normalization_errors": [], "scheduler_fixtures": []}

    def check(self, name, expected, actual, ok=None, *, basis="PROJECT", refs=None,
              blocked=None, classification="CODE", verdict=None, reason=None):
        if verdict is None:
            verdict = "BLOCKED" if blocked else "PASS" if (actual == expected if ok is None else ok) else "FAIL"
        self.result["assertions"].append({
            "id": self.state["id"] + ":" + name, "name": name,
            "basis": basis, "doc_refs": refs or self.state.get("doc_refs", []),
            "expected": deepcopy(expected), "actual": deepcopy(actual), "verdict": verdict,
            "classification": classification if verdict in ("FAIL", "BLOCKED") else None,
            "reason": blocked or reason or ("Независимое ожидаемое свойство подтверждено." if verdict == "PASS"
                                          else "Фактическое значение отличается от закреплённого ожидания."),
        })

    def post(self, endpoint, payload):
        calls = []

        def capture(fixture, *args, **kwargs):
            calls.append(deepcopy(fixture))
            return schedule_visit(fixture, *args, **kwargs)

        request = {"method": "POST", "endpoint": endpoint, "payload": deepcopy(payload)}
        with patch("prime_checkup.choice_route.schedule_visit", side_effect=capture), \
             patch("prime_checkup.engine.schedule_visit", side_effect=capture):
            try:
                response = self.client.post(endpoint, json=payload)
                request.update(http=response.status_code, response=response.json())
            except Exception:
                request.update(http=500, response=None, traceback=traceback.format_exc())
        request["scheduler_calls"] = len(calls)
        request["scheduler_fixtures"] = calls
        self.result["requests"].append(request)
        self.result["scheduler_fixtures"].extend(calls)
        return request

    def run(self, catalog_version):
        state = self.state
        if state.get("standalone_fixture") is not None:
            return self.run_scheduler()
        request = state["request"]
        raw = {**request["patient"], **request["context"]}
        normalized, errors = normalize_input(raw)
        self.result.update(normalized=normalized, normalization_errors=errors)
        rec = self.post("/recommend", request)
        actual_version = (rec["response"] or {}).get("versions", {}).get("catalog", catalog_version)
        selection = deepcopy(state["selection"])
        selection["catalog_version"] = actual_version
        plan_payload = {**request, **selection}
        plan = self.post("/plan", plan_payload)
        self.check("recommend_no_search", 0, rec["scheduler_calls"])
        self.evaluate_endpoint("recommend", rec)
        self.evaluate_endpoint("plan", plan)
        self.evaluate_normalized()
        self.evaluate_common(rec, plan)
        self.evaluate_special(rec, plan)
        return self.finish()

    def evaluate_endpoint(self, endpoint, request):
        expected = self.state["expected"].get(endpoint, {})
        data = request["response"] or {}
        target_http = expected.get("http", 200)
        self.check(endpoint + ".http", target_http, request["http"],
                   classification="MAPPING/CONTRACT" if request["http"] == 422 else "CODE")
        blocked = None if request["http"] == target_http else "Зависит от принятия публичного запроса; фактический HTTP " + str(request["http"])
        fields = {"package_id": "package.id", "variant_id": "package.variant_id",
                  "age_full": "age_full", "age_year": "age_year", "status": "status",
                  "schedule_status": "schedule.status", "error_code": "error.code"}
        for key, path in fields.items():
            if key not in expected:
                continue
            value, actual = expected[key], dotted(data, path)
            self.check(endpoint + "." + key, value, actual,
                       ok=actual in value if isinstance(value, list) else actual == value, blocked=blocked,
                       basis="RULE_SNAPSHOT" if key in ("package_id", "variant_id") else "PROJECT")
        for field in ("route", "after_results", "health_card"):
            if field in expected:
                self.check(endpoint + "." + field, expected[field], data.get(field), blocked=blocked)
        for key, field in (("item_ids", "items"), ("selected_ids", "selected_items"),
                           ("removed_ids", "removed_recommended_items"), ("added_ids", "added_items")):
            if key in expected:
                actual = [row["procedure_id"] for row in data.get(field, [])]
                self.check(endpoint + "." + key, sorted(expected[key]), sorted(actual), blocked=blocked,
                           basis="RULE_SNAPSHOT" if endpoint == "recommend" else "PROJECT")
        screening = {row["rule_id"]: row for row in data.get("screening", [])}
        for rule, outcome in expected.get("screening", {}).items():
            actual = screening.get(rule, {}).get("outcome")
            self.check(endpoint + "." + rule, outcome, actual,
                       ok=actual in outcome if isinstance(outcome, list) else actual == outcome,
                       blocked=blocked, basis="CLINICIAN_REVIEW" if outcome == "review" else "RULE_SNAPSHOT")

    def evaluate_normalized(self):
        patient = self.result["normalized"] or {}
        blocked = "Публичная нормализация отклонила запрос; смысловые поля пока не доступны." if self.result["normalization_errors"] else None
        for path, expected in self.state["expected"].get("normalized", {}).items():
            actual = dotted(patient, path)
            self.check("normalized." + path, expected, actual, blocked=blocked, basis="CONTRACT_GAP")
        for expected in self.state["expected"].get("history", []):
            rows = [row for row in patient.get("history", []) if row.get("screening_id") == expected["screening_id"]]
            actual = {key: rows[0].get(key) for key in expected} if len(rows) == 1 else rows
            self.check("history." + expected["screening_id"], expected, actual, blocked=blocked, basis="CONTRACT_GAP")

    def evaluate_common(self, rec, plan):
        for name, request in (("recommend", rec), ("plan", plan)):
            data = request["response"] or {}
            blocked = "Ответ не получен." if request["response"] is None else None
            self.check(name + ".demo_boundary", {"demo": True, "medical_validated": False},
                       {key: data.get(key) for key in ("demo", "medical_validated")}, blocked=blocked)
            self.check(name + ".next_visit_array", True, isinstance(data.get("next_visit"), list), blocked=blocked)
            self.check(name + ".no_invented_dates", True,
                       all(row.get("date") is None and row.get("year") is None for row in data.get("next_visit", []))
                       and data.get("reminder_draft", {}).get("due_date") is None
                       and data.get("reminder_draft", {}).get("sent") is False, blocked=blocked)
        p, r = plan["response"] or {}, rec["response"] or {}
        valid = plan["http"] == 200 and p.get("package") is not None and bool(p.get("selected_items"))
        if not valid:
            if plan["http"] == 200 and p.get("package") is None:
                self.check("stop_no_route_or_card", {"route": [], "health_card": [], "after_results": [], "schedule_status": "not_run"},
                           {"route": p.get("route"), "health_card": p.get("health_card"), "after_results": p.get("after_results"),
                            "schedule_status": p.get("schedule", {}).get("status")})
            return
        ids = [row["procedure_id"] for row in p["selected_items"]]
        recommended_ids = {row["procedure_id"] for row in r.get("items", [])}
        self.check("unique_service_ids", len(ids), len(set(ids)))
        self.check("diff_from_original", {"removed": sorted(recommended_ids - set(ids)), "added": sorted(set(ids) - recommended_ids)},
                   {"removed": sorted(row["procedure_id"] for row in p.get("removed_recommended_items", [])),
                    "added": sorted(row["procedure_id"] for row in p.get("added_items", []))})
        self.check("card_selected_only_unperformed", sorted(ids),
                   sorted(row["procedure_id"] for row in p.get("health_card", []))
                   if all(row.get("status") == "не пройдено" and row.get("result") == "нет данных" for row in p.get("health_card", [])) else None)
        self.check("screening_separate", True,
                   all(pid.startswith("prime_") for pid in ids)
                   and all(row.get("payment", {}).get("guaranteed") is False and row.get("source") and row.get("where") for row in p.get("screening", [])))
        self.check("unknown_price", None, p.get("total_price"))
        if p.get("mode") == "custom":
            self.check("custom_price_text", "Стоимость — у администратора", p.get("price_text"))
            self.check("removal_warning_why", True, all(any(
                warning.get("procedure_id") == item["procedure_id"] and item["why"] in warning.get("message", "")
                for warning in p.get("warnings", [])) for item in p.get("removed_recommended_items", [])))
            self.check("manual_addition_basis", True, all(item.get("selection_reason", {}).get("explanation") == "Выбрано пользователем из каталога PRIME"
                                                          for item in p.get("added_items", [])))
        service_actions = {item["procedure_id"]: [a["action_id"] for a in item.get("actions", [])] or [item["procedure_id"]]
                           for item in p["selected_items"]}
        planned = p.get("route", []) + p.get("after_results", [])
        unresolved = [row for row in p.get("unresolved_items", []) if row.get("action_id")]
        expected_actions = sorted(action for actions in service_actions.values() for action in actions)
        self.check("complete_action_disposition", expected_actions, sorted(set(row["action_id"] for row in planned + unresolved)))
        self.check("actions_belong_to_selected_services", True, all(row["procedure_id"] in ids for row in planned + unresolved))
        if p.get("status") == "review":
            self.check("review_no_search", {"status": "not_run", "calls": 0}, {"status": p["schedule"]["status"], "calls": plan["scheduler_calls"]})
        if p.get("schedule", {}).get("status") == "feasible":
            fixtures = plan["scheduler_fixtures"]
            if len(fixtures) != 1:
                self.check("independent_schedule_validator", [], ["No unique captured scheduler input"])
            else:
                native_route = [{**row, "procedure_id": row["action_id"]} for row in p["schedule"]["route"]]
                errors = validate_schedule(fixtures[0], native_route)
                self.check("independent_schedule_validator", [], errors)
                self.check("route_matches_chronology", [row["action_id"] for row in p["schedule"]["route"]],
                           [row["action_id"] for row in p.get("route", [])])
        self.check("after_results_no_time", True, all(row.get("start") is None and row.get("end") is None
                   and row.get("reason") == "после готовности результатов" for row in p.get("after_results", [])))

    def evaluate_special(self, rec, plan):
        try:
            from tools.scenario_assertions import evaluate_special
        except ModuleNotFoundError:
            for name in self.state["expected"].get("checks", []):
                self.check(name, "Свойство из закреплённого DOCX", None, verdict="NOT_RUN",
                           reason="Ответы первого прогона сохранены; отдельный проверяющий модуль ещё готовится.")
        else:
            evaluate_special(self, rec, plan)

    def run_scheduler(self):
        fixture = deepcopy(self.state["standalone_fixture"])
        original = deepcopy(fixture)
        try:
            result = schedule_visit(fixture, max_nodes=None)
            self.result.update(fixture=original, scheduler_result=result)
            expected = self.state["expected"]["fixture"]
            self.check("native_scheduler_exact_fixture", expected["status"], result["status"], basis="SYNTHETIC_FIXTURE")
            self.check("fixture_required_ids", expected["required_ids"], fixture["package"]["required_ids"], basis="SYNTHETIC_FIXTURE")
            self.check("fixture_durations", expected["durations"], {p["id"]: p["duration_minutes"] for p in fixture["procedures"]}, basis="SYNTHETIC_FIXTURE")
            self.check("fixture_unchanged", original, fixture, basis="SYNTHETIC_FIXTURE")
            if result["status"] == "feasible":
                self.check("independent_validator", [], validate_schedule(original, result["route"]), basis="SYNTHETIC_FIXTURE")
                actual = {row["procedure_id"]: [row["start"], row["end"]] for row in result["route"]}
                self.check("exact_intervals", expected["intervals"], actual, basis="SYNTHETIC_FIXTURE")
                self.check("complete_search_no_limit", "feasible", result["status"], basis="SYNTHETIC_FIXTURE")
            else:
                self.check("no_partial_success", [], result["route"], basis="SYNTHETIC_FIXTURE")
                self.check("independent_validator", [], result["route"], basis="SYNTHETIC_FIXTURE", reason="Готового маршрута нет: проверено отсутствие частичного успеха; валидатор полного маршрута здесь неприменим.")
                self.check("complete_search_no_limit", True, result["status"] == "infeasible" and "полного перебора" in result.get("reason", ""), basis="SYNTHETIC_FIXTURE")
            self.check("no_added_after_results", [], result.get("after_results", []))
        except Exception:
            self.result["traceback"] = traceback.format_exc()
            self.check("scheduler_exception", None, self.result["traceback"], ok=False)
        return self.finish()

    def finish(self):
        counts = Counter(row["verdict"] for row in self.result["assertions"])
        self.result["counts"] = {key: counts[key] for key in VERDICTS}
        self.result["verdict"] = next((key for key in ("FAIL", "BLOCKED", "NOT_RUN") if counts[key]),
                                      "PARTIAL_SCOPE" if counts["OUT_OF_SCOPE"] else "PASS")
        return self.result


def _json_digest(value):
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _differences(before, after, path=""):
    """Report every changed leaf; no ignored medical or presentation fields."""
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        result = []
        for key in sorted(set(before) | set(after)):
            child = path + "." + key if path else key
            if key not in before or key not in after:
                result.append({"path": child, "kind": "added" if key not in before else "removed",
                               "before": before.get(key), "after": after.get(key)})
            else:
                result.extend(_differences(before[key], after[key], child))
        return result
    if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        return [difference for index, (old, new) in enumerate(zip(before, after))
                for difference in _differences(old, new, f"{path}[{index}]")]
    return [{"path": path, "kind": "changed", "before": before, "after": after}]


def compare_historical(previous, current):
    """Exact parity with recorded demo-3: all 92 API replies and both S25 runs.

    Run timestamps, manifests and health metadata belong to execution evidence,
    not patient business results. Nothing inside a scenario response, normalized
    patient or scheduler fixture is removed, renamed or otherwise normalized.
    """
    old_states = {state["id"]: state for state in previous["states"]}
    new_states = {state["id"]: state for state in current["states"]}
    checks = []

    def compare(name, old, new):
        differences = _differences(old, new)
        checks.append({"id": name, "verdict": "FAIL" if differences else "PASS",
                       "historical_sha256": _json_digest(old), "actual_sha256": _json_digest(new),
                       "differences": differences})

    compare("state_ids", sorted(old_states), sorted(new_states))
    for sid in sorted(set(old_states) & set(new_states)):
        old, new = old_states[sid], new_states[sid]
        compare(sid + ".request_count", len(old["requests"]), len(new["requests"]))
        for index, (old_request, new_request) in enumerate(zip(old["requests"], new["requests"])):
            # Includes request envelope, HTTP code, COMPLETE public response,
            # captured scheduler inputs and call counts. No field exclusions.
            compare(sid + f".request[{index}]", old_request, new_request)
        for field in ("normalized", "normalization_errors", "scheduler_fixtures"):
            compare(sid + "." + field, old.get(field), new.get(field))
        if "fixture" in old or "fixture" in new:
            for field in ("fixture", "scheduler_result"):
                compare(sid + "." + field, old.get(field), new.get(field))
        # Same verification set and verdicts must also survive the packaging.
        compare(sid + ".assertions", old["assertions"], new["assertions"])
    compare("source_document_coverage", previous["document_coverage"], current["document_coverage"])
    return {"method": "Exact deep comparison; no allowed differences within public responses, normalization or fixtures",
            "historical_source": "reports/scenarios/results.json:final",
            "public_requests_compared": sum(len(state["requests"]) for state in current["states"]),
            "normalizations_compared": sum(bool(state["requests"]) for state in current["states"]),
            "scheduler_fixture_states_compared": sum("fixture" in state for state in current["states"]),
            "declared_business_field_exclusions": [], "checks": checks,
            "verdicts": dict(Counter(check["verdict"] for check in checks))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", default="packaging", help="Label for this new run; historical captures are always read-only")
    parser.add_argument("--output", default="scenario_results.json",
                        help="JSON filename beginning with scenario, written only under reports/packaging")
    args = parser.parse_args()
    if Path(args.output).name != args.output or not args.output.startswith("scenario") or not args.output.endswith(".json"):
        parser.error("--output must be a filename such as scenario_copy_results.json")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    historical_hashes = {path.relative_to(ROOT).as_posix(): sha256(path)
                         for path in HISTORY.rglob("*") if path.is_file()}
    fixture = read_json(FIXTURE)
    states = fixture["states"]
    assert len(states) == 48 and len({row["id"] for row in states}) == 48
    assert len({row["card_id"] for row in states}) == 25
    frozen = HISTORY / "expected_frozen.json"
    if not frozen.exists():
        raise SystemExit("The historical frozen independent expectations are missing")
    verify_expectations(frozen, fixture)
    baseline_manifest = read_json(HISTORY / "baseline_manifest.json")
    assert sha256(ROOT / "tests/fixtures/Scenarios.docx") == baseline_manifest["sha256"]["Scenarios.docx"], "Source DOCX changed"
    previous = read_json(HISTORY / "results.json")["final"]
    assert previous["expected_sha256"] == sha256(FIXTURE), "Historical final run used a different oracle"
    from tools.scenario_assertions import _S23_SNAPSHOTS
    _S23_SNAPSHOTS.clear()
    client = TestClient(app)
    health = client.get("/health")
    health.raise_for_status()
    catalog_version = read_json(ROOT / "prime_checkup/data/demo_catalog.json")["version"]
    run = {"phase": args.phase, "started_at_utc": datetime.now(timezone.utc).isoformat(),
           "method": "FastAPI TestClient against prime_checkup.main; S25 calls the same native scheduler directly; no browser or Uvicorn verification",
           "manifest": manifest(), "expected_sha256": sha256(FIXTURE), "health": health.json(),
           "server_slots": read_json(ROOT / "prime_checkup/data/prime_slots.json"), "states": []}
    for state in states:
        check = StateRun(state, client)
        try:
            value = check.run(catalog_version)
        except Exception:
            check.result["traceback"] = traceback.format_exc()
            check.check("unexpected_execution_error", None, check.result["traceback"], ok=False,
                        reason="Техническое исключение сохранено; независимые состояния продолжают выполняться.")
            value = check.finish()
        run["states"].append(value)
        print(state["id"], value["verdict"], json.dumps(value["counts"]))
    run["document_coverage"] = document_coverage(fixture, run)
    run["cross_state_checks"] = cross_state_checks(fixture, run)
    run["historical_parity"] = compare_historical(previous, run)
    history_after = {path.relative_to(ROOT).as_posix(): sha256(path)
                     for path in HISTORY.rglob("*") if path.is_file()}
    run["historical_evidence_unchanged"] = {"verdict": "PASS" if history_after == historical_hashes else "FAIL",
        "files_checked": len(historical_hashes), "before_sha256": historical_hashes, "after_sha256": history_after}
    counts = Counter(row["verdict"] for state in run["states"] for row in state["assertions"])
    doc_counts = Counter(row["verdict"] for card in run["document_coverage"] for row in card["assertions"])
    run["summary"] = {"cards": 25, "states": 48, "scenario_http_requests": sum(len(state["requests"]) for state in run["states"]),
        "health_http_requests": 1, "total_http_requests": 1 + sum(len(state["requests"]) for state in run["states"]),
        "scheduler_fixture_calls": sum("fixture" in state for state in run["states"]),
        "assertions": sum(counts.values()), "verdicts": {key: counts[key] for key in VERDICTS},
        "state_verdicts": dict(Counter(state["verdict"] for state in run["states"])),
        "document_assertions": sum(doc_counts.values()), "document_verdicts": {key: doc_counts[key] for key in VERDICTS},
        "card_verdicts": dict(Counter(card["verdict"] for card in run["document_coverage"])),
        "cross_state_assertions": len(run["cross_state_checks"]),
        "cross_state_verdicts": dict(Counter(check["verdict"] for check in run["cross_state_checks"])),
        "historical_parity_verdicts": run["historical_parity"]["verdicts"],
        "historical_evidence_unchanged": run["historical_evidence_unchanged"]["verdict"],
        "supplemental_html_requests": 0}
    write_json(OUTPUT / args.output, run)
    print(json.dumps(run["summary"], ensure_ascii=False))
    failed = counts["FAIL"] or counts["BLOCKED"] or counts["NOT_RUN"] or run["historical_parity"]["verdicts"].get("FAIL")
    failed = failed or any(row["verdict"] != "PASS" for row in run["cross_state_checks"])
    failed = failed or run["historical_evidence_unchanged"]["verdict"] != "PASS"
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

