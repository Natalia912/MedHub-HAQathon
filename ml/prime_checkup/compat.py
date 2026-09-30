"""Legacy predict calls the real engine; no replay cache."""
from .engine import build_plan


def predict(patient: dict) -> dict:
    return build_plan(patient)


if __name__ == "__main__":
    from .engine import load_data

    expected = ["ready", "ready", "ready", "needs_input", "review", "ready"]
    for example, status in zip(load_data("examples.json"), expected):
        assert predict(example["input"])["status"] == status
    print("Демонстрационный контракт: 6 профилей проверены.")
