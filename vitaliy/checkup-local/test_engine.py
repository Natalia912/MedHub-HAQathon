"""12 контрольных пациентов из spec/examples.json + карусель на 10 эталонных."""
import json
from pathlib import Path

from engine import morning, predict

ROOT = Path(__file__).parent
EXAMPLES = json.loads((ROOT / "spec" / "examples.json").read_text(encoding="utf-8"))
SAMPLES = json.loads((ROOT / "spec" / "sample_inputs.json").read_text(encoding="utf-8"))


def check(ex):
    out = predict(dict(ex["input"]))
    exp = ex["expect"]
    errs = []
    if out.get("error"):
        return [out["error"]]
    if out["age_year"] != exp["age_year"]:
        errs.append(f"возраст {out['age_year']} ≠ {exp['age_year']}")
    if bool(out["red_flag"]) != exp["red_flag"]:
        errs.append("красный флаг")
    if not exp["red_flag"]:
        if out["package"]["id"] != exp["package"]:
            errs.append(f"пакет {out['package']['id']} ≠ {exp['package']}")
        got = sorted(f["rule_id"] for f in out["free"])
        if got != sorted(exp["free_rules"]):
            errs.append(f"бесплатно {got} ≠ {sorted(exp['free_rules'])}")
        got_no = sorted(n["rule_id"] for n in out["not_eligible"])
        if got_no != sorted(exp["not_eligible"]):
            errs.append(f"не положено {got_no} ≠ {sorted(exp['not_eligible'])}")
    return errs


def test_examples():
    bad = {ex["name"]: e for ex in EXAMPLES if (e := check(ex))}
    assert not bad, bad


def test_samples_and_morning():
    pats = []
    for i, s in enumerate(SAMPLES if isinstance(SAMPLES, list) else SAMPLES.get("patients", [])):
        inp = s.get("input", s)
        out = predict(dict(inp))
        assert not out.get("error"), out
        if not out["red_flag"]:
            names = [x["exam"] for x in out["items"]] + [x["exam"] for x in out["extras"]]
            pats.append({"id": i, "label": s.get("name", str(i)), "names": names})
    m = morning(pats)
    assert m["same_time"]["patients"] and m["staggered"]["avg_wait"] < m["same_time"]["avg_wait"]


if __name__ == "__main__":
    ok = 0
    for ex in EXAMPLES:
        e = check(ex)
        print("OK " if not e else "ERR", ex["name"], "" if not e else e)
        ok += not e
    print(f"{ok}/{len(EXAMPLES)}")


def test_consent_and_route_prep():
    out = predict({"sex": "F", "birth_year": 1984, "checkup_year": 2026})
    titles = [c["title"] for c in out["consents"]]
    assert titles[0].startswith("Согласие на обследование")
    assert any("наркоз" in t for t in titles)
    rooms = {s["room"]: s for s in out["route"]["steps"]}
    assert [p["title"] for p in rooms["112"]["prep"]] == ["Гастроскопия — без еды 8 часов, без воды 2 часа"]
    assert [p["title"] for p in rooms["113"]["prep"]] == ["Колоноскопия — очищение кишечника"]


def test_scenario_days_fit_close():
    from fastapi.testclient import TestClient
    import app
    r = TestClient(app.app).post("/api/scenario", json={}).json()
    assert len(r["patients"]) == 12
    assert all(d["day_end"] <= "18:00" for d in r["days"])
    assert sum(1 for p in r["patients"] if p["red_flag"]) == 1
