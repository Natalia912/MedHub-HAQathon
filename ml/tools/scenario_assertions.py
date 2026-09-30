"""Concrete card assertions over captured responses, never a second engine.

Inputs and expected sets come from the frozen DOCX transcription. This module
does not import the application, issue requests, choose packages, or search slots.
"""
from copy import deepcopy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_S23_SNAPSHOTS = {}


def _path(value, path):
    for key in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _ids(rows):
    return [row.get("procedure_id") for row in rows]


def evaluate_special(run, rec_request, plan_request):
    """Append named, inspectable checks for this state; never treat 422 as PASS."""
    state, expected = run.state, run.state["expected"]
    r, p = rec_request.get("response") or {}, plan_request.get("response") or {}
    norm = run.result.get("normalized") or {}
    patient = state.get("request", {}).get("patient", {})
    rec_items = {row["procedure_id"]: row for row in r.get("items", [])}
    items = {row["procedure_id"]: row for row in p.get("selected_items", [])}
    rec_screen = {row["rule_id"]: row for row in r.get("screening", [])}
    plan_screen = {row["rule_id"]: row for row in p.get("screening", [])}
    answers = norm.get("answers", {})
    card = state["card_id"]
    step = state["id"].split("-")[-1]
    fixture = json.loads((ROOT / "tests/fixtures/prime_scenarios.json").read_text(encoding="utf-8"))
    mapping = {row["procedure_id"]: row for row in fixture["catalog_mapping"]}
    selected = set(expected.get("plan", {}).get("selected_ids", []))
    recommended = set(expected.get("recommend", {}).get("item_ids", []))
    expected_removed = set(expected.get("plan", {}).get("removed_ids", []))
    expected_added = set(expected.get("plan", {}).get("added_ids", []))
    intentional_error = expected.get("plan", {}).get("http") == 422

    def emit(name, target, actual, ok=None, *, needs=("rec", "plan"), basis="PROJECT", verdict=None, reason=None):
        blocked = []
        if "rec" in needs and (rec_request.get("http") != 200 or r.get("status") == "invalid"):
            blocked.append("/recommend не принял анкету: HTTP " + str(rec_request.get("http")))
        if "plan" in needs and (plan_request.get("http") != 200 or p.get("status") == "invalid"):
            blocked.append("/plan не вернул бизнес-результат: HTTP " + str(plan_request.get("http")))
        if "normalized" in needs and (not norm or run.result.get("normalization_errors")):
            blocked.append("Публичная нормализация не приняла исходные факты")
        run.check(name, target, actual, ok=ok, basis=basis,
                  blocked="; ".join(blocked) or None, verdict=verdict, reason=reason,
                  classification="MAPPING/CONTRACT" if blocked else "CODE")

    def both_fields(fields):
        return {phase: {key: _path(data, key) for key in fields} for phase, data in (("recommend", r), ("plan", p))}

    def flag_codes(item):
        return {flag.get("code") for flag in item.get("clinical_flags", [])}

    def selected_actions():
        return p.get("route", []) + p.get("after_results", []) + p.get("unresolved_items", [])

    def exact_selection():
        return sorted(selected) == sorted(_ids(p.get("selected_items", [])))

    def no_new_results(data):
        return all(row.get("status") == "не пройдено" and row.get("result") == "нет данных"
                   for row in data.get("health_card", []))

    def history_check(name, only=None):
        wanted = [row for row in expected.get("history", []) if only is None or row["screening_id"] in only]
        by_id = {row["screening_id"]: row for row in norm.get("history", [])}
        actual = [{key: by_id.get(row["screening_id"], {}).get(key) for key in row} for row in wanted]
        emit(name, wanted, actual, needs=("normalized",), basis="CONTRACT_GAP")

    def stopped(name, status):
        fields = {"status": status, "package": None, "items": [], "route": [],
                  "after_results": [], "health_card": [], "schedule.status": "not_run"}
        emit(name, {phase: fields for phase in ("recommend", "plan")}, both_fields(fields))

    def doctor_values(name, fields):
        target = {key: patient[key] for key in fields if key in patient}
        actual = {phase: {row["field"]: row.get("value") for row in data.get("doctor_summary", []) if row["field"] in target}
                  for phase, data in (("recommend", r), ("plan", p))}
        emit(name, {"recommend": target, "plan": target}, actual)

    def named(name):
        if name in {"female_basic_exact", "selection_exact", "mini_not_extended", "extended_instead_of_mini"}:
            actual = {"recommended": sorted(rec_items), "selected": sorted(items)}
            emit(name, {"recommended": sorted(recommended), "selected": sorted(selected)}, actual,
                 needs=("rec",) if intentional_error else ("rec", "plan"))
        elif name in {"curator_one_service_two_actions", "pediatric_conclusion_after_results", "after_results_only_selected"}:
            after = p.get("after_results", [])
            if name == "curator_one_service_two_actions":
                pid = "prime_curator_consultation_group"
                target = {"services": 1, "actions": ["prime_curator_final", "prime_curator_initial"],
                          "day": ["prime_curator_initial"], "after": ["prime_curator_final"]}
                actual = {"services": _ids(p.get("selected_items", [])).count(pid),
                          "actions": sorted(a.get("action_id") for a in items.get(pid, {}).get("actions", [])),
                          "day": sorted(a.get("action_id") for a in p.get("route", []) if a.get("procedure_id") == pid),
                          "after": sorted(a.get("action_id") for a in after if a.get("procedure_id") == pid)}
            elif name == "pediatric_conclusion_after_results":
                pid = "prime_pediatric_conclusion"
                target = {"selected": True, "day": [], "after": [pid]}
                actual = {"selected": pid in items, "day": [a.get("action_id") for a in p.get("route", []) if a.get("procedure_id") == pid],
                          "after": [a.get("action_id") for a in after if a.get("procedure_id") == pid]}
            else:
                target, actual = True, all(a.get("procedure_id") in selected for a in after)
            emit(name, target, actual)
        elif name in {"h0_preserved", "history_years_preserved", "history"}:
            history_check(name)
        elif name in {"history_range_not_year", "history_known_year_not_date"}:
            history_check(name, {"scr_breast"})
        elif name in {"groups_opaque", "item_sources", "catalog_mapping"}:
            mismatches = []
            for phase, data in (("recommend", r), ("plan", p)):
                for item in data.get("items", []):
                    source = mapping.get(item.get("procedure_id"))
                    if source is None or item.get("name") != source["source_name"] or item.get("is_group") != source["is_group"]:
                        mismatches.append({"phase": phase, "procedure_id": item.get("procedure_id"), "problem": "source_name_or_group"})
                    if not item.get("source") or not item.get("source_package_ids"):
                        mismatches.append({"phase": phase, "procedure_id": item.get("procedure_id"), "problem": "missing_origin"})
                    if source:
                        action_ids = [a.get("action_id") for a in item.get("actions", [])] or [item.get("procedure_id")]
                        if sorted(action_ids) != sorted(source["action_ids"]):
                            mismatches.append({"phase": phase, "procedure_id": item.get("procedure_id"), "problem": "invented_or_missing_actions", "actions": action_ids})
            emit(name, [], mismatches)
        elif name in {"screening_not_prime", "payment_not_guaranteed"}:
            actual = {"selection_matches_source": exact_selection(),
                      "all_selected_ids_prime": all(pid in mapping for pid in items),
                      "separate_rules": all(sid.startswith("scr_") for sid in rec_screen),
                      "payment_conditional": all(row.get("payment", {}).get("guaranteed") is False for row in list(rec_screen.values()) + list(plan_screen.values()))}
            emit(name, dict.fromkeys(actual, True), actual,
                 needs=("rec",) if intentional_error else ("rec", "plan"))
        elif name == "child_adult_answers_not_invented":
            fields = ("smoking", "hazardous_work_10y", "risk_group", "pregnant", "discharge", "dysuria")
            actual = {"request_omits": all(key not in patient for key in fields),
                      "smoking_pack_years": norm.get("smoking", {}).get("pack_years"),
                      "smoking_quit_years": norm.get("smoking", {}).get("quit_years_ago"),
                      "pregnant": norm.get("pregnant")}
            emit(name, {"request_omits": True, "smoking_pack_years": None, "smoking_quit_years": None, "pregnant": None}, actual, needs=("normalized",))
        elif name == "hepatitis_majority_boundary":
            row = rec_screen.get("scr_hepatitis", {})
            actual = {"age_full": r.get("age_full"), "age_year": r.get("age_year"), "outcome": row.get("outcome"), "reason": row.get("reason")}
            emit(name, "17 полных / 18 по году; review или needs_input с объяснением границы совершеннолетия", actual,
                 ok=actual["age_full"] == 17 and actual["age_year"] == 18 and actual["outcome"] in {"review", "needs_input"} and bool(actual["reason"]), needs=("rec",), basis="CLINICIAN_REVIEW")
        elif name == "adult_answers_explicit":
            target = {"for_child": False, "dysuria": "no", "smoking": {"pack_years": 0}, "hazardous_work_10y": False, "registered": ["none"]}
            actual = {key: answers.get(key, {}).get("value") for key in target}
            emit(name, target, actual, needs=("normalized",))
        elif name == "adult_for_child_conflict_blocks_child":
            actual = both_fields(["status", "package", "schedule.status", "route"])
            target = {phase: {"status": "needs_input", "package": None, "schedule.status": "not_run", "route": []} for phase in ("recommend", "plan")}
            emit(name, target, actual)
        elif name == "ct_names_not_merged":
            pid = "prime_lung_ct" if step == "A" else "prime_chest_ct"
            other = "prime_chest_ct" if step == "A" else "prime_lung_ct"
            emit(name, {"selected": pid, "name": mapping[pid]["source_name"], "other_absent": True},
                 {"selected": pid if pid in items else None, "name": items.get(pid, {}).get("name"), "other_absent": other not in items})
        elif name == "basic_no_mammography_or_pap":
            target = {"breast_ultrasound": True, "mammography": False, "pap": False}
            actual = {"breast_ultrasound": "prime_breast_ultrasound" in items, "mammography": "prime_mammography_2d3d" in items, "pap": "prime_pap_test" in items}
            emit(name, target, actual)
        elif name == "urgent_stops_both":
            stopped(name, "review")
        elif name == "urgent_question_both":
            stopped(name, "needs_input")
            emit(name + ".specific_question", True, all(any(q.get("field") == "urgent" and q.get("message") for q in data.get("questions", [])) for data in (r, p)))
        elif name == "screening_not_evaluated":
            emit(name, {"recommend": [], "plan": []}, {"recommend": r.get("screening"), "plan": p.get("screening")})
        elif name == "urgent_message_preserves_answer":
            phrase = {"chest_pain": "Боль или давление в груди", "dyspnea": "Сильная одышка", "stroke_signs": "трудно говорить"}.get(patient.get("urgent"))
            messages = {phase: [w.get("message", "") for w in data.get("warnings", []) if w.get("code") == "URGENT"] for phase, data in (("recommend", r), ("plan", p))}
            emit(name, {"expected_branch_fragment": phrase, "both_have_source": True}, messages,
                 ok=bool(phrase) and all(any(phrase in msg for msg in rows) for rows in messages.values()) and all(any(w.get("code") == "URGENT" and w.get("source") for w in data.get("warnings", [])) for data in (r, p)))
        elif name == "urgent_answer_closes_only_urgent":
            actual = {phase: [q for q in data.get("questions", []) if q.get("field") == "urgent"] for phase, data in (("recommend", r), ("plan", p))}
            emit(name, {"recommend": [], "plan": []}, actual)
        elif name in {"pregnancy_ct_mammography_only", "retained_mammography_review", "helicobacter_not_ct", "coverage_does_not_hide_clinical_flag"}:
            required = {"prime_chest_ct", "prime_mammography_2d3d"} & selected
            if name == "retained_mammography_review":
                required = {"prime_mammography_2d3d"}
            actual = {"required_flagged": sorted(pid for pid in required if "PREGNANCY_REVIEW" in flag_codes(items.get(pid, {}))),
                      "helicobacter_pregnancy_flags": sorted(flag_codes(items.get("prime_helicobacter_test", {})) & {"PREGNANCY_REVIEW", "PREGNANCY_UNKNOWN"}),
                      "status": p.get("status"), "schedule_status": p.get("schedule", {}).get("status")}
            target = {"required_flagged": sorted(required), "helicobacter_pregnancy_flags": [], "status": "review", "schedule_status": "not_run"}
            if name == "coverage_does_not_hide_clinical_flag":
                actual["independent_match"] = any(m.get("screening_id") == "scr_breast" for m in items.get("prime_mammography_2d3d", {}).get("screening_matches", []))
                target["independent_match"] = True
            emit(name, target, actual)
        elif name in {"pregnancy_missing_not_no", "reproductive_answers_not_pregnancy_proof"}:
            actual = {"normalized_pregnant": norm.get("pregnant"), "raw_answer": answers.get("pregnant", {}).get("value"),
                      "state": answers.get("pregnant", {}).get("state"), "ct_flags": sorted(flag_codes(items.get("prime_lung_ct", {})) & {"PREGNANCY_REVIEW", "PREGNANCY_UNKNOWN"}),
                      "status": p.get("status"), "schedule_status": p.get("schedule", {}).get("status")}
            target = {"normalized_pregnant": "unsure" if step == "A" else None, "raw_answer": "unsure" if step == "A" else None,
                      "state": "answered" if step == "A" else "unanswered", "ct_flags": ["PREGNANCY_REVIEW"] if step == "A" else ["PREGNANCY_UNKNOWN"], "status": "review", "schedule_status": "not_run"}
            emit(name, target, actual, needs=("normalized", "plan"))
        elif name == "registration_origin_distinct":
            registration = norm.get("registration", {})
            actual = {"confirmed": registration.get("confirmed_codes"), "ambiguous": registration.get("ambiguous_codes"),
                      "format": norm.get("input_format")}
            target = {"confirmed": ["breast_cancer"] if step == "C" else [], "ambiguous": ["breast_cancer"] if step == "B" else [], "format": "df733c4" if step == "B" else "clinic_v2"}
            emit(name, target, actual, needs=("normalized",), basis="CONTRACT_GAP")
        elif name in {"mammography_not_removed_by_screening", "paid_ct_stays_selected"}:
            pid = "prime_mammography_2d3d" if name.startswith("mammography") else "prime_chest_ct"
            actual = {"count": _ids(p.get("selected_items", [])).count(pid), "payment": items.get(pid, {}).get("payment"), "removed": pid in _ids(p.get("removed_recommended_items", [])), "new_result": next((row.get("result") for row in p.get("health_card", []) if row.get("procedure_id") == pid), None)}
            emit(name, {"count": 1, "payment": "paid_prime", "removed": False, "new_result": "нет данных"}, actual)
        elif name in {"unknown_smoking_not_zero", "quit_boundary_known"}:
            target = expected.get("normalized", {})
            actual = {path: _path(norm, path) for path in target}
            emit(name, target, actual, needs=("normalized",), basis="CONTRACT_GAP")
        elif name == "quit_boundary_source_conflict":
            row = rec_screen.get("scr_lung", {})
            reason = row.get("reason", "")
            emit(name, "review; reason retains 15 and both conflicting boundary descriptions", row,
                 ok=row.get("outcome") == "review" and "15" in reason and "менее" in reason and ("JSON" in reason or "quit_years_max" in reason), needs=("rec",), basis="CLINICIAN_REVIEW")
        elif name == "independent_registration_exclusion":
            target = {key: value for key, value in expected["recommend"]["screening"].items() if key in {"scr_cvd", "scr_breast", "scr_cervix", "scr_hepatitis"}}
            emit(name, target, {sid: rec_screen.get(sid, {}).get("outcome") for sid in target}, needs=("rec",), basis="RULE_SNAPSHOT")
        elif name == "where_changes_not_eligibility":
            expected_where = "Своя поликлиника прикрепления; учреждение и условия прохождения уточнить" if patient.get("attached_to") == "other" else "Поликлиника прикрепления Green Clinic; условия прохождения уточнить в регистратуре"
            actual = {sid: {"outcome": row.get("outcome"), "where": row.get("where"), "guaranteed": row.get("payment", {}).get("guaranteed")} for sid, row in rec_screen.items()}
            target = {sid: {"outcome": outcome, "where": expected_where, "guaranteed": False} for sid, outcome in expected["recommend"]["screening"].items()}
            emit(name, target, actual, needs=("rec",))
        elif name == "overlap_hba1c_exact_doppler_partial":
            target = {("scr_cvd", "prime_hba1c"): "exact", ("scr_cerebro", "prime_neck_leg_vessels_doppler"): "partial"}
            actual = {sid + "/" + pid: next((m.get("match_degree") for m in rec_screen.get(sid, {}).get("prime_matches", []) if m.get("procedure_id") == pid), None) for sid, pid in target}
            emit(name, {sid + "/" + pid: degree for (sid, pid), degree in target.items()}, actual, needs=("rec",), basis="CONTRACT_GAP")
        elif name == "anamnesis_context_preserved":
            doctor_values(name, ["conditions", "registered", "medications"])
        elif name == "draft_endo_out_of_scope":
            emit(name, "ANAMNESIS_DRAFT module is inactive; its proposed c_endo is not a required claim", "Неактивный модуль; контекст и отсутствие ложного назначения проверяются отдельными утверждениями", needs=(), verdict="OUT_OF_SCOPE", reason="Согласованный scope demo-3 не активирует 20 ANAMNESIS_DRAFT-правил.")
        elif name == "no_automatic_diagnosis_or_endo":
            actual = {"confirmed_codes": norm.get("registration", {}).get("confirmed_codes"), "ambiguous_codes": norm.get("registration", {}).get("ambiguous_codes"), "endo_selected": "c_endo" in items or "prime_endocrinology_consult" in items}
            emit(name, {"confirmed_codes": [], "ambiguous_codes": [], "endo_selected": False}, actual, needs=("normalized", "plan"))
        elif name in {"doctor_gets_drug_and_companion", "doctor_context"}:
            fields = ["blood_thinners", "companion", "medications"] if card == "S19" else ["conditions", "registered", "registered_on"]
            doctor_values(name, fields)
        elif name == "preparation_review_without_drug_instructions":
            pid = "prime_endoscopy_group"
            warnings = [flag.get("message", "") for flag in items.get(pid, {}).get("clinical_flags", [])]
            actual = {"recommend_status": r.get("status"), "plan_status": p.get("status"), "schedule_status": p.get("schedule", {}).get("status"), "endoscopy_requires_review": items.get(pid, {}).get("requires_review"), "messages": warnings}
            phrases = " ".join(warnings + [q.get("message", "") for q in p.get("questions", [])])
            # Check absence of concrete regimen commands, not a broad ban on explanatory words such as «отмена».
            forbidden = ["отмените препарат", "прекратите приём", "за 7 дней", "за 5 дней", "принимайте по", "мг в день"]
            ok = r.get("status") == p.get("status") == "review" and p.get("schedule", {}).get("status") == "not_run" and bool(warnings) and items.get(pid, {}).get("requires_review") is True and not any(s in phrases.lower() for s in forbidden)
            emit(name, "Both stages review; selected endoscopy flagged; no dose/withdrawal schedule", actual, ok=ok, basis="CLINICIAN_REVIEW")
        elif name == "endoscopy_group_not_split_or_removed":
            pid = "prime_endoscopy_group"
            actual = {"count": _ids(p.get("selected_items", [])).count(pid), "is_group": items.get(pid, {}).get("is_group"), "name": items.get(pid, {}).get("name"), "invented_parts": sorted(set(items) & {"prime_gastroscopy", "prime_colonoscopy"})}
            emit(name, {"count": 1, "is_group": True, "name": mapping[pid]["source_name"], "invented_parts": []}, actual)
        elif name == "age_dependent_child_groups_review":
            ids = ["prime_child_ecg_neurosonography_group", "prime_child_extended_ultrasound_group"]
            actual = {"selected_flagged": [pid for pid in ids if pid in items and "AGE_DEPENDENT_GROUP" in flag_codes(items[pid])], "status": p.get("status"), "schedule_status": p.get("schedule", {}).get("status")}
            emit(name, {"selected_flagged": ids, "status": "review", "schedule_status": "not_run"}, actual, basis="CLINICIAN_REVIEW")
        elif name in {"diff_against_automatic_mini", "diff_against_original_recommendation", "diff_exact"}:
            if intentional_error:
                # S23-D is a rejected conflict, not another accepted composition.
                # Diff semantics are exercised independently on S23-A/B/C.
                return
            actual = {"removed": sorted(_ids(p.get("removed_recommended_items", []))), "added": sorted(_ids(p.get("added_items", [])))}
            emit(name, {"removed": sorted(expected_removed), "added": sorted(expected_added)}, actual)
        elif name == "removed_warning_original_reason":
            actual = {}
            for pid in sorted(expected_removed):
                removal = next((row for row in p.get("removed_recommended_items", []) if row.get("procedure_id") == pid), {})
                why = rec_items.get(pid, {}).get("why")
                actual[pid] = {"why_preserved": bool(why) and removal.get("why") == why,
                               "warning_has_original_why": bool(why) and any(w.get("procedure_id") == pid and why in w.get("message", "") for w in p.get("warnings", [])), "not_restored": pid not in items}
            emit(name, {pid: {"why_preserved": True, "warning_has_original_why": True, "not_restored": True} for pid in expected_removed}, actual)
        elif name == "removed_actions_and_card_absent":
            used_ids = set(_ids(selected_actions())) | set(_ids(p.get("health_card", []))) | set(items)
            emit(name, [], sorted(expected_removed & used_ids))
        elif name == "removal_itself_not_review":
            emit(name, "ready", p.get("status"))
        elif name in {"urology_exact_source_not_c_uro_f", "manual_reason_not_medical", "duplicate_id_one_service_action_card"}:
            pid = "prime_urology_consult"
            item = items.get(pid, {})
            actual = {"selected_count": _ids(p.get("selected_items", [])).count(pid), "card_count": _ids(p.get("health_card", [])).count(pid),
                      "action_count": sum(a.get("procedure_id") == pid for a in selected_actions()), "name": item.get("name"), "source_package_ids": item.get("source_package_ids"),
                      "explanation": item.get("selection_reason", {}).get("explanation"), "wrong_id_present": "c_uro_f" in items}
            target = {"selected_count": 1, "card_count": 1, "action_count": 1, "name": mapping[pid]["source_name"], "source_package_ids": ["prime_extended"], "explanation": "Выбрано пользователем из каталога PRIME", "wrong_id_present": False}
            emit(name, target, actual)
        elif name == "earlier_response_copies_unchanged":
            changed = [sid for sid, record in _S23_SNAPSHOTS.items() if record["reference"] != record["frozen"]]
            emit(name, [], changed, needs=("rec",))
        elif name == "preset_conflict_not_ignored":
            if step == "D":
                actual = {"http": plan_request.get("http"), "code": _path(p, "error.code"), "route": p.get("route"), "schedule": _path(p, "schedule.status")}
                emit(name, {"http": 422, "code": "preset_mismatch", "route": [], "schedule": "not_run"}, actual, needs=("rec",))
            else:
                emit(name, expected["plan"].get("http", 200), plan_request.get("http"), needs=("rec",))
        elif name in {"empty_vs_missing_selection", "no_fallback_or_actions_for_empty"}:
            target = {"http": 200 if step == "A" else 422, "selected": [], "route": [], "after": [], "schedule": "not_run", "calls": 0}
            actual = {"http": plan_request.get("http"), "selected": _ids(p.get("selected_items", [])), "route": p.get("route"), "after": p.get("after_results"), "schedule": _path(p, "schedule.status"), "calls": plan_request.get("scheduler_calls")}
            target["status"] = "needs_input" if step == "A" else "invalid"
            actual["status"] = p.get("status")
            if step == "B":
                target["error"] = "missing"
                actual["error"] = _path(p, "error.code")
            emit(name, target, actual, needs=("rec",))
        elif name == "demo_flags":
            emit(name, {phase: {"demo": True, "medical_validated": False, "needs_doctor_review": True} for phase in ("recommend", "plan")}, both_fields(["demo", "medical_validated", "needs_doctor_review"]), needs=())
        elif name == "review_not_run":
            # Only applicable states contain an expected review outcome.
            phases = [phase for phase in ("recommend", "plan") if expected.get(phase, {}).get("status") == "review"]
            if not phases:
                return
            actual = {phase: {"status": data.get("status"), "schedule": _path(data, "schedule.status"), "calls": req.get("scheduler_calls")} for phase, data, req in (("recommend", r, rec_request), ("plan", p, plan_request)) if phase in phases}
            emit(name, {phase: {"status": "review", "schedule": "not_run", "calls": 0} for phase in phases}, actual)
        elif name == "context_dates":
            emit(name, {phase: state["request"]["context"] for phase in ("recommend", "plan")}, {"recommend": r.get("context"), "plan": p.get("context")})
        elif name == "intentional_omissions":
            wanted = state["profile_facts"]["explicit_omissions"]
            actual = {key: {"request_omitted": key not in patient, "original": answers.get(key, {}).get("value")} for key in wanted}
            emit(name, {key: {"request_omitted": True, "original": None} for key in wanted}, actual, needs=("normalized",))
        elif name == "normalized_negative_answers":
            fields = [key for key in ("conditions", "registered", "family_history") if patient.get(key) == ["none"]]
            actual = {key: answers.get(key, {}).get("value") for key in fields}
            emit(name, dict.fromkeys(fields, ["none"]), actual, needs=("normalized",))
        elif name == "health_card_unperformed":
            emit(name, {"ids": sorted(selected), "unperformed": True}, {"ids": sorted(_ids(p.get("health_card", []))), "unperformed": no_new_results(p)}, needs=("rec",) if expected.get("plan", {}).get("http") == 422 else ("plan",))
            if not selected:
                emit("empty_card_unperformed", [], p.get("health_card"), needs=("rec",) if intentional_error else ("plan",))
        elif name == "next_visit_without_date":
            actual = {"is_array": isinstance(p.get("next_visit"), list), "no_dates": all(row.get("date") is None and row.get("year") is None for row in p.get("next_visit", [])), "draft_date": _path(p, "reminder_draft.due_date"), "sent": _path(p, "reminder_draft.sent")}
            emit(name, {"is_array": True, "no_dates": True, "draft_date": None, "sent": False}, actual, needs=("rec",) if expected.get("plan", {}).get("http") == 422 else ("plan",))
        elif name == "no_price_calculation":
            actual = {"total_price": p.get("total_price")}
            target = {"total_price": None}
            if p.get("mode") == "custom":
                actual["price_text"], target["price_text"] = p.get("price_text"), "Стоимость — у администратора"
            emit(name, target, actual, needs=("rec",) if expected.get("plan", {}).get("http") == 422 else ("plan",))
        elif name == "variant_exact":
            target = {"recommended_variant": expected["recommend"].get("variant_id"), "selected_variant": state["selection"].get("variant_id")}
            actual = {"recommended_variant": _path(r, "package.variant_id"), "selected_variant": p.get("variant_id")}
            emit(name, target, actual)
        elif name == "stop_has_no_route_or_card":
            stopped(name, expected["recommend"].get("status", "needs_input"))
        elif name == "recommend.screening" and not expected.get("recommend", {}).get("screening"):
            # A global stop/urgent question deliberately does not evaluate rules.
            emit(name, [], r.get("screening"), needs=("rec",))
        elif name == "schedule_invariants" and (intentional_error or p.get("package") is None):
            # Rejected choices/global stops must not enter search. Their lack of
            # a complete route is an expected negative result, not unavailable data.
            actual = {"calls": plan_request.get("scheduler_calls"), "route": p.get("route"),
                      "schedule_route": _path(p, "schedule.route"), "status": _path(p, "schedule.status")}
            emit(name, {"calls": 0, "route": [], "schedule_route": [], "status": "not_run"}, actual,
                 needs=("rec",) if intentional_error else ("rec", "plan"))
        else:
            # General/normalization/scheduler checks are implemented by the root
            # runner. Reuse their actual verdicts instead of manufacturing PASS.
            prefixes = {"recommend.package": ["recommend.package_id"], "recommend.screening": ["recommend.scr_"],
                        "normalized": ["normalized."], "schedule_invariants": ["independent_schedule_validator", "complete_action_disposition", "review_no_search", "route_matches_chronology"],
                        "independent_validator": ["independent_schedule_validator"],
                        "native_scheduler_exact_fixture": ["fixture_status", "exact_intervals", "no_partial_success"],
                        "complete_search_no_limit": ["search_exhausted_not_limited"],
                        "fixture_unchanged": ["fixture_unchanged"]}.get(name, [name])
            checks = [row for row in run.result["assertions"] if any(row["name"].startswith(prefix) for prefix in prefixes)]
            blocked = not checks or any(row["verdict"] in {"BLOCKED", "NOT_RUN"} for row in checks)
            emit(name, "Все относящиеся конкретные проверки выполнены и подтверждены", [{"name": row["name"], "verdict": row["verdict"]} for row in checks],
                 ok=bool(checks) and all(row["verdict"] == "PASS" for row in checks), needs=(), verdict="BLOCKED" if blocked else None,
                 reason="Связанные конкретные проверки пока недоступны." if blocked else None)

    names = list(dict.fromkeys(expected.get("checks", [])))
    # Explicit aliases make original numbered assertion coverage inspectable.
    # Card-level assertions can refer to another step: only run a specialist
    # check where the frozen state's own check list actually schedules it.
    generic = {"recommend.package", "recommend.item_ids", "recommend.age_full", "recommend.age_year",
               "recommend.screening", "normalized", "history", "demo_flags", "item_sources",
               "catalog_mapping", "schedule_invariants", "screening_not_prime", "context_dates",
               "intentional_omissions", "normalized_negative_answers", "selection_exact", "diff_exact",
               "health_card_unperformed", "next_visit_without_date", "no_price_calculation", "payment_not_guaranteed",
               "recommend_no_search", "plan.error_code", "review_not_run", "doctor_context", "variant_exact"}
    generic.update({"h0_preserved", "curator_one_service_two_actions", "groups_opaque", "after_results_only_selected"})
    bound = {name for rows in state.get("assertion_checks", {}).values() for name in rows}
    for name in sorted(bound & generic):
        if name not in names:
            # Do not emit a phantom error check in a valid state of a multi-step card.
            if name == "plan.error_code" and "error_code" not in expected.get("plan", {}):
                continue
            if name == "normalized" and not expected.get("normalized"):
                continue
            if name == "curator_one_service_two_actions" and "prime_curator_consultation_group" not in selected:
                continue
            names.append(name)
    for name in names:
        # Root checks and aliases share the same stable assertion namespace.
        # Reuse an existing concrete check instead of counting it twice.
        if any(row["name"] == name for row in run.result["assertions"]):
            continue
        named(name)
    if card == "S23" and step in "ABC" and plan_request.get("http") == 200:
        _S23_SNAPSHOTS[state["id"]] = {"reference": p, "frozen": deepcopy(p)}
