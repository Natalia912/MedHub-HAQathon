"""Four explicit input formats, one patient representation; no medical inference.

The df733c4 export is lossy. Its omitted choices and derived diagnoses/smoking
values are observations about an old form, not confirmed patient facts.
"""
from copy import deepcopy
from datetime import date
import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, ValidationError, field_validator

from .config.clinic_fields import FIELDS, SOURCE_SHA
from .schemas import PlanInput, validation_errors

DEFAULTS = {"as_of_date": "2026-09-30", "visit_date": "2026-10-01",
            "checkup_year": 2026, "availability": "normal"}
REGISTRATION_MAP = {
    "pressure": "hypertension", "heart": "ihd", "diabetes": "diabetes", "glaucoma": "glaucoma",
    "head_vessels": "cerebrovascular", "breast": "breast_cancer", "hpv": "cervical_cancer",
    "bowel": "colorectal", "lungs": "lung_cancer", "hepatitis": "chronic_hepatitis",
}
CONDITIONS = set(REGISTRATION_MAP) | {"legs", "tb", "urine", "bleeding"}
FAMILY = {"colorectal_cancer", "breast_cancer", "other_cancer", "early_cvd", "hypertension", "diabetes", "tb"}
SCREENINGS = {"scr_cvd", "scr_cerebro", "scr_breast", "scr_cervix", "scr_colorectal", "scr_hepatitis", "scr_lung"}
CURRENT_SOURCE_SHA = "744d7f79e6872a31572dda9d75269a8a8b7bcd4a"
RISK_GROUPS = {"medical_worker_invasive", "planned_surgery", "hemodialysis_oncology_hematology",
               "transfusion_transplant", "pregnancy", "hiv_key_population"}
LABELS = {f["name"]: f["label"] for f in FIELDS}
LABELS.update(registered="Сообщённые диагнозы на учёте", registered_absent="Явно отрицаемые диагнозы на учёте",
              risk_group="Сообщённые группы риска по гепатитам")
FORM_FIELDS = {f["name"] for f in FIELDS}
DOCTOR_FIELDS = ["conditions", "conditions_other", "registered_on", "registered", "registered_absent", "family_history", "risk_group",
                 "pregnant", "last_period", "pregnancies", "births", "contraception", "discharge", "dysuria",
                 "smoke_status", "anesthesia_reaction", "blood_thinners", "allergy", "medications", "companion"]


class SmokingExport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    pack_years: float | None = Field(default=None, ge=0, le=600, allow_inf_nan=False)
    quit_years_ago: float | None = Field(default=None, ge=0, le=120, allow_inf_nan=False)


class ClinicInput(BaseModel):
    """Optional medical answers; only structural validation belongs in this schema."""
    model_config = ConfigDict(extra="forbid", strict=True)
    input_version: Literal["clinic_v1", "clinic_v2", "df733c4"]
    for_child: StrictBool | None = None
    sex: Literal["M", "F", "unknown"] | None = None
    birth_date: str | None = None
    birth_year: StrictInt | None = Field(default=None, ge=1, le=9999)
    checkup_year: StrictInt = Field(default=2026, ge=1, le=9999)
    as_of_date: str = DEFAULTS["as_of_date"]
    visit_date: str = DEFAULTS["visit_date"]
    availability: Literal["normal", "busy"] = "normal"
    urgent: Literal["none", "chest_pain", "dyspnea", "stroke_signs", "other_now", "unknown"] | None = None
    pregnant: Literal["no", "yes", "unsure", "unknown"] | None = None
    discharge: Literal["no", "yes", "unsure", "unknown"] | None = None
    dysuria: Literal["no", "yes", "unsure", "unknown"] | None = None
    conditions: list[str] | None = None
    registered_on: list[str] | None = None
    registered: list[str] | None = None
    registered_absent: list[str] | None = None
    family_history: list[str] | None = None
    risk_group: list[str] | dict[str, Literal["yes", "no", "unsure", "unknown"]] | None = None
    smoke_status: Literal["never", "smokes", "quit", "unknown"] | None = None
    cigs_per_day: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    smoke_years: float | None = Field(default=None, ge=0, le=80, allow_inf_nan=False)
    quit_years_ago: float | None = Field(default=None, ge=0, le=80, allow_inf_nan=False)
    smoking: SmokingExport | None = None
    hazardous_work_10y: StrictBool | Literal["yes", "no", "unknown"] | None = None
    last_screening: list[str] | dict[str, StrictInt | Literal["never", "unknown"] | None] | None = None
    attached_to: Literal["green_clinic", "other", "unknown"] | None = None
    conditions_other: str | None = Field(default=None, max_length=300)
    last_period: str | None = None
    pregnancies: StrictInt | None = Field(default=None, ge=0, le=30)
    births: StrictInt | None = Field(default=None, ge=0, le=30)
    contraception: Literal["none", "condom", "pills", "iud", "other", "not_needed", "unknown"] | None = None
    anesthesia_reaction: Literal["no", "yes", "never", "unsure", "unknown"] | None = None
    blood_thinners: Literal["no", "yes", "unsure", "unknown"] | None = None
    allergy: Literal["no", "yes", "unsure", "unknown"] | None = None
    medications: str | None = Field(default=None, max_length=1000)
    companion: Literal["yes", "no", "unsure", "unknown"] | None = None
    provenance: dict[str, str] = Field(default_factory=dict)

    @field_validator("birth_date", "as_of_date", "visit_date", "last_period")
    @classmethod
    def valid_date(cls, value):
        if value is None:
            return value
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("Укажите существующую дату в формате ГГГГ-ММ-ДД.")
        try:
            date.fromisoformat(value)
        except ValueError:
            raise ValueError("Укажите существующую дату в формате ГГГГ-ММ-ДД.") from None
        return value

    @field_validator("conditions", "registered_on", "registered", "registered_absent", "family_history", "risk_group", "last_screening")
    @classmethod
    def valid_codes(cls, value, info):
        if value is None:
            return value
        allowed = {"conditions": CONDITIONS, "registered_on": set(REGISTRATION_MAP),
                   "registered": set(REGISTRATION_MAP.values()), "registered_absent": set(REGISTRATION_MAP.values()),
                   "family_history": FAMILY, "risk_group": RISK_GROUPS,
                   "last_screening": SCREENINGS}[info.field_name]
        markers = set() if info.field_name == "registered_absent" else {"none", "unknown"}
        if any(code not in allowed | markers for code in value):
            raise ValueError("Выберите допустимый код ответа.")
        if any(code in value for code in ("none", "unknown")) and (len(value) != 1 or isinstance(value, dict)):
            raise ValueError("Ответы «нет» и «не знаю» не совмещаются с другими вариантами.")
        return sorted(set(value)) if isinstance(value, list) else value


def _error(field, message, code="inconsistent"):
    return {"scope": "input", "field": field, "code": code, "message": message}


def _question(field, message):
    return {"field": field, "code": "inconsistent_answers", "message": message}


def _and(*values):
    return False if False in values else None if None in values else True


def field_applicable(field, values, age_full):
    """Explicit questionnaire branches, not an interpreter of source show_if."""
    # The HTML renderer also calls this after failed validation; retain that form.
    if not isinstance(values, dict):
        values = {}
    if type(age_full) not in (int, float) or not math.isfinite(age_full):
        age_full = None
    sex = values.get("sex")
    adult = False if values.get("for_child") is True else None if age_full is None else age_full >= 18
    female = None if sex in (None, "unknown") else sex == "F"
    male = None if sex in (None, "unknown") else sex == "M"
    to55 = None if age_full is None else age_full <= 55
    current = values.get("input_version") == "clinic_v2"
    # A reported history is a fact about the past, not a proposal to perform a
    # screening now. Preserve it for every age and sex, including explicit never.
    if field == "last_screening":
        return True
    if field in {"smoking", "risk_group"}:
        return adult
    if current and field in {"anesthesia_reaction", "blood_thinners", "companion"}:
        return True
    if current and field == "conditions_other":
        return True
    if current and field in {"last_period", "contraception", "births"}:
        return _and(female, adult)
    if field in {"pregnant", "last_period", "contraception"}:
        return _and(female, adult, to55)
    if field in {"pregnancies", "discharge"}:
        return _and(female, adult)
    if field == "births":
        pregnancies = values.get("pregnancies")
        if type(pregnancies) not in (int, float) or not math.isfinite(pregnancies):
            pregnancies = None
        return _and(female, adult, None if pregnancies is None else pregnancies > 0)
    if field == "dysuria":
        return _and(male, adult)
    if field in {"smoke_status", "anesthesia_reaction", "blood_thinners", "companion"}:
        return adult
    if field in {"cigs_per_day", "smoke_years", "quit_years_ago"}:
        status = values.get("smoke_status")
        if not isinstance(status, str):
            status = None
        child_condition = None if status in (None, "unknown") else (
            status == "quit" or (status == "smokes" and values.get(field) == 0)
            if field == "quit_years_ago" else status in {"smokes", "quit"})
        return _and(adult, child_condition)
    if field == "hazardous_work_10y":
        if current:
            return adult
        return _and(adult, None if age_full is None else 50 <= age_full <= 70)
    if field == "conditions_other":
        return values.get("conditions") != ["none"]
    if field == "registered_on":
        conditions = values.get("conditions")
        if not isinstance(conditions, list) or not all(isinstance(value, str) for value in conditions):
            return None
        return None if conditions in (None, [], ["unknown"]) else bool(set(conditions) & set(REGISTRATION_MAP))
    return True


def _answer_state(value, present, input_format, field):
    if value == "unknown" or value == ["unknown"]:
        return "unknown"
    if value == "unsure" and field != "pregnant":
        return "unknown"
    if input_format == "df733c4" and field == "family_history" and value == ["none"]:
        return "unknown"
    if not present or value in (None, "", [], {}):
        return "unanswered"
    return "answered"


def _registration(values, answers, version, provenance):
    exported = values.get("registered") or []
    broad = values.get("registered_on") or []
    codes = set(exported) - {"none", "unknown"}
    mapped = {REGISTRATION_MAP[x] for x in broad if x in REGISTRATION_MAP}
    confirmed = version in {"clinic_v1", "clinic_v2"} and provenance.get("registered") == "confirmed_clinician"
    negative = not (codes or mapped) and ((answers["registered"]["state"] == "answered" and exported == ["none"]) or (
        answers["registered_on"]["state"] == "answered" and broad == ["none"]))
    negative_codes = set(values.get("registered_absent") or [])
    if negative:
        negative_codes.update(REGISTRATION_MAP.values())
    return {"confirmed_codes": sorted(codes) if confirmed else [],
            "ambiguous_codes": sorted(mapped | (set() if confirmed else codes)),
            "negative_codes": sorted(negative_codes),
            "negative_source": answers["registered_absent"]["source"] if values.get("registered_absent") else None,
            "known_negative": negative,
            "known_complete": confirmed and answers["registered"]["state"] == "answered",
            "source": answers["registered"]["source"] if codes else answers["registered_on"]["source"]}


def _smoking(values, version, warnings, age_full):
    if version == "clinic_v2":
        return _reported_smoking(values, age_full)
    status = values.get("smoke_status")
    if status == "unknown":
        status = None
    cigs, years = values.get("cigs_per_day"), values.get("smoke_years")
    quit_years = values.get("quit_years_ago") if status == "quit" or (
        status == "smokes" and values.get("quit_years_ago") == 0) else None
    pack_years = 0.0 if status == "never" else cigs / 20 * years if status in {"smokes", "quit"} and cigs is not None and years is not None else None
    missing = []
    if status in {"smokes", "quit"}:
        for field, message in (("cigs_per_day", "Уточните число сигарет в день."), ("smoke_years", "Уточните стаж курения.")):
            if values.get(field) is None:
                missing.append({"field": field, "message": message})
        if status == "quit" and quit_years is None:
            missing.append({"field": "quit_years_ago", "message": "Уточните, сколько лет назад прекратили курить; пропуск не означает 0."})
    derived = values.get("smoking")
    if derived:
        warnings.append({"code": "smoking_export_recomputed", "message": "Экспорт smoking не является исходным ответом: стаж рассчитан только по исходным полям, пропуски сохранены."})
        # Export rounds pack-years to one decimal; allow only that documented rounding.
        if pack_years is not None and derived.get("pack_years") is not None and not math.isclose(round(pack_years, 1), derived["pack_years"], abs_tol=1e-9):
            missing.append(_question("smoking", "Расчёт smoking расходится с исходными ответами о курении; уточните данные для скрининга."))
        if status == "quit" and quit_years is not None and derived.get("quit_years_ago") is not None and quit_years != derived["quit_years_ago"]:
            missing.append(_question("smoking", "Срок отказа в smoking расходится с исходным ответом; уточните данные для скрининга."))
    if status in {"smokes", "quit"} and years is not None and age_full is not None and years > age_full:
        missing.append(_question("smoke_years", "Стаж курения больше полного возраста; уточните исходные ответы для скрининга."))
    if status == "quit" and quit_years is not None and age_full is not None:
        if quit_years > age_full:
            missing.append(_question("quit_years_ago", "Срок отказа от курения больше возраста; уточните исходные ответы для скрининга."))
        elif years is not None and years + quit_years > age_full:
            missing.append(_question("smoking", "Сумма стажа и времени после отказа от курения больше возраста; уточните исходные ответы для скрининга."))
    if any(question.get("code") == "inconsistent_answers" for question in missing):
        pack_years = None
        quit_years = None
        warnings.append({"code": "smoking_answers_inconsistent", "message": "Данные курения противоречивы: расчёт скрининга требует уточнения. Это не блокирует подбор PRIME."})
    return {"status": status, "pack_years": pack_years, "quit_years_ago": quit_years,
            "source": f"{version}:raw_smoking_answers", "questions": missing}


def _reported_smoking(values, age_full):
    """Current questionnaire asks for these numbers directly, not a JS export.

    A missing cessation interval does not establish current smoking. Preserve the
    stated components without inventing cigarettes/day, years smoked or a status.
    """
    reported = values.get("smoking")
    pack_years = reported.get("pack_years") if reported else None
    quit_years = reported.get("quit_years_ago") if reported else None
    questions = []
    if quit_years is not None and age_full is not None and quit_years > age_full:
        questions.append(_question("smoking.quit_years_ago", "Срок отказа от курения больше возраста; уточните сообщённое значение."))
        pack_years = quit_years = None
    return {"status": "reported_exposure" if reported else None, "pack_years": pack_years,
            "quit_years_ago": quit_years, "source": "clinic_v2:reported_smoking", "questions": questions}


def _history(values, version, provenance, context, warnings):
    original = values.get("last_screening")
    if not original:
        return []
    history = []
    for screening_id in original:
        if screening_id in {"none", "unknown"}:
            continue
        value = original[screening_id] if isinstance(original, dict) else None
        if value == "never":
            history.append({"screening_id": screening_id, "performed_status": "never", "performed_year": None,
                            "performed_on": None, "date_precision": "not_applicable", "range_start": None,
                            "range_end": None, "source": f"{version}:last_screening", "result_status": "unknown",
                            "review_status": "unknown", "medical_validated": False})
            continue
        year = value if type(value) is int else None
        imported_range = version == "df733c4" and year == context["checkup_year"] - 1 and provenance.get("last_screening") != "known_year"
        is_range = isinstance(original, list) or imported_range
        history.append({"screening_id": screening_id, "performed_year": None if is_range else year,
                        "performed_on": None, "date_precision": "range" if is_range else "year" if year is not None else "unknown",
                        "range_start": context["checkup_year"] - 2 if is_range else None,
                        "range_end": context["checkup_year"] if is_range else None,
                        "source": f"{version}:last_screening", "result_status": "unknown", "review_status": "unknown",
                        "medical_validated": False})
    if any(row["date_precision"] == "range" for row in history):
        warnings.append({"code": "screening_history_range", "message": "История «за последние два года» сохранена как диапазон: точный год и результат не известны."})
    return history


def _legacy(raw):
    payload = {key: value for key, value in raw.items() if key != "input_version"}
    try:
        model = PlanInput.model_validate(payload)
    except ValidationError as exc:
        return None, validation_errors(exc.errors(include_input=False))
    values = model.model_dump(mode="json")
    answers = {key: {"state": "unknown" if value == "unknown" else "answered", "value": value,
                     "source": "legacy"} for key, value in values.items()}
    return {**values, "input_format": "legacy", "age_full": model.age, "age_year": None,
            "urgent": None, "pregnant": None, "pregnancy_applicable": None, "values": deepcopy(values),
            "answers": answers, "questions": [], "warnings": [], "doctor_summary": [],
            "registration": {"confirmed_codes": [], "ambiguous_codes": [], "known_negative": False, "source": "legacy"},
            "smoking": {"status": None, "pack_years": None, "quit_years_ago": None, "source": "legacy", "questions": []},
            "history": [], "context": {"input_version": "legacy", "as_of_date": None,
                "visit_date": values["visit_date"], "checkup_year": None, "availability": values["availability"],
                "defaulted": [], "source_sha": None}}, []


def normalize_input(raw):
    """Return (patient, []) or (None, common field errors), without mutating input."""
    if isinstance(raw, PlanInput):
        raw = raw.model_dump(mode="json")
    if not isinstance(raw, dict):
        return None, [_error("body", "Ожидается JSON-объект с полями анкеты.", "model_type")]
    raw = deepcopy(raw)
    version = raw.get("input_version")
    if version is None:
        version = "df733c4" if "birth_date" in raw or "birth_year" in raw else "legacy" if "age" in raw else "clinic_v1"
    if version not in {"legacy", "clinic_v1", "clinic_v2", "df733c4"}:
        return None, [_error("input_version", "Допустимые версии: legacy, clinic_v1, clinic_v2, df733c4.", "literal_error")]
    if "age" in raw and (version != "legacy" or "birth_date" in raw or "birth_year" in raw):
        return None, [_error("age", "Не смешивайте age прежней анкеты и новую анкету с датой рождения.")]
    if version == "legacy":
        return _legacy(raw)
    payload = {**raw, "input_version": version}
    # Explicit unknown is recorded below, while numeric/date validators receive no invented value.
    for field in {"for_child", "birth_date", "birth_year", "last_period", "pregnancies", "births", "cigs_per_day", "smoke_years", "quit_years_ago"}:
        if payload.get(field) == "unknown":
            payload[field] = None
    try:
        model = ClinicInput.model_validate(payload)
    except ValidationError as exc:
        errors = validation_errors(exc.errors(include_input=False))
        for error in errors:
            if error["code"] in {"int_type", "float_type", "greater_than_equal", "less_than_equal"}:
                error["message"] = "Укажите число в допустимом диапазоне; целые поля не принимают дробные значения."
            if error["code"] == "list_type":
                error["message"] = "Ожидается список допустимых кодов ответа."
        return None, errors
    values = model.model_dump(mode="json")
    as_of = date.fromisoformat(model.as_of_date)
    birth = date.fromisoformat(model.birth_date) if model.birth_date else None
    errors = []
    if version == "clinic_v2" and model.urgent == "other_now":
        errors.append(_error("urgent", "В текущей анкете clinic_v2 нет ответа other_now; он поддержан только в прежних форматах.", "literal_error"))
    if version == "clinic_v2" and any(raw.get(field) is not None for field in
                                      ("smoke_status", "cigs_per_day", "smoke_years", "quit_years_ago")):
        errors.append(_error("smoking", "Для clinic_v2 передайте самостоятельно сообщённые значения внутри smoking; старые компоненты курения относятся к clinic_v1/df733c4."))
    if set(model.registered_absent or []) & (set(model.registered or []) | {
            REGISTRATION_MAP[code] for code in model.registered_on or [] if code in REGISTRATION_MAP}):
        errors.append(_error("registered_absent", "Один и тот же код учёта одновременно сообщён и явно отрицается; уточните исходные ответы."))
    if birth and birth > as_of:
        errors.append(_error("birth_date", "Дата рождения не может быть позже даты оценки возраста."))
    if birth and model.birth_year is not None and birth.year != model.birth_year:
        errors.append(_error("birth_year", "Год рождения не совпадает с датой рождения."))
    birth_year = birth.year if birth else model.birth_year
    if birth_year and birth_year > as_of.year:
        errors.append(_error("birth_year", "Год рождения не может быть позже даты оценки возраста."))
    if birth_year and birth_year > model.checkup_year:
        errors.append(_error("checkup_year", "Год скрининга не может быть раньше года рождения."))
    age_full = as_of.year - birth.year - ((as_of.month, as_of.day) < (birth.month, birth.day)) if birth else None
    if age_full is not None and age_full > 120:
        errors.append(_error("birth_date", "Возраст для этого тестера не должен превышать 120 лет."))
    if birth_year and as_of.year - birth_year > 121:
        errors.append(_error("birth_year", "Проверьте год рождения: возраст превышает диапазон тестера."))
    if model.last_period and date.fromisoformat(model.last_period) > as_of:
        errors.append(_error("last_period", "Дата последних месячных не может быть позже даты оценки."))
    if version == "clinic_v2" and birth and model.last_period and date.fromisoformat(model.last_period) < birth:
        errors.append(_error("last_period", "Дата последних месячных не может быть раньше даты рождения."))
    if isinstance(model.last_screening, dict):
        for key, year in model.last_screening.items():
            if type(year) is int and (year < 1 or year > as_of.year or (birth_year and year < birth_year)):
                errors.append(_error(f"last_screening.{key}", "Год обследования должен быть не раньше рождения и не позже даты оценки."))
    if errors:
        return None, errors
    context = {"input_version": version, **{field: values[field] for field in DEFAULTS},
               "defaulted": [field for field in DEFAULTS if field not in raw],
               "source_sha": CURRENT_SOURCE_SHA if version == "clinic_v2" else SOURCE_SHA,
               "adapter_version": "intake-2"}
    warnings, questions, answers = [], [], {}
    provenance = model.provenance
    for field in sorted(FORM_FIELDS | {"birth_year", "registered", "registered_absent", "risk_group", "smoking"}):
        original = raw.get(field)
        state = _answer_state(original, field in raw, version, field)
        applicable = field_applicable(field, values, age_full)
        answers[field] = {"state": "not_applicable" if applicable is False else state,
                          "value": deepcopy(original), "source": provenance.get(field, f"{version}:provided" if field in raw else f"{version}:not_exported" if version == "df733c4" else f"{version}:unanswered")}
        if applicable is False:
            values[field] = None
            if state in {"answered", "unknown"}:
                warnings.append({"code": "answer_not_applicable", "field": field,
                                 "message": f"Ответ «{LABELS.get(field, field)}» сохранён в происхождении, но не применяется в этой ветке анкеты."})
        elif state in {"unknown", "unanswered"}:
            values[field] = None
    # Sex-specific checkbox remnants are retained in answers, never interpreted in a different branch.
    if model.sex == "M" and version != "clinic_v2":
        for field, female_codes in (("conditions", {"breast", "hpv"}), ("registered_on", {"breast", "hpv"})):
            value = values.get(field)
            if value and any(code in value for code in female_codes):
                values[field] = {key: val for key, val in value.items() if key not in female_codes} if isinstance(value, dict) else [code for code in value if code not in female_codes]
                warnings.append({"code": "option_not_applicable", "field": field, "message": "Отмеченные варианты для другого пола сохранены в исходных ответах и не влияют на расчёт."})
    if model.for_child is True and age_full is not None and age_full >= 18:
        questions.append(_question("for_child", "Указан взрослый возраст и подбор для ребёнка; уточните, для кого заполняется анкета."))
    if raw.get("pregnant") in {"yes", "unsure"} and field_applicable("pregnant", model.model_dump(mode="json"), age_full) is False:
        questions.append(_question("pregnant", "Ответ о беременности противоречит применимости раздела по полу/возрасту; уточните ответы с врачом."))
    if values.get("births") is not None and values.get("pregnancies") is not None and values["births"] > values["pregnancies"]:
        questions.append(_question("births", "Число родов больше числа беременностей; уточните исходные ответы."))
    if model.registered_on and model.conditions and set(model.registered_on) - {"none", "unknown"} - set(model.conditions):
        questions.append(_question("registered_on", "Отметки учёта не согласованы со списком состояний; уточните исходный ответ."))
    if model.conditions == ["none"] and model.registered and set(model.registered) - {"none", "unknown"}:
        questions.append(_question("registered", "Указаны коды учёта и ответ «ничего из этого»; уточните исходные сведения."))
    if version == "df733c4":
        warnings.append({"code": "lossy_form_export", "message": "Импорт df733c4 теряет отрицательные и пустые ответы. Пропуски не восстановлены как «нет»; преобразованные диагнозы не подтверждены."})
    if type(values.get("hazardous_work_10y")) is bool:
        values["hazardous_work_10y"] = "yes" if values["hazardous_work_10y"] else "no"
    registration = _registration(values, answers, version, provenance)
    smoking = _smoking(values, version, warnings, age_full)
    history = _history(values, version, provenance, context, warnings)
    doctor_summary = [{"field": field, "label": LABELS.get(field, "Экспортированный код учёта (диагноз не подтверждён)"),
                       "value": values.get(field), "state": answers[field]["state"], "source": answers[field]["source"]}
                      for field in DOCTOR_FIELDS if answers[field]["state"] in {"answered", "unknown"}]
    pregnancy_applicable = field_applicable("pregnant", model.model_dump(mode="json"), age_full)
    return {"input_format": version, "age_full": age_full, "age_year": model.checkup_year - birth_year if birth_year else None,
            "age": age_full, "sex": values.get("sex"), "urgent": values.get("urgent"), "pregnant": values.get("pregnant"),
            "pregnancy_applicable": pregnancy_applicable, "complaints": [], "visit_date": model.visit_date,
            "availability": model.availability, "values": values, "answers": answers, "context": context,
            "warnings": warnings, "questions": questions, "doctor_summary": doctor_summary,
            "registration": registration, "smoking": smoking, "history": history}, []
