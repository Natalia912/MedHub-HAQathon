"""Selectable PRIME services and presets, without prescribing or scheduling.

Membership is read from explicit package IDs. An age boundary belongs to its
package, not automatically to every service in that package. The conservative
applicability notes below describe gaps in the catalogue, not contraindications.
"""
import json
from copy import deepcopy
from pathlib import Path

from .engine import DataError


DATA = Path(__file__).parent / "data"
MEMBERSHIP_FIELDS = ("required_ids", "female_ids", "male_ids", "extended_ids")
# These two source groups explicitly mix examinations with an infant-only
# component. Their text is preserved; the editor never silently subtracts it.
AGE_DEPENDENT_GROUPS = {
    "prime_child_ecg_neurosonography_group",
    "prime_child_extended_ultrasound_group",
}


def _flag(code, message, source):
    return {"code": code, "message": message, "source": source,
            "validation_status": "demo_unvalidated"}


def _applicability(patient, memberships, procedure):
    """Describe explicit sex variants and missing cross-population guidance."""
    age, sex = patient.get("age_full"), patient.get("sex")
    package_ids = {package_id for package_id, _ in memberships}
    fields = {field for _, field in memberships}
    general = bool(fields & {"required_ids", "extended_ids"})
    sexes = {sex for field, sex in (("female_ids", "F"), ("male_ids", "M")) if field in fields}
    sex_scope = sorted(sexes) if not general else ["F", "M"]
    child_only = package_ids == {"prime_child"}
    adult_only = "prime_child" not in package_ids
    age_scope = "child_catalog_only" if child_only else "adult_catalog_only" if adult_only else "child_and_adult_catalog"
    source = "app/data/demo_catalog.json:packages (явные ссылки на ID услуг)"
    flags = []
    if not general and sexes and sex not in sexes:
        flags.append(_flag(
            "sex_variant_requires_review",
            "Услуга указана только в " + ("женской" if sexes == {"F"} else "мужской")
            + " части каталога. Применимость к указанному полу требует проверки; это не заключение о противопоказании.",
            source))
    if age is None or age < 1:
        flags.append(_flag("age_applicability_unknown",
                           "Для указанного возраста применимость услуги не установлена данными каталога.", source))
    elif (age < 18 and adult_only) or (age >= 18 and child_only):
        flags.append(_flag(
            "cross_population_requires_review",
            "Услуга представлена только в " + ("детском" if child_only else "взрослых")
            + " пакетах. Применимость вне этой группы не описана и требует решения врача; возраст пакета не считается противопоказанием услуги.",
            source))
    if procedure["id"] in AGE_DEPENDENT_GROUPS:
        flags.append(_flag(
            "AGE_DEPENDENT_GROUP",
            "Группа содержит действие с отдельным возрастным условием для младенцев. Состав для указанного возраста требует решения врача; компоненты группы автоматически не вычитаются, диапазон пакета 1–17 лет не расширяется.",
            "app/data/demo_catalog.json:procedures." + procedure["id"]))
    reason = (" ".join(flag["message"] for flag in flags) if flags else
              "Явные ссылки каталога не выявили несовпадения варианта. Наличие в каталоге не означает медицинского одобрения; граница 40 лет относится к выбору пакета.")
    return ({"status": "requires_review" if flags else "catalog_match", "reason": reason,
             "source": source, "sex_scope": sex_scope, "age_scope": age_scope}, flags)


def _preset_option(patient, package, variant_id, ids, sex=None):
    age = patient.get("age_full")
    when = package["when"]
    age_ok = age is not None and when["age_min"] <= age <= when["age_max"]
    sex_ok = patient.get("sex") in ("F", "M") and (sex is None or patient.get("sex") == sex)
    eligible = age_ok and sex_ok
    if age is None:
        reason = "Для выбора пресета нужен полный возраст."
    elif not age_ok:
        reason = f"Пресет предусмотрен каталогом для возраста {when['age_min']}–{when['age_max']} лет."
    elif not sex_ok:
        reason = "Пол не соответствует варианту пресета либо требует уточнения."
    else:
        reason = "Возраст и пол соответствуют варианту каталога; медицинские ограничения услуг проверяются отдельно."
    suffix = {"female": "f", "male": "m"}.get(variant_id, variant_id)
    return {
        "id": package["id"], "package_id": package["id"], "variant_id": variant_id,
        "name": package.get("name_" + suffix, package["name"]),
        "url": package.get("url_" + suffix), "source": package["source"],
        "source_sha": package.get("source_sha"), "selected_procedure_ids": list(dict.fromkeys(ids)),
        "eligible": eligible, "reason": reason,
        "age_min": when["age_min"], "age_max": when["age_max"], "sex": sex,
        "medical_validated": False,
    }


def catalog_for_patient(normalized, catalog):
    """Return complete selectable services and exact, explicitly named presets.

Actions are deliberately not selectable. Invalid package references are data
errors, rather than a reason to silently trim a patient's choice.
    """
    by_id = {entry["id"]: entry for entry in catalog["procedures"]}
    if len(by_id) != len(catalog["procedures"]):
        raise DataError("catalog.procedures", "В каталоге повторяется ID услуги.")
    memberships = {}
    options = []
    for package in catalog["packages"]:
        for field in MEMBERSHIP_FIELDS:
            for procedure_id in package.get(field, []):
                procedure = by_id.get(procedure_id)
                if (procedure is None or not procedure.get("active", True)
                        or procedure.get("parent_procedure_id") or not procedure_id.startswith("prime_")):
                    raise DataError(f"catalog.packages.{package['id']}.{field}",
                                    "Некорректная ссылка пакета на выбираемую услугу: " + procedure_id)
                memberships.setdefault(procedure_id, []).append((package["id"], field))
        if package["id"] == "prime_child":
            options.append(_preset_option(normalized, package, "mini", package["required_ids"]))
            if package.get("extended_ids"):
                options.append(_preset_option(normalized, package, "extended", package["extended_ids"]))
        else:
            for variant, sex, field in (("female", "F", "female_ids"), ("male", "M", "male_ids")):
                options.append(_preset_option(normalized, package, variant,
                                              package["required_ids"] + package.get(field, []), sex))
    items = []
    for procedure_id in sorted(memberships):
        entry = by_id[procedure_id]
        applicability, flags = _applicability(normalized, memberships[procedure_id], entry)
        items.append({
            "procedure_id": procedure_id, "name": entry["name"],
            "source_package_ids": sorted({package_id for package_id, _ in memberships[procedure_id]}),
            "source": entry["source"], "source_sha": entry.get("source_sha", catalog.get("source_sha")),
            "is_group": entry.get("is_group", False), "tags": list(entry.get("tags", [])),
            "conditional": entry.get("conditional", False), "action_ids": list(entry.get("action_ids", [])),
            "applicability": applicability, "applicability_flags": flags,
            "requires_review": bool(flags) or entry.get("conditional", False),
            "known_constraints": [constraint for constraint in ("pregnancy_review", "requires_indication")
                                  if constraint in entry.get("tags", [])],
            "validation_status": entry.get("validation_status", "demo_unvalidated"),
            "medical_validated": False,
        })
    return items, options


def enrich_screening(screening, normalized, catalog_items):
    """Separate public-program information and explicit paid PRIME choices.

No service is inserted into a selection; even an exact link denotes a component
and is not proof that an entire service is covered by the public programme.
    """
    links = json.loads((DATA / "screening_links.json").read_text(encoding="utf-8"))
    document = json.loads((DATA / "screening_rules.json").read_text(encoding="utf-8"))
    rules = {rule["id"]: rule for rule in document["screening"]}
    by_id = {item["procedure_id"]: item for item in catalog_items}
    for link in links["links"]:
        if link["procedure_id"] not in by_id or link["screening_id"] not in rules:
            raise DataError("screening_links.links", "Некорректная явная связь скрининга с каталогом: " + link["procedure_id"])
    attached_to = normalized.get("values", {}).get("attached_to")
    where = {
        "green_clinic": "Поликлиника прикрепления Green Clinic; условия прохождения уточнить в регистратуре",
        "other": "Своя поликлиника прикрепления; учреждение и условия прохождения уточнить",
    }.get(attached_to, "Уточнить поликлинику прикрепления")
    result = deepcopy(screening)
    for screening_item in result:
        rule_id = screening_item["rule_id"]
        if rule_id not in rules:
            raise DataError("screening.rule_id", "Неизвестное правило скрининга: " + rule_id)
        rule = rules[rule_id]
        screening_item["payment"] = {
            "status": "public_program_candidate" if screening_item["outcome"] == "candidate" else "requires_verification",
            "source_code": rule.get("payment"), "guaranteed": False,
            "text": "Возможность пройти по госпрограмме уточняется в поликлинике; оплата и доступность не подтверждены.",
        }
        screening_item["where"] = where
        screening_item["where_source"] = "Ответ attached_to; предоставленное правило: " + rule["source"]
        screening_item["repeat_years_reference"] = {
            "years": rule.get("repeat_years"), "source": rule["source"],
            "text": "Справочная периодичность из правила; не персональная дата следующего визита.",
        }
        matches = []
        for link in links["links"]:
            if link["screening_id"] != rule_id:
                continue
            matches.append({
                "procedure_id": link["procedure_id"], "name": by_id[link["procedure_id"]]["name"],
                "match_degree": link["match_degree"], "explanation": link["explanation"],
                "source": "app/data/screening_links.json", "source_sha": links.get("source_sha"),
            })
        screening_item["prime_matches"] = matches
        screening_item["choices"] = [{
            "kind": "public_program", "label": "Обсудить прохождение по госпрограмме в поликлинике",
            "where": where, "requires_confirmation": True,
        }] + [{
            "kind": "prime_service", "procedure_id": match["procedure_id"],
            "label": "Выбрать услугу PRIME: " + match["name"],
            "match_degree": match["match_degree"], "explanation": match["explanation"],
            "requires_explicit_selection": True,
        } for match in matches]
    return result
