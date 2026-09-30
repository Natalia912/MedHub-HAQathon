"""Единый вход и оболочка результата для HTML и JSON."""
import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


class PlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    age: StrictInt = Field(ge=1, le=120)
    sex: Literal["M", "F", "unknown"]
    complaints_state: Literal["none", "list", "unknown"]
    complaints: list[Literal["fatigue", "chest_pain"]] = Field(strict=True)
    family_crc: Literal["yes", "no", "unknown"]
    visit_date: date
    availability: Literal["normal", "busy"]

    @field_validator("visit_date", mode="before")
    @classmethod
    def iso_date(cls, value):
        if type(value) is date:
            return value
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("Укажите дату в формате ГГГГ-ММ-ДД.")
        return value

    @field_validator("complaints")
    @classmethod
    def consistent_complaints(cls, value, info):
        state = info.data.get("complaints_state")
        if state == "list" and not value:
            raise ValueError("Выберите хотя бы одну жалобу.")
        if state in ("none", "unknown") and value:
            raise ValueError("При ответе «нет» или «не знаю» список жалоб должен быть пуст.")
        return sorted(set(value))


class PlanResult(BaseModel):
    status: Literal["ready", "needs_input", "review", "invalid"] = "ready"
    demo: Literal[True] = True
    medical_validated: Literal[False] = False
    package: dict | None = None
    items: list[dict] = Field(default_factory=list)
    questions: list[dict] = Field(default_factory=list)
    warnings: list[dict] = Field(default_factory=list)
    trace: list[dict] = Field(default_factory=list)
    schedule: dict = Field(default_factory=lambda: {
        "status": "not_run", "route": [], "after_results": [], "reason": None,
    })
    health_card: list[dict] = Field(default_factory=list)
    reminder_draft: dict = Field(default_factory=lambda: {
        "status": "requires_clinician", "due_date": None, "basis": None, "sent": False,
    })
    versions: dict = Field(default_factory=lambda: {
        "engine": "demo-3", "catalog": "demo-2", "rules": "demo-2", "slots": "demo-2",
    })
    errors: list[dict] = Field(default_factory=list)
    input_context: dict = Field(default_factory=dict)
    screening: list[dict] = Field(default_factory=list)
    doctor_summary: list[dict] = Field(default_factory=list)
    proposed_extras: list[dict] = Field(default_factory=list)
    alternatives: list[dict] = Field(default_factory=list)


def validation_errors(errors):
    """No input values in diagnostics (or logs); use the same messages in both UIs."""
    messages = {
        "missing": "Обязательное поле не заполнено.",
        "int_type": "Возраст должен быть целым числом от 1 до 120.",
        "greater_than_equal": "Возраст должен быть от 1 до 120.",
        "less_than_equal": "Возраст должен быть от 1 до 120.",
        "literal_error": "Выберите допустимое значение поля.",
        "list_type": "Ожидается список допустимых кодов жалоб.",
        "extra_forbidden": "Это поле не входит в анкету демо.",
        "model_type": "Ожидается JSON-объект с полями анкеты.",
        "dict_type": "Ожидается JSON-объект с полями анкеты.",
        "json_invalid": "Некорректный JSON.",
    }
    result = []
    for error in errors:
        loc = [str(p) for p in error.get("loc", ()) if p != "body"]
        kind = error["type"]
        message = messages.get(kind, "Проверьте формат значения.")
        if kind.startswith("date_"):
            message = "Укажите существующую дату в формате ГГГГ-ММ-ДД."
        if kind == "value_error":
            message = error["msg"].removeprefix("Value error, ")
        result.append({"scope": "input", "field": ".".join(loc) or "body",
                       "code": kind, "message": message})
    return result


def invalid_result(errors):
    return PlanResult(status="invalid", errors=errors).model_dump(mode="json")
