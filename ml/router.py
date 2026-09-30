"""HTTP-обёртка движка. Подключение в app/main.py (две строки):

    from ml.router import router
    app.include_router(router)
"""
from fastapi import APIRouter

from ml.engine import catalog, plan, predict

router = APIRouter()


@router.post("/recommend")
def recommend(inp: dict):
    """Анкета -> пакет PRIME + бесплатный госскрининг + маршрут (spec/CONTRACT.md)."""
    return predict(inp)


@router.post("/plan")
def make_plan(body: dict):
    """{"input": анкета, "selected": [обследования]} -> маршрут дня и подготовка для выбранного набора."""
    return plan(body.get("input") or {}, body.get("selected") or [])


@router.get("/catalog")
def get_catalog():
    """Все обследования PRIME для «собрать свой пакет»."""
    return catalog()
