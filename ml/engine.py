"""Движок чекапа: анкета -> программа обследования (spec/CONTRACT.md).

Все правила — в spec/rules.json, здесь только их применение. predict() никогда не падает:
ошибка возвращается в поле "error".
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULES = json.loads((ROOT / "spec" / "rules.json").read_text(encoding="utf-8"))
SOURCES = RULES["_sources"]
DSM_TITLE = "Приказ МЗ РК ҚР ДСМ-174/2020 (ред. № 75 от 10.07.2026)"
PAYMENT_LABEL = {"free_gobmp": "бесплатно — ГОБМП", "free_osms": "бесплатно — ОСМС", "paid_prime": "пакет PRIME"}
PREGNANCY_RISKY = ("КТ", "Маммограф", "рентген", "Рентген")
CATALOG = {c["id"]: c for c in RULES.get("prime_catalog", [])}
MODEL_VERSION = "rules-1.0"


def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _birth_year(inp: dict) -> int:
    if inp.get("birth_year"):
        return int(inp["birth_year"])
    bd = inp.get("birth_date")
    if bd:
        return int(str(bd)[:4])
    raise ValueError("нет года/даты рождения")


def _source_text(key: str) -> str:
    """'DSM174 прил. 1 п.3, …' -> человекочитаемый источник."""
    if key.startswith("DSM174"):
        return DSM_TITLE + key[len("DSM174"):]
    if key == "PRIME":
        return "Состав пакета — primegc.kz/check-up"
    if key in ("CLINIC_RULE", "ANAMNESIS_DRAFT"):
        return "Правило клиники — требует подтверждения врача"
    return SOURCES.get(key, key)


def _where_free(attached: str | None) -> str:
    if attached == "green_clinic":
        return "в Green Clinic (поликлиника прикрепления), в течение 60 дней"
    if attached == "other":
        return "в вашей поликлинике прикрепления, в течение 60 дней"
    return "в поликлинике прикрепления, в течение 60 дней (прикрепление можно проверить на egov.kz)"


def _screening_check(rule: dict, ctx: dict) -> tuple[bool, str | None]:
    """(положен?, причина-если-не-положен). Причина None = не подходит по возрасту/полу (не показываем)."""
    w = rule["when"]
    if ctx["sex"] not in w.get("sex", ["M", "F"]):
        return False, None
    age = ctx["age_year"]
    if "age_year" in w and age not in w["age_year"]:
        return False, None
    if "age_min" in w and age < w["age_min"]:
        return False, None
    if "risk_group" in w and not set(ctx["risk_group"]) & set(w["risk_group"]):
        return False, None
    if "any_of" in w:
        ok = False
        for alt in w["any_of"]:
            if "pack_years_min" in alt:
                s = ctx["smoking"]
                py = s.get("pack_years") or 0
                quit_ago = s.get("quit_years_ago") or 0
                if py >= alt["pack_years_min"] and quit_ago <= alt.get("quit_years_max", 99):
                    ok = True
            if alt.get("hazardous_work_10y") and ctx["hazardous_work_10y"]:
                ok = True
        if not ok:
            return False, None
    reg = set(w.get("not_registered", [])) & set(ctx["registered"])
    if reg:
        return False, "Вы на учёте у врача по этому заболеванию — обследование проводит ваш врач по наблюдению, скрининг не нужен"
    if w.get("not_pregnant") and ctx["pregnant"] == "yes":
        return False, "Во время беременности этот скрининг не проводится — анализы назначит врач по ведению беременности"
    last = ctx["last_screening"].get(rule["id"])
    period = rule.get("repeat_years")
    if last and period and int(last) + period > ctx["checkup_year"]:
        return False, f"Вы проходили его в {last} году — следующий по графику в {int(last) + period} году"
    return True, None


def _route_step(exam: str) -> int:
    e = exam.lower()
    if "анестез" in e or "гастроскоп" in e or "колоноскоп" in e:
        return 4
    if "заключение" in e:
        return 5
    if "консультац" in e or "приём" in e or "прием" in e or "осмотр" in e:
        return 3
    if exam.startswith("КТ") or " КТ" in exam or "маммограф" in e or "рентген" in e:
        return 2
    if "узи" in e or "экг" in e or "эхокг" in e or "уздг" in e or "трузи" in e or "функц" in e:
        return 1
    return 0


def build_route(exams: list[str]) -> list[str]:
    steps = RULES["day_route_order"]["steps"]
    groups: dict[int, list[str]] = {}
    for ex in exams:
        groups.setdefault(_route_step(ex), []).append(ex)
    return [f"{n}. {steps[i]}: " + ", ".join(groups[i]) for n, i in enumerate(sorted(groups), 1)]


def build_prep(exams: list[str], inp: dict) -> list[dict]:
    out = []
    for p in RULES.get("prep_catalog", []):
        by_answer = p.get("when_answer")
        if by_answer and not all(inp.get(k) == v for k, v in by_answer.items()):
            continue
        if any(m.lower() in ex.lower() for m in p.get("match", []) for ex in exams):
            out.append({k: p[k] for k in ("id", "title", "text", "day", "source") if k in p})
    return out


def _context(inp: dict) -> dict:
    year = int(inp.get("checkup_year") or date.today().year)
    by = _birth_year(inp)
    return {
        "checkup_year": year,
        "birth_year": by,
        "age_year": year - by,
        "sex": inp.get("sex"),
        "for_child": bool(inp.get("for_child")),
        "registered": _as_list(inp.get("registered")),
        "conditions": _as_list(inp.get("conditions")),
        "family_history": _as_list(inp.get("family_history")),
        "complaints": _as_list(inp.get("complaints")),
        "risk_group": _as_list(inp.get("risk_group")),
        "pregnant": inp.get("pregnant"),
        "smoking": inp.get("smoking") or {},
        "hazardous_work_10y": bool(inp.get("hazardous_work_10y")),
        "last_screening": inp.get("last_screening") or {},
        "attached_to": inp.get("attached_to"),
    }


def _pick_package(ctx: dict) -> dict | None:
    age = ctx["age_year"]
    for p in RULES["packages"]:
        w = p["when"]
        if w["age_min"] <= age <= w["age_max"]:
            return p
    return None


def _matches(when: dict, ctx: dict, inp: dict) -> bool:
    for k, v in when.items():
        if k == "sex":
            if ctx["sex"] != v:
                return False
        elif k in ("conditions", "family_history", "complaints", "complaint"):
            if v not in ctx["complaints" if k == "complaint" else k]:
                return False
        elif inp.get(k) != v:
            return False
    return True


def predict(inp: dict) -> dict:
    try:
        return _predict(inp or {})
    except Exception as exc:  # predict() не падает — ошибка уходит в ответ
        return {"package": None, "items": [], "free": [], "not_eligible": [], "red_flags": [],
                "route": [], "prep": [], "next_visit": [], "needs_doctor_review": True,
                "reasons": [], "model_version": MODEL_VERSION, "error": f"{type(exc).__name__}: {exc}"}


def _predict(inp: dict) -> dict:
    ctx = _context(inp)
    base = {"age_year": ctx["age_year"], "needs_doctor_review": True, "model_version": MODEL_VERSION, "error": None}

    urgent = [u for u in _as_list(inp.get("urgent")) if u and u != "none"]
    if urgent or "chest_pain" in ctx["complaints"]:
        return {**base, "package": None, "items": [], "free": [], "not_eligible": [], "route": [], "prep": [],
                "next_visit": [], "clinic_rules": [],
                "red_flags": [{"code": (urgent or ["chest_pain"])[0],
                               "message": "Это не для чекапа. Позвоните 103 или обратитесь к врачу сегодня."}],
                "reasons": [{"factor": "red_flag", "detail": "Срочный симптом — чекап не предлагаем", "weight": 1.0}]}

    items: list[dict] = []
    reasons: list[dict] = []
    clinic_rules: list[str] = []

    # 1. Пакет PRIME
    pkg = _pick_package(ctx)
    package = None
    if pkg:
        female = ctx["sex"] == "F"
        name = pkg.get("name_f" if female else "name_m") or pkg.get("name_mini") or pkg["name"]
        url = pkg.get("url_f" if female else "url_m") or pkg.get("url_mini")
        exams = list(pkg["exams"]) + list(pkg.get("female_exams" if female else "male_exams", []))
        package = {"id": pkg["id"], "name": name, "url": url, "payment": "paid_prime", "price": pkg.get("price"),
                   "price_note": "стоимость — у администратора PRIME"}
        age_why = "детский пакет 1–17 лет" if pkg["id"] == "prime_child" else (
            "пакет «после 40 лет»" if pkg["id"] == "prime_extended" else "пакет «до 40 лет»")
        for ex in exams:
            it = {"exam": ex, "payment": "paid_prime", "why": f"Входит в {age_why} по вашему возрасту",
                  "source": _source_text("PRIME"), "where": "PRIME, в день визита", "rule_id": pkg["id"],
                  "emphasis": [], "caution": None}
            if ctx["pregnant"] in ("yes", "unsure") and any(k in ex for k in PREGNANCY_RISKY):
                it["caution"] = "При беременности или подозрении на неё — только после разговора с врачом"
            items.append(it)
        reasons.append({"factor": "package", "detail": f"{name}: возраст {ctx['age_year']}", "weight": 1.0})

    # 2. Анамнез и жалобы: добавить услуги или отметить важное в пакете (черновик, утверждает врач)
    for rule in RULES.get("anamnesis_rules", []) + RULES.get("complaints", []):
        if not _matches(rule["when"], ctx, inp):
            continue
        if rule.get("action") == "red_flag":
            continue
        clinic_rules.append(rule["id"])
        why = rule.get("why") or rule.get("note") or rule["id"]
        for word in rule.get("emphasize", []) + rule.get("exams", []):
            for it in items:
                if word.lower() in it["exam"].lower() and why not in it["emphasis"]:
                    it["emphasis"].append(why)
        for cid in rule.get("add", []):
            c = CATALOG.get(cid)
            if not c or any(c["name"] == it["exam"] for it in items):
                continue
            skip = rule.get("skip_if_in_package")
            if skip and any(skip.lower() in it["exam"].lower() for it in items):
                continue
            items.append({"exam": c["name"], "payment": "paid_prime", "why": f"Дополнительно: {why}",
                          "source": _source_text(rule.get("source", "CLINIC_RULE")), "where": "PRIME, в день визита",
                          "rule_id": rule["id"], "emphasis": [], "caution": None, "added": True,
                          "url": c.get("url"), "needs_doctor_validation": True})
        reasons.append({"factor": rule["id"], "detail": why, "weight": 0.5})

    # 3. Госскрининг — отдельным блоком, бесплатно
    free, not_eligible, next_visit = [], [], []
    for rule in RULES["screening"]:
        ok, why_not = _screening_check(rule, ctx)
        if not ok:
            if why_not:
                not_eligible.append({"rule_id": rule["id"], "name": rule["name"], "why": why_not})
            continue
        overlap = [it["exam"] for it in items
                   if any(o.lower() in it["exam"].lower() or it["exam"].lower() in o.lower()
                          for o in rule.get("prime_overlap", []))]
        free.append({
            "rule_id": rule["id"], "name": rule["name"], "exams": rule["stage1"],
            "payment": rule["payment"], "payment_label": PAYMENT_LABEL[rule["payment"]],
            "where": _where_free(ctx["attached_to"]),
            "source": _source_text(rule["source"]),
            "also_in_prime": overlap,
            "choice": ("Можно бесплатно в поликлинике или сегодня в PRIME в составе пакета" if overlap else None),
            "note": rule.get("note"),
        })
        period = rule.get("repeat_years")
        if period:
            next_visit.append({"rule_id": rule["id"], "name": rule["name"], "year": ctx["checkup_year"] + period})
        reasons.append({"factor": rule["id"], "detail": f"{rule['name']} — положен бесплатно", "weight": 1.0})

    exams = [it["exam"] for it in items]
    return {
        **base,
        "package": package,
        "items": items,
        "free": free,
        "not_eligible": not_eligible,
        "red_flags": [],
        "clinic_rules": clinic_rules,
        "route": build_route(exams),
        "prep": build_prep(exams, inp),
        "next_visit": next_visit,
        "summary": {"free_count": len(free), "paid_count": len(items)},
        "reasons": reasons,
    }


def plan(inp: dict, selected: list[str]) -> dict:
    """Выбранный пациентом набор (пресет или свой) -> маршрут дня, подготовка, повторы."""
    try:
        base = predict(inp)
        chosen = [s for s in selected if s]
        return {"selected": chosen, "route": build_route(chosen), "prep": build_prep(chosen, inp),
                "free": base.get("free", []), "next_visit": base.get("next_visit", []),
                "price_note": "стоимость своего набора — у администратора PRIME", "error": base.get("error")}
    except Exception as exc:
        return {"selected": [], "route": [], "prep": [], "free": [], "next_visit": [], "error": f"{type(exc).__name__}: {exc}"}


def catalog() -> list[dict]:
    """Каталог для «собрать свой пакет»: все обследования пакетов PRIME + услуги prime_catalog."""
    seen, out = set(), []
    for p in RULES["packages"]:
        for key in ("exams", "female_exams", "male_exams", "extended_exams"):
            for ex in p.get(key, []):
                if ex not in seen:
                    seen.add(ex)
                    out.append({"exam": ex, "from": p["id"]})
    for c in RULES.get("prime_catalog", []):
        if c["name"] not in seen:
            seen.add(c["name"])
            out.append({"exam": c["name"], "from": "prime_catalog", "url": c.get("url")})
    return out
