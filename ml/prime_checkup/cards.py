"""Fixed fictional result states; independent of questionnaire and selection."""
from copy import deepcopy

from .engine import load_data

COMPLETED_CASES = ("waiting", "received", "reviewed")


def get_completed_case(case: str = "waiting") -> dict:
    if case not in COMPLETED_CASES:
        raise ValueError("Неизвестный вымышленный вариант карты; допустимы waiting, received, reviewed.")
    fixture = load_data("completed.json")
    return deepcopy({"history": fixture["history"], **fixture["cases"][case]})
