"""Движок чекапа: анкета → программа PRIME + бесплатный госскрининг → подготовка → маршрут дня → повторы.

Все правила — в spec/rules.json (у каждой строки источник). В коде только порядок применения.
predict() никогда не падает: ошибка уходит в поле error.
"""
import json
from datetime import date, datetime, timedelta
from pathlib import Path

RULES = json.loads((Path(__file__).parent / "spec" / "rules.json").read_text(encoding="utf-8"))
SOURCES = RULES["_sources"]
MODEL_VERSION = "rules-2026-09-30"


def _source(key):
    """Короткое имя источника + полное описание из _sources."""
    head = key.split(" ")[0]
    human = {"ANAMNESIS_DRAFT": "правило анамнеза — черновик, утверждает врач",
             "PREP_DRAFT": "памятка — черновик, утверждает врач",
             "CONSENT": "Кодекс РК «О здоровье народа…», ст. 134",
             "ANAR_ROOMS": "кабинеты — со слов медэксперта", "ROOMS_DEMO": "допущение команды",
             "EXPERT_0930": "решение медэксперта 30.09.2026", "ROUTE_ESTIMATE": "ориентир команды"}
    text = human.get(key) or key.replace("DSM174", "Приказ МЗ РК ҚР ДСМ-174/2020,")
    return {"code": head, "text": text, "full": SOURCES.get(head, key)}


def _has(text, words):
    low = text.lower()
    return any(w.lower() in low for w in words)


def _ages(inp):
    today = date(int(inp.get("checkup_year") or date.today().year), date.today().month, date.today().day)
    bd = inp.get("birth_date")
    if bd:
        b = datetime.strptime(bd, "%Y-%m-%d").date()
        full = today.year - b.year - ((today.month, today.day) < (b.month, b.day))
        return today.year - b.year, full
    by = int(inp["birth_year"])
    return today.year - by, today.year - by  # без даты рождения полные годы = по году


def _package(full_age, inp):
    if inp.get("for_child") or full_age < 18:
        return RULES["packages"][0]
    for p in RULES["packages"]:
        w = p["when"]
        if w["age_min"] <= full_age <= w["age_max"]:
            return p
    return None


def _package_exams(pkg, sex):
    extra = pkg.get("female_exams" if sex == "F" else "male_exams", [])
    out = []
    for e in pkg["exams"] + extra:
        rule = next((o for o in RULES["optional_exams"]["rules"] if e.startswith(o["match"])), None)
        if rule:  # «Онкомаркеры: CA 15-3, CA 125, …» → по одному, выбирает куратор
            out += [rule["split_prefix"] + m.strip() for m in e[len(rule["match"]):].split(",")]
        else:
            out.append(e)
    return out


def _optional(exam):
    for o in RULES["optional_exams"]["rules"]:
        if exam.startswith(o["split_prefix"]):
            return o
    return None


def _package_name(pkg, sex):
    if pkg["id"] == "prime_child":
        return pkg.get("name_mini", pkg["name"])
    return pkg.get("name_f" if sex == "F" else "name_m", pkg["name"])


def _screening(inp, age_year):
    """Возвращает (положено, не положено с причиной)."""
    sex, year = inp["sex"], int(inp.get("checkup_year") or date.today().year)
    registered = set(inp.get("registered") or [])
    last = inp.get("last_screening") or {}
    smoking = inp.get("smoking") or {}
    ok, no = [], []
    for s in RULES["screening"]:
        w = s["when"]
        if sex not in w["sex"]:
            continue
        if "age_year" in w and age_year not in w["age_year"]:
            continue
        if "age_min" in w and age_year < w["age_min"]:
            continue
        if "any_of" in w:
            hit = False
            for cond in w["any_of"]:
                if "pack_years_min" in cond and (smoking.get("pack_years") or 0) >= cond["pack_years_min"] \
                        and (smoking.get("quit_years_ago") or 0) <= cond["quit_years_max"]:
                    hit = True
                if cond.get("hazardous_work_10y") and inp.get("hazardous_work_10y"):
                    hit = True
            if not hit:
                continue
        reg = registered & set(w.get("not_registered", []))
        if reg:
            no.append({"rule_id": s["id"], "name": s["name"],
                       "why": "Вы на учёте по этому заболеванию — обследование у врача, который вас наблюдает",
                       "source": _source(s["source"])})
            continue
        if w.get("not_pregnant") and inp.get("pregnant") == "yes":
            no.append({"rule_id": s["id"], "name": s["name"],
                       "why": "Во время беременности анализ делают в рамках наблюдения по беременности",
                       "source": _source(s["source"])})
            continue
        if s["id"] in last and year - int(last[s["id"]]) < s["repeat_years"]:
            no.append({"rule_id": s["id"], "name": s["name"],
                       "why": f"Проходили в {last[s['id']]} — следующий раз в {int(last[s['id']]) + s['repeat_years']}",
                       "source": _source(s["source"])})
            continue
        ok.append(s)
    return ok, no


def _catalog(cid):
    return next((c for c in RULES["prime_catalog"] if c["id"] == cid), None)


def _anamnesis(inp, exams):
    """Добавки сверх пакета и акценты внутри пакета — по утверждённой врачом таблице."""
    answers = {
        "conditions": set(inp.get("conditions") or []),
        "family_history": set(inp.get("family_history") or []),
    }
    adds, emph = [], {}
    for r in RULES["anamnesis_rules"]:
        w = r["when"]
        hit = True
        for k, v in w.items():
            if k == "sex":
                hit &= inp.get("sex") == v
            elif k in answers:
                hit &= v in answers[k]
            else:
                hit &= inp.get(k) == v
        if not hit:
            continue
        for cid in r.get("add", []):
            c = _catalog(cid)
            if not c or (r.get("skip_if_in_package") and any(_has(e, [r["skip_if_in_package"]]) for e in exams)):
                continue
            if any(a["exam"] == c["name"] for a in adds):
                continue
            adds.append({"exam": c["name"], "payment": "paid_extra", "why": f"Вы отметили: {r['why']}",
                         "source": _source(r["source"]), "url": c.get("url"), "rule_id": r["id"],
                         "needs_doctor_validation": True})
        for word in r.get("emphasize", []):
            for e in exams:
                if _has(e, [word]):
                    emph.setdefault(e, []).append(r["why"])
    return adds, emph


def _prep(inp, names):
    out = []
    for p in RULES["prep_catalog"]:
        if not any(_has(n, p["match"]) for n in names):
            continue
        if any(inp.get(k) != v for k, v in (p.get("when_answer") or {}).items()):
            continue
        out.append({k: p[k] for k in ("id", "day", "title", "text", "question", "options", "correct", "source")})
    return out


def _route(names):
    rp = RULES["route_plan"]
    t = datetime.strptime(rp["start"], "%H:%M")
    steps = []
    for st in rp["steps"]:
        if st.get("only_without") and any(_has(n, st["only_without"]) for n in names):
            continue
        if st["match"] and not any(_has(n, st["match"]) for n in names):
            continue
        mine = [n for n in names if _has(n, st["match"])] if st["match"] else []
        prep = [{"title": p["title"], "text": p["text"]} for p in RULES["prep_catalog"]
                if not p.get("when_answer") and any(_has(n, p["match"]) for n in mine)]
        steps.append({"time": t.strftime("%H:%M"), "title": st["title"], "minutes": st["minutes"], "exams": mine,
                      "prep": prep or None})
        t += timedelta(minutes=st["minutes"])
    steps.append({"time": t.strftime("%H:%M"), "title": "Свободны", "minutes": 0})
    return {"steps": steps, "final": rp["final"], "source": _source(rp["source"])}


def _consents(names):
    cat = RULES["consent_catalog"]
    out = [dict(cat["general"], source=_source(cat["general"]["source"]))]
    for c in cat["items"]:
        hits = [n for n in names if _has(n, c["match"])]
        if hits:
            out.append(dict({k: v for k, v in c.items() if k != "match"}, exams=hits, source=_source(c["source"])))
    return out


def predict(inp):
    try:
        return _predict(inp)
    except Exception as exc:  # экран не должен падать — показываем причину
        return {"error": f"{type(exc).__name__}: {exc}", "model_version": MODEL_VERSION}


def _predict(inp):
    if inp.get("birth_date") and not inp.get("birth_year"):
        inp = {**inp, "birth_year": int(inp["birth_date"][:4])}
    age_year, full_age = _ages(inp)
    year = int(inp.get("checkup_year") or date.today().year)
    urgent = inp.get("urgent") not in (None, "", "none") or "chest_pain" in (inp.get("complaints") or [])
    base = {"age_year": age_year, "full_age": full_age, "model_version": MODEL_VERSION, "error": None,
            "needs_doctor_review": True}
    if urgent:
        return {**base, "red_flag": True, "package": None, "items": [], "extras": [], "not_eligible": [],
                "message": "Это не чекап. Если беспокоит прямо сейчас — обратитесь к врачу; "
                           "при острой боли в груди, одышке, признаках инсульта — звоните 103."}

    pkg = _package(full_age, inp)
    exams = _package_exams(pkg, inp["sex"])
    free, not_eligible = _screening(inp, age_year)
    extras, emph = _anamnesis(inp, exams)

    covered = {}  # обследование пакета → бесплатный скрининг, который его перекрывает
    for s in free:
        for ov in s.get("prime_overlap", []):
            for e in exams:
                if _has(e, [ov]):
                    covered[e] = s["id"]

    free_items = [{"rule_id": s["id"], "name": s["name"], "exams": s["stage1"], "payment": s["payment"],
                   "repeat_years": s["repeat_years"], "deadline_days": s["deadline_days"],
                   "in_package": any(v == s["id"] for v in covered.values()),
                   "note": s.get("stage2_note") or s.get("note"), "source": _source(s["source"])} for s in free]

    pregnant = inp.get("pregnant") == "yes"
    items = []
    for e in exams:
        flags = []
        if pregnant and _has(e, ["КТ", "Маммограф", "Рентген"]):
            flags.append("Беременность — обсудите с врачом, это обследование обычно откладывают")
        opt = _optional(e)
        items.append({"exam": e, "payment": "paid_prime", "optional": bool(opt),
                      "why": (opt["why"] if opt else f"Входит в пакет «{_package_name(pkg, inp['sex'])}»"),
                      "emphasis": emph.get(e, []), "free_option": covered.get(e), "flags": flags,
                      "source": {"code": "PRIME", "text": "primegc.kz", "full": SOURCES["PRIME"]}})

    for c in RULES["complaints"]:  # семейный анамнез: рак кишечника → колоноскопия раньше 50
        fh = c["when"].get("family_history")
        if fh and fh in (inp.get("family_history") or []) and full_age < 50:
            items_note = c.get("note")
            for it in items:
                if _has(it["exam"], ["колоноскопия"]):
                    it["emphasis"].append(items_note)

    names = exams + [x["exam"] for x in extras]
    next_visit = [{"rule_id": s["id"], "name": s["name"], "year": year + s["repeat_years"], "free": True} for s in free]
    next_visit.append({"rule_id": pkg["id"], "name": "Повторный чекап PRIME", "year": year + 1, "free": False,
                       "note": "через год — рекомендация клиники"})
    return {**base, "red_flag": False,
            "package": {"id": pkg["id"], "name": _package_name(pkg, inp["sex"]), "price": pkg.get("price"),
                        "url": pkg.get("url_f" if inp["sex"] == "F" else "url_m") or pkg.get("url_mini")},
            "free": free_items, "items": items, "extras": extras, "not_eligible": not_eligible,
            "prep": _prep(inp, names), "route": _route_rooms(names), "consents": _consents(names), "next_visit": sorted(next_visit, key=lambda x: x["year"]),
            "summary": {"free_count": len(free_items), "package_count": len(items), "extra_count": len(extras)}}


# ---------- Утро клиники: карусель кабинетов ----------

def _room_minutes(room, names):
    """Длительность приёма пациента в кабинете: по числу исследований (study_words), не меньше minutes."""
    if not room.get("study_minutes"):
        return room["minutes"]
    mine = [n for n in names if _has(n, room["match"])]
    studies = sum(1 for n in mine for w in room["study_words"] if w.lower() in n.lower())
    return max(room["minutes"], studies * room["study_minutes"])


def _rooms(places=None):
    rooms = []
    for r in RULES["carousel"]["rooms"]:
        r = dict(r)
        if places and r["id"] in places:
            r["places"] = int(places[r["id"]])
        rooms.append(r)
    return rooms


def _simulate(patients, arrivals=None, places=None):
    """patients: [{"id","label","names":[услуги]}]. Жадная карусель: каждый идёт в свободный кабинет своей программы;
    группы по rank по возрастанию (0 — куратор и кровь, 1 — в любом порядке, 2+ — эндоскопия последней)."""
    cfg = RULES["carousel"]
    rooms = _rooms(places)
    start = datetime.strptime(cfg["start"], "%H:%M")
    walk = cfg["walk_minutes"]
    free_at = {r["id"]: [0] * r["places"] for r in rooms}
    busy = {r["id"]: 0 for r in rooms}
    state = []
    for p in patients:
        todo = [dict(r, dur=_room_minutes(r, p["names"])) for r in rooms if any(_has(n, r["match"]) for n in p["names"])]
        t0 = (arrivals or {}).get(p["id"], 0)
        state.append({"p": p, "todo": todo, "t": t0, "arrive": t0, "log": [], "ate": False})
    while any(s["todo"] for s in state):
        s = min((x for x in state if x["todo"]), key=lambda x: (x["t"], x["arrive"]))
        min_rank = min(r["rank"] for r in s["todo"])
        cands = [r for r in s["todo"] if r["rank"] == min_rank]
        best = min(cands, key=lambda r: (max(s["t"], min(free_at[r["id"]])), not r.get("fasting"), -r["dur"]))
        slot = free_at[best["id"]].index(min(free_at[best["id"]]))
        begin = max(s["t"], free_at[best["id"]][slot])
        end = begin + best["dur"]
        free_at[best["id"]][slot] = end + walk
        busy[best["id"]] += best["dur"]
        s["log"].append({"room": best["no"], "title": best["title"], "start": begin, "end": end, "wait": begin - s["t"],
                         "room_id": best["id"]})
        s["t"] = end + walk
        s["todo"].remove(best)
        if not s["ate"] and not any(r.get("fasting") or r.get("endoscopy") for r in s["todo"]) \
                and not any(_has(n, cfg["breakfast"]["only_without"]) for n in s["p"]["names"]):
            s["log"].append({"room": "—", "title": cfg["breakfast"]["title"], "start": s["t"],
                             "end": s["t"] + cfg["breakfast"]["minutes"], "wait": 0})
            s["t"] += cfg["breakfast"]["minutes"]
            s["ate"] = True
        if best.get("rest") or (best.get("endoscopy") and not any(r.get("endoscopy") for r in s["todo"])):
            s["log"].append({"room": "—", "title": cfg["rest"]["title"], "start": s["t"],
                             "end": s["t"] + cfg["rest"]["minutes"], "wait": 0})
            s["t"] += cfg["rest"]["minutes"]

    def hhmm(m):
        return (start + timedelta(minutes=m)).strftime("%H:%M")

    out = [{"id": s["p"]["id"], "label": s["p"]["label"], "arrive": hhmm(s["arrive"]), "finish": hhmm(s["t"]),
            "in_clinic": s["t"] - s["arrive"], "wait_total": sum(x["wait"] for x in s["log"]),
            "steps": [{**x, "start": hhmm(x["start"]), "end": hhmm(x["end"])} for x in s["log"]]} for s in state]
    day_end = max(s["t"] for s in state) if state else 0
    load = sorted(({"room": r["no"], "room_id": r["id"], "title": r["title"], "places": r["places"],
                    "places_options": r.get("places_options"), "busy": busy[r["id"]],
                    "share": round(busy[r["id"]] / (day_end * r["places"]), 2) if day_end else 0} for r in rooms),
                  key=lambda x: -x["share"])
    waits = [p["wait_total"] for p in out]
    return {"patients": out, "day_end": hhmm(day_end), "bottleneck": load[0] if load else None, "load": load,
            "rooms_count": len(rooms), "avg_wait": round(sum(waits) / len(waits)) if waits else 0,
            "max_wait": max(waits) if waits else 0, "source": _source(cfg["source"])}


def morning(patients, places=None):
    """Два режима: все приходят к началу дня / каждому своё время прихода.
    Своё время: приход сдвигается на ожидание в первой половине дня (до узкого места), шаг 15 минут;
    подбирается итерацией, пока среднее ожидание падает и конец дня не позже."""
    cfg = RULES["carousel"]
    start = datetime.strptime(cfg["start"], "%H:%M")
    la = datetime.strptime(cfg.get("latest_arrival", "23:59"), "%H:%M")
    cap = int((la - start).total_seconds() // 60)
    same = _simulate(patients, places=places)
    best, arrivals = same, {p["id"]: 0 for p in patients}
    for _ in range(6):
        improved = False
        for k in (0.9, 0.6, 0.4, 0.25):
            cand = dict(arrivals)
            for p in best["patients"]:
                cand[p["id"]] = min(cap, cand[p["id"]] + (int(p["wait_total"] * k) // 15) * 15)
            trial = _simulate(patients, cand, places)
            if trial["avg_wait"] < best["avg_wait"] and trial["day_end"] <= same["day_end"]:
                best, arrivals, improved = trial, cand, True
                break
        if not improved:
            break
    for p in best["patients"]:
        p["arrive"] = (start + timedelta(minutes=arrivals[p["id"]])).strftime("%H:%M")
    return {"same_time": same, "staggered": best, "capacity": capacity(patients, places)}


def capacity(patients, places=None):
    """Сколько пациентов из списка (по порядку записи) клиника пропускает за день, чтобы все освободились к day_close."""
    close = RULES["carousel"].get("day_close", "18:00")
    fit, info = 0, None
    for n in range(1, len(patients) + 1):
        m = _simulate(patients[:n], places=places)
        if m["day_end"] > close:
            break
        fit, info = n, m
    return {"day_close": close, "fits": fit, "of": len(patients),
            "day_end": info["day_end"] if info else None, "avg_wait": info["avg_wait"] if info else None}


def _route_rooms(names):
    """Маршрут одного пациента по кабинетам карусели (пустая клиника) + подготовка к каждому кабинету."""
    sim = _simulate([{"id": 0, "label": "", "names": names}])
    rooms = {r["id"]: r for r in RULES["carousel"]["rooms"]}
    steps = []
    for st in sim["patients"][0]["steps"]:
        room = rooms.get(st.get("room_id"))
        mine = [n for n in names if room and _has(n, room["match"])]
        def fits(p):
            if p.get("when_answer") or not any(_has(n, p["match"]) for n in mine):
                return False
            if room and room.get("endoscopy"):  # у ФГДС и колоноскопии одна услуга в пакете — подготовка по кабинету
                return any(_has(" ".join(room["match"]), [m]) for m in p["match"])
            return True
        if room is None and "наркоз" in st["title"]:
            prep = [{"id": p["id"], "title": p["title"], "text": p["text"], "source": p["source"]} for p in RULES["prep_catalog"]
                    if p["id"] == "pr_anesthesia"]
        else:
            prep = [{"id": p["id"], "title": p["title"], "text": p["text"], "source": p["source"]} for p in RULES["prep_catalog"] if fits(p)]
        steps.append({"time": st["start"], "end": st["end"], "room": st["room"], "title": st["title"], "exams": mine,
                      "minutes": _mins(st["start"], st["end"]), "prep": prep or None})
    steps.append({"time": sim["patients"][0]["finish"], "room": "", "title": "Свободны", "minutes": 0, "exams": [], "prep": None})
    return {"steps": steps, "final": RULES["route_plan"]["final"], "source": _source(RULES["carousel"]["source"])}


def _mins(a, b):
    return (int(b[:2]) * 60 + int(b[3:])) - (int(a[:2]) * 60 + int(a[3:]))
