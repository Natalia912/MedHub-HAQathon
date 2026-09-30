"""Information from the project's seven screening rules, not entitlement or orders.

Input is the shared intake adapter's normalized patient. No questionnaire answer
is turned into a diagnosis here; only explicitly confirmed registration codes can
exclude somebody on that ground. This module never changes a PRIME composition.
"""
import json
from copy import deepcopy
from pathlib import Path


DATA = Path(__file__).parent / "data"
BROAD_CONDITIONS = {
    "pressure": "hypertension", "heart": "ihd", "diabetes": "diabetes",
    "glaucoma": "glaucoma", "head_vessels": "cerebrovascular",
    "breast": "breast_cancer", "hpv": "cervical_cancer", "bowel": "colorectal",
    "lungs": "lung_cancer", "hepatitis": "chronic_hepatitis",
}
RULE_IDS = {"scr_cvd", "scr_cerebro", "scr_breast", "scr_cervix",
            "scr_colorectal", "scr_hepatitis", "scr_lung"}


def _load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def _check(outcome, reason, *missing):
    return {"outcome": outcome, "reason": reason, "missing_fields": list(missing)}


def _demographics(patient, rule):
    """Reject known age/sex mismatches before asking unrelated questions."""
    when = rule["when"]
    sex, age = patient.get("sex"), patient.get("age_year")
    if sex in ("M", "F") and sex not in when["sex"]:
        return _check("not_eligible", "Пол не соответствует указанным критериям демоправила.")
    if age is not None:
        if "age_year" in when and age not in when["age_year"]:
            return _check("not_eligible", "Возраст по году достижения не входит в перечень демоправила.")
        if "age_min" in when and age < when["age_min"]:
            return _check("not_eligible", "Возраст по году достижения ниже границы демоправила.")
    missing = []
    if sex not in ("M", "F"):
        missing.append("sex")
    if age is None:
        missing.append("birth_date")
    if missing:
        return _check("needs_input", "Уточните пол и/или год рождения для проверки критериев.", *missing)
    if (rule["id"] == "scr_hepatitis" and patient.get("age_full") is not None
            and patient["age_full"] < when["age_min"] <= age):
        return _check("review", "Возраст по году достижения соответствует нижней границе правила гепатитов, "
                      "но полных 18 лет ещё нет. Источник не разрешает однозначно вопрос применения этой "
                      "границы до дня рождения; необходимо согласовать правило с врачом. Возрастной пакет "
                      "PRIME по-прежнему выбирается по полным годам.")
    return None


def _registration(patient, rule):
    registration = patient.get("registration", {})
    excluded = set(rule["when"]["not_registered"])
    confirmed = set(registration.get("confirmed_codes", [])) & excluded
    if confirmed:
        return _check("not_eligible", "Указан точный подтверждённый код динамического наблюдения: "
                      + ", ".join(sorted(confirmed)) + ". Это исключение предоставленного демоправила.")
    ambiguous = set(registration.get("ambiguous_codes", [])) & excluded
    if ambiguous:
        return _check("needs_input", "Экспорт анкеты преобразовал широкий ответ в код "
                      + ", ".join(sorted(ambiguous))
                      + ". Он не подтверждает диагноз или основание динамического наблюдения; уточните у врача.",
                      "registered")
    if (registration.get("known_negative") or registration.get("known_complete")
            or excluded <= set(registration.get("negative_codes", []))):
        return None
    conditions = patient.get("values", {}).get("conditions", []) or []
    broad = {BROAD_CONDITIONS.get(code) for code in conditions} & excluded
    if broad:
        return _check("needs_input", "Широкий ответ об истории здоровья не устанавливает диагноз. "
                      "Уточните, есть ли соответствующее динамическое наблюдение и его точное основание.",
                      "registered_on")
    return _check("needs_input", "Не указано, есть ли динамическое наблюдение по исключениям этого правила; "
                  "пропуск не означает отрицательный ответ.", "registered_on")


def _hepatitis_pregnancy(patient):
    if patient.get("pregnancy_applicable") is False:
        return None
    pregnant = patient.get("pregnant")
    if pregnant == "yes":
        return _check("not_eligible", "В предоставленном JSON у этого правила задано not_pregnant. "
                      "Ответ «да» не соответствует этому критерию; дальнейшие действия определяет врач.")
    if pregnant == "unsure":
        return _check("review", "Возможность беременности требует уточнения врачом для этого демоправила.", "pregnant")
    if pregnant != "no":
        return _check("needs_input", "Для этого правила нужен ответ о беременности, если вопрос применим.", "pregnant")
    return None


def _lung_risk(patient, rule):
    """Three-valued OR: one known true branch suffices; unknown is not zero."""
    values = patient.get("values", {})
    hazardous = values.get("hazardous_work_10y")
    if hazardous is True or hazardous == "yes":
        return None
    hazardous_known_no = hazardous is False or hazardous == "no"
    hazardous_unavailable = patient.get("answers", {}).get("hazardous_work_10y", {}).get("state") == "not_applicable"
    applicability_reason = (
        "Вопрос о вредной работе неприменим в текущей ветке анкеты по полному возрасту "
        f"({patient.get('age_full')}), тогда как скрининг использует возраст по году достижения "
        f"({patient.get('age_year')}). Правила применимости требуют проверки: скрытый ответ не используется, "
        "уточнение недоступного вопроса не запрашивается."
    )
    smoking = patient.get("smoking", {})
    conflicts = [question for question in smoking.get("questions", [])
                 if question.get("code") == "inconsistent_answers"]
    if conflicts:
        fields = list(dict.fromkeys(question["field"] for question in conflicts))
        reason = " ".join(question["message"] for question in conflicts)
        if hazardous_unavailable and not hazardous_known_no:
            return _check("review", reason + " " + applicability_reason, *fields)
        if not hazardous_known_no:
            fields.append("hazardous_work_10y")
        return _check("needs_input", reason, *fields)
    status, pack_years = smoking.get("status"), smoking.get("pack_years")
    quit_years = smoking.get("quit_years_ago")
    smoking_rule = rule["when"]["any_of"][0]
    smoking_false = status == "never"
    missing = []
    disputed_boundary = False
    if status in ("smokes", "quit", "reported_exposure"):
        cessation_required = status in {"quit", "reported_exposure"}
        # A known false component of this AND is enough even if the other
        # smoking component is missing. Do not ask irrelevant missing values.
        if pack_years is not None and pack_years < smoking_rule["pack_years_min"]:
            smoking_false = True
        elif cessation_required and quit_years is not None and quit_years > smoking_rule["quit_years_max"]:
            smoking_false = True
        else:
            if pack_years is None:
                if status == "reported_exposure":
                    missing.append("smoking.pack_years")
                else:
                    missing.extend(field for field in ("cigs_per_day", "smoke_years")
                                   if values.get(field) in (None, "", "unknown"))
                if not missing:
                    missing.append("smoking")  # Adapter could not reconcile supplied values.
            if cessation_required and quit_years is None:
                missing.append("smoking.quit_years_ago" if status == "reported_exposure" else "quit_years_ago")
            if not missing:
                if status == "smokes" or quit_years < smoking_rule["quit_years_max"]:
                    return None
                disputed_boundary = quit_years == smoking_rule["quit_years_max"]
    elif status != "never":
        missing.append("smoking.pack_years" if patient.get("input_format") == "clinic_v2" else "smoke_status")
        if patient.get("input_format") == "clinic_v2":
            missing.append("smoking.quit_years_ago")
    if disputed_boundary:
        return _check("review", "Конфликт источника на границе 15 лет после отказа: JSON quit_years_max=15 "
                      "допускает включение границы, а note и текст приказа № 75 говорят «менее 15 лет». "
                      "Выбор оператора требует проверки. Вредная работа не подтверждена как независимое основание."
                      + (" " + applicability_reason if hazardous_unavailable else ""))
    if smoking_false and hazardous_known_no:
        return _check("not_eligible", "По известным ответам не выполнена ни одна из двух ветвей: "
                      "критерий курения или вредной работы.")
    if not hazardous_known_no:
        if hazardous_unavailable:
            return _check("review", applicability_reason, *missing)
        missing.append("hazardous_work_10y")
    return _check("needs_input", "Недостаточно данных для условия «курение ИЛИ вредная работа». "
                  "Неизвестные стаж, количество сигарет или срок отказа не заменяются нулём.", *missing)


def _history(patient, rule):
    records = [entry for entry in patient.get("history", []) if entry.get("screening_id") == rule["id"]]
    history_field = "last_screening." + rule["id"] if patient.get("input_format") == "clinic_v2" else "last_screening"
    if not records:
        if patient.get("input_format") == "clinic_v2":
            return _check("needs_input", "Не сообщена история этой программы: уточните год прошлого "
                          "прохождения либо явный ответ «никогда». Пропуск не означает отсутствие обследования.",
                          history_field)
        return None
    if all(entry.get("performed_status") == "never" for entry in records):
        return None
    checkup_year = patient.get("context", {}).get("checkup_year")
    if checkup_year is None:
        return _check("needs_input", "Нужен год оценки для сопоставления с историей.", "checkup_year")
    years = [entry.get("performed_year") for entry in records if entry.get("date_precision") == "year"
             and isinstance(entry.get("performed_year"), int)]
    # A real supplied year takes precedence over a lossy two-year export; no
    # synthetic YEAR-1 is reconstructed here. The normalizer marks those ranges.
    if years:
        elapsed = checkup_year - max(years)
        if elapsed < 0:
            return _check("review", "Год прошлого скрининга позднее года оценки; уточните историю.", "last_screening")
        if elapsed < rule["repeat_years"]:
            return _check("not_eligible", "Указан прошлый скрининг: " + str(max(years))
                          + " год. По периодичности демоправила интервал в календарных годах ещё не истёк; "
                          "это не назначение даты повтора и не оценка результатов.")
        return None
    return _check("needs_input", "История содержит только диапазон «за последние два года» или неизвестную дату. "
                  "Уточните время обследования: диапазон не заменяется конкретным годом или датой повтора.",
                  history_field)


def evaluate_screening(patient, rules=None):
    """Return independent informational outcomes, without blocking PRIME."""
    if patient.get("input_format") == "legacy":
        return []
    document = _load("screening_rules.json") if rules is None else rules
    rule_list = document["screening"] if isinstance(document, dict) else document
    results = []
    for rule in rule_list:
        if rule["id"] not in RULE_IDS:
            raise ValueError("Неизвестное правило скрининга: " + rule["id"])
        demographic = _demographics(patient, rule)
        checks = [demographic] if demographic else [_registration(patient, rule)]
        if not demographic:
            if rule["id"] == "scr_hepatitis":
                checks.append(_hepatitis_pregnancy(patient))
            if rule["id"] == "scr_lung":
                checks.append(_lung_risk(patient, rule))
            checks.append(_history(patient, rule))
        checks = [check for check in checks if check]
        priority = {"not_eligible": 0, "review": 1, "needs_input": 2}
        checks.sort(key=lambda check: priority[check["outcome"]])
        if checks:
            outcome = checks[0]["outcome"]
            relevant = [check for check in checks if check["outcome"] == outcome]
            reason = " ".join(check["reason"] for check in relevant)
            missing = list(dict.fromkeys(field for check in relevant for field in check["missing_fields"]))
        else:
            outcome, missing = "candidate", []
            reason = "Подходит по указанным критериям предоставленного демоправила. Условия и доступность уточняются в поликлинике."
        limits = ["Это не подтверждение права на бесплатную услугу, запись или персональное назначение повтора."]
        if not any(entry.get("screening_id") == rule["id"] for entry in patient.get("history", [])):
            limits.append("Сведения о прошлом прохождении не предоставлены; фактическая периодичность не установлена.")
        if rule["id"] == "scr_lung":
            limits.append("Соответствие профессии перечню вредных работ по приказу № 170 проверяется отдельно.")
        results.append({
            "rule_id": rule["id"], "name": rule["name"], "outcome": outcome,
            "reason": reason, "missing_fields": missing, "source": rule["source"],
            "source_path": "reference/df733c4/spec/rules.json:screening",
            "source_sha": document.get("source_sha") if isinstance(document, dict) else None,
            "validation_status": "demo_unvalidated", "medical_validated": False,
            "limitations": limits,
        })
    return results


def attach_screening_links(items, screening, links=None):
    """Add explicit correspondence metadata to a copy, preserving clinical flags."""
    document = _load("screening_links.json") if links is None else links
    link_list = document["links"] if isinstance(document, dict) else document
    outcomes = {result["rule_id"]: result["outcome"] for result in screening}
    result = deepcopy(items)
    for item in result:
        item["screening_matches"] = [
            {"screening_id": link["screening_id"], "match_degree": link["match_degree"],
             "outcome": outcomes[link["screening_id"]], "explanation": link["explanation"]}
            for link in link_list if link["procedure_id"] == item["procedure_id"]
            and link["screening_id"] in outcomes
        ]
    return result
