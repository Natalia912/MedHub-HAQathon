"""Order the user's selected actions and reuse the existing slot search.

Catalog service IDs and scheduling action IDs deliberately remain separate.
Category edges describe only this selection, while explicit predecessors retain
their meaning even when the user has omitted the referenced service.
"""

from copy import deepcopy

from .scheduler import _inspect_fixture, schedule_visit


def _issue(field, code, message):
    return {"scope": "data", "field": field, "code": code, "message": message}


def _topological(graph):
    pending, ordered = set(graph), []
    while pending:
        ready = sorted(pid for pid in pending if not graph[pid] & pending)
        if not ready:
            return None
        pid = ready[0]
        pending.remove(pid)
        ordered.append(pid)
    return ordered


def plan_actions(items, package_id, slots, availability, by_id, requires_review=False):
    """Return a complete order, unresolved actions, or a validated timed route.

    Only malformed data goes into top-level ``errors``. Missing technical data
    remains in ``schedule.errors``; omitted known prerequisites are a review of
    the preserved selection, not a corruption of the catalog.
    """
    result = {
        "route": [], "route_status": "draft", "unresolved_items": [],
        "schedule": {"status": "not_run", "route": [], "after_results": [],
                     "reason": None, "errors": []},
        "after_results": [], "errors": [], "requires_review": bool(requires_review),
    }

    def invalid(errors):
        result["errors"] = errors
        result["route"] = []
        result["route_status"] = "unresolved"
        result["schedule"].update(status="not_run", route=[], reason="Ошибка данных маршрута; план не построен.", errors=errors)
        return result

    if not isinstance(slots, dict) or not isinstance(slots.get("procedures", {}), dict):
        return invalid([_issue("slots.procedures", "INVALID_TYPE", "Технические данные действий должны быть словарём.")])
    variants = slots.get("slots", {})
    if not isinstance(variants, dict) or not isinstance(variants.get(availability, {}), dict):
        return invalid([_issue("slots.slots", "INVALID_TYPE", "Варианты доступности должны быть словарями.")])
    metadata, available = slots.get("procedures", {}), variants.get(availability, {})
    actions = [action for item in items for action in (item.get("actions") or [item])]
    action_map = {}
    for action in actions:
        pid = action["procedure_id"]
        if pid not in by_id:
            return invalid([_issue("items", "UNKNOWN_ID", f"Неизвестное действие каталога: {pid}.")])
        if pid in action_map:
            return invalid([_issue("items", "DUPLICATE_ACTION", f"Действие выбрано повторно: {pid}.")])
        action_map[pid] = action
    selected = set(action_map)
    day_ids = {pid for pid, action in action_map.items() if not action.get("after_results", False)}
    graph, categories, errors, order_missing, conflicts = {}, {}, [], [], []

    for pid in sorted(selected):
        meta = metadata.get(pid, {})
        if not isinstance(meta, dict):
            errors.append(_issue(f"procedures.{pid}", "INVALID_TYPE", "Повреждены технические данные действия."))
            continue
        category = meta.get("category")
        if category is None:
            order_missing.append(_issue(f"procedures.{pid}.category", "MISSING_DATA", "Не задана категория порядка дня."))
        elif type(category) is not int or category not in range(-1, 6):
            errors.append(_issue(f"procedures.{pid}.category", "INVALID_CATEGORY", "Неизвестная категория порядка дня."))
        else:
            categories[pid] = category
        predecessors = meta.get("predecessors")
        graph[pid] = set()
        if predecessors is None:
            order_missing.append(_issue(f"procedures.{pid}.predecessors", "MISSING_DATA", "Не заданы сведения о явных предпосылках действия."))
            continue
        if (not isinstance(predecessors, list) or
                any(not isinstance(value, str) or not value for value in predecessors) or
                len(set(predecessors)) != len(predecessors)):
            errors.append(_issue(f"procedures.{pid}.predecessors", "INVALID_IDS", "Предпосылки должны быть списком уникальных ID."))
            continue
        for predecessor in predecessors:
            if predecessor not in by_id:
                errors.append(_issue(f"procedures.{pid}.predecessors", "UNKNOWN_ID", f"Неизвестная явная предпосылка: {predecessor}."))
            elif predecessor not in selected:
                conflicts.append({"action_id": pid, "procedure_id": action_map[pid].get("parent_procedure_id") or pid,
                                  "prerequisite_id": predecessor, "code": "REQUIRED_PREDECESSOR_MISSING",
                                  "field": f"procedures.{pid}.predecessors",
                                  "message": f"Для действия «{action_map[pid]['name']}» явно требуется {predecessor}, отсутствующее в выборе. Выбор сохранён; обсудите зависимость с врачом."})
            else:
                graph[pid].add(predecessor)
                if pid in day_ids and predecessor not in day_ids:
                    conflicts.append({"action_id": pid, "procedure_id": action_map[pid].get("parent_procedure_id") or pid,
                                      "prerequisite_id": predecessor, "code": "AFTER_RESULTS_PREREQUISITE",
                                      "field": f"procedures.{pid}.predecessors",
                                      "message": "Действие дня зависит от действия после результатов; требуется решение о порядке визитов."})
    if errors:
        return invalid(errors)
    # Day categories do not make unselected services mandatory. Actions within
    # one category stay independent, letting actual slots determine their order.
    for pid in day_ids:
        if pid in categories:
            graph[pid].update(other for other in day_ids
                              if other in categories and categories[other] < categories[pid])
    ordered = _topological(graph)
    if ordered is None:
        return invalid([_issue("procedures.predecessors", "DEPENDENCY_CYCLE", "Цикл явных зависимостей или конфликт с порядком категорий.")])

    def public_row(pid, status="draft"):
        action = action_map[pid]
        return {"action_id": pid, "procedure_id": action.get("parent_procedure_id") or pid,
                "name": action["name"], "category": categories.get(pid), "status": status}

    result["after_results"] = [{**public_row(pid), "reason": "после готовности результатов"}
                               for pid in ordered if pid not in day_ids]
    result["schedule"]["after_results"] = deepcopy(result["after_results"])
    fixture = {"id": "selected-prime-technical-day",
               "package": {"id": package_id, "required_ids": sorted(day_ids)}, "procedures": []}
    for key in ("patient_window", "transition_minutes", "resources", "resource_busy"):
        if key in slots:
            fixture[key] = deepcopy(slots[key])
    for pid in sorted(day_ids):
        meta = metadata.get(pid, {})
        procedure = {"id": pid, "name": action_map[pid]["name"]}
        for key in ("duration_minutes", "resources"):
            if key in meta:
                procedure[key] = deepcopy(meta[key])
        if "predecessors" in meta and meta["predecessors"] is not None:
            # Missing selected prerequisites have already been reported above;
            # never silently use this reduced graph to run a successful search.
            procedure["predecessors"] = sorted(graph[pid] & day_ids)
        if pid in available:
            procedure["slots"] = deepcopy(available[pid])
        fixture["procedures"].append(procedure)

    # Reuse the scheduler's data checks even when a clinical review prevents
    # search. A malformed interval must not masquerade as a lack of free time.
    data_errors, missing = _inspect_fixture(fixture)
    if data_errors:
        return invalid(data_errors)
    result["requires_review"] = bool(requires_review or conflicts)
    if order_missing or conflicts:
        result["route_status"] = "unresolved"
        result["unresolved_items"] = deepcopy(conflicts)
        for issue in order_missing:
            pid = issue["field"].split(".")[1]
            result["unresolved_items"].append({**public_row(pid), **issue})
        # List remaining day actions explicitly, without showing a partial order
        # as a complete route for the selection.
        unresolved_ids = {row["action_id"] for row in result["unresolved_items"]}
        for pid in sorted(day_ids - unresolved_ids):
            result["unresolved_items"].append({**public_row(pid), "code": "ORDER_UNRESOLVED",
                                                "message": "Полный порядок выбранных действий пока не определён."})
        result["schedule"].update(status="not_run" if result["requires_review"] else "needs_data",
                                  reason="Нужно уточнить порядок или явные предпосылки выбранных действий.",
                                  errors=missing + order_missing)
        return result

    result["route"] = [public_row(pid) for pid in ordered if pid in day_ids]
    if requires_review:
        result["schedule"]["reason"] = "Проект порядка требует решения врача по выбранным позициям; поиск времени не запускался."
        return result
    result["schedule"] = schedule_visit(fixture)
    result["schedule"]["after_results"] = deepcopy(result["after_results"])
    if result["schedule"]["status"] == "not_run" and result["schedule"].get("errors"):
        return invalid(result["schedule"]["errors"])
    if result["schedule"]["status"] == "feasible":
        # schedule_visit independently validates its native action-ID route.
        # Convert IDs only afterwards, retaining chronological order unchanged.
        rows = result["schedule"]["route"]
        result["route"] = [public_row(row["procedure_id"], "ready") for row in rows]
        result["schedule"]["route"] = [
            {**row, **public_row(row["procedure_id"], "ready")} for row in rows
        ]
        result["route_status"] = "ready"
    return result
