"""Standalone JSON service; importing it never starts a server."""
from fastapi import FastAPI

from .router import router

app = FastAPI(title="PRIME — тестовый процедурный конструктор", version="demo-3")
app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok", "demo": True, "medical_validated": False, "engine": "demo-3"}
