"""Two stateless stages over the existing recommendation and scheduling functions."""
from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError

from .choice_catalog import catalog_for_patient, enrich_screening
from .choice_route import plan_actions
from .engine import (DataError, clinic_proposed_extras, evaluate_composition_review, expand_actions, link_actions,
                        load_data, make_item, recommend_base, validate_catalog, validate_composition)
from .intake import normalize_input
from .schemas import invalid_result, validation_errors
from .screening import attach_screening_links

CONTEXT_FIELDS = {"as_of_date", "checkup_year", "visit_date", "availability"}
NEXT_VISIT = {"kind": "results_review", "date": None, "year": None,
              "status": "requires_clinician", "basis": None,
              "reason": "Дату определят после готовности результатов и решения врача"}


class SelectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    mode: Literal["preset", "custom"]
    base_package_id: StrictStr = Field(min_length=1)
    variant_id: StrictStr | None = None
    selected_procedure_ids: list[StrictStr] | None = None
    catalog_version: StrictStr = Field(min_length=1)


def input_error(field, message, code="invalid_selection"):
    return {"scope": "input", "field": field, "code": code, "message": message}


def public_error(errors, stage):
    return public_result(invalid_result(errors), stage)


def response_http_status(result):
    if any(error.get("code") == "catalog_changed" for error in result.get("errors", [])):
        return 409
    return 422 if result["status"] == "invalid" else 200


def merge_context(patient, context):
    if not isinstance(patient, dict):
        return None, [input_error("patient", "Ожидается объект исходной анкеты.", "model_type")]
    if context is None:
        context = {}
    if not isinstance(context, dict):
        return None, [input_error("context", "Технический контекст должен быть объектом.", "dict_type")]
    errors = [input_error(f"context.{key}", "Неизвестный параметр технического контекста.", "extra_forbidden") for key in context if key not in CONTEXT_FIELDS]
    for key in ("as_of_date", "checkup_year"):
        if key in context and key in patient and context[key] != patient[key]:
            errors.append(input_error(f"context.{key}", "Дата/год оценки противоречит значению в исходной анкете.", "context_conflict"))
    # A new visit and slot variant are explicitly chosen technical settings.
    # Medical answers and evaluation dates are never silently overridden.
    return {**deepcopy(patient), **deepcopy(context)}, errors


def public_item(item):
    value = deepcopy(item)
    value["why"] = " ".join(reason["explanation"] for reason in value["reasons"])
    value["rule_id"] = value["reasons"][0]["rule_id"] if value["reasons"] else None
    value["payment"] = "paid_prime"
    value["requires_review"] = bool(value.get("clinical_flags"))
    for action in value.get("actions", []):
        action["action_id"] = action["procedure_id"]
        action["procedure_id"] = value["procedure_id"]
    return value


def public_result(result, stage):
    result["stage"] = stage
    result["versions"]["engine"] = "demo-3"
    result["model_version"] = "procedural-demo-3"
    result["age_full"] = result.get("input_context", {}).get("age_full")
    result["age_year"] = result.get("input_context", {}).get("age_year")
    result["context"] = {key: value for key, value in result.get("input_context", {}).items() if key in CONTEXT_FIELDS and value is not None}
    for key in ("catalog", "package_options", "route", "after_results", "next_visit", "selected_items", "added_items", "removed_recommended_items", "unresolved_items"):
        result.setdefault(key, [])
    result.setdefault("route_status", "not_run")
    result.setdefault("total_price", None)
    result.setdefault("price_text", "цена не указана")
    result["summary"] = {"prime_count": len(result["items"]), "screening_candidate_count": sum(row["outcome"] == "candidate" for row in result["screening"])}
    result["not_eligible"] = [{"rule_id": row["rule_id"], "why": row["reason"], "source": row["source"]} for row in result["screening"] if row["outcome"] == "not_eligible"]
    result["red_flags"] = [deepcopy(warning) for warning in result["warnings"] if warning.get("code") in ("URGENT", "cmp_chest_pain")]
    result["reasons"] = [{"procedure_id": item["procedure_id"], **deepcopy(reason)} for item in result["items"] for reason in item["reasons"]]
    result["needs_doctor_review"] = True
    result["error"] = deepcopy(result["errors"][0]) if result["errors"] else None
    return result


def recommendation_catalog_flags(patient, entries, by_id):
    """Expose the same service restrictions in the editor, without applying them globally."""
    temporary = {"items": [], "status": "ready", "package": {}, "questions": [], "warnings": [], "trace": [], "schedule": {}}
    for entry in entries:
        item = make_item(by_id[entry["procedure_id"]], {"rule_id": "catalog", "explanation": "Позиция каталога PRIME", "source": entry["source"]})
        item["clinical_flags"] = deepcopy(entry.get("applicability_flags", []))
        temporary["items"].append(item)
    evaluate_composition_review(patient, temporary)
    for entry, item in zip(entries, temporary["items"]):
        entry["clinical_flags"] = item["clinical_flags"]
        entry["requires_review"] = bool(item["clinical_flags"])


def recommend(patient, context=None, *, catalog=None, rules=None, slots=None):
    raw, errors = merge_context(patient, context)
    if errors:
        return public_error(errors, "recommendation")
    result = recommend_base(raw, catalog=catalog, rules=rules, slots=slots)
    result["health_card"] = []
    result["schedule"]["after_results"] = []
    if result["status"] == "invalid" or not result["package"]:
        return public_result(result, "recommendation")
    normalized, _ = normalize_input(raw)
    try:
        catalog = load_data("demo_catalog.json") if catalog is None else deepcopy(catalog)
        rules = load_data("demo_rules.json") if rules is None else deepcopy(rules)
        by_id, _ = validate_catalog(catalog, rules)
        entries, options = catalog_for_patient(normalized, catalog)
        recommendation_catalog_flags(normalized, entries, by_id)
        result["catalog"], result["package_options"] = entries, options
        result["package"]["variant_id"] = "mini" if result["package"]["id"] == "prime_child" else "female" if normalized["sex"] == "F" else "male"
        result["package"]["payment"] = "paid_prime"
        result["screening"] = enrich_screening(result["screening"], normalized, entries)
        entry_map = {entry["procedure_id"]: entry for entry in entries}
        for item in result["items"]:
            item["source_package_ids"] = entry_map[item["procedure_id"]]["source_package_ids"]
        result["items"] = [public_item(item) for item in result["items"]]
    except DataError as exc:
        result["status"], result["errors"] = "invalid", [exc.error]
    return public_result(result, "recommendation")


def plan_selection(patient, selection, context=None, *, catalog=None, rules=None, slots=None):
    if isinstance(selection, dict) and "selected_procedure_ids" in selection and not isinstance(selection["selected_procedure_ids"], list):
        return public_error([input_error("selected_procedure_ids", "Ожидается массив ID выбранных услуг.", "list_type")], "plan")
    try:
        request = SelectionInput.model_validate(selection)
    except ValidationError as exc:
        return public_error(validation_errors(exc.errors(include_input=False)), "plan")
    if request.mode == "custom" and request.selected_procedure_ids is None:
        return public_error([input_error("selected_procedure_ids", "В режиме custom передайте массив выбранных ID, в том числе пустой.", "missing")], "plan")
    result = recommend(patient, context, catalog=catalog, rules=rules, slots=slots)
    result.update(stage="plan", mode=request.mode, base_package=None)
    if result["status"] == "invalid":
        return result
    current_version = result["versions"]["catalog"]
    if request.catalog_version != current_version:
        result["status"] = "invalid"
        result["errors"] = [input_error("catalog_version", "Каталог изменился. Повторите POST /recommend и проверьте выбор по новой версии.", "catalog_changed")]
        return public_result(result, "plan")
    # Only a service-level review has a package. Global stops/missing patient
    # answers retain their priority and cannot be bypassed by a selection.
    if not result["package"]:
        return public_result(result, "plan")
    raw, _ = merge_context(patient, context)
    normalized, _ = normalize_input(raw)
    try:
        catalog = load_data("demo_catalog.json") if catalog is None else deepcopy(catalog)
        rules = load_data("demo_rules.json") if rules is None else deepcopy(rules)
        slots = load_data("prime_slots.json") if slots is None else deepcopy(slots)
        by_id, _ = validate_catalog(catalog, rules)
        options = [option for option in result["package_options"] if option["package_id"] == request.base_package_id and (request.variant_id is None or option["variant_id"] == request.variant_id)]
        if request.variant_id is None:
            matching = [option for option in options if option["eligible"]]
            options = matching if len(matching) == 1 else options
        if len(options) != 1:
            return public_error([input_error("variant_id", "Укажите существующий пакет и однозначный variant_id из package_options.", "unknown_preset")], "plan")
        base = options[0]
        if request.mode == "preset" and not base["eligible"]:
            return public_error([input_error("base_package_id", "Этот пресет не соответствует возрасту/полу анкеты. Отдельные услуги можно обсудить в режиме custom.", "ineligible_preset")], "plan")
        selected = sorted(set(request.selected_procedure_ids or []))
        if request.mode == "preset":
            if request.selected_procedure_ids is not None and set(selected) != set(base["selected_procedure_ids"]):
                return public_error([input_error("selected_procedure_ids", "Состав не совпадает с выбранным пресетом. Для изменения состава используйте mode=custom.", "preset_mismatch")], "plan")
            selected = list(dict.fromkeys(base["selected_procedure_ids"]))
        catalog_map = {entry["procedure_id"]: entry for entry in result["catalog"]}
        unknown = [pid for pid in selected if pid not in catalog_map]
        if unknown:
            return public_error([input_error("selected_procedure_ids", "ID отсутствует в выбираемом каталоге услуг PRIME: " + ", ".join(unknown), "unknown_procedure")], "plan")
        recommended = {item["procedure_id"]: deepcopy(item) for item in result["items"]}
        result["recommended_package"] = deepcopy(result["package"])
        result["base_package"] = deepcopy(base)
        result["variant_id"] = base["variant_id"]
        result["selected_procedure_ids"] = selected
        result["items"] = []
        # Variants are already available in package_options. Legacy wording
        # about an unselected child alternative is not true after selecting it.
        result["alternatives"] = []
        result["status"] = "ready"
        result["questions"] = []
        result["warnings"] = [warning for warning in result["warnings"] if warning.get("code") != "PRELIMINARY"]
        result["trace"] = [row for row in result["trace"] if row["rule_id"] not in ("catalog_indications", "clinic_pregnancy", "clinic_preparation")]
        result["schedule"] = {"status": "not_run", "route": [], "after_results": [], "reason": None}
        result["package"] = {"id": None if request.mode == "custom" else base["package_id"], "variant_id": base["variant_id"],
                             "name": "Индивидуальный набор" if request.mode == "custom" else base["name"],
                             "title": "Индивидуальный набор" if request.mode == "custom" else "Выбранный пресет PRIME",
                             "source": base["source"], "url": base.get("url"), "price": None,
                             "preliminary": False, "reason": "Состав выбран пользователем; это не врачебное назначение."}
        result["price_text"] = "Стоимость — у администратора" if request.mode == "custom" else "цена не указана"
        result["removed_recommended_items"] = [item for pid, item in recommended.items() if pid not in selected]
        for removed in result["removed_recommended_items"]:
            result["warnings"].append({"code": "removed_recommendation", "procedure_id": removed["procedure_id"],
                                       "message": f"Вы исключили {removed['name']}; исходная рекомендация: {removed['why']}"})
        for pid in selected:
            entry = catalog_map[pid]
            kind = "selected_preset" if request.mode == "preset" else "retained_recommendation" if pid in recommended else "manual_selection"
            explanation = f"Из выбранного пользователем пресета «{base['name']}»." if request.mode == "preset" else "Сохранено пользователем из исходной рекомендации." if pid in recommended else "Выбрано пользователем из каталога PRIME"
            selection_reason = {"rule_id": kind, "explanation": explanation, "source": entry["source"], "validation_status": "demo_unvalidated"}
            item = make_item(by_id[pid], selection_reason)
            if pid in recommended:
                item["reasons"] = deepcopy(recommended[pid]["reasons"]) + [selection_reason]
                item["highlighted"] = recommended[pid]["highlighted"]
            item["selection_reason"] = selection_reason
            item["source_package_ids"] = entry["source_package_ids"]
            item["clinical_flags"] = deepcopy(entry.get("applicability_flags", []))
            item["screening_matches"] = deepcopy(recommended.get(pid, {}).get("screening_matches", []))
            result["items"].append(item)
        result["items"] = attach_screening_links(result["items"], result["screening"])
        if normalized["input_format"] != "legacy":
            result["proposed_extras"] = clinic_proposed_extras(normalized, result["items"])
        if not selected:
            result["status"] = "needs_input"
            result["questions"] = [{"field": "selected_procedure_ids", "message": "Выберите хотя бы одну услугу"}]
            return public_result(result, "plan")
        validate_composition(result["items"], selected, by_id)
        link_actions(result["items"], by_id)
        actions = expand_actions(result["items"])
        validate_composition(actions, [action["procedure_id"] for action in actions], by_id)
        review = evaluate_composition_review(normalized, result)
        planned = plan_actions(result["items"], base["package_id"], slots, normalized["availability"], by_id, requires_review=review)
        for key in ("route", "route_status", "unresolved_items", "schedule", "after_results"):
            result[key] = planned[key]
        if planned["errors"]:
            result["status"], result["errors"] = "invalid", planned["errors"]
        elif planned["requires_review"]:
            result["status"] = "review"
            result["package"]["preliminary"] = True
        result["next_visit"] = [deepcopy(NEXT_VISIT)]
        result["health_card"] = [{"procedure_id": item["procedure_id"], "name": item["name"], "status": "не пройдено", "result": "нет данных"} for item in result["items"]]
        result["items"] = [public_item(item) for item in result["items"]]
        result["selected_items"] = deepcopy(result["items"])
        result["added_items"] = [deepcopy(item) for item in result["items"] if item["procedure_id"] not in recommended]
    except DataError as exc:
        result["status"], result["errors"] = "invalid", [exc.error]
        result["schedule"] = {"status": "not_run", "route": [], "after_results": [], "reason": exc.error["message"]}
        result["route"], result["route_status"] = [], "unresolved"
    return public_result(result, "plan")


def recommend_request(raw):
    if isinstance(raw, dict) and ("patient" in raw or "context" in raw):
        extra = set(raw) - {"patient", "context"}
        if extra:
            return public_error([input_error(key, "Неизвестное поле запроса рекомендации.", "extra_forbidden") for key in sorted(extra)], "recommendation")
        return recommend(raw.get("patient"), raw.get("context"))
    return recommend(raw)


def plan_request(raw):
    if not isinstance(raw, dict):
        return public_error([input_error("body", "Ожидается JSON-объект запроса плана.", "model_type")], "plan")
    selection = {key: value for key, value in raw.items() if key not in ("patient", "context")}
    return plan_selection(raw.get("patient"), selection, raw.get("context"))
