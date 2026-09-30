"""Synthetic patient factories preserved from the local tester regression."""

def clinic(**changes):
    value = {
        "input_version": "clinic_v1", "for_child": False, "sex": "M",
        "birth_date": "1988-01-10", "urgent": "none", "conditions": ["none"], "registered": ["none"],
        "smoke_status": "never", "as_of_date": "2026-09-30", "checkup_year": 2026,
        "visit_date": "2026-10-01", "availability": "normal",
    }
    value.update(changes)
    return value
