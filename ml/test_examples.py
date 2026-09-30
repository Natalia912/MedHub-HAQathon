"""Прогон контрольных пациентов spec/examples.json через движок: python -m ml.test_examples"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ml.engine import predict  # noqa: E402

EXAMPLES = json.loads((Path(__file__).resolve().parent.parent / "spec" / "examples.json").read_text(encoding="utf-8"))


def check(ex: dict) -> list[str]:
    out, exp, errs = predict(ex["input"]), ex["expect"], []
    if out.get("error"):
        return [f"ошибка: {out['error']}"]
    if out["age_year"] != exp["age_year"]:
        errs.append(f"возраст {out['age_year']} ≠ {exp['age_year']}")
    pkg = out["package"]["id"] if out["package"] else None
    if pkg != exp["package"]:
        errs.append(f"пакет {pkg} ≠ {exp['package']}")
    free = sorted(f["rule_id"] for f in out["free"])
    if free != sorted(exp["free_rules"]):
        errs.append(f"бесплатно {free} ≠ {sorted(exp['free_rules'])}")
    ne = sorted(n["rule_id"] for n in out["not_eligible"])
    if ne != sorted(exp["not_eligible"]):
        errs.append(f"не положено {ne} ≠ {sorted(exp['not_eligible'])}")
    if bool(out["red_flags"]) != exp["red_flag"]:
        errs.append(f"красный флаг {bool(out['red_flags'])} ≠ {exp['red_flag']}")
    missing = set(exp.get("clinic_rules", [])) - set(out.get("clinic_rules", []))
    if missing:
        errs.append(f"не сработали правила клиники {sorted(missing)}")
    return errs


if __name__ == "__main__":
    bad = 0
    for ex in EXAMPLES:
        errs = check(ex)
        bad += bool(errs)
        print(("OK   " if not errs else "FAIL ") + ex["name"] + ("" if not errs else " — " + "; ".join(errs)))
    print(f"\n{len(EXAMPLES) - bad}/{len(EXAMPLES)} зелёных")
    sys.exit(1 if bad else 0)
