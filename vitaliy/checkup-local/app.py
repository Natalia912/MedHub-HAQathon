"""Сервер: страница + API. Запуск: python -m uvicorn app:app --port 8010"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from anketa_fields import FIELDS, STEPS
from api_logic import DEMO, api_morning, api_scenario
from engine import RULES, predict

ROOT = Path(__file__).parent

app = FastAPI(title="Check-up Intelligence")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
def anketa():
    """Анкета — форма Натальи в стиле Green Clinic (static/anketa)."""
    return FileResponse(ROOT / "static" / "anketa" / "index.html")


@app.get("/app")
def index():
    """Программа, согласие, подготовка, куратор, утро клиники, карта здоровья, 12 пациентов."""
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/fields")
def fields():
    return FIELDS


@app.get("/steps")
def steps():
    return STEPS


@app.get("/rules")
def rules():
    return RULES


@app.post("/api/predict")
def api_predict(patient: dict):
    return predict(patient)


@app.get("/api/samples")
def api_samples():
    return DEMO


@app.get("/api/sources")
def api_sources():
    return RULES["_sources"]


@app.get("/api/catalog")
def api_catalog():
    return RULES["prime_catalog"]


@app.get("/api/consent")
def api_consent():
    return RULES["consent_catalog"]


@app.post("/api/morning")
def morning_route(body: dict):
    return api_morning(body)


@app.post("/api/scenario")
def scenario_route(body: dict):
    return api_scenario(body)
