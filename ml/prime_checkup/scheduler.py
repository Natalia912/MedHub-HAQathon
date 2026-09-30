"""Finite, deterministic backtracking for the explicitly fictional demo slots.

Times are integer minutes and occupied intervals are half-open. A procedure can
only start at the beginning of one of its listed slots.
"""

from copy import deepcopy
import json
from pathlib import Path


FIXTURE_CASES = ("feasible", "backtracking", "no_slot", "missing", "conflict")


def load_fixture(case: str) -> dict:
    """Return a fresh variant; never modify a fixture shared across requests."""
    if case not in FIXTURE_CASES:
        raise ValueError("Неизвестный технический пример")
    source = Path(__file__).parent / "data" / "scheduler_demo.json"
    fixture = deepcopy(json.loads(source.read_text(encoding="utf-8")))
    by_id = {procedure["id"]: procedure for procedure in fixture["procedures"]}
    if case == "feasible":
        by_id["DEMO_A"]["slots"] = [[600, 620]]
    elif case == "no_slot":
        by_id["DEMO_B"]["slots"] = []
    elif case == "missing":
        del by_id["DEMO_C"]["duration_minutes"]
    elif case == "conflict":
        by_id["DEMO_A"]["slots"] = [[540, 560]]
    return fixture


def _error(field: str, code: str, message: str) -> dict:
    return {"scope": "data", "field": field, "code": code, "message": message}


def _integer(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _interval(value) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and all(_integer(point) for point in value)
        and 0 <= value[0] < value[1] <= 1440
    )


def _overlap(start: int, end: int, other_start: int, other_end: int) -> bool:
    return start < other_end and other_start < end


def _string_list(value) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and item for item in value)


def _inspect_fixture(fixture: dict) -> tuple[list, list]:
    """Separate unavailable data from malformed data before starting search."""
    errors, missing = [], []
    if not isinstance(fixture, dict):
        return [_error("fixture", "INVALID_TYPE", "Данные расписания должны быть объектом.")], []

    def required(container, key, path):
        if key not in container or container[key] is None:
            missing.append(_error(path, "MISSING_DATA", "Не указано обязательное поле расписания."))
            return False
        return True

    if required(fixture, "patient_window", "patient_window") and not _interval(fixture["patient_window"]):
        errors.append(_error("patient_window", "INVALID_INTERVAL", "Некорректный интервал времени пациента."))
    if required(fixture, "transition_minutes", "transition_minutes"):
        transition = fixture["transition_minutes"]
        if not _integer(transition) or transition < 0:
            errors.append(_error("transition_minutes", "INVALID_VALUE", "Буфер перехода должен быть целым неотрицательным числом."))

    resources = fixture.get("resources")
    if required(fixture, "resources", "resources") and (
        not _string_list(resources) or len(resources) != len(set(resources))
    ):
        errors.append(_error("resources", "INVALID_RESOURCES", "Ресурсы должны быть списком уникальных идентификаторов."))
    known_resources = set(resources) if _string_list(resources) else set()

    required_ids = None
    if required(fixture, "package", "package"):
        package = fixture["package"]
        if not isinstance(package, dict):
            errors.append(_error("package", "INVALID_TYPE", "Пакет должен быть объектом."))
        elif required(package, "required_ids", "package.required_ids"):
            required_ids = package["required_ids"]
            if not _string_list(required_ids) or len(required_ids) != len(set(required_ids)):
                errors.append(_error("package.required_ids", "INVALID_IDS", "Обязательные действия должны быть списком уникальных ID."))

    procedures = fixture.get("procedures")
    by_id = {}
    if required(fixture, "procedures", "procedures"):
        if not isinstance(procedures, list):
            errors.append(_error("procedures", "INVALID_TYPE", "Процедуры должны быть списком."))
        else:
            for index, procedure in enumerate(procedures):
                path = f"procedures.{index}"
                if not isinstance(procedure, dict):
                    errors.append(_error(path, "INVALID_TYPE", "Процедура должна быть объектом."))
                    continue
                procedure_id = procedure.get("id")
                if required(procedure, "id", f"{path}.id"):
                    if not isinstance(procedure_id, str) or not procedure_id:
                        errors.append(_error(f"{path}.id", "INVALID_ID", "ID должен быть непустой строкой."))
                    elif procedure_id in by_id:
                        errors.append(_error(f"{path}.id", "DUPLICATE_ID", "ID процедуры повторяется."))
                    else:
                        by_id[procedure_id] = procedure
                        path = f"procedures.{procedure_id}"
                if required(procedure, "name", f"{path}.name") and (
                    not isinstance(procedure["name"], str) or not procedure["name"]
                ):
                    errors.append(_error(f"{path}.name", "INVALID_NAME", "Название должно быть непустой строкой."))
                if required(procedure, "duration_minutes", f"{path}.duration_minutes"):
                    duration = procedure["duration_minutes"]
                    if not _integer(duration) or duration <= 0:
                        errors.append(_error(f"{path}.duration_minutes", "INVALID_DURATION", "Длительность должна быть положительным целым числом."))
                if required(procedure, "slots", f"{path}.slots"):
                    slots = procedure["slots"]
                    if not isinstance(slots, list):
                        errors.append(_error(f"{path}.slots", "INVALID_TYPE", "Слоты должны быть списком интервалов."))
                    else:
                        for slot_index, slot in enumerate(slots):
                            if not _interval(slot):
                                errors.append(_error(f"{path}.slots.{slot_index}", "INVALID_INTERVAL", "Слот должен быть интервалом целых минут [начало, конец), начало < конец."))
                for key in ("resources", "predecessors"):
                    if required(procedure, key, f"{path}.{key}"):
                        value = procedure[key]
                        if not _string_list(value) or len(value) != len(set(value)):
                            errors.append(_error(f"{path}.{key}", "INVALID_IDS", "Ожидается список уникальных ID."))
                if _string_list(procedure.get("resources")) and _string_list(resources):
                    for resource in procedure["resources"]:
                        if resource not in known_resources:
                            errors.append(_error(f"{path}.resources", "UNKNOWN_RESOURCE", f"Неизвестный ресурс: {resource}."))

    if isinstance(procedures, list):
        if _string_list(required_ids):
            for procedure_id in required_ids:
                if procedure_id not in by_id:
                    errors.append(_error("package.required_ids", "UNKNOWN_ID", f"Неизвестная обязательная процедура: {procedure_id}."))
        for procedure_id, procedure in by_id.items():
            predecessors = procedure.get("predecessors")
            if _string_list(predecessors):
                for predecessor in predecessors:
                    if predecessor not in by_id:
                        errors.append(_error(f"procedures.{procedure_id}.predecessors", "UNKNOWN_ID", f"Неизвестный предшественник: {predecessor}."))
                    elif _string_list(required_ids) and procedure_id in required_ids and predecessor not in required_ids:
                        errors.append(_error(f"procedures.{procedure_id}.predecessors", "REQUIRED_PREDECESSOR_MISSING", f"Обязательное действие требует не включённого в план предшественника: {predecessor}."))

        # Kahn's algorithm avoids recursion while checking all known references.
        graph = {
            procedure_id: set(procedure.get("predecessors", [])) & by_id.keys()
            for procedure_id, procedure in by_id.items()
            if _string_list(procedure.get("predecessors", []))
        }
        pending = set(graph)
        while pending:
            ready = {procedure_id for procedure_id in pending if not graph[procedure_id] & pending}
            if not ready:
                errors.append(_error("procedures.predecessors", "DEPENDENCY_CYCLE", "Обнаружен цикл зависимостей процедур."))
                break
            pending -= ready

    resource_busy = fixture.get("resource_busy", {})
    if not isinstance(resource_busy, dict):
        errors.append(_error("resource_busy", "INVALID_TYPE", "Занятость ресурсов должна быть объектом."))
    else:
        for resource, intervals in resource_busy.items():
            if _string_list(resources) and resource not in known_resources:
                errors.append(_error(f"resource_busy.{resource}", "UNKNOWN_RESOURCE", "Неизвестный ресурс в занятости."))
            if not isinstance(intervals, list):
                errors.append(_error(f"resource_busy.{resource}", "INVALID_TYPE", "Занятость должна быть списком интервалов."))
            else:
                for index, interval in enumerate(intervals):
                    if not _interval(interval):
                        errors.append(_error(f"resource_busy.{resource}.{index}", "INVALID_INTERVAL", "Некорректный интервал занятости ресурса."))
    return errors, missing


def validate_schedule(fixture: dict, route: list) -> list:
    """Independently verify completeness and every constraint of a found route."""
    errors, missing = _inspect_fixture(fixture)
    if errors or missing:
        return errors + missing
    if not isinstance(route, list):
        return [_error("route", "INVALID_TYPE", "Маршрут должен быть списком.")]
    procedures = {procedure["id"]: procedure for procedure in fixture["procedures"]}
    required_ids = set(fixture["package"]["required_ids"])
    placed = {}
    valid_rows = []
    for index, row in enumerate(route):
        path = f"route.{index}"
        if not isinstance(row, dict):
            errors.append(_error(path, "INVALID_TYPE", "Позиция маршрута должна быть объектом."))
            continue
        procedure_id = row.get("procedure_id")
        if not isinstance(procedure_id, str) or procedure_id not in required_ids:
            errors.append(_error(f"{path}.procedure_id", "UNEXPECTED_ID", "В маршруте есть действие вне обязательного состава."))
            continue
        if procedure_id in placed:
            errors.append(_error(f"{path}.procedure_id", "DUPLICATE_ID", "Действие в маршруте повторяется."))
        placed[procedure_id] = row
        procedure = procedures[procedure_id]
        start, end = row.get("start"), row.get("end")
        if not _interval([start, end]):
            errors.append(_error(path, "INVALID_INTERVAL", "Некорректный занятый интервал маршрута."))
            continue
        valid_rows.append(row)
        if end != start + procedure["duration_minutes"]:
            errors.append(_error(path, "DURATION_MISMATCH", "Длительность в маршруте отличается от исходной."))
        if not any(start == slot[0] and end <= slot[1] for slot in procedure["slots"]):
            errors.append(_error(path, "SLOT_MISMATCH", "Действие не соответствует началу или вместимости слота."))
        window = fixture["patient_window"]
        if start < window[0] or end > window[1]:
            errors.append(_error(path, "OUTSIDE_PATIENT_WINDOW", "Действие выходит за время пациента."))
        row_resources = row.get("resources")
        if not _string_list(row_resources) or sorted(row_resources) != sorted(procedure["resources"]):
            errors.append(_error(f"{path}.resources", "RESOURCE_MISMATCH", "Ресурсы в маршруте отличаются от исходных."))
        for resource in procedure["resources"]:
            for busy in fixture.get("resource_busy", {}).get(resource, []):
                if _overlap(start, end, *busy):
                    errors.append(_error(path, "RESOURCE_BUSY", f"Ресурс {resource} занят."))
    for procedure_id in sorted(required_ids - placed.keys()):
        errors.append(_error("route", "INCOMPLETE", f"Обязательное действие отсутствует: {procedure_id}."))

    # Resource conflicts are checked independently from patient overlap.
    transition = fixture["transition_minutes"]
    for index, row in enumerate(valid_rows):
        procedure = procedures[row["procedure_id"]]
        for other in valid_rows[index + 1:]:
            if _overlap(row["start"], row["end"] + transition, other["start"], other["end"] + transition):
                errors.append(_error("route", "PATIENT_OVERLAP", "Время пациента или буфер перехода пересекается."))
            shared = set(procedure["resources"]) & set(procedures[other["procedure_id"]]["resources"])
            if shared and _overlap(row["start"], row["end"], other["start"], other["end"]):
                errors.append(_error("route", "RESOURCE_OVERLAP", f"Ресурс используется одновременно: {', '.join(sorted(shared))}."))
        for predecessor_id in procedure["predecessors"]:
            predecessor = placed.get(predecessor_id)
            if predecessor is not None and _integer(predecessor.get("end")) and predecessor["end"] > row["start"]:
                errors.append(_error("route", "DEPENDENCY_VIOLATION", f"Предшественник {predecessor_id} не завершён к началу {procedure['id']}."))
    return errors


def schedule_visit(fixture: dict, max_nodes: int | None = 10000) -> dict:
    """Find the first full feasible route, or honestly report why none is shown."""
    result = {"status": "not_run", "route": [], "after_results": [], "reason": None, "errors": []}
    errors, missing = _inspect_fixture(fixture)
    if errors:
        result.update(reason="Ошибка исходных данных расписания.", errors=errors + missing)
        return result
    if missing:
        result.update(status="needs_data", reason="Не хватает обязательных данных расписания.", errors=missing)
        return result
    if max_nodes is not None and (not _integer(max_nodes) or max_nodes < 0):
        result.update(reason="Некорректный лимит поиска.", errors=[_error("max_nodes", "INVALID_LIMIT", "Лимит поиска должен быть целым неотрицательным числом или null.")])
        return result
    procedures = {procedure["id"]: procedure for procedure in fixture["procedures"]}
    required_ids = set(fixture["package"]["required_ids"])
    for procedure_id in sorted(required_ids):
        if not procedures[procedure_id]["slots"]:
            result.update(status="infeasible", reason=f"NO_AVAILABLE_SLOT: {procedure_id} — для обязательного действия нет доступных слотов.")
            return result

    placed = {}
    nodes = 0
    limit_reached = False
    transition = fixture["transition_minutes"]

    def can_place(procedure, start, end, slot):
        window = fixture["patient_window"]
        if end > slot[1] or start < window[0] or end > window[1]:
            return False
        if any(placed[predecessor]["end"] > start for predecessor in procedure["predecessors"]):
            return False
        for row in placed.values():
            patient_conflict = _overlap(start, end + transition, row["start"], row["end"] + transition)
            resource_conflict = bool(set(procedure["resources"]) & set(row["resources"])) and _overlap(start, end, row["start"], row["end"])
            if patient_conflict or resource_conflict:
                return False
        for resource in procedure["resources"]:
            if any(_overlap(start, end, *busy) for busy in fixture.get("resource_busy", {}).get(resource, [])):
                return False
        return True

    def search():
        nonlocal nodes, limit_reached
        if required_ids == placed.keys():
            return True
        ready = [
            procedures[procedure_id] for procedure_id in required_ids - placed.keys()
            if all(predecessor in placed for predecessor in procedures[procedure_id]["predecessors"])
        ]
        procedure = min(ready, key=lambda item: (len(item["slots"]), item["id"]))
        for slot in sorted(procedure["slots"]):
            if max_nodes is not None and nodes >= max_nodes:
                limit_reached = True
                return False
            nodes += 1
            start = slot[0]
            end = start + procedure["duration_minutes"]
            if not can_place(procedure, start, end, slot):
                continue
            placed[procedure["id"]] = {"procedure_id": procedure["id"], "name": procedure["name"], "start": start, "end": end, "resources": list(procedure["resources"])}
            if search():
                return True
            del placed[procedure["id"]]
            if limit_reached:
                return False
        return False

    if search():
        route = sorted(placed.values(), key=lambda row: (row["start"], row["procedure_id"]))
        validation_errors = validate_schedule(fixture, route)
        if validation_errors:
            result.update(reason="Проверка найденного маршрута обнаружила ошибку; маршрут не показан как готовый.", errors=validation_errors)
        else:
            result.update(status="feasible", route=route)
    elif limit_reached:
        result.update(status="unknown", reason="Достигнут лимит поиска; наличие полного допустимого маршрута не установлено.")
    else:
        result.update(status="infeasible", reason="При заданных слотах полный план не найден после полного перебора.")
    return result
