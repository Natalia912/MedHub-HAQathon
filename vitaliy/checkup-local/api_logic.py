"""Логика API без веб-сервера — её же исполняет онлайн-копия (Pyodide в браузере)."""
import json
from pathlib import Path

from engine import capacity, morning, predict

ROOT = Path(__file__).parent
DEMO = json.loads((ROOT / "spec" / "demo_patients.json").read_text(encoding="utf-8"))["patients"]


def _names(out):
    return [x["exam"] for x in out["items"]] + [x["exam"] for x in out["extras"]]


def api_morning(body: dict):
    """body: {"places": {"r103": 2}} — утро для 12 демо-пациентов (красный флаг в утро не идёт)."""
    pats = []
    for i, d in enumerate(DEMO):
        out = predict(dict(d["input"]))
        if not out.get("error") and not out["red_flag"]:
            pats.append({"id": i, "label": d["name"], "names": _names(out)})
    return morning(pats, body.get("places"))


def api_scenario(body: dict):
    """Все 12 демо-пациентов по этапам. Запись по дням: в день берём столько, сколько кабинеты пропускают к day_close
    (capacity), остальных — на следующий день; у каждого своё время прихода."""
    places = body.get("places")
    outs, pats = {}, []
    for i, d in enumerate(DEMO):
        out = predict(dict(d["input"]))
        outs[i] = out
        if not out.get("error") and not out["red_flag"]:
            pats.append({"id": i, "label": d["name"], "names": _names(out)})
    slot, days, rest = {}, [], pats
    while rest:
        n = max(1, capacity(rest, places)["fits"])
        m = morning(rest[:n], places)["staggered"]
        days.append({"day": len(days) + 1, "count": n, "avg_wait": m["avg_wait"], "day_end": m["day_end"]})
        for p in m["patients"]:
            slot[p["id"]] = {**p, "day": len(days)}
        rest = rest[n:]
    rows = []
    for i, d in enumerate(DEMO):
        out = outs[i]
        row = {"id": i, "name": d["name"], "red_flag": out.get("red_flag", False)}
        if not out["red_flag"]:
            mp = slot.get(i, {})
            row.update({"package": out["package"]["name"], "free": [f["name"] for f in out["free"]],
                        "extras": [x["exam"] for x in out["extras"]], "consents": [c["title"] for c in out["consents"]],
                        "prep": len(out["prep"]), "items": len(out["items"]) + len(out["extras"]),
                        "day": mp.get("day"), "arrive": mp.get("arrive"), "finish": mp.get("finish"),
                        "wait": mp.get("wait_total"),
                        "next": [f"{n['name']} — {n['year']}" for n in out["next_visit"]]})
        rows.append(row)
    return {"patients": rows, "days": days}
