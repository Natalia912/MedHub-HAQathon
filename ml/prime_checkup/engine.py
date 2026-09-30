"""Процедурный демонстрационный конструктор, без медицинских назначений."""
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from .schemas import PlanResult, invalid_result
from .intake import normalize_input
from .screening import evaluate_screening, attach_screening_links
from .scheduler import schedule_visit

DATA = Path(__file__).parent / "data"


class DataError(ValueError):
    def __init__(self, field, message):
        self.error = {"scope": "data", "field": field, "code": "INVALID_DATA", "message": message}


def load_data(filename):
    try:
        return json.loads((DATA / filename).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DataError(filename, "Не удалось прочитать JSON-данные демо.") from exc


def validate_catalog(catalog, rules):
    """Reject broken references before selecting or merging any composition."""
    if not isinstance(catalog, dict) or not isinstance(catalog.get("procedures"), list):
        raise DataError("catalog.procedures", "Каталог должен содержать список процедур.")
    by_id = {}
    for proc in catalog["procedures"]:
        if not isinstance(proc, dict) or not all(key in proc for key in ("id", "name", "is_group", "source", "validation_status", "after_results")):
            raise DataError("catalog.procedures", "У позиции каталога отсутствуют обязательные данные.")
        pid = proc["id"]
        if not isinstance(pid, str) or not pid or pid in by_id:
            raise DataError("catalog.procedures.id", "ID процедур должны быть непустыми и уникальными.")
        if not isinstance(proc["name"], str) or not proc["name"] or type(proc["is_group"]) is not bool or type(proc["after_results"]) is not bool:
            raise DataError(f"procedures.{pid}", "Некорректные название или признаки позиции каталога.")
        if proc["validation_status"] != "demo_unvalidated":
            raise DataError(f"procedures.{pid}.validation_status", "Демо не имеет медицинского подтверждения.")
        if type(proc.get("conditional", False)) is not bool or not isinstance(proc.get("tags", []), list) or any(not isinstance(tag, str) for tag in proc.get("tags", [])):
            raise DataError(f"procedures.{pid}", "Повреждены признаки условной позиции или явные теги процедуры.")
        by_id[pid] = proc
    packages = catalog.get("packages")
    if not isinstance(packages, list):
        raise DataError("catalog.packages", "Отсутствует список пакетов.")
    seen = set()
    for package in packages:
        if not isinstance(package, dict) or not all(key in package for key in ("id", "name", "when", "price", "source", "required_ids")):
            raise DataError("catalog.packages", "Повреждены обязательные данные пакета.")
        if not isinstance(package["id"], str) or package["id"] in seen:
            raise DataError("catalog.packages.id", "ID пакетов должны быть уникальными строками.")
        seen.add(package["id"])
        bounds = package["when"]
        if not isinstance(bounds, dict) or any(type(bounds.get(k)) is not int for k in ("age_min", "age_max")) or bounds["age_min"] > bounds["age_max"]:
            raise DataError(f"packages.{package['id']}.when", "Некорректный возрастной диапазон пакета.")
        for key in ("required_ids", "female_ids", "male_ids", "extended_ids"):
            check_ids(package.get(key, []), by_id, f"packages.{package['id']}.{key}")
    for pid, proc in by_id.items():
        check_ids(proc.get("conflicts_with", []), by_id, f"procedures.{pid}.conflicts_with")
        check_ids(proc.get("action_ids", []), by_id, f"procedures.{pid}.action_ids")
        for action_id in proc.get("action_ids", []):
            if action_id == pid or by_id[action_id].get("action_ids") or by_id[action_id].get("parent_procedure_id") != pid:
                raise DataError(f"procedures.{pid}.action_ids", "Некорректная связь услуги и её действий.")
    if not isinstance(rules, dict) or not isinstance(rules.get("rules"), list):
        raise DataError("rules", "Отсутствуют демонстрационные адаптации правил.")
    expected = {"cmp_fatigue": "highlight", "cmp_family_crc": "note", "cmp_chest_pain": "require_review"}
    found = {}
    for rule in rules["rules"]:
        if not isinstance(rule, dict) or not isinstance(rule.get("id"), str) or rule["id"] not in expected or rule["id"] in found:
            raise DataError("rules", "Неизвестное или повторное правило; активны только три демо-адаптации.")
        rid = rule["id"]
        if rule.get("action") != expected[rid] or rule.get("needs_doctor_validation") is not True or rule.get("validation_status") != "demo_unvalidated" or rule.get("source_rule_id") != rid:
            raise DataError(f"rules.{rid}", "Нарушены границы неподтверждённой адаптации правила.")
        if not isinstance(rule.get("explanation"), str) or not isinstance(rule.get("source"), str):
            raise DataError(f"rules.{rid}", "У правила отсутствуют объяснение или источник.")
        check_ids(rule.get("procedure_ids", []), by_id, f"rules.{rid}.procedure_ids")
        found[rid] = rule
    if set(found) != set(expected):
        raise DataError("rules", "Нужны все три демонстрационные адаптации правил.")
    return by_id, found


def check_ids(ids, by_id, field):
    if not isinstance(ids, list) or any(not isinstance(pid, str) or pid not in by_id for pid in ids):
        raise DataError(field, "Обнаружена ссылка на неизвестный ID или неверный список ссылок.")


def rule_trace(rule, outcome, explanation=None):
    return {"rule_id": rule["id"], "source_rule_id": rule["source_rule_id"],
            "outcome": outcome, "action": rule["action"],
            "explanation": explanation or rule["explanation"], "source": rule["source"],
            "validation_status": rule["validation_status"],
            "needs_doctor_validation": rule["needs_doctor_validation"], "medical_validated": False}


def reason_for(rule):
    return {"rule_id": rule["id"], "source_rule_id": rule.get("source_rule_id", rule["id"]),
            "explanation": rule["explanation"], "source": rule["source"],
            "validation_status": "demo_unvalidated", "needs_doctor_validation": True,
            "medical_validated": False}


def require_review(result, rule):
    result["status"] = "review"
    note(result, rule)


def require_input(result, field, message):
    result["status"] = "needs_input"
    result["questions"].append({"field": field, "message": message})


def note(result, rule):
    result["warnings"].append({"code": rule["id"], "message": rule["explanation"], **reason_for(rule)})


def make_item(proc, reason):
    return {"procedure_id": proc["id"], "name": proc["name"], "is_group": proc.get("is_group", False),
            "after_results": proc.get("after_results", False), "source": proc["source"],
            "validation_status": "demo_unvalidated", "medical_validated": False,
            "reasons": [deepcopy(reason)], "highlighted": False,
            "conditional": proc.get("conditional", False), "required": not proc.get("conditional", False),
            "tags": list(proc.get("tags", [])), "action_ids": list(proc.get("action_ids", [])),
            "actions": [], "clinical_flags": [], "screening_matches": []}


def add(items, procedure_id, by_id, reason):
    """Used only by synthetic A–D tests; no real complaint rule calls add."""
    check_ids([procedure_id], by_id, "add.procedure_id")
    items.append(make_item(by_id[procedure_id], reason))


def merge_same_ids(items):
    merged = {}
    for item in items:
        pid = item["procedure_id"]
        if pid not in merged:
            merged[pid] = deepcopy(item)
            continue
        existing = merged[pid]
        for key in ("name", "is_group", "after_results", "source", "validation_status"):
            if existing.get(key) != item.get(key):
                raise DataError(f"items.{pid}", "Конфликтующие определения одного обязательного действия.")
        for reason in item["reasons"]:
            if reason not in existing["reasons"]:
                existing["reasons"].append(deepcopy(reason))
        existing["highlighted"] = existing["highlighted"] or item.get("highlighted", False)
    return list(merged.values())


def highlight(items, rule):
    found = []
    for item in items:
        if item["procedure_id"] in rule.get("procedure_ids", []):
            item["highlighted"] = True
            item["reasons"].append(reason_for(rule))
            found.append(item["procedure_id"])
    return found, [pid for pid in rule.get("procedure_ids", []) if pid not in found]


def evaluate_blocking_rules(patient, result, rule_map):
    rule = rule_map["cmp_chest_pain"]
    matched = "chest_pain" in patient.complaints
    outcome = "matched" if matched else "unknown" if patient.complaints_state == "unknown" else "not_matched"
    result["trace"].append(rule_trace(rule, outcome))
    if matched:
        require_review(result, rule)
        for rid in ("cmp_fatigue", "cmp_family_crc"):
            result["trace"].append(rule_trace(rule_map[rid], "skipped", "Подбор остановлен блокирующим правилом."))
    return matched


def find_missing_answers(patient, result):
    questions = {"sex": "Уточните пол для выбора состава каталога.",
                 "complaints_state": "Уточните, есть ли жалобы из списка.",
                 "family_crc": "Уточните семейный анамнез по раку кишечника."}
    for field, message in questions.items():
        if getattr(patient, field) == "unknown":
            require_input(result, field, message)
    return bool(result["questions"])


def choose_package(patient, catalog, result):
    candidates = []
    for package in catalog["packages"]:
        bounds = package["when"]
        matched = bounds["age_min"] <= patient.age <= bounds["age_max"]
        result["trace"].append({"rule_id": package["id"], "outcome": "matched" if matched else "not_matched",
                                "action": "choose_package", "source": package["source"],
                                "validation_status": "demo_unvalidated",
                                "explanation": f"Полный возраст {patient.age}; диапазон каталога {bounds['age_min']}–{bounds['age_max']}."})
        if matched:
            candidates.append(package)
    if len(candidates) != 1:
        result["status"] = "review"
        result["warnings"].append({"code": "PACKAGE_SELECTION", "message": "Нет подходящего шаблона." if not candidates else "Подходят несколько шаблонов; правило выбора отсутствует."})
        return None
    return candidates[0]


def apply_rules(patient, result, rule_map):
    for rid in ("cmp_fatigue", "cmp_family_crc"):
        rule = rule_map[rid]
        matched = "fatigue" in patient.complaints if rid == "cmp_fatigue" else patient.family_crc == "yes"
        trace = rule_trace(rule, "matched" if matched else "not_matched")
        if matched and rid == "cmp_fatigue":
            trace["highlighted_ids"], trace["not_found_ids"] = highlight(result["items"], rule)
        elif matched:
            note(result, rule)
        result["trace"].append(trace)


def validate_composition(items, required_ids, by_id):
    ids = [item["procedure_id"] for item in items]
    check_ids(ids, by_id, "items")
    if not set(required_ids).issubset(ids) or len(ids) != len(set(ids)):
        raise DataError("items", "Нарушена полнота или уникальность обязательного состава.")
    for pid in ids:
        if set(by_id[pid].get("conflicts_with", [])) & set(ids):
            raise DataError(f"items.{pid}", "В составе есть конфликтующие обязательные действия.")


def make_schedule_fixture(items, package_id, slots, availability):
    """All timing is in a separate technical fixture, never inferred from medicine."""
    items = expand_actions(items)
    if not isinstance(slots, dict):
        raise DataError("slots", "Повреждены данные расписания.")
    metadata = slots.get("procedures", {})
    variants = slots.get("slots", {})
    if not isinstance(metadata, dict) or not isinstance(variants, dict):
        raise DataError("slots", "Длительности и варианты слотов должны быть словарями.")
    variant = variants.get(availability, {})
    if not isinstance(variant, dict):
        raise DataError("slots.slots", "Вариант слотов должен быть словарём.")
    selected = {item["procedure_id"] for item in items}
    day_ids = {item["procedure_id"] for item in items if not item["after_results"]}
    for pid in sorted(selected):
        if not isinstance(metadata.get(pid, {}), dict):
            raise DataError(f"procedures.{pid}", "Повреждены технические данные процедуры.")
    # Inspect even postponed nodes so an unknown reference or a cycle cannot disappear.
    graph = {}
    for item in items:
        pid = item["procedure_id"]
        meta = metadata.get(pid, {})
        if not isinstance(meta, dict):
            raise DataError(f"procedures.{pid}", "Повреждены технические данные процедуры.")
        predecessors = meta.get("predecessors", [])
        check_ids(predecessors, selected, f"procedures.{pid}.predecessors")
        category = meta.get("category")
        if category is not None and (type(category) is not int or category not in range(-1, 6)):
            raise DataError(f"procedures.{pid}.category", "Неизвестная категория маршрута.")
        graph[pid] = list(predecessors)
        if category is not None:
            graph[pid] += [other for other in sorted(selected) if type(metadata.get(other, {}).get("category")) is int and metadata[other]["category"] < category]
    visiting, visited = set(), set()

    def visit(pid):
        if pid in visiting:
            raise DataError("procedures.predecessors", "Цикл зависимостей обязательных действий.")
        if pid in visited:
            return
        visiting.add(pid)
        for other in graph[pid]:
            visit(other)
        visiting.remove(pid)
        visited.add(pid)

    for pid in sorted(selected):
        visit(pid)
    procedures = []
    for item in items:
        pid = item["procedure_id"]
        if pid not in day_ids:
            continue
        if any(pred not in day_ids for pred in graph[pid]):
            raise DataError(f"procedures.{pid}.predecessors", "Действие дня зависит от ещё не готовых результатов.")
        proc = {"id": pid, "name": item["name"]}
        meta = metadata.get(pid, {})
        for key in ("duration_minutes", "resources", "predecessors"):
            if key in meta:
                proc[key] = deepcopy(meta[key])
        # Missing category is schedule data, not permission to ignore category order.
        if "predecessors" in meta:
            proc["predecessors"] = sorted(set(graph[pid]))
        if pid in variant:
            proc["slots"] = deepcopy(variant[pid])
        procedures.append(proc)
    fixture = {"id": "prime-technical-day", "package": {"id": package_id, "required_ids": sorted(day_ids)}, "procedures": procedures}
    fixture["missing_categories"] = [pid for pid in sorted(day_ids) if metadata.get(pid, {}).get("category") is None]
    for key in ("patient_window", "transition_minutes", "resources", "resource_busy"):
        if key in slots:
            fixture[key] = deepcopy(slots[key])
    return fixture


def expand_actions(items):
    """One catalog service can have distinct initial and after-results actions."""
    return [action for item in items for action in (item.get("actions") or [item])]


def link_actions(items, by_id):
    for item in items:
        for action_id in item["action_ids"]:
            action = make_item(by_id[action_id], item["reasons"][0])
            action["reasons"] = deepcopy(item["reasons"])
            action["parent_procedure_id"] = item["procedure_id"]
            item["actions"].append(action)


def evaluate_urgent(patient, result):
    urgent = patient.get("urgent")
    source = "reference/df733c4/app/config/fields.py: urgent; spec/rules.json:cmp_chest_pain"
    explanation = {
        "chest_pain": "Боль или давление в груди: подбор остановлен, требуется обращение к врачу; при острой боли — 103 (исходное правило клиники).",
        "dyspnea": "Сильная одышка: подбор остановлен. По материалам анкеты нужна помощь врача сегодня.",
        "stroke_signs": "Внезапная слабость в руке или ноге, трудно говорить: подбор остановлен. По материалам анкеты нужна помощь врача сегодня.",
        "other_now": "Другое, что беспокоит сейчас: подбор остановлен; обратитесь к врачу для обсуждения состояния.",
    }
    matched = urgent in explanation
    result["trace"].append({"rule_id": "clinic_urgent", "outcome": "matched" if matched else "not_matched" if urgent == "none" else "unknown", "action": "require_review", "source": source, "validation_status": "demo_unvalidated", "explanation": explanation.get(urgent, "Проверка ответа о текущем самочувствии.")})
    if matched:
        result["status"] = "review"
        result["warnings"].append({"code": "URGENT", "message": explanation[urgent], "source": source, "validation_status": "demo_unvalidated"})
        result["schedule"]["reason"] = "Подбор остановлен по ответу о текущем самочувствии."
        return True
    if urgent != "none":
        require_input(result, "urgent", "Уточните, беспокоит ли что-то прямо сейчас; отсутствие ответа не означает «нет».")
        return True
    return False


def clinic_input_questions(patient, result):
    for question in patient.get("questions", []):
        require_input(result, question["field"], question.get("message", question.get("reason", "Уточните противоречивый ответ.")))
    if patient.get("age_full") is None:
        require_input(result, "birth_date", "Укажите полную дату рождения для возраста на дату оценки.")
    if patient.get("sex") not in ("F", "M"):
        require_input(result, "sex", "Уточните пол для выбора состава каталога.")
    return bool(result["questions"])


def apply_clinic_rules(patient, result, rule_map):
    result["trace"].append(rule_trace(rule_map["cmp_fatigue"], "skipped", "Новая анкета не спрашивает fatigue; правило действует только в техническом legacy-режиме."))
    family = patient.get("values", {}).get("family_history") or []
    matched = "colorectal_cancer" in family
    rule = rule_map["cmp_family_crc"]
    state = patient.get("answers", {}).get("family_history", {}).get("state")
    result["trace"].append(rule_trace(rule, "matched" if matched else "unknown" if state in ("unknown", "unanswered") else "not_matched"))
    if matched:
        note(result, rule)
    result["proposed_extras"] = clinic_proposed_extras(patient, result["items"])


def clinic_proposed_extras(patient, items):
    """Discussion suggestions are relative to the actual composition, never additions."""
    extras = []
    present = {item["procedure_id"] for item in items}
    for field, specialist_id, name in (("discharge", "prime_gynecology_consult", "Консультация гинеколога"), ("dysuria", "prime_urology_consult", "Консультация уролога")):
        if patient.get("values", {}).get(field) != "yes":
            continue
        reason = "Ответ «Да» на вопрос анкеты; обсудите обследование с врачом. Это предложение, не обязательная процедура пакета."
        extras.append({"procedure_id": None, "name": "Обследование на половые инфекции", "reason": reason, "note": "Точный состав назначает врач", "source": f"reference/df733c4/ml/README.md:{field}", "validation_status": "demo_unvalidated", "scheduled": False})
        if specialist_id not in present:
            extras.append({"procedure_id": specialist_id, "name": name, "reason": reason, "source": f"reference/df733c4/ml/README.md:{field}", "validation_status": "demo_unvalidated", "scheduled": False})
    return extras


def evaluate_composition_review(patient, result):
    for item in result["items"]:
        if item["conditional"]:
            item["clinical_flags"].append({"code": "INDICATION_REQUIRED", "message": "В источнике: по показаниям. Необходимость включения определяет врач; автоматически не запланировано.", "source": item["source"]})
        if patient["input_format"] != "legacy" and patient.get("pregnancy_applicable") is True and "pregnancy_review" in item["tags"]:
            pregnancy = patient.get("pregnant")
            if pregnancy != "no":
                missing = pregnancy not in ("yes", "unsure")
                item["clinical_flags"].append({"code": "PREGNANCY_UNKNOWN" if missing else "PREGNANCY_REVIEW", "message": "Уточните ответ о беременности до согласования этой позиции." if missing else "По демонстрационному правилу анкеты требуется решение врача; КТ/маммография не включаются в автоматически согласованный маршрут.", "source": "reference/df733c4/app/config/fields.py:pregnant"})
                if missing and not any(q["field"] == "pregnant" for q in result["questions"]):
                    result["questions"].append({"field": "pregnant", "message": "В пакете есть услуги, зависящие от ответа о беременности. Уточните ответ."})
        # S19 authorizes a preparation review, not a medication regimen or an
        # absolute contraindication. The restriction belongs to this service;
        # rebuilding a custom selection without it removes only these flags.
        if patient["input_format"] != "legacy" and item["procedure_id"] == "prime_endoscopy_group":
            values = patient.get("values", {})
            preparation = (
                ("blood_thinners", "yes", "PREPARATION_MEDICATION_REVIEW", "pr_thinners", "medications",
                 "Сообщён приём препарата, разжижающего кровь. Уточните у врача название, дозу/режим и подготовку к выбранному обследованию; самостоятельно схему приёма не меняйте."),
                ("companion", "no", "PREPARATION_RETURN_REVIEW", "pr_anesthesia", "companion",
                 "Сообщено, что сопровождающего нет. Обсудите с врачом условия возвращения домой после анестезии; автоматическое согласование этой позиции не выполнено."),
            )
            for field, value, code, rule_id, question_field, message in preparation:
                if values.get(field) != value:
                    continue
                source = "https://github.com/Natalia912/MedHub-HAQathon/blob/744d7f79e6872a31572dda9d75269a8a8b7bcd4a/spec/rules.json"
                item["clinical_flags"].append({"code": code, "message": message, "source": source,
                                               "source_rule_id": rule_id, "validation_status": "demo_unvalidated",
                                               "source_path": "prep_catalog." + rule_id,
                                               "basis": "Scenarios.docx 1.1:S19; только согласование подготовки"})
                if not any(q["field"] == question_field for q in result["questions"]):
                    result["questions"].append({"field": question_field, "message": message})
    flagged = [item for item in result["items"] if item["clinical_flags"]]
    for rule_id, codes, source in (("catalog_indications", {"INDICATION_REQUIRED"}, "reference/df733c4/spec/rules.json:packages"), ("clinic_pregnancy", {"PREGNANCY_UNKNOWN", "PREGNANCY_REVIEW"}, "reference/df733c4/app/config/fields.py:pregnant"), ("clinic_preparation", {"PREPARATION_MEDICATION_REVIEW", "PREPARATION_RETURN_REVIEW"}, "Scenarios.docx 1.1:S19; 744d7f7/spec/rules.json:prep_catalog.pr_thinners/pr_anesthesia")):
        matched = [flag for item in flagged for flag in item["clinical_flags"] if flag["code"] in codes]
        outcome = "unknown" if any(flag["code"] == "PREGNANCY_UNKNOWN" for flag in matched) else "matched" if matched else "not_matched"
        if rule_id == "clinic_pregnancy" and (patient["input_format"] == "legacy" or patient.get("pregnancy_applicable") is False):
            outcome = "skipped"
        result["trace"].append({"rule_id": rule_id, "outcome": outcome, "action": "require_review", "source": source, "validation_status": "demo_unvalidated", "explanation": matched[0]["message"] if matched else "Ветка проверена; дополнительных ограничений состава по этому правилу не установлено."})
    if flagged:
        result["status"] = "review"
        result["package"]["preliminary"] = True
        result["schedule"]["reason"] = "Предварительный состав требует решения врача или уточнения отмеченных позиций; расписание не запускалось."
        result["warnings"].append({"code": "PRELIMINARY", "message": result["schedule"]["reason"]})
    return bool(flagged)


def recommend_base(raw_input, catalog=None, rules=None, slots=None):
    """Shared clinical/catalog calculation. This stage never searches for slots."""
    normalized, errors = normalize_input(raw_input)
    if errors:
        return invalid_result(errors)
    result = PlanResult().model_dump(mode="json")
    result["versions"]["engine"] = "demo-3"
    result["input_context"] = {**deepcopy(normalized.get("context", {})), "input_format": normalized["input_format"], "age_full": normalized.get("age_full"), "age_year": normalized.get("age_year"), "answers": deepcopy(normalized.get("answers", {})), "registration": deepcopy(normalized.get("registration", {})), "smoking": deepcopy(normalized.get("smoking", {})), "history": deepcopy(normalized.get("history", []))}
    result["doctor_summary"] = deepcopy(normalized.get("doctor_summary", []))
    result["warnings"].extend(deepcopy(normalized.get("warnings", [])))
    legacy = normalized["input_format"] == "legacy"
    patient = SimpleNamespace(**normalized)
    if not legacy and evaluate_urgent(normalized, result):
        return result
    if not legacy and clinic_input_questions(normalized, result):
        return result
    try:
        catalog = load_data("demo_catalog.json") if catalog is None else deepcopy(catalog)
        rules = load_data("demo_rules.json") if rules is None else deepcopy(rules)
        slots = load_data("prime_slots.json") if slots is None else deepcopy(slots)
        by_id, rule_map = validate_catalog(catalog, rules)
        result["versions"]["source_sha"] = catalog.get("source_sha")
        for name, data in (("catalog", catalog), ("rules", rules), ("slots", slots)):
            if not isinstance(data, dict) or not isinstance(data.get("version"), str):
                raise DataError(f"{name}.version", "Не указана версия данных.")
            result["versions"][name] = data["version"]
        if legacy and evaluate_blocking_rules(patient, result, rule_map):
            return result
        if legacy and find_missing_answers(patient, result):
            for rid, unknown in (("cmp_fatigue", patient.complaints_state == "unknown"), ("cmp_family_crc", patient.family_crc == "unknown")):
                result["trace"].append(rule_trace(rule_map[rid], "unknown" if unknown else "skipped", "Нужны ответы до сборки состава."))
            return result
        package = choose_package(patient, catalog, result)
        if package is None:
            return result
        result["package"] = {key: deepcopy(package[key]) for key in ("id", "name", "price", "source")}
        suffix = "f" if patient.sex == "F" else "m"
        result["package"]["name"] = package.get("name_mini") if package["id"] == "prime_child" else package.get(f"name_{suffix}", package["name"])
        result["package"]["name"] = result["package"]["name"] or package["name"]
        result["package"].update(title="Кандидат по каталогу PRIME", reason=f"Полный возраст {patient.age}: диапазон {package['when']['age_min']}–{package['when']['age_max']} лет; дата визита {patient.visit_date}; пол {patient.sex}.", url=package.get("url_mini") if package["id"] == "prime_child" else package.get(f"url_{suffix}"), preliminary=False)
        if package["id"] == "prime_child" and package.get("extended_ids"):
            result["alternatives"].append({"name": package.get("name_extended", "Детский расширенный вариант"), "procedure_ids": list(package["extended_ids"]), "items": [{"procedure_id": pid, "name": by_id[pid]["name"]} for pid in package["extended_ids"]], "url": package.get("url_extended"), "reason": "Альтернатива для обсуждения с педиатром; в выбранный мини-пакет и маршрут не добавлена."})
        required_ids = list(package["required_ids"])
        supplement = package.get("female_ids" if patient.sex == "F" else "male_ids", [])
        for ids, basis in ((required_ids, "основной состав"), (supplement, "дополнение для выбранного пола")):
            for pid in ids:
                reason = {"rule_id": package["id"], "explanation": f"Входит в {basis} пакета «{package['name']}».",
                          "source": package["source"], "validation_status": "demo_unvalidated"}
                result["items"].append(make_item(by_id[pid], reason))
        if legacy:
            apply_rules(patient, result, rule_map)
            result["warnings"].append({"code": "LEGACY_MODE", "message": "Короткий технический legacy-профиль: новая анкета не заполнена, беременность и другие новые ответы не предполагаются."})
        else:
            apply_clinic_rules(normalized, result, rule_map)
        result["items"] = merge_same_ids(result["items"])
        validate_composition(result["items"], required_ids + supplement, by_id)
        link_actions(result["items"], by_id)
        actions = expand_actions(result["items"])
        validate_composition(actions, [item["procedure_id"] for item in actions], by_id)
        if not legacy:
            result["screening"] = evaluate_screening(normalized)
            result["items"] = attach_screening_links(result["items"], result["screening"])
            result["versions"]["screening"] = "demo-2"
        result["health_card"] = [{"procedure_id": item["procedure_id"], "name": item["name"], "status": "не пройдено", "result": "нет данных"} for item in result["items"]]
        result["reminder_draft"]["basis"] = "требует назначения врача"
        after_results = [{"procedure_id": item["procedure_id"], "parent_procedure_id": item.get("parent_procedure_id"), "name": item["name"], "reason": "после готовности результатов"} for item in expand_actions(result["items"]) if item["after_results"]]
        result["schedule"]["after_results"] = after_results
        result["warnings"] += [
            {"code": "UNVALIDATED", "message": "Медицинские правила не подтверждены врачом. Это демонстрация механики каталога."},
            {"code": "AGE_40", "message": "Граница 40 лет импортирована из spec/rules.json и требует проверки."},
            {"code": "TEST_SCHEDULE", "message": "Длительности, ресурсы, слоты и нулевой буфер переходов — тестовые. Порядок категорий требует проверки клиникой."},
        ]
        if any(item["is_group"] for item in result["items"]):
            result["warnings"].append({"code": "OPAQUE_GROUPS", "message": "Состав каталожных групп не раскрыт. Пересечение с отдельными анализами неизвестно."})
        if evaluate_composition_review(normalized, result):
            return result
    except DataError as exc:
        result["status"] = "invalid"
        result["errors"] = [exc.error]
        result["schedule"] = {"status": "not_run", "route": [], "after_results": [], "reason": "Ошибка данных; маршрут не построен."}
    return result


def build_plan(raw_input, catalog=None, rules=None, slots=None):
    """Compatibility endpoint: the same recommendation followed by its preset schedule."""
    result = recommend_base(raw_input, catalog=catalog, rules=rules, slots=slots)
    if result["status"] != "ready" or not result["package"]:
        return result
    after_results = result["schedule"]["after_results"]
    try:
        slots = load_data("prime_slots.json") if slots is None else deepcopy(slots)
        fixture = make_schedule_fixture(result["items"], result["package"]["id"], slots, result["input_context"]["availability"])
        result["schedule"] = schedule_visit(fixture)
        if fixture["missing_categories"] and result["schedule"]["status"] != "not_run":
            result["schedule"].update(status="needs_data", route=[], reason="Не хватает обязательных данных расписания.")
            result["schedule"]["errors"] += [{"scope": "data", "field": f"procedures.{pid}.category", "code": "MISSING_DATA", "message": "Не указана тестовая категория маршрута."} for pid in fixture["missing_categories"]]
        if result["schedule"]["status"] == "not_run" and result["schedule"].get("errors"):
            result["status"] = "invalid"
            result["errors"] = result["schedule"]["errors"]
        result["schedule"]["after_results"] = after_results
    except DataError as exc:
        result["status"] = "invalid"
        result["errors"] = [exc.error]
        result["schedule"] = {"status": "not_run", "route": [], "after_results": [], "reason": "Ошибка данных; маршрут не построен."}
    return result
